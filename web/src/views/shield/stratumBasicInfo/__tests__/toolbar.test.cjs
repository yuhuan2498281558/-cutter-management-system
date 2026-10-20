const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vue = require('vue');
const { compile, plain } = require('../../analysis/__tests__/helpers.cjs');

const source = fs.readFileSync(path.resolve(__dirname, '../crud.tsx'), 'utf8');
const { crudOptions } = compile(source, name => {
  if (name === 'vue') return vue;
  if (name === '@fast-crud/fast-crud') return { dict: value => value };
  if (name === '../crudUtils') return { createIndexFormatter: () => () => 1 };
  if (name === './api' || name === '/@/utils/service') return {};
  throw new Error(`Unexpected import ${name}`);
}).createCrudOptions({ crudExpose: {} });

// The global actionbar in settings.ts adds a click-less 导出 button for users with :Export permission,
// so this page hides it explicitly; exporting goes through the ExportDropdown in index.vue.
test('toolbar hides the backend export button and keeps 新增', () => {
  const { buttons } = crudOptions.actionbar;

  assert.deepEqual(plain(buttons.export), { show: false });
  assert.equal(buttons.add.show, true);
  assert.equal(buttons.add.text, '新增');
});
