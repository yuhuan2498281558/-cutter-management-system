const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');

function setup(props) {
  const filename = process.env.EXPORT_DROPDOWN_TEST_FILE || path.resolve(__dirname, '../ExportDropdown.vue');
  const { descriptor } = parse(fs.readFileSync(filename, 'utf8'));
  const script = compileScript(descriptor, { id: 'export-dropdown-test' });
  const calls = [], warnings = [];
  const context = { exports: {}, require(name) {
    if (name === 'vue') return vue;
    if (name === '@element-plus/icons-vue') return { Download: {} };
    if (name === 'element-plus') return { ElMessage: { warning: text => warnings.push(text) } };
    if (name === '../utils/export') return { exportTableData: options => calls.push(options) };
    throw new Error(`Unexpected import: ${name}`);
  } };
  vm.runInNewContext(ts.transpileModule(script.content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, context);
  const state = context.exports.default.setup(props, { expose() {} });
  return { state, calls, warnings };
}

function binding() {
  return {
    data: [{ warehouse_id: 'TEST-1', summary_status: 'CONFIRMED', duration: 0 }],
    table: { columns: {
      _index: { title: '序号' },
      warehouse_id: { title: '开仓编号' },
      summary_status: { title: '汇总状态', formatter: ({ value, row, index }) => `${value === 'CONFIRMED' ? '已确认' : '待确认'} / ${row.warehouse_id} / ${index}` },
      duration: { title: '持续时间（小时）' },
      hidden: { title: '隐藏字段', show: false },
    } },
  };
}

test('template-unwrapped Fast-CRUD binding exports its data and actual table columns', () => {
  const crudBinding = vue.reactive(binding());
  const before = JSON.stringify(crudBinding);
  const { state, calls } = setup({ title: '开仓明细', crudBinding });
  state.handleCommand('csv');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].rows, crudBinding.data);
  assert.deepEqual(Array.from(calls[0].columns, column => column.key), ['warehouse_id', 'summary_status', 'duration']);
  assert.deepEqual(Array.from(calls[0].columns, column => column.title), ['开仓编号', '汇总状态', '持续时间（小时）']);
  assert.equal(calls[0].columns[1].formatter(crudBinding.data[0], 0), '已确认 / TEST-1 / 0');
  assert.equal(calls[0].columns[2].formatter(crudBinding.data[0], 0), 0);
  assert.equal(JSON.stringify(crudBinding), before);
});

test('ref bindings and replacement data remain reactive', () => {
  const crudBinding = vue.ref(binding());
  const { state } = setup({ title: '开仓明细', crudBinding });
  assert.equal(state.exportRows.value.length, 1);
  crudBinding.value = { ...binding(), data: [] };
  assert.equal(state.exportRows.value.length, 0);
  crudBinding.value = binding();
  assert.equal(state.exportColumns.value.length, 3);
  assert.equal(state.exportRows.value.length, 1);
});

test('empty or missing bindings do not trigger a download', () => {
  for (const crudBinding of [undefined, {}, { data: [], table: { columns: {} } }]) {
    const { state, calls, warnings } = setup({ title: '开仓明细', crudBinding });
    state.handleCommand('csv');
    assert.equal(calls.length, 0);
    assert.equal(warnings.length, 1);
  }
});

test('explicit detail rows, columns, metadata and filename keep precedence', () => {
  const rows = [{ position: '80A' }], columns = [{ key: 'position', title: '刀位号' }];
  const meta = [{ label: '换刀环号', value: 100 }];
  const { state, calls } = setup({ title: '明细', filename: 'detail-all', rows, columns, meta, crudBinding: binding() });
  state.handleCommand('pdf');
  assert.equal(calls[0].rows, rows);
  assert.equal(calls[0].columns, columns);
  assert.equal(calls[0].meta, meta);
  assert.equal(calls[0].filename, 'detail-all');
  assert.equal(calls[0].format, 'pdf');
});

test('explicit empty detail rows never fall back to unrelated CRUD data', () => {
  const { state, calls } = setup({ title: '明细', rows: [], crudBinding: binding() });
  state.handleCommand('excel');
  assert.equal(calls.length, 0);
});
