const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { compile, plain, settle, deferred } = require('../../analysis/__tests__/helpers.cjs');

const source = fs.readFileSync(path.resolve(__dirname, '../crud.tsx'), 'utf8');

// Compiles the real crud.tsx; api, request and timers are replaced.
function load({ respond = async () => ({ code: 2000, data: [{ id: 8 }] }) } = {}) {
  const requests = [], timers = [];
  const api = {
    GetToolNumbers: async () => ({ code: 2000, data: [{ value: 'DJ-001', label: 'DJ-001', extra: 1 }] }),
    GetCutterPositions: async () => ({ code: 2000, data: [{ value: 'S1L', label: 'S1L' }] }),
  };
  const { crudOptions } = compile(source, name => {
    if (name === './api') return api;
    if (name === '@fast-crud/fast-crud') return { dict: value => value, compute: fn => ({ computeFn: fn }) };
    if (name === '../crudUtils') return { createIndexFormatter: () => () => 1 };
    if (name === '/@/utils/service') return { request: config => { requests.push(plain(config)); return respond(config); } };
    throw new Error(`Unexpected import ${name}`);
  }, {
    setTimeout: fn => timers.push(fn),
    console: { error() {}, warn() {}, log() {} },
  }).createCrudOptions({ crudExpose: {} });
  const runTimers = () => { while (timers.length) timers.shift()(); };
  return { crudOptions, columns: crudOptions.columns, requests, runTimers };
}

test('the broken embedded cost table is gone', () => {
  const { columns } = load();

  assert.equal(columns.cost_records, undefined);
  assert.deepEqual(Object.keys(columns),
    ['_index', 'tool_type', 'tool_name', 'shield_machine', 'tool_number', 'cutter_position_no', 'create_datetime']);
});

test('new form fills the latest shield machine only when none is chosen', async () => {
  const page = load();
  const empty = {};
  const chosen = { shield_machine: 5 };
  const onOpened = page.columns.shield_machine.form.wrapper.onOpened;

  await onOpened({ mode: 'add', form: empty });
  await onOpened({ mode: 'add', form: chosen });
  page.runTimers();

  assert.equal(empty.shield_machine, 8);
  assert.equal(chosen.shield_machine, 5);
  assert.deepEqual(page.requests[0].params, { page: 1, limit: 1, ordering: '-id' });
});

test('a choice made while the default is loading is not overwritten', async () => {
  const pending = deferred();
  const page = load({ respond: () => pending.promise });
  const form = {};

  const opening = page.columns.shield_machine.form.wrapper.onOpened({ mode: 'add', form });
  await settle();
  form.shield_machine = 3;
  pending.resolve({ code: 2000, data: [{ id: 8 }] });
  await opening;
  page.runTimers();

  assert.equal(form.shield_machine, 3);
});

test('shield machine options request up to 999 records', () => {
  const { dict } = load().columns.shield_machine;

  assert.equal(dict.url, '/api/shield/shield_machine_basic_info/');
  assert.deepEqual(plain(dict.params ?? null), { limit: 999 });
});

test('tool type, tool number and cutter position options are unchanged', async () => {
  const { columns } = load();

  assert.deepEqual(plain(columns.tool_type.dict.data.map(item => [item.value, item.label])),
    [['DISC', '滚刀'], ['RIPPER', '撕裂刀'], ['SCRAPER', '刮刀']]);
  assert.deepEqual(plain(await columns.tool_number.dict.getData({})), [{ value: 'DJ-001', label: 'DJ-001' }]);
  assert.deepEqual(plain(await columns.cutter_position_no.dict.getData({})), [{ value: 'S1L', label: 'S1L' }]);
});
