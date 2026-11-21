// Characterization of components/CutterPositionDetail.vue before the F2 fixes.
// Section 1 is the contract the fixes must keep. Section 2 is the duplicate frontend sort
// (F-15) and goes away with it. Section 3 documents F-03/F-04 as todo, not as correct.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');
const { compile, plain } = require('../../analysis/__tests__/helpers.cjs');

const file = path.resolve(__dirname, '../components/CutterPositionDetail.vue');
const API = '/api/shield/cutter_position_info/';
const MACHINE = { id: 9, shield_model_id: 'SM-01', shield_model: 'ZTE6250' };

// Order returned by CutterPositionInfoViewSet.list: tool_type ('' first), then prefix, number, suffix.
const BACKEND_ORDER = [
  ['', '45'],
  ...Array.from({ length: 79 }, (_, i) => ['DISC', String(i + 1)]),
  ['DISC', '80a'], ['DISC', '80b'], ['DISC', 'y1'], ['DISC', 'y3'], ['DISC', 'y5'],
  ...Array.from({ length: 19 }, (_, i) => [['SCRAPER', `S${i + 1}L`], ['SCRAPER', `S${i + 1}R`]]).flat(),
].map(([type, no], index) => ({ id: index + 1, tool_type: type || null, cutter_position_no: no }));
const codes = rows => rows.map(row => `${row.tool_type}:${row.cutter_position_no}`);

function shuffled(items, seed) {
  const copy = items.slice();
  let state = seed;
  for (let i = copy.length - 1; i > 0; i--) {
    state = (state * 1103515245 + 12345) % 2147483648;
    const j = state % (i + 1);
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

// Compiles the real <script setup>; fast-crud, request, Element Plus and timers are replaced.
function mountDetail(t, { respond = () => ({ code: 2000, data: [] }) } = {}) {
  const { descriptor, errors } = parse(fs.readFileSync(file, 'utf8'), { filename: file });
  assert.deepEqual(errors, []);
  const script = compileScript(descriptor, { id: 'cutter-position-test' });
  const requests = [], notices = [], events = [], logged = [], refreshes = [], mounted = [], timers = [];
  let crudOptions;
  const modules = {
    vue: { ...vue, onMounted: fn => mounted.push(fn) },
    '@fast-crud/fast-crud': {
      useExpose: () => ({ crudExpose: { doRefresh: () => refreshes.push('refresh') } }),
      useCrud: ({ crudOptions: options }) => { crudOptions = options; return { resetCrudOptions() {} }; },
      dict: options => options,
    },
    '/@/utils/service': { request: async config => { requests.push(plain(config)); return respond(config); } },
    'element-plus': { ElMessage: { success: text => notices.push(['success', text]), error: text => notices.push(['error', text]) } },
    '@element-plus/icons-vue': { ArrowLeft: { name: 'ArrowLeft' } },
    './CutterheadDisplay.vue': { default: { name: 'CutterheadDisplay' } },
  };
  const globals = {
    setTimeout: (fn, ms) => timers.push({ fn, ms }),
    clearTimeout() {},
    console: { error: (...args) => logged.push(args), warn() {}, log() {} },
  };
  const component = compile(script.content, name => {
    if (name in modules) return modules[name];
    throw new Error(`Unexpected import ${name}`);
  }, globals).default;
  const scope = vue.effectScope();
  const state = scope.run(() => component.setup({ shieldMachine: MACHINE }, {
    expose() {}, emit: (...args) => events.push(args),
  }));
  t.after(() => scope.stop());
  const runTimers = () => { while (timers.length) timers.shift().fn(); };
  return { state, crudOptions, columns: crudOptions.columns, api: crudOptions.request,
    requests, notices, events, logged, refreshes, mounted, timers, runTimers };
}

// ---- 1. Contract kept by the F2 fixes ----

test('mounting refreshes once and keeps every cutter position on one page', t => {
  const page = mountDetail(t);

  assert.equal(page.mounted.length, 1);
  page.mounted[0]();
  assert.deepEqual(page.refreshes, ['refresh']);
  assert.equal(page.crudOptions.pagination.pageSize, 1000);
  assert.equal(page.crudOptions.table.rowKey, 'id');
});

test('list request filters by the current shield machine and passes the query through', async t => {
  const page = mountDetail(t);

  await page.api.pageRequest({ page: 1, limit: 1000, cutter_position_no: 'S1' });

  assert.equal(page.requests.length, 1);
  const { url, method, params } = page.requests[0];
  const { ordering, ...rest } = params;
  assert.equal(url, API);
  assert.equal(method, 'get');
  assert.deepEqual(rest, { page: 1, limit: 1000, cutter_position_no: 'S1', shield_machine: 9 });
});

test('list keeps the backend order and returns the response object', async t => {
  const response = { code: 2000, msg: 'success', page: 1, limit: 1000, total: BACKEND_ORDER.length,
    data: BACKEND_ORDER.slice() };
  const page = mountDetail(t, { respond: () => response });

  const result = await page.api.pageRequest({ page: 1, limit: 1000 });

  assert.equal(result, response);
  assert.equal(result.data.length, 123);
  assert.deepEqual(codes(result.data), codes(BACKEND_ORDER));
  assert.deepEqual(codes(result.data).slice(78, 86),
    ['DISC:78', 'DISC:79', 'DISC:80a', 'DISC:80b', 'DISC:y1', 'DISC:y3', 'DISC:y5', 'SCRAPER:S1L']);
  assert.deepEqual(codes(result.data).slice(-3), ['SCRAPER:S18R', 'SCRAPER:S19L', 'SCRAPER:S19R']);
});

test('list returns an empty response unchanged', async t => {
  const response = { code: 2000, msg: 'success', page: 1, limit: 1000, total: 0, data: [] };
  const page = mountDetail(t, { respond: () => response });

  assert.equal(await page.api.pageRequest({ page: 1, limit: 1000 }), response);
  assert.deepEqual(response.data, []);
});

test('add posts the whole form with the current shield machine', async t => {
  const response = { code: 2000, data: { id: 31 }, msg: '新增成功' };
  const page = mountDetail(t, { respond: () => response });
  const form = { cutter_position_no: '12', _tool_parent_type_select: 'DISC', tool_info: 12, _tool_type_code_display: 'DJ-01' };

  const result = await page.api.addRequest({ form });

  assert.equal(result, response);
  assert.deepEqual(page.requests, [{ url: API, method: 'post', data: {
    cutter_position_no: '12', _tool_parent_type_select: 'DISC', tool_info: 12, _tool_type_code_display: 'DJ-01', shield_machine: 9,
  } }]);
  assert.deepEqual(page.notices, [['success', '添加成功']]);
});

test('edit puts the whole form to the form id', async t => {
  const response = { code: 2000, data: { id: 3, cutter_position_no: '80a' }, msg: '更新成功' };
  const page = mountDetail(t, { respond: () => response });
  const form = { id: 3, cutter_position_no: '80a', shield_machine: 9, tool_info: 12,
    _tool_parent_type_select: 'DISC', _tool_type_code_display: 'DJ-01' };

  const result = await page.api.editRequest({ form, row: { id: 3, cutter_position_no: '80A' } });

  assert.equal(result, response);
  assert.deepEqual(page.requests, [{ url: `${API}3/`, method: 'put', data: {
    id: 3, cutter_position_no: '80a', shield_machine: 9, tool_info: 12, _tool_parent_type_select: 'DISC', _tool_type_code_display: 'DJ-01',
  } }]);
  assert.deepEqual(page.notices, [['success', '修改成功']]);
});

test('delete uses the row id', async t => {
  const response = { code: 2000, data: [], msg: '删除成功' };
  const page = mountDetail(t, { respond: () => response });

  assert.equal(await page.api.delRequest({ row: { id: 4, cutter_position_no: 'S1L' } }), response);
  assert.deepEqual(page.requests, [{ url: `${API}4/`, method: 'delete' }]);
  assert.deepEqual(page.notices, [['success', '删除成功']]);
});

test('failed writes reject with the backend error and show no success message', async t => {
  const failure = { code: 4000, msg: '刀位号已存在' };
  const page = mountDetail(t, { respond: () => { throw failure; } });

  await assert.rejects(page.api.addRequest({ form: { cutter_position_no: '1' } }), error => error === failure);
  await assert.rejects(page.api.editRequest({ form: { id: 1 }, row: { id: 1 } }), error => error === failure);
  await assert.rejects(page.api.delRequest({ row: { id: 1 } }), error => error === failure);
  assert.equal(page.requests.length, 3);
  assert.deepEqual(page.notices, []);
});

test('tool name options stay empty until a parent type is chosen', async t => {
  const page = mountDetail(t);
  const { getData, label, value } = page.columns.tool_info.dict;

  assert.equal(label, 'tool_type_name');
  assert.equal(value, 'id');
  assert.deepEqual(plain(await getData({ form: {} })), []);
  assert.deepEqual(plain(await getData({})), []);
  assert.deepEqual(page.requests, []);
});

test('tool name options load up to 999 tools of the parent type and keep the first item per code', async t => {
  const tools = [
    { id: 12, tool_type_code: 'DJ-01', tool_type_name: '17寸滚刀', tool_parent_type: 'DISC' },
    { id: 5, tool_type_code: 'DJ-01', tool_type_name: '17寸滚刀', tool_parent_type: 'DISC' },
    { id: 7, tool_type_code: 'DJ-02', tool_type_name: '18寸滚刀', tool_parent_type: 'DISC' },
  ];
  const page = mountDetail(t, { respond: () => ({ code: 2000, data: tools }) });

  const options = await page.columns.tool_info.dict.getData({ form: { _tool_parent_type_select: 'DISC' } });

  assert.deepEqual(page.requests, [{ url: '/api/shield/tool_info/', method: 'get', params: { tool_parent_type: 'DISC', limit: 999 } }]);
  assert.deepEqual(plain(options.map(item => item.id)), [12, 7]);
  assert.equal(options[0], tools[0]);
});

test('tool name options fall back to an empty list when loading fails', async t => {
  const page = mountDetail(t, { respond: () => { throw { code: 4000, msg: 'x' }; } });

  const options = await page.columns.tool_info.dict.getData({ form: { _tool_parent_type_select: 'SCRAPER' } });

  assert.deepEqual(plain(options), []);
  assert.equal(page.logged.length, 1);
});

test('changing the parent type clears the tool and its code, then reloads tool options', async t => {
  const page = mountDetail(t);
  const reloads = [], refs = [];
  const form = { _tool_parent_type_select: 'SCRAPER', tool_info: 12, _tool_type_code_display: 'DJ-01' };

  await page.columns._tool_parent_type_select.form.valueChange({
    value: 'SCRAPER', form, getComponentRef: name => { refs.push(name); return { reloadDict: async () => reloads.push(name) }; },
  });

  assert.equal(form.tool_info, undefined);
  assert.equal(form._tool_type_code_display, undefined);
  assert.deepEqual(refs, ['tool_info']);
  assert.deepEqual(reloads, ['tool_info']);

  const bare = { tool_info: 7 };
  await page.columns._tool_parent_type_select.form.valueChange({ value: 'DISC', form: bare, getComponentRef: () => undefined });
  assert.equal(bare.tool_info, undefined);
});

test('clearing the tool name clears the code box without a request', async t => {
  const page = mountDetail(t);
  const form = { tool_info: undefined, _tool_type_code_display: 'DJ-01' };

  await page.columns.tool_info.form.valueChange({ value: undefined, form });

  assert.equal(form._tool_type_code_display, undefined);
  assert.deepEqual(page.requests, []);
});

test('opening the edit form restores parent type and code from the row', t => {
  const page = mountDetail(t);
  const onOpened = page.columns.tool_info.form.wrapper.onOpened;
  const edited = {};
  const added = {};
  const untyped = {};

  onOpened({ mode: 'edit', form: edited, row: { id: 3, tool_parent_type: 'SCRAPER', tool_type_code: 'GD-01', tool_info: 21 } });
  onOpened({ mode: 'add', form: added, row: { tool_parent_type: 'DISC', tool_type_code: 'DJ-01' } });
  onOpened({ mode: 'edit', form: untyped, row: { id: 4, tool_parent_type: null } });
  page.runTimers();

  assert.equal(edited._tool_parent_type_select, 'SCRAPER');
  assert.equal(edited._tool_type_code_display, 'GD-01');
  assert.deepEqual(added, {});
  assert.deepEqual(untyped, {});
});

test('parent type options and table text use the three tool types', t => {
  const page = mountDetail(t);
  const format = page.columns.tool_parent_type.column.formatter;

  assert.deepEqual(plain(page.columns._tool_parent_type_select.dict.data.map(item => [item.value, item.label])),
    [['DISC', '滚刀'], ['RIPPER', '撕裂刀'], ['SCRAPER', '刮刀']]);
  assert.equal(format({ row: { tool_parent_type: 'DISC' } }), '滚刀');
  assert.equal(format({ row: { tool_parent_type: 'RIPPER' } }), '撕裂刀');
  assert.equal(format({ row: { tool_parent_type: 'SCRAPER' } }), '刮刀');
  assert.equal(format({ row: { tool_parent_type: 'OTHER' } }), 'OTHER');
  assert.equal(format({ row: {} }), '-');
});

test('cutterhead selection is remembered and 返回 emits close', t => {
  const page = mountDetail(t);

  page.state.handleCutterSelected({ code: 'S1L' });
  page.state.handleClose();

  assert.equal(page.state.selectedCutterCode.value, 'S1L');
  assert.deepEqual(page.events, [['close']]);
});

// ---- 2. Duplicate frontend sort (F-15). Delete together with the sort. ----

test('F-15: list request sends an ordering param that the backend list() ignores', async t => {
  const page = mountDetail(t);

  await page.api.pageRequest({ page: 1, limit: 1000 });

  assert.equal(page.requests[0].params.ordering, 'tool_type,cutter_position_no');
});

test('F-15: frontend re-sort of a shuffled list reproduces the backend order', async t => {
  for (let seed = 1; seed <= 20; seed++) {
    const page = mountDetail(t, { respond: () => ({ code: 2000, data: shuffled(BACKEND_ORDER, seed) }) });
    const result = await page.api.pageRequest({ page: 1, limit: 1000 });
    assert.deepEqual(codes(result.data), codes(BACKEND_ORDER), `seed ${seed}`);
  }
});

test('F-15: results-shaped responses are re-sorted the same way', async t => {
  const page = mountDetail(t, { respond: () => ({ results: shuffled(BACKEND_ORDER, 7) }) });

  const result = await page.api.pageRequest({ page: 1, limit: 1000 });

  assert.deepEqual(codes(result.results), codes(BACKEND_ORDER));
});

// ---- 3. Known bugs, fixed by F2. Expected behavior, marked todo until then. ----

test('F-03: choosing a tool name shows its tool_type_code', { todo: 'F2 修复 F-03 后去掉 todo' }, async t => {
  const page = mountDetail(t, { respond: () => ({ code: 2000, data: { id: 12, tool_type_code: 'DJ-01' }, msg: 'success' }) });
  const form = {};

  await page.columns.tool_info.form.valueChange({ value: 12, form });

  assert.equal(form._tool_type_code_display, 'DJ-01');
});

test('F-04: options keep the tool referenced by the edited row', { todo: 'F2 修复 F-04 后去掉 todo' }, async t => {
  const tools = [
    { id: 12, tool_type_code: 'DJ-01', tool_type_name: '17寸滚刀' },
    { id: 5, tool_type_code: 'DJ-01', tool_type_name: '17寸滚刀' },
    { id: 7, tool_type_code: 'DJ-02', tool_type_name: '18寸滚刀' },
  ];
  const page = mountDetail(t, { respond: () => ({ code: 2000, data: tools }) });

  const options = await page.columns.tool_info.dict.getData({ form: { _tool_parent_type_select: 'DISC', tool_info: 5 } });

  assert.ok(options.some(item => item.id === 5));
  assert.ok(options.some(item => item.id === 7));
});
