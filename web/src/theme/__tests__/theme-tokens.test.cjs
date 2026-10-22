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
  assert.equal(THEME_VERSION, 'c-2026-10');
  for (const version of ['a-2026-10', 'old-version', undefined]) {
    const initial = { themeConfig: { primary: '#409eff' }, themeConfigStyle: '--el-color-primary: #409eff;', oldLayout: 'transverse', token: 'kept' };
    if (version) initial.themeVersion = version;
    const storage = memoryStorage(initial);
    assert.equal(resetStaleThemeCache(storage), true);
    assert.equal(storage.data.has('themeConfig'), false);
    assert.equal(storage.data.has('themeConfigStyle'), false);
    // 窗口宽度变化时 layout/index.vue 会按 oldLayout 切回上次的布局，旧值留着会盖掉新的默认布局
    assert.equal(storage.data.has('oldLayout'), false);
    assert.equal(storage.get('themeVersion'), 'c-2026-10');
    assert.equal(storage.get('token'), 'kept');
  }
});

test('current theme version keeps the cached layout config', () => {
  const { resetStaleThemeCache } = loadThemeVersion();
  const storage = memoryStorage({ themeVersion: 'c-2026-10', themeConfig: { layout: 'classic' }, themeConfigStyle: '--x: 1;', oldLayout: 'classic' });
  assert.equal(resetStaleThemeCache(storage), false);
  assert.deepEqual(storage.get('themeConfig'), { layout: 'classic' });
  assert.equal(storage.get('themeConfigStyle'), '--x: 1;');
  assert.equal(storage.get('oldLayout'), 'classic');
});

test('App.vue checks the theme version during setup, before anything reads the cached layout config', () => {
  const app = read('App.vue');
  const reset = app.indexOf('resetStaleThemeCache(Local)');
  assert.ok(reset > 0);
  assert.equal(app.indexOf('resetStaleThemeCache(Local)', reset + 1), -1);
  for (const reader of ['const getGlobalComponentSize', 'onMounted(', "if (Local.get('themeConfig'))"]) assert.ok(reset < app.indexOf(reader), reader);
});

test('tokens.scss defines every design variable with the agreed value', () => {
  const expected = {
    '--dv-bg': '#eae7de', '--dv-surface': '#fffefb', '--dv-tile': '#f6f4ee', '--dv-surface-muted': '#efede6', '--dv-selected': '#e2dfd5',
    '--dv-hover': '#f2f0e9', '--dv-hover-solid': '#f2f0e9', '--dv-fill': 'rgba(20, 20, 19, 0.06)',
    '--dv-side-top': '#f9f8f3', '--dv-side-bot': '#f2f0e8', '--dv-side-bot-mix': '#f5f4ed', '--dv-side-border': 'rgba(20, 20, 19, 0.08)', '--dv-side-inset': '#efede6',
    '--dv-raise': '#ffffff', '--dv-raise-hl': 'rgba(255, 255, 255, 0.95)', '--dv-raise-sh': 'rgba(70, 52, 34, 0.13)', '--dv-raise-border': 'rgba(20, 20, 19, 0.07)', '--dv-drop': 'rgba(70, 52, 34, 0.22)',
    '--dv-text': '#141413', '--dv-text-regular': '#3d3d3a', '--dv-text-secondary': '#73726c', '--dv-text-muted': '#adaba2', '--dv-text-nav': '#3d3d3a',
    '--dv-border': '#e9e6dd', '--dv-border-strong': '#ddd9ce',
    '--dv-primary': '#c6613f', '--dv-primary-hover': '#b4542f', '--dv-on-primary': '#ffffff', '--dv-ai': '#c96442',
    '--dv-accent': '#d97757', '--dv-accent-strong': '#c15f3c', '--dv-accent-soft': '#fbede6',
    '--dv-success': '#5b7841', '--dv-success-bg': '#ecf1e4', '--dv-success-text': '#5b7841',
    '--dv-warning': '#8f620e', '--dv-warning-bg': '#f6edd8', '--dv-warning-text': '#8f620e',
    '--dv-danger': '#b23a2b', '--dv-danger-bg': '#f8e7e3', '--dv-danger-text': '#b23a2b',
    '--dv-info': '#4a6d96', '--dv-info-bg': '#e8eef5', '--dv-info-text': '#4a6d96',
    '--dv-radius-sm': '9px', '--dv-radius': '11px', '--dv-radius-lg': '22px', '--dv-radius-xl': '28px',
    '--dv-radius-card': '26px', '--dv-radius-table': '24px', '--dv-radius-popover': '18px', '--dv-radius-badge': '7px',
    '--dv-radius-pill': '999px', '--dv-page-gutter': '10px', '--dv-content-pad': '32px',
    '--dv-shadow-1': '0 1px 2px rgba(70, 52, 34, 0.05), 0 0 0 1px rgba(20, 20, 19, 0.06)',
    '--dv-shadow-raised': 'inset 0 1px 0 rgba(255, 255, 255, 0.95), 0 0 0 1px rgba(20, 20, 19, 0.07), 0 1px 2px rgba(70, 52, 34, 0.085)',
    '--dv-shadow-side': 'inset 0 1px 0 rgba(255, 255, 255, 0.95), 0 0 0 1px rgba(20, 20, 19, 0.08), 0 1px 2px rgba(70, 52, 34, 0.065), 0 10px 24px -22px rgba(70, 52, 34, 0.22)',
    '--dv-shadow-inset': 'inset 0 1px 1.5px rgba(70, 52, 34, 0.07)',
    '--dv-shadow-button': 'inset 0 1px 0 rgba(255, 255, 255, 0.22), 0 1px 2px rgba(70, 52, 34, 0.13), 0 4px 10px -6px #c6613f',
    '--dv-shadow-button-plain': '0 1px 1px rgba(13, 15, 18, 0.04)',
    '--dv-shadow-overlay': '0 24px 48px -12px rgba(70, 52, 34, 0.26), 0 0 0 1px rgba(20, 20, 19, 0.08)',
    // 数据分析页等页面的公共卡片引用这四个变量（见 views/shield/analysis/index.vue 的 .analysis-card）
    '--dv-card-bg': 'var(--dv-tile)', '--dv-card-border': 'transparent', '--dv-shadow-card': 'none',
    '--dv-font-sans': '"Geist", "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif',
    '--dv-font-serif': '"Source Serif 4", "Noto Serif SC", "Songti SC", "STSong", Georgia, serif',
    '--dv-font-mono': '"Geist Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    '--dv-font-size': '13px', '--dv-line-height': '1.54',
  };
  const css = sass.compile(path.resolve(themeDir, 'tokens.scss'), { style: 'expanded' }).css;
  const rootBlock = css.slice(css.indexOf(':root {'), css.indexOf('}', css.indexOf(':root {')));
  const defined = Object.fromEntries([...rootBlock.matchAll(/^\s*(--dv-[\w-]+):\s*(.+);$/gm)].map(([, name, value]) => [name, value.trim()]));
  for (const [name, value] of Object.entries(expected)) assert.equal(defined[name], value, name);
  // 主面板内容的左右内边距：宽度 ≤640px 时收成 16px
  assert.match(css, /@media \(max-width: 640px\) \{\s*:root \{\s*--dv-content-pad: 16px;\s*\}\s*\}/);
});

test('fonts.scss is the first theme import, tokens.scss comes next and element plus colours derive from it', () => {
  const imports = [...read('theme/index.scss').matchAll(/@import\s+'([^']+)'/g)].map(match => match[1]);
  assert.equal(imports[0], './fonts.scss');
  assert.equal(imports[1], './tokens.scss');
  const css = sass.compile(path.resolve(themeDir, 'index.scss'), { style: 'expanded', loadPaths: [themeDir] }).css;
  for (const type of ['primary', 'success', 'warning', 'danger', 'error', 'info']) {
    assert.match(css, new RegExp(`--el-color-${type}: var\\(--dv-`));
    for (const level of ['light-3', 'light-5', 'light-7', 'light-8', 'light-9', 'dark-2']) assert.match(css, new RegExp(`--el-color-${type}-${level}: #[0-9a-f]{6};`));
  }
  assert.match(css, /--el-color-primary-light-9: #f9efec;/);
  assert.match(css, /--el-font-family: var\(--dv-font-sans\);/);
  assert.match(css, /--el-font-size-base: var\(--dv-font-size\);/);
  assert.match(css, /--next-bg-main-color: var\(--dv-bg\);/);
  // 表格固定列是 sticky 的，悬停底色必须不透明
  assert.match(css, /--el-table-row-hover-bg-color: var\(--dv-hover-solid\);/);
  // 正文 13px、行高 1.54
  const body = css.match(/\nhtml,\nbody,\n#app \{([^}]*)\}/)[1];
  assert.match(body, /font-family: var\(--dv-font-sans\);/);
  assert.match(body, /font-size: var\(--dv-font-size\);/);
  assert.match(body, /line-height: var\(--dv-line-height\);/);
});

test('fonts.scss declares the bundled font files with font-display swap', () => {
  const fontsDir = path.resolve(srcDir, 'assets/fonts');
  const scss = read('theme/fonts.scss');
  const faces = [...scss.matchAll(/@font-face \{([^}]*)\}/g)].map(match => match[1]);
  const prop = (face, name) => (face.match(new RegExp(`\\n\\s*${name}: ([^;]+);`)) || [])[1];
  for (const face of faces) {
    assert.equal(prop(face, 'font-display'), 'swap');
    assert.equal(prop(face, 'font-style'), 'normal');
    assert.ok(prop(face, 'unicode-range'));
    // 相对路径引用，交给 Vite 打包；文件必须真实存在
    const url = prop(face, 'src').match(/^url\('(\.\.\/assets\/fonts\/[\w-]+\/[\w-]+\.woff2)'\) format\('woff2(-variations)?'\)$/)[1];
    assert.ok(fs.existsSync(path.resolve(themeDir, url)), url);
  }
  const byFamily = family => faces.filter(face => prop(face, 'font-family') === `'${family}'`);
  for (const [family, weight] of [['Geist', '100 900'], ['Geist Mono', '100 900'], ['Source Serif 4', '200 900']]) {
    assert.equal(byFamily(family).length, 1, family);
    assert.equal(prop(byFamily(family)[0], 'font-weight'), weight, family);
  }
  // 中文衬线只带 600 一个字重，按 unicode-range 分片；目录里的分片都要有对应的 @font-face
  const noto = byFamily('Noto Serif SC');
  assert.equal(noto.length, 101);
  for (const face of noto) assert.equal(prop(face, 'font-weight'), '600');
  const referenced = new Set(noto.map(face => prop(face, 'src').match(/noto-serif-sc\/([\w-]+\.woff2)/)[1]));
  const shards = fs.readdirSync(path.join(fontsDir, 'noto-serif-sc')).filter(file => file.endsWith('.woff2'));
  assert.deepEqual([...referenced].sort(), shards.sort());
  assert.equal(faces.length, 3 + 101);
  // 每个字体目录都带许可证
  for (const dir of fs.readdirSync(fontsDir)) assert.match(fs.readFileSync(path.join(fontsDir, dir, 'LICENSE'), 'utf8'), /SIL Open Font License/, dir);
});

test('fs-page becomes a card inset by the page gutter without a fixed height', () => {
  const css = sass.compile(path.resolve(themeDir, 'index.scss'), { style: 'expanded', loadPaths: [themeDir] }).css;
  const rules = [...css.matchAll(/(^|\n)div\.fs-page \{([^}]*)\}/g)].map(match => match[2]);
  assert.equal(rules.length, 1);
  for (const side of ['top', 'right', 'bottom', 'left']) assert.match(rules[0], new RegExp(`${side}: var\\(--dv-page-gutter\\);`));
  assert.match(rules[0], /width: auto !important;/);
  assert.match(rules[0], /border: 1px solid var\(--el-border-color\);/);
  assert.match(rules[0], /border-radius: var\(--dv-radius-lg\);/);
  assert.doesNotMatch(rules[0], /height|shadow|margin/);
});

test('fast-crud row buttons and table overrides take their colours from the theme', () => {
  const settings = read('settings.ts');
  const rowHandle = settings.slice(settings.indexOf('rowHandle: {'), settings.indexOf('group:{'));
  assert.doesNotMatch(rowHandle, /#[0-9a-fA-F]{3,6}\b/);
  assert.match(rowHandle, /remove: \{[^}]*style:\{color: 'var\(--el-color-danger\)'\}/);
  const reset = read('assets/style/reset.scss');
  assert.doesNotMatch(reset, /#[0-9a-fA-F]{3,6}\b/);
});

test('layout defaults use the sidebar layout and the new theme colours', () => {
  const store = read('stores/themeConfig.ts');
  const defaults = { layout: 'defaults', primary: '#c6613f', menuBar: '#f9f8f3', menuBarColor: '#3d3d3a', menuBarActiveColor: '#ffffff', topBar: '#fffefb', topBarColor: '#73726c', columnsMenuBar: '#f9f8f3', columnsMenuBarColor: '#3d3d3a' };
  for (const [key, value] of Object.entries(defaults)) assert.match(store, new RegExp(`\\n\\s*${key}: '${value}',`), key);
  assert.match(store, /\n\s*isBreadcrumb: true,/);
  // 设置抽屉按这些默认值写内联变量；app.scss 的兜底值要指向同一组 token
  const tokens = sass.compile(path.resolve(themeDir, 'tokens.scss'), { style: 'expanded' }).css;
  const token = name => tokens.match(new RegExp(`--dv-${name}: ([^;]+);`))[1];
  const app = read('theme/app.scss');
  const fallback = { topBar: 'surface', topBarColor: 'text-secondary', menuBar: 'side-top', menuBarColor: 'text-nav', menuBarActiveColor: 'raise', columnsMenuBar: 'side-top', columnsMenuBarColor: 'text-nav' };
  for (const [key, name] of Object.entries(fallback)) {
    assert.match(app, new RegExp(`--next-bg-${key}: var\\(--dv-${name}\\);`), key);
    assert.equal(token(name), defaults[key], key);
  }
  assert.equal(token('primary'), defaults.primary);
});
