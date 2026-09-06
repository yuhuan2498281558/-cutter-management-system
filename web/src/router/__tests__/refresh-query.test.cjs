// Run from web: node --test src/router/__tests__/refresh-query.test.cjs
// Execute the real route guard with Vue Router; mock menu/auth boundaries only.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const vueRouter = require('vue-router');

function setup(t, { authenticated = true, backend = true, initialized = false, initFails = false } = {}) {
  const routesStore = vue.reactive({ routesList: initialized ? [{}] : [] });
  const themeStore = vue.reactive({ themeConfig: { isRequestRoutes: backend } });
  let initializationCount = 0;
  const context = { exports: {}, window: { location: { pathname: '/', hash: '#/' } }, console: { log() {}, warn() {}, error() {} } };
  const initialize = async () => {
    initializationCount++;
    if (initFails) return false;
    context.exports.router.addRoute({ path: '/shield/toolChangeDetail', name: 'detail', component: {} });
    context.exports.router.addRoute({ path: '/shield/warehouseOpening', name: 'opening', component: {} });
    routesStore.routesList = [{}];
    return true;
  };
  const staticRoutes = [
    { path: '/login', name: 'login', component: {} },
    { path: '/mobile/login', name: 'mobileLogin', component: {} },
    { path: '/mobile/tasks/:id', name: 'mobileDetail', component: {} },
  ];
  context.require = name => {
    if (name === 'vue-router') return { ...vueRouter, createWebHashHistory: vueRouter.createMemoryHistory };
    if (name === 'vue') return vue;
    if (name === 'pinia') return { storeToRefs: vue.toRefs };
    if (name === 'nprogress') return { configure() {}, start() {}, done() {} };
    if (name.endsWith('.css')) return {};
    if (name === '/@/stores/index') return {};
    if (name === '/@/stores/routesList') return { useRoutesList: () => routesStore };
    if (name === '/@/stores/themeConfig') return { useThemeConfig: () => themeStore };
    if (name === '/@/stores/keepAliveNames') return { useKeepALiveNames: () => ({ setCacheKeepAlive() {} }) };
    if (name === '/@/utils/storage') return { Session: { get: () => authenticated ? 'test-session' : null, clear() {} } };
    if (name === '/@/router/backEnd') return { initBackEndControlRoutes: initialize };
    if (name === '/@/router/frontEnd') return { initFrontEndControlRoutes: initialize };
    if (name === '/@/router/route') return {
      staticRoutes, dynamicRoutes: [], notFoundAndNoPower: [{ path: '/:path(.*)*', name: 'notFound', component: {} }],
    };
    throw new Error(`Unexpected import: ${name}`);
  };
  const source = fs.readFileSync(path.resolve(__dirname, '../index.ts'), 'utf8').replaceAll('import.meta.env.DEV', 'false');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText;
  vm.runInNewContext(compiled, context);
  const router = context.exports.router;
  t.after(() => router.options.history.destroy());
  return { router, initializationCount: () => initializationCount };
}

for (const mode of ['view', 'supplement']) {
  test(`cold refresh preserves warehouse id/code and ${mode} mode after dynamic route registration`, async t => {
    const { router, initializationCount } = setup(t);
    const target = '/shield/toolChangeDetail?warehouse_id=235&warehouse_code=TEST-15&mode=' + mode;
    await router.push(target);
    assert.equal(router.currentRoute.value.name, 'detail');
    assert.deepEqual(router.currentRoute.value.query, { warehouse_id: '235', warehouse_code: 'TEST-15', mode });
    assert.equal(router.currentRoute.value.fullPath, target);
    assert.equal(initializationCount(), 1);
  });
}
test('cold refresh preserves encoded query, repeated values, empty values and hash', async t => {
  const { router } = setup(t);
  const target = '/shield/toolChangeDetail?warehouse_id=235&note=' + encodeURIComponent('测试 A&B#1') + '&tag=a&tag=b&empty=#photos';
  await router.push(target);
  assert.equal(router.currentRoute.value.query.note, '测试 A&B#1');
  assert.deepEqual(router.currentRoute.value.query.tag, ['a', 'b']);
  assert.equal(router.currentRoute.value.query.empty, '');
  assert.equal(router.currentRoute.value.hash, '#photos');
});
test('frontend-controlled dynamic routes also preserve query', async t => {
  const { router } = setup(t, { backend: false });
  await router.push('/shield/toolChangeDetail?warehouse_id=236&mode=view');
  assert.equal(router.currentRoute.value.name, 'detail');
  assert.equal(router.currentRoute.value.query.warehouse_id, '236');
});
test('adjacent opening-list route refresh and subsequent warm navigation work', async t => {
  const { router, initializationCount } = setup(t);
  await router.push('/shield/warehouseOpening');
  assert.equal(router.currentRoute.value.name, 'opening');
  await router.push({ path: '/shield/toolChangeDetail', query: { warehouse_id: '237', mode: 'view' } });
  assert.equal(router.currentRoute.value.query.warehouse_id, '237');
  assert.equal(initializationCount(), 1);
});
test('missing id is not replaced with a cached or guessed warehouse', async t => {
  const { router } = setup(t);
  await router.push('/shield/toolChangeDetail');
  assert.deepEqual(router.currentRoute.value.query, {});
});
test('unauthenticated detail routes still go to login without loading menus', async t => {
  const { router, initializationCount } = setup(t, { authenticated: false });
  await router.push('/shield/toolChangeDetail?warehouse_id=235&mode=view');
  assert.equal(router.currentRoute.value.name, 'login');
  assert.equal(initializationCount(), 0);
});
test('menu initialization failure still redirects to login', async t => {
  const { router } = setup(t, { initFails: true });
  await router.push('/shield/toolChangeDetail?warehouse_id=235&mode=view');
  assert.equal(router.currentRoute.value.name, 'login');
});
test('mobile auth guard still preserves the complete requested route', async t => {
  const { router, initializationCount } = setup(t, { authenticated: false });
  await router.push('/mobile/tasks/12?filter=pending');
  assert.equal(router.currentRoute.value.name, 'mobileLogin');
  assert.equal(router.currentRoute.value.query.redirect, '/mobile/tasks/12?filter=pending');
  assert.equal(initializationCount(), 0);
});
