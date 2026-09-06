// Real list setup and button configuration; network and confirmation boundaries are mocked.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const { parse, compileScript } = require('@vue/compiler-sfc');
const ts = require('typescript');
const vue = require('vue');
const source = process.env.WITHDRAW_TEST_REF
  ? execFileSync('git', ['show', `${process.env.WITHDRAW_TEST_REF}:web/src/views/shield/warehouseOpening/index.vue`], { encoding: 'utf8' })
  : fs.readFileSync(path.resolve(__dirname, '../index.vue'), 'utf8');
const { descriptor } = parse(source);
const script = compileScript(descriptor, { id: 'withdraw-test' });
const plain = value => JSON.parse(JSON.stringify(value));
const settle = () => new Promise(setImmediate);
function compile(content, requireModule) {
  const context = { exports: {}, require: requireModule };
  vm.runInNewContext(ts.transpileModule(content, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, context);
  return context.exports;
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
const row = id => ({ id, warehouse_id: `TEST-${id}`, summary_status: 'CONFIRMED' });
function setup(t, overrides = {}) {
  const calls = [], notices = [], hooks = {};
  const component = compile(script.content, name => {
    if (name === 'vue') return { ...vue, ...Object.fromEntries(['onMounted', 'onActivated', 'onDeactivated', 'onUnmounted'].map(key => [key, fn => { hooks[key] = fn; }])) };
    if (name === 'vue-router') return { useRouter: () => ({ push: target => calls.push(['route', target]) }) };
    if (name === '@fast-crud/fast-crud') return {
      useExpose: () => ({ crudExpose: { doRefresh: async () => { calls.push(['refresh']); return overrides.refresh?.(); } } }),
      useCrud: () => ({ resetCrudOptions() {} }),
    };
    if (name === './crud') return { createCrudOptions: () => ({ crudOptions: {} }) };
    if (name === './api') return { WithdrawSummary: async id => {
      calls.push(['post', id]);
      return overrides.save ? overrides.save(id) : { msg: '撤回成功' };
    } };
    if (name === 'element-plus') return {
      ElMessage: Object.fromEntries(['success', 'error', 'warning'].map(level => [level, text => notices.push([level, text])])),
      ElMessageBox: { confirm: async (...args) => { calls.push(['confirm', ...args]); return overrides.confirm?.(); } },
    };
    if (name.endsWith('.vue') || name === '/@/utils/service') return {};
    throw new Error(`Unexpected import ${name}`);
  }).default;
  const scope = vue.effectScope();
  const state = scope.run(() => component.setup({}, { expose() {} }));
  t.after(() => { hooks.onUnmounted?.(); scope.stop(); });
  return { state, calls, notices, hooks };
}

test('duplicate clicks share one confirmation and only one POST', async t => {
  const confirm = deferred();
  const { state: s, calls } = setup(t, { confirm: () => confirm.promise });
  const first = s.withdrawCompletion(row(1));
  const second = s.withdrawCompletion(row(1));
  confirm.resolve();
  await Promise.all([first, second]);
  assert.equal(calls.filter(c => c[0] === 'confirm').length, 1);
  assert.equal(calls.filter(c => c[0] === 'post').length, 1);
});

test('while a POST is pending another row cannot start a second withdrawal', async t => {
  const save = deferred();
  const { state: s, calls } = setup(t, { save: () => save.promise });
  const first = s.withdrawCompletion(row(1));
  await settle();
  const second = s.withdrawCompletion(row(2));
  await settle();
  save.resolve({ msg: '撤回成功' });
  await Promise.all([first, second]);
  assert.deepEqual(calls.filter(c => c[0] === 'post'), [['post', 1]]);
});

test('cancel does not POST and next confirmation is allowed', async t => {
  let cancel = true;
  const { state: s, calls } = setup(t, { confirm: async () => { if (cancel) throw 'cancel'; } });
  await s.withdrawCompletion(row(1));
  assert.equal(calls.filter(c => c[0] === 'post').length, 0);
  cancel = false;
  await s.withdrawCompletion(row(2));
  assert.deepEqual(calls.filter(c => c[0] === 'post'), [['post', 2]]);
});

test('snapshot opening ID is stable while confirmation is pending', async t => {
  const confirm = deferred(), opening = row(1);
  const { state: s, calls } = setup(t, { confirm: () => confirm.promise });
  const pending = s.withdrawCompletion(opening);
  opening.id = 2;
  confirm.resolve();
  await pending;
  assert.deepEqual(calls.filter(c => c[0] === 'post'), [['post', 1]]);
});

test('network rejection is handled, never refreshes, and unlocks for explicit retry', async t => {
  let fail = true;
  const { state: s, calls, notices } = setup(t, { save: async () => { if (fail) throw new Error('offline'); return {}; } });
  await assert.doesNotReject(s.withdrawCompletion(row(1)));
  assert.equal(calls.filter(c => c[0] === 'refresh').length, 0);
  assert.equal(notices.filter(c => c[0] === 'success').length, 0);
  assert.ok(notices.some(c => c[1].includes('核对')));
  fail = false;
  await s.withdrawCompletion(row(1));
  assert.equal(calls.filter(c => c[0] === 'post').length, 2);
});

test('refresh failure is reported separately after a successful withdrawal', async t => {
  const { state: s, calls, notices } = setup(t, { refresh: async () => { throw new Error('refresh offline'); } });
  await assert.doesNotReject(s.withdrawCompletion(row(1)));
  assert.equal(calls.filter(c => c[0] === 'post').length, 1);
  assert.ok(notices.some(c => c[0] === 'success'));
  assert.ok(notices.some(c => c[0] === 'warning' && c[1].includes('刷新')));
  assert.equal(notices.some(c => c[0] === 'error'), false);
});

for (const lifecycle of ['onDeactivated', 'onUnmounted']) {
  test(`${lifecycle} before confirmation resolves prevents a POST`, async t => {
    const confirm = deferred();
    const { state: s, calls, hooks } = setup(t, { confirm: () => confirm.promise });
    const pending = s.withdrawCompletion(row(1));
    hooks[lifecycle]?.();
    confirm.resolve();
    await pending;
    assert.equal(calls.filter(c => c[0] === 'post').length, 0);
  });
}

test('late success after leaving cannot refresh or toast over a new operation', async t => {
  const old = deferred(), fresh = deferred();
  const { state: s, calls, notices, hooks } = setup(t, { save: id => id === 1 ? old.promise : fresh.promise });
  const first = s.withdrawCompletion(row(1));
  await settle();
  hooks.onDeactivated?.();
  hooks.onActivated?.();
  const second = s.withdrawCompletion(row(2));
  await settle();
  old.resolve({ msg: '旧请求成功' });
  await first;
  const staleEffects = { refreshed: calls.some(c => c[0] === 'refresh'), noticeCount: notices.length, busy: s.withdrawingId?.value };
  fresh.resolve({ msg: '新请求成功' });
  await second;
  assert.deepEqual(staleEffects, { refreshed: false, noticeCount: 0, busy: 2 });
  assert.deepEqual(notices, [['success', '新请求成功']]);
});

test('missing ID is a no-op and success preserves confirmation text and refresh order', async t => {
  const { state: s, calls } = setup(t);
  await s.withdrawCompletion({});
  assert.equal(calls.length, 0);
  await s.withdrawCompletion(row(1));
  assert.deepEqual(calls.map(c => c[0]), ['confirm', 'post', 'refresh']);
  assert.match(calls[0][1], /按移动端明细重新计算/);
  assert.match(calls[0][1], /退回待复核/);
});

test('real API uses original POST endpoint without inventing a payload', async () => {
  const calls = [];
  const api = compile(fs.readFileSync(path.resolve(__dirname, '../api.ts'), 'utf8'), name => {
    assert.equal(name, '/@/utils/service');
    return { request: async config => calls.push(config) };
  });
  await api.WithdrawSummary(1);
  assert.deepEqual(plain(calls), [{ url: '/api/shield/warehouse_opening/1/withdraw_summary/', method: 'post' }]);
});

test('real CRUD button reflects pending row and locks all withdrawal buttons', async () => {
  const { createCrudOptions } = compile(fs.readFileSync(path.resolve(__dirname, '../crud.tsx'), 'utf8'), name => {
    if (name === '@fast-crud/fast-crud') return { dict: options => options, compute: fn => fn };
    if (name === 'vue-router') return { useRouter: () => ({}) };
    if (name === '../crudUtils') return { createIndexFormatter: () => () => 1 };
    if (name === './api' || name.endsWith('.vue')) return {};
    throw new Error(`Unexpected CRUD import ${name}`);
  });
  const withdrawingId = vue.ref(null), clicked = [];
  const { crudOptions } = createCrudOptions({ crudExpose: {}, onSupplement() {}, onWithdraw: row => clicked.push(row.id), withdrawingId });
  const button = crudOptions.rowHandle.buttons.withdrawSummary;
  assert.equal(button.show({ row: row(1) }), true);
  assert.equal(button.show({ row: { ...row(1), summary_status: 'DRAFT' } }), false);
  assert.equal(button.loading({ row: row(1) }), false);
  assert.equal(button.disabled(), false);
  withdrawingId.value = 1;
  assert.equal(button.loading({ row: row(1) }), true);
  assert.equal(button.loading({ row: row(2) }), false);
  assert.equal(button.disabled(), true);
  withdrawingId.value = null;
  assert.equal(button.disabled(), false);
  button.click({ row: row(2) });
  assert.deepEqual(clicked, [2]);
});
