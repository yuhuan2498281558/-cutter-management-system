// Actual approval dialog setup with a stubbed approval_detail request; no network calls.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { parse, compileScript } = require('@vue/compiler-sfc');
const ts = require('typescript');
const vue = require('vue');

const { descriptor } = parse(fs.readFileSync(path.resolve(__dirname, '../MobileTaskApprovalDialog.vue'), 'utf8'));
const script = compileScript(descriptor, { id: 'mobile-task-approval-dialog-test' });
const compiled = ts.transpileModule(script.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
const nos = list => Array.from(list, item => item.cutter_position_no);
const response = (id, ...positions) => ({ data: { task: { id, warehouse_id_name: `开仓${id}` }, details: positions.map(no => ({ cutter_position_no: no })) } });

function mount(t, respond) {
  const calls = [];
  const context = {
    exports: {}, console,
    require(name) {
      if (name === 'vue') return vue;
      if (name === './api') return { ApprovalDetail: async id => { calls.push(id); return respond(id, calls.length); } };
      throw new Error(`Unexpected import: ${name}`);
    },
  };
  vm.runInNewContext(compiled, context);
  const scope = vue.effectScope();
  const state = scope.run(() => context.exports.default.setup({}, { expose() {}, emit() {} }));
  t.after(() => scope.stop());
  return { s: state, calls };
}

test('opening a row shows its summary at once, then the loaded task and positions', async t => {
  const wait = deferred();
  const { s, calls } = mount(t, () => wait.promise);
  const opening = s.open({ id: 'A', warehouse_id_name: '行A' });
  assert.equal(s.visible.value, true);
  assert.equal(s.loading.value, true);
  assert.equal(s.task.value.warehouse_id_name, '行A');
  assert.deepEqual(nos(s.details.value), []);
  wait.resolve(response('A', 'A-1', 'A-2'));
  await opening;
  assert.deepEqual(calls, ['A']);
  assert.equal(s.task.value.warehouse_id_name, '开仓A');
  assert.deepEqual(nos(s.details.value), ['A-1', 'A-2']);
  assert.equal(s.loading.value, false);
});

test('a late response for a previously opened row cannot replace the current row', async t => {
  const pending = {};
  const { s } = mount(t, id => { pending[id] = deferred(); return pending[id].promise; });
  const first = s.open({ id: 'A' });
  s.visible.value = false;
  const second = s.open({ id: 'B' });
  pending.B.resolve(response('B', 'B-1'));
  await second;
  pending.A.resolve(response('A', 'A-1'));
  await first;
  assert.equal(s.task.value.warehouse_id_name, '开仓B');
  assert.deepEqual(nos(s.details.value), ['B-1']);
  assert.equal(s.loading.value, false);
});

test('an older response finishing first neither applies its data nor ends loading', async t => {
  const pending = {};
  const { s } = mount(t, id => { pending[id] = deferred(); return pending[id].promise; });
  const first = s.open({ id: 'A' });
  const second = s.open({ id: 'B', warehouse_id_name: '行B' });
  pending.A.resolve(response('A', 'A-1'));
  await first;
  assert.equal(s.task.value.warehouse_id_name, '行B');
  assert.deepEqual(nos(s.details.value), []);
  assert.equal(s.loading.value, true);
  pending.B.reject(new Error('offline'));
  await second;
  assert.equal(s.loadFailed.value, true);
  assert.equal(s.loading.value, false);
});

test('a failed load shows a retry state, separate from a task without positions', async t => {
  let fail = true;
  const { s, calls } = mount(t, async id => { if (fail) throw new Error('offline'); return response(id); });
  await s.open({ id: 'A', warehouse_id_name: '行A' });
  assert.equal(s.loadFailed.value, true);
  assert.equal(s.loading.value, false);
  assert.equal(s.task.value.warehouse_id_name, '行A');
  assert.deepEqual(nos(s.details.value), []);
  fail = false;
  await s.retry();
  assert.deepEqual(calls, ['A', 'A']);
  assert.equal(s.loadFailed.value, false);
  assert.equal(s.task.value.warehouse_id_name, '开仓A');
  assert.deepEqual(nos(s.details.value), []);
});

test('an older failure cannot mark the current row as failed', async t => {
  const pending = {};
  const { s } = mount(t, id => { pending[id] = deferred(); return pending[id].promise; });
  const first = s.open({ id: 'A' });
  const second = s.open({ id: 'B' });
  pending.B.resolve(response('B', 'B-1'));
  await second;
  pending.A.reject(new Error('late'));
  await first;
  assert.equal(s.loadFailed.value, false);
  assert.deepEqual(nos(s.details.value), ['B-1']);
});

test('the dialog renders the failure text and a retry button instead of the table', () => {
  const template = descriptor.template.content;
  assert.match(template, /<div v-if="loadFailed"[^>]*>[\s\S]*加载失败[\s\S]*<el-button[^>]*@click="retry"[^>]*>重试<\/el-button>[\s\S]*?<\/div>\s*<el-table v-else/);
});
