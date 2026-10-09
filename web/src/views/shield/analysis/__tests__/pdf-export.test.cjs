// Executes the actual PDF exporter against parsed Element Plus DOM structures.
// xmldom supplies real nodes; the adapter adds only browser selector/element APIs.
// Printing, timers, image readiness and ECharts are controlled boundaries.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { DOMParser, XMLSerializer } = require('@xmldom/xmldom');

const serializer = new XMLSerializer();
const serialize = node => serializer.serializeToString(node);
const elements = node => Array.from(node.childNodes || []).filter(child => child.nodeType === 1);
function descendants(node) {
  return elements(node).flatMap(child => [child, ...descendants(child)]);
}
function matches(node, selector) {
  if (node.nodeType !== 1) return false;
  const tag = selector.match(/^[\w*-]+/)?.[0];
  if (tag && tag !== '*' && node.tagName.toLowerCase() !== tag.toLowerCase()) return false;
  const classes = (node.getAttribute('class') || '').split(/\s+/);
  if ([...selector.matchAll(/\.([\w-]+)/g)].some(match => !classes.includes(match[1]))) return false;
  return [...selector.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)].every(([, name, value]) =>
    node.hasAttribute(name) && (value === undefined || node.getAttribute(name) === value));
}
function queryAll(selector) {
  const selectors = selector.split(',').map(value => value.trim());
  assert(selectors.every(value => !/[ >+~]/.test(value.replace(/\[[^\]]*\]/g, ''))), `Unsupported test selector: ${selector}`);
  return descendants(this).filter(node => selectors.some(value => matches(node, value)));
}
const initialDocument = new DOMParser().parseFromString('<html><body /></html>', 'application/xml');
const elementPrototype = Object.getPrototypeOf(initialDocument.documentElement);
const documentPrototype = Object.getPrototypeOf(initialDocument);
for (const prototype of [elementPrototype, documentPrototype]) {
  prototype.querySelectorAll = queryAll;
  prototype.querySelector = function (selector) { return queryAll.call(this, selector)[0] || null; };
}
elementPrototype.closest = function (selector) {
  for (let node = this; node?.nodeType === 1; node = node.parentNode) if (matches(node, selector)) return node;
  return null;
};
elementPrototype.remove = function () { this.parentNode?.removeChild(this); };
elementPrototype.replaceWith = function (node) { this.parentNode.replaceChild(node, this); };
Object.defineProperties(elementPrototype, {
  children: { configurable: true, get() { return elements(this); } },
  outerHTML: { configurable: true, get() { return serialize(this); } },
  classList: { configurable: true, get() { const node = this; return {
    contains(value) { return (node.getAttribute('class') || '').split(/\s+/).includes(value); },
    add(value) { node.setAttribute('class', [...new Set((node.getAttribute('class') || '').split(/\s+/).filter(Boolean).concat(value))].join(' ')); },
  }; } },
  style: { configurable: true, get() { const node = this; return new Proxy({}, {
    get(_, property) { return Object.fromEntries((node.getAttribute('style') || '').split(';').filter(Boolean).map(item => item.split(':').map(value => value.trim())))[String(property).replace(/[A-Z]/g, value => '-' + value.toLowerCase())] || ''; },
    set(_, property, value) { const name = String(property).replace(/[A-Z]/g, item => '-' + item.toLowerCase()); node.setAttribute('style', `${node.getAttribute('style') || ''};${name}:${value}`); return true; },
  }); } },
});
for (const property of ['className', 'src', 'width', 'height']) {
  const attribute = property === 'className' ? 'class' : property;
  Object.defineProperty(elementPrototype, property, { configurable: true,
    get() { const value = this.getAttribute(attribute); return ['width', 'height'].includes(property) ? Number(value || 0) : value; },
    set(value) { this.setAttribute(attribute, String(value)); },
  });
}
function parse(html) { return new DOMParser().parseFromString(html, 'application/xml'); }
function compile(filename, requireModule, globals = {}) {
  const context = { exports: {}, require: requireModule, ...globals };
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, context, { filename });
  return context.exports;
}
const utils = path.resolve(__dirname, '../utils');
const presentation = compile(path.join(utils, 'presentation.ts'), name => { throw new Error(`Unexpected presentation import ${name}`); });
function harness(markup = '<section class="page"><p>报告</p></section>', options = {}) {
  const document = parse(`<html><body>${markup}</body></html>`);
  const before = serialize(document);
  const notices = [], timers = new Map(), snapshots = [], opened = [];
  let now = 0, timerId = 0, html = '', printed = 0, focused = 0;
  const printDocument = {
    images: options.images || [], fonts: options.fonts,
    write(value) { html = value; }, close() {},
  };
  const printWindow = { document: printDocument, closed: false, focus() { focused++; }, print() { printed++; } };
  const api = compile(path.join(utils, 'pdfExport.ts'), name => {
    if (name === './presentation') return presentation;
    if (name === 'element-plus') return { ElMessage: Object.fromEntries(['error', 'warning', 'success'].map(level => [level, message => notices.push({ level, message })])) };
    if (name === 'echarts') return { getInstanceByDom: node => {
      if (!options.chart) return undefined;
      return {
        getDataURL(params) { snapshots.push({ id: node.getAttribute('_echarts_instance_'), params: JSON.parse(JSON.stringify(params)) }); return `data:image/png;base64,${node.getAttribute('_echarts_instance_')}`; },
        getWidth: () => 900, getHeight: () => 360,
        getOption: () => options.chart,
        setOption() { throw new Error('Export must not mutate the live chart'); },
        dispatchAction() { throw new Error('Export must preserve the live zoom and legend'); },
      };
    } };
    throw new Error(`Unexpected exporter import ${name}`);
  }, {
    document, window: { open(...args) { opened.push(args); return options.blocked ? null : printWindow; } },
    Date: { now: () => now },
    setTimeout(callback, delay) { const id = ++timerId; timers.set(id, { callback, due: now + delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  return {
    document, printWindow, notices, snapshots, opened, timers,
    run(title = '测试报告', sections = '.page', meta = [], tables = []) { return api.exportAnalysisPdf(title, sections, meta, tables); },
    tick(milliseconds = 100) { now += milliseconds; const due = [...timers.entries()].filter(([, item]) => item.due <= now); for (const [id, item] of due) { timers.delete(id); item.callback(); } },
    get html() { return html; }, get output() { return parse(html); },
    get printed() { return printed; }, get focused() { return focused; },
    unchanged() { assert.equal(serialize(document), before, 'Source page DOM was mutated'); },
  };
}
function tableFixture(count = 150, auto = false) {
  const header = '<thead><tr><th rowspan="2">厂家 / 开仓</th><th colspan="3">安装与费用来源</th><th class="gutter" rowspan="2" /></tr><tr><th>金额<span class="caret-wrapper">排序</span></th><th>样本</th><th>说明</th></tr></thead>';
  const rows = Array.from({ length: count }, (_, index) => `<tr><td style="position:sticky;left:0"><button onclick="bad()">厂家-${index} &amp; 开仓-${index}</button></td><td>${index === 0 ? '¥0' : index}</td><td>${index === 1 ? '未记录' : '0'}</td><td><span>装入 N-${index}</span><small class="cell-detail">换下 O-${index}</small></td></tr>`).join('');
  return `<section class="page"><div class="el-card"><div class="el-table" style="max-height:480px;overflow:hidden;width:1800px"><div class="el-table__header-wrapper">${auto ? '' : `<table class="el-table__header" width="1800">${header}</table>`}</div><div class="el-table__body-wrapper" style="height:400px;overflow:auto"><table class="el-table__body" style="width:1800px"><colgroup><col width="180" /><col name="gutter" /></colgroup>${auto ? header : ''}<tbody>${rows}</tbody></table></div><div class="el-table__footer-wrapper"><table class="el-table__footer"><tbody><tr><td colspan="4">汇总 150 条</td></tr></tbody></table></div></div></div></section>`;
}

test('split Element Plus header/body becomes one full 150-row table with grouped headers and static button labels', () => {
  const h = harness(tableFixture());
  assert.equal(h.run(), true);
  const output = h.output;
  const table = output.querySelector('.analysis-print-table');
  assert.equal(output.querySelectorAll('table').length, 1);
  assert.equal(table.querySelectorAll('thead').length, 1);
  assert.equal(table.querySelector('thead').querySelectorAll('tr').length, 2);
  assert.equal(table.querySelector('th').getAttribute('rowspan'), '2');
  assert.equal(table.querySelectorAll('th')[1].getAttribute('colspan'), '3');
  assert.equal(table.querySelector('tbody').querySelectorAll('tr').length, 150);
  assert.equal(table.querySelector('tfoot').textContent, '汇总 150 条');
  assert.equal(table.querySelectorAll('button, a, .gutter, .caret-wrapper').length, 0);
  assert.equal(output.querySelectorAll('.el-table, .el-table__body-wrapper').length, 0);
  assert.match(table.textContent, /厂家-149 & 开仓-149/);
  assert.match(table.textContent, /¥0/);
  assert.match(table.textContent, /未记录/);
  assert.match(table.textContent, /装入 N-149换下 O-149/);
  assert.equal(table.querySelectorAll('small').length, 150);
  assert.equal(table.querySelectorAll('[onclick], [style], [width], [height]').length, 0);
  assert.ok(output.querySelector('.analysis-print-table-card'));
  assert.match(h.html, /\.analysis-print-table-card\{[^}]*break-inside:auto!important/);
  assert.match(h.html, /thead\{display:table-header-group/);
  h.unchanged();
});

test('auto layout takes the existing body header once and preserves adjacent independent tables', () => {
  const h = harness(tableFixture(2, true).replace('</section>', '<div class="el-table"><table class="el-table__body"><thead><tr><th>第二张表</th></tr></thead><tbody><tr><td>独立值</td></tr></tbody></table></div></section>'));
  h.run();
  const tables = h.output.querySelectorAll('.analysis-print-table');
  assert.equal(tables.length, 2);
  assert.equal(tables[0].querySelectorAll('thead').length, 1);
  assert.equal(tables[0].querySelector('tbody').querySelectorAll('tr').length, 2);
  assert.equal(tables[1].querySelector('tbody').textContent, '独立值');
  h.unchanged();
});

test('a 50-row visible detail table exports all 1646 snapshot rows without changing the source page', () => {
  const h = harness(tableFixture(50).replace('class="el-table"', 'class="el-table" data-analysis-table="sources"'));
  const rows = Array.from({ length: 1646 }, (_, index) => [`开仓-${index}`, String(index), index === 0 ? '¥0' : '未记录']);
  assert.equal(h.document.querySelector('table.el-table__body').querySelector('tbody').querySelectorAll('tr').length, 50);
  assert.equal(h.run('费用来源', '.page', [], [{ id: 'sources', headers: ['开仓', '刀位', '登记金额（元）'], rows }]), true);
  const table = h.output.querySelector('[data-analysis-table="sources"]');
  assert.equal(table.tagName, 'table');
  assert.equal(table.querySelectorAll('thead').length, 1);
  assert.equal(table.querySelector('tbody').querySelectorAll('tr').length, 1646);
  assert.equal(table.querySelectorAll('td').length, 1646 * 3);
  assert.equal(table.querySelector('tbody').lastChild.textContent, '开仓-16451645未记录');
  assert.equal(h.output.querySelectorAll('.el-table, .el-table__body-wrapper, tfoot').length, 0);
  assert.ok(h.output.querySelector('.analysis-print-table-card'));
  h.unchanged();
});

test('snapshot headers and cells preserve Chinese, zero, explicit missing values and empty strings as safe text', () => {
  const unsafe = '<img src=x onerror=bad()> & "厂家"';
  const headers = [unsafe, '登记金额（元）', '未填写', '缺价', '配对说明'];
  const rows = [[unsafe, '¥0', '', '未记录', '装入 N-1\n换下 O-1'], ['厂家乙', '0', '', '无闭合样本', '中文 & <待核对>']];
  const h = harness('<section class="page"><div data-analysis-table="service"><p>旧数据</p></div></section>');
  const snapshot = { id: 'service', headers, rows };
  const before = JSON.stringify(snapshot);
  assert.equal(h.run('厂家表现', '.page', [], [snapshot]), true);
  const table = h.output.querySelector('[data-analysis-table="service"]');
  assert.deepEqual(table.querySelectorAll('th').map(cell => cell.textContent), headers);
  assert.deepEqual(table.querySelector('tbody').querySelectorAll('tr').map(row => row.querySelectorAll('td').map(cell => cell.textContent)), rows);
  assert.equal(table.querySelectorAll('img, script, [onerror]').length, 0);
  assert.doesNotMatch(table.textContent, /旧数据/);
  assert.equal(JSON.stringify(snapshot), before);
  h.unchanged();
});

test('snapshot replacement coexists with ordinary grouped tables and full chart images across sections', () => {
  const markup = tableFixture(2).replace('</section>', '<div data-analysis-table="sources">当前第1页</div><div class="chart-content"><div _echarts_instance_="full-chart"><canvas /><canvas /></div></div></section>')
    + '<section class="service-page"><div data-analysis-table="service">当前第2页</div></section>';
  const h = harness(markup, { chart: { series: [{ name: '费用趋势' }], dataZoom: [{ start: 20, end: 80 }] } });
  const sections = [{ title: '费用来源', selector: '.page' }, { title: '服役段', selector: '.service-page' }];
  const tables = [{ id: 'sources', headers: ['完整来源'], rows: [['来源1'], ['来源2'], ['来源3']] },
    { id: 'service', headers: ['完整服役'], rows: [['服役1'], ['服役2']] },
    { id: 'unused', headers: ['其他模块'], rows: [['不属于本报告']] }];
  assert.equal(h.run('全量报告', sections, [], tables), true);
  const output = h.output;
  assert.equal(output.querySelectorAll('.analysis-print-table').length, 3);
  const ordinary = output.querySelectorAll('.analysis-print-table').find(table => !table.hasAttribute('data-analysis-table'));
  assert.equal(ordinary.querySelector('thead').querySelectorAll('tr').length, 2);
  assert.equal(ordinary.querySelector('tbody').querySelectorAll('tr').length, 2);
  assert.equal(output.querySelector('[data-analysis-table="sources"]').querySelector('tbody').querySelectorAll('tr').length, 3);
  assert.equal(output.querySelector('[data-analysis-table="service"]').querySelector('tbody').querySelectorAll('tr').length, 2);
  assert.equal(output.querySelectorAll('img').length, 1);
  assert.equal(output.querySelectorAll('canvas, [_echarts_instance_]').length, 0);
  assert.match(output.querySelector('.chart-snapshot-note').textContent, /费用趋势.*20% 至 80%/);
  assert.doesNotMatch(output.querySelector('body').textContent, /当前第|不属于本报告/);
  h.unchanged();
});

test('an empty matched snapshot replaces stale visible rows, including a directly selected table root', () => {
  const h = harness('<section class="page"><div data-analysis-table="service"><table><tbody><tr><td>过期行</td></tr></tbody></table></div></section>');
  assert.equal(h.run('空快照', '[data-analysis-table="service"]', [], [{ id: 'service', headers: ['服役段'], rows: [] }]), true);
  const output = h.output;
  assert.equal(output.querySelectorAll('table').length, 1);
  assert.equal(output.querySelector('thead').textContent, '服役段');
  assert.equal(output.querySelector('tbody').querySelectorAll('tr').length, 0);
  assert.doesNotMatch(output.querySelector('body').textContent, /过期行/);
  h.unchanged();
});

test('metadata, title and section text are escaped while controls are removed and explanation/empty text stay', () => {
  const markup = '<section class="page"><div class="analysis-export-bar"><button>导出按钮</button></div><div class="analysis-no-export">秘密配置控件</div><form class="el-form">筛选控件</form><div class="chart-card-header"><div class="chart-heading"><h3>图形标题</h3></div><div><button>趋势选择</button></div></div><details><summary>统计口径</summary><p>完整说明</p></details><p class="state-tip">当前范围无有效样本</p><p onclick="bad()">安全文本<script>bad()</script></p><a href="javascript:bad()">开仓-123</a></section>';
  const h = harness(markup);
  const unsafe = '<img src=x onerror=bad()> & "厂家"';
  h.run(unsafe, [{ title: unsafe, selector: '.page' }], [{ label: unsafe, value: unsafe }, { label: '零', value: '0' }, { label: '缺失', value: '' }]);
  const output = h.output;
  assert.equal(output.querySelector('title').textContent, unsafe);
  assert.equal(output.querySelectorAll('script, img, [onclick], a, button, form').length, 0);
  assert.equal(output.querySelector('details').hasAttribute('open'), true);
  assert.match(output.querySelector('body').textContent, /完整说明/);
  assert.match(output.querySelector('body').textContent, /当前范围无有效样本/);
  assert.match(output.querySelector('body').textContent, /开仓-123/);
  assert.doesNotMatch(output.querySelector('body').textContent, /秘密配置控件|筛选控件|导出按钮|趋势选择/);
  const cells = output.querySelector('.filter-summary').querySelectorAll('td');
  assert.equal(cells[0].textContent, unsafe);
  assert.equal(cells[1].textContent, '0');
  assert.equal(cells[2].textContent, '未记录');
  h.unchanged();
});

test('ECharts complete image replaces each multi-canvas root and records current legend/zoom without mutations', () => {
  const option = { series: [{ name: '厂家A' }, { name: '<厂家B>' }], legend: [{ selected: { '<厂家B>': false } }], dataZoom: [{ start: 20, end: 80 }, { startValue: 0, endValue: 12 }] };
  const beforeOption = JSON.stringify(option);
  const h = harness('<section class="page"><div class="chart-content"><div _echarts_instance_="first"><canvas /><canvas /></div><div _echarts_instance_="second"><canvas /><canvas /></div></div></section>', { chart: option });
  assert.equal(h.run(), true);
  assert.deepEqual(h.snapshots, ['first', 'second'].map(id => ({ id, params: { type: 'png', pixelRatio: 2, backgroundColor: '#fff' } })));
  const output = h.output;
  assert.equal(output.querySelectorAll('canvas, [_echarts_instance_]').length, 0);
  assert.equal(output.querySelectorAll('.chart-export-box').length, 2);
  assert.equal(output.querySelectorAll('img').length, 2);
  assert.equal(output.querySelector('img').getAttribute('width'), '900');
  assert.equal(output.querySelector('img').getAttribute('height'), '360');
  const note = output.querySelector('.chart-snapshot-note').textContent;
  assert.match(note, /厂家A、<厂家B>/);
  assert.match(note, /未选中：<厂家B>/);
  assert.match(note, /20% 至 80%/);
  assert.match(note, /0 至 12/);
  assert.equal(JSON.stringify(option), beforeOption);
  h.unchanged();
});

test('an unavailable ECharts instance with multiple canvases stops before opening a partial report', () => {
  const h = harness('<section class="page"><div _echarts_instance_="missing"><canvas /><canvas /></div></section>');
  assert.equal(h.run(), false);
  assert.equal(h.opened.length, 0);
  assert.equal(h.notices[0].level, 'error');
  assert.match(h.notices[0].message, /图表.*就绪/);
  h.unchanged();
});

test('one-canvas fallback retains original dimensions when no ECharts instance exists', () => {
  const h = harness('<section class="page"><div _echarts_instance_="fallback"><canvas width="800" height="320" /></div></section>');
  h.document.querySelector('canvas').toDataURL = type => { assert.equal(type, 'image/png'); return 'data:image/png;base64,fallback'; };
  assert.equal(h.run(), true);
  const image = h.output.querySelector('img');
  assert.equal(image.getAttribute('src'), 'data:image/png;base64,fallback');
  assert.equal(image.getAttribute('width'), '800');
  assert.equal(image.getAttribute('height'), '320');
  h.unchanged();
});

test('missing sections and an empty section list stop without opening a blank print window', () => {
  for (const sections of ['.missing', []]) {
    const h = harness();
    assert.equal(h.run('空报告', sections), false);
    assert.equal(h.opened.length, 0);
    assert.equal(h.notices.length, 1);
    assert.match(h.notices[0].message, /未找到|没有可导出/);
  }
});

test('blocked popups show an actionable message without scheduling printing', () => {
  const h = harness(undefined, { blocked: true });
  assert.equal(h.run(), false);
  assert.equal(h.opened.length, 1);
  assert.equal(h.timers.size, 0);
  assert.match(h.notices[0].message, /拦截.*允许/);
});

test('ready images and fonts print exactly once and leave no polling timer', async () => {
  const h = harness(undefined, { images: [{ complete: true, naturalWidth: 900 }], fonts: { ready: Promise.resolve() } });
  assert.equal(h.run(), true);
  h.tick();
  assert.equal(h.printed, 0, 'Must wait for fonts promise');
  await Promise.resolve();
  h.tick(); h.tick(20000);
  assert.equal(h.printed, 1);
  assert.equal(h.focused, 1);
  assert.equal(h.timers.size, 0);
  assert.equal(h.notices.length, 0);
});

test('a pending image can finish and print once before the bounded deadline', () => {
  const image = { complete: false, naturalWidth: 0 };
  const h = harness(undefined, { images: [image] });
  h.run(); h.tick();
  assert.equal(h.printed, 0);
  image.complete = true; image.naturalWidth = 600;
  h.tick(); h.tick();
  assert.equal(h.printed, 1);
  assert.equal(h.timers.size, 0);
});

test('broken images stop auto-printing with a visible failure', () => {
  const h = harness(undefined, { images: [{ complete: true, naturalWidth: 0 }] });
  h.run(); h.tick(); h.tick(10000);
  assert.equal(h.printed, 0);
  assert.equal(h.timers.size, 0);
  assert.equal(h.notices.length, 1);
  assert.match(h.notices[0].message, /图片加载失败/);
});

test('image and font waits have a fixed deadline and never print a partial report', () => {
  for (const options of [{ images: [{ complete: false, naturalWidth: 0 }] }, { fonts: { ready: new Promise(() => {}) } }]) {
    const h = harness(undefined, options);
    h.run(); h.tick(); h.tick(10000); h.tick(10000);
    assert.equal(h.printed, 0);
    assert.equal(h.timers.size, 0);
    assert.equal(h.notices.length, 1);
    assert.match(h.notices[0].message, /超时.*未自动打印/);
  }
});

test('closing the print window cancels further polling without printing or an error', () => {
  const h = harness(undefined, { images: [{ complete: false, naturalWidth: 0 }] });
  h.run(); h.tick();
  h.printWindow.closed = true;
  h.tick(); h.tick(10000);
  assert.equal(h.printed, 0);
  assert.equal(h.focused, 0);
  assert.equal(h.timers.size, 0);
  assert.equal(h.notices.length, 0);
});
