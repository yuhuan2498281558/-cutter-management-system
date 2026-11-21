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

test('project and shield machine options request up to 999 records', () => {
  assert.equal(columns.project.dict.url, '/api/shield/project/');
  assert.equal(columns.project.dict.label, 'project_name');
  assert.deepEqual(plain(columns.project.dict.params ?? null), { limit: 999 });
  assert.equal(columns.shield_machine.dict.url, '/api/shield/shield_machine_basic_info/');
  assert.equal(columns.shield_machine.dict.label, 'shield_model');
  assert.deepEqual(plain(columns.shield_machine.dict.params ?? null), { limit: 999 });
});

test('every remote dictionary on the page asks for the full list', () => {
  const remote = Object.entries(columns).filter(([, column]) => column.dict?.url);

  assert.equal(remote.length, 2);
  for (const [key, column] of remote) {
    assert.deepEqual(plain(column.dict.params ?? null), { limit: 999 }, key);
  }
});
