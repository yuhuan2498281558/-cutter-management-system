const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');

const filename = path.join(__dirname, '../ProjectRouteMap.vue');
const { descriptor } = parse(fs.readFileSync(filename, 'utf8'), { filename });

function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

function harness(stratumPages) {
  const script = descriptor.scriptSetup.content.replace(/^import .*$/gm, '')
    .replace('pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;', '');
  const compiled = compileScript(descriptor, { id: 'map-loading-test' });
  const exposed = Object.keys(compiled.bindings).filter(name => !compiled.imports?.[name]);
  const calibration = { exports: {} };
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname, '../profileCalibration.ts'), 'utf8'),
    { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, calibration);
  const project = deferred(), strata = deferred(), openings = deferred(), pdf = deferred(), render = deferred();
  const started = [];
  const stratumRequests = [];
  const openingRequests = [];
  const observers = [];
  let renders = 0;
  let mount, unmount;
  const page = {
    getViewport: ({ scale }) => ({ width: 9524 * scale, height: 652 * scale }),
    getTextContent: async () => ({ items: Array.from({ length: 281 }, (_, n) => ({ str: `${String(n * 10).padStart(4, '0')}环` })) }),
    render: () => { renders += 1; return { promise: render.promise, cancel() {} }; },
  };
  const document = { getPage: async () => page, destroy() {} };
  const context = {
    ...vue, ...calibration.exports,
    onMounted: fn => { mount = fn; }, onUnmounted: fn => { unmount = fn; }, onBeforeUnmount: () => {},
    window: { devicePixelRatio: 1, innerHeight: 768, clearTimeout() {}, setTimeout: fn => { fn(); return 1; } },
    ResizeObserver: class {
      constructor(callback) { this.callback = callback; observers.push(this); }
      observe(target) { this.target = target; }
      disconnect() {}
    },
    GetHomeProjectInfo: () => { started.push('project'); return project.promise; },
    request: ({ url, params }) => {
      const key = url.includes('warehouse_opening') ? 'openings' : 'strata';
      started.push(key);
      if (key === 'openings') { openingRequests.push(params); return openings.promise; }
      stratumRequests.push(params);
      return stratumPages ? Promise.resolve().then(() => stratumPages(params.page)) : strata.promise;
    },
    pdfjsLib: { getDocument: () => { started.push('pdf'); return { promise: pdf.promise }; } },
  };
  vm.createContext(context);
  vm.runInContext(ts.transpileModule(script, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText
    + `\nglobalThis.api={${exposed.join(',')}};`, context);
  const api = context.api;
  return { api, started, stratumRequests, openingRequests, observers, renders: () => renders,
    project, strata, openings, pdf, render, document,
    mount: () => mount(), unmount: () => unmount() };
}

async function footerText(api) {
  const { renderToString } = require('@vue/server-renderer');
  const template = descriptor.template.content.match(/<footer class="route-footer">[\s\S]*?<\/footer>/)[0];
  const html = await renderToString(vue.createSSRApp({ template, setup: () => api }));
  return html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
}

test('slow project and stratum requests do not block PDF, openings or actual progress', async () => {
  const h = harness();
  const mounted = h.mount();
  assert.deepEqual(new Set(h.started), new Set(['project', 'strata', 'pdf', 'openings']));
  assert.equal(h.api.progressText.value, '加载中…');
  assert.equal(h.api.openingStatusText.value, '读取中…');
  h.openings.resolve({ data: [{ id: 2, ring_no: '487' }, { id: 1, ring_no: '90' }] });
  await settle();
  assert.equal(h.api.openingStatusText.value, '487 环');
  assert.equal(h.api.currentPercent.value, null);
  h.pdf.resolve(h.document);
  await settle();
  assert.equal(h.api.progressText.value, '17.4%');
  assert.equal(h.api.totalRings.value, 2800);
  assert.equal(h.api.selectedRatioText.value, '加载中…');
  h.project.resolve({ data: { project_name: '项目' } });
  h.strata.resolve({ data: [{ ring_no: '487', stratum_info: '混合地层',
    stratum_type_ratios: { CLAY: 100 }, stratum_ratio_labels: { CLAY: '黏土' } }] });
  await mounted;
  assert.equal(h.api.selectedStratumText.value, '混合地层');
  assert.equal(h.api.selectedRatioText.value, '黏土 100.00%');
  h.unmount();
});

test('stratum pagination loads later rings despite the server page limit', async () => {
  const h = harness(page => ({
    data: [{ ring_no: String(page === 3 ? 487 : page), stratum_type_ratios: { CLAY: 100 }, stratum_ratio_labels: { CLAY: '黏土' } }],
    total: 3, is_next: page < 3, limit: 1,
  }));
  const mounted = h.mount();
  h.project.resolve({ data: {} });
  h.openings.resolve({ data: [{ ring_no: '487' }] });
  h.pdf.resolve(h.document);
  await mounted;
  assert.deepEqual(h.stratumRequests.map(p => p.page), [1, 2, 3]);
  assert.ok(h.stratumRequests.every(p => p.project === 1 && p.limit <= 999));
  assert.equal(h.api.stratumCount.value, 3);
  assert.equal(h.api.selectedRatioText.value, '黏土 100.00%');
  h.unmount();
});

test('a failed later stratum page does not publish a partial coverage count', async () => {
  const h = harness(page => {
    if (page === 2) throw new Error('network unavailable');
    return { data: [{ ring_no: '1' }], total: 2, is_next: true };
  });
  const mounted = h.mount();
  h.project.resolve({ data: {} });
  h.openings.resolve({ data: [] });
  h.pdf.resolve(h.document);
  await mounted;
  assert.equal(h.api.stratumCount.value, 0);
  assert.deepEqual(h.stratumRequests.map(p => p.page), [1, 2]);
  assert.equal(h.api.selectedStratumText.value, '加载失败');
  assert.equal(h.api.selectedRatioText.value, '加载失败');
  assert.ok((await footerText(h.api)).includes('地层信息 加载失败'));
  h.unmount();
});

test('verified range and progress do not wait for slow canvas rendering', async () => {
  const h = harness();
  h.api.canvasRef.value = { style: {}, getContext: () => ({}) };
  h.api.stageRef.value = { clientWidth: 900, closest: () => null };
  const mounted = h.mount();
  h.project.resolve({ data: {} });
  h.strata.resolve({ data: [] });
  h.openings.resolve({ data: [{ ring_no: '487' }] });
  h.pdf.resolve(h.document);
  await settle();
  assert.equal(h.api.progressText.value, '17.4%');
  h.render.resolve();
  await mounted;
  h.unmount();
});

test('opening failure is distinguished from an empty successful response', async () => {
  for (const failed of [false, true]) {
    const h = harness();
    const mounted = h.mount();
    h.project.resolve({ data: {} });
    h.strata.resolve({ data: [] });
    h.pdf.resolve(h.document);
    if (failed) h.openings.reject(new Error('timeout'));
    else h.openings.resolve({ data: [] });
    await mounted;
    assert.equal(h.api.currentPercent.value, null);
    assert.equal(h.api.openingStatusText.value, failed ? '读取失败' : '暂无记录');
    assert.equal(h.api.progressText.value, failed ? '加载失败，请刷新重试' : '暂不可计算');
    h.unmount();
  }
});

test('PDF failure does not discard openings or invent a percentage', async () => {
  const h = harness();
  const mounted = h.mount();
  h.project.resolve({ data: {} });
  h.strata.resolve({ data: [] });
  h.openings.resolve({ data: [{ ring_no: '487' }] });
  h.pdf.reject(new Error('PDF unavailable'));
  await mounted;
  assert.equal(h.api.openingStatusText.value, '487 环');
  assert.equal(h.api.totalRings.value, 0);
  assert.equal(h.api.currentPercent.value, null);
  assert.equal(h.api.progressText.value, '加载失败，请刷新重试');
  h.unmount();
});

test('opening markers are requested in numeric ring order', async () => {
  const h = harness();
  const mounted = h.mount();
  h.project.resolve({ data: {} });
  h.strata.resolve({ data: [] });
  h.openings.resolve({ data: [] });
  h.pdf.resolve(h.document);
  await mounted;
  assert.equal(h.openingRequests.length, 1);
  assert.equal(h.openingRequests[0].ordering, 'ring_int');
  assert.equal(h.openingRequests[0].project, 1);
  h.unmount();
});

test('resize notifications watch the scroll container and skip repainting an unchanged map', async () => {
  const h = harness();
  h.api.canvasRef.value = { style: {}, getContext: () => ({}) };
  h.api.stageRef.value = { clientWidth: 900, closest: () => null };
  h.api.bodyRef.value = { clientWidth: 600 };
  const mounted = h.mount();
  h.project.resolve({ data: {} });
  h.strata.resolve({ data: [] });
  h.openings.resolve({ data: [{ ring_no: '487' }] });
  h.pdf.resolve(h.document);
  h.render.resolve();
  await mounted;
  assert.equal(h.renders(), 1);
  assert.equal(h.observers.length, 1);
  assert.equal(h.observers[0].target, h.api.bodyRef.value);
  // 观察器开始观察时浏览器会立即发一次初始通知，尺寸没变不应再整图重画。
  h.observers[0].callback([]);
  await settle();
  assert.equal(h.renders(), 1);
  h.unmount();
});

test('stratum failure is shown as a failure rather than as missing data', async () => {
  for (const failed of [false, true]) {
    const h = harness(() => {
      if (failed) throw new Error('network unavailable');
      return { data: [], total: 0, is_next: false };
    });
    const mounted = h.mount();
    h.project.resolve({ data: {} });
    h.openings.resolve({ data: [{ ring_no: '487' }] });
    h.pdf.resolve(h.document);
    await mounted;
    assert.equal(h.api.stratumCount.value, 0);
    assert.equal(h.api.selectedStratumText.value, failed ? '加载失败' : '待导入');
    assert.equal(h.api.selectedRatioText.value, failed ? '加载失败' : '暂无占比数据');
    const footer = await footerText(h.api);
    assert.ok(footer.includes(failed ? '地层信息 加载失败' : '地层信息 0 环'), footer);
    h.unmount();
  }
});
