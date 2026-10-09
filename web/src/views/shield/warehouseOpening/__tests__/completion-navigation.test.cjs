// Real parent SFC setup; only refresh, router and notification boundaries are simulated.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const { parse, compileScript } = require('@vue/compiler-sfc');
const ts = require('typescript');
const vue = require('vue');
const router = require('vue-router');
const source = process.env.NAVIGATION_TEST_REF
  ? execFileSync('git', ['show', `${process.env.NAVIGATION_TEST_REF}:web/src/views/shield/warehouseOpening/index.vue`], { encoding: 'utf8' })
  : fs.readFileSync(path.resolve(__dirname, '../index.vue'), 'utf8');
const { descriptor } = parse(source);
const script = compileScript(descriptor, { id: 'completion-navigation-test' });
const plain = value => JSON.parse(JSON.stringify(value));
const row = id => ({ id, warehouse_id: `TEST-${id}`, summary_status: 'CONFIRMED' });
function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
function setup(t, overrides = {}) {
  const calls = [], notices = [], hooks = {};
  const context = { exports: {}, require: name => {
    if (name === 'vue') return { ...vue, ...Object.fromEntries(['onMounted', 'onActivated', 'onDeactivated', 'onUnmounted'].map(key => [key, fn => { hooks[key] = fn; }])) };
    if (name === 'vue-router') return { ...router, useRouter: () => ({ push: async target => { calls.push(['route', plain(target)]); return overrides.push?.(target); } }) };
    if (name === '@fast-crud/fast-crud') return {
      useExpose: () => ({ crudExpose: { doRefresh: async () => { calls.push(['refresh']); return overrides.refresh?.(); } } }),
      useCrud: () => ({ resetCrudOptions() {} }),
    };
    if (name === './crud') return { createCrudOptions: () => ({ crudOptions: {} }) };
    if (name === 'element-plus') return { ElMessage: Object.fromEntries(['success', 'warning', 'error'].map(level => [level, message => notices.push([level, message])])) };
    if (name === './api') return new Proxy({}, { get() { throw new Error('Saved handler must not write business data'); } });
    if (name.endsWith('.vue') || name === '/@/utils/service') return {};
    throw new Error(`Unexpected import ${name}`);
  } };
  vm.runInNewContext(ts.transpileModule(script.content, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, context);
  const scope = vue.effectScope();
  const state = scope.run(() => context.exports.default.setup({}, { expose() {} }));
  t.after(() => { hooks.onUnmounted?.(); scope.stop(); });
  state.openCompletion(row(1));
  return { state, calls, notices, hooks };
}

test('refresh failure still enters confirmed opening, reports refresh separately and does not reject', async t => {
  const { state, calls, notices } = setup(t, { refresh: () => Promise.reject(new Error('offline')) });
  await assert.doesNotReject(state.handleCompletionSaved(row(1)));
  assert.deepEqual(calls.map(c => c[0]), ['refresh', 'route']);
  assert.deepEqual(calls[1][1], { path: '/shield/toolChangeDetail', query: { warehouse_id: 1, warehouse_code: 'TEST-1', mode: 'supplement' } });
  assert.ok(notices.some(n => n[0] === 'warning' && /已确认/.test(n[1]) && /刷新/.test(n[1])));
});

test('snapshot keeps both ID and code stable while refresh is pending', async t => {
  const wait = deferred(), opening = row(1);
  const { state, calls } = setup(t, { refresh: () => wait.promise });
  const pending = state.handleCompletionSaved(opening);
  opening.id = 2; opening.warehouse_id = 'CHANGED';
  wait.resolve(); await pending;
  assert.equal(calls[1][1].query.warehouse_id, 1);
  assert.equal(calls[1][1].query.warehouse_code, 'TEST-1');
});

test('failed list read retains the server-confirmed fields in the original row and consumes the saved event', async t => {
  const { state, calls } = setup(t, { refresh: () => Promise.reject(new Error('offline')) });
  const original = { ...row(1), summary_status: 'DRAFT', supplement_ready: false, checked_tool_count: 10 };
  state.openCompletion(original);
  const saved = { ...row(1), supplement_ready: true, checked_tool_count: 8 };
  await state.handleCompletionSaved(saved);
  assert.equal(original.summary_status, 'CONFIRMED');
  assert.equal(original.supplement_ready, true);
  assert.equal(original.checked_tool_count, 8);
  await state.handleCompletionSaved(saved);
  assert.equal(calls.filter(c => c[0] === 'route').length, 1);
});

test('late router rejection after leaving is absorbed without a stale recovery warning', async t => {
  const wait = deferred();
  const { state, hooks, notices, calls } = setup(t, { push: () => wait.promise });
  const pending = state.handleCompletionSaved(row(1));
  await new Promise(setImmediate);
  assert.equal(calls.filter(c => c[0] === 'route').length, 1);
  hooks.onDeactivated();
  wait.reject(new Error('late navigation'));
  await assert.doesNotReject(pending);
  assert.equal(notices.length, 0);
});

test('late refresh failure cannot disturb a newly opened confirmation dialog', async t => {
  const wait = deferred();
  const { state, notices, calls } = setup(t, { refresh: () => wait.promise });
  const pending = state.handleCompletionSaved(row(1));
  state.openCompletion(row(2));
  wait.reject(new Error('old refresh'));
  await assert.doesNotReject(pending);
  assert.equal(notices.length, 0);
  assert.equal(calls.filter(c => c[0] === 'route').length, 0);
  assert.equal(state.completionVisible.value, true);
  assert.equal(state.selectedOpening.value.id, 2);
});

for (const event of ['onDeactivated', 'onUnmounted']) {
  for (const fails of [false, true]) {
    test(`${event} during refresh suppresses late ${fails ? 'failure' : 'success'} and navigation`, async t => {
      const wait = deferred();
      const { state, calls, notices, hooks } = setup(t, { refresh: () => wait.promise });
      const pending = state.handleCompletionSaved(row(1));
      hooks[event]();
      fails ? wait.reject(new Error('late')) : wait.resolve();
      await assert.doesNotReject(pending);
      assert.equal(calls.filter(c => c[0] === 'route').length, 0);
      assert.equal(notices.length, 0);
      assert.equal(state.completionVisible.value, false);
    });
  }
}

test('opening another dialog invalidates the old pending navigation', async t => {
  const wait = deferred();
  const { state, calls } = setup(t, { refresh: () => wait.promise });
  const pending = state.handleCompletionSaved(row(1));
  state.openCompletion(row(2));
  wait.resolve(); await pending;
  assert.equal(calls.filter(c => c[0] === 'route').length, 0);
  assert.equal(state.selectedOpening.value.id, 2);
  assert.equal(state.completionVisible.value, true);
});

test('leaving and reactivating never revives the old saved callback', async t => {
  const wait = deferred();
  const { state, calls, hooks } = setup(t, { refresh: () => wait.promise });
  const pending = state.handleCompletionSaved(row(1));
  hooks.onDeactivated(); hooks.onActivated();
  const late = state.handleCompletionSaved(row(1));
  wait.resolve(); await Promise.all([pending, late]);
  assert.equal(calls.filter(c => c[0] === 'route').length, 0);
});

test('duplicate saved events cannot start parallel refreshes or navigation', async t => {
  const wait = deferred();
  const { state, calls } = setup(t, { refresh: () => wait.promise });
  const first = state.handleCompletionSaved(row(1));
  const duplicate = state.handleCompletionSaved(row(1));
  wait.resolve(); await Promise.all([first, duplicate]);
  assert.deepEqual(calls.map(c => c[0]), ['refresh', 'route']);
});

test('missing or mismatched saved IDs are ignored', async t => {
  const { state, calls } = setup(t);
  await state.handleCompletionSaved({});
  await state.handleCompletionSaved(row(2));
  assert.equal(calls.length, 0);
});

test('router rejection is handled as navigation failure, not failed confirmation', async t => {
  const { state, notices } = setup(t, { push: () => Promise.reject(new Error('route failed')) });
  await assert.doesNotReject(state.handleCompletionSaved(row(1)));
  assert.ok(notices.some(n => /已确认/.test(n[1]) && /补录明细/.test(n[1])));
});

test('an actual router guard abort gets a visible recovery hint', async t => {
  const memoryRouter = router.createRouter({ history: router.createMemoryHistory(), routes: [
    { path: '/', component: {} }, { path: '/shield/toolChangeDetail', component: {} },
  ] });
  await memoryRouter.push('/');
  memoryRouter.beforeEach(() => false);
  const { state, notices } = setup(t, { push: target => memoryRouter.push(target) });
  await state.handleCompletionSaved(row(1));
  assert.equal(memoryRouter.currentRoute.value.path, '/');
  assert.ok(notices.some(n => /补录明细/.test(n[1])));
});
