const { test } = require('node:test');
const assert = require('node:assert/strict');
const { setup, settle, deferred, plain } = require('../../analysis/__tests__/helpers.cjs');

const fastCrud = { useExpose: () => ({ crudExpose: { doRefresh() {} } }), useCrud: () => ({ resetCrudOptions() {} }) };
const mountPage = (t, request) => setup(t, '../project/index.vue', {
  modules: { '@fast-crud/fast-crud': fastCrud, './crud': { createCrudOptions: () => ({ crudOptions: {} }) } },
  request,
});
const button = (h, text) => h.nodes().find(node => node.type?.name === 'el-button'
  && node.children?.default?.()?.some(child => child.children === text));

test('import dialog loads all projects and shield machines', async t => {
  const h = mountPage(t, async config => ({ code: 2000, data: config.url.includes('project')
    ? [{ id: 1, project_name: '长乐隧道' }] : [{ id: 2, shield_model: '中铁 1 号' }] }));

  await h.state.openImportDialog();

  assert.equal(h.state.importDialogVisible.value, true);
  assert.deepEqual(h.requests, [
    { url: '/api/shield/project/', method: 'get', params: { page: 1, limit: 10000 } },
    { url: '/api/shield/shield_machine_basic_info/', method: 'get', params: { page: 1, limit: 10000 } },
  ]);
  assert.deepEqual(plain(h.state.projectOptions.value), [{ id: 1, project_name: '长乐隧道' }]);
  assert.deepEqual(plain(h.state.machineOptions.value), [{ id: 2, shield_model: '中铁 1 号' }]);
});

test('import dialog still opens when the option requests fail', async t => {
  const h = mountPage(t, async () => { throw { code: 4000, msg: '无权限' }; });

  await h.state.openImportDialog();
  await settle();

  assert.equal(h.state.importDialogVisible.value, true);
  assert.deepEqual(plain(h.state.projectOptions.value), []);
  assert.deepEqual(plain(h.state.machineOptions.value), []);
  assert.deepEqual(h.notices, []);
});

test('开始导入 shows loading while the XML import runs', async t => {
  const pending = deferred();
  const h = mountPage(t, config => config.method === 'post' ? pending.promise : Promise.resolve({ code: 2000, data: [] }));
  await h.state.openImportDialog();
  Object.assign(h.state.importForm, { project: 1, shield_machine: 2, folder_path: ' \\\\nas\\ring ' });

  const submitting = h.state.submitImport();
  await settle();
  assert.equal(button(h, '开始导入').props.loading, true);
  assert.deepEqual(h.requests.at(-1), { url: '/api/shield/project/1/import_tunneling_xml/', method: 'post', data: {
    shield_machine: 2, folder_path: '\\\\nas\\ring', files_per_ring: 10, overwrite: true, import_incomplete: false,
  } });

  pending.resolve({ code: 2000, msg: '已导入 12 环' });
  await submitting;
  assert.equal(button(h, '开始导入').props.loading, false);
  assert.equal(h.state.importDialogVisible.value, false);
  assert.deepEqual(h.notices, [['success', '已导入 12 环']]);
});
