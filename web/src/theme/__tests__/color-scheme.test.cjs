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

function loadModule(file, requireMap = {}) {
  const context = { exports: {}, require: name => requireMap[name] ?? require(name) };
  context.module = { exports: context.exports };
  vm.runInNewContext(toCjs(read(file), file), context);
  return context.exports;
}

test('normalizeColorScheme falls back to the warm scheme and applyColorScheme writes data-scheme', () => {
  const { normalizeColorScheme, colorSchemeColors, applyColorScheme } = loadModule('theme/colorSchemes.ts');
  assert.equal(normalizeColorScheme('blue'), 'blue');
  for (const value of ['claude', undefined, null, '', 'dark']) assert.equal(normalizeColorScheme(value), 'claude');
  assert.equal(colorSchemeColors('blue').primary, '#0067c0');
  assert.equal(colorSchemeColors(undefined).primary, '#c6613f');
  const attrs = {};
  const root = { setAttribute: (name, value) => (attrs[name] = value) };
  applyColorScheme('blue', root);
  assert.equal(attrs['data-scheme'], 'blue');
  applyColorScheme(undefined, root);
  assert.equal(attrs['data-scheme'], 'claude');
});

// 运行 setings.vue 的 <script setup>（依赖打桩），返回模板能用到的绑定和打桩出来的 html、本地缓存
function setupSetings(themeConfig) {
  const { descriptor } = parse(read('layout/navBars/breadcrumb/setings.vue'), { filename: 'setings.vue' });
  const script = compileScript(descriptor, { id: 'setings' });
  const style = new Map();
  const documentElement = {
    style: {
      setProperty: (name, value) => style.set(name, value),
      getPropertyValue: name => style.get(name) ?? '',
      get cssText() {
        return [...style].map(([k, v]) => `${k}: ${v};`).join(' ');
      },
    },
    setAttribute() {},
  };
  const local = new Map();
  const Local = { get: key => local.get(key) ?? null, set: (key, val) => local.set(key, JSON.parse(JSON.stringify(val))), remove: key => local.delete(key), clear: () => local.clear() };
  const ElMessage = { warning() {} };
  const colorSchemes = loadModule('theme/colorSchemes.ts');
  const themeUtils = loadModule('utils/theme.ts', { 'element-plus': { ElMessage } });
  const requireMap = {
    vue,
    'element-plus': { ElMessage },
    'vue-i18n': { useI18n: () => ({ locale: vue.ref('zh-cn') }) },
    pinia: { storeToRefs: () => ({ themeConfig: vue.ref(themeConfig) }) },
    '/@/stores/themeConfig': { useThemeConfig: () => ({}) },
    '/@/utils/theme': themeUtils,
    '/@/utils/toolsValidate': { verifyAndSpace: v => v },
    '/@/utils/storage': { Local },
    '/@/utils/wartermark': { default: { set() {}, del() {} } },
    '/@/utils/commonFunction': { default: () => ({ copyText: () => Promise.resolve() }) },
    '/@/utils/other': { default: { isMobile: () => false } },
    '/@/utils/mitt': { default: { on() {}, off() {}, emit() {} } },
    '/@/theme/colorSchemes': colorSchemes,
  };
  const context = { exports: {}, require: name => { if (!(name in requireMap)) throw new Error(`unexpected import ${name}`); return requireMap[name]; }, document: { documentElement, querySelector: () => null }, setTimeout: () => 0, console };
  context.module = { exports: context.exports };
  vm.runInNewContext(toCjs(script.content, 'setings.ts'), context);
  const component = context.exports.default;
  let bindings;
  // setup 外没有组件实例：onMounted 之类只会警告，这里关掉警告
  const warn = console.warn;
  console.warn = () => {};
  try {
    bindings = component.setup({}, { expose() {}, emit() {}, attrs: {}, slots: {} });
  } finally {
    console.warn = warn;
  }
  return { bindings, style, local };
}

test('switching the scheme in the settings drawer rewrites the inline primary and menu colours and saves them', () => {
  const store = loadModule('stores/themeConfig.ts', {
    pinia: { defineStore: (id, options) => options },
    '/@/theme/colorSchemes': loadModule('theme/colorSchemes.ts'),
  });
  const themeConfig = store.useThemeConfig.state().themeConfig;
  assert.equal(themeConfig.colorScheme, 'claude');
  const { bindings, style, local } = setupSetings(themeConfig);
  // 抽屉最上面的"主题配色"列出两张色卡
  assert.deepEqual(Array.from(bindings.COLOR_SCHEMES, s => s.label), ['暖白', '灰白蓝']);
  assert.equal(bindings.currentColorScheme.value, 'claude');

  bindings.onColorSchemeChange('blue');
  assert.equal(themeConfig.colorScheme, 'blue');
  assert.equal(bindings.currentColorScheme.value, 'blue');
  // 主题色和它的深浅色重新写进 html 内联变量（内联变量盖过样式表，只换 data-scheme 不够）
  assert.equal(themeConfig.primary, '#0067c0');
  assert.equal(style.get('--el-color-primary'), '#0067c0');
  assert.equal(style.get('--el-color-primary-light-9'), '#e5eff8');
  assert.equal(style.get('--el-color-primary-dark-2'), '#005cac');
  // 顶栏、菜单的内联变量也换成灰白蓝
  const expected = { topBar: '#ffffff', topBarColor: '#5d5d5d', menuBar: '#ffffff', menuBarColor: '#1b1b1b', menuBarActiveColor: '#ebebeb', columnsMenuBar: '#ffffff', columnsMenuBarColor: '#1b1b1b' };
  for (const [key, value] of Object.entries(expected)) {
    assert.equal(themeConfig[key], value, key);
    assert.equal(style.get(`--next-bg-${key}`), value, key);
  }
  // 配置和内联样式都存下，刷新后 App.vue 读回（配色本身由 App.vue 按 colorScheme 写 data-scheme）
  assert.equal(local.get('themeConfig').colorScheme, 'blue');
  assert.equal(local.get('themeConfig').primary, '#0067c0');
  assert.match(local.get('themeConfigStyle'), /--el-color-primary: #0067c0;/);
  assert.match(local.get('themeConfigStyle'), /--next-bg-menuBarActiveColor: #ebebeb;/);

  // 切回暖白
  bindings.onColorSchemeChange('claude');
  assert.equal(themeConfig.colorScheme, 'claude');
  assert.equal(style.get('--el-color-primary'), '#c6613f');
  assert.equal(style.get('--next-bg-menuBar'), '#f9f8f3');
  assert.match(local.get('themeConfigStyle'), /--el-color-primary: #c6613f;/);
});

test('a cached config without colorScheme reads as the warm scheme', () => {
  const themeConfig = { ...loadModule('stores/themeConfig.ts', { pinia: { defineStore: (id, options) => options }, '/@/theme/colorSchemes': loadModule('theme/colorSchemes.ts') }).useThemeConfig.state().themeConfig };
  delete themeConfig.colorScheme;
  const { bindings, style } = setupSetings(themeConfig);
  assert.equal(bindings.currentColorScheme.value, 'claude');
  // 已经是暖白：点暖白什么也不做
  bindings.onColorSchemeChange('claude');
  assert.equal(style.size, 0);
});

test('the settings drawer opens with the scheme section and App.vue keeps data-scheme in step', () => {
  const setings = read('layout/navBars/breadcrumb/setings.vue');
  const template = setings.slice(0, setings.indexOf('</template>\n\n<script'));
  const scheme = template.indexOf('<el-divider content-position="left">主题配色</el-divider>');
  assert.ok(scheme > 0);
  assert.ok(scheme < template.indexOf("$t('message.layout.oneTitle')"));
  assert.match(template, /v-for="scheme in COLOR_SCHEMES"/);
  assert.match(template, /@click="onColorSchemeChange\(scheme\.value\)"/);
  const app = read('App.vue');
  // 首次渲染前就按缓存设好 data-scheme（store 要到挂载后才读缓存），之后跟着 colorScheme 走
  const reset = app.indexOf('resetStaleThemeCache(Local);');
  const apply = app.indexOf("applyColorScheme(Local.get('themeConfig')?.colorScheme);");
  assert.ok(reset > 0 && apply > reset);
  assert.ok(apply < app.indexOf('onMounted('));
  assert.match(app, /watch\(\s*\(\) => themeConfig\.value\.colorScheme,\s*\(scheme\) => applyColorScheme\(scheme\)\s*\);/);
});
