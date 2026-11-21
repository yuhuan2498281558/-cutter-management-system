const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { compile, plain } = require('../../analysis/__tests__/helpers.cjs');

const source = fs.readFileSync(path.resolve(__dirname, '../crud.tsx'), 'utf8');
const { columns } = compile(source, name => {
  if (name === './api') return {};
  if (name === '@fast-crud/fast-crud') return { dict: value => value };
  if (name === '../crudUtils') return { createIndexFormatter: () => () => 1 };
  throw new Error(`Unexpected import ${name}`);
}).createCrudOptions({ crudExpose: {} }).crudOptions;

test('tool type options request up to 999 tools', () => {
  const { dict } = columns.tool_info;

  assert.equal(dict.url, '/api/shield/tool_info/');
  assert.equal(dict.label, 'tool_type_name');
  assert.equal(dict.value, 'id');
  assert.deepEqual(plain(dict.params ?? null), { limit: 999 });
});

test('every remote dictionary on the page asks for the full list', () => {
  const remote = Object.entries(columns).filter(([, column]) => column.dict?.url);

  assert.ok(remote.length > 0);
  for (const [key, column] of remote) {
    assert.deepEqual(plain(column.dict.params ?? null), { limit: 999 }, key);
  }
});
