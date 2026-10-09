// Real Fast-CRUD query/state handling, actual CRUD options, settings transforms and API.
// Only the HTTP transport and the unmounted search/table widget boundary are substituted.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const ts = require('typescript');
const vue = require('vue');
const fastCrud = require('@fast-crud/fast-crud');
const elementUi = require('@fast-crud/ui-element');
const webRoot = path.resolve(__dirname, '../../../../..');
const plain = value => JSON.parse(JSON.stringify(value));
const settle = () => new Promise(setImmediate);

function compile(source, requireModule, globals = {}) {
  const context = { exports: {}, require: requireModule, setTimeout, clearTimeout, ...globals };
  vm.runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, context);
  return context.exports;
}

// Extract the actual method through the TypeScript AST; do not reimplement its
// transformQuery/transformRes or initialize production upload/environment integrations.
function readCommonOptions() {
  const file = path.join(webRoot, 'src/settings.ts');
  const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true);
  const methods = [];
  function visit(node) {
    if (ts.isMethodDeclaration(node) && node.name?.getText(source) === 'commonOptions') methods.push(node.getText(source));
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.equal(methods.length, 1, 'Expected the production Fast-CRUD commonOptions method');
  return compile('export const options = ({' + methods[0] + '}).commonOptions;', name => {
    throw new Error('Unexpected settings import: ' + name);
  }, { auth: () => true, successNotification() {} }).options;
}
const commonOptions = readCommonOptions();
const crudSource = process.env.OPENING_SEARCH_TEST_REF
  ? execFileSync('git', ['show', process.env.OPENING_SEARCH_TEST_REF + ':web/src/views/shield/warehouseOpening/crud.tsx'], { cwd: webRoot, encoding: 'utf8' })
  : fs.readFileSync(path.resolve(__dirname, '../crud.tsx'), 'utf8');

// A Vue host with no browser or DOM. Mounting a null-rendering harness gives the
// production composables a real component/effect scope and normal disposal.
const renderer = vue.createRenderer({
  createElement: type => ({ type, children: [] }),
  createText: text => ({ text }),
  createComment: text => ({ comment: text }),
  setText: (node, text) => { node.text = text; },
  setElementText: (node, text) => { node.text = text; },
  patchProp() {},
  parentNode: node => node.parent,
  nextSibling: () => null,
  insert(node, parent) { node.parent = parent; parent.children.push(node); },
  remove(node) {
    if (node.parent) node.parent.children = node.parent.children.filter(child => child !== node);
  },
});

function response(total, page = 1, limit = 20, ids = [301, 302]) {
  return { code: 2000, msg: 'synthetic read-only response', total, page, limit,
    data: ids.map(id => ({ id, warehouse_id: 'TEST-' + id, ring_no: String(id) })) };
}

function setup(t, responses) {
  const calls = [], widgetUpdates = [];
  let clearSortCalls = 0;
  const remaining = [...responses];
  const api = compile(fs.readFileSync(path.resolve(__dirname, '../api.ts'), 'utf8'), name => {
    assert.equal(name, '/@/utils/service');
    return { request: async config => {
      calls.push(plain(config));
      assert.equal(config.method, 'get', 'Search must never write');
      assert.equal(config.url, '/api/shield/warehouse_opening/');
      assert.ok(remaining.length, 'Unexpected extra request');
      return remaining.shift();
    } };
  });
  const formatters = compile(fs.readFileSync(path.resolve(__dirname, '../../crudUtils.ts'), 'utf8'), name => {
    throw new Error('Unexpected formatter import: ' + name);
  });
  const { createCrudOptions } = compile(crudSource, name => {
    if (name === 'vue') return vue;
    if (name === '@fast-crud/fast-crud') return fastCrud;
    if (name === 'vue-router') return { useRouter: () => ({ push() { throw new Error('Search must not navigate'); } }) };
    if (name === './api') return api;
    if (name === '../crudUtils') return formatters;
    if (name.endsWith('.vue')) return { render: () => null };
    throw new Error('Unexpected CRUD import: ' + name);
  });
  let state;
  const app = renderer.createApp({
    setup() {
      const crudRef = vue.ref({
        setSearchFormData: update => widgetUpdates.push(plain(update)),
        tableRef: { tableRef: { clearSort: () => { clearSortCalls++; } } },
      });
      const crudBinding = vue.ref();
      const { crudExpose } = fastCrud.useExpose({ crudRef, crudBinding });
      const { crudOptions } = createCrudOptions({ crudExpose, withdrawingId: vue.ref(null) });
      // The parent fills these form defaults after its initial project/machine GETs.
      // They must remain add-form defaults, never implicit search constraints.
      crudOptions.columns.project.form.value = 1;
      crudOptions.columns.shield_model.form.value = 11;
      const { resetCrudOptions } = fastCrud.useCrud({ crudExpose, crudOptions });
      // FsSearch normally emits its initial validated model when mounted. The
      // widget is omitted here, so deliver that boundary event explicitly.
      crudBinding.value.search['onUpdate:validatedForm']({});
      state = { crudBinding, crudExpose, crudOptions, resetCrudOptions };
      return () => null;
    },
  });
  app.use(elementUi.default || elementUi).use(fastCrud.FastCrud, {
    commonOptions, logger: { off: { tableColumns: false } },
  });
  fastCrud.setLogger({ level: 'error' });
  app.mount({ children: [] });
  t.after(() => app.unmount());
  return { ...state, calls, widgetUpdates, clearSortCalls: () => clearSortCalls };
}

test('merged search controls are usable while persistent add-form defaults do not constrain the initial GET', async t => {
  const s = setup(t, [response(137)]);
  const search = s.crudBinding.value.search.columns;
  const visible = Object.entries(search).filter(([, field]) => field.show === true)
    .sort(([, left], [, right]) => left.order - right.order).map(([key]) => key);
  assert.deepEqual(visible, ['project', 'shield_model', 'ring_no', 'warehouse_id']);
  for (const key of ['project', 'shield_model']) {
    assert.equal(search[key].component.filterable, true);
    assert.equal(search[key].component.clearable, true);
    assert.equal(search[key].value, undefined, 'Add-form values must not become search-field defaults');
  }
  assert.equal(search.warehouse_id.component.disabled, false, 'Search must not inherit the generated-ID form lock');
  assert.equal(s.crudBinding.value.form.columns.warehouse_id.component.disabled, true);
  assert.equal(s.crudBinding.value.form.columns.project.value, 1);
  assert.equal(s.crudBinding.value.form.columns.shield_model.value, 11);
  await s.crudExpose.doRefresh();
  assert.deepEqual(s.calls, [{ url: '/api/shield/warehouse_opening/', method: 'get', params: { page: 1, limit: 20 } }]);
  assert.equal(s.crudBinding.value.pagination.total, 137);
});

test('combined filters use the real API and retain server total through actual pagination callbacks', async t => {
  const s = setup(t, [response(41, 1, 20), response(41, 2, 20, [399]), response(41, 1, 10, [401, 402])]);
  s.crudExpose.doPageTurn(7);
  await s.crudExpose.doSearch({ form: { project: 2, shield_model: 21 }, mergeForm: false });
  assert.deepEqual(s.calls[0].params, { page: 1, limit: 20, project: 2, shield_model: 21 });
  assert.deepEqual(plain(s.crudBinding.value.data).map(row => row.id), [301, 302]);
  assert.equal(s.crudBinding.value.pagination.total, 41, 'The server total is larger than the loaded rows');
  s.crudBinding.value.pagination.onCurrentChange(2);
  await settle();
  assert.deepEqual(s.calls[1].params, { page: 2, limit: 20, project: 2, shield_model: 21 });
  assert.deepEqual(plain(s.crudBinding.value.data).map(row => row.id), [399]);
  s.crudBinding.value.pagination.onSizeChange(10);
  await settle();
  assert.deepEqual(s.calls[2].params, { page: 1, limit: 10, project: 2, shield_model: 21 });
  assert.equal(s.crudBinding.value.pagination.total, 41);
  assert.equal(s.crudBinding.value.pagination.currentPage, 1);
});

test('clearing one selected machine removes it from the next GET without restoring form defaults', async t => {
  const s = setup(t, [response(41), response(72)]);
  await s.crudExpose.doSearch({ form: { project: 2, shield_model: 21 }, mergeForm: false });
  s.crudExpose.doPageTurn(3);
  await s.crudExpose.doSearch({ form: { project: 2, shield_model: undefined }, mergeForm: false });
  assert.deepEqual(s.calls[1].params, { page: 1, limit: 20, project: 2 });
  assert.equal(s.crudBinding.value.pagination.total, 72);
  assert.equal(s.crudBinding.value.form.columns.project.value, 1);
  assert.equal(s.crudBinding.value.form.columns.shield_model.value, 11);
  assert.equal(s.crudExpose.getSearchFormData().shield_model, undefined);
  assert.equal(s.widgetUpdates.at(-1).mergeForm, false);
});

test('real search reset handlers clear combined fields and sorting and fetch page one with the unchanged page size', async t => {
  const s = setup(t, [response(0, 1, 10, []), response(137, 1, 10)]);
  s.crudBinding.value.pagination.pageSize = 10;
  await s.crudExpose.doSearch({ form: { project: 2, shield_model: 21, ring_no: '999', warehouse_id: 'NONE' }, mergeForm: false });
  assert.equal(s.crudBinding.value.pagination.total, 0);
  s.crudExpose.doPageTurn(4);
  s.crudBinding.value.table.sort = { prop: 'open_time', asc: false };
  // These are the actual callbacks bound to FsSearch's validated-form/reset/search events.
  const search = s.crudBinding.value.search;
  search['onUpdate:validatedForm'](plain(search.initialForm || {}));
  search.on_reset();
  search.on_search();
  await settle();
  assert.deepEqual(s.calls[1].params, { page: 1, limit: 10 });
  assert.equal(s.crudBinding.value.pagination.total, 137);
  assert.equal(s.crudBinding.value.pagination.currentPage, 1);
  assert.equal(s.clearSortCalls(), 1);
  assert.deepEqual(plain(s.crudBinding.value.table.sort), {});
});
