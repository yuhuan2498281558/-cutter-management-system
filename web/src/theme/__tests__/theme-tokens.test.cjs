const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const sass = require('sass');

const themeDir = path.resolve(__dirname, '..');
const srcDir = path.resolve(themeDir, '..');
const read = file => fs.readFileSync(path.resolve(srcDir, file), 'utf8');

function loadThemeVersion() {
  const context = { exports: {} };
  vm.runInNewContext(ts.transpileModule(read('theme/themeVersion.ts'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, context);
  return context.exports;
}
function memoryStorage(initial) {
  const data = new Map(Object.entries(initial));
  return { data, get: key => (data.has(key) ? data.get(key) : null), set: (key, val) => data.set(key, val), remove: key => data.delete(key) };
}

test('stale or missing theme version clears both theme caches and records the current version', () => {
  const { THEME_VERSION, resetStaleThemeCache } = loadThemeVersion();
  assert.equal(THEME_VERSION, 'a-2026-10');
  for (const version of ['old-version', undefined]) {
    const initial = { themeConfig: { primary: '#409eff' }, themeConfigStyle: '--el-color-primary: #409eff;', token: 'kept' };
    if (version) initial.themeVersion = version;
    const storage = memoryStorage(initial);
    assert.equal(resetStaleThemeCache(storage), true);
    assert.equal(storage.data.has('themeConfig'), false);
    assert.equal(storage.data.has('themeConfigStyle'), false);
    assert.equal(storage.get('themeVersion'), 'a-2026-10');
    assert.equal(storage.get('token'), 'kept');
  }
});

test('current theme version keeps the cached layout config', () => {
  const { resetStaleThemeCache } = loadThemeVersion();
  const storage = memoryStorage({ themeVersion: 'a-2026-10', themeConfig: { layout: 'defaults' }, themeConfigStyle: '--x: 1;' });
  assert.equal(resetStaleThemeCache(storage), false);
  assert.deepEqual(storage.get('themeConfig'), { layout: 'defaults' });
  assert.equal(storage.get('themeConfigStyle'), '--x: 1;');
});

test('App.vue checks the theme version before reading the cached layout config', () => {
  const app = read('App.vue');
  const reset = app.indexOf('resetStaleThemeCache(Local)');
  assert.ok(reset > 0);
  assert.ok(reset < app.indexOf("if (Local.get('themeConfig'))"));
});

test('tokens.scss defines every design variable with the agreed value', () => {
  const expected = {
    '--dv-bg': '#f4f3ee', '--dv-surface': '#ffffff', '--dv-surface-muted': '#efede6', '--dv-selected': '#e2dfd5',
    '--dv-hover': 'rgba(31, 30, 29, 0.04)',
    '--dv-text': '#1f1e1d', '--dv-text-secondary': '#6b6962', '--dv-text-muted': '#9a978e', '--dv-text-nav': '#3d3b36',
    '--dv-border': '#e5e2d9', '--dv-border-strong': '#d6d2c6',
    '--dv-primary': '#1f1e1d', '--dv-primary-hover': '#3a3936', '--dv-on-primary': '#faf9f5', '--dv-ai': '#c96442',
    '--dv-success': '#4a7c59', '--dv-success-bg': '#e6efe3', '--dv-success-text': '#3b6e46',
    '--dv-warning': '#b7832f', '--dv-warning-bg': '#f6ead2', '--dv-warning-text': '#8a5a12',
    '--dv-danger': '#b5533c', '--dv-danger-bg': '#f5e1dc', '--dv-danger-text': '#a8432f',
    '--dv-info': '#8a877e', '--dv-info-bg': '#ecebe6', '--dv-info-text': '#5f5d57',
    '--dv-radius-sm': '6px', '--dv-radius': '8px', '--dv-radius-lg': '10px', '--dv-radius-xl': '12px',
    '--dv-font-sans': '"PingFang SC", "Microsoft YaHei", "Noto Sans SC", "Hiragino Sans GB", system-ui, sans-serif',
    '--dv-font-serif': '"Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong", serif',
    '--dv-font-mono': 'ui-monospace, "Cascadia Mono", Consolas, monospace',
  };
  const css = sass.compile(path.resolve(themeDir, 'tokens.scss'), { style: 'expanded' }).css;
  const defined = Object.fromEntries([...css.matchAll(/^\s*(--dv-[\w-]+):\s*(.+);$/gm)].map(([, name, value]) => [name, value.trim()]));
  for (const [name, value] of Object.entries(expected)) assert.equal(defined[name], value, name);
});

test('tokens.scss is the first theme import and element plus colours derive from it', () => {
  const imports = [...read('theme/index.scss').matchAll(/@import\s+'([^']+)'/g)].map(match => match[1]);
  assert.equal(imports[0], './tokens.scss');
  const css = sass.compile(path.resolve(themeDir, 'index.scss'), { style: 'expanded', loadPaths: [themeDir] }).css;
  for (const type of ['primary', 'success', 'warning', 'danger', 'error', 'info']) {
    assert.match(css, new RegExp(`--el-color-${type}: var\\(--dv-`));
    for (const level of ['light-3', 'light-5', 'light-7', 'light-8', 'light-9', 'dark-2']) assert.match(css, new RegExp(`--el-color-${type}-${level}: #[0-9a-f]{6};`));
  }
  assert.match(css, /--el-color-primary-light-9: #e9e9e8;/);
  assert.match(css, /--el-font-family: var\(--dv-font-sans\);/);
  assert.match(css, /--next-bg-main-color: var\(--dv-bg\);/);
});

test('layout defaults use the new theme colours', () => {
  const store = read('stores/themeConfig.ts');
  const defaults = { primary: '#1f1e1d', menuBar: '#efede6', menuBarColor: '#3d3b36', menuBarActiveColor: '#e2dfd5', topBar: '#ffffff', topBarColor: '#6b6962', columnsMenuBar: '#efede6', columnsMenuBarColor: '#3d3b36' };
  for (const [key, value] of Object.entries(defaults)) assert.match(store, new RegExp(`\\n\\s*${key}: '${value}',`), key);
});
