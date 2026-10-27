const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { setup, plain, deferred, settle, compile, echartsStub, descendants } = require('./helpers.cjs');

const meta = scope => ({ schema_version: 2, generated_at: '2026-09-11T00:00:00Z', summary_status: 'CONFIRMED', opening_count: 2, draft_opening_count: 1, excluded_inactive_count: 0, unobserved_count: 0, warnings: [], scope: { project_name: '验收工程', shield_machine_name: '一号机', ...scope } });
const sources = { installation: 100, confirmed_repair: 20, legacy: 30, unresolved: 50, total: 150, missing_price_count: 1, pending_repair_count: 1, repair_missing_price_count: 0, unresolved_count: 1, priced_count: 3 };
const sourceRows = [
  { id: 'detail:1', detail_id: 1, opening_id: 11, warehouse_id: 'W-11', ring_no: '100', cutter_position_no: '1', manufacturer: 'A', source: 'installation', amount: 100, included: true, reason: '', old_tool_number: 'OLD', new_tool_number: 'NEW' },
  { id: 'repair:1', detail_id: 1, opening_id: 11, warehouse_id: 'W-11', ring_no: '100', manufacturer: '', source: 'confirmed_repair', amount: 20, included: true, inspection_status: 'CONFIRMED' },
  { id: 'detail:2', detail_id: 2, opening_id: 12, warehouse_id: 'W-12', ring_no: '200', manufacturer: 'A', source: 'legacy_untyped', amount: 30, included: true },
  { id: 'detail:3', detail_id: 3, opening_id: 12, warehouse_id: 'W-12', ring_no: '200', manufacturer: 'A', source: 'unresolved', amount: 50, included: false, reason: '待核对' },
  { id: 'detail:4', detail_id: 4, opening_id: 12, manufacturer: 'B', source: 'installation', amount: 0, included: true },
  { id: 'detail:5', detail_id: 5, opening_id: 12, manufacturer: 'B', source: 'installation', amount: null, included: false, reason: '缺价' },
];
const brands = [
  { manufacturer: 'A', total_cost: 130, count: 3, installation_count: 2, legacy_replacement_count: 1, avg_cost: 100, priced_count: 1, missing_price_count: 1, avg_lifespan: 80, lifespan_count: 2, paired_count: 2, abnormal_rate: 0.5, wear_recorded_count: 2, abnormal_count: 1 },
  { manufacturer: 'B', total_cost: 0, count: 2, installation_count: 2, legacy_replacement_count: 0, avg_cost: 0, priced_count: 1, avg_lifespan: null, lifespan_count: 0, paired_count: 0, abnormal_rate: null, wear_recorded_count: 0 },
];
function fixture(config) {
  const common = { meta: meta(config.params) };
  if (config.url.endsWith('filter_options/')) return { data: { manufacturers: ['A', 'B', 'C'], stratum_types: [{ value: 'ROCK', label: '岩层' }, { value: 'SOIL', label: '土层' }] } };
  if (config.url.endsWith('cost_overview/')) return { data: { ...common, cost_sources: sources, source_rows: sourceRows, source_rows_total: sourceRows.length, type_breakdown: [{ tool_type: 'DISC', cost_sources: sources }], cost_per_ring: { available: false, reason: '范围不支持摊销', ring_count: 0, total: null } } };
  if (config.url.endsWith('cost_trend/')) return { data: { ...common, items: [{ ring_no: '100', installation_cost: 100, confirmed_repair_cost: 20, legacy_cost: 0, unresolved_cost: 50, cumulative_cost: 120, replacement_count: 2 }, { ring_no: '200', installation_cost: 0, confirmed_repair_cost: 0, legacy_cost: 30, cumulative_cost: 150, replacement_count: 1 }] } };
  const data = { ...common, items: brands, source_rows: sourceRows, unknown_manufacturer_count: 1, pairing_unresolved_count: 1,
    service_rows: [{ opening_id: 11, warehouse_id: 'W-11', old_tool_number: 'OLD', manufacturer: 'A', service_rings: 80, paired: true }], manufacturers: ['A', 'B'],
    time_axis: [{ ring_no: '100', open_time: '2026-01-01' }, { ring_no: '200', open_time: '2026-02-01' }],
    series: [{ manufacturer: 'A', data: [100, null], count_data: [1, 0] }, { manufacturer: 'B', data: [null, 0], count_data: [0, 1] }],
    lifespan_series: [{ manufacturer: 'A', data: [80, null], count_data: [2, 0] }],
    abnormal_rate_series: [{ manufacturer: 'A', data: [0.5, null], count_data: [2, 0], abnormal_count_data: [1, 0] }],
    normal_rate_series: [{ manufacturer: 'A', data: [0.5, null], count_data: [2, 0], abnormal_count_data: [1, 0] }],
  };
  return { data };
}
function create(t, options = {}) { return setup(t, 'pages/CostAnalysis.vue', { request: fixture, ...options }); }
function bindCharts(s) { for (const key of ['costTrendRef', 'typeRef']) s[key].value = { key }; s.renderCharts(); }
const latest = (result, key) => result.charts.find(chart => chart.element.key === key)?.options.at(-1);
const detailCard = result => result.nodes().find(node => node.type?.name === 'ChartCard' && /^费用来源明细/.test(node.props?.title));

test('the cost page asks only for cost data, and the top stratum condition reaches both requests', async t => {
  const r = create(t, { props: { filter: { summary_status: 'CONFIRMED', stratum_type: 'ROCK' } } });
  await r.mount();
  // 厂家对比搬到了寿命与厂家页：这里不再请求厂家接口和筛选项
  assert.deepEqual(r.requests.map(call => call.url.split('/').at(-2)).sort(), ['cost_overview', 'cost_trend']);
  for (const call of r.requests) assert.equal(call.params.stratum_type, 'ROCK', call.url);
  assert.equal(r.nodes().some(node => node.type?.name === 'el-form-item' && node.props.label === '地层'), false);
  r.props.filter = { summary_status: 'CONFIRMED' }; await settle();
  for (const endpoint of ['cost_overview/', 'cost_trend/']) {
    assert.equal(r.requests.filter(item => item.url.endsWith(endpoint)).at(-1).params.stratum_type, undefined, endpoint);
  }
});
test('source stacks and source table use explicit amounts, retain unresolved, missing and zero records', async t => {
  const r = create(t); await r.mount(); bindCharts(r.state);
  assert.equal(r.state.sources.value.total, 150); assert.equal(r.state.sourceRows.value.length, 6);
  // 费用来源构成图已由结论区的比例条代替：三段金额与原图一致，占比按合计 150 计算
  assert.deepEqual(plain(r.state.shareParts.value.map(item => item.amount)), [100, 20, 30]);
  const share = setup(t, 'components/AmountShare.vue', { props: { parts: r.state.shareParts.value, total: r.state.sources.value.total } });
  const cells = name => share.nodes().filter(node => node.props?.class === name).map(node => node.children);
  assert.deepEqual(cells('share-amount'), ['¥100', '¥20', '¥30']);
  assert.deepEqual(cells('share-percent'), ['66.7%', '13.3%', '20.0%']);
  assert.deepEqual(plain(r.nodes().some(node => node.props?.title === '费用来源构成')), false);
  assert.deepEqual(plain(latest(r, 'costTrendRef').series.slice(0, 3).map(item => item.data)), [[100, 0], [20, 0], [0, 30]]);
  assert.equal(r.state.formatCurrency(0), '¥0'); assert.equal(r.state.formatCurrency(null), '未记录');
});

test('new scope invalidates old export immediately and late requests cannot overwrite it', async t => {
  const old = deferred(), fresh = deferred();
  const r = create(t, { props: { filter: { project: 1, summary_status: 'CONFIRMED' } }, request: config => config.url.endsWith('cost_overview/') ? (config.params.project === 1 ? old.promise : fresh.promise) : fixture(config) });
  const first = r.state.loadData(); r.props.filter = { project: 2, summary_status: 'CONFIRMED' }; await settle();
  r.state.exportCompositionPdf(); assert.equal(r.exports.length, 0);
  old.resolve(fixture({ url: 'cost_overview/', params: { project: 1 } })); await first;
  assert.equal(r.state.costLoading.value, true); assert.equal(r.state.costOverview.value, undefined);
  fresh.resolve(fixture({ url: 'cost_overview/', params: { project: 2 } })); await settle();
  assert.equal(r.state.costOverview.value.meta.scope.project, 2); assert.equal(r.state.costReady.value, true);
});

test('legacy responses never display obsolete statistics or become exportable', async t => {
  const r = create(t, { request: config => { const response = fixture(config); delete response.data.meta; return response; } });
  await r.mount(); assert.equal(r.state.costReady.value, false);
  assert.equal(r.state.sources.value, undefined); assert.ok(r.state.costError.value);
  r.state.exportCompositionPdf(); assert.equal(r.exports.length, 0);
});
test('the export includes the complete source table with the successful scope; drill-through is readonly', async t => {
  const r = create(t); await r.mount(); r.state.exportCompositionPdf();
  assert.equal(r.exports.length, 1);
  assert.ok(r.exports[0][1].some(section => section.selector === '.cost-source-section'));
  assert.ok(r.exports[0][2].some(item => item.value.includes('验收工程')));
  r.state.openOpening(sourceRows[0]); assert.deepEqual(plain(r.routes[0]), { path: '/shield/toolChangeDetail', query: { warehouse_id: '11', warehouse_code: 'W-11', mode: 'view' } });
});
test('real template binds chart modes, the ready export gate and one scrollable source table', async t => {
  const r = create(t); let nodes = r.nodes();
  const actions = () => r.nodes().find(node => node.type?.name === 'AnalysisActions').props;
  assert.deepEqual(plain(actions().exports.map(item => [item.label, item.disabled])), [['导出费用来源 PDF', true]]);
  await r.mount(); nodes = r.nodes();
  assert.equal(actions().exports[0].disabled, false); assert.equal(actions().exports[0].run, r.state.exportCompositionPdf);
  const radios = nodes.filter(node => node.type?.name === 'el-radio-button'); assert.deepEqual(radios.map(node => node.props.label), ['consumption', 'cumulative']);
  const tables = nodes.filter(node => node.type?.name === 'el-table'); assert.equal(tables.length, 1);
  assert.equal(tables[0].props['data-analysis-table'], 'sources');
  assert.equal(tables[0].props.data.length, 6); assert.equal(tables[0].props['max-height'], 420);
  assert.equal(nodes.some(node => node.type?.name === 'ManufacturerComparison' || node.props?.class === 'section-heading'), false);
});
test('deactivation rejects late responses and unmount releases every chart', async t => {
  const wait = deferred(); let delayed = false;
  const r = create(t, { request: config => delayed ? wait.promise : fixture(config) });
  await r.mount(); bindCharts(r.state); delayed = true;
  const pending = r.state.loadData(); r.hooks.onDeactivated.forEach(hook => hook());
  wait.resolve(fixture({ url: 'cost_overview/', params: {} })); await pending;
  assert.equal(r.state.costReady.value, false); r.unmount(); assert.ok(r.charts.every(chart => chart.disposed));
});

test('a long source table paginates locally while exporting every successful row', async t => {
  const rows = Array.from({ length: 1646 }, (_, id) => ({ ...sourceRows[id % sourceRows.length], id: `source-${id}` }));
  const r = create(t, { request: config => {
    const response = fixture(config);
    if (config.url.endsWith('cost_overview/')) response.data.source_rows = rows;
    return response;
  } });
  await r.mount();
  const initialRequests = r.requests.length;
  assert.equal(r.state.visibleSourceRows.value.length, 50);
  r.state.sourcePage.value = 33;
  assert.equal(r.state.visibleSourceRows.value.length, 46);
  assert.equal(r.state.visibleSourceRows.value[0].id, 'source-1600');
  r.state.exportCompositionPdf();
  assert.equal(r.exports[0][3][0].rows.length, 1646);
  assert.equal(r.exports[0][3][0].rows[4][3], '¥0'); assert.equal(r.exports[0][3][0].rows[5][3], '未记录');
  r.state.sourcePageSize.value = 100;
  assert.equal(r.state.sourcePage.value, 1); assert.equal(r.state.visibleSourceRows.value.length, 100);
  await settle(); assert.equal(r.requests.length, initialRequests, 'Paging does not issue network queries');
  r.state.sourcePage.value = 2;
  r.props.filter = { project: 2, summary_status: 'CONFIRMED' };
  assert.equal(r.state.sourcePage.value, 1); assert.equal(r.state.visibleSourceRows.value.length, 0);
});
test('unrelated charts retain their options and user view when a single metric changes', async t => {
  const r = create(t); await r.mount(); bindCharts(r.state);
  const counts = () => r.charts.map(chart => chart.options.length);
  // 图表顺序：环号趋势、刀型贡献（费用来源构成图已由比例条代替，厂家图已搬到寿命与厂家页）
  assert.deepEqual(counts(), [1, 1]);
  r.state.renderCharts(); assert.deepEqual(counts(), [1, 1]);
  r.state.costMode.value = 'cumulative'; r.state.renderCharts();
  assert.deepEqual(counts(), [2, 1]);
  r.state.sourcePage.value = 2; r.state.renderCharts();
  assert.deepEqual(counts(), [2, 1]);
  r.state.typeRef.value = { key: 'replacement-element' }; r.state.renderCharts();
  assert.equal(r.charts[1].disposed, true); assert.equal(r.charts[2].options.length, 1);
});
test('conclusion leads with the explicit total, its source shares, the per-ring figure and only non-zero review items', async t => {
  const r = create(t); await r.mount();
  const nodes = r.nodes();
  const composition = nodes.find(node => node.props?.class === 'cost-composition-section');
  const hero = descendants(composition).find(node => node.props?.class === 'analysis-hero');
  const heroNodes = descendants(hero);
  assert.equal(heroNodes.find(node => node.props?.class === 'hero-value').children, '¥150');
  const tips = heroNodes.filter(node => node.type?.name === 'InfoTip').map(node => node.props.content);
  assert.deepEqual(tips, ['新装登记、已确认返修、历史登记三类之和，不是财务结算额', '范围不支持摊销']);
  const share = heroNodes.find(node => node.type?.name === 'AmountShare');
  assert.equal(share.props.total, 150);
  assert.deepEqual(plain(share.props.parts), [
    { label: '新装刀具登记', amount: 100, color: '#3f5f7a', tip: '装入刀具登记，可能包含维修件' },
    { label: '已确认返修', amount: 20, color: '#6f8f6a', tip: '按对应拆除开仓归集' },
    { label: '历史登记', amount: 30, color: '#c2b8a3', tip: '保留旧式整刀、维修与未分类来源' },
  ]);
  assert.equal(heroNodes.find(node => node.props?.class === 'hero-stat-value').children, '暂不计算');
  const review = heroNodes.find(node => node.type?.name === 'ReviewList');
  assert.deepEqual(plain(review.props.items.map(item => [item.name, item.pending, `${item.lead}：${item.detail}`])), [
    ['缺登记价格', true, '1 条缺登记价格：没有计入金额，合计偏小'],
    ['返修待确认', true, '1 条返修待确认：确认后，返修金额和合计还会增加'],
    ['已确认返修缺价', false, '0 条已确认返修缺价：未计入返修金额'],
    ['金额归属待核对', true, '1 条金额归属待核对（¥50）：未计入合计'],
  ]);
  assert.equal(nodes.some(node => ['analysis-metrics', 'cost-quality', 'analysis-note allocation-note'].includes(node.props?.class)), false);
  const scopes = nodes.filter(node => node.type?.name === 'ScopeSummary');
  assert.equal(scopes.length, 1, 'the scope is stated once; the manufacturer section has no second scope line');
  assert.equal(scopes[0].props.meta, r.state.costOverview.value.meta);

  const allocated = create(t, { request: config => {
    const response = fixture(config);
    if (config.url.endsWith('cost_overview/')) response.data.cost_per_ring = { available: true, total: 10457.55, ring_count: 473 };
    return response;
  } });
  await allocated.mount();
  const stat = descendants(allocated.nodes().find(node => node.props?.class === 'hero-card hero-stat analysis-card'));
  assert.equal(stat.find(node => node.props?.class === 'hero-stat-value').children, '¥10,457.55 / 环');
  assert.equal(stat.find(node => node.type?.name === 'InfoTip').props.content, '分母 473 环（最大减最小开仓环号加 1），不是实际掘进单环成本');
});

test('the source detail card counts rows and flags only server truncation', async t => {
  const r = create(t, { request: config => {
    const response = fixture(config);
    if (config.url.endsWith('cost_overview/')) Object.assign(response.data, { source_rows_total: 900, source_rows_truncated: true });
    return response;
  } });
  assert.equal(detailCard(r).props.title, '费用来源明细');
  await r.mount();
  const card = detailCard(r);
  assert.equal(card.props.title, '费用来源明细 · 6 条');
  assert.equal(card.props.description, '对应上方工程费用合计。每行一项来源，保留未纳入原因。零价保留为 ¥0，缺价不补零。');
  assert.deepEqual(descendants(card).filter(node => node.props?.class === 'detail-truncated').map(node => node.children), ['只返回了前 6 条（共 900 条）']);
  assert.equal(r.nodes().some(node => /分页查看|PDF 导出全部返回记录|服务端已截取/.test(String(node.children))), false);
  assert.equal(r.nodes().some(node => node.type?.name === 'el-tabs' && node.props?.class === 'detail-tabs'), false, 'one table needs no tabs');
  r.state.exportCompositionPdf();
  assert.deepEqual(plain(r.exports[0][1]), [
    { title: '费用来源与明确合计', selector: '.cost-composition-section' },
    { title: '环号变化与刀型贡献', selector: '.cost-trend-section' },
    { title: '费用来源明细', selector: '.cost-source-section', note: '对应上方工程费用合计。每行一项来源，保留未纳入原因。零价保留为 ¥0，缺价不补零。' },
  ]);
});
function loadCostChartOptions() {
  function load(file) {
    return compile(fs.readFileSync(file, 'utf8'), name => name === 'echarts' ? echartsStub : load(path.resolve(path.dirname(file), `${name}.ts`)));
  }
  return load(path.resolve(__dirname, '../utils/costChartOptions.ts'));
}

test('cost option builders preserve source order, colors and explicit amounts', () => {
  const { buildCompositionOption, buildTypeOption, buildCostTrendOption } = loadCostChartOptions();
  assert.equal(buildCompositionOption, undefined, 'the composition chart was replaced by the share bar');
  const type = buildTypeOption([{ tool_type: 'DISC', cost_sources: sources }, { tool_type: 'OTHER' }]);
  const trend = buildCostTrendOption(fixture({ url: 'cost_trend/', params: {} }).data, 'consumption');
  const expected = [['新装登记', '#3f5f7a'], ['已确认返修', '#6f8f6a'], ['历史登记', '#c2b8a3']];
  for (const option of [type, trend]) {
    assert.deepEqual(plain(option.series.slice(0, 3).map(item => [item.name, item.color])), expected);
  }
  assert.deepEqual(plain(type.series.map(item => item.data)), [[100, null], [20, null], [30, null]]);
  assert.deepEqual(plain(type.yAxis.data), ['滚刀', 'OTHER']);
  assert.equal(type.tooltip.valueFormatter(0), '¥0');
});

test('manufacturer colors stay stable across chart builders, ordering and focused subsets', () => {
  const { buildRelationshipOption, buildBrandTrendOption } = loadCostChartOptions();
  const relationship = buildRelationshipOption(brands);
  const price = fixture({ url: 'brand_comparison/', params: {} }).data;
  const trend = buildBrandTrendOption([...price.series].reverse(), price.time_axis, 'price', { unit: '元', ratio: false });
  assert.deepEqual(plain(relationship.series[0].data.map(item => [item.name, item.itemStyle.color])), [['A', '#c2b8a3'], ['B', '#6f8f6a']]);
  assert.deepEqual(plain(trend.series.map(item => [item.name, item.color])), [['B', '#6f8f6a'], ['A', '#c2b8a3']]);
  const focused = buildRelationshipOption([brands[0]]);
  assert.equal(focused.series[0].data[0].itemStyle.color, relationship.series[0].data[0].itemStyle.color);
  assert.equal(focused.series[0].label.show, true);
});

test('cost trend builder switches only the count or cumulative series and its axis', () => {
  const { buildCostTrendOption } = loadCostChartOptions();
  const data = fixture({ url: 'cost_trend/', params: {} }).data;
  const consumption = buildCostTrendOption(data, 'consumption');
  const cumulative = buildCostTrendOption(data, 'cumulative');
  assert.deepEqual(plain(consumption.series.slice(0, 3).map(item => item.data)), [[100, 0], [20, 0], [0, 30]]);
  assert.deepEqual(plain(cumulative.series.slice(0, 3)), plain(consumption.series.slice(0, 3)));
  const line = { type: 'line', yAxisIndex: 1, color: '#6b6962', smooth: false, symbol: 'circle', symbolSize: 5 };
  assert.deepEqual(plain(consumption.series[3]), { ...line, name: '实际更换数量', data: [2, 1] });
  assert.deepEqual(plain(cumulative.series[3]), { ...line, name: '累计明确金额', data: [120, 150] });
  assert.deepEqual(plain(consumption.yAxis[1]), { type: 'value', name: '更换数量（把）', minInterval: 1 });
  assert.deepEqual(plain(cumulative.yAxis[1]), { type: 'value', name: '累计金额（元）' });
});

test('the title-row refresh reloads cost data and stays busy until it finishes', async t => {
  let hold = null;
  const r = create(t, { request: config => hold ? hold.promise.then(() => fixture(config)) : fixture(config) });
  await r.mount();
  const actions = () => r.nodes().find(node => node.type?.name === 'AnalysisActions');
  assert.equal(actions().props.refresh, r.state.loadData); assert.equal(actions().props.refreshing, false);
  hold = deferred(); r.requests.length = 0;
  const done = actions().props.refresh(); await settle();
  assert.deepEqual(r.requests.map(call => call.url.split('/').at(-2)).sort(), ['cost_overview', 'cost_trend']);
  assert.equal(actions().props.refreshing, true);
  hold.resolve(); await done; await settle();
  assert.equal(actions().props.refreshing, false); assert.equal(r.state.costReady.value, true);
});
