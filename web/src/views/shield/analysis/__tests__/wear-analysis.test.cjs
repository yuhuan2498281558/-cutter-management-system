const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { setup, plain, deferred, settle, compile, echartsStub, descendants, textOf } = require('./helpers.cjs');

const meta = scope => ({ schema_version: 2, generated_at: '2026-09-11T00:00:00Z', summary_status: 'CONFIRMED', opening_count: 2, draft_opening_count: 0, excluded_inactive_count: 0, unobserved_count: 0, warnings: [], scope: { project_name: '磨损验收工程', ...scope } });
const rows = [
  { opening_id: 11, ring_no: '100', open_time: '2026-01-01', checked_count: 5, total: 4, abnormal: 1, abnormal_rate: 0.25, replacement_count: 2, unrecorded_count: 1, geological_conditions: '<img src=x onerror=alert(1)>', stratum_types: '<岩层>' },
  { opening_id: 12, ring_no: '200', open_time: '2026-02-01', checked_count: 2, total: 0, abnormal: 0, abnormal_rate: null, replacement_count: 1, unrecorded_count: 2, geological_conditions: '', stratum_types: '' },
];
function fixture(config) {
  const data = config.url.endsWith('wear_distribution/') ? {
    checked_count: 7, total: 7, wear_recorded_count: 4, normal_count: 3, abnormal_count: 1, unrecorded_count: 3,
    items: [{ wear_condition: '正常', state: 'NORMAL', count: 3 }, { wear_condition: '偏磨', state: 'ABNORMAL', count: 1 }, { wear_condition: '未知', state: null, count: 3 }],
  } : { items: rows };
  return { data: { ...data, meta: meta(config.params) } };
}
function create(t, options = {}) { return setup(t, 'pages/WearAnalysis.vue', { request: fixture, ...options }); }
function charts(r) { r.state.distributionRef.value = { key: 'distribution' }; r.state.trendChartRef.value = { key: 'trend' }; r.state.renderCharts(); }
function option(r, key) { return r.charts.find(chart => chart.element.key === key).options.at(-1); }

test('wear uses exact global GET scope and keeps observed, recorded and replaced counts separate', async t => {
  const r = create(t, { props: { filter: { project: 7, shield_machine: 9, manufacturer: '原厂家', summary_status: 'CONFIRMED', start_ring: '100' } } });
  await r.mount(); assert.equal(r.requests.length, 2);
  for (const call of r.requests) { assert.equal(call.method, 'get'); assert.equal(call.params.manufacturer, '原厂家'); assert.equal(call.params.start_ring, '100'); }
  assert.equal(r.state.overallRate.value, 0.25); assert.equal(r.state.wearDist.value.checked_count, 7);
  assert.equal(r.state.trendRows.value[0].total, 4); assert.equal(r.state.trendRows.value[0].replacement_count, 2);
});

test('distribution balances all three groups and trend preserves null denominators with no mean line', async t => {
  const r = create(t); await r.mount(); charts(r);
  const distribution = option(r, 'distribution'); assert.equal(distribution.series[0].type, 'bar');
  assert.deepEqual(plain(distribution.series[0].data.map(item => item.value)), [3, 1, 3]);
  const trend = option(r, 'trend'); assert.deepEqual(plain(trend.xAxis.data), ['100环', '200环']);
  assert.deepEqual(plain(trend.series.map(item => item.data)), [[4, 0], [2, 1], [0.25, null]]);
  assert.equal(trend.series[2].yAxisIndex, 1); assert.equal(trend.series[2].connectNulls, false);
  assert.equal(trend.series[2].markLine, undefined); assert.equal(r.state.formatPercent(null), '无有效样本'); assert.equal(r.state.formatPercent(0), '0.0%');
});

test('tooltip shows denominator and safely escapes geological descriptions', async t => {
  const r = create(t); await r.mount(); charts(r);
  const tooltip = option(r, 'trend').tooltip.formatter([{ dataIndex: 0 }]);
  assert.match(tooltip, /1 \/ 4/); assert.match(tooltip, /&lt;img/); assert.match(tooltip, /&lt;岩层&gt;/); assert.doesNotMatch(tooltip, /<img/);
  assert.equal(option(r, 'trend').tooltip.formatter([]), '');
});

test('a failed request clears old data and export until a complete retry succeeds', async t => {
  let fails = false; const r = create(t, { request: config => { if (fails && config.url.endsWith('wear_trend/')) throw new Error('offline'); return fixture(config); } });
  await r.mount(); fails = true; await r.state.loadData();
  assert.equal(r.state.ready.value, false); assert.equal(r.state.trendRows.value.length, 0); assert.ok(r.state.error.value);
  r.state.exportPdf(); assert.equal(r.exports.length, 0);
  fails = false; await r.state.loadData(); assert.equal(r.state.ready.value, true); assert.equal(r.state.error.value, '');
});

test('old responses and deactivated pages cannot replace a new scope', async t => {
  const old = deferred(), fresh = deferred();
  const r = create(t, { props: { filter: { project: 1 } }, request: config => config.url.endsWith('wear_distribution/') ? (config.params.project === 1 ? old.promise : fresh.promise) : fixture(config) });
  const first = r.state.loadData(); r.props.filter = { project: 2 }; await settle();
  old.resolve(fixture({ url: 'wear_distribution/', params: { project: 1 } })); await first;
  assert.equal(r.state.loading.value, true); assert.equal(r.state.wearDist.value, undefined);
  r.hooks.onDeactivated.forEach(hook => hook()); fresh.resolve(fixture({ url: 'wear_distribution/', params: { project: 2 } })); await settle();
  assert.equal(r.state.ready.value, false); assert.equal(r.state.wearDist.value, undefined);
});

test('old contract is rejected; empty results can recover and chart DOM replacements dispose old instances', async t => {
  let mode = 'old'; const r = create(t, { request: config => { const result = fixture(config); if (mode === 'old') delete result.data.meta; if (mode === 'empty') { result.data.items = []; result.data.total = 0; result.data.wear_recorded_count = 0; } return result; } });
  await r.mount(); assert.equal(r.state.ready.value, false);
  mode = 'empty'; await r.state.loadData(); assert.equal(r.state.overallRate.value, null); assert.equal(r.state.trendRows.value.length, 0); charts(r);
  const previous = r.charts[0]; mode = 'full'; await r.state.loadData(); r.state.distributionRef.value = { key: 'new-distribution' }; r.state.renderCharts();
  assert.equal(previous.disposed, true); assert.equal(r.state.trendRows.value.length, 2);
  r.unmount(); assert.ok(r.charts.every(chart => chart.disposed));
});

test('real template labels the denominator correctly and exports complete rows with readonly trace', async t => {
  const r = create(t); await r.mount();
  const tables = r.nodes().filter(node => node.type?.name === 'el-table'); assert.equal(tables.length, 2); assert.equal(tables[0].props.data.length, 2); assert.equal(tables[0].props['max-height'], 480);
  const columns = r.nodes().filter(node => node.type?.name === 'el-table-column');
  assert.ok(columns.some(node => node.props?.prop === 'total' && node.props.label === '已分类磨损数'));
  assert.ok(!columns.some(node => node.props?.prop === 'total' && node.props.label === '检查刀具数'));
  r.state.exportPdf();
  assert.deepEqual(plain(r.exports[0][1].map(section => section.selector)), ['.wear-summary-section', '.wear-charts-section', '.wear-opening-section', '.wear-description-section']);
  assert.ok(r.exports[0][2].some(item => item.value.includes('磨损验收工程')));
  r.state.openOpening(rows[0]); assert.deepEqual(plain(r.routes[0]), { path: '/shield/toolChangeDetail', query: { warehouse_id: '11', mode: 'view' } });
});

test('page size changes only resize the charts, so legend and zoom state survive', async t => {
  const observers = [];
  class RecordingResizeObserver { constructor(callback) { this.callback = callback; this.targets = []; observers.push(this); } observe(target) { this.targets.push(target); } disconnect() {} }
  const frame = async () => { await settle(); await new Promise(resolve => setTimeout(resolve, 0)); };
  const r = create(t, { globals: { ResizeObserver: RecordingResizeObserver } });
  r.state.pageRef.value = { key: 'page' };
  await r.mount(); charts(r); await frame();
  assert.equal(observers.length, 1); assert.deepEqual(observers[0].targets, [{ key: 'page' }]);
  assert.equal(r.charts.length, 2);
  r.charts.forEach(chart => { chart.resizeCount = 0; chart.resize = function () { this.resizeCount += 1; }; });
  const setOptionCounts = () => r.charts.map(chart => chart.options.length);
  const resizeCounts = () => r.charts.map(chart => chart.resizeCount);
  const before = setOptionCounts();
  observers[0].callback([]); observers[0].callback([]); observers[0].callback([]); await frame();
  assert.deepEqual(setOptionCounts(), before);
  assert.deepEqual(resizeCounts(), [1, 1]);
  observers[0].callback([]); r.hooks.onDeactivated.forEach(hook => hook()); await frame();
  assert.deepEqual(resizeCounts(), [1, 1]);
  r.hooks.onActivated.forEach(hook => hook()); await frame();
  const options = setOptionCounts(), resizes = resizeCounts();
  observers[0].callback([]); await frame();
  assert.deepEqual(setOptionCounts(), options);
  assert.deepEqual(resizeCounts(), resizes.map(count => count + 1));
});

test('conclusion leads with the abnormal share; counts and wear basis move to the side, info tips and scope details', async t => {
  const r = create(t); await r.mount();
  const summary = r.nodes().find(node => node.props?.class === 'wear-summary-section');
  const parts = descendants(summary);
  assert.equal(parts.find(node => node.props?.class === 'hero-value').children, '25.0%');
  assert.equal(textOf(parts.find(node => node.props?.class === 'hero-sub')), '非正常 1 / 已分类 4');
  const tips = parts.filter(node => node.type?.name === 'InfoTip').map(node => node.props.content);
  assert.deepEqual(tips, ['非正常样本数 ÷ 已分类磨损样本数', '正常 3 · 非正常 1', '来自明确检查 / 更换等证据，非整仓人工汇总数', '含未记录或未识别，不计入比例分母']);
  const stats = parts.filter(node => node.props?.class === 'hero-card hero-stat analysis-card').map(node => [
    descendants(node).find(item => item.props?.class === 'hero-label').children[0].children,
    descendants(node).find(item => item.props?.class === 'hero-stat-value').children,
    descendants(node).find(item => item.props?.class === 'hero-stat-sub')?.children,
  ]);
  assert.deepEqual(stats, [['有效观察明细', '7', undefined], ['磨损未分类', '3', '不计入比例分母']]);
  const scope = parts.find(node => node.type?.name === 'ScopeSummary');
  assert.match(textOf(scope), /“中度磨损”“异常磨损”归非正常，比例不等于设备故障率/);
  assert.match(textOf(scope), /筛选厂家时按已确认旧刀配对归属原安装厂家/);
  assert.equal(r.nodes().some(node => ['analysis-metrics', 'analysis-note'].includes(node.props?.class)), false);

  const none = create(t, { request: config => { const result = fixture(config); if (config.url.endsWith('wear_distribution/')) result.data.unrecorded_count = 0; return result; } });
  await none.mount();
  assert.equal(none.nodes().some(node => node.props?.class === 'hero-stat-sub'), false, 'no denominator line when nothing is unclassified');
});

test('the two wear tables share one card with tabs and still export separately with their basis', async t => {
  const r = create(t);
  const card = () => descendants(r.nodes().find(node => node.props?.class === 'analysis-detail-card'));
  const labels = () => card().filter(node => node.type?.name === 'el-tab-pane').map(node => node.props.label);
  assert.deepEqual(labels(), ['逐仓对照', '现场磨损描述']);
  await r.mount();
  assert.deepEqual(labels(), ['逐仓对照 · 2 次开仓', '现场磨损描述']);
  const tip = () => card().find(node => node.type?.name === 'InfoTip').props.content;
  const panes = () => card().filter(node => node.dirs).map(node => [node.dirs[0].value, descendants(node)[1].props.class]);
  assert.equal(tip(), '地层是同次开仓的工程背景，关联不等于原因；一仓可能跨多个地层，不能将各地层组重复加总。');
  assert.deepEqual(panes(), [[true, 'wear-opening-section'], [false, 'wear-description-section']]);
  assert.equal(r.nodes().some(node => /点击环号|保留当前范围全部返回记录/.test(String(node.children))), false);
  r.state.detailTab.value = 'descriptions';
  assert.equal(tip(), '保留原始描述及系统归类；占比以全部有效观察明细为分母，与上方非正常比例不同。');
  assert.deepEqual(panes(), [[false, 'wear-opening-section'], [true, 'wear-description-section']]);
  r.state.exportPdf();
  assert.deepEqual(plain(r.exports[0][1]), [
    { title: '', selector: '.wear-summary-section' },
    { title: '', selector: '.wear-charts-section' },
    { title: '逐仓磨损、消耗与地层对照', selector: '.wear-opening-section', note: '地层是同次开仓的工程背景，关联不等于原因；一仓可能跨多个地层，不能将各地层组重复加总。' },
    { title: '现场磨损描述明细', selector: '.wear-description-section', note: tip() },
  ]);
});

function loadWearChartOptions() {
  function load(file) {
    return compile(fs.readFileSync(file, 'utf8'), name => name === 'echarts' ? echartsStub : load(path.resolve(path.dirname(file), `${name}.ts`)));
  }
  return load(path.resolve(__dirname, '../utils/wearChartOptions.ts'));
}

test('wear option builders read only their arguments and zoom long trends', () => {
  const { buildWearDistributionOption, buildWearTrendOption } = loadWearChartOptions();
  const distribution = buildWearDistributionOption({ normal_count: 3, abnormal_count: 1, unrecorded_count: 3 });
  assert.deepEqual(plain(distribution.yAxis.data), ['正常', '非正常', '未分类']);
  assert.deepEqual(plain(distribution.series[0].data.map(item => [item.value, item.itemStyle.color])), [[3, '#6f8f6a'], [1, '#b5533c'], [3, '#9a978e']]);
  const trend = buildWearTrendOption(rows);
  assert.deepEqual(plain(trend.series.map(item => item.name)), ['已分类磨损数', '实际更换数', '非正常比例']);
  assert.deepEqual(plain(trend.dataZoom), []); assert.equal(trend.yAxis[1].axisLabel.formatter(0.25), '25%');
  assert.match(trend.tooltip.formatter([{ dataIndex: 1 }]), /200 环 · 2026-02-01.*地层：未记录/);
  const long = buildWearTrendOption(Array.from({ length: 15 }, (_, index) => ({ ...rows[0], ring_no: String(index + 1) })));
  assert.deepEqual(plain(long.dataZoom), [{ type: 'inside' }]);
});
