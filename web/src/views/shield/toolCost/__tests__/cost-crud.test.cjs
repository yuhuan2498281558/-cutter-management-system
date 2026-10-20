const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { compile, plain } = require('../../analysis/__tests__/helpers.cjs');

const source = fs.readFileSync(path.resolve(__dirname, '../crud.tsx'), 'utf8');

function load({ toolInfoId = '7' } = {}) {
  const calls = [];
  const api = Object.fromEntries(['GetList', 'AddObj', 'UpdateObj', 'DelObj'].map(name => [name, async arg => {
    calls.push([name, plain(arg)]);
    return { code: 2000 };
  }]));
  const moduleUnderTest = compile(source, name => {
    if (name === './api') return api;
    if (name === '@fast-crud/fast-crud') return { dict: value => value, compute: fn => ({ computeFn: fn }) };
    if (name === '../crudUtils') return { createIndexFormatter: () => () => 1 };
    if (name === 'vue-router') return { useRoute: () => ({ query: { tool_info_id: toolInfoId } }) };
    throw new Error(`Unexpected import ${name}`);
  });
  const { crudOptions } = moduleUnderTest.createCrudOptions({ crudExpose: {} });
  return { crudOptions, columns: crudOptions.columns, calls };
}

test('switching an existing repair record to NEW_TOOL sends an empty repair_parts list', () => {
  const { columns } = load();
  const form = { id: 1, cost_type: 'NEW_TOOL', repair_parts: ['刀圈', '轴承'] };

  columns.cost_type.form.valueChange({ value: 'NEW_TOOL', form });

  assert.deepEqual(plain(form.repair_parts), []);
  assert.deepEqual(JSON.parse(JSON.stringify(form)), { id: 1, cost_type: 'NEW_TOOL', repair_parts: [] });
});

test('switching to REPAIR keeps the chosen repair parts', () => {
  const { columns } = load();
  const form = { cost_type: 'REPAIR', repair_parts: ['密封件'] };

  columns.cost_type.form.valueChange({ value: 'REPAIR', form });

  assert.deepEqual(form.repair_parts, ['密封件']);
});

test('repair parts are only shown and required for REPAIR', () => {
  const { columns } = load();
  const { show, rules } = columns.repair_parts.form;

  assert.equal(show.computeFn({ form: { cost_type: 'REPAIR' } }), true);
  assert.equal(show.computeFn({ form: { cost_type: 'NEW_TOOL' } }), false);
  assert.equal(rules[0].required.computeFn({ form: { cost_type: 'REPAIR' } }), true);
  assert.equal(rules[0].required.computeFn({ form: { cost_type: 'NEW_TOOL' } }), false);
});

test('unit price shows yuan with two decimals and keeps zero', () => {
  const format = load().columns.unit_price.column.formatter;

  assert.equal(format({ value: 0 }), '¥0.00');
  assert.equal(format({ value: '12.5' }), '¥12.50');
  assert.equal(format({ value: 1234.567 }), '¥1234.57');
  assert.equal(format({ value: null }), '-');
  assert.equal(format({ value: undefined }), '-');
});

test('repair parts column joins the list and shows - when empty', () => {
  const format = load().columns.repair_parts.column.formatter;

  assert.equal(format({ value: ['刀圈', '轴承'] }), '刀圈, 轴承');
  assert.equal(format({ value: [] }), '-');
  assert.equal(format({ value: undefined }), '-');
  assert.equal(format({ value: null }), '-');
  assert.equal(format({ value: '刀圈' }), '-');
});

test('list and create are scoped to the tool_info_id in the URL', async () => {
  const { crudOptions, calls } = load({ toolInfoId: '7' });

  await crudOptions.request.pageRequest({ page: 1, limit: 20 });
  await crudOptions.request.addRequest({ form: { cost_type: 'NEW_TOOL', unit_price: 100 } });
  await crudOptions.request.editRequest({ form: { cost_type: 'NEW_TOOL', repair_parts: [] }, row: { id: 3 } });
  await crudOptions.request.delRequest({ row: { id: 3 } });

  assert.deepEqual(calls, [
    ['GetList', { page: 1, limit: 20, tool_info: '7' }],
    ['AddObj', { cost_type: 'NEW_TOOL', unit_price: 100, tool_info: '7' }],
    ['UpdateObj', { cost_type: 'NEW_TOOL', repair_parts: [], id: 3 }],
    ['DelObj', 3],
  ]);
});
