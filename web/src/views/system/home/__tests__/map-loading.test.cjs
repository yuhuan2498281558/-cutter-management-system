const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const { parse } = require('@vue/compiler-sfc');

function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

function harness() {
  const script = parse(fs.readFileSync(path.join(__dirname, '../ProjectRouteMap.vue'), 'utf8'))
    .descriptor.scriptSetup.content.replace(/^import .*$/gm, '')
    .replace('pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;', '');
  const calibration = { exports: {} };
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname, '../profileCalibration.ts'), 'utf8'),
    { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, calibration);
  const project = deferred(), strata = deferred(), openings = deferred(), pdf = deferred(), render = deferred();
  const started = [];
  let mount, unmount;
  const page = {
    getViewport: ({ scale }) => ({ width: 9524 * scale, height: 652 * scale }),
    getTextContent: async () => ({ items: Array.from({ length: 281 }, (_, n) => ({ str: `${String(n * 10).padStart(4, '0')}环` })) }),
    render: () => ({ promise: render.promise, cancel() {} }),
  };
  const document = { getPage: async () => page, destroy() {} };
  const context = {
    ...vue, ...calibration.exports,
    onMounted: fn => { mount = fn; }, onUnmounted: fn => { unmount = fn; },
    window: { devicePixelRatio: 1, innerHeight: 768, clearTimeout() {} },
    ResizeObserver: class { observe() {} disconnect() {} },
    GetHomeProjectInfo: () => { started.push('project'); return project.promise; },
    request: ({ url }) => {
      const key = url.includes('warehouse_opening') ? 'openings' : 'strata';
      started.push(key);
      return key === 'openings' ? openings.promise : strata.promise;
    },
    pdfjsLib: { getDocument: () => { started.push('pdf'); return { promise: pdf.promise }; } },
  };
  vm.createContext(context);
  vm.runInContext(ts.transpileModule(script, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText
    + '\nglobalThis.api={progressText,openingStatusText,currentPercent,totalRings,selectedStratumText,selectedRatioText,pdfError,canvasRef,stageRef};', context);
  const api = context.api;
  return { api, started, project, strata, openings, pdf, render, document,
    mount: () => mount(), unmount: () => unmount() };
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
