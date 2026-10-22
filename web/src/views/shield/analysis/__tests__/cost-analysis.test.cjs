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
function bindCharts(s) { for (const key of ['costTrendRef', 'typeRef', 'relationshipRef', 'brandTrendRef']) s[key].value = { key }; s.renderCharts(); }
const latest = (result, key) => result.charts.find(chart => chart.element.key === key)?.options.at(-1);
const detailCard = result => result.nodes().find(node => node.props?.class === 'analysis-detail-card');

test('real GET calls retain inherited strata while local manufacturer selections only narrow scope', async t => {
  const r = create(t, { props: { filter: { summary_status: 'CONFIRMED', project: 4, shield_machine: 9, start_ring: '100', end_ring: '200', manufacturers: 'A,B', stratum_types: 'ROCK' } } });
  await r.mount();
  for (const call of r.requests) { assert.equal(call.method, 'get'); assert.equal(call.params.project, 4); assert.equal(call.params.start_ring, '100'); assert.equal(call.params.manufacturers, 'A,B'); }
  r.state.brandFilterForm.manufacturers = ['A', 'C']; r.state.applyBrandFilter(); await settle();
  assert.deepEqual(plain(r.state.buildBrandFilter()), { summary_status: 'CONFIRMED', project: 4, shield_machine: 9, start_ring: '100', end_ring: '200', manufacturers: 'A', stratum_types: 'ROCK' });
  r.state.resetBrandFilter(); await settle(); assert.equal(r.state.buildBrandFilter().manufacturers, 'A,B');
});

test('top stratum condition reaches every cost and manufacturer endpoint with no standalone block', async t => {
  const r = create(t, { props: { filter: { summary_status: 'CONFIRMED', stratum_type: 'ROCK' } } });
  await r.mount();
  const endpoints = ['cost_overview/', 'cost_trend/', 'brand_cost/', 'brand_price_trend/', 'brand_performance_trend/'];
  for (const endpoint of endpoints) {
    const call = r.requests.find(item => item.url.endsWith(endpoint));
    assert.ok(call, endpoint);
    assert.equal(call.params.stratum_type, 'ROCK', endpoint);
  }
  assert.equal(r.nodes().some(node => node.type?.name === 'StratumManufacturerComparison'), false);
  assert.equal(r.nodes().some(node => node.type?.name === 'el-form-item' && node.props.label === '地层'), false);
  r.state.resetBrandFilter(); await settle();
  assert.equal(r.state.buildBrandFilter().stratum_type, 'ROCK');
  r.props.filter = { summary_status: 'CONFIRMED' }; await settle();
  for (const endpoint of endpoints) {
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
  assert.equal(r.state.unknownManufacturerAmount.value, 20);
});

test('manufacturer relationships require both sample groups, retain table rows and single-point zero trends', async t => {
  const r = create(t); await r.mount(); bindCharts(r.state);
  assert.equal(r.state.brandSummaryItems.value.length, 2); assert.equal(r.state.relationshipItems.value.length, 1);
  const scatter = latest(r, 'relationshipRef'); assert.deepEqual(plain(scatter.series[0].data[0].value), [100, 80]);
  assert.match(scatter.tooltip.formatter({ data: scatter.series[0].data[0] }), /1 个有价样本/);
  assert.match(scatter.tooltip.formatter({ data: scatter.series[0].data[0] }), /2 个闭合段/);
  const line = latest(r, 'brandTrendRef'); assert.equal(line.series.length, 2); assert.equal(line.series[0].connectNulls, false);
  assert.deepEqual(plain(line.series[1].data), [null, 0]); assert.equal(r.state.hasTrendData.value, true);
  r.state.focusManufacturer('B'); r.state.brandMetric.value = 'service'; r.state.renderCharts();
  assert.equal(r.state.hasTrendData.value, false); assert.equal(r.state.brandSummaryItems.value.length, 2);
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

test('a failed brand request leaves engineering costs available and retry recovers brand export', async t => {
  let fail = true;
  const r = create(t, { request: config => { if (fail && config.url.endsWith('brand_price_trend/')) throw new Error('offline'); return fixture(config); } });
  await r.mount(); assert.equal(r.state.costReady.value, true); assert.equal(r.state.brandReady.value, false);
  r.state.exportTrendPdf(); assert.equal(r.exports.length, 0);
  fail = false; await r.state.loadBrandData(); assert.equal(r.state.brandReady.value, true); assert.equal(r.state.brandError.value, '');
});

test('legacy responses never display obsolete statistics or become exportable', async t => {
  const r = create(t, { request: config => { const response = fixture(config); if (!config.url.endsWith('filter_options/')) delete response.data.meta; return response; } });
  await r.mount(); assert.equal(r.state.costReady.value, false); assert.equal(r.state.brandReady.value, false);
  assert.equal(r.state.sources.value, undefined); assert.ok(r.state.costError.value);
  r.state.exportCompositionPdf(); r.state.exportTrendPdf(); assert.equal(r.exports.length, 0);
});

test('exports include complete source and vendor tables with successful scope; drill-through is readonly', async t => {
  const r = create(t); await r.mount(); r.state.exportCompositionPdf(); r.state.exportTrendPdf();
  assert.equal(r.exports.length, 2);
  assert.ok(r.exports[0][1].some(section => section.selector === '.cost-source-section'));
  assert.equal(r.exports[1][1][0].selector, '.cost-brand-section');
  assert.ok(r.exports[0][2].some(item => item.value.includes('验收工程')));
  r.state.openOpening(sourceRows[0]); assert.deepEqual(plain(r.routes[0]), { path: '/shield/toolChangeDetail', query: { warehouse_id: '11', warehouse_code: 'W-11', mode: 'view' } });
});

test('real template binds chart modes, ready export gates and complete scrollable tables', async t => {
  const r = create(t); let nodes = r.nodes();
  const exportItems = () => r.nodes().find(node => node.type?.name === 'AnalysisActions').props.exports;
  assert.deepEqual(plain(exportItems().map(item => [item.label, item.disabled])), [['费用来源 PDF', true], ['厂家表现 PDF', true]]);
  await r.mount(); nodes = r.nodes();
  assert.deepEqual(plain(exportItems().map(item => item.disabled)), [false, false]);
  assert.equal(exportItems()[0].run, r.state.exportCompositionPdf); assert.equal(exportItems()[1].run, r.state.exportTrendPdf);
  const radios = nodes.filter(node => node.type?.name === 'el-radio-button'); assert.deepEqual(radios.map(node => node.props.label), ['consumption', 'cumulative']);
  const tables = nodes.filter(node => node.type?.name === 'el-table'); assert.equal(tables.length, 3);
  const sourceTable = tables.find(node => node.props['data-analysis-table'] === 'sources');
  assert.equal(sourceTable.props.data.length, 6); assert.equal(sourceTable.props['max-height'], 420);
});

test('deactivation rejects late responses and unmount releases every chart', async t => {
  const wait = deferred(); let delayed = false;
  const r = create(t, { request: config => delayed ? wait.promise : fixture(config) });
  await r.mount(); bindCharts(r.state); delayed = true;
  const pending = r.state.loadData(); r.hooks.onDeactivated.forEach(hook => hook());
  wait.resolve(fixture({ url: 'cost_overview/', params: {} })); await pending;
  assert.equal(r.state.costReady.value, false); r.unmount(); assert.ok(r.charts.every(chart => chart.disposed));
});

test('manufacturer filters sit on the section heading with labels inside the controls; reset preserves inherited scope', async t => {
  const r = create(t, { props: { filter: { project: 4, start_ring: '100', end_ring: '200', manufacturer: 'A', summary_status: 'CONFIRMED' } } });
  await r.mount();
  const heading = r.nodes().find(node => node.props?.class === 'section-heading');
  const headingNodes = descendants(heading);
  assert.equal(headingNodes.find(node => node.type === 'h3').children, '厂家对比');
  assert.equal(headingNodes.find(node => node.props?.class === 'section-note').children, '沿用上方条件，只收窄厂家');
  assert.equal(headingNodes.find(node => node.type?.name === 'InfoTip').props.content, '厂家表不含未知厂家，不能将表内合计当作工程总计。');
  const form = headingNodes.find(node => node.type?.name === 'el-form' && node.props?.class === 'brand-filter-form');
  const controls = descendants(form).filter(node => node.type?.name === 'el-select');
  assert.deepEqual(controls.map(node => node.props['aria-label']), ['对比厂家', '图上显示']);
  assert.deepEqual(controls.map(node => descendants(node).find(child => child.props?.class === 'control-label').children), ['对比厂家', '图上显示']);
  const reset = descendants(form).find(node => node.type?.name === 'el-button' && node.props?.onClick === r.state.resetBrandFilter);
  assert.ok(reset); r.state.brandFilterForm.manufacturers = ['A']; r.state.applyBrandFilter(); await settle();
  reset.props.onClick(); await settle();
  assert.deepEqual(plain(r.state.buildBrandFilter()), { project: 4, start_ring: '100', end_ring: '200', manufacturer: 'A', summary_status: 'CONFIRMED' });
});

test('normal and abnormal trend tooltips show their own numerators over recorded closed-old-tool samples', async t => {
  const r = create(t, { request: config => {
    const response = fixture(config);
    if (config.url.endsWith('brand_performance_trend/')) {
      response.data.abnormal_rate_series = [{ manufacturer: 'A', data: [1, null], count_data: [3, 0], abnormal_count_data: [3, 0] }];
      response.data.normal_rate_series = [{ manufacturer: 'A', data: [0, null], count_data: [3, 0], abnormal_count_data: [3, 0] }];
    }
    return response;
  } });
  await r.mount(); bindCharts(r.state);
  r.state.brandMetric.value = 'abnormal'; r.state.renderCharts();
  let tooltip = latest(r, 'brandTrendRef').tooltip.formatter([{ dataIndex: 0, seriesName: 'A' }]);
  assert.match(tooltip, /100\.0%/); assert.match(tooltip, /非正常数 \/ 有记录数：3 \/ 3/); assert.match(tooltip, /已闭合配对旧刀/);
  r.state.brandMetric.value = 'normal'; r.state.renderCharts();
  tooltip = latest(r, 'brandTrendRef').tooltip.formatter([{ dataIndex: 0, seriesName: 'A' }]);
  assert.match(tooltip, /0\.0%/); assert.match(tooltip, /正常数 \/ 有记录数：0 \/ 3/);
  const noSamples = latest(r, 'brandTrendRef').tooltip.formatter([{ dataIndex: 1, seriesName: 'A' }]);
  assert.match(noSamples, /无有效样本/); assert.match(noSamples, /正常数 \/ 有记录数：0 \/ 0/);
  const card = r.nodes().find(node => node.props?.title === r.state.trendConfig.value.title);
  assert.match(card.props.description, /100% 表示这些样本全部归入当前类别/); assert.match(card.props.description, /不表示全部供货刀具失效/);
});

test('a V2 response missing service fields is an explicit service error, not empty manufacturer charts', async t => {
  const r = create(t, { request: config => {
    const response = fixture(config);
    if (config.url.endsWith('brand_cost/')) {
      delete response.data.service_rows;
      response.data.items = response.data.items.map(({ avg_lifespan, lifespan_count, paired_count, ...item }) => item);
    }
    return response;
  } });
  await r.mount();
  assert.equal(r.state.costReady.value, true);
  assert.equal(r.state.brandReady.value, false);
  // The helper compiles the SFC and composable in separate VM realms, so its
  // instanceof Error boundary replaces the message. Verify exact production
  // error at the validator, then verify the actual query enters error state.
  assert.throws(() => r.state.requireBrandData({ meta: meta({}), items: brands }), {
    message: '厂家分析服务尚未更新，缺少完整的服役与配对数据。请重启后端后重新加载。',
  });
  assert.ok(r.state.brandError.value);
  assert.equal(r.state.selectedTrend.value.length, 0, 'Do not retain price charts beside invalid service data');
  r.state.exportTrendPdf(); assert.equal(r.exports.length, 0);
  assert.equal(detailCard(r).props.error, '', 'the source tab keeps the engineering cost state');
  r.state.detailTab.value = 'service';
  assert.equal(detailCard(r).props.error, r.state.brandError.value);
  assert.equal(detailCard(r).props.onRetry, r.state.detailState.value.retry); assert.equal(r.state.detailState.value.retry, r.state.loadBrandData);
});

test('manufacturer contract requires arrays, finite nullable averages and integer sample counts without coercion', t => {
  const r = create(t);
  const valid = () => ({ meta: meta({}), items: [{ ...brands[0] }], service_rows: [] });
  const changes = [
    data => { delete data.items; }, data => { data.items = {}; }, data => { data.service_rows = null; },
    data => { data.items = [null]; }, data => { delete data.items[0].avg_lifespan; }, data => { data.items[0].avg_lifespan = Infinity; },
    data => { data.items[0].avg_cost = '100'; }, data => { data.items[0].avg_cost = NaN; },
    data => { data.items[0].lifespan_count = -1; }, data => { data.items[0].lifespan_count = 0.5; },
    data => { delete data.items[0].paired_count; }, data => { data.items[0].paired_count = '2'; },
    data => { data.items[0].priced_count = null; }, data => { data.items[0].priced_count = Infinity; },
  ];
  for (const change of changes) {
    const data = valid(); change(data);
    assert.throws(() => r.state.requireBrandData(data), /缺少完整的服役与配对数据/);
  }
  const data = valid(); assert.equal(r.state.requireBrandData(data), data);
});

test('valid empty service arrays and nullable averages remain honest empty states, not service errors', async t => {
  const r = create(t, { request: config => {
    const response = fixture(config);
    if (config.url.endsWith('brand_cost/')) {
      response.data.items = [{ ...brands[1], avg_cost: null, priced_count: 0 }];
      response.data.service_rows = [];
    }
    return response;
  } });
  await r.mount();
  assert.equal(r.state.brandReady.value, true); assert.equal(r.state.brandError.value, '');
  assert.equal(r.state.relationshipItems.value.length, 0); assert.equal(r.state.serviceRows.value.length, 0);
  assert.equal(r.state.brandSummaryItems.value.length, 1);
  r.state.detailTab.value = 'service';
  const cards = [r.nodes().find(node => node.props?.title === '安装均价与已拆刀服役环数'), detailCard(r)];
  assert.ok(cards.every(node => node.props['is-empty'] === true && node.props.error === ''));
  assert.doesNotThrow(() => r.state.requireBrandData({ meta: meta({}), items: [], service_rows: [] }));
});

test('complete eight-manufacturer data displays every relationship point and all 469 service rows', async t => {
  const names = Array.from({ length: 8 }, (_, index) => `厂家${index + 1}`);
  const service = Array.from({ length: 469 }, (_, index) => ({ opening_id: 11, warehouse_id: 'W-11', old_tool_number: `OLD-${index}`, manufacturer: names[index % 8], service_rings: 80, paired: true }));
  const r = create(t, { request: config => {
    const response = fixture(config);
    if (config.url.endsWith('brand_cost/')) {
      response.data.items = names.map((manufacturer, index) => ({ ...brands[0], manufacturer, avg_cost: 100 + index, avg_lifespan: 80 + index, paired_count: 58, lifespan_count: 58 }));
      response.data.service_rows = service; response.data.service_rows_total = 469;
    }
    return response;
  } });
  await r.mount(); bindCharts(r.state);
  assert.equal(r.state.brandReady.value, true);
  assert.equal(latest(r, 'relationshipRef').series[0].data.length, 8);
  assert.equal(r.state.serviceRows.value.length, 469);
  r.state.detailTab.value = 'service';
  assert.equal(detailCard(r).props['is-empty'], false);
  const tables = r.nodes().filter(node => node.type?.name === 'el-table');
  assert.equal(tables.find(node => node.props['data-analysis-table'] === 'service').props.data.length, 50);
  r.state.exportTrendPdf();
  assert.equal(r.exports[0][3][0].rows.length, 469);
});

test('long source and service tables paginate locally while exporting every successful row', async t => {
  const rows = Array.from({ length: 1646 }, (_, id) => ({ ...sourceRows[id % sourceRows.length], id: `source-${id}` }));
  const service = Array.from({ length: 823 }, (_, id) => ({ detail_id: id, opening_id: 11, warehouse_id: 'W-11', ring_no: '100',
    cutter_position_no: '1', manufacturer: 'A', old_tool_number: `OLD-${id}`, installation_ring_no: '20', service_rings: 80, paired: true }));
  const r = create(t, { request: config => {
    const response = fixture(config);
    if (config.url.endsWith('cost_overview/')) response.data.source_rows = rows;
    if (config.url.endsWith('brand_cost/')) response.data.service_rows = service;
    return response;
  } });
  await r.mount();
  const initialRequests = r.requests.length;
  assert.equal(r.state.visibleSourceRows.value.length, 50); assert.equal(r.state.visibleServiceRows.value.length, 50);
  r.state.sourcePage.value = 33; r.state.servicePage.value = 17;
  assert.equal(r.state.visibleSourceRows.value.length, 46); assert.equal(r.state.visibleServiceRows.value.length, 23);
  assert.equal(r.state.visibleSourceRows.value[0].id, 'source-1600');
  assert.equal(r.state.visibleServiceRows.value[0].detail_id, 800);
  r.state.exportCompositionPdf(); r.state.exportTrendPdf();
  assert.equal(r.exports[0][3][0].rows.length, 1646); assert.equal(r.exports[1][3][0].rows.length, 823);
  assert.equal(r.exports[0][3][0].rows[4][3], '¥0'); assert.equal(r.exports[0][3][0].rows[5][3], '未记录');
  assert.match(r.exports[1][3][0].rows[822][3], /OLD-822/);
  r.state.sourcePageSize.value = 100; r.state.servicePageSize.value = 200;
  assert.equal(r.state.sourcePage.value, 1); assert.equal(r.state.servicePage.value, 1);
  assert.equal(r.state.visibleSourceRows.value.length, 100); assert.equal(r.state.visibleServiceRows.value.length, 200);
  await settle(); assert.equal(r.requests.length, initialRequests, 'Paging does not issue network queries');
  r.state.sourcePage.value = 2; r.state.servicePage.value = 2;
  r.props.filter = { project: 2, summary_status: 'CONFIRMED' };
  assert.equal(r.state.sourcePage.value, 1); assert.equal(r.state.servicePage.value, 1);
  assert.equal(r.state.visibleSourceRows.value.length, 0); assert.equal(r.state.visibleServiceRows.value.length, 0);
});

test('trend requests omit duplicate detail payloads without changing the global filter', async t => {
  const r = create(t); await r.mount();
  const source = fs.readFileSync(path.resolve(__dirname, '../../../../utils/service.ts'), 'utf8');
  const serializer = source.slice(source.indexOf('paramsSerializer: {') + 'paramsSerializer: '.length, source.indexOf('\n\t});', source.indexOf('paramsSerializer: {'))).trim().replace(/,$/, '');
  const { value } = compile(`import qs from 'qs'; export const value = ${serializer};`, () => ({ default: require('qs') }));
  for (const call of r.requests) {
    const isTrend = /brand_(price|performance)_trend/.test(call.url);
    assert.equal(call.params.include_details, isTrend ? 'false' : undefined);
    const query = new URLSearchParams(value.serialize(call.params));
    assert.equal(query.get('include_details'), isTrend ? 'false' : null);
  }
  assert.equal(r.props.filter.include_details, undefined);
});

test('unrelated charts retain their options and user view when a single metric changes', async t => {
  const r = create(t); await r.mount(); bindCharts(r.state);
  const counts = () => r.charts.map(chart => chart.options.length);
  // 图表顺序：环号趋势、刀型贡献、厂家关系、厂家趋势（费用来源构成图已由比例条代替）
  assert.deepEqual(counts(), [1, 1, 1, 1]);
  r.state.renderCharts(); assert.deepEqual(counts(), [1, 1, 1, 1]);
  r.state.brandMetric.value = 'service'; r.state.renderCharts();
  assert.deepEqual(counts(), [1, 1, 1, 2]);
  r.state.costMode.value = 'cumulative'; r.state.renderCharts();
  assert.deepEqual(counts(), [2, 1, 1, 2]);
  r.state.sourcePage.value = 2; r.state.renderCharts();
  assert.deepEqual(counts(), [2, 1, 1, 2]);
  r.state.relationshipRef.value = { key: 'replacement-element' }; r.state.renderCharts();
  assert.equal(r.charts[2].disposed, true); assert.equal(r.charts[4].options.length, 1);
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

test('records outside the manufacturer table show one line only when there are any', async t => {
  const r = create(t); await r.mount();
  const line = result => result.nodes().filter(node => /不在本表|厂家缺失|厂家未核实/.test(String(node.children))).map(node => node.children);
  assert.deepEqual(line(r), ['1 条更换记录缺厂家、¥20明确金额厂家未核实，不在本表']);
  const clean = create(t, { request: config => {
    const response = fixture(config);
    if (config.url.endsWith('brand_cost/')) Object.assign(response.data, { unknown_manufacturer_count: 0, source_rows: sourceRows.filter(row => row.manufacturer) });
    return response;
  } });
  await clean.mount();
  assert.equal(clean.state.brandReady.value, true);
  assert.deepEqual(line(clean), []);
});

test('one detail card switches source and service tables, counts rows and flags only server truncation', async t => {
  const r = create(t, { request: config => {
    const response = fixture(config);
    if (config.url.endsWith('cost_overview/')) Object.assign(response.data, { source_rows_total: 900, source_rows_truncated: true });
    return response;
  } });
  const card = () => descendants(detailCard(r));
  const labels = () => card().filter(node => node.type?.name === 'el-tab-pane').map(node => node.props.label);
  const tip = () => card().find(node => node.type?.name === 'InfoTip').props.content;
  assert.deepEqual(labels(), ['费用来源明细', '旧刀配对与服役段']);
  await r.mount();
  assert.deepEqual(labels(), ['费用来源明细 · 6 条', '旧刀配对与服役段 · 1 条']);
  assert.equal(tip(), '对应上方工程费用合计，不随厂家图形聚焦变化。每行一项来源，保留未纳入原因。零价保留为 ¥0，缺价不补零。');
  assert.deepEqual(card().filter(node => node.props?.class === 'detail-truncated').map(node => node.children), ['只返回了前 6 条（共 900 条）']);
  assert.equal(r.nodes().some(node => /分页查看|PDF 导出全部返回记录|服务端已截取/.test(String(node.children))), false);
  // 两个页签的内容都保持渲染（v-show），导出时各自的表都能找到
  const panes = () => card().filter(node => node.dirs).map(node => [node.dirs[0].value, descendants(node)[1].props.class]);
  assert.deepEqual(panes(), [[true, 'cost-source-section'], [false, 'cost-service-section']]);
  r.state.detailTab.value = 'service';
  assert.deepEqual(panes(), [[false, 'cost-source-section'], [true, 'cost-service-section']]);
  assert.equal(tip(), '完整保留厂家查询返回的已拆刀及待核对样本。服役段不是失效寿命；原安装信息只在系统配对可追溯时展示。');
  assert.deepEqual(card().filter(node => node.props?.class === 'detail-truncated').map(node => node.children), ['只返回了前 6 条（共 900 条）'], 'service rows were not truncated');

  r.state.exportCompositionPdf(); r.state.exportTrendPdf();
  assert.deepEqual(plain(r.exports[0][1]), [
    { title: '费用来源与明确合计', selector: '.cost-composition-section' },
    { title: '环号变化与刀型贡献', selector: '.cost-trend-section' },
    { title: '费用来源明细', selector: '.cost-source-section', note: '对应上方工程费用合计，不随厂家图形聚焦变化。每行一项来源，保留未纳入原因。零价保留为 ¥0，缺价不补零。' },
  ]);
  assert.deepEqual(plain(r.exports[1][1]), [
    { title: '厂家对照、指标与配对依据', selector: '.cost-brand-section', note: '厂家表不含未知厂家，不能将表内合计当作工程总计。' },
    { title: '旧刀配对与服役段', selector: '.cost-service-section', note: tip() },
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
  const price = fixture({ url: 'brand_price_trend/', params: {} }).data;
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

test('the title-row refresh reloads cost and manufacturer data and stays busy until both finish', async t => {
  let hold = null;
  const r = create(t, { request: config => hold && /brand_/.test(config.url) ? hold.promise.then(() => fixture(config)) : fixture(config) });
  await r.mount();
  const actions = () => r.nodes().find(node => node.type?.name === 'AnalysisActions');
  assert.equal(actions().props.refresh, r.state.refreshAll); assert.equal(actions().props.refreshing, false);
  hold = deferred(); r.requests.length = 0;
  const done = actions().props.refresh(); await settle();
  assert.deepEqual(r.requests.map(call => call.url.split('/').at(-2)).sort(), ['brand_cost', 'brand_performance_trend', 'brand_price_trend', 'cost_overview', 'cost_trend']);
  assert.equal(r.state.costLoading.value, false, 'cost data is already back');
  assert.equal(actions().props.refreshing, true, 'still busy while manufacturer data loads');
  hold.resolve(); await done; await settle();
  assert.equal(actions().props.refreshing, false);
  assert.equal(r.state.costReady.value, true); assert.equal(r.state.brandReady.value, true);
});
