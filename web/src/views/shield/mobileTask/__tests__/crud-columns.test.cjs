// Desktop mobile-task list columns, built from the actual crud.tsx with stubbed imports.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const compiled = ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../crud.tsx'), 'utf8'), {
  fileName: 'crud.tsx',
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.Preserve },
}).outputText;

function loadColumns() {
  const remoteDicts = [];
  const context = {
    exports: {},
    require(name) {
      if (name === './api') return {};
      if (name === '@fast-crud/fast-crud') return { dict: config => { remoteDicts.push(config); return config; } };
      throw new Error(`Unexpected import: ${name}`);
    },
  };
  vm.runInNewContext(compiled, context);
  const { crudOptions } = context.exports.createCrudOptions({ crudExpose: {} });
  return { columns: crudOptions.columns, remoteDicts };
}

test('the list keeps the opening number column and no longer loads the opening dictionary', () => {
  const { columns, remoteDicts } = loadColumns();
  assert.equal('warehouse' in columns, false);
  assert.deepEqual(remoteDicts, []);
  assert.equal(columns.warehouse_id_name.title, '开仓编号');
  assert.equal(columns.warehouse_id_name.column.show, undefined);
});
