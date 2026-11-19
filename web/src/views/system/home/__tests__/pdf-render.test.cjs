const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const { parse } = require('@vue/compiler-sfc');

function harness() {
  const source = fs.readFileSync(path.join(__dirname, '../ProjectRouteMap.vue'), 'utf8');
  const script = parse(source).descriptor.scriptSetup.content
    .replace(/^import .*$/gm, '')
    .replace('pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;', '');
  let unmount, beforeUnmount = () => {};
  const calibration = { exports: {} };
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname, '../profileCalibration.ts'), 'utf8'),
    { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, calibration);
  const context = { ...vue, ...calibration.exports, onMounted: () => {}, onUnmounted: fn => { unmount = fn; },
    onBeforeUnmount: fn => { beforeUnmount = fn; },
    requestAnimationFrame: callback => setImmediate(callback),
    window: { devicePixelRatio: 1, innerHeight: 768, clearTimeout() {} } };
  vm.createContext(context);
  vm.runInContext(ts.transpileModule(script, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText +
    '\nglobalThis.api={renderPdf,toggleFullscreen,setPage:p=>pdfPage=p,canvasRef,stageRef,isFullscreen,pdfError,getTask:()=>renderTask};', context);
  const api = context.api;
  let active = false;
  const tasks = [];
  api.stageRef.value = { clientWidth: 900, closest: () => null };
  api.canvasRef.value = { style: {}, getContext: () => ({}),
    set width(value) { assert.equal(active, false, 'canvas resized before render settled'); },
    set height(value) { assert.equal(active, false, 'canvas resized before render settled'); } };
  api.setPage({ getViewport: ({ scale }) => ({ width: 9524 * scale, height: 652 * scale }),
    render() {
      assert.equal(active, false, 'overlapping render');
      active = true;
      let resolve, reject;
      const promise = new Promise((a, b) => { resolve = a; reject = b; });
      const task = { promise, cancel() {},
        finish() { active = false; resolve(); },
        fail() { active = false; reject(new Error('render failed')); },
        settleCancellation() { active = false; reject({ name: 'RenderingCancelledException' }); } };
      tasks.push(task);
      return task;
    } });
  return { api, tasks, unmount, beforeUnmount: () => beforeUnmount() };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

test('rapid fullscreen and resize wait for cancellation and only newest request renders', async () => {
  const h = harness();
  const first = h.api.renderPdf();
  h.api.isFullscreen.value = true;
  const second = h.api.renderPdf();
  h.api.isFullscreen.value = false;
  const third = h.api.renderPdf();
  assert.equal(h.tasks.length, 1);
  h.tasks[0].settleCancellation();
  await first;
  await second;
  assert.equal(h.tasks.length, 2);
  assert.equal(h.api.getTask(), h.tasks[1]);
  h.tasks[1].finish();
  await third;
  assert.equal(h.api.getTask(), null);
});

test('unmount invalidates queued renders before they reuse the canvas', async () => {
  const h = harness();
  const first = h.api.renderPdf();
  const queued = h.api.renderPdf();
  // Vue clears template refs during unmount before teardown resets the canvas.
  h.api.canvasRef.value = null;
  h.unmount();
  h.tasks[0].settleCancellation();
  await Promise.all([first, queued]);
  assert.equal(h.tasks.length, 1);
  assert.equal(h.api.getTask(), null);
});

test('a repeated request for an unchanged size does not repaint the PDF', async () => {
  const h = harness();
  const first = h.api.renderPdf();
  h.tasks[0].finish();
  await first;
  const repeated = h.api.renderPdf();
  await settle();
  assert.equal(h.tasks.length, 1);
  await repeated;
  // 进行中的同尺寸请求也不打断重来。
  h.api.isFullscreen.value = true;
  const fullscreen = h.api.renderPdf();
  const again = h.api.renderPdf();
  h.tasks[1].finish();
  await fullscreen;
  await settle();
  assert.equal(h.tasks.length, 2);
  h.tasks.slice(2).forEach(task => task.finish());
  await again;
});

test('a fullscreen switch and the resize notification it causes paint only once', async () => {
  const h = harness();
  const first = h.api.renderPdf();
  h.tasks[0].finish();
  await first;
  const toggled = h.api.toggleFullscreen();
  while (h.tasks.length < 2) await settle();
  // 全屏改变了容器尺寸，ResizeObserver 防抖后再请求一次。
  const observed = h.api.renderPdf();
  h.tasks[1].finish();
  await toggled;
  await settle();
  assert.equal(h.tasks.length, 2);
  h.tasks.slice(2).forEach(task => task.finish());
  await observed;
});

test('a failed render can be retried at the same size', async () => {
  const h = harness();
  const first = h.api.renderPdf();
  h.tasks[0].fail();
  await first;
  assert.equal(h.api.pdfError.value, 'PDF 渲染失败，请刷新重试');
  const retry = h.api.renderPdf();
  assert.equal(h.tasks.length, 2);
  h.tasks[1].finish();
  await retry;
});

test('unmount releases the canvas although Vue clears the template ref first', async () => {
  for (const pending of [false, true]) {
    const h = harness();
    const canvas = { style: {}, width: 0, height: 0, getContext: () => ({}) };
    h.api.canvasRef.value = canvas;
    const rendering = h.api.renderPdf();
    if (!pending) {
      h.tasks[0].finish();
      await rendering;
    }
    assert.ok(canvas.width > 0 && canvas.height > 0);
    h.beforeUnmount();
    h.api.canvasRef.value = null;
    h.unmount();
    if (pending) {
      assert.ok(canvas.width > 0, 'canvas is kept until the cancelled render settles');
      h.tasks[0].settleCancellation();
      await rendering;
      await settle();
    }
    assert.equal(canvas.width, 0);
    assert.equal(canvas.height, 0);
  }
});
