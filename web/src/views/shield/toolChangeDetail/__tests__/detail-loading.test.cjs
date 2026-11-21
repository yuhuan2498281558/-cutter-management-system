// Actual detail SFC setup with synthetic GET responses; no business writes.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const { parse, compileScript } = require('@vue/compiler-sfc');
const ts = require('typescript');
const vue = require('vue');
const source = process.env.DETAIL_LOAD_TEST_REF
  ? execFileSync('git', ['show', `${process.env.DETAIL_LOAD_TEST_REF}:web/src/views/shield/toolChangeDetail/index.vue`], { encoding: 'utf8' })
  : fs.readFileSync(path.resolve(__dirname, '../index.vue'), 'utf8');
function compile(content, requireModule = require) {
  const context = { exports: {}, require: requireModule, console: { error() {} } };
  vm.runInNewContext(ts.transpileModule(content, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, context);
  return context.exports;
}
const helpers = compile(fs.readFileSync(path.resolve(__dirname, '../tablePresentation.ts'), 'utf8'));
const presentation = compile(fs.readFileSync(path.resolve(__dirname, '../detailPresentation.ts'), 'utf8'));
const script = compileScript(parse(source).descriptor, { id: 'detail-load-test' });
function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
const fixture = config => {
  if (config.url.includes('warehouse_opening')) return { data: { shield_model: 9, supplement_ready: true, warehouse_id: 'TEST', ring_no: '100' } };
  if (config.url.includes('cutter_position_info')) return { data: [{ id: 1, cutter_position_no: '1', tool_type: 'DISC' }] };
  return { data: [{ id: 11, cutter_position_no: '1', tool_number: 'TEST-1', is_checked: true, is_replaced: true }] };
};
function setup(t, respond = async config => fixture(config)) {
  const hooks = {}, calls = [], notices = [], opened = [];
  const route = vue.reactive({ path: '/shield/toolChangeDetail', query: { warehouse_id: '1', mode: 'supplement' } });
  const component = compile(script.content, name => {
    if (name === 'vue') return { ...vue, ...Object.fromEntries(['onMounted', 'onActivated', 'onDeactivated', 'onUnmounted'].map(key => [key, fn => { hooks[key] = fn; }])) };
    if (name === 'vue-router') return { useRoute: () => route, useRouter: () => ({ back() {}, replace: async target => { route.query = target.query; } }) };
    if (name === './tablePresentation') return helpers;
    if (name === './detailPresentation') return presentation;
    if (name === '/@/utils/service') return { request: async config => { assert.equal(config.method, 'get'); calls.push(config); return respond(config); } };
    if (name === 'element-plus') return { ElMessage: Object.fromEntries(['success', 'warning', 'error'].map(key => [key, message => notices.push([key, message])])) };
    if (name.endsWith('.vue')) return {};
    throw new Error(`Unexpected import: ${name}`);
  }).default;
  const scope = vue.effectScope();
  const state = scope.run(() => component.setup({}, { expose() {} }));
  state.repairDialogRef.value = { open: (...args) => opened.push(args) };
  t.after(() => { hooks.onUnmounted?.(); scope.stop(); });
  return { state, hooks, route, calls, notices, opened };
}

test('read failure exposes a persistent retry state and retry recovers', async t => {
  let fail = true;
  const { state: s } = setup(t, async config => { if (fail) throw new Error('offline'); return fixture(config); });
  await s.getWarehouseInfo();
  assert.match(s.loadError?.value || '', /重新加载/);
  assert.equal(s.loading?.value, false);
  assert.equal(s.dataLoaded.value, false);
  fail = false;
  await s.getWarehouseInfo();
  assert.equal(s.loadError.value, '');
  assert.equal(s.dataLoaded.value, true);
  assert.equal(s.tableData.value[0].tool_number, 'TEST-1');
});

test('detail refresh failure clears stale rows and blocks repair/export-ready state', async t => {
  let fail = false;
  const { state: s, opened } = setup(t, async config => { if (fail && config.url.includes('tool_change_detail')) throw new Error('offline'); return fixture(config); });
  await s.getWarehouseInfo();
  const oldRow = s.tableData.value[0];
  fail = true;
  await s.loadData();
  s.openOldToolRepair(oldRow);
  assert.equal(s.tableData.value.length, 0);
  assert.equal(s.dataLoaded.value, false);
  assert.equal(s.isEditable.value, false);
  assert.equal(opened.length, 0);
});

test('pending refresh immediately hides old detail data and blocks repair', async t => {
  const wait = deferred(); let pending = false;
  const { state: s, opened } = setup(t, config => pending ? wait.promise : fixture(config));
  await s.getWarehouseInfo(); const oldRow = s.tableData.value[0];
  pending = true;
  const loading = s.loadData();
  s.openOldToolRepair(oldRow);
  assert.equal(s.loading?.value, true);
  assert.equal(s.dataLoaded.value, false);
  assert.equal(opened.length, 0);
  wait.reject(new Error('finish')); await loading;
});

for (const lifecycle of ['onDeactivated', 'onUnmounted']) {
  for (const fails of [false, true]) {
    test(`${lifecycle} isolates late opening ${fails ? 'failure' : 'success'}`, async t => {
      const wait = deferred();
      const { state: s, hooks, calls, notices } = setup(t, () => wait.promise);
      const pending = s.getWarehouseInfo();
      hooks[lifecycle]?.();
      fails ? wait.reject(new Error('late')) : wait.resolve(fixture({ url: 'warehouse_opening' }));
      await pending;
      assert.equal(calls.length, 1);
      assert.equal(notices.length, 0);
      assert.equal(s.warehouseInfo.value, null);
      assert.equal(s.dataLoaded.value, false);
    });
  }
}

test('an older refresh cannot overwrite or finish a newer pending refresh', async t => {
  const old = deferred(), fresh = deferred(); let count = 0;
  const { state: s } = setup(t, config => {
    if (config.url.includes('warehouse_opening')) return (++count === 1 ? old : fresh).promise;
    return fixture(config);
  });
  const first = s.getWarehouseInfo();
  const second = s.getWarehouseInfo();
  old.resolve({ data: { shield_model: 3, supplement_ready: true, warehouse_id: 'OLD' } });
  await first;
  assert.equal(s.loading?.value, true);
  assert.equal(s.warehouseInfo.value, null);
  fresh.resolve(fixture({ url: 'warehouse_opening' })); await second;
  assert.equal(s.warehouseInfo.value.warehouse_id, 'TEST');
});

test('late details cannot repopulate a deactivated page', async t => {
  const wait = deferred();
  const { state: s, hooks, notices } = setup(t, config => config.url.includes('tool_change_detail') ? wait.promise : fixture(config));
  const pending = s.getWarehouseInfo(); await new Promise(setImmediate);
  hooks.onDeactivated?.();
  wait.resolve(fixture({ url: 'tool_change_detail' })); await pending;
  assert.equal(s.tableData.value.length, 0);
  assert.equal(s.dataLoaded.value, false);
  assert.equal(notices.length, 0);
});

test('route change before deactivation cannot downgrade the new route or continue old reads', async t => {
  const wait = deferred();
  const { state: s, route, calls, notices } = setup(t, () => wait.promise);
  const pending = s.getWarehouseInfo();
  route.query.warehouse_id = '2';
  wait.resolve({ data: { shield_model: 9, supplement_ready: false } });
  await pending;
  assert.equal(route.query.mode, 'supplement');
  assert.equal(calls.length, 1);
  assert.equal(notices.length, 0);
  assert.equal(s.warehouseInfo.value, null);
});

const openingByUrl = config => {
  const response = fixture(config);
  if (config.url.includes('warehouse_opening')) response.data.ring_no = config.url.includes('/2/') ? '200' : '100';
  return response;
};

// Mounts the page like layout/routerView/parent.vue: KeepAlive keyed by decodeURI(route.fullPath),
// so each detail URL gets its own cached instance. Real vue-router, in-memory renderer, mocked GETs.
async function mountWithLayoutKey(t, respond = async config => openingByUrl(config)) {
  const VueRouter = require('vue-router');
  const calls = [], instances = [];
  const component = compile(script.content, name => {
    if (name === 'vue' || name === 'vue-router') return require(name);
    if (name === './tablePresentation') return helpers;
    if (name === './detailPresentation') return presentation;
    if (name === '/@/utils/service') return { request: async config => { calls.push(config.url); return respond(config); } };
    if (name === 'element-plus') return { ElMessage: { success() {}, warning() {}, error() {} } };
    if (name.endsWith('.vue')) return {};
    throw new Error(`Unexpected import: ${name}`);
  }).default;
  const Detail = {
    name: 'ToolChangeDetail',
    setup(props, ctx) { const state = component.setup(props, ctx); instances.push(state); return state; },
    render: () => vue.h('div'),
  };
  const Layout = {
    setup() {
      const route = VueRouter.useRoute();
      const key = vue.ref('');
      vue.watch(() => route.fullPath, () => { key.value = decodeURI(route.fullPath); }, { immediate: true });
      return () => vue.h(VueRouter.RouterView, null, {
        default: ({ Component }) => vue.h(vue.KeepAlive, null, { default: () => (Component ? vue.h(Component, { key: key.value }) : null) }),
      });
    },
  };
  const remove = node => { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1); node.parent = null; };
  const element = type => ({ type, children: [], parent: null, text: '' });
  const { createApp } = vue.createRenderer({
    createElement: element, createText: text => ({ ...element('#text'), text }), createComment: text => ({ ...element('#comment'), text }),
    setText(node, text) { node.text = text; }, setElementText(node, text) { node.text = text; node.children = []; },
    insert(node, parent, anchor) {
      remove(node);
      const index = anchor ? parent.children.indexOf(anchor) : -1;
      if (index < 0) parent.children.push(node); else parent.children.splice(index, 0, node);
      node.parent = parent;
    },
    remove, parentNode: node => node.parent,
    nextSibling: node => (node.parent ? node.parent.children[node.parent.children.indexOf(node) + 1] || null : null),
    patchProp() {},
  });
  const router = VueRouter.createRouter({ history: VueRouter.createMemoryHistory(), routes: [{ path: '/shield/toolChangeDetail', component: Detail }] });
  const app = createApp(Layout);
  app.use(router);
  await router.push('/shield/toolChangeDetail?warehouse_id=1&mode=supplement');
  await router.isReady();
  app.mount(element('root'));
  t.after(() => app.unmount());
  const openings = () => calls.filter(url => url.includes('warehouse_opening')).map(url => url.match(/\/(\d+)\/$/)[1]);
  return { router, calls, instances, openings };
}

test('with the layout fullPath key, switching detail tabs requests the new opening only once', async t => {
  const { router, calls, instances, openings } = await mountWithLayoutKey(t);
  await new Promise(setImmediate);
  assert.equal(calls.length, 3);
  await router.push('/shield/toolChangeDetail?warehouse_id=2&mode=view');
  await new Promise(setImmediate);
  assert.equal(instances.length, 2);
  assert.deepEqual(openings(), ['1', '2']);
  assert.equal(calls.length, 6);
  const [first, second] = instances;
  assert.equal(first.pageActive.value, false);
  assert.equal(second.warehouseInfo.value.ring_no, '200');
  assert.equal(second.isEditable.value, false);
  await router.push('/shield/toolChangeDetail?warehouse_id=1&mode=supplement');
  await new Promise(setImmediate);
  assert.equal(instances.length, 2);
  assert.deepEqual(openings(), ['1', '2', '1']);
  assert.equal(first.warehouseInfo.value.ring_no, '100');
  assert.equal(first.isEditable.value, true);
  assert.equal(second.pageActive.value, false);
});

test('with the layout fullPath key, switching tabs during loading never leaves a tab stuck loading', async t => {
  const slow = deferred(); let count = 0;
  const { router, instances, openings } = await mountWithLayoutKey(t, config => (
    config.url.includes('warehouse_opening') && ++count === 1 ? slow.promise : openingByUrl(config)
  ));
  const [first] = instances;
  assert.equal(first.loading.value, true);
  await router.push('/shield/toolChangeDetail?warehouse_id=2&mode=view');
  await new Promise(setImmediate);
  const second = instances[1];
  assert.equal(second.loading.value, false);
  assert.equal(second.warehouseInfo.value.ring_no, '200');
  await router.push('/shield/toolChangeDetail?warehouse_id=1&mode=supplement');
  await new Promise(setImmediate);
  slow.resolve(openingByUrl({ url: '/api/shield/warehouse_opening/1/' }));
  await new Promise(setImmediate);
  assert.deepEqual(openings(), ['1', '2', '1']);
  assert.equal(first.loading.value, false);
  assert.equal(first.dataLoaded.value, true);
  assert.equal(first.warehouseInfo.value.ring_no, '100');
});

test('activation refreshes cached readiness but initial activation does not double-load', async t => {
  const { state: s, hooks, calls } = setup(t);
  hooks.onActivated?.();
  assert.equal(calls.length, 0);
  await s.getWarehouseInfo();
  hooks.onDeactivated?.(); hooks.onActivated?.();
  await new Promise(setImmediate);
  assert.equal(calls.length, 6);
  assert.equal(s.dataLoaded.value, true);
});

test('template binds retry, loading and repaired-record refresh without changing export columns', () => {
  assert.match(source, /v-if="loading" role="status"/);
  assert.match(source, /@click="getWarehouseInfo" :disabled="loading"/);
  assert.match(source, /<OldToolRepairDialog v-if="pageActive"[^>]*@saved="getWarehouseInfo"/);
  assert.match(source, /<ExportDropdown[^>]*:rows="tableData"/);
});
