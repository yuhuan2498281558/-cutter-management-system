// Execute the actual component setup/parser with Vue computed values, no browser or model.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');

function loadComponent(file, props, exports, environment = {}) {
  const context = { exports: {}, defineProps: () => props, defineEmits: () => () => {}, defineExpose() {}, ...environment };
  context.require = name => {
    if (name === 'vue') return { ...vue, onUnmounted() {} };
    if (name === '../constants') return { SECTION_TITLES: ['结论', '关键依据', '注意事项'], quickQuestionGroups: [] };
    if (name === 'element-plus') return { ElMessage: { success() {}, error() {} } };
    if (name === '@element-plus/icons-vue' || name.endsWith('.vue')) return {};
    throw new Error(`Unexpected import: ${name}`);
  };
  const source = fs.readFileSync(path.resolve(__dirname, '../components/', file), 'utf8').match(/<script[^>]*>([\s\S]*?)<\/script>/)[1] + `\nexports.component = { ${exports} };`;
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText, context);
  return context.exports.component;
}

for (const [content, block] of [
  ['- 检查刀位\n- 复核磨损', 'list'],
  ['1. 检查刀位\n2. 复核磨损', 'list'],
  ['刀位 | 数量\n--- | ---\nS1L | 2', 'table'],
  ['| 刀位 | 数量 |\n| --- | --- |\n| S1L | 2 |', 'table'],
  ['## 工程结论', 'heading'],
  ['---', 'divider'],
]) {
  test(`standalone ${block} uses Markdown rendering without requiring a heading or bold text`, () => {
    const h = loadComponent('AnalysisMessage.vue', { content }, 'hasMarkdown, markdownBlocks, renderInline');
    assert.equal(h.hasMarkdown.value, true);
    assert.equal(h.markdownBlocks.value[0].type, block);
  });
}

test('inline code is rendered and raw HTML is escaped before controlled tags are generated', () => {
  const h = loadComponent('AnalysisMessage.vue', { content: '复核刀位 `S1L`' }, 'hasMarkdown, renderInline');
  assert.equal(h.hasMarkdown.value, true);
  assert.equal(h.renderInline('复核刀位 `S1L`'), '复核刀位 <code>S1L</code>');
  const output = h.renderInline('**结论** <img src=x onerror=alert(1)> `<script>alert(1)</script>`');
  assert.match(output, /<strong>结论<\/strong>/);
  assert.match(output, /&lt;img/);
  assert.match(output, /<code>&lt;script&gt;/);
  assert.equal(/<(img|script)\b/.test(output), false);
});

test('plain legacy section answers retain existing section rendering', () => {
  const h = loadComponent('AnalysisMessage.vue', { content: '结论：需要复核\n关键依据：换刀数量增加' }, 'hasMarkdown, parsed');
  assert.equal(h.hasMarkdown.value, false); assert.equal(h.parsed.value.sections.length, 2);
});

test('rule table preserves escaped separators, literal slashes, zero and missing values', () => {
  const content = '## 开仓记录\n\n| 刀位 | 次数 |\n| --- | --- |\n| A\\|B\\\\C | 0 |\n| S1L | 暂无 |';
  const h = loadComponent('AnalysisMessage.vue', { content }, 'markdownBlocks, isNumericColumn');
  const table = h.markdownBlocks.value.find(block => block.type === 'table');
  assert.deepEqual(Array.from(table.rows[0]), ['A|B\\C', '0']);
  assert.deepEqual(Array.from(table.rows[1]), ['S1L', '暂无']);
  assert.equal(h.isNumericColumn('更换（把）'), true);
  assert.equal(h.isNumericColumn('数量来源'), false);
});

test('prepending history keeps the old content at the same visual position', () => {
  const h = loadComponent('ChatMessageList.vue', { messages: [], isGenerating: false }, 'containerRef, captureScrollPosition, restoreScrollPosition, isNearBottom');
  const element = { scrollTop: 30, scrollHeight: 1000, clientHeight: 400 };
  h.containerRef.value = element;
  const position = h.captureScrollPosition();
  element.scrollHeight = 1700; h.restoreScrollPosition(position);
  assert.equal(element.scrollTop, 730); assert.equal(h.isNearBottom.value, false);
});

test('shortcut uses a current S-series cutter position rather than retired G-series', () => {
  const context = { exports: {} };
  const source = fs.readFileSync(path.resolve(__dirname, '../constants.ts'), 'utf8');
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, context);
  const query = context.exports.quickQuestionGroups.find(group => group.title === '刀位统计').items.find(item => item.label === '指定刀位').query;
  assert.equal(query, '分析S1L刀位的换刀和磨损情况');
});

for (const [label, content] of [
  ['extra cell', '| 厂家 | 更换次数 |\n| --- | --- |\n| A厂家 | 2 | 不得丢失的异常说明 |'],
  ['missing cell', '| 厂家 | 更换次数 | 异常率 |\n| --- | --- | --- |\n| A厂家 | 2 |'],
  ['separator width mismatch', '| 厂家 | 更换次数 |\n| --- | --- | --- |\n| A厂家 | 2 |'],
]) {
  test(`malformed table (${label}) retains its entire source with a concise warning`, () => {
    const h = loadComponent('AnalysisMessage.vue', { content, streaming: false }, 'markdownBlocks, hasMarkdown');
    const block = h.markdownBlocks.value[0];
    assert.equal(block.type, 'raw'); assert.equal(block.text, content);
    assert.match(block.note, /列数不一致/); assert.equal(h.hasMarkdown.value, true);
  });
}

test('a partial streaming table has no permanent format error and recovers when the row completes', () => {
  const props = vue.reactive({ content: '| 厂家 | 更换次数 |\n| --- | --- |\n| A厂家', streaming: true });
  const h = loadComponent('AnalysisMessage.vue', props, 'markdownBlocks');
  assert.equal(h.markdownBlocks.value[0].type, 'table'); assert.equal(h.markdownBlocks.value[0].rows.length, 0);
  props.content += ' | 0 |\n';
  assert.equal(h.markdownBlocks.value[0].type, 'table');
  assert.deepEqual(Array.from(h.markdownBlocks.value[0].rows[0]), ['A厂家', '0']);
  props.streaming = false; assert.equal(h.markdownBlocks.value[0].type, 'table');
});

test('an unfinished table gets a format note only once streaming ends and preserves unsafe source as text', () => {
  const props = vue.reactive({ content: '| 厂家 | 数量 |\n| --- | --- |\n| <img src=x onerror=alert(1)> | 0 | 多列 |', streaming: true });
  const h = loadComponent('AnalysisMessage.vue', props, 'markdownBlocks');
  assert.equal(h.markdownBlocks.value[0].note, undefined);
  props.streaming = false;
  assert.match(h.markdownBlocks.value[0].note, /已保留原文/);
  assert.equal(h.markdownBlocks.value[0].text, props.content);
});

test('ordered list starting at 3 retains its source start number and flat item content', () => {
  const h = loadComponent('AnalysisMessage.vue', { content: '3. 复核厂家反馈\n4. 对比异常率' }, 'markdownBlocks');
  const block = h.markdownBlocks.value[0];
  assert.equal(block.type, 'list'); assert.equal(block.ordered, true); assert.equal(block.start, 3);
  assert.deepEqual(Array.from(block.items), ['复核厂家反馈', '对比异常率']);
});

for (const content of [
  '- 风险刀位\n  - S1L异常磨损\n  - S2R正常\n- 复核地层',
  '3. 厂家表现\n   1. 异常率\n      - 样本不足\n4. 地层条件',
  '- 结论\n  这行是同一条的补充依据\n- 建议',
  '- 父项\n\n  - 子项\n- 下一父项',
  '  - 带缩进的列表片段\n  - 保留原始归属层级',
]) {
  test('unsupported nested list structure preserves all indentation and numbering in original text', () => {
    const h = loadComponent('AnalysisMessage.vue', { content }, 'markdownBlocks');
    assert.equal(h.markdownBlocks.value.length, 1);
    assert.equal(h.markdownBlocks.value[0].type, 'raw');
    assert.equal(h.markdownBlocks.value[0].text, content);
  });
}

test('new report measurements align numerically while descriptive headers remain text', () => {
  const h = loadComponent('AnalysisMessage.vue', { content: '' }, 'isNumericColumn');
  for (const header of ['更换次数', '异常率', '平均寿命（环）', '环数', '占比', '推力（kN）', '扭矩（kN·m）', '转速（rpm）', '贯入度（mm/r）', '成本（元）', '样本数', '平均值', '最小值', '最大（kN）']) assert.equal(h.isNumericColumn(header), true, header);
  for (const header of ['厂家名称', '地层类型', '刀具类型', '数量来源', '分析范围', '异常环段']) assert.equal(h.isNumericColumn(header), false, header);
  for (const header of ['关联观测数', '换刀观测数', '记录平均价格（元）', '安装数', '完成服役数', '在役数', '平均服役（环）', '服役（环）', '折合每环价格（元/环）', '地层标签关联次数', '采样点数']) assert.equal(h.isNumericColumn(header), true, header);
  for (const header of ['各地层关联次数', '最短/最长（环）', '起止时间', '状态', '依据与限制', '刀具编号', '刀位']) assert.equal(h.isNumericColumn(header), false, header);
});

test('the actual template aligns a first-column count numerically while keeping labels textual', async () => {
  const { renderToString } = require('@vue/server-renderer');
  const content = '| 观测记录数 | 刀位 |\n| --- | --- |\n| 12 | S1L |';
  const bindings = loadComponent('AnalysisMessage.vue', { content }, 'hasMarkdown, markdownBlocks, renderInline, isNumericColumn, tableMinWidth, tableColumnStyle, parsed, splitSingleItem');
  const source = fs.readFileSync(path.resolve(__dirname, '../components/AnalysisMessage.vue'), 'utf8');
  const template = require('@vue/compiler-sfc').parse(source).descriptor.template.content;
  const html = await renderToString(vue.createSSRApp({ template, setup: () => bindings }));
  assert.match(html, /<th class="numeric" scope="col">观测记录数<\/th>/);
  assert.match(html, /<td class="numeric">12<\/td>/);
  assert.match(html, /<th class="" scope="col">刀位<\/th>/);
  assert.match(html, /<td class="">S1L<\/td>/);
});

test('copying a completed answer preserves scope, definitions and Markdown exactly', async () => {
  const copied = [];
  const h = loadComponent('ChatMessageList.vue', { messages: [] }, 'handleCopy', { navigator: { clipboard: { writeText: async text => copied.push(text) } } });
  const content = '分析范围：100-300环\n统计口径：已确认更换\n\n| 厂家 | 次数 |\n| --- | --- |\n| A | 0 |';
  await h.handleCopy({ content });
  assert.deepEqual(copied, [content]);
});

test('copying stopped/failed answers retains integrity notices and the original answer body', async () => {
  const copied = [];
  const h = loadComponent('ChatMessageList.vue', { messages: [] }, 'handleCopy', { navigator: { clipboard: { writeText: async text => copied.push(text) } } });
  const content = '分析范围：100-300环\n统计口径：已确认更换\n尚未写完的结论';
  await h.handleCopy({ content, aborted: true });
  await h.handleCopy({ content, rawError: true });
  assert.equal(copied[0], `回答已中止，内容不完整\n\n${content}`);
  assert.equal(copied[1], `查询未完成或失败，以下内容仅供核对\n\n${content}`);
});
