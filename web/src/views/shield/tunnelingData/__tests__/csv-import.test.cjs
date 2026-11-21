const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vue = require('vue');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');
const { compile, settle, deferred, plain, descendants } = require('../../analysis/__tests__/helpers.cjs');

const file = path.resolve(__dirname, '../index.vue');

// Compiles the real script and template; fast-crud, request, ImportCsv and FormData are replaced.
function mountPage(t, { respond = async () => ({ code: 2000, data: [] }), importCsv = async () => ({ code: 2000, msg: '导入成功' }), search = {} } = {}) {
  const { descriptor, errors } = parse(fs.readFileSync(file, 'utf8'), { filename: file });
  assert.deepEqual(errors, []);
  const script = compileScript(descriptor, { id: 'tunneling-index-test' });
  const template = compileTemplate({ source: descriptor.template.content, filename: file, id: 'tunneling-index-test' });
  assert.deepEqual(template.errors, []);
  const requests = [], uploads = [], notices = [], refreshes = [], mounted = [];
  const modules = {
    vue: { ...vue, onMounted: fn => mounted.push(fn) },
    '@fast-crud/fast-crud': { useExpose: () => ({ crudExpose: { doRefresh: () => refreshes.push('refresh'), getSearchFormData: () => search } }), useCrud: () => ({}) },
    './crud': { createCrudOptions: () => ({ crudOptions: {} }) },
    'element-plus': { ElMessage: Object.fromEntries(['success', 'warning', 'error'].map(key => [key, text => notices.push([key, text])])) },
    '/@/utils/service': { request: config => { requests.push(plain(config)); return respond(config); } },
    './api': { ImportCsv: data => { uploads.push(data.entries); return importCsv(data); } },
    '/@/views/shield/components/ExportDropdown.vue': { default: { name: 'ExportDropdown' } },
  };
  const globals = { FormData: class { constructor() { this.entries = []; } append(key, value) { this.entries.push([key, value]); } } };
  const component = compile(script.content, name => {
    if (name in modules) return modules[name];
    throw new Error(`Unexpected import ${name}`);
  }, globals).default;
  const scope = vue.effectScope();
  const state = scope.run(() => component.setup({}, { expose() {} }));
  t.after(() => scope.stop());
  const { render } = compile(template.code, name => {
    assert.equal(name, 'vue');
    return { ...vue, resolveComponent: name => ({ name }), resolveDirective: () => ({}) };
  });
  const context = vue.proxyRefs(state);
  const find = name => descendants(render(context, [])).find(node => node.type?.name === name);
  // 对话框底部"选择文件并导入"按钮在 el-upload 里面
  const uploadButton = () => descendants(find('el-upload')).find(node => node !== find('el-upload') && node.type?.name === 'el-button');
  return { state, requests, uploads, notices, refreshes, mounted, find, uploadButton };
}

test('CSV import shows loading and locks the upload until the request finishes', async t => {
  const pending = deferred();
  const page = mountPage(t, { importCsv: () => pending.promise });
  const csv = { name: 'ring-100.csv' };
  page.state.importVisible.value = true;
  page.state.importForm.project = 1;
  page.state.importForm.shield_machine = 2;
  assert.equal(page.uploadButton().props.loading, false);
  assert.equal(page.find('el-upload').props.disabled, false);

  const uploading = page.state.handleBeforeUpload(csv);
  await settle();

  assert.equal(page.state.importing.value, true);
  assert.equal(page.uploadButton().props.loading, true);
  assert.equal(page.find('el-upload').props.disabled, true);
  assert.equal(page.uploads.length, 1);
  assert.equal(page.uploads[0][0][1], csv);
  assert.deepEqual(page.uploads[0].slice(1), [['project', '1'], ['shield_machine', '2']]);

  pending.resolve({ code: 2000, msg: '导入 30 环' });
  assert.equal(await uploading, false);

  assert.deepEqual(page.notices, [['success', '导入 30 环']]);
  assert.deepEqual(page.refreshes, ['refresh']);
  assert.equal(page.state.importing.value, false);
  assert.equal(page.uploadButton().props.loading, false);
  assert.equal(page.find('el-upload').props.disabled, false);
  assert.equal(page.state.importVisible.value, false, 'a successful import closes the dialog');
});

test('failed CSV import shows the backend msg and unlocks the upload', async t => {
  const page = mountPage(t, { importCsv: async () => { throw { code: 4000, msg: 'CSV 缺少环号列' }; } });
  page.state.importForm.project = 1;
  page.state.importForm.shield_machine = 2;

  assert.equal(await page.state.handleBeforeUpload({ name: 'bad.csv' }), false);

  assert.deepEqual(page.notices, [['error', 'CSV 缺少环号列']]);
  assert.deepEqual(page.refreshes, []);
  assert.equal(page.state.importing.value, false);
});

test('CSV import without project or shield machine only warns', async t => {
  const page = mountPage(t);
  page.state.importForm.project = 1;

  assert.equal(await page.state.handleBeforeUpload({ name: 'ring.csv' }), false);

  assert.deepEqual(page.notices, [['warning', '请先选择项目和盾构机']]);
  assert.deepEqual(page.uploads, []);
});

test('the page has no import selectors of its own: mounting only loads the table', async t => {
  const page = mountPage(t);

  page.mounted.forEach(fn => fn());
  await settle();

  assert.deepEqual(page.requests, []);
  assert.deepEqual(page.refreshes, ['refresh']);
  assert.equal(page.state.importVisible.value, false);
});

test('opening the import dialog loads options once and preselects the only project and shield machine', async t => {
  const page = mountPage(t, { respond: async config => ({ code: 2000, data: config.url.includes('project')
    ? [{ id: 1, project_name: '长乐隧道' }] : [{ id: 2, shield_model: '中铁 1 号' }] }) });

  await page.state.openImport();
  await page.state.openImport();

  assert.equal(page.state.importVisible.value, true);
  assert.deepEqual(page.requests, [
    { url: '/api/shield/project/', method: 'get', params: { limit: 10000 } },
    { url: '/api/shield/shield_machine_basic_info/', method: 'get', params: { limit: 10000 } },
  ]);
  assert.deepEqual(plain(page.state.projectOptions.value), [{ id: 1, project_name: '长乐隧道' }]);
  assert.deepEqual(plain(page.state.machineOptions.value), [{ id: 2, shield_model: '中铁 1 号' }]);
  assert.deepEqual(plain(page.state.importForm), { project: 1, shield_machine: 2 });
});

test('the import target defaults to the project and shield machine chosen in the search bar', async t => {
  const page = mountPage(t, {
    search: { project: 3, shield_machine: 4 },
    respond: async config => ({ code: 2000, data: config.url.includes('project')
      ? [{ id: 1 }, { id: 3 }] : [{ id: 2 }, { id: 4 }] }),
  });

  await page.state.openImport();

  assert.deepEqual(plain(page.state.importForm), { project: 3, shield_machine: 4 });
});

test('a failed option request leaves empty options and no unhandled rejection', async t => {
  const rejections = [];
  const onRejection = reason => rejections.push(reason);
  process.on('unhandledRejection', onRejection);
  t.after(() => process.off('unhandledRejection', onRejection));
  const page = mountPage(t, { respond: async () => { throw { code: 4000, msg: '无权限' }; } });

  await page.state.openImport();
  await new Promise(resolve => setTimeout(resolve, 0));

  assert.deepEqual(rejections, []);
  assert.deepEqual(plain(page.state.projectOptions.value), []);
  assert.deepEqual(plain(page.state.machineOptions.value), []);
  assert.equal(page.state.importForm.project, undefined);
  assert.equal(page.state.importForm.shield_machine, undefined);
});
