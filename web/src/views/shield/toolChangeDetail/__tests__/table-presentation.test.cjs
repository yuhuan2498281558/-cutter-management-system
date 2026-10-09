// Run from web: node --test src/views/shield/toolChangeDetail/__tests__/*.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');

function run(source, requireModule = require, globals = {}) {
  const context = { ...globals, exports: {}, require: requireModule };
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
function setup(t, mode = 'supplement', options = {}) {
  const scope = vue.effectScope();
  const compiled = run(script.content, name => {
    if (name === 'vue') return { ...vue, onMounted() {}, onActivated() {}, onDeactivated() {}, onUnmounted() {} };
    if (name === 'vue-router') return { useRoute: () => ({ path: '/shield/toolChangeDetail', query: options.query || { mode } }), useRouter: () => options.router || {} };
    if (name === './tablePresentation') return helpers;
    if (name === '/@/utils/service') return { request: options.request || (() => { throw new Error('Unexpected API call'); }) };
    if (name === 'element-plus') return { ElMessage: { success() {}, warning() {}, error() {} } };
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

test('active filter feedback tracks independent conditions without changing export data', t => {
  const s = setup(t);
  assert.equal(s.hasActiveFilters.value, false);
  s.searchText.value = '   ';
  assert.equal(s.hasActiveFilters.value, false);
  s.searchText.value = ' NEW-5 ';
  s.checkFilter.value = 'REPLACED';
  s.repairFilter.value = 'CONFIRMED';
  assert.equal(s.hasActiveFilters.value, true);
  assert.equal(s.checkFilterLabel.value, '已更换');
  assert.equal(s.filteredTableData.value.length, 1);
  s.searchText.value = '';
  assert.equal(s.checkFilter.value, 'REPLACED');
  assert.equal(s.repairFilter.value, 'CONFIRMED');
  s.checkFilter.value = 'ALL';
  assert.equal(s.hasActiveFilters.value, true);
  assert.equal(s.tableData.value.length, 7);
  s.resetFilters();
  assert.equal(s.hasActiveFilters.value, false);
});

test('empty state differentiates no records and filtered-out records with a reset action', () => {
  assert.match(source, /tableData.length \? '没有符合筛选条件的刀位' : '暂无刀位数据'/);
  assert.match(source, /@click="resetFilters">清除筛选，显示全部/);
  for (const name of ['清除刀位和编号搜索', '清除检查状态条件', '清除返修状态条件']) assert.ok(source.includes(`aria-label="${name}"`));
  assert.match(source, /role="status" aria-live="polite"/);
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

function findExpandedDetail(node) {
  if (node.type === 1 && node.props.some(prop => prop.type === 6 && prop.name === 'class' && prop.value?.content.split(/\s+/).includes('expanded-detail'))) return node.loc.source;
  for (const child of node.children || []) {
    const content = findExpandedDetail(child);
    if (content) return content;
  }
}

test('expanded details use full-width semantic groups with attachments below', () => {
  const expansion = findExpandedDetail(descriptor.template.ast);
  assert.ok(expansion, 'expanded detail container exists');
  for (const label of ['新刀信息', '磨损与更换', '采购信息']) assert.ok(expansion.includes(`aria-label="${label}"`));
  assert.ok(expansion.includes('class="detail-attachments"'));
  assert.ok(expansion.includes('class="attachment-field detail-remark"'));
  assert.ok(!expansion.includes('el-descriptions'));
  for (const style of descriptor.styles) {
    require('postcss').parse(style.content).walkDecls('max-width', declaration => assert.notEqual(declaration.value, '1100px'));
  }
  assert.match(source, /class="export-scope">导出全部刀位及完整字段，不受筛选影响/);
});

test('expanded content renders zero values, long remarks and escaped text without altering data', async t => {
  const { renderToString } = require('@vue/server-renderer');
  const s = setup(t);
  const expansion = findExpandedDetail(descriptor.template.ast);
  assert.ok(expansion, 'expanded detail container exists');
  const compiled = compileTemplate({ source: expansion, filename: 'expanded-detail.vue', id: 'expanded-render-test' });
  assert.deepEqual(compiled.errors, []);
  const { render } = run(compiled.code);
  const row = {
    cutter_position_no: '17',
    blade_wear_amount: 0, replacement_count: 0, price: 0, manufacturer: '<script>bad</script>',
    brand: '测试品牌', replacement_type: 'REPAIR', repair_parts: ['刀圈', '轴承'],
    trajectory: { display: 'R1955 mm', source: '图纸依据' }, tool_parent_type: 'DISC',
    new_tool_record_data: { ring_type_display: '光面', ring_manufacturer: '测试厂家' },
    remark: '长备注\n第二行', old_photo_links: [{ id: 1, name: 'old-photo.png', url: '/test-photo.png' }],
  };
  const snapshot = JSON.stringify(row);
  const app = vue.createSSRApp({ setup: () => ({ row, warehouseId: 123, newToolSummary: s.newToolSummary }), render });
  app.component('ElTooltip', { props: ['content', 'placement'], setup: (_, { slots }) => () => slots.default?.() });
  app.component('ElLink', { setup: (_, { slots }) => () => vue.h('a', {}, slots.default?.()) });
  app.component('ElImage', { render: () => vue.h('img') });
  const html = await renderToString(app);
  assert.ok(html.includes('id="tool-detail-123-17"'));
  assert.equal((html.match(/<dd>0<\/dd>/g) || []).length, 3);
  for (const text of ['光面', 'R1955 mm', '刀圈、轴承', '测试品牌', 'old-photo.png', '长备注\n第二行']) assert.ok(html.includes(text));
  assert.ok(html.includes('&lt;script&gt;bad&lt;/script&gt;'));
  assert.ok(!html.includes('<table'));
  assert.equal(JSON.stringify(row), snapshot);
});

test('real loading joins by position, preserves missing numbers and zero fields, and sorts naturally', async t => {
  const calls = [];
  const positions = ['80B', '2', '80A', '1'].map((p, i) => ({ id: i + 1, cutter_position_no: p, tool_type: 'DISC', tool_type_name: '测试滚刀' }));
  const detail = { id: 12, cutter_position_no: '2', tool_number: 'STORED-2', is_checked: true, is_replaced: true, blade_wear_amount: 0, price: '0', old_tool_record_data: { inspection_status: 'CLOSED' } };
  const original = JSON.stringify({ positions, detail });
  const s = setup(t, 'view', { query: { warehouse_id: '123', mode: 'view' }, request: async config => {
    calls.push(config);
    if (config.url === '/api/shield/warehouse_opening/123/') return { data: { shield_model: 9, supplement_ready: true } };
    if (config.url === '/api/shield/cutter_position_info/') return { data: positions };
    if (config.url === '/api/shield/tool_change_detail/') return { data: [detail] };
    throw new Error('Unexpected URL');
  } });
  await s.getWarehouseInfo();
  assert.equal(s.dataLoaded.value, true);
  assert.equal(JSON.stringify(s.tableData.value.map(r => r.cutter_position_no)), JSON.stringify(['1', '2', '80A', '80B']));
  assert.equal(s.tableData.value[0].tool_number, '');
  assert.equal(s.tableData.value[1].tool_number, 'STORED-2');
  assert.equal(s.tableData.value[1].blade_wear_amount, 0);
  assert.equal(s.tableData.value[1].price, 0);
  assert.equal(repairStatus(s.tableData.value[1]), 'CLOSED');
  assert.ok(calls.every(c => c.method === 'get'));
  assert.equal(calls[1].params.shield_machine, 9);
  assert.equal(calls[2].params.warehouse, 123);
  assert.equal(JSON.stringify({ positions, detail }), original);
});

test('missing warehouse prevents reads and does not guess an id', async t => {
  let reads = 0, backs = 0;
  const s = setup(t, 'view', { query: {}, router: { back: () => backs++ }, request: async () => { reads++; } });
  await s.getWarehouseInfo();
  assert.equal(reads, 0);
  assert.equal(backs, 1);
});

test('unconfirmed warehouse downgrades supplement to view with query preserved', async t => {
  const replacements = [];
  const s = setup(t, 'supplement', { query: { warehouse_id: '123', mode: 'supplement', warehouse_code: 'TEST-123' }, router: { replace: async target => replacements.push(target) }, request: async config => ({ data: config.url.includes('warehouse_opening') ? { shield_model: 9, supplement_ready: false } : [] }) });
  await s.getWarehouseInfo();
  assert.equal(s.isEditable.value, false);
  assert.equal(replacements.length, 1);
  assert.equal(replacements[0].query.mode, 'view');
  assert.equal(replacements[0].query.warehouse_id, '123');
  assert.equal(replacements[0].query.warehouse_code, 'TEST-123');
});

test('parent repair entry enforces missing-record, not-replaced, readonly and archived guards', t => {
  const s = setup(t, 'view');
  const opened = [];
  s.repairDialogRef.value = { open: (row, options) => opened.push({ row, options }) };
  s.openOldToolRepair({ is_replaced: true });
  s.openOldToolRepair({ id: 1, is_replaced: false });
  assert.equal(opened.length, 0);
  s.openOldToolRepair({ id: 1, is_replaced: true });
  assert.equal(opened[0].options.readOnly, true);
  const editable = setup(t);
  editable.warehouseInfo.value = { supplement_ready: true };
  editable.repairDialogRef.value = s.repairDialogRef.value;
  editable.openOldToolRepair({ id: 2, is_replaced: true });
  editable.openOldToolRepair({ id: 3, is_replaced: true, old_tool_record_data: { inspection_status: 'CLOSED' } });
  assert.equal(opened[1].options.readOnly, false);
  assert.equal(opened[2].options.readOnly, true);
});

function exportHarness(t) {
  const blobs = [], documents = [];
  const utility = run(fs.readFileSync(path.resolve(__dirname, '../../utils/export.ts'), 'utf8'), require, {
    Blob, URL: { createObjectURL: blob => { blobs.push(blob); return 'blob:test'; }, revokeObjectURL() {} },
    document: { createElement: () => ({ style: {}, click() {} }), body: { appendChild() {}, removeChild() {} } },
    window: { open: () => ({ document: { write: html => documents.push(html), close() {} }, focus() {}, print() {} }) },
    setTimeout: fn => fn(),
  });
  const s = setup(t);
  s.tableData.value = rows.map((row, i) => ({ ...row, remark: i === 0 ? '长备注,"引号"\n第二行 <b>文本</b>' : `record-${i}`, price: 0 }));
  s.searchText.value = 'not-present';
  assert.equal(s.filteredTableData.value.length, 0);
  const dropdownSource = fs.readFileSync(path.resolve(__dirname, '../../components/ExportDropdown.vue'), 'utf8');
  const dropdown = compileScript(parse(dropdownSource).descriptor, { id: 'export-integration-test' });
  const component = run(dropdown.content, name => {
    if (name === 'vue') return vue;
    if (name === '../utils/export') return utility;
    if (name === 'element-plus') return { ElMessage: { warning() {} } };
    if (name === '@element-plus/icons-vue') return { Download: {} };
    throw new Error(`Unexpected export import: ${name}`);
  });
  const props = vue.reactive({ title: '隔离导出验收', filename: 'test-only', rows: s.tableData.value, columns: s.exportColumns, meta: s.exportMeta.value });
  const state = component.default.setup(props, { expose() {} });
  return { state, blobs, documents };
}

function parseCsv(text) {
  const records = []; let record = [], value = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { value += '"'; i++; }
      else quoted = !quoted;
    } else if (!quoted && (char === ',' || char === '\n')) {
      record.push(value); value = '';
      if (char === '\n') { records.push(record); record = []; }
    } else value += char;
  }
  record.push(value); records.push(record);
  return records;
}

test('actual dropdown-to-CSV export retains every row and 18 columns despite empty screen filter', async t => {
  const { state, blobs } = exportHarness(t);
  state.handleCommand('csv');
  assert.equal(blobs.length, 1);
  const csv = parseCsv((await blobs[0].text()).replace(/^\uFEFF/, ''));
  const headerIndex = csv.findIndex(row => row.includes('刀位号') && row.includes('刀具编号'));
  assert.equal(headerIndex, 17); // 16 opening metadata rows and one separator
  assert.equal(csv[headerIndex].length, 18);
  const data = csv.slice(headerIndex + 1);
  assert.equal(data.length, rows.length);
  assert.ok(data.every(row => row.length === 18));
  assert.equal(data[0][17], '长备注,"引号"\n第二行 <b>文本</b>');
  assert.equal(data[0][15], '0');
  assert.equal(data[1][4], '');
});

test('actual Excel and print exports keep full table, opening metadata and escaped text', async t => {
  const { state, blobs, documents } = exportHarness(t);
  state.handleCommand('excel');
  state.handleCommand('pdf');
  for (const html of [await blobs[0].text(), documents[0]]) {
    assert.ok(html.includes('开仓基本信息'));
    assert.ok(html.includes('&lt;b&gt;文本&lt;/b&gt;'));
    const detailRows = html.split('<tr class="detail-header">')[1];
    assert.equal((detailRows.match(/<th>/g) || []).length, 18);
    assert.equal((detailRows.match(/<td>/g) || []).length, rows.length * 18);
    for (const row of rows) assert.ok(html.includes(`<td>${row.cutter_position_no}</td>`));
  }
});
