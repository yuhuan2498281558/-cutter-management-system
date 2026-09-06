// Execute the actual component setup/parser with Vue computed values, no browser or model.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');

function loadComponent(file, props, exports) {
  const context = { exports: {}, defineProps: () => props, defineEmits: () => () => {}, defineExpose() {} };
  context.require = name => {
    if (name === 'vue') return { ...vue, onUnmounted() {} };
    if (name === '../constants') return { SECTION_TITLES: ['结论', '关键依据', '注意事项'], quickQuestionGroups: [] };
    if (name === 'element-plus') return { ElMessage: {} };
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
