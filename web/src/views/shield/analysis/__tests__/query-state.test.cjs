const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vue = require('vue');
const { compile, root, deferred, plain, settle, setup } = require('./helpers.cjs');
function query(t, fetcher) {
  const hooks = {};
  const mock = { ...vue, ...Object.fromEntries(['onMounted', 'onBeforeUnmount', 'onActivated', 'onDeactivated'].map(k => [k, fn => { hooks[k] = fn; }])) };
  const { useAnalysisQuery } = compile(fs.readFileSync(path.join(root, 'utils/useAnalysisQuery.ts'), 'utf8'), () => mock);
  const filter = vue.ref({ project: 1, summary_status: 'CONFIRMED' });
  const scope = vue.effectScope();
  const state = scope.run(() => useAnalysisQuery(() => filter.value, fetcher));
  t.after(() => { hooks.onBeforeUnmount(); scope.stop(); });
  return { state, filter, hooks };
}
test('late success and failure cannot replace newer data or loading state', async t => {
  for (const fails of [false, true]) {
    const first = deferred();
    const h = query(t, scope => scope.project === 1 ? first.promise : Promise.resolve({ project: 2 }));
    const pending = h.state.load(); h.filter.value = { project: 2 };
    await vue.nextTick();
    if (fails) first.reject(new Error('late')); else first.resolve({ project: 1 });
    await pending;
    assert.equal(h.state.data.value.project, 2); assert.equal(h.state.error.value, ''); assert.equal(h.state.ready.value, true);
  }
});
test('scope changes invalidate old export data immediately and use a request snapshot', async t => {
  const pending = deferred(); const seen = [];
  const h = query(t, async f => { seen.push(f); return seen.length === 1 ? { project: 1 } : pending.promise; });
  await h.state.load(); assert.equal(h.state.ready.value, true);
  h.filter.value = { project: 2 };
  assert.equal(h.state.ready.value, false); assert.equal(h.state.data.value, null);
  assert.equal(seen[0].project, 1); pending.resolve({ project: 2 }); await vue.nextTick();
});
test('failure clears result and explicit retry recovers', async t => {
  let fail = true;
  const h = query(t, async () => { if (fail) throw new Error('offline'); return { ok: true }; });
  await h.state.load(); assert.equal(h.state.ready.value, false); assert.ok(h.state.error.value);
  fail = false; await h.state.load(); assert.equal(h.state.ready.value, true);
});
test('deactivation and unmount discard outstanding responses', async t => {
  const pending = deferred(); const h = query(t, () => pending.promise);
  const load = h.state.load(); h.hooks.onDeactivated(); pending.resolve({ stale: true }); await load;
  assert.equal(h.state.data.value, null); assert.equal(h.state.ready.value, false);
});

test('linked filter mutations invalidate immediately and request only the final snapshot', async t => {
  const seen = [];
  const pending = deferred();
  const h = query(t, async filter => {
    seen.push(filter);
    return seen.length === 1 ? { project: 1 } : pending.promise;
  });
  await h.state.load();
  h.filter.value.project = 2;
  assert.equal(h.state.ready.value, false);
  assert.equal(h.state.data.value, null);
  assert.equal(h.state.loading.value, true);
  delete h.filter.value.summary_status;
  Object.assign(h.filter.value, { shield_machine: 4, summary_status: 'CONFIRMED', manufacturers: ['A'] });
  h.filter.value.manufacturers.push('B');
  assert.equal(seen.length, 1);
  await settle();
  assert.deepEqual(plain(seen), [{ project: 1, summary_status: 'CONFIRMED' }, {
    project: 2, shield_machine: 4, summary_status: 'CONFIRMED', manufacturers: ['A', 'B'],
  }]);
  pending.resolve({ project: 2 }); await settle();
  assert.equal(h.state.ready.value, true);
});

test('explicit refresh replaces a queued automatic request without duplicate fetches', async t => {
  const seen = [];
  const h = query(t, async filter => { seen.push(filter.project); return filter; });
  await h.state.load();
  h.filter.value = { project: 2 };
  await h.state.load(); await settle();
  assert.deepEqual(seen, [1, 2]);
  assert.equal(h.state.data.value.project, 2);
  assert.equal(h.state.ready.value, true);
});

test('deactivation and unmount cancel requests still queued by filter changes', async t => {
  for (const hook of ['onDeactivated', 'onBeforeUnmount']) {
    const seen = [];
    const h = query(t, async filter => { seen.push(filter.project); return filter; });
    await h.state.load();
    h.filter.value = { project: 2 };
    h.hooks[hook](); await settle();
    assert.deepEqual(seen, [1]);
    assert.equal(h.state.data.value, null); assert.equal(h.state.loading.value, false);
    if (hook === 'onDeactivated') {
      h.hooks.onActivated(); await settle();
      assert.deepEqual(seen, [1, 2]); assert.equal(h.state.ready.value, true);
    }
  }
});

test('cost global scope and local brand reset issue each endpoint once with the final scope', async t => {
  const h = setup(t, 'pages/CostAnalysis.vue', {
    props: { filter: { project: 1, summary_status: 'CONFIRMED' } },
    request: async config => ({ data: {
      meta: { schema_version: 2, scope: config.params }, manufacturers: ['A', 'B'], stratum_types: [],
      items: [], service_rows: [], series: [], lifespan_series: [], normal_rate_series: [], abnormal_rate_series: [], time_axis: [],
    } }),
  });
  await h.mount();
  h.state.brandFilterForm.manufacturers = ['A']; h.state.applyBrandFilter(); await settle();
  assert.equal(h.requests.at(-1).params.manufacturers, 'A');
  h.requests.length = 0;
  h.props.filter = { project: 2, shield_machine: 7, summary_status: 'CONFIRMED' };
  assert.equal(h.state.costReady.value, false); assert.equal(h.state.brandReady.value, false);
  assert.equal(h.requests.length, 0);
  await settle();
  assert.equal(h.requests.length, 6); assert.equal(new Set(h.requests.map(call => call.url)).size, 6);
  for (const call of h.requests) assert.deepEqual(call.params, { project: 2, shield_machine: 7, summary_status: 'CONFIRMED',
    ...(/brand_(price|performance)_trend/.test(call.url) ? { include_details: 'false' } : {}) });
  assert.equal(h.state.costReady.value, true); assert.equal(h.state.brandReady.value, true);
});
test('formatters preserve zero, missing values and safely escape text', () => {
  const p = compile(fs.readFileSync(path.join(root, 'utils/presentation.ts'), 'utf8'), () => ({}));
  assert.equal(p.formatCurrency(0), '¥0'); assert.equal(p.formatCurrency(null), '未记录');
  assert.equal(p.formatPercent(0), '0.0%'); assert.equal(p.formatPercent(null), '无有效样本');
  assert.equal(p.escapeHtml('<b>&'), '&lt;b&gt;&amp;');
  assert.throws(() => p.requireAnalysisV2({ kpi: {} }));
  assert.equal(p.requireAnalysisV2({ meta: { schema_version: 2 } }).meta.schema_version, 2);
});
test('scope names are unique and trajectory bounds remain visible in scope and export', () => {
  const p = compile(fs.readFileSync(path.join(root, 'utils/presentation.ts'), 'utf8'), () => ({}));
  const meta = { summary_status: 'CONFIRMED', scope: { project_name: '工程A、工程A、工程B', shield_machine_name: '盾构机1、盾构机1', blade_track_min: '0', blade_track_max: '6765.2' } };
  const summary = p.scopeSummary(meta);
  assert.equal(summary.split('工程A').length, 2); assert.equal(summary.split('盾构机1').length, 2);
  assert.match(summary, /刀刃轨迹 0 至 6765.2 mm/);
  assert.equal(p.analysisExportMeta(meta)[0].value, summary);
});
test('trajectory filter never displays old service results that silently ignore bounds', async t => {
  let supported = false;
  const h = query(t, async () => ({ overview: { meta: { filter_capabilities: supported ? ['blade_track_range'] : [] } } }));
  h.filter.value = { blade_track_min: '0' }; await settle();
  assert.equal(h.state.ready.value, false); assert.equal(h.state.data.value, null); assert.match(h.state.error.value, /刀刃轨迹/);
  supported = true; await h.state.load(); assert.equal(h.state.ready.value, true);
});
