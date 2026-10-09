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
