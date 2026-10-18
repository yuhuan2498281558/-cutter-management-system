// Run from web: node --test src/views/ai-assistant/__tests__/answer-parsing.test.cjs
// Characterization tests for AnalysisMessage.vue parsing: column widths, numeric columns,
// legacy sections and paragraph merging. They lock today's output before the parser moves.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');

const transpile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText;
const plain = value => JSON.parse(JSON.stringify(value));
const componentPath = path.resolve(__dirname, '../components/AnalysisMessage.vue');

function loadConstants() {
  const context = { exports: {} };
  vm.runInNewContext(transpile(fs.readFileSync(path.resolve(__dirname, '../constants.ts'), 'utf8')), context);
  return context.exports;
}

function loadParser(props = { content: '' }) {
  const constants = loadConstants();
  const context = { exports: {}, defineProps: () => props };
  context.require = name => {
    if (name === 'vue') return vue;
    if (name === '../constants') return constants;
    throw new Error(`Unexpected import: ${name}`);
  };
  const source = fs.readFileSync(componentPath, 'utf8').match(/<script[^>]*>([\s\S]*?)<\/script>/)[1]
    + '\nexports.parser = { parseMarkdown, parseAnalysisMessage, isNumericColumn, tableColumnWidth, tableMinWidth, tableColumnStyle, splitSingleItem, renderInline, markdownBlocks, hasMarkdown, parsed };';
  vm.runInNewContext(transpile(source), context);
  return context.exports.parser;
}

async function render(content) {
  const { renderToString } = require('@vue/server-renderer');
  const template = require('@vue/compiler-sfc').parse(fs.readFileSync(componentPath, 'utf8')).descriptor.template.content;
  const bindings = { ...loadParser({ content }), content };
  // Drop SSR fragment markers so the assertions read like the browser DOM.
  return (await renderToString(vue.createSSRApp({ template, setup: () => bindings }))).replace(/<!--[[\]]-->/g, '');
}

test('column widths come from the header only, in the order wide text, description, numeric, short label, default', () => {
  const h = loadParser();
  for (const [header, width] of [
    ['各地层关联次数', 600],
    ['主要磨损类型', 400], ['依据与限制', 400], ['处理建议', 400], ['备注', 400], ['更换次数说明', 400],
    ['更换次数', 112], ['平均服役（环）', 115], ['地层标签关联次数', 128], ['折合每环价格（元/环）', 167], ['平均检查一把刀时长（分钟）', 168],
    ['刀位', 72], ['序号', 72], ['排名', 72],
    ['刀具类型', 128], ['刀型', 128], ['磨损状态', 128], ['状态', 128], ['地层类型', 128],
    ['刀位号', 180], ['刀具编号', 180], ['厂家名称', 180], ['异常环段', 180], ['数量来源', 180],
  ]) assert.equal(h.tableColumnWidth(header), width, header);
});

test('table width is the sum of column widths and each col gets a fixed pixel width', () => {
  const h = loadParser();
  const headers = ['刀位', '更换次数', '主要磨损类型'];
  assert.equal(h.tableMinWidth(headers), 584);
  assert.deepEqual(plain(headers.map((_header, index) => h.tableColumnStyle(headers, index))), [{ width: '72px' }, { width: '112px' }, { width: '400px' }]);
});

test('numeric and short columns widen to their longest cell, text columns keep the header width', async () => {
  const h = loadParser();
  assert.equal(h.tableColumnWidth('异常率', ['33.1%（39/118）', '**41.8%（51/122）**']), 146);
  assert.equal(h.tableColumnWidth('异常率', ['12.5%']), 112);
  assert.equal(h.tableColumnWidth('刀位', ['S19L（3次）']), 111);
  assert.equal(h.tableColumnWidth('异常率', ['41.8%（51/122，其中 3 把未检查，另有 2 把待复核）']), 220);
  assert.equal(h.tableColumnWidth('高频刀位', ['11、13、1、12、14、10、S1L、S2R、S3L']), 180);
  const html = await render('| 环号 | 异常率 |\n| --- | --- |\n| 400 | **41.8%（51/122）** |');
  assert.match(html, /<div class="markdown-table-wrap" style="width:328px;"/);
  assert.match(html, /<col style="width:180px;"><col style="width:146px;">/);
});

test('the rendered table wrapper is two pixels wider than the table and cols use header widths', async () => {
  const html = await render('| 刀位 | 更换次数 | 主要磨损类型 |\n| --- | --- | --- |\n| S1L | 2 | 偏磨 |');
  assert.match(html, /<div class="markdown-table-wrap" style="width:586px;"/);
  assert.match(html, /<table class="markdown-table" style="min-width:584px;">/);
  assert.match(html, /<col style="width:72px;"><col style="width:112px;"><col style="width:400px;">/);
});

test('numeric columns cover averages, intervals, durations and money while exclusions win', () => {
  const h = loadParser();
  for (const header of ['均值', '平均', '中位数（环）', '最小值(kN)', '开仓间隔（环）', '开仓时长（h）', '推进距离（m）', '费用（元）', '金额', '单价（元）', '样本量', '异常数', '检查（把）']) {
    assert.equal(h.isNumericColumn(header), true, header);
  }
  for (const header of ['', '平均磨损', '更换次数来源', '刀具名称', '最短 / 最长（环）', '异常环段', '分析范围']) {
    assert.equal(h.isNumericColumn(header), false, header);
  }
});

test('legacy section answers split by the real section titles and keep kinds, lead and bullets', () => {
  const h = loadParser();
  const content = '本次分析基于最近100环\n结论：需要复核\n关键依据\n• 更换数量增加\n• 异常率上升\n数据依据: 共12条记录\n关键发现：\n注意事项/建议：复核S1L\n注意事项：\n建议\n- 增加备刀';
  assert.deepEqual(plain(h.parseAnalysisMessage(content)), {
    lead: '本次分析基于最近100环',
    sections: [
      { title: '结论', kind: 'conclusion', items: ['需要复核'] },
      { title: '关键依据', kind: 'evidence', items: ['更换数量增加', '异常率上升'] },
      { title: '数据依据', kind: 'evidence', items: ['共12条记录'] },
      { title: '注意事项/建议', kind: 'warning', items: ['复核S1L'] },
      { title: '建议', kind: 'suggestion', items: ['增加备刀'] },
    ],
  });
  assert.equal(h.splitSingleItem('- 第一行\n\n • 第二行 '), '第一行\n第二行');
});

test('legacy sections render as titled blocks only when the answer has no Markdown', async () => {
  const content = '本次分析基于最近100环\n结论：需要复核\n关键依据\n• 更换数量增加\n• 异常率上升';
  const h = loadParser({ content });
  assert.equal(h.hasMarkdown.value, false);
  const html = await render(content);
  assert.match(html, /<p class="analysis-lead">本次分析基于最近100环<\/p>/);
  assert.match(html, /<div class="analysis-section conclusion"><div class="analysis-section-title">结论<\/div><p class="section-single-p">需要复核<\/p><\/div>/);
  assert.match(html, /<div class="analysis-section evidence"><div class="analysis-section-title">关键依据<\/div><ul class="section-list"><li>更换数量增加<\/li><li>异常率上升<\/li><\/ul><\/div>/);
  assert.equal(loadParser({ content: '结论：需要复核\n- 增加备刀' }).hasMarkdown.value, true, 'a Markdown list switches to Markdown rendering');
  assert.match(await render('只有一段普通回答\n第二行'), /<div class="plain-answer">只有一段普通回答\n第二行<\/div>/);
});

test('consecutive lines merge into one paragraph until a blank line or a block start', () => {
  const h = loadParser();
  const blocks = content => plain(h.parseMarkdown(content)).map(block => [block.type, block.text ?? block.items ?? block.headers ?? '']);
  assert.deepEqual(blocks('  第一行\n第二行  \n\n第三行'), [['paragraph', '第一行\n第二行'], ['paragraph', '第三行']]);
  assert.deepEqual(blocks('说明\n## 小结'), [['paragraph', '说明'], ['heading', '小结']]);
  assert.deepEqual(blocks('说明\n---'), [['paragraph', '说明'], ['divider', '']]);
  assert.deepEqual(blocks('说明\n- 复核'), [['paragraph', '说明'], ['list', ['复核']]]);
  assert.deepEqual(blocks('说明\n2) 复核'), [['paragraph', '说明'], ['list', ['复核']]]);
  assert.deepEqual(blocks('说明\n刀位 | 数量\n--- | ---\nS1L | 2'), [['paragraph', '说明'], ['table', ['刀位', '数量']]]);
  assert.deepEqual(blocks('刀位 | 数量\n仍是正文'), [['paragraph', '刀位 | 数量\n仍是正文']]);
  assert.deepEqual(blocks('说明 **加粗**\n`S1L` 续行'), [['paragraph', '说明 **加粗**\n`S1L` 续行']]);
});

test('note paragraphs keep their muted style and headings keep their level', async () => {
  const content = '## 换刀统计\n\n统计口径：已确认更换\n\n正文说明';
  assert.deepEqual(plain(loadParser().parseMarkdown(content))[0], { type: 'heading', level: 2, text: '换刀统计' });
  const html = await render(content);
  // SSR leaves v-html on <component :is> empty, so only the heading tag and class are checked here.
  assert.match(html, /<h2 class="markdown-heading level-2">/);
  assert.match(html, /<p class="(?=[^"]*\banswer-note\b)(?=[^"]*\bmarkdown-paragraph\b)[^"]*">统计口径：已确认更换<\/p>/);
  assert.match(html, /<p class="markdown-paragraph">正文说明<\/p>/);
});

test('待复核线索 sections share the 建议 style and 数据范围和限制 is recognised as a section', () => {
  const h = loadParser();
  assert.deepEqual(plain(h.parseAnalysisMessage('结论：S1L 异常集中\n待复核线索\n• 复核第120环开仓记录\n数据范围和限制：只覆盖第100–300环')).sections, [
    { title: '结论', kind: 'conclusion', items: ['S1L 异常集中'] },
    { title: '待复核线索', kind: 'suggestion', items: ['复核第120环开仓记录'] },
    { title: '数据范围和限制', kind: 'default', items: ['只覆盖第100–300环'] },
  ]);
});
