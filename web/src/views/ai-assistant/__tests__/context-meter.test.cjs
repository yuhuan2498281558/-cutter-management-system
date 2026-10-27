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
  const emitted = [];
  const context = { exports: {}, defineProps: () => props, defineEmits: () => name => emitted.push(name) };
  context.require = name => {
    if (name === 'vue') return vue;
    throw new Error(`Unexpected import: ${name}`);
  };
  const source = fs.readFileSync(componentPath, 'utf8').match(/<script[^>]*>([\s\S]*?)<\/script>/)[1]
    + '\nexports.meter = { formatTokens, usedPercent, level, tooltipLines, rows, barRows, triggerShare, pagingNote, compactNote, autoCompaction, historyNote, billingLine, compactionLine, canCompact, requestCompact, panelOpen };';
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText, context);
  return { props, emitted, ...context.exports.meter };
}

const plain = value => JSON.parse(JSON.stringify(value));
const memory = { backend: 'legacy', recent_turns: null, recent_budget: null, recent_tokens: 1800, included_turns: 2, summary_tokens: 0, summary_trigger_tokens: null, pending_tokens: null };
// A schema 2 turn as the backend sends it: 256k window, trigger at 80%, hard input limit 243712.
const turn = (used, overrides = {}) => ({
  kind: 'turn', schema_version: 2, measurement: 'estimated', estimated: true,
  window: 256000, input_budget: 243712, hard_input_limit: 243712, trigger_tokens: 204800,
  output_reserve: 8192, safety_margin: 4096, used, exceeded: false,
  parts: { system: 4000, tools: 8500, memory: 1800, question: 100, results: used - 14430, other: 30 },
  results_raw: 30000, compacted_results: 1, summarized_results: 0, model_calls: 2,
  thresholds: { compaction_min_tokens: 1000 }, memory,
  history: { turns: 2, tool_results: 3, legacy_qa_turns: 0, other_project_turns: 0, tokens: 1800 },
  provider_usage: null, last_prompt_tokens_actual: null,
  compaction: { state: 'none', checkpoints: 0, pruned_results: 0, last_at: null, last_before: null, last_after: null },
  ...overrides,
});

test('the ring is the share of the whole window; it warns at 75% of the trigger line and turns red at the trigger', () => {
  for (const [used, percent, level] of [[25600, 10, 'normal'], [153600, 60, 'warning'], [204800, 80, 'danger']]) {
    const m = loadMeter(turn(used));
    assert.equal(m.usedPercent.value, percent);
    assert.equal(m.level.value, level, `${used}`);
  }
  assert.equal(loadMeter(turn(30000, { exceeded: true })).level.value, 'danger');
});

test('an older backend without a trigger line keeps the 70% / 90% share of the input budget', () => {
  const old = { ...turn(9442), schema_version: undefined, trigger_tokens: undefined, hard_input_limit: undefined, window: 16384, input_budget: 13312 };
  const m = loadMeter(old);
  assert.equal(m.usedPercent.value, 71);
  assert.equal(m.level.value, 'warning');
  assert.equal(m.triggerShare.value, null);
});

test('token counts read as 541, 1k, 1.2k and 24k', () => {
  const { formatTokens } = loadMeter(null);
  assert.deepEqual([541, 1000, 1200, 24000, null].map(formatTokens), ['541', '1k', '1.2k', '24k', '—']);
});

test('rule answers and missing data show a grey ring with a plain explanation', () => {
  const rule = loadMeter({ ...turn(20000), kind: 'rule', used: null, parts: null });
  assert.equal(rule.level.value, 'idle');
  assert.deepEqual(Array.from(rule.tooltipLines.value), ['直连查库不调用模型，不占模型上下文']);
  const none = loadMeter(null);
  assert.equal(none.level.value, 'idle');
  assert.deepEqual(Array.from(none.tooltipLines.value), ['上下文用量：还没有数据']);
});

test('the breakdown lists the used parts with the history note, then what is left and the reserve, filling the window bar', () => {
  const m = loadMeter(turn(20000));
  assert.deepEqual(plain(m.rows.value.map(row => [row.label, row.value, row.note])), [
    ['系统提示', 4000, ''], ['工具说明', 8500, ''], ['对话历史', 1800, '2 轮 · 3 个查询结果'], ['本次问题', 100, ''],
    ['本轮查询结果', 5570, '原 30k'], ['其他开销', 30, ''], ['剩余', 223712, ''], ['预留回答 + 余量', 12288, ''],
  ]);
  const share = m.barRows.value.reduce((sum, row) => sum + row.share, 0);
  assert.ok(Math.abs(share - 100) < 1e-9, `bar covers the whole window, got ${share}`);
  assert.equal(m.triggerShare.value, 80);
  assert.deepEqual(Array.from(m.tooltipLines.value), ['本轮模型上下文（估算）', '已用 20k / 256k · 8%']);
});

test('a measured total keeps the estimated proportions but the rows add up to the measured value', () => {
  const m = loadMeter(turn(20000, { measurement: 'actual', used: 22000 }));
  const used = m.rows.value.filter(row => !['free', 'reserve'].includes(row.key)).reduce((sum, row) => sum + row.value, 0);
  assert.ok(Math.abs(used - 22000) <= 3, `parts add up to the measured total, got ${used}`);
  assert.equal(m.rows.value.find(row => row.key === 'free').value, 243712 - 22000);
  assert.equal(m.tooltipLines.value[0], '本轮模型上下文（实测）');
});

test('without automatic compaction the panel states the hard limit; with it the warning names the trigger line', () => {
  assert.equal(loadMeter(turn(160000)).autoCompaction.value, false);
  assert.equal(loadMeter(turn(160000)).tooltipLines.value[2], '接近上限，大范围查询可能超出');
  const auto = loadMeter(turn(160000, { compaction: { ...turn(0).compaction, auto: true } }));
  assert.equal(auto.autoCompaction.value, true);
  assert.equal(auto.tooltipLines.value[2], '接近 204.8k，到了会自动整理早前对话');
  const due = loadMeter(turn(210000, { compaction: { ...turn(0).compaction, auto: true } }));
  assert.equal(due.tooltipLines.value[2], '下一问会先整理早前对话');
});

test('provider billing, older or other-project turns, paging and compaction counts are reported only when present', () => {
  const m = loadMeter(turn(20000, {
    provider_usage: { prompt_tokens: 30000, completion_tokens: 480, cache_hit_tokens: 24000 },
    history: { turns: 4, tool_results: 3, legacy_qa_turns: 2, other_project_turns: 1, tokens: 1800 },
    paged_lists: 2, page_requests: 1,
  }));
  assert.equal(m.billingLine.value, '本轮接口计费：输入 30k（缓存命中 24k） · 输出 480');
  assert.equal(m.historyNote.value, '（1 轮属于其他项目、2 轮是改版前的记录，只带问答文字）');
  assert.equal(m.pagingNote.value, '（本轮分页 2 处，翻页 1 次）');
  assert.equal(m.compactNote.value, '（本轮 1 条）');
  const bare = loadMeter(turn(20000, { compacted_results: 0, paged_lists: undefined }));
  assert.equal(bare.billingLine.value, '');
  assert.equal(bare.historyNote.value, '');
  assert.equal(bare.pagingNote.value, '');
  assert.equal(bare.compactNote.value, '');
  assert.equal(loadMeter({ ...turn(20000), kind: 'baseline', provider_usage: { prompt_tokens: 1, completion_tokens: 1, cache_hit_tokens: 0 } }).billingLine.value, '');
});

test('the compact button appears only when the backend offers it and there is history to compact', () => {
  const manual = { ...turn(0).compaction, manual: true };
  assert.equal(loadMeter(turn(20000)).canCompact.value, false);
  assert.equal(loadMeter(turn(20000, { compaction: manual, history: { ...turn(0).history, turns: 1 } })).canCompact.value, false);
  const m = loadMeter(turn(20000, { compaction: manual }));
  assert.equal(m.canCompact.value, true);
  m.panelOpen.value = true;
  m.requestCompact();
  assert.equal(m.panelOpen.value, false);
  assert.deepEqual(m.emitted, ['compact']);
});

test('the last compaction is reported as before and after sizes only once it happened', () => {
  assert.equal(loadMeter(turn(20000)).compactionLine.value, '');
  const done = loadMeter(turn(20000, { compaction: { ...turn(0).compaction, checkpoints: 1, last_before: 210000, last_after: 41000 } }));
  assert.equal(done.compactionLine.value, '早前对话已整理：210k → 41k');
});
