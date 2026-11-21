const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');

const filename = path.join(__dirname, '../BimfaceModel.vue');
const { descriptor } = parse(fs.readFileSync(filename, 'utf8'), { filename });
const settle = async (rounds = 3) => { for (let i = 0; i < rounds; i += 1) await new Promise(resolve => setImmediate(resolve)); };
const SDK_SRC = '/vendor/bimface/BimfaceSDKLoader@latest-release.js';

function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}

// options: sdkGlobals（SDK 加载后是否有全局对象）、viewToken（取 token 的实现）、
// statusFails / mappingsFails（刀位状态、映射接口失败）。
function harness(options = {}) {
  const compiled = compileScript(descriptor, { id: 'bimface-model-test' });
  const exposed = new Set(Object.keys(compiled.bindings).filter(name => !compiled.imports?.[name]));
  exposed.add('loadScript');
  exposed.add('bindModelSelection');
  const source = [descriptor.script?.content ?? '', descriptor.scriptSetup.content].join('\n')
    .replace(/^import\s[^;]*?from\s*'[^']*';/gm, '')
    .replaceAll('import.meta.env', 'importMetaEnv');

  const scripts = [];
  const head = {
    children: [],
    appendChild(element) { this.children.push(element); scripts.push(element); },
  };
  const document = {
    head,
    querySelector(selector) {
      const src = selector.match(/src="([^"]+)"/)?.[1];
      return head.children.find(element => element.src === src) ?? null;
    },
    createElement(tag) {
      if (tag === 'canvas') return { getContext: () => ({ getExtension: () => ({ loseContext() {} }) }) };
      return { tagName: tag.toUpperCase(), remove() { head.children = head.children.filter(child => child !== this); } };
    },
  };
  const infoRequests = [];
  const viewTokenCalls = [];
  const sdkLoads = [];
  const timers = [];
  const clock = { now: 0 };
  let mount, unmount;
  const context = {
    ...vue,
    importMetaEnv: { BASE_URL: '/', DEV: false },
    console: { warn() {}, error() {} },
    onMounted: fn => { mount = fn; },
    onUnmounted: fn => { unmount = fn; },
    document,
    window: {},
    Date: class extends Date { static now() { return clock.now; } },
    requestAnimationFrame: callback => setImmediate(callback),
    setTimeout: (callback, delay) => timers.push({ callback, delay, cleared: false }),
    clearTimeout: id => { if (timers[id - 1]) timers[id - 1].cleared = true; },
    ResizeObserver: class { observe() {} disconnect() {} },
    isActiveCutterPosition: () => true,
    getCutterInfo: code => {
      const request = deferred();
      infoRequests.push({ code, ...request });
      return request.promise;
    },
    getAllCutterStatus: async onError => {
      if (options.statusFails) onError?.(new Error('status unavailable'));
      return {};
    },
    getActiveCutterModelMappings: async onError => {
      if (options.mappingsFails) onError?.(new Error('mapping unavailable'));
      return [];
    },
    getBimfaceViewToken: async force => {
      viewTokenCalls.push(force);
      return options.viewToken ? options.viewToken() : 'view-token';
    },
  };
  if (options.sdkGlobals !== false) {
    context.window.BimfaceSDKLoaderConfig = class {};
    context.window.BimfaceSDKLoader = { load: (config, onSuccess, onError) => sdkLoads.push({ config, onSuccess, onError }) };
    context.window.Glodon = { Bimface: {} };
  }
  vm.createContext(context);
  vm.runInContext(ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText
    + `\nglobalThis.api={${[...exposed].join(',')},setViewer:v=>{viewer=v;}};`, context);
  return {
    api: context.api, scripts, infoRequests, viewTokenCalls, sdkLoads, clock,
    pendingTimers: () => timers.filter(timer => !timer.cleared && !timer.fired),
    mount: () => mount(), unmount: () => unmount(),
    async render() {
      const { renderToString } = require('@vue/server-renderer');
      const stub = { render() { return vue.h('span', this.$slots.default?.()); } };
      const app = vue.createSSRApp({ template: descriptor.template.content, setup: () => ({ ...context.api, Close: {} }) });
      for (const name of ['ElIcon', 'ElButton', 'Loading', 'WarningFilled']) app.component(name, stub);
      const html = await renderToString(app);
      return html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    },
  };
}

// 让 SDK 脚本加载完成，走到 BimfaceSDKLoader.load 之前的各步。
async function finishSdkScript(h) {
  await settle();
  h.scripts[0].onload();
  await settle(6);
}

test('a late response for an earlier cutter does not replace the newer one',async () => {
  const h = harness();
  const first = h.api.onHotspotClick({ code: '12', type: '滚刀' });
  const second = h.api.onHotspotClick({ code: '40', type: '刮刀' });
  // 先点的刀位先返回：面板仍等待新刀位，不提前结束加载。
  h.infoRequests[0].resolve({ code: '12', type: '滚刀', history: [] });
  await settle();
  assert.equal(h.api.selectedCode.value, '40');
  assert.equal(h.api.selectedCutter.value.code, '40');
  assert.equal(h.api.infoLoading.value, true);
  h.infoRequests[1].resolve({ code: '40', type: '刮刀', history: [] });
  await Promise.all([first, second]);
  assert.equal(h.api.selectedCutter.value.code, '40');
  assert.equal(h.api.infoLoading.value, false);
});

test('an earlier cutter answering after the newer one does not overwrite the panel',async () => {
  const h = harness();
  const first = h.api.onHotspotClick({ code: '12', type: '滚刀' });
  const second = h.api.onHotspotClick({ code: '40', type: '刮刀' });
  h.infoRequests[1].resolve({ code: '40', type: '刮刀', history: [] });
  await second;
  h.infoRequests[0].resolve({ code: '12', type: '滚刀', history: [] });
  await first;
  assert.equal(h.api.selectedCode.value, '40');
  assert.equal(h.api.selectedCutter.value.code, '40');
});

test('closing the panel discards a response that arrives afterwards',async () => {
  const h = harness();
  const click = h.api.onHotspotClick({ code: '7', type: '滚刀' });
  h.api.closePanel();
  h.infoRequests[0].resolve({ code: '7', type: '滚刀', history: [] });
  await click;
  assert.equal(h.api.selectedCutter.value, null);
  assert.equal(h.api.selectedCode.value, '');
  assert.equal(h.api.infoLoading.value, false);
});

test('clicking a cutter that is still loading does not send another request',async () => {
  const h = harness();
  const first = h.api.onHotspotClick({ code: '7', type: '滚刀' });
  const again = h.api.onHotspotClick({ code: '7', type: '滚刀' });
  assert.equal(h.infoRequests.length, 1);
  h.infoRequests.forEach(request => request.resolve({ code: '7', type: '滚刀' }));
  await Promise.all([first, again]);
});

test('model selection registers each event name once',() => {
  const h = harness();
  const registered = [];
  h.api.setViewer({ addEventListener: name => registered.push(name) });
  // SDK 的枚举值就是同名字符串时，不能把同一个处理函数注册两次。
  h.api.bindModelSelection({ Glodon: { Bimface: { Viewer: { Viewer3DEvent: {
    SelectionChanged: 'SelectionChanged', MouseClicked: 'MouseClicked',
  } } } } });
  assert.deepEqual([...registered].sort(), ['ComponentsSelectionChanged', 'MouseClick', 'MouseClicked', 'SelectionChanged']);
});

test('an SDK script that is still loading is shared by repeated calls',async () => {
  const h = harness();
  const first = h.api.loadScript(SDK_SRC);
  const second = h.api.loadScript(SDK_SRC);
  assert.equal(h.scripts.length, 1);
  let secondDone = false;
  second.then(() => { secondDone = true; }, () => { secondDone = true; });
  await settle();
  assert.equal(secondDone, false, 'the second call waits for the same script');
  h.scripts[0].onload();
  await Promise.all([first, second]);
});

test('a failed SDK script is removed so that retrying downloads it again',async () => {
  const h = harness();
  const failed = h.api.loadScript(SDK_SRC);
  h.scripts[0].onerror();
  await assert.rejects(failed);
  const retry = h.api.loadScript(SDK_SRC);
  assert.equal(h.scripts.length, 2);
  let retried = false;
  retry.then(() => { retried = true; });
  await settle();
  assert.equal(retried, false, 'the retry waits for the new script');
  h.scripts[1].onload();
  await retry;
});

test('initialisation stops once the component unmounts while the SDK loads',async () => {
  const h = harness();
  h.api.initModel();
  await settle();
  assert.equal(h.scripts.length, 1);
  h.unmount();
  h.scripts[0].onload();
  await settle(6);
  assert.equal(h.viewTokenCalls.length, 0);
  assert.equal(h.sdkLoads.length, 0);
});

test('BIM model script and template compile', () => {
  const compiled = compileScript(descriptor, { id: 'bimface-model-test' });
  const { errors } = compileTemplate({ source: descriptor.template.content, filename, id: 'bimface-model-test',
    compilerOptions: { bindingMetadata: compiled.bindings, expressionPlugins: ['typescript'] } });
  assert.deepEqual(errors, []);
});

test('a failed cutter request is shown as a load failure in the panel', async () => {
  const h = harness();
  const click = h.api.onHotspotClick({ code: '7', type: '滚刀' });
  h.infoRequests[0].resolve({ code: '7', type: '滚刀', loadFailed: true });
  await click;
  const text = await h.render();
  assert.ok(text.includes('刀位数据加载失败'), text);
  assert.ok(!text.includes('暂无当前刀具数据'), text);
  assert.ok(!text.includes('暂无更换历史'), text);
});

test('status or mapping failures are shown beside the legend instead of as untested cutters', async () => {
  for (const [options, failed] of [[{}, false], [{ statusFails: true }, true], [{ mappingsFails: true }, true]]) {
    const h = harness(options);
    await h.mount();
    assert.equal(h.api.dataError.value, failed);
    h.api.modelState.value = 'ready';
    const text = await h.render();
    assert.equal(text.includes('刀位数据加载失败'), failed, text);
    h.unmount();
  }
});

test('model errors are shown in Chinese with the next step and without raw details', async () => {
  const cases = [
    ['SDK globals missing', { sdkGlobals: false }, h => finishSdkScript(h), 'BIM 组件未就绪，请点击重试'],
    ['SDK scripts unavailable', {}, async h => {
      await settle();
      h.scripts[0].onerror();
      await settle();
      h.scripts[1].onerror();
      await settle(6);
    }, 'BIM 组件未就绪，请点击重试'],
    ['view token failed', { viewToken: () => { throw new Error('Request failed with status code 500'); } },
      h => finishSdkScript(h), 'BIM 模型加载失败，请点击重试'],
    ['loader rejected', {}, async h => {
      await finishSdkScript(h);
      h.sdkLoads[0].onError({ code: 'authentication.failed', message: 'token expired' });
    }, 'BIM 模型初始化失败，请点击重试'],
    ['viewer creation failed', {}, async h => {
      await finishSdkScript(h);
      h.sdkLoads[0].onSuccess();
    }, 'BIM 模型初始化失败，请点击重试'],
  ];
  for (const [name, options, act, message] of cases) {
    const h = harness(options);
    h.api.initModel();
    await act(h);
    assert.equal(h.api.modelState.value, 'error', name);
    assert.equal(h.api.errorMsg.value, message, name);
  }
});

test('repeated WebGL context loss stops automatic rebuilding and asks the user to retry', async () => {
  const h = harness();
  const lose = () => h.api.handleWebglContextLost({ preventDefault() {} });
  h.clock.now = 0;
  lose();
  h.clock.now = 10 * 1000;
  lose();
  assert.equal(h.api.modelState.value, 'loading');
  assert.equal(h.pendingTimers().length, 1, 'one rebuild is scheduled');
  h.clock.now = 20 * 1000;
  lose();
  assert.equal(h.api.modelState.value, 'error');
  assert.match(h.api.errorMsg.value, /释放系统内存.*重启浏览器/);
  assert.equal(h.pendingTimers().length, 0, 'no further rebuild is scheduled');
  const text = await h.render();
  assert.ok(text.includes('重试'), text);
  // 用户点重试后重新计数，下一次丢失仍会自动重建。
  h.api.retryModel();
  assert.equal(h.api.modelState.value, 'loading');
  h.clock.now = 25 * 1000;
  lose();
  assert.equal(h.api.modelState.value, 'loading');
});

test('WebGL context losses spread over more than a minute keep rebuilding', () => {
  const h = harness();
  for (const seconds of [0, 70, 140, 210]) {
    h.clock.now = seconds * 1000;
    h.api.handleWebglContextLost({ preventDefault() {} });
    assert.equal(h.api.modelState.value, 'loading', `loss at ${seconds}s`);
  }
});

function loadCutterApi(request) {
  const source = fs.readFileSync(path.join(__dirname, '../cutterApi.ts'), 'utf8');
  const module = { exports: {} };
  const context = { module, exports: module.exports, require: () => ({ request }), localStorage: { getItem() {}, setItem() {}, removeItem() {} } };
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, context);
  return module.exports;
}

test('cutter API marks failures without changing the existing return shapes', async () => {
  const failing = loadCutterApi(async () => { throw new Error('network unavailable'); });
  const info = await failing.getCutterInfo('S3L');
  assert.equal(info.code, 'S3L');
  assert.equal(info.type, '刮刀');
  assert.equal(info.loadFailed, true);
  const errors = [];
  assert.deepEqual({ ...(await failing.getAllCutterStatus(error => errors.push(error))) }, {});
  assert.equal([...(await failing.getActiveCutterModelMappings(error => errors.push(error)))].length, 0);
  assert.equal(errors.length, 2);
  // 不传回调的老调用方照旧拿到空结果。
  assert.deepEqual({ ...(await failing.getAllCutterStatus()) }, {});
  assert.equal([...(await failing.getActiveCutterModelMappings())].length, 0);

  const working = loadCutterApi(async () => ({ data: { tool_parent_type: 'DISC', history: [] } }));
  const ok = await working.getCutterInfo('12');
  assert.equal(ok.type, '滚刀');
  assert.equal(ok.loadFailed, undefined);
});

test('the cutter panel shows its change history and scrolls long lists inside the panel', async () => {
  const postcss = require('postcss');
  const rules = {};
  for (const style of descriptor.styles) {
    postcss.parse(style.content).walkDecls(decl => { (rules[decl.parent.selector] ??= {})[decl.prop] = decl.value; });
  }
  // 面板里的小节不能被样式整体隐藏（"更换历史"曾被一条 nth-of-type 规则误隐藏）。
  const hiddenSections = Object.entries(rules)
    .filter(([selector, decls]) => /section/.test(selector) && decls.display === 'none')
    .map(([selector]) => selector);
  assert.deepEqual(hiddenSections, []);
  assert.equal(rules['.bm-panel']['overflow-y'], 'auto');
  assert.equal(rules['.history']['overflow-y'], 'auto');
  assert.ok(rules['.history']['max-height'], 'long histories scroll within a bounded list');

  const h = harness();
  const click = h.api.onHotspotClick({ code: '12', type: '滚刀' });
  h.infoRequests[0].resolve({ code: '12', type: '滚刀', history: [
    { serialNumber: 'D-0012-B', startRing: 120, endRing: 260, replaceDate: '2026-05-01' },
    { serialNumber: 'D-0012-A', startRing: 0, endRing: 120, replaceDate: '2026-03-01' },
  ] });
  await click;
  const text = await h.render();
  assert.ok(text.includes('更换历史'), text);
  assert.ok(text.includes('D-0012-B') && text.includes('D-0012-A'), text);
});
