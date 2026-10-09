// Real SFC setup/template/API; Element Plus validation and HTTP are isolated boundaries.
// No DOM mounting, browser layout assertion, or business database writes.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');
const ts = require('typescript');
const vue = require('vue');

const source = fs.readFileSync(path.resolve(__dirname, '../OpeningCompletionDialog.vue'), 'utf8');
const { descriptor, errors } = parse(source);
assert.deepEqual(errors, []);
const script = compileScript(descriptor, { id: 'summary-template-bindings' });
const template = compileTemplate({
  source: descriptor.template.content,
  filename: 'OpeningCompletionDialog.vue',
  id: 'summary-template-bindings',
});
assert.deepEqual(template.errors, []);
const plain = value => JSON.parse(JSON.stringify(value));
const fields = {
  opening_duration: { label: '开仓持续时间（小时）', precision: 2 },
  tool_change_duration: { label: '换刀总时长（小时）', precision: 2 },
  checked_tool_count: { label: '检查刀具数量（把）', precision: 0 },
  replaced_tool_count: { label: '更换刀具数量（把）', precision: 0 },
};

function compile(content, requireModule) {
  const context = { exports: {}, require: requireModule };
  vm.runInNewContext(ts.transpileModule(content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, context);
  return context.exports;
}

// Traverse both native wrappers/Fragments and component slots; no assumed grouping depth.
function descendants(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(descendants);
  const children = node.children;
  const nested = Array.isArray(children)
    ? children
    : children && typeof children === 'object'
      ? Object.values(children).filter(slot => typeof slot === 'function').flatMap(slot => slot())
      : [];
  return [node, ...nested.flatMap(descendants)];
}

function only(nodes, predicate, description) {
  const matches = nodes.filter(predicate);
  assert.equal(matches.length, 1, description);
  return matches[0];
}

function setup(t, openingOverrides = {}) {
  const original = {
    id: 17, warehouse_id: 'ISOLATED-17', ring_no: '123',
    opening_duration: 8.5, tool_change_duration: 3.25,
    checked_tool_count: 44, replaced_tool_count: 12, usage_distance: 68,
    ...openingOverrides,
  };
  const originalSnapshot = plain(original);
  const props = vue.reactive({ modelValue: true, opening: original });
  const requests = [], events = [], unmount = [];
  const api = compile(fs.readFileSync(path.resolve(__dirname, '../api.ts'), 'utf8'), name => {
    assert.equal(name, '/@/utils/service');
    return { request: async request => {
      requests.push(plain(request));
      return { data: { ...plain(props.opening), ...plain(request.data) } };
    } };
  });
  const component = compile(script.content, name => {
    if (name === 'vue') return { ...vue, onUnmounted: callback => unmount.push(callback) };
    if (name === './api') return api;
    if (name === 'element-plus') return { ElMessage: { success() {} } };
    throw new Error(`Unexpected setup import: ${name}`);
  }).default;
  const scope = vue.effectScope();
  const state = scope.run(() => component.setup(props, {
    expose() {},
    emit(name, value) {
      events.push([name, value]);
      if (name === 'update:modelValue') props.modelValue = value;
    },
  }));
  state.formRef.value = { validate: async () => true, clearValidate() {} };
  t.after(() => { unmount.forEach(callback => callback()); scope.stop(); });
  const { render } = compile(template.code, name => {
    assert.equal(name, 'vue');
    return { ...vue, resolveComponent: name => ({ name }) };
  });
  const context = vue.proxyRefs({ ...state, ...vue.toRefs(props) });
  const nodes = () => descendants(render(context, []));
  const control = key => {
    const item = only(nodes(), node => node.type?.name === 'el-form-item' && node.props?.prop === key, `unique form item ${key}`);
    assert.equal(item.props.label, fields[key].label);
    return only(descendants(item), node => node.type?.name === 'el-input-number', `unique numeric control ${key}`);
  };
  const confirm = () => only(nodes(), node => node.type?.name === 'el-button' && node.props?.type === 'primary', 'unique primary submit action').props.onClick();
  return { props, state, originalSnapshot, requests, events, nodes, control, confirm };
}

test('rendered summary controls preserve initial values, units and numeric precision', t => {
  const h = setup(t);
  assert.equal(h.nodes().filter(node => node.type?.name === 'el-input-number').length, 4);
  for (const [key, spec] of Object.entries(fields)) {
    const node = h.control(key);
    assert.equal(node.props.modelValue, h.originalSnapshot[key]);
    assert.equal(node.props.min, 0);
    assert.equal(node.props.precision, spec.precision);
    assert.equal(typeof node.props['onUpdate:modelValue'], 'function');
  }
});

test('rendered v-model handlers reach exact four-field POST through the real submit action', async t => {
  const h = setup(t);
  const payload = { opening_duration: 7.75, tool_change_duration: 2.5, checked_tool_count: 52, replaced_tool_count: 19 };
  for (const [key, value] of Object.entries(payload)) {
    h.control(key).props['onUpdate:modelValue'](value);
    assert.equal(h.control(key).props.modelValue, value);
  }
  assert.deepEqual(plain(h.props.opening), h.originalSnapshot);
  await h.confirm();
  assert.deepEqual(h.requests, [{ url: '/api/shield/warehouse_opening/17/complete_summary/', method: 'post', data: payload }]);
  assert.deepEqual(plain(h.props.opening), h.originalSnapshot);
  assert.equal(h.events.filter(([name]) => name === 'saved').length, 1);
});

test('zero values survive all four rendered controls and the submitted payload', async t => {
  const h = setup(t);
  const payload = Object.fromEntries(Object.keys(fields).map(key => [key, 0]));
  for (const key of Object.keys(fields)) h.control(key).props['onUpdate:modelValue'](0);
  await h.confirm();
  assert.equal(h.requests.length, 1);
  assert.deepEqual(h.requests[0].data, payload);
  assert.deepEqual(plain(h.props.opening), h.originalSnapshot);
});

for (const [value, display] of [[68, 68], [0, 0], [null, '-']]) {
  test(`usage distance ${String(value)} is display-only and has no update binding`, t => {
    const h = setup(t, { usage_distance: value });
    const item = only(h.nodes(), node => node.type?.name === 'el-form-item' && node.props?.label === '本次使用距离（m）', 'usage-distance item');
    const input = only(descendants(item), node => node.type?.name === 'el-input', 'usage-distance display');
    // Explicit :model-value stays kebab-case until Vue normalizes component props.
    assert.equal(input.props['model-value'] ?? input.props.modelValue, display);
    assert.notEqual(input.props.disabled, undefined);
    assert.notEqual(input.props.disabled, false);
    assert.equal(input.props['onUpdate:modelValue'], undefined);
    assert.equal(Object.hasOwn(h.state.form, 'usage_distance'), false);
    assert.equal(h.requests.length, 0);
  });
}
