// Run from web: node --test src/views/shield/analysis/__tests__/manufacturer-comparison.test.cjs
// 厂家对比（从成本页搬到寿命与厂家页的一整块）：筛选、对照表、两张图和厂家对照 PDF
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { setup, plain, deferred, settle, descendants } = require('./helpers.cjs');

const meta = scope => ({ schema_version: 2, generated_at: '2026-09-11T00:00:00Z', summary_status: 'CONFIRMED', opening_count: 2, draft_opening_count: 1, excluded_inactive_count: 0, unobserved_count: 0, warnings: [], scope: { project_name: '验收工程', shield_machine_name: '一号机', ...scope } });
const brands = [
  { manufacturer: 'A', total_cost: 130, count: 3, installation_count: 2, legacy_replacement_count: 1, avg_cost: 100, priced_count: 1, missing_price_count: 1, avg_lifespan: 80, lifespan_count: 2, paired_count: 2, abnormal_rate: 0.5, wear_recorded_count: 2, abnormal_count: 1 },
  { manufacturer: 'B', total_cost: 0, count: 2, installation_count: 2, legacy_replacement_count: 0, avg_cost: 0, priced_count: 1, avg_lifespan: null, lifespan_count: 0, paired_count: 0, abnormal_rate: null, wear_recorded_count: 0 },
];
const COMPARISON = 'brand_comparison/';
function fixture(config) {
  if (config.url.endsWith('filter_options/')) return { data: { manufacturers: ['A', 'B', 'C'] } };
  return { data: { meta: meta(config.params), items: brands, unknown_manufacturer_count: 1, unknown_manufacturer_amount: 20, pairing_unresolved_count: 1,
    manufacturers: ['A', 'B'],
    time_axis: [{ ring_no: '100', open_time: '2026-01-01' }, { ring_no: '200', open_time: '2026-02-01' }],
    series: [{ manufacturer: 'A', data: [100, null], count_data: [1, 0] }, { manufacturer: 'B', data: [null, 0], count_data: [0, 1] }],
    lifespan_series: [{ manufacturer: 'A', data: [80, null], count_data: [2, 0] }],
    abnormal_rate_series: [{ manufacturer: 'A', data: [0.5, null], count_data: [2, 0], abnormal_count_data: [1, 0] }],
    normal_rate_series: [{ manufacturer: 'A', data: [0.5, null], count_data: [2, 0], abnormal_count_data: [1, 0] }],
  } };
}
const emptyComparison = () => ({ meta: meta({}), items: [], time_axis: [], series: [], lifespan_series: [], abnormal_rate_series: [], normal_rate_series: [] });
function create(t, options = {}) { return setup(t, 'components/ManufacturerComparison.vue', { request: fixture, ...options }); }
function bindCharts(s) { for (const key of ['relationshipRef', 'brandTrendRef']) s[key].value = { key }; s.renderCharts(); }
const latest = (result, key) => result.charts.find(chart => chart.element.key === key)?.options.at(-1);

test('real GET calls retain inherited scope while local manufacturer selections only narrow it', async t => {
  const r = create(t, { props: { filter: { summary_status: 'CONFIRMED', project: 4, shield_machine: 9, start_ring: '100', end_ring: '200', manufacturers: 'A,B', stratum_types: 'ROCK' } } });
  await r.mount();
  for (const call of r.requests) { assert.equal(call.method, 'get'); assert.equal(call.params.project, 4); assert.equal(call.params.start_ring, '100'); assert.equal(call.params.manufacturers, 'A,B'); }
  r.state.brandFilterForm.manufacturers = ['A', 'C']; r.state.applyBrandFilter(); await settle();
  assert.deepEqual(plain(r.state.buildBrandFilter()), { summary_status: 'CONFIRMED', project: 4, shield_machine: 9, start_ring: '100', end_ring: '200', manufacturers: 'A', stratum_types: 'ROCK' });
  r.state.resetBrandFilter(); await settle(); assert.equal(r.state.buildBrandFilter().manufacturers, 'A,B');
});

test('one comparison request carries the page filter unchanged, beside the manufacturer options', async t => {
  const filter = { summary_status: 'CONFIRMED', project: 4, stratum_type: 'ROCK' };
  const r = create(t, { props: { filter } });
  await r.mount();
  // 对照表和两类趋势一次取齐，不再分三个接口各算一遍
  assert.deepEqual(r.requests.map(call => call.url.split('/').at(-2)).sort(), ['brand_comparison', 'filter_options']);
  assert.deepEqual(plain(r.requests.find(call => call.url.endsWith(COMPARISON)).params), filter);
  r.props.filter = { summary_status: 'CONFIRMED' }; await settle();
  assert.equal(r.requests.filter(item => item.url.endsWith(COMPARISON)).at(-1).params.stratum_type, undefined);
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

test('a failed request blocks export until a retry succeeds; legacy responses never become exportable', async t => {
  let fail = true;
  const r = create(t, { request: config => { if (fail && config.url.endsWith(COMPARISON)) throw new Error('offline'); return fixture(config); } });
  await r.mount(); assert.equal(r.state.brandReady.value, false);
  r.state.exportPdf(); assert.equal(r.exports.length, 0);
  fail = false; await r.state.loadBrandData(); assert.equal(r.state.brandReady.value, true); assert.equal(r.state.brandError.value, '');
  const legacy = create(t, { request: config => { const response = fixture(config); if (!config.url.endsWith('filter_options/')) delete response.data.meta; return response; } });
  await legacy.mount(); assert.equal(legacy.state.brandReady.value, false);
  legacy.state.exportPdf(); assert.equal(legacy.exports.length, 0);
});

test('export takes the comparison block with the successful scope and how the charts were narrowed', async t => {
  const r = create(t); await r.mount(); r.state.exportPdf();
  const [title, sections, metaItems, tables] = r.exports[0];
  assert.equal(title, '数据分析-厂家对照与服役表现');
  assert.deepEqual(plain(sections), [{ title: '厂家对照与指标', selector: '.brand-section', note: '厂家表不含未知厂家，不能将表内合计当作工程总计。' }]);
  assert.ok(metaItems.some(item => item.value.includes('验收工程')));
  assert.deepEqual(plain(metaItems.slice(-2)), [{ label: '图形展示', value: '按明确金额前 8 家；表格保留全部' }, { label: '当前趋势指标', value: '按开仓环号：安装记录均价' }]);
  assert.equal(tables, undefined);
});

test('the page refreshes and exports through what the component exposes', t => {
  const source = fs.readFileSync(path.resolve(__dirname, '../components/ManufacturerComparison.vue'), 'utf8');
  assert.match(source, /defineExpose\(\{ load: loadBrandData, loading: brandLoading, ready: brandReady, exportPdf \}\)/);
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
    if (config.url.endsWith(COMPARISON)) {
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
    if (config.url.endsWith(COMPARISON)) {
      delete response.data.lifespan_series;
      response.data.items = response.data.items.map(({ avg_lifespan, lifespan_count, paired_count, ...item }) => item);
    }
    return response;
  } });
  await r.mount();
  assert.equal(r.state.brandReady.value, false);
  // 测试工具把组件和 composable 编译在不同的 VM 里，instanceof Error 判断会换掉报错文字；这里在校验函数上核对原文，再确认查询进入错误状态
  assert.throws(() => r.state.requireBrandData({ meta: meta({}), items: brands }), {
    message: '厂家分析服务尚未更新，缺少完整的服役与配对数据。请重启后端后重新加载。',
  });
  assert.ok(r.state.brandError.value);
  assert.equal(r.state.selectedTrend.value.length, 0, 'Do not retain price charts beside invalid service data');
  r.state.exportPdf(); assert.equal(r.exports.length, 0);
});

test('manufacturer contract requires arrays, finite nullable averages and integer sample counts without coercion', t => {
  const r = create(t);
  const valid = () => ({ ...emptyComparison(), items: [{ ...brands[0] }] });
  const changes = [
    data => { delete data.items; }, data => { data.items = {}; }, data => { data.lifespan_series = null; },
    data => { delete data.series; }, data => { delete data.time_axis; },
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

test('valid empty series and nullable averages remain honest empty states, not service errors', async t => {
  const r = create(t, { request: config => {
    const response = fixture(config);
    if (config.url.endsWith(COMPARISON)) {
      response.data.items = [{ ...brands[1], avg_cost: null, priced_count: 0 }];
      response.data.lifespan_series = [];
    }
    return response;
  } });
  await r.mount();
  assert.equal(r.state.brandReady.value, true); assert.equal(r.state.brandError.value, '');
  assert.equal(r.state.relationshipItems.value.length, 0); assert.equal(r.state.brandSummaryItems.value.length, 1);
  const card = r.nodes().find(node => node.props?.title === '安装均价与已拆刀服役环数');
  assert.equal(card.props['is-empty'], true); assert.equal(card.props.error, '');
  assert.doesNotThrow(() => r.state.requireBrandData(emptyComparison()));
});

test('complete eight-manufacturer data displays every relationship point', async t => {
  const names = Array.from({ length: 8 }, (_, index) => `厂家${index + 1}`);
  const r = create(t, { request: config => {
    const response = fixture(config);
    if (config.url.endsWith(COMPARISON)) {
      response.data.items = names.map((manufacturer, index) => ({ ...brands[0], manufacturer, avg_cost: 100 + index, avg_lifespan: 80 + index, paired_count: 58, lifespan_count: 58 }));
    }
    return response;
  } });
  await r.mount(); bindCharts(r.state);
  assert.equal(r.state.brandReady.value, true);
  assert.equal(latest(r, 'relationshipRef').series[0].data.length, 8);
});

test('a chart keeps its options when only the other one changes, and is rebuilt on a new element', async t => {
  const r = create(t); await r.mount(); bindCharts(r.state);
  const counts = () => r.charts.map(chart => chart.options.length);
  assert.deepEqual(counts(), [1, 1]);
  r.state.renderCharts(); assert.deepEqual(counts(), [1, 1]);
  r.state.brandMetric.value = 'service'; r.state.renderCharts();
  assert.deepEqual(counts(), [1, 2]);
  r.state.relationshipRef.value = { key: 'replacement-element' }; r.state.renderCharts();
  assert.equal(r.charts[0].disposed, true); assert.equal(r.charts[2].options.length, 1);
  r.unmount(); assert.ok(r.charts.every(chart => chart.disposed));
});

test('records outside the manufacturer table show one line only when there are any', async t => {
  const r = create(t); await r.mount();
  const line = result => result.nodes().filter(node => /不在本表|厂家缺失|厂家未核实/.test(String(node.children))).map(node => node.children);
  assert.deepEqual(line(r), ['1 条更换记录缺厂家、¥20明确金额厂家未核实，不在本表']);
  const clean = create(t, { request: config => {
    const response = fixture(config);
    if (config.url.endsWith(COMPARISON)) Object.assign(response.data, { unknown_manufacturer_count: 0, unknown_manufacturer_amount: 0 });
    return response;
  } });
  await clean.mount();
  assert.equal(clean.state.brandReady.value, true);
  assert.deepEqual(line(clean), []);
});

test('a slow manufacturer request keeps loading true until it returns', async t => {
  const hold = deferred();
  const r = create(t, { request: config => config.url.endsWith(COMPARISON) ? hold.promise.then(() => fixture(config)) : fixture(config) });
  const mounted = r.mount(); await settle();
  assert.equal(r.state.brandLoading.value, true);
  hold.resolve(); await mounted; await settle();
  assert.equal(r.state.brandLoading.value, false); assert.equal(r.state.brandReady.value, true);
});
