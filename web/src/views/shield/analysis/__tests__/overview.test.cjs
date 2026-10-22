const test = require('node:test');
const assert = require('node:assert/strict');
const { setup, settle, deferred, plain } = require('./helpers.cjs');
const meta = { schema_version: 2, generated_at: '2026-09-11T00:00:00Z', summary_status: 'CONFIRMED', opening_count: 1, draft_opening_count: 2, scope: { project_name: '验收工程' }, warnings: [] };
function payload(n = 4) {
  return { meta, kpi: { total_replacements: n, total_untyped: 2, cost_sources: { installation: 0, confirmed_repair: 20, legacy: 30, total: 50 } }, monthly_trend: [{ month: '2026-09', total_replacements: n, replacements: 1, repairs: 1, untyped: 2, cost: 50 }], type_trend: [{ ring_no: '100', DISC: 3, SCRAPER: 1 }], recent_openings: [{ id: 9, warehouse_id: 'KC9', ring_no: '100', cost: 0, cost_sources: { installation: 0 } }] };
}
function harness(t, request) {
  const h = setup(t, 'pages/Overview.vue', { request: request || (async config => ({ data: config.url.includes('cost_trend') ? { meta, items: [{ ring_no: '100', total_cost: 50, replacement_count: 4 }] } : payload() })) });
  h.state.trendRef.value = {}; h.state.typeRef.value = {}; return h;
}
test('overview shows all replacement types, source zero and exact successful scope', async t => {
  const h = harness(t); await h.mount();
  assert.equal(h.state.kpi.value.total_replacements, 4);
  assert.equal(h.state.formatCurrency(h.state.sources.value.installation), '¥0');
  h.state.trendMode.value = 'month'; await settle();
  assert.deepEqual(plain(h.charts[0].options.at(-1).series[0].data), [4]);
  assert.deepEqual(plain(h.charts[1].options.at(-1).yAxis.data), ['滚刀', '刮刀']);
  h.state.exportPdf(); assert.match(JSON.stringify(h.exports[0]), /验收工程/);
  await h.state.viewOpening({ id: 9, warehouse_id: 'KC9' });
  assert.deepEqual(plain(h.routes[0].query), { warehouse_id: 9, warehouse_code: 'KC9', mode: 'view' });
});
test('late overview cannot override a new scope and export clears immediately', async t => {
  const old = deferred();
  const h = harness(t, async config => ({ data: config.url.includes('cost_trend') ? { meta, items: [] } : config.params.project === 2 ? payload(9) : await old.promise }));
  const pending = h.mount(); h.props.filter.project = 2; await settle();
  assert.equal(h.state.kpi.value.total_replacements, 9);
  old.resolve(payload(1)); await pending;
  assert.equal(h.state.kpi.value.total_replacements, 9);
  h.props.filter.project = 3; h.state.exportPdf(); assert.equal(h.exports.length, 0);
});
test('failure clears both endpoint results and retry recovers', async t => {
  let fail = true;
  const h = harness(t, async config => { if (fail && config.url.includes('cost_trend')) throw new Error('失败'); return { data: config.url.includes('cost_trend') ? { meta, items: [] } : payload() }; });
  await h.mount(); assert.equal(h.state.ready.value, false); assert.ok(h.state.error.value);
  fail = false; await h.state.load(); await settle(); assert.equal(h.state.ready.value, true);
  h.unmount(); assert.ok(h.charts.every(c => c.disposed));
});
test('schema mismatch refuses outdated backend totals', async t => {
  const h = harness(t, async () => ({ data: { ...payload(), meta: undefined } }));
  await h.mount(); assert.equal(h.state.data.value, null); h.state.exportPdf(); assert.equal(h.exports.length, 0);
});

const trendItems = [{ ring_no: '100', total_cost: 50, replacement_count: 4 }, { ring_no: '120', total_cost: null }];
const monthlyTrend = [{ month: '2026-09', total_replacements: 4, cost: 50 }, { month: '', cost: null }];
const typeTrend = [{ ring_no: '100', DISC: 3, SCRAPER: 1 }, { ring_no: '120', DISC: 5, SCRAPER: 2 }];
function modeHarness(t) {
  return harness(t, async config => ({ data: config.url.includes('cost_trend') ? { meta, items: trendItems } : { ...payload(), monthly_trend: monthlyTrend, type_trend: typeTrend } }));
}
test('ring trend uses ring numbers, two value axes, zoom and keeps cost gaps', async t => {
  const h = modeHarness(t); await h.mount();
  const option = h.charts[0].options.at(-1);
  assert.equal(option.tooltip.trigger, 'axis'); assert.deepEqual(plain(option.legend), { bottom: 0, type: 'scroll' }); assert.equal(option.grid.bottom, 78);
  assert.deepEqual(plain(option.xAxis), { type: 'category', data: ['100', '120'], name: '环号' });
  assert.deepEqual(plain(option.yAxis), [{ type: 'value', name: '实际更换 / 把次', minInterval: 1 }, { type: 'value', name: '明确金额 / 元' }]);
  assert.deepEqual(plain(option.dataZoom), [{ type: 'inside' }, { type: 'slider', height: 14, bottom: 28 }]);
  assert.deepEqual(plain(option.series.map(item => [item.name, item.type, item.data])), [['实际更换', 'bar', [4, 0]], ['明确金额', 'line', [50, null]]]);
  assert.equal(option.series[0].yAxisIndex, undefined); assert.equal(option.series[1].yAxisIndex, 1); assert.equal(option.series[1].connectNulls, false);
});
test('month trend switches only the axis labels and monthly values', async t => {
  const h = modeHarness(t); await h.mount();
  h.state.trendMode.value = 'month'; await settle();
  const option = h.charts[0].options.at(-1);
  assert.deepEqual(plain(option.xAxis), { type: 'category', data: ['2026-09', '日期未记录'], name: '月份' });
  assert.deepEqual(plain(option.series.map(item => item.data)), [[4, 0], [50, null]]);
  assert.equal(option.yAxis.length, 2); assert.equal(option.dataZoom.length, 2); assert.equal(option.grid.bottom, 78); assert.equal(option.series[1].connectNulls, false);
});
test('type total mode shows the latest ring as horizontal bars without legend', async t => {
  const h = modeHarness(t); await h.mount();
  assert.deepEqual(h.charts.map(chart => chart.theme), ['dv', 'dv']);
  const option = h.charts[1].options.at(-1);
  assert.equal(option.grid.bottom, 35); assert.deepEqual(plain(option.legend), { bottom: 0, show: false });
  assert.deepEqual(plain(option.xAxis), { type: 'value', name: '把次', minInterval: 1 });
  assert.deepEqual(plain(option.yAxis), { type: 'category', data: ['滚刀', '刮刀'] });
  assert.equal(option.series.length, 1); assert.equal(option.series[0].type, 'bar');
  assert.deepEqual(plain(option.series[0].data), [{ value: 5, itemStyle: { color: '#3f5f7a' } }, { value: 2, itemStyle: { color: '#b98a4a' } }]);
});
test('type cumulative mode draws one line per tool type with legend and taller grid', async t => {
  const h = modeHarness(t); await h.mount();
  h.state.typeMode.value = 'cumulative'; await settle();
  const option = h.charts[1].options.at(-1);
  assert.equal(option.grid.bottom, 70); assert.deepEqual(plain(option.legend), { bottom: 0, show: true });
  assert.deepEqual(plain(option.xAxis), { type: 'category', name: '环号', data: ['100', '120'] });
  assert.deepEqual(plain(option.yAxis), { type: 'value', name: '累计更换 / 把次', minInterval: 1 });
  assert.deepEqual(plain(option.series), [{ name: '滚刀', type: 'line', color: '#3f5f7a', data: [3, 5] }, { name: '刮刀', type: 'line', color: '#b98a4a', data: [1, 2] }]);
});

const { descendants, textOf: nodeText } = require('./helpers.cjs');
test('conclusion shows three big numbers with non-zero secondary lines, the interval aside, and non-zero review items', async t => {
  const kpi = {
    total_openings: 15, detail_checked_count: 0, total_replacements: 74, total_untyped: 2, avg_rings_between_openings: 9.2,
    summary_replaced_count: 74, summary_detail_replaced_count: 76, replacement_gap: 2,
    cost_sources: { installation: 100, confirmed_repair: 20, legacy: 30, total: 150, unresolved: 0, unresolved_count: 0, missing_price_count: 3, pending_repair_count: 0, repair_missing_price_count: 1 },
  };
  let current = kpi;
  const h = harness(t, async config => ({ data: config.url.includes('cost_trend') ? { meta, items: [] } : { ...payload(), kpi: current } }));
  await h.mount();
  const read = () => h.nodes().filter(node => ['kpi', 'kpi kpi-minor'].includes(node.props?.class)).map(node => {
    const parts = descendants(node);
    return [parts.find(item => item.props?.class === 'hero-label').children, nodeText(parts.find(item => item.props?.class === 'kpi-value')),
      parts.find(item => item.props?.class === 'kpi-sub')?.children, node.props.class === 'kpi kpi-minor'];
  });
  assert.deepEqual(read(), [
    ['范围内开仓', '15次', undefined, false],
    ['实际更换', '74把次', '含未分类更换 2 把次', false],
    ['明确金额合计', '¥150', '缺登记价格 3 条 · 缺返修价 1 条', false],
    ['平均开仓间隔', '9.2环', undefined, true],
  ]);
  const share = h.nodes().find(node => node.type?.name === 'AmountShare');
  assert.equal(share.props.inline, ''); assert.equal(share.props.total, 150);
  assert.deepEqual(plain(share.props.parts.map(part => [part.label, part.amount])), [['新装刀具登记', 100], ['已确认返修', 20], ['历史登记', 30]]);
  const review = () => plain(h.nodes().find(node => node.type?.name === 'ReviewList').props.items);
  assert.deepEqual(review().map(item => [item.name, item.pending]), [['待核对候选金额', false], ['整仓数量核对差额', true]]);
  assert.equal(`${review()[1].lead}：${review()[1].detail}`, '整仓数量核对差额 2：已确认人工更换汇总 74，同仓全部有效明细 76');
  assert.equal(review()[1].tip, '此处比较整仓数量；上方实际更换数随刀型、厂家筛选。');
  assert.equal(h.nodes().some(node => ['analysis-note', 'reconciliation', 'analysis-metrics'].includes(node.props?.class)), false);

  current = { ...kpi, detail_checked_count: 6, replacement_gap: 0, cost_sources: { ...kpi.cost_sources, unresolved: 50, unresolved_count: 1 } };
  await h.state.load(); await settle();
  assert.equal(read()[0][2], '明细有检查证据 6 条');
  assert.deepEqual(review().map(item => [item.name, item.pending]), [['待核对候选金额', true], ['整仓数量核对差额', false]]);
  assert.equal(`${review()[0].lead}：${review()[0].detail}`, '待核对候选金额 ¥50（1 次更换）：不计入合计');

  // 历史维修价和返修价都为 0：金额 0，但仍有 1 次待核对
  current = { ...kpi, replacement_gap: 0, cost_sources: { ...kpi.cost_sources, unresolved: 0, unresolved_count: 1 } };
  await h.state.load(); await settle();
  assert.deepEqual(review().map(item => [item.name, item.pending]), [['待核对候选金额', true], ['整仓数量核对差额', false]]);
  assert.equal(`${review()[0].lead}：${review()[0].detail}`, '待核对候选金额 ¥0（1 次更换）：不计入合计');
});
