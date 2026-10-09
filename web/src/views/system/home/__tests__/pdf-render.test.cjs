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
  let unmount;
  const calibration = { exports: {} };
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname, '../profileCalibration.ts'), 'utf8'),
    { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, calibration);
  const context = { ...vue, ...calibration.exports, onMounted: () => {}, onUnmounted: fn => { unmount = fn; },
    window: { devicePixelRatio: 1, innerHeight: 768, clearTimeout() {} } };
  vm.createContext(context);
  vm.runInContext(ts.transpileModule(script, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText +
    '\nglobalThis.api={renderPdf,setPage:p=>pdfPage=p,canvasRef,stageRef,isFullscreen,getTask:()=>renderTask};', context);
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
        settleCancellation() { active = false; reject({ name: 'RenderingCancelledException' }); } };
      tasks.push(task);
      return task;
    } });
  return { api, tasks, unmount };
}

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
