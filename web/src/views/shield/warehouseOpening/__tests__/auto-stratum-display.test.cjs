// Run from web: node --test src/views/shield/warehouseOpening/__tests__/auto-stratum-display.test.cjs
// Renders the real AutoStratumDisplay setup + template to VNodes; no DOM mounting, no API calls.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');
const ts = require('typescript');
const vue = require('vue');

const source = fs.readFileSync(path.resolve(__dirname, '../AutoStratumDisplay.vue'), 'utf8');
const { descriptor, errors } = parse(source);
assert.deepEqual(errors, []);
const script = compileScript(descriptor, { id: 'auto-stratum-display' });
const template = compileTemplate({ source: descriptor.template.content, filename: 'AutoStratumDisplay.vue', id: 'auto-stratum-display' });
assert.deepEqual(template.errors, []);

function compile(content, requireModule) {
  const context = { exports: {}, require: requireModule };
  vm.runInNewContext(ts.transpileModule(content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, context);
  return context.exports;
}
const component = compile(script.content, name => {
  assert.equal(name, 'vue');
  return vue;
}).default;
const { render } = compile(template.code, name => {
  assert.equal(name, 'vue');
  return { ...vue, resolveComponent: name => ({ name }) };
});

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

function setup(t, values = {}) {
  const defaults = Object.fromEntries(Object.entries(component.props).map(([key, spec]) => [key, spec.default]));
  const props = vue.reactive({ ...defaults, ...values });
  const events = [];
  const scope = vue.effectScope();
  const state = scope.run(() => component.setup(props, { expose() {}, emit: (...args) => events.push(args) }));
  t.after(() => scope.stop());
  const tree = () => {
    const root = render(vue.proxyRefs({ ...state, ...vue.toRefs(props), $emit: (...args) => events.push(args) }), []);
    const nodes = descendants(root);
    const status = nodes.find(node => node.props?.role === 'status');
    return {
      root,
      input: nodes.find(node => node.type?.name === 'el-input'),
      status,
      text: descendants(status).find(node => node.type === 'span').children,
      retry: nodes.find(node => node.type?.name === 'el-button'),
    };
  };
  return { props, events, tree };
}

const between = [{ stratum_type_code: 'A', stratum_type_name: '砂层', ring_count: 3 }, { stratum_type_code: 'B', stratum_type_name: '岩层', ring_count: 2 }];

test('defaults render the waiting between-field with the automatic placeholder', t => {
  const { tree } = setup(t);
  const view = tree();
  assert.equal(view.text, '请选择项目并输入换刀环号');
  assert.equal(view.input.props['model-value'], '');
  assert.equal(view.input.props.placeholder, '自动获取');
  assert.notEqual(view.input.props.disabled, undefined);
  assert.notEqual(view.input.props.disabled, false);
  assert.equal(view.retry, undefined);
});

for (const kind of ['between', 'position']) {
  const value = kind === 'between' ? between : '  粉质黏土，埋深 12 m  ';
  const shown = kind === 'between' ? '砂层（3 环）、岩层（2 环）' : '粉质黏土，埋深 12 m';
  const empty = kind === 'between' ? [] : '';
  const cases = [
    ['waiting', value, '请选择项目并输入换刀环号'],
    ['loading', empty, '正在获取地层信息…'],
    ['error', empty, '获取失败，请重试'],
    ['ready', value, '已自动获取'],
    ['ready', empty, kind === 'between' ? '该环段暂无地层数据' : '该位置暂无地层数据'],
  ];
  for (const [status, modelValue, expected] of cases) {
    test(`${kind} ${status} ${modelValue === empty ? 'without' : 'with'} strata shows "${expected}"`, t => {
      const { tree } = setup(t, { kind, status, modelValue });
      const view = tree();
      assert.equal(view.text, expected);
      assert.equal(view.input.props['model-value'], modelValue === empty ? '' : shown);
      assert.equal(view.root.props['aria-busy'], status === 'loading');
      assert.equal(view.status.props.class.split(/\s+/).includes('is-error'), status === 'error');
      assert.equal(Boolean(view.retry), status === 'error');
    });
  }
}

test('first opening only changes the empty between text', t => {
  assert.equal(setup(t, { kind: 'between', status: 'ready', modelValue: [], firstOpening: true }).tree().text, '首次开仓，暂无期间地层');
  assert.equal(setup(t, { kind: 'between', status: 'ready', modelValue: between, firstOpening: true }).tree().text, '已自动获取');
  assert.equal(setup(t, { kind: 'position', status: 'ready', modelValue: '', firstOpening: true }).tree().text, '该位置暂无地层数据');
});

test('a value of the other kind is not displayed', t => {
  assert.equal(setup(t, { kind: 'between', status: 'ready', modelValue: '砂层' }).tree().input.props['model-value'], '');
  assert.equal(setup(t, { kind: 'position', status: 'ready', modelValue: between }).tree().input.props['model-value'], '');
});

test('hovering the field shows the full stratum text', t => {
  const longText = '粉质黏土，灰黄色，可塑，含少量铁锰质结核及氧化物斑点，局部夹薄层粉砂，埋深 12.5 m';
  assert.equal(setup(t, { kind: 'position', status: 'ready', modelValue: longText }).tree().root.props.title, longText);
  assert.equal(setup(t, { kind: 'between', status: 'ready', modelValue: between }).tree().root.props.title, '砂层（3 环）、岩层（2 环）');
  assert.equal(setup(t, { kind: 'between', status: 'ready', modelValue: [] }).tree().root.props.title, '');
});

test('retry button emits retry once per click and only in the error state', t => {
  const { props, events, tree } = setup(t, { status: 'error' });
  const retry = tree().retry;
  assert.equal(descendants(retry).some(node => node.children === '重试'), true);
  retry.props.onClick();
  assert.deepEqual(events, [['retry']]);
  props.status = 'loading';
  assert.equal(tree().retry, undefined);
  assert.deepEqual(events, [['retry']]);
});
