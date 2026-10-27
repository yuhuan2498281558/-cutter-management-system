// Run from web: node --test src/views/shield/analysis/__tests__/life-analysis.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { setup, plain, compile, echartsStub } = require('./helpers.cjs');

const meta = scope => ({ schema_version: 2, generated_at: '2026-10-27T00:00:00Z', summary_status: 'CONFIRMED', opening_count: 15, draft_opening_count: 0, excluded_inactive_count: 0, unobserved_count: 0, warnings: [], scope: { project_name: '寿命验收工程', ...scope } });
const spread = values => values.length >= 5 ? { count: values.length, median: 150, q1: 140, q3: 160 } : { count: values.length, values };
const summary = (removed, extra = {}) => ({
  removed_count: removed, life_km: removed ? spread(Array.from({ length: removed }, (_, index) => 100 + index)) : null,
  abnormal_count: 1, classified_count: removed, unclassified_count: 0, wear_per_100km: removed ? spread([1.5]) : null,
  priced_count: removed, cost_per_km: removed >= 5 ? 31.04 : null, in_service_count: 1, in_service_km: spread([12]), ...extra,
});
const segment = (id, manufacturer, radius, km, state = 'NORMAL', type = 'DISC') => ({
  detail_id: id, installation_detail_id: id + 100, cutter_position_no: String(id), tool_parent_type: type, radius_mm: radius,
  manufacturer, installation_ring_no: '100', ring_no: '200', service_rings: 100, revolutions: 12000, km, estimated_share: 1,
  wear_state: state, blade_wear_amount: 8, wear_per_100km: 2, price: 5000,
});
const data = () => ({
  groups: [
    { tool_parent_type: 'DISC', label: '滚刀', manufacturers: ['甲厂', '乙厂'], summary: summary(6), bands: [
      { radius_min: 0, radius_max: 1000, trajectory_count: 1, summary: summary(1), cells: [{ manufacturer: '甲厂', ...summary(1) }], trajectories: [
        { radius_mm: 135, positions: ['1'], summary: summary(1), cells: [{ manufacturer: '甲厂', ...summary(1) }] }] },
      { radius_min: 6000, radius_max: 7000, trajectory_count: 2, summary: summary(5), cells: [{ manufacturer: '甲厂', ...summary(5) }, { manufacturer: '乙厂', ...summary(0, { in_service_count: 2 }) }], trajectories: [
        { radius_mm: 6770.8, positions: ['78', 'Y3'], summary: summary(3), cells: [{ manufacturer: '甲厂', ...summary(3) }] },
        { radius_mm: 6809.8, positions: ['79', 'Y1'], summary: summary(2), cells: [{ manufacturer: '甲厂', ...summary(2) }] }] }] },
    { tool_parent_type: 'SCRAPER', label: '刮刀', manufacturers: ['乙厂'], summary: summary(1), bands: [
      { radius_min: 3000, radius_max: 4000, trajectory_count: 1, summary: summary(1), cells: [{ manufacturer: '乙厂', ...summary(1) }], trajectories: [
        { radius_mm: 3430, positions: ['S1L', 'S1R'], summary: summary(1), cells: [{ manufacturer: '乙厂', ...summary(1) }] }] }] },
  ],
  segments: [
    segment(1, '甲厂', 135, 6.4), segment(78, '甲厂', 6770.8, 300, 'ABNORMAL'), segment(79, '甲厂', 6770.8, 200),
    segment(80, '乙厂', 6809.8, 250), segment(81, '甲厂', 6809.8, 420), segment(90, '乙厂', 3430, 150, 'NORMAL', 'SCRAPER'),
  ],
  in_service: [
    { detail_id: 5, cutter_position_no: '1', tool_parent_type: 'DISC', radius_mm: 135, manufacturer: '甲厂', installation_ring_no: '400', through_ring_no: '487', revolutions: 10000, km: 8.5, estimated_share: 1 },
    { detail_id: 6, cutter_position_no: 'S1L', tool_parent_type: 'SCRAPER', radius_mm: 3430, manufacturer: '乙厂', installation_ring_no: '487', through_ring_no: '487', revolutions: 0, km: 0, estimated_share: null },
  ],
  positions: [
    { tool_parent_type: 'DISC', cutter_position_no: '1', radius_mm: 135, removed_count: 1, removed_km: 6.4, in_service_km: 8.5, covered_km: 14.9 },
    { tool_parent_type: 'SCRAPER', cutter_position_no: 'S1L', radius_mm: 3430, removed_count: 1, removed_km: 150, in_service_km: 0, covered_km: 150 },
  ],
  excluded: [{ reason: '厂家反馈未确认', count: 232 }, { reason: '旧刀身份未确认', count: 122 }],
  excluded_rows: [{ detail_id: 7, opening_id: 31, warehouse_id: 'W-31', ring_no: '317', cutter_position_no: '12', tool_parent_type: 'DISC', old_tool_number: 'OLD-7', manufacturer: '甲厂', reason: '厂家反馈未确认' }],
  revolution_basis: { ring_width_mm: 2000, reference_penetration_mm: 16.67, reference_revolutions_per_ring: 120, reference_penetration_range_mm: [14, 21], tunneling_ring_count: 1, estimated_share: 1 },
  basis: { mileage: '里程口径', revolutions: '圈数口径', life: '寿命口径' },
});
function create(t, options = {}) {
  return setup(t, 'pages/LifeAnalysis.vue', { request: config => ({ data: { ...data(), meta: meta(config.params) } }), ...options });
}
function charts(r) { r.state.curveRef.value = { key: 'curve' }; r.state.renderCharts(); return r.charts.at(-1).options.at(-1); }

test('the page asks life_mileage with the exact applied filter and opens on discs', async t => {
  const r = create(t, { props: { filter: { project: 7, manufacturer: '甲厂', start_ring: '100', summary_status: 'CONFIRMED' } } });
  await r.mount();
  assert.equal(r.requests.length, 1);
  assert.equal(r.requests[0].url, '/api/shield/analysis/life_mileage/');
  assert.deepEqual(plain(r.requests[0].params), { project: 7, manufacturer: '甲厂', start_ring: '100', summary_status: 'CONFIRMED' });
  assert.equal(r.state.group.value.label, '滚刀');
  assert.equal(r.state.trajectoryCount.value, 3);
  assert.deepEqual(plain(r.state.basisLines.value), ['里程口径', '圈数口径', '寿命口径']);
});

test('the matrix has one row per band with trajectories underneath, an all-manufacturer column first', async t => {
  const r = create(t); await r.mount();
  assert.deepEqual(plain(r.state.matrixColumns.value.map(column => column.label)), ['全部厂家', '甲厂', '乙厂']);
  const [inner, outer] = r.state.matrixRows.value;
  assert.deepEqual([inner.label, inner.sub, outer.label, outer.sub], ['R0–1000 mm', '1 条轨迹', 'R6000–7000 mm', '2 条轨迹']);
  assert.deepEqual(plain(outer.children.map(row => [row.label, row.sub])), [['R6770.8 mm', '78、Y3'], ['R6809.8 mm', '79、Y1']]);
  // 五段以上给中位数，少于五段列出各段的值；没有已拆段的厂家显示"—"
  assert.deepEqual(plain(outer.views['']), { main: '150', sub: '5 段', tip: '中位 150 km，四分位 140–160 km，5 段' });
  assert.equal(outer.children[0].views['厂家:甲厂'].main, '100、101、102');
  assert.equal(outer.views['厂家:乙厂'], null);
  r.state.metric.value = 'service';
  assert.equal(r.state.matrixRows.value[1].views['厂家:乙厂'].main, '2 把');
  r.state.metric.value = 'cost';
  assert.deepEqual([r.state.matrixRows.value[1].views[''].main, r.state.matrixRows.value[0].views[''].main], ['31', '—']);
});

test('the busiest band is selected by default; a trajectory row narrows the curve and the segment list', async t => {
  const r = create(t); await r.mount();
  assert.equal(r.state.selection.value.label, 'R6000–7000 mm');
  assert.deepEqual(plain(r.state.selectedSegments.value.map(row => row.detail_id)), [79, 78, 80, 81]);
  r.state.selectRow(r.state.matrixRows.value[1].children[0]);
  assert.deepEqual(plain(r.state.selectedSegments.value.map(row => row.detail_id)), [79, 78]);
  const option = charts(r);
  assert.deepEqual(plain(option.series.map(series => series.name)), ['甲厂']);
  const points = option.series[0].data;
  assert.deepEqual(plain(points.map(point => point.value)), [[0, 0], [200, 50], [300, 100]]);
  assert.deepEqual(plain(points.map(point => point.symbol)), ['none', 'emptyCircle', 'circle']);
  assert.equal(option.series[0].step, 'end');
  const tip = option.tooltip.formatter({ seriesName: '甲厂', data: points[2] });
  assert.match(tip, /刀位 78 · R6770\.8 mm/); assert.match(tip, /拆除时非正常/);
  assert.equal(option.tooltip.formatter({ seriesName: '甲厂', data: points[0] }), '');
});

test('switching to scrapers resets the selection and the per-type lists', async t => {
  const r = create(t); await r.mount();
  r.state.selectRow(r.state.matrixRows.value[0]);
  r.state.toolType.value = 'SCRAPER';
  await Promise.resolve();
  assert.equal(r.state.selection.value.label, 'R3000–4000 mm');
  assert.deepEqual(plain(r.state.selectedSegments.value.map(row => row.detail_id)), [90]);
  assert.deepEqual(plain(r.state.typedPositions.value.map(row => row.cutter_position_no)), ['S1L']);
  assert.deepEqual(plain(r.state.typedService.value.map(row => row.cutter_position_no)), ['S1L']);
});

test('review items flag the estimated mileage and the removed tools left out, with their reasons', async t => {
  const r = create(t); await r.mount();
  const [estimate, excluded] = r.state.reviewItems.value;
  assert.deepEqual([estimate.pending, estimate.detail, estimate.tip], [true, '全部按参考值约 120 圈/环推算', '圈数口径']);
  assert.deepEqual([excluded.pending, excluded.detail, excluded.tip], [true, '354 把已拆刀', '厂家反馈未确认 232 把；旧刀身份未确认 122 把']);
  assert.deepEqual(['参考值估算', '掘进推算', '估算 25.0%', '—'], [1, 0, 0.25, null].map(r.state.sourceText));
});

test('PDF export names the tool type and the selected band, and waits for complete data', async t => {
  const r = create(t); await r.mount();
  r.state.exportPdf();
  const [title, sections] = r.exports[0];
  assert.equal(title, '数据分析-寿命与厂家（滚刀）');
  assert.deepEqual(plain(sections.map(section => section.selector)), ['.life-summary-section', '.life-matrix-section', '.life-curve-section', '.life-segment-section', '.life-position-section']);
  assert.match(sections[2].title, /滚刀 · R6000–7000 mm/);
  const pending = create(t, { request: () => new Promise(() => {}) });
  pending.state.exportPdf();
  assert.equal(pending.exports.length, 0);
});

test('cell texts: medians from five segments, listed values below, nothing for an empty group', () => {
  const file = path.resolve(__dirname, '../utils/lifeChartOptions.ts');
  const modules = { './chartTheme': { TOOLTIP_STYLE: {}, DEFAULT_GRID: {} }, './costChartOptions': { manufacturerColor: () => '#000' } };
  const options = compile(fs.readFileSync(file, 'utf8'), name => {
    if (modules[name]) return modules[name];
    if (name === './presentation') return compile(fs.readFileSync(path.resolve(__dirname, '../utils/presentation.ts'), 'utf8'), () => ({}));
    if (name === 'echarts') return echartsStub;
    throw new Error(`Unexpected import ${name}`);
  });
  assert.equal(options.spreadText({ count: 2, values: [142.49, 150.06] }), '142.5、150.1');
  assert.equal(options.spreadTip({ count: 1, values: [6.4] }, 'km'), '1 段，各段 6.4 km；少于 5 段不给中位数');
  assert.equal(options.cellView(summary(0, { in_service_count: 0 }), 'life'), null);
  assert.deepEqual(plain(options.cellView(summary(3, { unclassified_count: 1, classified_count: 2 }), 'abnormal')), { main: '1/2', sub: '未分类 1', tip: '非正常拆除段数 / 拆除时磨损已分类的段数' });
  assert.equal(options.radiusText(6770.8), 'R6770.8 mm');
  assert.equal(options.wearStateLabel(null), '未分类');
});

test('the action area refreshes mileage and the manufacturer comparison, and exports either', async t => {
  const r = create(t); await r.mount();
  const actions = () => r.nodes().find(node => node.type?.name === 'AnalysisActions').props;
  assert.deepEqual(plain(actions().exports.map(item => [item.label, item.disabled])), [['寿命与厂家 PDF', false], ['厂家对照 PDF', true]]);
  assert.equal(actions().refresh, r.state.refreshAll);
  const loads = [];
  r.state.brandRef.value = { load: async () => loads.push('brand'), loading: false, ready: true, exportPdf: () => loads.push('brand-pdf') };
  assert.deepEqual(plain(actions().exports.map(item => item.disabled)), [false, false]);
  r.requests.length = 0; await r.state.refreshAll();
  assert.deepEqual(r.requests.map(call => call.url.split('/').at(-2)), ['life_mileage']);
  actions().exports[1].run();
  assert.deepEqual(loads, ['brand', 'brand-pdf']);
  assert.ok(r.nodes().some(node => node.type?.name === 'ManufacturerComparison'));
});

test('removed tools left out are listed one by one and open their opening read-only', async t => {
  const r = create(t); await r.mount();
  r.state.detailTab.value = 'excluded';
  const table = r.nodes().filter(node => node.type?.name === 'el-table').find(node => node.props.data?.[0]?.old_tool_number === 'OLD-7');
  assert.ok(table);
  r.state.openOpening(table.props.data[0]);
  assert.deepEqual(plain(r.routes[0]), { path: '/shield/toolChangeDetail', query: { warehouse_id: '31', warehouse_code: 'W-31', mode: 'view' } });
});
