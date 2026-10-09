const { test } = require('node:test');
const assert = require('node:assert/strict');
const { setup, plain, deferred, settle } = require('./helpers.cjs');

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
  r.state.exportPdf(); assert.equal(r.exports[0][1], '.wear-page'); assert.ok(r.exports[0][2].some(item => item.value.includes('磨损验收工程')));
  r.state.openOpening(rows[0]); assert.deepEqual(plain(r.routes[0]), { path: '/shield/toolChangeDetail', query: { warehouse_id: '11', mode: 'view' } });
});
