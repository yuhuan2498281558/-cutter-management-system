// Actual mobile task list setup with stubbed list requests; no network calls.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { parse, compileScript } = require('@vue/compiler-sfc');
const ts = require('typescript');
const vue = require('vue');

const { descriptor } = parse(fs.readFileSync(path.resolve(__dirname, '../tasks.vue'), 'utf8'));
const script = compileScript(descriptor, { id: 'mobile-tasks-loading-test' });
const compiled = ts.transpileModule(script.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
const allTasks = [
  { id: 1, status: 'IN_PROGRESS' }, { id: 2, status: 'RETURNED' }, { id: 3, status: 'SUBMITTED' },
  { id: 4, status: 'COMPLETED' }, { id: 5, status: 'CANCELLED' }, { id: 6, status: 'UNASSIGNED' },
];
const activeTasks = allTasks.filter(task => !['COMPLETED', 'CANCELLED'].includes(task.status));
const statuses = list => Array.from(list, task => task.status);

function mount(t, respond) {
  const hooks = {}, toasts = [], calls = [];
  const context = {
    exports: {}, console,
    require(name) {
      if (name === 'vue') return { ...vue, onMounted: fn => { hooks.onMounted = fn; } };
      if (name === 'vue-router') return { useRouter: () => ({ push() {} }) };
      if (name === 'vant') return { showToast: message => toasts.push(message) };
      if (name === './api') return { getMobileTasks: async status => { calls.push(status); return respond(status, calls.length); } };
      throw new Error(`Unexpected import: ${name}`);
    },
  };
  vm.runInNewContext(compiled, context);
  const scope = vue.effectScope();
  const state = scope.run(() => context.exports.default.setup({}, { expose() {} }));
  t.after(() => scope.stop());
  return { s: state, hooks, toasts, calls };
}

test('mount loads the active tab once; each tab keeps its request status and filter', async t => {
  const { s, hooks, calls } = mount(t, async status => ({ data: status === 'active' ? activeTasks : allTasks }));
  await hooks.onMounted();
  assert.deepEqual(calls, ['active']);
  assert.deepEqual(statuses(s.tasks.value), ['IN_PROGRESS', 'RETURNED', 'UNASSIGNED']);
  assert.equal(s.inProgressCount.value, 1);
  assert.equal(s.returnedCount.value, 1);
  s.tab.value = 'submitted';
  await s.loadTasks();
  assert.deepEqual(calls, ['active', '']);
  assert.deepEqual(statuses(s.tasks.value), ['SUBMITTED', 'COMPLETED']);
  assert.equal(s.loading.value, false);
});

test('a late response from the previous tab cannot overwrite the current tab', async t => {
  const pending = [];
  const { s } = mount(t, () => { const wait = deferred(); pending.push(wait); return wait.promise; });
  const first = s.loadTasks();
  s.tab.value = 'submitted';
  const second = s.loadTasks();
  pending[1].resolve({ data: allTasks });
  await second;
  assert.deepEqual(statuses(s.tasks.value), ['SUBMITTED', 'COMPLETED']);
  assert.equal(s.loading.value, false);
  pending[0].resolve({ data: activeTasks });
  await first;
  assert.deepEqual(statuses(s.tasks.value), ['SUBMITTED', 'COMPLETED']);
  assert.equal(s.loading.value, false);
});

test('an older request finishing first neither applies its rows nor ends loading', async t => {
  const pending = [];
  const { s, toasts } = mount(t, () => { const wait = deferred(); pending.push(wait); return wait.promise; });
  const first = s.loadTasks();
  s.tab.value = 'submitted';
  s.refreshing.value = true;
  const second = s.loadTasks();
  pending[0].reject({ msg: 'offline' });
  await first;
  assert.deepEqual(statuses(s.tasks.value), []);
  assert.equal(s.loading.value, true);
  assert.equal(s.refreshing.value, true);
  assert.deepEqual(toasts, []);
  pending[1].resolve({ data: allTasks });
  await second;
  assert.deepEqual(statuses(s.tasks.value), ['SUBMITTED', 'COMPLETED']);
  assert.equal(s.loading.value, false);
  assert.equal(s.refreshing.value, false);
});

test('a failed request after switching tabs clears the old rows and shows a toast', async t => {
  const { s, toasts } = mount(t, async status => {
    if (status === '') throw { msg: '网络异常' };
    return { data: activeTasks };
  });
  await s.loadTasks();
  assert.equal(s.tasks.value.length, 3);
  s.tab.value = 'submitted';
  s.refreshing.value = true;
  await s.loadTasks();
  assert.deepEqual(statuses(s.tasks.value), []);
  assert.equal(s.inProgressCount.value, 0);
  assert.equal(s.loading.value, false);
  assert.equal(s.refreshing.value, false);
  assert.deepEqual(toasts, ['网络异常']);
});

test('failure toast keeps the existing message fallbacks', async t => {
  const errors = [{ response: { data: { msg: '登录已过期' } } }, new Error('timeout'), {}];
  const { s, toasts } = mount(t, async (_status, count) => { throw errors[count - 1]; });
  for (let index = 0; index < errors.length; index += 1) await s.loadTasks();
  assert.deepEqual(toasts, ['登录已过期', 'timeout', '任务加载失败']);
});

test('the empty state shows "暂无任务" once loading ends with no rows', () => {
  assert.match(descriptor.template.content, /<van-empty v-if="!loading && tasks.length === 0" description="暂无任务" \/>/);
});
