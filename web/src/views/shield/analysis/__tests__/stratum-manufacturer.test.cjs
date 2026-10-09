const { test } = require('node:test');
const assert = require('node:assert/strict');
const { setup, deferred, settle } = require('./helpers.cjs');

function payload(params, items = []) {
  return { data: { meta: { schema_version: 2, scope: params }, items,
    stratum_options: [{ value: 'GRANITE', label: '弱风化花岗岩' }],
    unpaired_count: 0, missing_stratum_segment_count: 0, unknown_manufacturer_count: 0 } };
}

test('service stratum is a separate condition and retains project machine and removal interval', async t => {
  const r = setup(t, 'components/StratumManufacturerComparison.vue', {
    props: { filter: { project: 1, shield_machine: 3, start_ring: '10', end_ring: '100' } },
    request: config => payload(config.params),
  });
  await r.mount();
  r.state.selectedStratum.value = 'GRANITE'; await settle();
  const call = r.requests.at(-1);
  assert.equal(call.url, '/api/shield/analysis/brand_stratum_performance/');
  assert.equal(call.params.service_stratum, 'GRANITE');
  assert.equal(call.params.project, 1); assert.equal(call.params.shield_machine, 3);
  assert.equal(call.params.start_ring, '10');
  r.props.filter = { project: 2 }; await settle();
  assert.equal(r.state.selectedStratum.value, '');
  assert.equal(r.requests.at(-1).params.project, 2);
});

test('late results cannot replace the new geology cohort and failure remains retryable', async t => {
  const stale = deferred();
  const r = setup(t, 'components/StratumManufacturerComparison.vue', {
    props: { filter: { project: 1 } },
    request: config => config.params.project === 1 ? stale.promise : payload(config.params),
  });
  const pending = r.state.load();
  r.props.filter = { project: 2 }; await settle();
  stale.resolve(payload({ project: 1 })); await pending; await settle();
  assert.equal(r.state.data.value.meta.scope.project, 2);
  r.unmount();
  assert.equal(r.state.data.value, null);
});
