// Run from web: node --test src/views/shield/toolChangeDetail/__tests__/*.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');

function run(source, requireModule = require) {
  const context = { exports: {}, require: requireModule };
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  });
  vm.runInNewContext(compiled.outputText, context);
  return context.exports;
}
const helpers = run(fs.readFileSync(path.resolve(__dirname, '../tablePresentation.ts'), 'utf8'));
const { repairStatus, matchesDetailFilters } = helpers;
const rows = [
  { cutter_position_no: '1', tool_number: 'BASE-1', is_checked: false, is_replaced: false },
  { cutter_position_no: '80A', tool_number: '', is_checked: true, is_replaced: false },
  { cutter_position_no: 'S1L', tool_number: 'NEW-3', is_checked: true, is_replaced: true },
  ...['PENDING_VENDOR_FEEDBACK', 'CONFIRMED', 'CLOSED', 'UNRECOGNIZED'].map((status, i) => ({
    cutter_position_no: String(i + 4), tool_number: `NEW-${i + 4}`, is_checked: true, is_replaced: true,
    old_tool_record_data: { inspection_status: status },
  })),
];
const select = (check = 'ALL', repair = 'ALL', query = '') => rows.filter(row => matchesDetailFilters(row, check, repair, query));

test('repair states distinguish absent records, vendor feedback, confirmation, archive and unknown', () => {
  assert.deepEqual(rows.map(repairStatus), ['NOT_REPLACED', 'NOT_REPLACED', 'UNRECORDED', 'PENDING_VENDOR_FEEDBACK', 'CONFIRMED', 'CLOSED', 'UNKNOWN']);
  assert.equal(repairStatus({ is_replaced: true, old_tool_record_data: {} }), 'UNKNOWN');
});
test('default filter preserves all rows and original order', () => assert.deepEqual(select(), rows));
test('check filters distinguish unchecked, checked without replacement and replaced', () => {
  assert.deepEqual(select('UNCHECKED'), [rows[0]]);
  assert.deepEqual(select('CHECKED_ONLY'), [rows[1]]);
  assert.deepEqual(select('REPLACED'), rows.slice(2));
});
test('each repair filter returns only its corresponding status', () => {
  for (const status of Object.keys(helpers.repairLabels)) {
    assert.deepEqual(select('ALL', status), rows.filter(row => repairStatus(row) === status));
  }
});
test('search accepts alphanumeric positions and stored numbers without generating identifiers', () => {
  assert.deepEqual(select('ALL', 'ALL', ' 80a '), [rows[1]]);
  assert.deepEqual(select('ALL', 'ALL', 's1l'), [rows[2]]);
  assert.deepEqual(select('ALL', 'ALL', 'new-4'), [rows[3]]);
  assert.equal(matchesDetailFilters({}, 'ALL', 'ALL', 'missing'), false);
});
test('combined filters use intersection and handle zero results', () => {
  assert.deepEqual(select('REPLACED', 'PENDING_VENDOR_FEEDBACK', 'new-4'), [rows[3]]);
  assert.deepEqual(select('UNCHECKED', 'CLOSED'), []);
  assert.deepEqual(select('ALL', 'ALL', 'not-present'), []);
});
test('filtering never mutates original rows or creates replacement row objects', () => {
  const original = JSON.stringify(rows);
  for (const row of rows) Object.freeze(row);
  assert.equal(select('REPLACED', 'UNRECORDED')[0], rows[2]);
  assert.equal(JSON.stringify(rows), original);
});

const source = fs.readFileSync(path.resolve(__dirname, '../index.vue'), 'utf8');
const { descriptor, errors } = parse(source);
const script = compileScript(descriptor, { id: 'detail-presentation-test' });
test('updated Vue template compiles', () => {
  assert.deepEqual(errors, []);
  assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename: 'index.vue', id: 'detail-presentation-test', compilerOptions: { bindingMetadata: script.bindings, expressionPlugins: ['typescript'] } }).errors, []);
});
function setup(t, mode = 'supplement') {
  const scope = vue.effectScope();
  const compiled = run(script.content, name => {
    if (name === 'vue') return { ...vue, onMounted() {} };
    if (name === 'vue-router') return { useRoute: () => ({ query: { mode } }), useRouter: () => ({}) };
    if (name === './tablePresentation') return helpers;
    if (name === '/@/utils/service') return { request: () => { throw new Error('Unexpected API call'); } };
    if (name === 'element-plus') return { ElMessage: {} };
    if (name.endsWith('.vue')) return {};
    throw new Error(`Unexpected import: ${name}`);
  });
  const state = scope.run(() => compiled.default.setup({}, { expose() {} }));
  t.after(() => scope.stop());
  state.tableData.value = [...rows];
  return state;
}
test('actual controller filters reactively and reset restores full export source', t => {
  const s = setup(t);
  s.checkFilter.value = 'REPLACED';
  s.repairFilter.value = 'CONFIRMED';
  s.searchText.value = 'new-5';
  assert.equal(s.filteredTableData.value.length, 1);
  assert.equal(s.filteredTableData.value[0].tool_number, 'NEW-5');
  assert.equal(s.tableData.value.length, 7);
  s.resetFilters();
  assert.equal(s.filteredTableData.value.length, 7);
  assert.equal(s.searchText.value, '');
  assert.equal(s.checkFilter.value, 'ALL');
  assert.equal(s.repairFilter.value, 'ALL');
  assert.match(source, /:data="filteredTableData"/);
  assert.match(source, /<ExportDropdown[^>]*:rows="tableData"/);
});
test('full export keeps all 18 original fields, including fields now inside expansion', t => {
  const s = setup(t);
  assert.equal(JSON.stringify(s.exportColumns.map(c => c.key)), JSON.stringify([
    'tool_parent_type_display', 'tool_type_name', 'cutter_position_no', 'is_checked', 'tool_number',
    'wear_condition', 'blade_wear_amount', 'trajectory', 'is_replaced', 'replacement_count',
    'manufacturer', 'new_tool_record_data', 'replacement_type', 'repair_parts', 'brand', 'price', 'old_photo_links', 'remark',
  ]));
  assert.equal(s.exportMeta.value.length, 16);
});
test('edit eligibility still requires supplement mode and ready warehouse', t => {
  const s = setup(t);
  assert.equal(s.isEditable.value, false);
  s.warehouseInfo.value = { supplement_ready: true };
  assert.equal(s.isEditable.value, true);
  const readonly = setup(t, 'view');
  readonly.warehouseInfo.value = { supplement_ready: true };
  assert.equal(readonly.isEditable.value, false);
});
