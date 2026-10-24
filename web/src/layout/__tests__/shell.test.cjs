const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const sass = require('sass');

const srcDir = path.resolve(__dirname, '..', '..');
const read = file => fs.readFileSync(path.resolve(srcDir, file), 'utf8');
const themeCss = () => sass.compile(path.resolve(srcDir, 'theme/index.scss'), { style: 'expanded', loadPaths: [path.resolve(srcDir, 'theme')] }).css;

function loadOpenedPages() {
  const context = { exports: {}, require };
  vm.runInNewContext(ts.transpileModule(read('layout/navBars/tagsView/openedPages.ts'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, context);
  return context.exports;
}

test('recent pages list the current page first, then the other open pages newest first, at most six', () => {
  const { recentOpenedPages } = loadOpenedPages();
  // 函数在 vm 里运行，返回的数组属于另一个 realm，先转成本地数组再比较
  const paths = list => Array.from(recentOpenedPages(list), p => p.route.path);
  const page = (path, isActive = false) => ({ route: { path, url: path }, isActive });
  const list = ['/a', '/b', '/c', '/d', '/e', '/f', '/g', '/h'].map(p => page(p, p === '/c'));
  assert.deepEqual(paths(list), ['/c', '/h', '/g', '/f', '/e', '/d']);
  assert.deepEqual(paths([page('/a'), page('/b', true)]), ['/b', '/a']);
  assert.deepEqual(paths([]), []);
});

test('the sidebar recent list mirrors the tags view, which still owns the open pages and the keep-alive cache', () => {
  // 标签栏不关：isTagsview 保持 true，keep-alive 仍按标签栏的 cachedViews 缓存和释放
  assert.match(read('stores/themeConfig.ts'), /\n\s*isTagsview: true,/);
  assert.match(read('layout/routerView/parent.vue'), /themeConfig\.value\.isTagsview \? cachedViews\.value : state\.keepAliveNameList/);
  // 侧边栏布局只隐藏横条，组件照常挂载
  const navBars = read('layout/navBars/index.vue');
  assert.match(navBars, /<TagsView v-if="setShowTagsView" v-show="themeConfig\.layout !== 'defaults'" \/>/);
  // tagsView.vue 把打开的页面同步给侧栏，关闭走它自己的 closeCurrentTagsView
  const tagsView = read('layout/navBars/tagsView/tagsView.vue');
  assert.match(tagsView, /import \{ openedPages \} from '\/@\/layout\/navBars\/tagsView\/openedPages';/);
  assert.match(tagsView, /openedPages\.list = state\.tagsViewList\.map\(\(v: RouteItem\) => \(\{ route: v, isActive: isActive\(v\) \}\)\);/);
  assert.match(tagsView, /const closeFromOpenedPages = \(v: RouteItem\) => \{\s*closeCurrentTagsView\(getThemeConfig\.value\.isShareTagsView \? v\.path : v\.url\);/);
  assert.match(tagsView, /openedPages\.close = closeFromOpenedPages;/);
  assert.match(tagsView, /if \(openedPages\.close === closeFromOpenedPages\) \{\s*openedPages\.list = \[\];\s*openedPages\.close = null;/);
  // 侧栏读这份镜像，关闭调用登记的 close
  const recent = read('layout/component/asideRecent.vue');
  assert.match(recent, /recentOpenedPages\(openedPages\.list\)/);
  assert.match(recent, /openedPages\.close\?\.\(route\)/);
  assert.match(recent, /v-if="!page\.route\.meta\?\.isAffix"/);
});

test('the sidebar panel holds logo, menu search, menu, recent pages and the user block', () => {
  const aside = read('layout/component/aside.vue');
  const order = ['<Logo v-if="setShowLogo" />', 'class="layout-aside-search"', '<Vertical :menuList="state.menuList" />', '<AsideRecent v-if="isPanel && !isPanelCollapse" />', '<AsideUser v-if="isPanel" />'];
  const at = order.map(snippet => aside.indexOf(snippet));
  for (const [k, index] of at.entries()) assert.ok(index > 0, order[k]);
  assert.deepEqual([...at].sort((a, b) => a - b), at);
  assert.match(aside, /<span>搜索菜单<\/span>/);
  assert.match(aside, /layout === 'defaults' \? 'layout-aside-pc-256' : 'layout-aside-pc-220'/);
  // 菜单搜索打开的是现有的搜索弹窗组件
  assert.match(aside, /const Search = defineAsyncComponent\(\(\) => import\('\/@\/layout\/navBars\/breadcrumb\/search\.vue'\)\);/);
  assert.match(read('layout/component/asideRecent.vue'), />最近打开</);
  // 用户菜单：顶栏和侧栏共用同一个下拉组件；侧边栏布局顶栏不再显示头像和用户名
  assert.match(read('layout/component/asideUser.vue'), /<UserDropdown trigger="click"/);
  const user = read('layout/navBars/breadcrumb/user.vue');
  assert.match(user, /<template v-if="themeConfig\.layout !== 'defaults'">[\s\S]*<UserDropdown[\s\S]*<\/UserDropdown>\s*<\/template>/);
  assert.doesNotMatch(user, /onHandleCommandClick|ElMessageBox/);
  const dropdown = read('layout/navBars/breadcrumb/userDropdown.vue');
  for (const command of ['command="/home"', 'command="/personal"', 'command="logOut"']) assert.ok(dropdown.includes(command), command);
});

test('the system name reads 盾构刀具管理系统 everywhere outside the login page', () => {
  assert.match(read('layout/logo/index.vue'), /<span class = "layout-logo__title">盾构刀具管理系统<\/span>/);
  assert.match(read('layout/logo/index.vue'), /Information Management System of Shield Tunnel Cutter/);
  assert.match(read('layout/footer/index.vue'), /<div>盾构刀具管理系统<\/div>/);
  assert.match(read('stores/themeConfig.ts'), /\n\s*globalTitle: '盾构刀具管理系统',/);
  assert.match(fs.readFileSync(path.resolve(srcDir, '..', 'index.html'), 'utf8'), /<title>盾构刀具管理系统<\/title>/);
});

test('the sidebar layout insets two panels by the page gutter and floats a glass top bar over the main panel', () => {
  const css = themeCss();
  const rule = selector => {
    const at = css.indexOf(`\n${selector} {`);
    assert.ok(at >= 0, selector);
    return css.slice(at, css.indexOf('}', at));
  };
  const shell = rule('.layout-container.layout-shell');
  assert.match(shell, /padding: var\(--dv-page-gutter\);/);
  assert.match(shell, /gap: var\(--dv-page-gutter\);/);
  const asidePanel = rule('.layout-container.layout-shell .layout-aside.layout-aside-panel');
  for (const decl of ['border-radius: var(--dv-radius-lg);', 'background: var(--dv-side-bg);', 'box-shadow: var(--dv-shadow-side);', 'padding: 14px 12px 12px;']) assert.ok(asidePanel.includes(decl), decl);
  const mainPanel = rule('.layout-container.layout-shell .layout-container-view');
  for (const decl of ['border-radius: var(--dv-radius-lg);', 'background-color: var(--dv-surface);', 'box-shadow: var(--dv-shadow-1);', 'overflow: hidden;']) assert.ok(mainPanel.includes(decl), decl);
  assert.match(rule('.layout-container.layout-shell .layout-container-view > .layout-header'), /position: absolute;/);
  assert.match(rule('.layout-container.layout-shell .layout-container-view .layout-main.layout-main-under-topbar'), /padding-top: var\(--dv-topbar-height\) !important;/);
  // 窄屏：侧栏是离边一个页面间距、280px 宽的浮动抽屉
  const drawer = rule('.layout-container.layout-shell .layout-aside-panel.layout-aside-mobile');
  for (const decl of ['top: var(--dv-page-gutter);', 'bottom: var(--dv-page-gutter);', 'width: var(--dv-aside-mobile-width);']) assert.ok(drawer.includes(decl), decl);
  assert.match(css, /\.layout-aside-mobile-mode \{[^}]*background-color: var\(--dv-scrim\);/);
  // 毛玻璃画在 ::before 上：加在顶栏本身会让顶栏里的菜单搜索弹窗遮罩只剩顶栏大小
  const header = read('layout/navBars/breadcrumb/index.vue');
  const glass = header.slice(header.indexOf('&.is-glass {'));
  const before = glass.slice(glass.indexOf('&::before {'), glass.indexOf('}', glass.indexOf('&::before {')));
  assert.match(before, /backdrop-filter: var\(--dv-backdrop\);/);
  assert.match(before, /background: var\(--dv-topbar-bg\);/);
  assert.equal(glass.slice(0, glass.indexOf('&::before {')).includes('backdrop-filter'), false);
});

test('route pages sit in a centred, padded column except CRUD pages, the home screen and the assistant', () => {
  const css = themeCss();
  assert.match(css, /\n\.layout-container \.layout-parent \{\s*width: 100%;\s*max-width: var\(--dv-content-max\);\s*margin: 0 auto;\s*padding: var\(--dv-content-pad-top\) var\(--dv-content-pad\) var\(--dv-content-pad-bottom\);\s*\}/);
  assert.match(css, /\.layout-container \.layout-parent\.layout-parent-full,\s*\.layout-container \.layout-parent \.layout-parent \{\s*max-width: none;\s*padding: 0;\s*\}/);
  assert.match(css, /\.layout-container \.layout-parent:has\(> \.fs-page, > \.ai-assistant-container\) \{\s*max-width: none;\s*padding: 0;\s*\}/);
  const parent = read('layout/routerView/parent.vue');
  assert.match(parent, /<div class="layout-parent" :class="\{ 'layout-parent-full': isFullPage \}">/);
  assert.match(parent, /return route\.name === 'home';/);
  // 智能助手按布局给出的可用高度铺满，不再写死顶栏和标签栏的高度
  assert.match(read('views/ai-assistant/index.vue'), /\.ai-assistant-container \{[^}]*height: var\(--dv-main-height\);/);
  assert.match(css, /\.layout-container\.layout-shell \.layout-container-view \.layout-main \{[^}]*--dv-main-height: calc\(100vh - 2 \* var\(--dv-page-gutter\) - var\(--dv-topbar-height\) - var\(--dv-footer-height\)\);/);
  assert.match(css, /\.layout-container \.layout-main \{\s*--dv-main-height: calc\(100vh - 85px - var\(--dv-footer-height\)\);/);
  assert.match(css, /\.layout-container \.layout-main\.layout-main-no-footer \{\s*--dv-footer-height: 0px;/);
  assert.match(read('layout/footer/index.vue'), /height: var\(--dv-footer-height\);/);
  assert.match(read('layout/component/main.vue'), /'layout-main-no-footer': !isFooter/);
});
