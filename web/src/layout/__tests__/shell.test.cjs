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

test('recent pages list the five most recently visited pages, newest first, without the home page', () => {
  const { recentOpenedPages, overflowOpenedPages, RECENT_PAGES_LIMIT } = loadOpenedPages();
  assert.equal(RECENT_PAGES_LIMIT, 5);
  // 函数在 vm 里运行，返回的数组属于另一个 realm，先转成本地数组再比较
  const paths = list => Array.from(recentOpenedPages(list), p => p.route.path);
  const overflow = list => Array.from(overflowOpenedPages(list), p => p.route.path);
  const page = (path, lastVisit = 0, isActive = false, isAffix = false) => ({ route: { path, url: path, meta: { isAffix } }, isActive, lastVisit });
  const home = page('/home', 900, false, true);
  // 打开顺序 a..g，访问顺序与打开顺序不同；当前页 /d 最后访问
  const list = [home, page('/a', 100), page('/b', 600), page('/c', 300), page('/d', 700, true), page('/e', 200), page('/f', 500), page('/g', 400)];
  assert.deepEqual(paths(list), ['/d', '/b', '/f', '/g', '/c']);
  // 挤出去的是最久没访问的，首页（固定页）不列也不关
  assert.deepEqual(overflow(list), ['/e', '/a']);
  // 没有访问记录的（刷新前打开、之后没再访问）排在后面，按打开先后倒序；当前页总在第一个
  assert.deepEqual(paths([page('/a'), page('/b'), page('/c', 0, true), page('/d', 50)]), ['/c', '/d', '/b', '/a']);
  assert.deepEqual(paths([page('/a', 900), page('/b', 100, true)]), ['/b', '/a']);
  for (let n = 0; n <= 8; n++) {
    const pages = Array.from({ length: n }, (_, k) => page(`/p${k}`, k + 1, k === 0));
    assert.equal(paths(pages).length, Math.min(n, 5));
    assert.equal(overflow(pages).length, Math.max(n - 5, 0));
    assert.equal(overflow(pages).includes('/p0'), false);
  }
  assert.deepEqual(paths([]), []);
  assert.deepEqual(paths([home]), []);
});

test('the sidebar recent list mirrors the tags view, which still owns the open pages and the keep-alive cache', () => {
  // 标签栏不关：isTagsview 保持 true，keep-alive 仍按标签栏的 cachedViews 缓存和释放
  assert.match(read('stores/themeConfig.ts'), /\n\s*isTagsview: true,/);
  assert.match(read('layout/routerView/parent.vue'), /themeConfig\.value\.isTagsview \? cachedViews\.value : state\.keepAliveNameList/);
  // 侧边栏布局只隐藏横条，组件照常挂载
  const navBars = read('layout/navBars/index.vue');
  assert.match(navBars, /<TagsView v-if="setShowTagsView" v-show="themeConfig\.layout !== 'defaults'" \/>/);
  // tagsView.vue 把打开的页面和最后访问时间同步给侧栏，关闭走它自己的 closeCurrentTagsView
  const tagsView = read('layout/navBars/tagsView/tagsView.vue');
  assert.match(tagsView, /import \{ openedPages, overflowOpenedPages \} from '\/@\/layout\/navBars\/tagsView\/openedPages';/);
  assert.match(tagsView, /const getOpenedPageKey = \(v: RouteItem\) => \(getThemeConfig\.value\.isShareTagsView \? v\.path : v\.url\);/);
  assert.match(tagsView, /const closeFromOpenedPages = \(v: RouteItem\) => \{\s*closeCurrentTagsView\(getOpenedPageKey\(v\)\);/);
  assert.match(tagsView, /openedPages\.list = state\.tagsViewList\.map\(\(v: RouteItem\) => \(\{ route: v, isActive: isActive\(v\), lastVisit: visits\[getOpenedPageKey\(v\)\] \}\)\);/);
  // 当前页的访问时间记成现在，其余沿用上次的记录；记录存在会话缓存里，列表重新载入时短暂清空不丢记录
  assert.match(tagsView, /\[getOpenedPageKey\(v\), isActive\(v\) \? now : lastVisits\[getOpenedPageKey\(v\)\] \|\| 0\]/);
  assert.match(tagsView, /let lastVisits: Record<string, number> = Session\.get\('tagsViewLastVisits'\) \|\| \{\};/);
  assert.match(tagsView, /if \(state\.tagsViewList\.length\) \{\s*lastVisits = visits;\s*Session\.set\('tagsViewLastVisits', lastVisits\);/);
  // 侧边栏布局（没有标签栏横条）里，挤出最近 5 个的页面走标签栏的关闭逻辑真正关掉，释放 keep-alive 缓存；
  // 切换布局也要重新检查，所以 layout 在监听的来源里。只在用户自己选的是侧边栏布局时关（窄屏临时变的不关），
  // 具体行为见 recent-pages.test.cjs
  assert.match(tagsView, /getThemeConfig\.value\.isShareTagsView, getThemeConfig\.value\.layout\]/);
  assert.match(tagsView, /const isSidebarLayoutChosen = \(\) => \(Local\.get\('oldLayout'\) \|\| getThemeConfig\.value\.layout\) === 'defaults';/);
  assert.match(tagsView, /if \(getThemeConfig\.value\.layout === 'defaults' && isSidebarLayoutChosen\(\)\) \{\s*overflowOpenedPages\(openedPages\.list\)\.forEach\(\(page\) => closeFromOpenedPages\(page\.route\)\);/);
  const close = tagsView.slice(tagsView.indexOf('const closeCurrentTagsView'), tagsView.indexOf('// 4、关闭其它'));
  assert.match(close, /storesKeepALiveNames\.delCachedView\(v\);/);
  assert.match(tagsView, /openedPages\.close = closeFromOpenedPages;/);
  assert.match(tagsView, /if \(openedPages\.close === closeFromOpenedPages\) \{\s*openedPages\.list = \[\];\s*openedPages\.close = null;/);
  // 侧栏读这份镜像；列表里不放关闭按钮，页面只靠挤出最近 5 个关掉。点小标题折叠列表，折叠状态记在浏览器里
  const recent = read('layout/component/asideRecent.vue');
  assert.match(recent, /recentOpenedPages\(openedPages\.list\)/);
  assert.doesNotMatch(recent, /layout-aside-recent-close|onClose/);
  assert.match(recent, /<button type="button" class="layout-aside-recent-label" :aria-expanded="!collapsed" @click="onToggle">/);
  assert.match(recent, /<nav v-show="!collapsed" class="layout-aside-recent-list">/);
  assert.match(recent, /Local\.set\('asideRecentCollapsed', collapsed\.value\)/);
  assert.match(recent, /@keydown\.enter="onOpen\(page\.route\)"/);
});

test('recent pages sit right under the home menu item and look like quiet 32px rows without a selection bar', () => {
  // 菜单在"首页"那一项后面留插槽，侧栏把"最近打开"放进去；收起时不传插槽
  const vertical = read('layout/navMenu/vertical.vue');
  assert.match(vertical, /const homeIndex = computed\(\(\) => menuLists\.value\.findIndex\(\(val\) => val\.path === '\/home'\)\);/);
  assert.match(vertical, /<li v-if="\$slots\.afterHome && k === homeIndex" [^>]*role="none"><slot name="afterHome" \/><\/li>\s*<\/template>\s*<\/el-menu>/);
  assert.match(vertical, /<li v-if="\$slots\.afterHome && homeIndex < 0" [^>]*><slot name="afterHome" \/><\/li>\s*<template v-for="\(val, k\) in menuLists">/);
  const aside = read('layout/component/aside.vue');
  assert.match(aside, /<Vertical :menuList="state\.menuList">\s*<template v-if="isPanel && !isPanelCollapse" #afterHome>\s*<AsideRecent \/>\s*<\/template>\s*<\/Vertical>/);
  const recent = read('layout/component/asideRecent.vue');
  const style = recent.slice(recent.indexOf('<style'));
  assert.match(style, /&-label \{[^}]*font-size: 12px;[^}]*color: var\(--dv-text-muted\);/);
  assert.match(style, /&-item \{[^}]*height: 32px;[^}]*font-size: 13px;/);
  assert.match(style, /&\.is-current \{[^}]*\.layout-aside-recent-dot::before \{\s*background: var\(--el-color-primary\);/);
  assert.match(style, /&::before \{[^}]*border-radius: 50%;/);
  assert.doesNotMatch(style, /width: 3px/);
});

test('the sidebar holds logo, menu with recent pages, and the user block, without a menu search box', () => {
  const aside = read('layout/component/aside.vue');
  const order = ['<Logo v-if="setShowLogo" />', '<Vertical :menuList="state.menuList">', '<AsideRecent />', '<AsideUser v-if="isPanel" />'];
  const at = order.map(snippet => aside.indexOf(snippet));
  for (const [k, index] of at.entries()) assert.ok(index > 0, order[k]);
  assert.deepEqual([...at].sort((a, b) => a - b), at);
  // 菜单搜索只留顶栏右侧的搜索图标
  assert.doesNotMatch(aside, /layout-aside-search|搜索菜单|breadcrumb\/search\.vue/);
  assert.match(aside, /layout === 'defaults' \? 'layout-aside-pc-256' : 'layout-aside-pc-220'/);
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

test('the sidebar layout lays the sidebar and the main area flat against the window edges, split by a 1px divider', () => {
  const css = themeCss();
  const rule = selector => {
    const at = css.indexOf(`\n${selector} {`);
    assert.ok(at >= 0, selector);
    return css.slice(at, css.indexOf('}', at));
  };
  // 外壳不再有外边距、间隙和露出来的画布底色：侧栏、主内容区贴边满高
  assert.equal(css.includes('\n.layout-container.layout-shell {'), false);
  const shellRules = [...css.matchAll(/\n(\.layout-container\.layout-shell[^{]*)\{([^}]*)\}/g)];
  assert.ok(shellRules.length >= 8);
  for (const [, selector, body] of shellRules) assert.doesNotMatch(body, /page-gutter|radius-lg|shadow-side|shadow-1\b/, selector);
  const aside = rule('.layout-container.layout-shell .layout-aside.layout-aside-panel');
  // 分割线是不占宽度的内阴影：收起时 64px 里正好 48px 内容区，图标中线落在 32px
  for (const decl of ['padding: 12px 8px 8px;', 'border-right: none;', 'box-shadow: inset -1px 0 0 var(--dv-divider);', 'background: var(--dv-side-bg);', 'z-index: auto;']) assert.ok(aside.includes(decl), decl);
  assert.doesNotMatch(aside, /border-radius|gradient/);
  const main = rule('.layout-container.layout-shell .layout-container-view');
  for (const decl of ['background-color: var(--dv-surface);', 'overflow: hidden;']) assert.ok(main.includes(decl), decl);
  assert.doesNotMatch(main, /border-radius|box-shadow/);
  assert.match(rule('.layout-container.layout-shell .layout-container-view > .layout-header'), /position: absolute;/);
  assert.match(rule('.layout-container.layout-shell .layout-container-view .layout-main.layout-main-under-topbar'), /padding-top: var\(--dv-topbar-height\) !important;/);
  // 窄屏：侧栏是从左边贴边滑出的 280px 满高抽屉，打开时右侧投影（收起时不加，免得投影漏进窗口）
  const drawer = rule('.layout-container.layout-shell .layout-aside-panel.layout-aside-mobile');
  for (const decl of ['top: 0;', 'bottom: 0;', 'left: calc(-1 * var(--dv-aside-mobile-width));', 'width: var(--dv-aside-mobile-width);']) assert.ok(drawer.includes(decl), decl);
  assert.doesNotMatch(drawer, /box-shadow/);
  const open = rule('.layout-container.layout-shell .layout-aside-panel.layout-aside-mobile.layout-aside-mobile-open');
  for (const decl of ['left: 0;', 'box-shadow: var(--dv-shadow-drawer);']) assert.ok(open.includes(decl), decl);
  assert.match(css, /\.layout-aside-mobile-mode \{[^}]*background-color: var\(--dv-scrim\);/);
  const mainPanel = main;
  // 抽屉里的用户菜单、搜索建议、退出确认框挂在 body 上，层级从 2000 起：抽屉和遮罩要比它们低，主面板隔离自己的 z-index
  const z = selector => Number(rule(selector).match(/z-index: (\d+);/)[1]);
  assert.ok(z('.layout-container.layout-shell .layout-aside-panel.layout-aside-mobile') < 2000);
  assert.ok(z('.layout-container.layout-shell .layout-aside-mobile-mode') < z('.layout-container.layout-shell .layout-aside-panel.layout-aside-mobile'));
  assert.match(mainPanel, /isolation: isolate;/);
  // 顶栏带 z-index：菜单搜索弹窗挂到 body，免得被顶栏的层级压在页面元素下面
  const search = read('layout/navBars/breadcrumb/search.vue');
  assert.match(search, /<el-dialog\s[^>]*append-to-body\s+modal-class="layout-search-dialog"/);
  // main.ts 默认弹窗点遮罩、按 Esc 都不关；搜索没有关闭按钮，必须显式打开这两种关闭方式
  assert.match(search, /<el-dialog\s[^>]*:close-on-click-modal="true"\s+:close-on-press-escape="true"/);
  assert.match(search, /<style lang="scss">\s*\/\/[^\n]*\n\.layout-search-dialog \{/);
  // 毛玻璃画在 ::before 上：加在顶栏本身会让顶栏里的菜单搜索弹窗遮罩只剩顶栏大小
  const header = read('layout/navBars/breadcrumb/index.vue');
  const glass = header.slice(header.indexOf('&.is-glass {'), header.indexOf('</style>'));
  const before = glass.slice(glass.indexOf('&::before {'), glass.indexOf('}', glass.indexOf('&::before {')));
  assert.match(before, /backdrop-filter: var\(--dv-backdrop\);/);
  assert.match(before, /background: var\(--dv-topbar-bg\);/);
  assert.equal(glass.slice(0, glass.indexOf('&::before {')).includes('backdrop-filter'), false);
  // 顶栏平铺：底边一条分割线，没有圆角
  assert.match(glass, /border-bottom-color: var\(--dv-divider\);/);
  assert.doesNotMatch(glass, /border-radius/);
});

test('the sidebar menu is Win11-style: 36px items, 14px text and a grey selected fill without a side bar', () => {
  const css = themeCss();
  const rule = selector => {
    const at = css.indexOf(`\n${selector} {`);
    assert.ok(at >= 0, selector);
    return css.slice(at, css.indexOf('}', at));
  };
  const has = (selector, ...decls) => {
    const block = rule(selector);
    for (const decl of decls) assert.ok(block.includes(decl), `${selector} → ${decl}`);
    return block;
  };
  has('.layout-aside .el-menu', '--el-menu-item-height: 36px;', '--el-menu-sub-item-height: 32px;', '--el-menu-item-font-size: 14px;', '--el-menu-icon-width: 16px;',
    '--el-menu-base-level-padding: 12px;', '--el-menu-level-padding: 28px;', '--el-menu-active-color: var(--dv-text);', '--el-menu-hover-bg-color: var(--dv-hover) !important;');
  has('.layout-aside .el-menu .el-menu--inline .el-menu-item,\n.layout-aside .el-menu .el-menu--inline .el-sub-menu__title', 'height: var(--el-menu-sub-item-height) !important;');
  // 图标 16px（跟着组件大小缩放）、与文字间距 12px、跟文字同色；收起时没有子菜单的项的图标在提示框触发层里，也要命中
  has('.layout-aside .el-menu .el-menu-item > i,\n.layout-aside .el-menu .el-menu-item > .el-menu-tooltip__trigger > i,\n.layout-aside .el-menu .el-sub-menu__title > i:not(.el-sub-menu__icon-arrow)',
    'width: var(--el-menu-icon-width);', 'margin: 0 12px 0 0;', 'font-size: calc(16px * var(--dv-icon-scale)) !important;', 'color: inherit;');
  // 子菜单展开、收起没有高度动画
  has('.layout-aside .el-menu .el-collapse-transition-enter-active,\n.layout-aside .el-menu .el-collapse-transition-leave-active,\n.layout-aside .el-menu .el-sub-menu__icon-arrow', 'transition: none;');
  // 选中：正文色 600 字重，选中灰底来自菜单高亮背景色，不再是凸起白块
  const selected = '.layout-aside .el-menu .el-menu-item.is-active,\n.layout-aside .el-menu .el-sub-menu.is-active:not(.is-opened) > .el-sub-menu__title';
  assert.doesNotMatch(has(selected, 'color: var(--dv-text);', 'font-weight: 600;'), /box-shadow/);
  assert.match(css, /--next-bg-menuBarActiveColor: var\(--dv-selected\);/);
  assert.match(css, /\n\.el-menu-hover-bg-color, \.el-menu-item\.is-active,\s*\.el-sub-menu\.is-active \.el-sub-menu__title \{\s*background-color: var\(--next-bg-menuBarActiveColor\) !important;/);
  // 选中项只靠灰底和字重，侧栏和收起时弹出的子菜单都不画侧边竖线
  assert.doesNotMatch(css, /\.el-menu-item\.is-active::before|\.el-sub-menu__title::before/);
});

test('the collapsed sidebar centres every icon on the 64px column', () => {
  const css = themeCss();
  const rule = selector => {
    const at = css.indexOf(`\n${selector} {`);
    assert.ok(at >= 0, selector);
    return css.slice(at, css.indexOf('}', at));
  };
  // Element Plus 收起时把没有子菜单的项的图标放进铺满整项、自带左右内边距、内容靠左的提示框触发层：
  // 只把 li 居中不够（V2 的问题），触发层也要居中、去掉内边距
  const centred = rule('.layout-aside .el-menu.el-menu--collapse > .el-menu-item,\n.layout-aside .el-menu.el-menu--collapse > .el-menu-item > .el-menu-tooltip__trigger,\n.layout-aside .el-menu.el-menu--collapse > .el-sub-menu > .el-sub-menu__title');
  assert.match(centred, /justify-content: center;/);
  assert.match(centred, /padding: 0 !important;/);
  assert.match(rule('.layout-aside .el-menu.el-menu--collapse > .el-menu-item > i,\n.layout-aside .el-menu.el-menu--collapse > .el-menu-item > .el-menu-tooltip__trigger > i,\n.layout-aside .el-menu.el-menu--collapse > .el-sub-menu > .el-sub-menu__title > i:not(.el-sub-menu__icon-arrow)'), /margin-right: 0;/);
  // 64px 侧栏左右各 8px 内边距，菜单、用户区都在 48px 宽的内容区里居中，中线正好在 32px
  assert.match(css, /\.layout-aside-pc-64 \{\s*width: 64px !important;/);
  const aside = read('layout/component/aside.vue');
  const collapse = aside.slice(aside.indexOf('&.is-collapse {'));
  assert.match(collapse, /:deep\(\.layout-aside-user\) \{\s*flex-direction: column;[^}]*padding: 8px 0 0;/);
  assert.match(read('layout/component/asideUser.vue'), /\.layout-aside-user \{\s*display: flex;\s*align-items: center;/);
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
  // 侧边栏布局：外壳贴边，可用高度 = 窗口高 - 顶栏 - 页脚（宽窄屏一样，不再扣页面间距）
  assert.match(css, /\.layout-container\.layout-shell \.layout-container-view \.layout-main \{[^}]*--dv-main-height: calc\(100vh - var\(--dv-topbar-height\) - var\(--dv-footer-height\)\);/);
  assert.equal((css.match(/--dv-main-height: calc\(100vh - var\(--dv-topbar-height\)/g) || []).length, 1);
  assert.match(css, /\.layout-container \.layout-main \{\s*--dv-main-height: calc\(100vh - 85px - var\(--dv-footer-height\)\);/);
  assert.match(css, /\.layout-container \.layout-main\.layout-main-no-footer \{\s*--dv-footer-height: 0px;/);
  assert.match(read('layout/footer/index.vue'), /height: var\(--dv-footer-height\);/);
  assert.match(read('layout/component/main.vue'), /'layout-main-no-footer': !isFooter/);
});
