// Run from web: node --test src/views/shield/toolChangeDetail/__tests__/old-tool-repair.test.cjs
// Executes the real SFC setup with Vue reactivity and mocked API boundaries (no database writes).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');
const ts = require('typescript');
const vue = require('vue');

const source = process.env.REPAIR_TEST_REF
  ? execFileSync('git', ['show', `${process.env.REPAIR_TEST_REF}:web/src/views/shield/toolChangeDetail/OldToolRepairDialog.vue`], { encoding: 'utf8' })
  : fs.readFileSync(path.resolve(__dirname, '../OldToolRepairDialog.vue'), 'utf8');
const { descriptor, errors } = parse(source);
assert.deepEqual(errors, []);
const script = compileScript(descriptor, { id: 'old-tool-repair-test' });
const compiled = ts.transpileModule(script.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

const fields = {
  ring_damage: [{ value: 'CHIPPED', label: '崩裂' }],
  bearing_failure_reasons: [{ value: 'WEAR', label: '磨损' }],
  hub_failure_reasons: [{ value: 'BROKEN', label: '断裂' }],
  old_tool_dispositions: [{ value: 'SCRAP', label: '报废' }, { value: 'REPAIRABLE', label: '可维修' }],
};
const record = (number = 'OLD-1', status = 'PENDING_VENDOR_FEEDBACK') => ({
  data: { old_tool_record_data: { old_tool_number: number, inspection_status: status, remark: '原补充说明' } },
});
function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
function setup(t, overrides = {}) {
  const writes = [], emitted = [], notices = [], unmount = [];
  const api = {
    GetOldToolRecord: async () => record(),
    GetToolChangeOptions: async () => ({ data: structuredClone(fields) }),
    UpdateOldToolRecord: async (id, data) => { writes.push({ id, data }); return { msg: '已保存' }; },
    ...overrides,
  };
  const context = {
    exports: {}, FormData,
    require(name) {
      if (name === 'vue') return { ...vue, onUnmounted: fn => unmount.push(fn) };
      if (name === './api') return api;
      if (name === 'element-plus') return {
        ElMessage: Object.fromEntries(['success', 'error', 'warning'].map(level => [level, text => notices.push({ level, text })])),
        ElMessageBox: { confirm: overrides.confirm || (async () => {}) },
      };
      throw new Error(`Unexpected module ${name}`);
    },
  };
  vm.runInNewContext(compiled, context);
  const scope = vue.effectScope();
  const state = scope.run(() => context.exports.default.setup({}, { expose() {}, emit: (...args) => emitted.push(args) }));
  t.after(() => { unmount.forEach(fn => fn()); scope.stop(); });
  return { state, writes, emitted, notices, unmount };
}

test('loads backend options into the rendered reactive state', async t => {
  const { state: s } = setup(t);
  const openOptions = { readOnly: false };
  await s.open({ id: 1, tool_parent_type: 'DISC' }, openOptions);
  for (const key of Object.keys(fields)) {
    assert.equal(JSON.stringify(s.options[key]), JSON.stringify(fields[key]));
  }
  assert.deepEqual(openOptions, { readOnly: false });
  assert.equal(s.form.old_tool_number, 'OLD-1');
});

test('loading blocks writes, including direct handler calls', async t => {
  const pending = deferred();
  const { state: s, writes } = setup(t, { GetOldToolRecord: () => pending.promise });
  const opening = s.open({ id: 1 });
  assert.equal(s.canSave.value, false);
  await s.save('SAVE_DRAFT');
  assert.equal(writes.length, 0);
  pending.resolve(record());
  await opening;
  assert.equal(s.canSave.value, true);
});

test('failed load blocks writes and retry recovers', async t => {
  let fail = true;
  const { state: s, writes } = setup(t, {
    GetToolChangeOptions: async () => { if (fail) throw new Error('network'); return { data: fields }; },
  });
  await s.open({ id: 1 });
  assert.ok(s.loadError.value);
  assert.equal(s.loading.value, false);
  await s.save('SAVE_DRAFT');
  assert.equal(writes.length, 0);
  fail = false;
  await s.retryLoad();
  assert.equal(s.loadError.value, '');
  assert.equal(s.canSave.value, true);
});

test('malformed options are not treated as a successful load', async t => {
  const { state: s } = setup(t, { GetToolChangeOptions: async () => ({ data: {} }) });
  await s.open({ id: 1 });
  assert.equal(s.loaded.value, false);
  assert.ok(s.loadError.value);
});

test('late response from A cannot overwrite already loaded B', async t => {
  const first = deferred();
  const { state: s } = setup(t, { GetOldToolRecord: id => id === 1 ? first.promise : Promise.resolve(record('OLD-B')) });
  const a = s.open({ id: 1 });
  await s.open({ id: 2 });
  first.resolve(record('OLD-A'));
  await a;
  assert.equal(s.row.value.id, 2);
  assert.equal(s.form.old_tool_number, 'OLD-B');
  assert.equal(s.canSave.value, true);
});

test('stale failure does not clear B loading state or show an error', async t => {
  const first = deferred(), second = deferred();
  const { state: s } = setup(t, { GetOldToolRecord: id => id === 1 ? first.promise : second.promise });
  const a = s.open({ id: 1 });
  const b = s.open({ id: 2 });
  first.reject(new Error('A failed'));
  await a;
  assert.equal(s.loading.value, true);
  assert.equal(s.loadError.value, '');
  second.resolve(record('OLD-B'));
  await b;
  assert.equal(s.form.old_tool_number, 'OLD-B');
});

test('closing and unmounting invalidate outstanding loads', async t => {
  for (const close of ['close', 'unmount']) {
    const pending = deferred();
    const { state: s, unmount } = setup(t, { GetOldToolRecord: () => pending.promise });
    const opening = s.open({ id: 1 });
    if (close === 'close') s.visible.value = false;
    else unmount.forEach(fn => fn());
    pending.resolve(record());
    await opening;
    assert.equal(s.loaded.value, false);
    assert.equal(s.form.old_tool_number, '');
  }
});

test('read-only and archived records reject all save actions', async t => {
  for (const readOnly of [true, false]) {
    const { state: s, writes } = setup(t, {
      GetOldToolRecord: async () => record('OLD-1', readOnly ? 'PENDING_VENDOR_FEEDBACK' : 'CLOSED'),
    });
    await s.open({ id: 1 }, { readOnly });
    for (const action of ['SAVE_DRAFT', 'CONFIRM', 'CLOSE']) await s.save(action);
    assert.equal(writes.length, 0);
    assert.equal(s.canSave.value, false);
  }
});

test('draft preserves identity, false/zero values, arrays and files in the multipart contract', async t => {
  const { state: s, writes, emitted } = setup(t);
  await s.open({ id: 7 });
  Object.assign(s.form, { bearing_failed: false, ring_wear_amount: 0, ring_damage: ['CHIPPED'], remark: '补录说明' });
  s.fileList.value = [{ raw: new Blob(['test-photo'], { type: 'image/png' }) }];
  await s.save('SAVE_DRAFT');
  assert.equal(writes.length, 1);
  assert.equal(writes[0].id, 7);
  const data = writes[0].data;
  assert.equal(data.get('workflow_action'), 'SAVE_DRAFT');
  assert.equal(data.get('old_tool_number'), 'OLD-1');
  assert.equal(data.get('bearing_failed'), 'false');
  assert.equal(data.get('ring_wear_amount'), '0');
  assert.equal(data.get('ring_damage'), '["CHIPPED"]');
  assert.equal(data.get('remark'), '补录说明');
  assert.equal(data.getAll('photos').length, 1);
  assert.equal(emitted.length, 1);
  assert.equal(s.visible.value, false);
});

test('save lock prevents duplicates and switching records while saving', async t => {
  const pending = deferred();
  let count = 0;
  const { state: s } = setup(t, { UpdateOldToolRecord: () => { count++; return pending.promise; } });
  await s.open({ id: 1 });
  const saving = s.save('SAVE_DRAFT');
  await s.save('SAVE_DRAFT');
  await s.open({ id: 2 });
  assert.equal(count, 1);
  assert.equal(s.row.value.id, 1);
  pending.resolve({ msg: 'ok' });
  await saving;
  assert.equal(s.saving.value, false);
});

test('failed save keeps user input for retry', async t => {
  const { state: s, emitted } = setup(t, { UpdateOldToolRecord: async () => { throw new Error('network'); } });
  await s.open({ id: 1 });
  s.form.remark = '保留填写内容';
  await s.save('SAVE_DRAFT');
  assert.equal(s.form.remark, '保留填写内容');
  assert.equal(s.visible.value, true);
  assert.equal(s.canSave.value, true);
  assert.equal(emitted.length, 0);
});

test('archive confirmation is locked and cancellation performs no write', async t => {
  const pending = deferred();
  const { state: s, writes } = setup(t, {
    GetOldToolRecord: async () => record('OLD-1', 'CONFIRMED'),
    confirm: () => pending.promise,
  });
  await s.open({ id: 1 });
  s.form.disposition = 'SCRAP';
  const saving = s.save('CLOSE');
  await s.save('SAVE_DRAFT');
  assert.equal(s.saving.value, true);
  pending.reject('cancel');
  await saving;
  assert.equal(writes.length, 0);
  assert.equal(s.canSave.value, true);
});

test('template compiles and save controls bind to the same readiness guard', () => {
  const result = compileTemplate({ source: descriptor.template.content, filename: 'OldToolRepairDialog.vue', id: 'repair-test', compilerOptions: { bindingMetadata: script.bindings } });
  assert.deepEqual(result.errors, []);
  assert.equal((descriptor.template.content.match(/:disabled="!canSave"/g) || []).length, 4);
  assert.match(descriptor.template.content, /v-if="loadError"/);
  assert.match(descriptor.template.content, /@click="retryLoad"/);
});

test('missing old record can still start a new draft after successful loading', async t => {
  const { state: s, writes } = setup(t, { GetOldToolRecord: async () => ({ data: { old_tool_record_data: null } }) });
  await s.open({ id: 1 });
  assert.equal(s.canSave.value, true);
  await s.save('SAVE_DRAFT');
  assert.equal(writes.length, 1);
});

test('confirmation requires disposition and preserves the CONFIRM action', async t => {
  const { state: s, writes } = setup(t);
  await s.open({ id: 1 });
  await s.save('CONFIRM');
  assert.equal(writes.length, 0);
  s.form.disposition = 'SCRAP';
  await s.save('CONFIRM');
  assert.equal(writes[0].data.get('workflow_action'), 'CONFIRM');
  assert.equal(writes[0].data.get('disposition'), 'SCRAP');
});

test('repair archive requires repair result and preserves the CLOSE action', async t => {
  const { state: s, writes } = setup(t, { GetOldToolRecord: async () => record('OLD-1', 'CONFIRMED') });
  await s.open({ id: 1 });
  s.form.disposition = 'REPAIRABLE';
  await s.save('CLOSE');
  assert.equal(writes.length, 0);
  s.form.repair_result = '维修完成';
  await s.save('CLOSE');
  assert.equal(writes[0].data.get('workflow_action'), 'CLOSE');
  assert.equal(writes[0].data.get('repair_result'), '维修完成');
});
