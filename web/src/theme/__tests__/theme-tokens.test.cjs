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
  assert.equal(THEME_VERSION, 'd-2026-10');
  for (const version of ['a-2026-10', 'c-2026-10', 'old-version', undefined]) {
    const initial = { themeConfig: { primary: '#409eff' }, themeConfigStyle: '--el-color-primary: #409eff;', oldLayout: 'transverse', token: 'kept' };
    if (version) initial.themeVersion = version;
    const storage = memoryStorage(initial);
    assert.equal(resetStaleThemeCache(storage), true);
    assert.equal(storage.data.has('themeConfig'), false);
    assert.equal(storage.data.has('themeConfigStyle'), false);
    // 窗口宽度变化时 layout/index.vue 会按 oldLayout 切回上次的布局，旧值留着会盖掉新的默认布局
    assert.equal(storage.data.has('oldLayout'), false);
    assert.equal(storage.get('themeVersion'), 'd-2026-10');
    assert.equal(storage.get('token'), 'kept');
  }
});

test('current theme version keeps the cached layout config', () => {
  const { resetStaleThemeCache } = loadThemeVersion();
  const storage = memoryStorage({ themeVersion: 'd-2026-10', themeConfig: { layout: 'classic' }, themeConfigStyle: '--x: 1;', oldLayout: 'classic' });
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
    '--dv-side-bg': '#f9f8f3', '--dv-side-inset': '#efede6',
    '--dv-raise': '#ffffff', '--dv-raise-hl': 'rgba(255, 255, 255, 0.95)', '--dv-raise-sh': 'rgba(70, 52, 34, 0.13)', '--dv-raise-border': 'rgba(20, 20, 19, 0.07)', '--dv-drop': 'rgba(70, 52, 34, 0.22)',
    '--dv-text': '#141413', '--dv-text-regular': '#3d3d3a', '--dv-text-secondary': '#73726c', '--dv-text-muted': '#adaba2', '--dv-text-nav': '#3d3d3a',
    '--dv-border': '#e9e6dd', '--dv-border-strong': '#ddd9ce', '--dv-divider': '#e9e6dd',
    '--dv-primary': '#c6613f', '--dv-primary-hover': '#b4542f', '--dv-on-primary': '#ffffff', '--dv-ai': '#c96442',
    '--dv-accent': '#d97757', '--dv-accent-strong': '#c15f3c', '--dv-accent-soft': '#fbede6',
    '--dv-success': '#5b7841', '--dv-success-bg': '#ecf1e4', '--dv-success-text': '#5b7841',
    '--dv-warning': '#8f620e', '--dv-warning-bg': '#f6edd8', '--dv-warning-text': '#8f620e',
    '--dv-danger': '#b23a2b', '--dv-danger-bg': '#f8e7e3', '--dv-danger-text': '#b23a2b',
    '--dv-info': '#4a6d96', '--dv-info-bg': '#e8eef5', '--dv-info-text': '#4a6d96',
    '--dv-radius-sm': '9px', '--dv-radius': '11px', '--dv-radius-lg': '22px', '--dv-radius-xl': '28px',
    '--dv-radius-card': '26px', '--dv-radius-table': '24px', '--dv-radius-popover': '18px', '--dv-radius-badge': '7px',
    '--dv-radius-seg': '12px', '--dv-radius-seg-sm': '8px', '--dv-radius-toast': '14px',
    '--dv-control-height': '34px', '--dv-control-height-sm': '30px',
    '--dv-radius-pill': '999px', '--dv-page-gutter': '10px', '--dv-content-pad': '32px',
    '--dv-content-pad-top': '32px', '--dv-content-pad-bottom': '80px', '--dv-content-max': '1320px',
    '--dv-aside-width': '256px', '--dv-aside-mobile-width': '280px', '--dv-topbar-height': '52px', '--dv-footer-height': '28px',
    '--dv-topbar-bg': 'rgba(255, 254, 251, 0.84)', '--dv-backdrop': 'saturate(1.6) blur(14px)', '--dv-scrim': 'rgba(8, 9, 11, 0.4)',
    '--dv-logo-bg': 'linear-gradient(160deg, #e4a089, #d97757 50%, #c15f3c)',
    '--dv-shadow-logo': 'inset 0 1px 0 rgba(255, 255, 255, 0.35), inset 0 -1px 0 rgba(0, 0, 0, 0.14), 0 2px 4px -2px rgba(217, 119, 87, 0.45)',
    '--dv-shadow-1': '0 1px 2px rgba(70, 52, 34, 0.05), 0 0 0 1px rgba(20, 20, 19, 0.06)',
    '--dv-shadow-raised': 'inset 0 1px 0 rgba(255, 255, 255, 0.95), 0 0 0 1px rgba(20, 20, 19, 0.07), 0 1px 2px rgba(70, 52, 34, 0.085)',
    '--dv-shadow-inset': 'inset 0 1px 1.5px rgba(70, 52, 34, 0.07)',
    '--dv-shadow-drawer': '8px 0 24px -8px rgba(70, 52, 34, 0.22)',
    '--dv-shadow-button': 'inset 0 1px 0 rgba(255, 255, 255, 0.22), 0 1px 2px rgba(70, 52, 34, 0.13), 0 4px 10px -6px #c6613f',
    '--dv-shadow-button-plain': '0 1px 1px rgba(13, 15, 18, 0.04)',
    '--dv-shadow-overlay': '0 24px 48px -12px rgba(70, 52, 34, 0.26), 0 0 0 1px rgba(20, 20, 19, 0.08)',
    // 数据分析页等页面的公共卡片引用这四个变量（见 views/shield/analysis/index.vue 的 .analysis-card）
    '--dv-card-bg': 'var(--dv-tile)', '--dv-card-border': 'transparent', '--dv-shadow-card': 'none',
    '--dv-font-sans': '"Geist", "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif',
    '--dv-font-serif': '"Source Serif 4", "Noto Serif SC", "Songti SC", "STSong", Georgia, serif',
    '--dv-font-mono': '"Geist Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    '--dv-font-title': 'var(--dv-font-serif)',
    '--dv-font-size': '13px', '--dv-line-height': '1.54',
  };
  const css = sass.compile(path.resolve(themeDir, 'tokens.scss'), { style: 'expanded' }).css;
  const rootBlock = css.slice(css.indexOf(':root {'), css.indexOf('}', css.indexOf(':root {')));
  const defined = Object.fromEntries([...rootBlock.matchAll(/^\s*(--dv-[\w-]+):\s*(.+);$/gm)].map(([, name, value]) => [name, value.trim()]));
  for (const [name, value] of Object.entries(expected)) assert.equal(defined[name], value, name);
  // 主面板内容的内边距：宽度 ≤640px 时收成 22px 16px 56px
  assert.match(css, /@media \(max-width: 640px\) \{\s*:root \{\s*--dv-content-pad: 16px;\s*--dv-content-pad-top: 22px;\s*--dv-content-pad-bottom: 56px;\s*\}\s*\}/);
});

test('the grey-white-blue scheme overrides the tokens with the Win11 light values', () => {
  const css = sass.compile(path.resolve(themeDir, 'tokens.scss'), { style: 'expanded' }).css;
  const block = selector => {
    const at = css.indexOf(`\n${selector} {`);
    assert.ok(at >= 0, selector);
    return Object.fromEntries([...css.slice(at, css.indexOf('}', at)).matchAll(/^\s*(--dv-[\w-]+):\s*(.+);$/gm)].map(([, name, value]) => [name, value.trim()]));
  };
  const root = block(':root');
  const blue = block(':root[data-scheme=blue]');
  const expected = {
    // 背景一律白，灰只用在悬停、选中、表头/浅底块
    '--dv-bg': '#ffffff', '--dv-surface': '#ffffff', '--dv-side-bg': '#ffffff', '--dv-card-bg': 'var(--dv-surface)',
    '--dv-hover': '#f0f0f0', '--dv-hover-solid': '#f0f0f0', '--dv-selected': '#ebebeb', '--dv-tile': '#f7f7f7', '--dv-surface-muted': '#f7f7f7',
    '--dv-divider': '#e5e5e5', '--dv-border': '#e5e5e5', '--dv-border-strong': '#d1d1d1', '--dv-card-border': 'var(--dv-border)',
    '--dv-text': '#1b1b1b', '--dv-text-nav': '#1b1b1b', '--dv-text-secondary': '#5d5d5d', '--dv-text-muted': '#8a8a8a',
    // 主题蓝；悬停加深一档、最浅一档用于选中行和焦点光晕（Element Plus 的深浅色算法）；链接文字 #005fb8
    '--dv-primary': '#0067c0', '--dv-primary-hover': '#005dad', '--dv-accent': '#0067c0', '--dv-accent-strong': '#005fb8', '--dv-accent-soft': '#e6f0f9',
    // info 是中性灰蓝，不和主题蓝撞色
    '--dv-info': '#5b6b7d', '--dv-info-bg': '#eef1f4', '--dv-info-text': '#5b6b7d',
    // 控件 4px，卡片/表格/弹窗/浮层 8px
    '--dv-radius-sm': '4px', '--dv-radius': '4px', '--dv-radius-badge': '4px', '--dv-radius-card': '8px', '--dv-radius-table': '8px',
    '--dv-radius-xl': '8px', '--dv-radius-popover': '8px', '--dv-radius-toast': '8px', '--dv-radius-lg': '8px',
    // 阴影只留浮层、弹窗和抽屉；卡片不加阴影
    '--dv-shadow-overlay': '0 8px 16px rgba(0, 0, 0, 0.14), 0 0 0 1px rgba(0, 0, 0, 0.06)', '--dv-shadow-drawer': '8px 0 24px -8px rgba(0, 0, 0, 0.18)',
    '--dv-shadow-1': '0 0 0 1px rgba(0, 0, 0, 0.08)', '--dv-shadow-button-plain': 'none', '--dv-shadow-logo': 'none',
    '--dv-logo-bg': '#0067c0', '--dv-topbar-bg': 'rgba(255, 255, 255, 0.84)',
    // 标题不用衬线
    '--dv-font-title': 'var(--dv-font-sans)',
  };
  for (const [name, value] of Object.entries(expected)) assert.equal(blue[name], value, name);
  // 只覆盖暖白里有的变量；状态色（成功/警告/危险）、卡片阴影沿用暖白
  for (const name of Object.keys(blue)) assert.ok(name in root, name);
  for (const name of ['--dv-success', '--dv-warning', '--dv-danger', '--dv-shadow-card', '--dv-font-sans', '--dv-font-size']) assert.equal(blue[name], undefined, name);
  assert.equal(root['--dv-shadow-card'], 'none');
});

test('the grey-white-blue scheme regenerates the Element Plus primary and info shades', () => {
  const css = sass.compile(path.resolve(themeDir, 'index.scss'), { style: 'expanded', loadPaths: [themeDir] }).css;
  const blocks = [...css.matchAll(/\n:root\[data-scheme=blue\] \{([^}]*)\}/g)].map(match => match[1]);
  const el = blocks.find(body => body.includes('--el-color-primary'));
  assert.ok(el);
  const shades = { 'light-3': '#4d95d3', 'light-5': '#80b3e0', 'light-7': '#b3d1ec', 'light-8': '#cce1f2', 'light-9': '#e6f0f9', 'dark-2': '#00529a' };
  for (const [level, value] of Object.entries(shades)) assert.match(el, new RegExp(`--el-color-primary-${level}: ${value};`), level);
  assert.match(el, /--el-color-primary: var\(--dv-primary\);/);
  assert.match(el, /--el-color-primary-rgb: 0, 103, 192;/);
  assert.match(el, /--el-color-info-rgb: 91, 107, 125;/);
  assert.doesNotMatch(el, /--el-color-(success|warning|danger)/);
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

test('fs-page is a transparent page padded like the main content, without a fixed height', () => {
  const css = sass.compile(path.resolve(themeDir, 'index.scss'), { style: 'expanded', loadPaths: [themeDir] }).css;
  const rules = [...css.matchAll(/(^|\n)div\.fs-page \{([^}]*)\}/g)].map(match => match[2]);
  assert.equal(rules.length, 1);
  // 主面板已经是白底大圆角面板：CRUD 页不再画卡片（边框、圆角、底色、四边内缩），只留与主内容一致的内边距
  assert.match(rules[0], /padding: var\(--dv-content-pad\);/);
  for (const side of ['top', 'right', 'bottom', 'left']) assert.doesNotMatch(rules[0], new RegExp(`(^|\\n)\\s*${side}:`));
  assert.doesNotMatch(rules[0], /border|background|radius|width/);
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

function loadColorSchemes() {
  const context = { exports: {} };
  vm.runInNewContext(ts.transpileModule(read('theme/colorSchemes.ts'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, context);
  return context.exports;
}

test('layout defaults use the sidebar layout and the warm scheme colours', () => {
  const store = read('stores/themeConfig.ts');
  assert.match(store, /\n\s*layout: 'defaults',/);
  assert.match(store, /\n\s*isBreadcrumb: true,/);
  // 默认配色暖白；主题色、顶栏、菜单颜色取自 colorSchemes.ts 的暖白
  assert.match(store, /\n\s*colorScheme: 'claude',/);
  assert.match(store, /const defaultColors = colorSchemeColors\('claude'\);/);
  const keys = ['primary', 'topBar', 'topBarColor', 'menuBar', 'menuBarColor', 'menuBarActiveColor', 'columnsMenuBar', 'columnsMenuBarColor'];
  for (const key of keys) assert.match(store, new RegExp(`\\n\\s*${key}: defaultColors\\.${key},`), key);
});

test('each scheme sets the layout colours to the values of its own tokens', () => {
  const { COLOR_SCHEMES } = loadColorSchemes();
  assert.deepEqual(Array.from(COLOR_SCHEMES, s => [s.value, s.label]), [['claude', '暖白'], ['blue', '灰白蓝']]);
  // 设置抽屉按这些颜色写内联变量；app.scss 的兜底值要指向同一组 token，两套配色下都对得上
  const tokens = sass.compile(path.resolve(themeDir, 'tokens.scss'), { style: 'expanded' }).css;
  const block = selector => {
    const at = tokens.indexOf(`\n${selector} {`);
    return Object.fromEntries([...tokens.slice(at, tokens.indexOf('}', at)).matchAll(/^\s*--dv-([\w-]+):\s*(.+);$/gm)].map(([, name, value]) => [name, value.trim()]));
  };
  const root = block(':root');
  const values = { claude: root, blue: { ...root, ...block(':root[data-scheme=blue]') } };
  const app = read('theme/app.scss');
  // 菜单高亮背景色是选中项的灰底（Win11 侧栏：选中灰底 + 左侧竖线），不再是白色凸起块
  const fallback = { primary: 'primary', topBar: 'surface', topBarColor: 'text-secondary', menuBar: 'side-bg', menuBarColor: 'text-nav', menuBarActiveColor: 'selected', columnsMenuBar: 'side-bg', columnsMenuBarColor: 'text-nav' };
  for (const scheme of COLOR_SCHEMES) {
    for (const [key, name] of Object.entries(fallback)) {
      if (key !== 'primary') assert.match(app, new RegExp(`--next-bg-${key}: var\\(--dv-${name}\\);`), key);
      assert.equal(scheme.colors[key], values[scheme.value][name], `${scheme.value}.${key}`);
    }
  }
});
