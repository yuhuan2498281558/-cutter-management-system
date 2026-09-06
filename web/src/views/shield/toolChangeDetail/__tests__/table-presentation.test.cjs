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

test('expanded details use full-width semantic groups with attachments below', () => {
  const expansion = descriptor.template.content.split('<div class="expanded-detail">')[1].split('</template>')[0];
  for (const label of ['新刀信息', '磨损与更换', '采购信息']) assert.ok(expansion.includes(`aria-label="${label}"`));
  assert.ok(expansion.includes('class="detail-attachments"'));
  assert.ok(expansion.includes('class="attachment-field detail-remark"'));
  assert.ok(!expansion.includes('el-descriptions'));
  assert.ok(!source.includes('max-width: 1100px'));
  assert.match(source, /class="export-scope">导出全部刀位及完整字段，不受筛选影响/);
});

test('expanded content renders zero values, long remarks and escaped text without altering data', async t => {
  const { renderToString } = require('@vue/server-renderer');
  const s = setup(t);
  const expansion = '<div class="expanded-detail">' + descriptor.template.content.split('<div class="expanded-detail">')[1].split('</template>')[0];
  const compiled = compileTemplate({ source: expansion, filename: 'expanded-detail.vue', id: 'expanded-render-test' });
  assert.deepEqual(compiled.errors, []);
  const { render } = run(compiled.code);
  const row = {
    blade_wear_amount: 0, replacement_count: 0, price: 0, manufacturer: '<script>bad</script>',
    brand: '测试品牌', replacement_type: 'REPAIR', repair_parts: ['刀圈', '轴承'],
    trajectory: { display: 'R1955 mm', source: '图纸依据' }, tool_parent_type: 'DISC',
    new_tool_record_data: { ring_type_display: '光面', ring_manufacturer: '测试厂家' },
    remark: '长备注\n第二行', old_photo_links: [{ id: 1, name: 'old-photo.png', url: '/test-photo.png' }],
  };
  const snapshot = JSON.stringify(row);
  const app = vue.createSSRApp({ setup: () => ({ row, newToolSummary: s.newToolSummary }), render });
  app.component('ElTooltip', { props: ['content', 'placement'], setup: (_, { slots }) => () => slots.default?.() });
  app.component('ElLink', { setup: (_, { slots }) => () => vue.h('a', {}, slots.default?.()) });
  app.component('ElImage', { render: () => vue.h('img') });
  const html = await renderToString(app);
  assert.equal((html.match(/<dd>0<\/dd>/g) || []).length, 3);
  for (const text of ['光面', 'R1955 mm', '刀圈、轴承', '测试品牌', 'old-photo.png', '长备注\n第二行']) assert.ok(html.includes(text));
  assert.ok(html.includes('&lt;script&gt;bad&lt;/script&gt;'));
  assert.ok(!html.includes('<table'));
  assert.equal(JSON.stringify(row), snapshot);
});
