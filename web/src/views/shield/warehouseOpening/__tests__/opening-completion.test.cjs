// Real SFC setup and Vue state; mocked network boundaries, no business database writes.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');
const ts = require('typescript');
const vue = require('vue');

const source = process.env.SUMMARY_TEST_REF
  ? execFileSync('git', ['show', `${process.env.SUMMARY_TEST_REF}:web/src/views/shield/warehouseOpening/OpeningCompletionDialog.vue`], { encoding: 'utf8' })
  : fs.readFileSync(path.resolve(__dirname, '../OpeningCompletionDialog.vue'), 'utf8');
const { descriptor, errors } = parse(source);
assert.deepEqual(errors, []);
const script = compileScript(descriptor, { id: 'completion-test' });
function compile(code, requireModule) {
  const output = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const context = { exports: {}, require: requireModule };
  vm.runInNewContext(output, context);
  return context.exports;
}
const plain = value => JSON.parse(JSON.stringify(value));
const settle = async () => { await new Promise(setImmediate); await vue.nextTick(); };
const opening = (id = 1) => ({ id, warehouse_id: `TEST-${id}`, opening_duration: 4, tool_change_duration: 2, checked_tool_count: 10, replaced_tool_count: 3, usage_distance: 20 });
function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
function setup(t, options = {}) {
  const props = vue.reactive({ modelValue: true, opening: opening(), ...options.props });
  const writes = [], events = [], notices = [], unmount = [];
  const api = { CompleteSummary: async (id, payload) => {
    writes.push({ id, payload });
    return options.save ? options.save(id, payload) : { data: opening(id), msg: '已确认' };
  } };
  const component = compile(script.content, name => {
    if (name === 'vue') return { ...vue, onUnmounted: fn => unmount.push(fn) };
    if (name === './api') return api;
    if (name === 'element-plus') return { ElMessage: { success: value => notices.push(value) } };
    throw new Error(`Unexpected import ${name}`);
  }).default;
  const scope = vue.effectScope();
  const state = scope.run(() => component.setup(props, { expose() {}, emit: (name, value) => {
    events.push([name, value]);
    if (name === 'update:modelValue') props.modelValue = value;
  } }));
  state.formRef.value = { validate: options.validate || (async () => true), clearValidate() {} };
  t.after(() => { unmount.forEach(fn => fn()); scope.stop(); });
  return { state, props, writes, events, notices, unmount };
}

test('initial values, zero counts and unchanged four-field payload', async t => {
  const { state: s, writes, events } = setup(t, { props: { opening: { ...opening(), checked_tool_count: 0, replaced_tool_count: 0 } } });
  assert.equal(s.form.checked_tool_count, 0);
  s.form.opening_duration = 0;
  s.form.tool_change_duration = 0;
  await s.submit();
  assert.deepEqual(plain(writes), [{ id: 1, payload: { opening_duration: 0, tool_change_duration: 0, checked_tool_count: 0, replaced_tool_count: 0 } }]);
  assert.equal(events.filter(e => e[0] === 'saved').length, 1);
  assert.equal(s.visible.value, false);
});

test('locks before async validation and suppresses duplicate submits', async t => {
  const validation = deferred();
  const { state: s, writes } = setup(t, { validate: () => validation.promise });
  const first = s.submit();
  const locked = s.saving.value;
  const second = s.submit();
  validation.resolve(true);
  await Promise.all([first, second]);
  assert.equal(locked, true);
  assert.equal(writes.length, 1);
});

test('validation rejection is handled, unlocks and never writes', async t => {
  const { state: s, writes } = setup(t, { validate: async () => { throw { replaced_tool_count: ['invalid'] }; } });
  await assert.doesNotReject(s.submit());
  assert.equal(s.saving.value, false);
  assert.equal(writes.length, 0);
});

test('saving blocks v-model close and duplicate request, success closes once', async t => {
  const response = deferred();
  const { state: s, writes, events } = setup(t, { save: () => response.promise });
  const first = s.submit();
  await settle();
  s.visible.value = false;
  await settle();
  const remainedOpen = s.visible.value;
  const second = s.submit();
  response.resolve({ data: opening(), msg: '已确认' });
  await Promise.all([first, second]);
  assert.equal(remainedOpen, true);
  assert.equal(writes.length, 1);
  assert.equal(events.filter(e => e[0] === 'saved').length, 1);
});

test('failed save keeps edits, shows error, releases lock and allows explicit retry', async t => {
  let fail = true;
  const { state: s, events } = setup(t, { save: async () => {
    if (fail) throw new Error('offline');
    return { data: opening() };
  } });
  s.form.checked_tool_count = 12;
  await assert.doesNotReject(s.submit());
  assert.equal(s.form.checked_tool_count, 12);
  assert.equal(s.visible.value, true);
  assert.equal(s.saving.value, false);
  assert.ok(s.submitError.value);
  assert.equal(events.filter(e => e[0] === 'saved').length, 0);
  fail = false;
  await s.submit();
  assert.equal(events.filter(e => e[0] === 'saved').length, 1);
});

test('switching opening during validation cannot submit either record', async t => {
  const validation = deferred();
  const { state: s, props, writes } = setup(t, { validate: () => validation.promise });
  const pending = s.submit();
  props.opening = { ...opening(2), checked_tool_count: 20 };
  await settle();
  validation.resolve(true);
  await pending;
  assert.equal(writes.length, 0);
  assert.equal(s.form.checked_tool_count, 20);
});

test('old response cannot close a new opening or clear its save lock', async t => {
  const oldResponse = deferred(), newResponse = deferred();
  const { state: s, props, events } = setup(t, { save: id => id === 1 ? oldResponse.promise : newResponse.promise });
  const oldPending = s.submit();
  await settle();
  props.opening = opening(2);
  await settle();
  const newPending = s.submit();
  await settle();
  oldResponse.resolve({ data: opening(1) });
  await oldPending;
  const staleEffects = { visible: s.visible.value, saving: s.saving.value, saved: events.filter(e => e[0] === 'saved').length };
  newResponse.resolve({ data: opening(2) });
  await newPending;
  assert.deepEqual(staleEffects, { visible: true, saving: true, saved: 0 });
  assert.equal(events.filter(e => e[0] === 'saved')[0][1].id, 2);
});

for (const action of ['parent-close', 'unmount']) {
  test(`${action} invalidates a late response without success or saved event`, async t => {
    const response = deferred();
    const { state: s, props, events, notices, unmount } = setup(t, { save: () => response.promise });
    const pending = s.submit();
    await settle();
    if (action === 'parent-close') props.modelValue = false;
    else unmount.forEach(fn => fn());
    await settle();
    response.resolve({ data: opening() });
    await pending;
    assert.equal(events.filter(e => e[0] === 'saved').length, 0);
    assert.equal(notices.length, 0);
  });
}

test('hidden dialog and missing opening refuse submission', async t => {
  const hidden = setup(t, { props: { modelValue: false } });
  await hidden.state.submit();
  assert.equal(hidden.writes.length, 0);
  const missing = setup(t, { props: { opening: null } });
  await missing.state.submit();
  assert.equal(missing.writes.length, 0);
});

test('reopen resets unsaved values without mutating the supplied row', async t => {
  const { state: s, props } = setup(t);
  s.form.checked_tool_count = 99;
  s.visible.value = false;
  await settle();
  props.modelValue = true;
  await settle();
  assert.equal(s.form.checked_tool_count, 10);
  assert.equal(props.opening.checked_tool_count, 10);
});

test('template locks form, cancel, escape, backdrop and close icon while saving', t => {
  const { state: s } = setup(t);
  const result = compileTemplate({ source: descriptor.template.content, filename: 'OpeningCompletionDialog.vue', id: 'completion-test' });
  assert.deepEqual(result.errors, []);
  const { render } = compile(result.code, name => {
    assert.equal(name, 'vue');
    return { ...vue, resolveComponent: name => ({ name }) };
  });
  s.saving.value = true;
  const root = render(vue.proxyRefs(s), []);
  assert.equal(root.props['show-close'], false);
  assert.equal(root.props['close-on-click-modal'], false);
  assert.equal(root.props['close-on-press-escape'], false);
  const children = root.children.default();
  const form = children.find(node => node.type?.name === 'el-form');
  assert.equal(form.props.disabled, true);
  assert.equal(root.children.footer()[0].props.disabled, true);
});

test('before-close blocks while saving and permits normal dismissal', t => {
  const { state: s } = setup(t);
  let closes = 0;
  s.saving.value = true;
  s.beforeClose(() => closes++);
  assert.equal(closes, 0);
  s.saving.value = false;
  s.beforeClose(() => closes++);
  assert.equal(closes, 1);
});

test('mismatched response cannot navigate and keeps entered values', async t => {
  const { state: s, events } = setup(t, { save: async () => ({ data: opening(2) }) });
  await s.submit();
  assert.ok(s.submitError.value);
  assert.equal(s.visible.value, true);
  assert.equal(events.filter(e => e[0] === 'saved').length, 0);
});

test('old failure cannot add an error to a reopened same-ID session', async t => {
  const response = deferred();
  const { state: s, props } = setup(t, { save: () => response.promise });
  const pending = s.submit();
  await settle();
  props.modelValue = false;
  props.modelValue = true;
  await settle();
  s.form.checked_tool_count = 15;
  response.reject(new Error('late offline'));
  await pending;
  assert.equal(s.submitError.value, '');
  assert.equal(s.visible.value, true);
  assert.equal(s.form.checked_tool_count, 15);
});

test('unmount during validation prevents a later POST', async t => {
  const validation = deferred();
  const { state: s, writes, unmount } = setup(t, { validate: () => validation.promise });
  const pending = s.submit();
  unmount.forEach(fn => fn());
  validation.resolve(true);
  await pending;
  assert.equal(writes.length, 0);
});

test('replacement-count rule compares against current checked count', t => {
  const { state: s } = setup(t);
  const validator = s.rules.replaced_tool_count[1].validator;
  let result;
  s.form.checked_tool_count = 2;
  validator({}, 3, error => { result = error; });
  assert.match(result.message, /不能大于/);
  validator({}, 2, error => { result = error; });
  assert.equal(result, undefined);
});

test('actual API preserves POST URL and exact payload object', async () => {
  const calls = [];
  const api = compile(fs.readFileSync(path.resolve(__dirname, '../api.ts'), 'utf8'), name => {
    assert.equal(name, '/@/utils/service');
    return { request: async args => { calls.push(args); return { data: opening() }; } };
  });
  const payload = { opening_duration: 4, tool_change_duration: 2, checked_tool_count: 10, replaced_tool_count: 3 };
  await api.CompleteSummary(1, payload);
  assert.deepEqual(plain(calls), [{ url: '/api/shield/warehouse_opening/1/complete_summary/', method: 'post', data: payload }]);
});

test('actual parent saved handler refreshes and navigates to the returned opening in supplement mode', async t => {
  const { descriptor: parent } = parse(fs.readFileSync(path.resolve(__dirname, '../index.vue'), 'utf8'));
  const parentScript = compileScript(parent, { id: 'completion-parent-test' });
  const calls = [];
  const component = compile(parentScript.content, name => {
    if (name === 'vue') return { ...vue, onMounted() {}, onActivated() {}, onDeactivated() {}, onUnmounted() {} };
    if (name === 'vue-router') return { useRouter: () => ({ push: value => calls.push(['route', value]) }) };
    if (name === '@fast-crud/fast-crud') return {
      useExpose: () => ({ crudExpose: { doRefresh: async () => calls.push(['refresh']) } }),
      useCrud: () => ({ resetCrudOptions() {} }),
    };
    if (name === './crud') return { createCrudOptions: () => ({ crudOptions: {} }) };
    if (name.endsWith('.vue') || name === './api' || name === 'element-plus' || name === '/@/utils/service') return {};
    throw new Error(`Unexpected parent import ${name}`);
  }).default;
  const scope = vue.effectScope();
  t.after(() => scope.stop());
  const state = scope.run(() => component.setup({}, { expose() {} }));
  await state.handleCompletionSaved(opening(2));
  assert.deepEqual(plain(calls), [['refresh'], ['route', { path: '/shield/toolChangeDetail', query: { warehouse_id: 2, warehouse_code: 'TEST-2', mode: 'supplement' } }]]);
});
