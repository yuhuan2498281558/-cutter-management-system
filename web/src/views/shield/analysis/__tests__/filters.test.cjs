const { test } = require('node:test');
const assert = require('node:assert/strict');
const vue = require('vue');
const { setup, deferred, plain, settle, descendants } = require('./helpers.cjs');
const response = (manufacturers = ['甲厂']) => ({ data: { manufacturers, tool_types: [{ value: 'DISC', label: '滚刀' }], tool_type_names: [] } });

test('default/reset stay confirmed and remove old scope fields', async t => {
  const h = setup(t, 'components/FilterPanel.vue', { request: async () => response() });
  Object.assign(h.state.form, { project: 1, shield_machine: 2, manufacturer: '甲厂', start_ring: '0', end_ring: '100', summary_status: 'ALL' });
  h.state.emitChange();
  assert.equal(h.events[0][1].start_ring, '0');
  h.state.onReset(); await settle();
  assert.deepEqual(h.events.at(-1), ['filter-change', { summary_status: 'CONFIRMED' }]);
});

test('invalid ranges never replace the applied query or emit requests', async t => {
  const h = setup(t, 'components/FilterPanel.vue', { request: async () => response() });
  for (const [start, end] of [['x', '100'], ['200', '100'], ['-1', '5'], ['2147483648', '']]) {
    Object.assign(h.state.form, { start_ring: start, end_ring: end });
    h.state.onScopeChange();
    assert.ok(h.state.rangeError.value);
  }
  assert.equal(h.events.length, 0); assert.equal(h.requests.length, 0);
  assert.deepEqual(plain(h.state.appliedFilter.value), { summary_status: 'CONFIRMED' });
});

test('old option responses cannot replace a new project scope', async t => {
  const old = deferred();
  const h = setup(t, 'components/FilterPanel.vue', { request: config => config.params.project === 1 ? old.promise : Promise.resolve(response(['乙厂'])) });
  h.state.form.project = 1; const first = h.state.fetchAnalysisOptions();
  h.state.form.project = 2; await h.state.fetchAnalysisOptions();
  old.resolve(response(['甲厂'])); await first;
  assert.deepEqual(plain(h.state.manufacturerList.value), ['乙厂']);
  assert.equal(h.requests[0].method, 'get');
  assert.equal(h.requests[0].url, '/api/shield/analysis/filter_options/');
});

test('option failure preserves applied scope and explicit retry recovers', async t => {
  let fail = true;
  const h = setup(t, 'components/FilterPanel.vue', { request: async () => { if (fail) throw new Error('offline'); return response(); } });
  h.state.form.project = 1; h.state.emitChange();
  await h.state.fetchAnalysisOptions(); assert.ok(h.state.optionsError.value);
  assert.equal(h.state.appliedFilter.value.project, 1);
  fail = false; await h.state.fetchAnalysisOptions(); assert.equal(h.state.optionsError.value, '');
});

test('unmount invalidates pending option response', async t => {
  const pending = deferred();
  const h = setup(t, 'components/FilterPanel.vue', { request: () => pending.promise });
  const load = h.state.fetchAnalysisOptions(); h.unmount(); pending.resolve(response()); await load;
  assert.deepEqual(plain(h.state.manufacturerList.value), []);
});

test('actual rendered form submits bound status and ring controls', t => {
  const h = setup(t, 'components/FilterPanel.vue', { request: async () => response() });
  const nodes = h.nodes();
  const input = nodes.find(n => n.type?.name === 'el-input' && n.props?.['aria-label'] === '起始环号');
  input.props['onUpdate:modelValue']('0');
  const status = nodes.find(n => n.type?.name === 'el-select' && n.props?.modelValue === 'CONFIRMED');
  status.props['onUpdate:modelValue']('DRAFT');
  nodes.find(n => n.type?.name === 'el-form').props.onSubmit({ preventDefault() {} });
  assert.deepEqual(h.events.at(-1), ['filter-change', { summary_status: 'DRAFT', start_ring: '0' }]);
});

test('top-level stratum selector filters existing queries and reset clears the condition', async t => {
  const h = setup(t, 'components/FilterPanel.vue', { request: async config => ({ data: {
    ...response().data,
    stratum_types: [{ value: 'ROCK', label: '岩层' }, { value: 'SOIL', label: '土层' }],
    manufacturers: config.params.stratum_type === 'ROCK' ? ['岩层厂家'] : ['甲厂', '岩层厂家'],
  } }) });
  await h.state.fetchAnalysisOptions();
  const select = h.nodes().find(node => node.props?.['aria-label'] === '地层类型');
  assert.ok(select);
  h.state.form.manufacturer = '甲厂';
  select.props['onUpdate:modelValue']('ROCK');
  select.props.onChange(); await settle();
  assert.deepEqual(h.events.at(-1), ['filter-change', { summary_status: 'CONFIRMED', stratum_type: 'ROCK' }]);
  assert.deepEqual(plain(h.state.manufacturerList.value), ['岩层厂家']);
  assert.equal(h.requests.at(-2).params.stratum_type, undefined, 'other strata remain selectable');
  assert.equal(h.requests.at(-1).params.stratum_type, 'ROCK');
  assert.equal(h.state.stratumTypeOptions.value.length, 2);
  const stratumSelect = () => h.nodes().find(node => node.props?.['aria-label'] === '地层类型');
  assert.equal(stratumSelect().props.modelValue, 'ROCK');
  assert.ok(h.nodes().some(node => node.type?.name === 'el-option' && node.props.value === 'ROCK' && node.props.label === '岩层'));
  h.state.onReset(); await settle();
  assert.deepEqual(h.events.at(-1), ['filter-change', { summary_status: 'CONFIRMED' }]);
  assert.equal(stratumSelect().props.modelValue, '');
});

test('changing project clears the previous project stratum condition', async t => {
  const h = setup(t, 'components/FilterPanel.vue', { request: async () => response() });
  Object.assign(h.state.form, { project: 2, stratum_type: 'OLD_PROJECT_ROCK', manufacturer: '甲厂' });
  h.state.onProjectChange(); await settle();
  assert.deepEqual(h.events.at(-1), ['filter-change', { summary_status: 'CONFIRMED', project: 2 }]);
});

test('parent replaces all fields instead of leaving hidden old filters', t => {
  const h = setup(t, 'index.vue');
  h.state.onFilterChange({ project: 1, stratum_types: 'OLD', cost_type: 'REPAIR' });
  h.state.onFilterChange({ project: 2 });
  assert.deepEqual(plain(vue.unref(h.state.currentFilter)), { summary_status: 'CONFIRMED', project: 2 });
});

test('parent publishes one complete scope to synchronous child observers', t => {
  const h = setup(t, 'index.vue');
  h.state.onFilterChange({ project: 1, shield_machine: 2, start_ring: '100', end_ring: '200' });
  const seen = [];
  const stop = vue.watch(() => vue.unref(h.state.currentFilter), value => seen.push(plain(value)), { deep: true, flush: 'sync' });
  t.after(stop);
  const filter = { project: 3, shield_machine: 4, start_ring: '200', end_ring: '300' };
  h.state.onFilterChange(filter);
  assert.deepEqual(seen, [{ summary_status: 'CONFIRMED', ...filter }]);
  const overview = h.nodes().find(node => node.type?.name === 'Overview');
  assert.deepEqual(plain(overview.props.filter), seen[0]);
});
test('trajectory bounds preserve zero and decimals in all options and emitted scope, reset clears them', async t => {
  const h = setup(t, 'components/FilterPanel.vue', { request: async () => response() });
  const nodes = h.nodes();
  nodes.find(n => n.props?.['aria-label'] === '刀刃轨迹最小值').props['onUpdate:modelValue']('0');
  nodes.find(n => n.props?.['aria-label'] === '刀刃轨迹最大值').props['onUpdate:modelValue'](' 6765.2 ');
  h.state.onScopeChange(); await settle();
  assert.deepEqual(h.events.at(-1)[1], { summary_status: 'CONFIRMED', blade_track_min: '0', blade_track_max: '6765.2' });
  assert.equal(h.requests.at(-1).params.blade_track_max, '6765.2');
  const trackInput = label => h.nodes().find(n => n.props?.['aria-label'] === label);
  assert.equal(trackInput('刀刃轨迹最小值').props.modelValue, '0');
  assert.equal(trackInput('刀刃轨迹最大值').props.modelValue.trim(), '6765.2');
  h.state.onReset(); await settle();
  assert.equal(h.events.at(-1)[1].blade_track_min, undefined);
  assert.equal(trackInput('刀刃轨迹最小值').props.modelValue, '');
});
test('invalid trajectory bounds cannot send queries or replace applied scope; one bound is allowed', async t => {
  const h = setup(t, 'components/FilterPanel.vue', { request: async () => response() });
  for (const [min, max] of [['NaN', ''], ['Infinity', ''], ['-1', '10'], ['6000', '5000'], ['1e4', '']]) {
    Object.assign(h.state.form, { blade_track_min: min, blade_track_max: max });
    h.state.onScopeChange(); assert.ok(h.state.trackRangeError.value);
  }
  assert.equal(h.requests.length, 0); assert.equal(h.events.length, 0);
  Object.assign(h.state.form, { blade_track_min: '', blade_track_max: '3000' }); h.state.onScopeChange(); await settle();
  assert.equal(h.events.at(-1)[1].blade_track_max, '3000'); assert.equal(h.events.at(-1)[1].blade_track_min, undefined);
});

test('one row shows the common conditions; the "more" badge counts non-default hidden conditions', async t => {
  const h = setup(t, 'components/FilterPanel.vue', { request: async () => response() });
  const nodes = () => h.nodes();
  const rows = nodes().filter(node => node.props?.class === 'filter-row');
  const selects = row => descendants(row).filter(node => node.type?.name === 'el-select').map(node => node.props['aria-label']);
  assert.deepEqual(selects(rows[0]), ['项目', '盾构机', '地层类型', '开仓状态']);
  assert.ok(descendants(rows[0]).some(node => node.props?.['aria-label'] === '起始环号'));
  assert.deepEqual(selects(rows[1]), ['刀具类型', '刀具细分类型', '厂家']);
  assert.ok(descendants(rows[1]).some(node => node.props?.['aria-label'] === '刀刃轨迹最小值'));
  assert.equal(nodes().some(node => typeof node.children === 'string' && node.children.includes('查询范围')), false);
  assert.equal(nodes().some(node => node.type?.name === 'el-button' && node.props?.['native-type'] === 'submit'), false);

  const moreRow = () => nodes().find(node => node.props?.id === 'analysis-more-filters');
  const toggle = () => nodes().find(node => node.type?.name === 'el-button' && node.props?.class === 'more-toggle');
  const badge = () => nodes().find(node => node.props?.class === 'more-badge')?.children;
  assert.equal(rows[1].props.id, 'analysis-more-filters'); assert.equal(moreRow().props.id, toggle().props['aria-controls']);
  assert.equal(moreRow().dirs[0].dir, vue.vShow);
  assert.equal(moreRow().dirs[0].value, false); assert.equal(toggle().props['aria-expanded'], false);
  toggle().props.onClick();
  assert.equal(moreRow().dirs[0].value, true); assert.equal(toggle().props['aria-expanded'], true);

  assert.equal(badge(), undefined);
  Object.assign(h.state.form, { project: 1, shield_machine: 2, stratum_type: 'ROCK', start_ring: '1', summary_status: 'ALL' });
  assert.equal(badge(), undefined, 'common-row conditions are not counted');
  h.state.form.blade_track_max = '3000';
  assert.equal(badge(), '1');
  Object.assign(h.state.form, { tool_parent_type: 'DISC', tool_type_name: '19寸滚刀', manufacturer: '甲厂', blade_track_min: '0' });
  assert.equal(badge(), '4', 'both trajectory bounds count as one condition, zero included');
  Object.assign(h.state.form, { blade_track_min: ' ', blade_track_max: '' });
  assert.equal(badge(), '3');
  h.state.onReset(); await settle();
  assert.equal(badge(), undefined);
});

test('range inputs query only on Enter or blur, never while typing or when invalid', async t => {
  const h = setup(t, 'components/FilterPanel.vue', { request: async () => response() });
  const input = label => h.nodes().find(node => node.type?.name === 'el-input' && node.props?.['aria-label'] === label);
  const type = (label, value) => input(label).props['onUpdate:modelValue'](value);
  // el-input 的 change 在回车或失焦时触发
  const commit = label => input(label).props.onChange(input(label).props.modelValue);
  type('起始环号', '100'); type('结束环号', '200'); await settle();
  assert.equal(h.events.length, 0); assert.equal(h.requests.length, 0);
  commit('结束环号'); await settle();
  assert.deepEqual(h.events.at(-1), ['filter-change', { summary_status: 'CONFIRMED', start_ring: '100', end_ring: '200' }]);
  const emitted = h.events.length, requested = h.requests.length;
  type('起始环号', '300'); commit('起始环号'); await settle();
  assert.equal(h.events.length, emitted); assert.equal(h.requests.length, requested);
  assert.equal(h.state.rangeError.value, '起始环号不能大于结束环号');
  const field = h.nodes().find(node => node.type?.name === 'el-form-item' && node.props?.error === '起始环号不能大于结束环号');
  assert.ok(field, 'error stays on the range field'); assert.notEqual(field.props['inline-message'], undefined);
  assert.ok(descendants(field).some(node => node.props?.['aria-label'] === '起始环号'));
  type('起始环号', '150'); commit('起始环号'); await settle();
  assert.equal(h.state.rangeError.value, '');
  assert.deepEqual(h.events.at(-1), ['filter-change', { summary_status: 'CONFIRMED', start_ring: '150', end_ring: '200' }]);
});
