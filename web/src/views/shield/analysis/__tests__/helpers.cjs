// Real Vue setup/template and API compilation. Only browser and HTTP boundaries are replaced.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('typescript');
const vue = require('vue');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');

const root = path.resolve(__dirname, '..');
const plain = value => JSON.parse(JSON.stringify(value));
const settle = async () => { await vue.nextTick(); await new Promise(setImmediate); await vue.nextTick(); };
function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
function compile(source, requireModule, globals = {}) {
  const context = { exports: {}, require: requireModule, console, setTimeout, clearTimeout, ...globals };
  vm.runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, context);
  return context.exports;
}
function descendants(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(descendants);
  const children = node.children;
  const nested = Array.isArray(children) ? children : children && typeof children === 'object'
    ? Object.entries(children).filter(([key, slot]) => key !== '_' && typeof slot === 'function')
      .flatMap(([, slot]) => { try { return slot({ row: {}, $index: 0 }); } catch { return []; } }) : [];
  return [node, ...nested.flatMap(descendants)];
}
function setup(t, filename, options = {}) {
  const file = path.resolve(root, filename);
  const { descriptor, errors } = parse(fs.readFileSync(file, 'utf8'), { filename: file });
  assert.deepEqual(errors, []);
  const script = compileScript(descriptor, { id: 'analysis-test' });
  const template = compileTemplate({ source: descriptor.template.content, filename: file, id: 'analysis-test' });
  assert.deepEqual(template.errors, []);
  const requests = [], events = [], charts = [], exports = [], notices = [], routes = [];
  const hooks = { onMounted: [], onBeforeUnmount: [], onUnmounted: [], onActivated: [], onDeactivated: [] };
  const props = vue.reactive({ filter: { summary_status: 'CONFIRMED' }, ...options.props });
  const globals = {
    window: { addEventListener() {}, removeEventListener() {}, innerWidth: 1366, setTimeout, clearTimeout },
    ResizeObserver: class { observe() {} disconnect() {} },
    requestAnimationFrame: fn => setTimeout(fn, 0), cancelAnimationFrame: clearTimeout,
  };
  const vueMock = { ...vue, ...Object.fromEntries(Object.keys(hooks).map(key => [key, fn => hooks[key].push(fn)])) };
  const cache = new Map();
  const request = async config => {
    requests.push(plain(config));
    if (!options.request) throw new Error(`Unexpected request: ${config.url}`);
    return options.request(config);
  };
  function requireModule(name, from = file) {
    if (options.modules?.[name]) return options.modules[name];
    if (name === 'vue') return vueMock;
    if (name === '/@/utils/service') return { request };
    if (name === 'vue-router') return { useRouter: () => ({ push: value => { routes.push(value); return Promise.resolve(); } }) };
    if (name === 'element-plus') return { ElMessage: Object.fromEntries(['success', 'warning', 'error', 'info'].map(key => [key, value => notices.push([key, value])])) };
    if (name === 'echarts') return { init: element => {
      const chart = { element, options: [], disposed: false, width: 900,
        getDom: () => element, getWidth() { return this.width; }, getHeight: () => 360,
        isDisposed() { return this.disposed; }, setOption(value) { this.options.push(value); },
        resize() {}, clear() { this.options = []; }, dispose() { this.disposed = true; }, on() {}, off() {},
      };
      charts.push(chart); return chart;
    } };
    if (name.endsWith('.vue')) return { default: { name: path.basename(name, '.vue') } };
    if (name.includes('pdfExport')) return { exportAnalysisPdf: (...args) => { exports.push(args); return true; } };
    if (name.startsWith('.')) {
      const resolved = path.resolve(path.dirname(from), name.endsWith('.ts') ? name : `${name}.ts`);
      if (!cache.has(resolved)) cache.set(resolved, compile(fs.readFileSync(resolved, 'utf8'), n => requireModule(n, resolved), globals));
      return cache.get(resolved);
    }
    throw new Error(`Unexpected import ${name}`);
  }
  const component = compile(script.content, requireModule, globals).default;
  const scope = vue.effectScope();
  const state = scope.run(() => component.setup(props, { expose() {}, emit: (...args) => events.push(plain(args)) }));
  const { render } = compile(template.code, name => {
    assert.equal(name, 'vue');
    return { ...vue, resolveComponent: name => ({ name }), resolveDirective: () => ({}) };
  }, globals);
  const context = vue.proxyRefs({ ...state, ...vue.toRefs(props) });
  let destroyed = false;
  const unmount = () => {
    if (destroyed) return;
    destroyed = true;
    hooks.onBeforeUnmount.forEach(fn => fn()); hooks.onUnmounted.forEach(fn => fn()); scope.stop();
  };
  t.after(unmount);
  return { state, props, requests, events, charts, exports, notices, routes, hooks, unmount,
    nodes: () => descendants(render(context, [])),
    mount: async () => { await Promise.all(hooks.onMounted.map(fn => fn())); await settle(); },
  };
}
module.exports = { root, plain, settle, deferred, compile, descendants, setup };
