const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const sass = require('sass');

const themeDir = path.resolve(__dirname, '..');
const css = sass.compile(path.resolve(themeDir, 'index.scss'), { style: 'expanded', loadPaths: [themeDir] }).css;
// 取一条规则的声明块；选择器按编译后的原文写（Sass 把顶层的多个选择器写成逗号加换行，嵌套出来的写成逗号加空格）
const rule = selector => {
  const at = css.indexOf(`\n${selector} {`);
  assert.ok(at >= 0, `missing rule: ${selector}`);
  return css.slice(at, css.indexOf('}', at));
};
const has = (selector, ...declarations) => {
  const block = rule(selector);
  for (const declaration of declarations) assert.ok(block.includes(declaration), `${selector} → ${declaration}`);
};

test('component rules take colours only from variables', () => {
  for (const file of ['element.scss', 'fastCrud.scss']) {
    const source = fs.readFileSync(path.resolve(themeDir, file), 'utf8').replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
    assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, file);
  }
});

test('buttons: 34px terracotta primary with a raised shadow, plain default, terracotta link text', () => {
  assert.match(css, /--el-component-size: var\(--dv-control-height\);/);
  has('.el-button:not(.el-button--large, .el-button--small, .is-link)', 'height: var(--dv-control-height);', 'padding: 0 14px;');
  has('.el-button--small:not(.is-link)', '--el-button-size: var(--dv-control-height-sm);', 'font-size: 12.5px;', 'border-radius: var(--dv-radius-sm);');
  has('.el-button:not(.el-button--primary, .el-button--success, .el-button--warning, .el-button--danger, .el-button--info, .el-button--text):not(.is-text, .is-link, .is-disabled)', 'box-shadow: var(--dv-shadow-button-plain);');
  has('.el-button:not(.el-button--primary, .el-button--success, .el-button--warning, .el-button--danger, .el-button--info, .el-button--text)', '--el-button-border-color: var(--dv-border-strong);', '--el-button-hover-bg-color: var(--dv-hover);');
  has('.el-button--primary:not(.is-plain, .is-text, .is-link):not(.is-disabled)', 'box-shadow: var(--dv-shadow-button);');
  has('.el-button--primary:not(.is-plain, .is-text, .is-link)', '--el-button-text-color: var(--dv-on-primary);', '--el-button-hover-bg-color: var(--dv-primary-hover);');
  // 链接、文字按钮：默认和主色类型陶土色链接字，状态色类型不动
  assert.match(css, /\.el-button\.is-text:not\(\.el-button--success, \.el-button--warning, \.el-button--danger, \.el-button--info\) \{\s*--el-button-text-color: var\(--dv-accent-strong\);/);
  assert.match(css, /\.el-button--text:not\(\.is-disabled\):active \{\s*color: var\(--dv-accent-strong\);/);
});

test('inputs and selects: strong border, accent focus ring with a soft halo', () => {
  has('.el-input,\n.el-textarea,\n.el-date-editor', '--el-input-border-color: var(--dv-border-strong);', '--el-input-focus-border-color: var(--dv-accent);');
  assert.match(css, /\.el-input__wrapper\.is-focus,[\s\S]*?\{\s*box-shadow: 0 0 0 1px var\(--dv-accent\) inset, 0 0 0 3px var\(--dv-accent-soft\);/);
  has('.el-select__wrapper', 'min-height: var(--dv-control-height);', 'box-shadow: 0 0 0 1px var(--dv-border-strong) inset;');
  has('.el-select__wrapper.is-focused', 'box-shadow: 0 0 0 1px var(--dv-accent) inset, 0 0 0 3px var(--dv-accent-soft);');
});

test('segmented control: radio-button groups and dv-segmented tabs share the fill track and raised selection', () => {
  has('.el-radio-group:has(> .el-radio-button)', 'padding: 3px;', 'gap: 2px;', 'border-radius: var(--dv-radius-seg);', 'background-color: var(--dv-fill);');
  has('.el-radio-button .el-radio-button__inner', 'height: 28px;', 'padding: 0 11px;', 'border-radius: var(--dv-radius-sm) !important;', 'color: var(--dv-text-secondary);', 'font-size: 12.5px;');
  has('.el-radio-button.is-active .el-radio-button__inner', 'background-color: var(--dv-surface);', 'color: var(--dv-text);', 'box-shadow: var(--dv-shadow-1) !important;');
  has('.el-radio-button.el-radio-button--small .el-radio-button__inner', 'height: 24px;', 'border-radius: var(--dv-radius-seg-sm) !important;', 'font-size: 12px;');
  has('.el-tabs.dv-segmented > .el-tabs__header .el-tabs__nav', 'padding: 3px;', 'border-radius: var(--dv-radius-seg);', 'background-color: var(--dv-fill);');
  has('.el-tabs.dv-segmented > .el-tabs__header .el-tabs__item.is-active', 'background-color: var(--dv-surface);', 'box-shadow: var(--dv-shadow-1);');
});

test('tags: 22px badges with soft status backgrounds, neutral default and neutral select chips', () => {
  has('.el-tag', '--el-tag-border-radius: var(--dv-radius-badge);', 'font-weight: 500;');
  has('.el-tag:not(.el-tag--small, .el-tag--large)', 'height: 22px;', 'padding: 0 8px;');
  has('.el-tag:not(.el-tag--dark, .el-tag--plain)', '--el-tag-bg-color: var(--dv-fill);', '--el-tag-text-color: var(--dv-text-secondary);');
  for (const type of ['success', 'warning', 'danger', 'info']) has(`.el-tag:not(.el-tag--dark, .el-tag--plain).el-tag--${type}`, `--el-tag-bg-color: var(--dv-${type}-bg);`, `--el-tag-text-color: var(--dv-${type}-text);`);
  has('.el-select .el-tag:not(.el-tag--dark, .el-tag--plain),\n.el-cascader .el-tag:not(.el-tag--dark, .el-tag--plain)', '--el-tag-bg-color: var(--dv-fill);', '--el-tag-text-color: var(--dv-text-secondary);');
});

test('tables: framed with a large radius, tile header, 48px rows and an accent bar on the current row', () => {
  has('.el-table', '--el-table-header-bg-color: var(--dv-tile);', '--el-table-header-text-color: var(--dv-text-secondary);', '--el-table-current-row-bg-color: var(--dv-accent-soft);', 'border: 1px solid var(--dv-border);', 'border-radius: var(--dv-radius-table);');
  has('.el-table th.el-table__cell', 'font-size: 12px;', 'font-weight: 500;');
  has('.el-table .el-table__body tr:last-child > td.el-table__cell', 'border-bottom: none;');
  has('.el-table .el-table__cell:first-child .cell', 'padding-left: 20px;');
  has('.el-table .el-table__body tr.current-row > td.el-table__cell:first-child', 'box-shadow: inset 3px 0 0 var(--dv-accent);');
  has('.el-table--default .el-table__body td.el-table__cell', 'padding: 12px 0;');
  // fast-crud 写死的浅蓝当前行换成同一个变量
  has('.fs-crud-table tr.fs-current-row', 'background-color: var(--el-table-current-row-bg-color);');
});

test('cards are flat tiles; dialogs, drawers and popovers use the large radii and the overlay shadow', () => {
  // 卡片边线跟着配色：暖白不画（宽 0，和 V2 一样不占位置），灰白蓝 1px 灰线；两套都不加阴影
  has('.el-card', '--el-card-bg-color: var(--dv-card-bg);', '--el-card-border-radius: var(--dv-radius-card);', 'border: var(--dv-card-border-width) solid var(--dv-card-border);');
  has('.el-card__header', 'padding: 20px 22px 0;', 'border-bottom: none;');
  has('.el-card__body', 'padding: 20px 22px;');
  has('.el-dialog', '--el-dialog-border-radius: var(--dv-radius-xl);', '--el-dialog-box-shadow: var(--dv-shadow-overlay);');
  has('.el-dialog .el-dialog__title', 'font-family: var(--dv-font-title);');
  assert.doesNotMatch(css, /\.el-dialog \.el-dialog__(header|footer) \{\s*border-(bottom|top): 1px/);
  has('.el-message-box .el-message-box__title', 'font-family: var(--dv-font-title);');
  has('.el-drawer', 'border-radius: var(--dv-radius-xl);', 'box-shadow: var(--dv-shadow-overlay);');
  has('.el-drawer.rtl, .el-drawer.ltr','top: var(--dv-page-gutter);', 'bottom: var(--dv-page-gutter);', 'height: auto;');
  has('.el-drawer.rtl', 'right: var(--dv-page-gutter);');
  has('.el-drawer .el-drawer__title', 'font-family: var(--dv-font-title);');
  has('.el-drawer .el-drawer__footer', 'border-top: 1px solid var(--el-border-color);');
  has('.el-popper.is-light', '--el-popper-border-radius: var(--dv-radius-popover);', 'box-shadow: var(--dv-shadow-overlay);');
  has('.el-select-dropdown__item.is-selected', 'color: var(--dv-accent-strong);');
  has('.el-dropdown-menu .el-dropdown-menu__item', 'border-radius: var(--dv-radius-sm);');
});

test('toasts are dark, pagination and focus use the terracotta family, and serif title helpers exist', () => {
  has(".el-message,\n.el-message[class*=el-message--]", '--el-message-bg-color: var(--dv-text);', '--el-message-text-color: var(--dv-surface);');
  has('.el-message', 'border-radius: var(--dv-radius-toast);', 'box-shadow: var(--dv-shadow-overlay);');
  assert.match(css, /\.el-pagination\.is-background \.el-pager li\.is-active \{\s*background-color: var\(--el-color-primary\) !important;\s*color: var\(--dv-on-primary\) !important;/);
  has('.el-pagination', '--el-pagination-button-color: var(--el-text-color-secondary);', '--el-pagination-border-radius: var(--dv-radius-sm);');
  has(":focus-visible:not(input, textarea, [tabindex=\"-1\"])", 'outline: 2px solid var(--dv-accent) !important;', 'outline-offset: 2px;');
  has('.dv-page-title', 'font-family: var(--dv-font-title);', 'font-size: 24px;', 'font-weight: 600;', 'line-height: 1.25;');
  has('.dv-section-title', 'font-family: var(--dv-font-title);', 'font-size: 19px;', 'font-weight: 600;');
  // 标题一律走 --dv-font-title（暖白衬线、灰白蓝无衬线），不直接写衬线
  assert.doesNotMatch(css, /font-family: var\(--dv-font-serif\)/);
  assert.match(fs.readFileSync(path.resolve(themeDir, '..', 'layout/logo/index.vue'), 'utf8'), /&__title \{\s*font-family: var\(--dv-font-title\);/);
});
