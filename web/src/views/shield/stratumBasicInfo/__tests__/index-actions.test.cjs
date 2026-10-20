const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');
const { compile, settle, deferred, plain } = require('../../analysis/__tests__/helpers.cjs');

const file = path.resolve(__dirname, '../index.vue');
const XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

// Compiles the real <script setup>; only fast-crud, Element Plus, the API module and browser objects are replaced.
function mountPage(t, { api, confirm = async () => 'confirm' }) {
  const { descriptor, errors } = parse(fs.readFileSync(file, 'utf8'), { filename: file });
  assert.deepEqual(errors, []);
  const script = compileScript(descriptor, { id: 'stratum-index-test' });
  const notices = [], blobs = [], links = [], revoked = [], refreshes = [];
  const modules = {
    vue: { ...vue, onMounted() {} },
    '@fast-crud/fast-crud': {
      useExpose: () => ({ crudExpose: { doRefresh: () => refreshes.push('refresh') } }),
      useCrud: () => ({ resetCrudOptions() {} }),
    },
    './crud': { createCrudOptions: () => ({ crudOptions: {} }) },
    'element-plus': {
      ElMessage: { success: text => notices.push(['success', text]), error: text => notices.push(['error', text]) },
      ElMessageBox: { confirm },
    },
    './api': api,
    '/@/utils/storage': { getAuthHeader: () => ({ Authorization: 'JWT test' }) },
    '/@/views/shield/components/ExportDropdown.vue': { default: { name: 'ExportDropdown' } },
  };
  const globals = {
    Blob: class { constructor(parts, options) { this.parts = parts; this.type = options?.type; blobs.push(this); } },
    window: { URL: { createObjectURL: () => 'blob:template', revokeObjectURL: url => revoked.push(url) } },
    document: { createElement: tag => { const link = { tag, click() { this.clicked = true; } }; links.push(link); return link; } },
  };
  const component = compile(script.content, name => {
    if (name in modules) return modules[name];
    throw new Error(`Unexpected import ${name}`);
  }, globals).default;
  const scope = vue.effectScope();
  const state = scope.run(() => component.setup({}, { expose() {} }));
  t.after(() => scope.stop());
  return { state, notices, blobs, links, revoked, refreshes };
}

test('template download writes the blob response body, not the axios response object', async t => {
  const bytes = new Uint8Array([0x50, 0x4b, 0x03, 0x04]);
  const response = { data: bytes, status: 200, headers: {} };
  const page = mountPage(t, { api: { downloadTemplate: async () => response } });

  await page.state.handleDownloadTemplate();

  assert.equal(page.blobs.length, 1);
  assert.equal(page.blobs[0].parts.length, 1);
  assert.equal(page.blobs[0].parts[0], bytes);
  assert.equal(page.blobs[0].type, XLSX_TYPE);
  assert.equal(page.links.length, 1);
  assert.equal(page.links[0].tag, 'a');
  assert.equal(page.links[0].href, 'blob:template');
  assert.equal(page.links[0].download, '导入地层基本信息模板.xlsx');
  assert.equal(page.links[0].clicked, true);
  assert.deepEqual(page.revoked, ['blob:template']);
  assert.deepEqual(page.notices, [['success', '模板下载成功']]);
});

test('template download failure shows one error and creates no file', async t => {
  const page = mountPage(t, { api: { downloadTemplate: async () => { throw { message: 'Network Error' }; } } });

  await page.state.handleDownloadTemplate();

  assert.equal(page.blobs.length, 0);
  assert.equal(page.links.length, 0);
  assert.deepEqual(page.notices, [['error', '模板下载失败']]);
});

test('PDF extraction business error shows the backend msg and clears loading', async t => {
  const calls = [];
  const pending = deferred();
  const page = mountPage(t, { api: { importFromPdf: params => { calls.push(plain(params)); return pending.promise; } } });

  const running = page.state.handleImportFromPdf();
  await settle();
  assert.equal(page.state.pdfImporting.value, true);
  assert.deepEqual(calls, [{ project: 1 }]);

  pending.reject({ code: 4000, msg: 'PDF 不存在' });
  await running;

  assert.equal(page.state.pdfImporting.value, false);
  assert.deepEqual(page.notices, [['error', '导入失败：PDF 不存在']]);
  assert.deepEqual(page.refreshes, []);
});

test('PDF extraction falls back to the transport message, then to 网络错误', async t => {
  const failures = [{ message: 'timeout of 20000ms exceeded' }, {}, undefined];
  const page = mountPage(t, { api: { importFromPdf: async () => { throw failures.shift(); } } });

  await page.state.handleImportFromPdf();
  await page.state.handleImportFromPdf();
  await page.state.handleImportFromPdf();

  assert.deepEqual(page.notices, [
    ['error', '导入失败：timeout of 20000ms exceeded'],
    ['error', '导入失败：网络错误'],
    ['error', '导入失败：网络错误'],
  ]);
  assert.equal(page.state.pdfImporting.value, false);
});

test('PDF extraction success reports counts and refreshes the table', async t => {
  const page = mountPage(t, {
    api: { importFromPdf: async () => ({ code: 2000, data: { created: 2, updated: 3, total: 5 }, msg: 'success' }) },
  });

  await page.state.handleImportFromPdf();

  assert.deepEqual(page.notices, [['success', '导入完成：新建 2 条，更新 3 条，共 5 环']]);
  assert.deepEqual(page.refreshes, ['refresh']);
  assert.equal(page.state.pdfImporting.value, false);
});

test('cancelling the PDF confirmation sends no request', async t => {
  const calls = [];
  const page = mountPage(t, {
    api: { importFromPdf: async params => { calls.push(plain(params)); } },
    confirm: async () => { throw 'cancel'; },
  });

  await page.state.handleImportFromPdf();

  assert.deepEqual(calls, []);
  assert.deepEqual(page.notices, []);
  assert.equal(page.state.pdfImporting.value, false);
});
