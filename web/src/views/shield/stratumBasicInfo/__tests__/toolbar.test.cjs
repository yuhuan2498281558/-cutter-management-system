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
test('toolbar hides the backend export button and 新增; exporting is the only page action', () => {
  const { buttons } = crudOptions.actionbar;

  assert.deepEqual(plain(buttons.export), { show: false });
  assert.deepEqual(plain(buttons.add), { show: false });
  const page = fs.readFileSync(path.resolve(__dirname, '../index.vue'), 'utf8');
  assert.match(page, /<ExportDropdown /);
  assert.doesNotMatch(page, /从PDF提取地层|下载模板|el-upload/);
});

// Without search fields the 查询 button had nothing to submit; the ring range goes to the backend as ring_start/ring_end.
test('search offers project and a ring range, and the range fields stay out of the table and form', () => {
  const searchable = Object.entries(crudOptions.columns)
    .filter(([, column]) => column.search?.show)
    .sort(([, a], [, b]) => a.search.order - b.search.order)
    .map(([key, column]) => [key, column.title]);
  assert.deepEqual(searchable, [['project', '所属项目'], ['ring_start', '起始环号'], ['ring_end', '结束环号']]);
  for (const key of ['ring_start', 'ring_end']) {
    assert.equal(crudOptions.columns[key].type, 'text', `${key} must use a field type fast-crud renders in search`);
    assert.equal(crudOptions.columns[key].column.show, false);
    assert.equal(crudOptions.columns[key].form.show, false);
  }
});
