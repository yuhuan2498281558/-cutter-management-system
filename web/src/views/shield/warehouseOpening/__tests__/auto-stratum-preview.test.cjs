// Exercise the real CRUD preview flow with controlled timers and API responses.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const source = fs.readFileSync(path.resolve(__dirname, '../crud.tsx'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
const data = (name = '测试地层') => ({ last_ring_no: '88', rings_between_openings: 12, usage_distance: 24,
  stratum_info_between_list: [{ stratum_type_code: 'TEST', stratum_type_name: name, ring_count: 12 }], geological_conditions: name });
function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
function setup(request = async () => ({ data: data() })) {
  const timers = new Map(), calls = [], hooks = {};
  let timerId = 0;
  const context = { exports: {}, setTimeout(fn, delay) { timers.set(++timerId, { fn, delay }); return timerId; },
    clearTimeout(id) { timers.delete(id); }, require(name) {
      if (name === 'vue') return { ...vue, onDeactivated: fn => { hooks.deactivate = fn; }, onScopeDispose: fn => { hooks.dispose = fn; } };
      if (name === '@fast-crud/fast-crud') return { compute: fn => fn, dict: value => value };
      if (name === 'vue-router') return { useRouter: () => ({}) };
      if (name === '../crudUtils') return { createIndexFormatter: () => () => 1 };
      if (name.endsWith('.vue')) return {};
      if (name === './api') return { GetAutoStratumPreview: params => { calls.push(plain(params)); return request(params); } };
      throw new Error('Unexpected import: ' + name);
    } };
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, context);
  const { crudOptions: options } = context.exports.createCrudOptions({ crudExpose: {}, withdrawingId: vue.ref(null) });
  const field = options.columns.stratum_info_between_list.form.component;
  const open = form => { options.form.wrapper.onOpen(); options.form.wrapper.onOpened({ form }); };
  const change = form => options.columns.ring_no.form.valueChange({ form });
  const run = () => { const next = timers.entries().next().value; assert.ok(next, 'Expected a scheduled request'); timers.delete(next[0]); return next[1].fn(); };
  return { options, field, calls, hooks, timers, open, change, run, status: () => field.status() };
}

test('missing inputs clear stale automatic fields without requesting and keep state out of the business form', () => {
  const s = setup(), form = { project: 1, ring_no: '', ...data() };
  s.open(form);
  assert.equal(s.status(), 'waiting');
  assert.equal(s.timers.size, 0);
  assert.equal(form.geological_conditions, '');
  assert.equal(form.last_ring_no, undefined);
  assert.equal(Object.keys(form).some(key => /status|preview/i.test(key)), false);
});

test('debounce sends only the newest project/ring/machine/record parameters', async () => {
  const s = setup(), form = { project: 1, ring_no: '100', shield_model: 11, id: 3, ...data() };
  s.open(form);
  assert.equal(s.status(), 'loading');
  assert.equal(form.geological_conditions, '');
  form.ring_no = '120'; form.shield_model = 12; s.change(form);
  assert.equal(s.timers.size, 1);
  assert.equal([...s.timers.values()][0].delay, 280);
  await s.run();
  assert.deepEqual(s.calls, [{ project: 1, ring_no: '120', shield_model: 12, opening_id: 3 }]);
  assert.equal(s.status(), 'ready');
  assert.equal(form.geological_conditions, '测试地层');
});

test('successful empty response stays ready and distinguishes the first opening', async () => {
  const s = setup(async () => ({ data: { last_ring_no: null, rings_between_openings: null, usage_distance: null, stratum_info_between_list: [], geological_conditions: '' } }));
  const form = { project: 1, ring_no: '0' };
  s.open(form); await s.run();
  assert.equal(s.status(), 'ready');
  assert.equal(s.field.firstOpening({ form }), true);
  assert.equal(form.stratum_info_between_list.length, 0);
});

test('failure supports one explicit immediate retry and restores successful fields', async () => {
  let fail = true;
  const s = setup(async () => { if (fail) throw new Error('offline'); return { data: data() }; });
  const form = { project: 1, ring_no: '100' };
  s.open(form); await s.run();
  assert.equal(s.status(), 'error');
  fail = false; s.field.onRetry(); s.field.onRetry();
  assert.equal(s.status(), 'loading');
  assert.equal(s.timers.size, 1);
  assert.equal([...s.timers.values()][0].delay, 0);
  await s.run();
  assert.equal(s.calls.length, 2);
  assert.equal(s.status(), 'ready');
});

for (const outcome of ['success', 'failure']) {
  test(`late ${outcome} from an old ring cannot replace the newest result`, async () => {
    const old = deferred();
    const s = setup(params => params.ring_no === '100' ? old.promise : Promise.resolve({ data: data('新环号') }));
    const form = { project: 1, ring_no: '100' };
    s.open(form); const pending = s.run();
    form.ring_no = '120'; s.change(form); await s.run();
    if (outcome === 'success') old.resolve({ data: data('旧环号') }); else old.reject(new Error('late offline'));
    await pending;
    assert.equal(s.status(), 'ready');
    assert.equal(form.geological_conditions, '新环号');
  });
}

test('clearing prerequisites invalidates an already running response', async () => {
  const old = deferred(), s = setup(() => old.promise), form = { project: 1, ring_no: '100' };
  s.open(form); const pending = s.run();
  form.project = undefined; s.change(form); old.resolve({ data: data() }); await pending;
  assert.equal(s.status(), 'waiting');
  assert.equal(form.geological_conditions, '');
});

test('closing and reopening ignores old callbacks, responses and old close events', async () => {
  const old = deferred(), s = setup(params => params.ring_no === '100' ? old.promise : Promise.resolve({ data: data('新表单') }));
  const first = { project: 1, ring_no: '100' }, second = { project: 2, ring_no: '200' };
  s.open(first); const pending = s.run();
  s.options.form.wrapper.onClosed({ form: first });
  s.open(second);
  s.options.form.wrapper.onClosed({ form: first }); s.change(first);
  await s.run(); old.resolve({ data: data('旧表单') }); await pending;
  assert.equal(s.status(), 'ready');
  assert.equal(first.geological_conditions, '');
  assert.equal(second.geological_conditions, '新表单');
});

for (const lifecycle of ['deactivate', 'dispose']) {
  test(`${lifecycle} cancels timers and prevents late responses/retries`, async () => {
    const old = deferred(), s = setup(() => old.promise), form = { project: 1, ring_no: '100' };
    s.open(form); const pending = s.run();
    s.hooks[lifecycle](); old.resolve({ data: data() }); await pending;
    s.change(form); s.field.onRetry();
    assert.equal(s.status(), 'waiting');
    assert.equal(s.timers.size, 0);
    assert.equal(form.geological_conditions, '');
    s.open(form); s.hooks[lifecycle]();
    assert.equal(s.timers.size, 0);
  });
}

test('reset previews the restored defaults again', async () => {
  const s = setup(), form = { project: 1, ring_no: '100' };
  s.open(form); await s.run();
  form.ring_no = undefined; s.options.form.doReset({ form });
  assert.equal(s.status(), 'waiting');
  assert.equal(form.geological_conditions, '');
});
