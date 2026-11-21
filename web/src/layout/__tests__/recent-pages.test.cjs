// 侧栏"最近打开"的行为测试：在 vm 里跑 tagsView.vue 的 <script setup>（路由、会话缓存、keep-alive 打桩），模拟打开页面
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { parse, compileScript } = require('@vue/compiler-sfc');
const vue = require('vue');

const srcDir = path.resolve(__dirname, '..', '..');
const read = file => fs.readFileSync(path.resolve(srcDir, file), 'utf8');
const toCjs = (code, file) => ts.transpileModule(code, { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const clone = value => JSON.parse(JSON.stringify(value));

function loadModule(file, requireMap = {}) {
  const context = { exports: {}, require: name => requireMap[name] ?? require(name) };
  context.module = { exports: context.exports };
  vm.runInNewContext(toCjs(read(file), file), context);
  return context.exports;
}

const meta = (extra = {}) => ({ title: 't', isLink: '', isHide: false, isKeepAlive: true, isAffix: false, isIframe: false, ...extra });
const makeRoutes = () => [
  { path: '/home', name: 'home', meta: meta({ isAffix: true }) },
  ...['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map(n => ({ path: `/${n}`, name: n, meta: meta() })),
  { path: '/detail', name: 'detail', meta: meta({ isHide: true }) },
];

// 挂载一个 tagsView：layout 是当前布局，oldLayout 是用户自己选的布局（窄屏时两者不同），session 是会话缓存，current 是当前路由
function mountTagsView({ layout = 'defaults', oldLayout = layout, session = {}, current = '/home' } = {}) {
  const routes = makeRoutes();
  const sessionMap = new Map(Object.entries(clone(session)));
  const Session = { get: k => (sessionMap.has(k) ? clone(sessionMap.get(k)) : null), set: (k, v) => sessionMap.set(k, clone(v)), remove: k => sessionMap.delete(k) };
  const Local = { get: k => (k === 'oldLayout' ? oldLayout : null), set() {}, remove() {} };
  const themeConfig = vue.ref({ isShareTagsView: false, isCacheTagsView: true, layout, isSortableTagsView: false, tagsStyle: 'tags-style-five', isTagsview: true });
  const pinia = { state: vue.ref({ tagsViewRoutes: { tagsViewRoutes: routes } }) };
  const cached = [];
  const keepAlive = {
    addCachedView: async v => { if (v.meta.isKeepAlive && !cached.includes(v.name)) cached.push(v.name); },
    delCachedView: async v => { const i = cached.indexOf(v.name); if (i > -1) cached.splice(i, 1); },
    delOthersCachedViews: async () => {},
    delAllCachedViews: async () => { cached.length = 0; },
  };
  const toRoute = (target) => {
    const record = routes.find(r => r.path === target.path);
    const query = target.query || {};
    const search = Object.keys(query).length ? `?${new URLSearchParams(query)}` : '';
    return { path: record.path, fullPath: record.path + search, query: { ...query }, params: {}, meta: record.meta, name: record.name };
  };
  const route = vue.reactive(toRoute({ path: current }));
  let beforeRouteUpdate = null;
  const pushes = [];
  const router = {
    push: async to => {
      const target = typeof to === 'string' ? { path: to } : to;
      pushes.push(clone({ path: target.path, query: target.query }));
      const next = toRoute(target);
      if (beforeRouteUpdate) await beforeRouteUpdate(next);
      Object.assign(route, next);
    },
  };
  const mounted = [];
  const openedPagesModule = loadModule('layout/navBars/tagsView/openedPages.ts', { vue });
  const requireMap = {
    vue: { ...vue, onMounted: fn => mounted.push(fn), onBeforeMount() {}, onUnmounted() {}, onBeforeUpdate() {} },
    'vue-router': { useRoute: () => route, useRouter: () => router, onBeforeRouteUpdate: fn => (beforeRouteUpdate = fn) },
    sortablejs: { default: { create: () => ({ el: null, destroy() {}, toArray: () => [] }) } },
    'element-plus': { ElMessage() {} },
    pinia: { storeToRefs: () => ({ themeConfig, tagsViewRoutes: vue.ref(routes) }) },
    '/@/stores/index': { default: pinia },
    '/@/stores/tagsViewRoutes': { useTagsViewRoutes: () => ({ setCurrenFullscreen() {} }) },
    '/@/stores/themeConfig': { useThemeConfig: () => ({}) },
    '/@/stores/keepAliveNames': { useKeepALiveNames: () => keepAlive },
    '/@/utils/storage': { Session, Local },
    '/@/utils/arrayOperation': loadModule('utils/arrayOperation.ts'),
    '/@/utils/other': { default: { setTagsViewNameI18n: v => v.path, isMobile: () => false } },
    '/@/utils/mitt': { default: { on() {}, off() {}, emit() {} } },
    '/@/layout/navBars/tagsView/openedPages': openedPagesModule,
  };
  const { descriptor } = parse(read('layout/navBars/tagsView/tagsView.vue'), { filename: 'tagsView.vue' });
  const context = {
    exports: {},
    require: name => { if (!(name in requireMap)) throw new Error(`unexpected import ${name}`); return requireMap[name]; },
    document: { querySelector: () => null },
    window: { addEventListener() {}, removeEventListener() {} },
    setTimeout, console, Date,
  };
  context.module = { exports: context.exports };
  vm.runInNewContext(toCjs(compileScript(descriptor, { id: 'tags' }).content, 'tagsView.ts'), context);
  // setup 外没有组件实例，生命周期钩子已打桩；关掉 Vue 的其余警告
  const warn = console.warn;
  console.warn = () => {};
  let bindings;
  try {
    bindings = context.exports.default.setup({}, { expose() {}, emit() {}, attrs: {}, slots: {} });
  } finally {
    console.warn = warn;
  }
  const env = { bindings, router, route, pushes, cached, Session, openedPages: openedPagesModule.openedPages, recentOpenedPages: openedPagesModule.recentOpenedPages };
  env.mount = async () => { mounted.forEach(fn => fn()); await settle(); };
  env.open = async to => { await router.push(to); await settle(); };
  // 列表属于 vm 里的另一个 realm，先转成本地数组再比较
  env.tags = () => Array.from(env.bindings.state.tagsViewList, v => v.url);
  env.recent = () => Array.from(env.recentOpenedPages(env.openedPages.list), p => p.route.url);
  return env;
}
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise(resolve => setTimeout(resolve, 2)); };

test('in the sidebar layout, opening a sixth page closes the least recently visited one and frees its cache', async () => {
  const env = mountTagsView();
  await env.mount();
  for (const p of ['/a', '/b', '/c', '/d', '/e']) await env.open(p);
  assert.deepEqual(env.tags(), ['/home', '/a', '/b', '/c', '/d', '/e']);
  // 回到 /a，再开 /f：最久没访问的是 /b，不是最早打开的 /a
  await env.open('/a');
  await env.open('/f');
  assert.deepEqual(env.tags(), ['/home', '/a', '/c', '/d', '/e', '/f']);
  assert.deepEqual(env.recent(), ['/f', '/a', '/e', '/d', '/c']);
  assert.equal(env.cached.includes('b'), false);
  for (const p of ['/g', '/h']) await env.open(p);
  assert.deepEqual(env.recent(), ['/h', '/g', '/f', '/a', '/e']);
  assert.deepEqual(env.tags(), ['/home', '/a', '/e', '/f', '/g', '/h']);
  // 当前页一直在列表第一个，关页面不会额外跳转
  assert.equal(env.route.path, '/h');
  assert.deepEqual(env.pushes.map(p => p.path), ['/a', '/b', '/c', '/d', '/e', '/a', '/f', '/g', '/h']);
});

test('pages of the same route with different queries are trimmed oldest first and the current one stays', async () => {
  const env = mountTagsView();
  await env.mount();
  for (let id = 1; id <= 7; id++) await env.open({ path: '/detail', query: { id: String(id) } });
  assert.deepEqual(env.recent(), ['/detail-7', '/detail-6', '/detail-5', '/detail-4', '/detail-3']);
  assert.equal(env.tags().length, 1 + 5);
  assert.equal(env.route.fullPath, '/detail?id=7');
});

test('a layout that only turns into the sidebar layout on a narrow window keeps all its tags', async () => {
  // 经典布局下开了 8 个标签；窗口拖窄后 layout 临时是 defaults，用户选的 oldLayout 还是 classic
  const tagsViewList = makeRoutes().slice(0, 9).map(r => ({ ...r, url: r.path, query: {} }));
  const narrow = mountTagsView({ layout: 'defaults', oldLayout: 'classic', session: { tagsViewList }, current: '/b' });
  await narrow.mount();
  assert.equal(narrow.tags().length, 9);
  assert.equal(narrow.recent().length, 5);
  // 用户自己选的就是侧边栏布局：照常只留最近 5 个，当前页 /b 不关
  const sidebar = mountTagsView({ layout: 'defaults', oldLayout: 'defaults', session: { tagsViewList }, current: '/b' });
  await sidebar.mount();
  assert.equal(sidebar.tags().length, 1 + 5);
  assert.ok(sidebar.tags().includes('/b'));
  assert.equal(sidebar.recent()[0], '/b');
});

test('visit times survive a reload and a page opened from the address bar joins the list as the current page', async () => {
  const first = mountTagsView();
  await first.mount();
  for (const p of ['/a', '/b', '/c', '/d', '/e']) await first.open(p);
  await first.open('/b');
  const session = { tagsViewList: first.Session.get('tagsViewList'), tagsViewLastVisits: first.Session.get('tagsViewLastVisits') };
  // 刷新：标签和访问记录从会话缓存恢复，顺序不乱
  const reloaded = mountTagsView({ session, current: '/b' });
  await reloaded.mount();
  assert.deepEqual(reloaded.recent(), ['/b', '/e', '/d', '/c', '/a']);
  // 地址栏直接打开不在列表里的 /g：加进列表、排第一，挤掉最久没访问的 /a
  const typed = mountTagsView({ session, current: '/g' });
  await typed.mount();
  assert.deepEqual(typed.recent(), ['/g', '/b', '/e', '/d', '/c']);
  assert.equal(typed.tags().includes('/a'), false);
});
