// Run from web: node --test src/views/ai-assistant/__tests__/context-meter.test.cjs
// Run the actual ContextMeter setup against hand-built ContextInfo values; no browser or backend.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');

const componentPath = path.resolve(__dirname, '../components/ContextMeter.vue');

function loadMeter(info) {
  const props = vue.reactive({ info });
  const context = { exports: {}, defineProps: () => props };
  context.require = name => {
    if (name === 'vue') return vue;
    throw new Error(`Unexpected import: ${name}`);
  };
  const source = fs.readFileSync(componentPath, 'utf8').match(/<script[^>]*>([\s\S]*?)<\/script>/)[1]
    + '\nexports.meter = { formatTokens, usedPercent, level, tooltipLines, rows, barRows, pagingNote, compactNote, softLimitReachable, memoryNote };';
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText, context);
  return { props, ...context.exports.meter };
}

const legacyMemory = { backend: 'legacy', recent_turns: 3, recent_budget: 1200, recent_tokens: 870, included_turns: 2, summary_tokens: 0, summary_trigger_tokens: null, pending_tokens: null };
const turn = (used, overrides = {}) => ({
  kind: 'turn', estimated: true, window: 16384, input_budget: 13312, output_reserve: 2048, safety_margin: 1024,
  used, exceeded: false,
  parts: { system: 2100, tools: 3000, memory: 870, question: 100, results: used - 6100, other: 30 },
  results_raw: 8500, compacted_results: 1, summarized_results: 0, model_calls: 3,
  thresholds: { compaction_min_tokens: 1000, evidence_soft_tokens: 24000 },
  memory: legacyMemory,
  ...overrides,
});

test('the ring percentage is the used share of the input budget, with warning at 70% and danger at 90%', () => {
  for (const [used, percent, level] of [[6656, 50, 'normal'], [9442, 71, 'warning'], [12000, 90, 'danger']]) {
    const m = loadMeter(turn(used));
    assert.equal(m.usedPercent.value, percent);
    assert.equal(m.level.value, level, `${used}`);
  }
  assert.equal(loadMeter(turn(9442, { exceeded: true })).level.value, 'danger');
});

test('rule answers and missing data show a grey ring with a plain explanation', () => {
  const rule = loadMeter({ ...turn(5000), kind: 'rule', used: null, parts: null });
  assert.equal(rule.level.value, 'idle');
  assert.deepEqual(Array.from(rule.tooltipLines.value), ['直连查库不调用模型，不占模型上下文']);
  const none = loadMeter(null);
  assert.equal(none.level.value, 'idle');
  assert.deepEqual(Array.from(none.tooltipLines.value), ['上下文用量：还没有数据']);
});

test('the breakdown lists the used parts, then what is left and the reserve, and fills the window bar', () => {
  const m = loadMeter(turn(9442));
  const rows = JSON.parse(JSON.stringify(m.rows.value.map(row => [row.label, row.value, row.note])));
  assert.deepEqual(rows, [
    ['系统提示', 2100, ''], ['工具说明', 3000, ''], ['对话记忆', 870, '最近 2 轮'], ['本次问题', 100, ''],
    ['查询结果', 3342, '原 8.5k'], ['其他开销', 30, ''], ['剩余', 3870, ''], ['预留回答 + 余量', 3072, ''],
  ]);
  const share = m.barRows.value.reduce((sum, row) => sum + row.share, 0);
  assert.ok(Math.abs(share - 100) < 1e-9, `bar covers the whole window, got ${share}`);
  assert.deepEqual(Array.from(m.tooltipLines.value), ['本轮模型上下文（估算）', '已用 9.4k / 13.3k · 71%', '接近上限，大范围查询可能超出']);
});

test('the rules show this turn\'s paging and compaction counts and hide an unreachable soft limit', () => {
  const m = loadMeter(turn(9442, { paged_lists: 2, page_requests: 1 }));
  assert.equal(m.pagingNote.value, '（本轮分页 2 处，翻页 1 次）');
  assert.equal(m.compactNote.value, '（本轮 1 条）');
  assert.equal(m.softLimitReachable.value, false);
  const wide = loadMeter(turn(9442, { window: 65536, input_budget: 62464, thresholds: { compaction_min_tokens: 1000, evidence_soft_tokens: 24000 } }));
  assert.equal(wide.softLimitReachable.value, true);
  assert.equal(loadMeter(turn(9442)).pagingNote.value, '', 'older backends without paging counts add nothing');
});

test('memory explains the sliding window for legacy memory and the summary trigger for django memory', () => {
  assert.equal(loadMeter(turn(9442)).memoryNote.value, '只带最近 3 轮原文（不超过 1.2k），更早的对话不带入');
  const django = loadMeter(turn(9442, { memory: { ...legacyMemory, backend: 'django', summary_tokens: 300, summary_trigger_tokens: 1800, pending_tokens: 640 } }));
  assert.equal(django.memoryNote.value, '只带最近 3 轮原文（不超过 1.2k）；更早的对话累计 640 / 1.8k，到了自动整理成摘要');
  assert.equal(django.rows.value.find(row => row.label === '对话记忆').note, '最近 2 轮 + 摘要');
});
