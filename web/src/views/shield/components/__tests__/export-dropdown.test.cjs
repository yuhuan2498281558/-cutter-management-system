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

// Mirrors the display side of the fast-crud 1.20.2 Dict class: dataMap keyed by value, getNodeByValue and getLabel.
// Remote lookups and reloads are recorded so tests can prove export never triggers them.
function dict({ data = [], value = 'value', label = 'label' } = {}) {
  const requests = [];
  return {
    value, label, requests,
    dataMap: Object.fromEntries(data.map(item => [item[value], item])),
    getNodeByValue(key) { return this.dataMap[key]; },
    getLabel(node) { return node[this.label]; },
    getNodesByValues(values) { requests.push(values); return []; },
    loadDict() { requests.push('load'); },
  };
}

// fast-crud 1.20.2 table columns: the column sub-config plus title and key; dict-select columns
// carry the dict on component.dict and have no formatter.
function dictColumn(title, key, options) {
  return { title, key, component: { name: 'fs-values-format', vModel: 'modelValue', dict: dict(options) } };
}

function binding() {
  return {
    data: [{ warehouse_id: 'TEST-1', summary_status: 'CONFIRMED', duration: 0 }],
    table: { columns: {
      _index: { title: '序号', key: '_index' },
      warehouse_id: { title: '开仓编号', key: 'warehouse_id', formatter: ({ value, row, index }) => `${value} / ${row.summary_status} / ${index}` },
      summary_status: dictColumn('汇总状态', 'summary_status', { data: [{ value: 'CONFIRMED', label: '已确认' }, { value: 'DRAFT', label: '待确认' }] }),
      duration: { title: '持续时间（小时）', key: 'duration' },
      hidden: { title: '隐藏字段', key: 'hidden', show: false },
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
  assert.equal(calls[0].columns[0].formatter(crudBinding.data[0], 0), 'TEST-1 / CONFIRMED / 0');
  assert.equal(calls[0].columns[1].formatter(crudBinding.data[0], 0), '已确认');
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

test('dict columns without a formatter export the labels shown in the table', () => {
  const tools = dictColumn('刀具类型', 'tool_type', { data: [{ value: 'DISC', label: '滚刀' }, { value: 'SCRAPER', label: '刮刀' }] });
  const machine = dictColumn('所属盾构机', 'shield_machine', { value: 'id', label: 'shield_model', data: [{ id: 7, shield_model: '盾构机 A' }] });
  const statusWithFormatter = { ...dictColumn('汇总状态', 'summary_status', { data: [{ value: 'CONFIRMED', label: '已确认' }] }), formatter: ({ value }) => `状态：${value}` };
  const crudBinding = { data: [{ tool_type: ['DISC', 'SCRAPER'], shield_machine: 7, summary_status: 'CONFIRMED' }], table: { columns: { tool_type: tools, shield_machine: machine, summary_status: statusWithFormatter } } };
  const { state, calls } = setup({ title: '刀具类型', crudBinding });
  state.handleCommand('csv');
  const row = crudBinding.data[0];
  assert.deepEqual(Array.from(calls[0].columns, column => column.formatter(row, 0)), ['滚刀、刮刀', '盾构机 A', '状态：CONFIRMED']);
  for (const column of [tools, machine, statusWithFormatter]) assert.deepEqual(column.component.dict.requests, []);
});

test('dict values missing from loaded dict data keep their original value', () => {
  const status = dictColumn('汇总状态', 'summary_status', { data: [{ value: 'CONFIRMED', label: '已确认' }] });
  const notLoaded = dictColumn('所属盾构机', 'shield_machine', { value: 'id', label: 'shield_model' });
  const crudBinding = { data: [
    { summary_status: 'ARCHIVED', shield_machine: 9 },
    { summary_status: ['CONFIRMED', 'UNKNOWN'], shield_machine: null },
  ], table: { columns: { summary_status: status, shield_machine: notLoaded } } };
  const { state, calls } = setup({ title: '开仓信息', crudBinding });
  state.handleCommand('excel');
  const cells = crudBinding.data.map((row, index) => Array.from(calls[0].columns, column => column.formatter(row, index)));
  assert.deepEqual(cells, [['ARCHIVED', 9], ['已确认、UNKNOWN', null]]);
  assert.deepEqual(notLoaded.component.dict.requests, []);
});
