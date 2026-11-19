const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { compile, plain, settle, deferred } = require('../../analysis/__tests__/helpers.cjs');

const source = fs.readFileSync(path.resolve(__dirname, '../crud.tsx'), 'utf8');

// Compiles the real crud.tsx; request, router and timers are replaced.
function load({ respond = async () => ({ code: 2000, data: [{ id: 8, shield_model: '最新盾构机' }] }) } = {}) {
  const requests = [], routes = [], logged = [], timers = [];
  const moduleUnderTest = compile(source, name => {
    if (name === './api') return {};
    if (name === '@fast-crud/fast-crud') return { dict: value => value };
    if (name === '../crudUtils') return { createIndexFormatter: () => () => 1 };
    if (name === '/@/utils/service') return { request: config => { requests.push(plain(config)); return respond(config); } };
    if (name === 'vue-router') return { useRouter: () => ({ push: value => routes.push(plain(value)) }) };
    throw new Error(`Unexpected import ${name}`);
  }, {
    setTimeout: (fn, ms) => timers.push({ fn, ms }),
    console: { error: (...args) => logged.push(args), warn() {}, log() {} },
  });
  const { crudOptions } = moduleUnderTest.createCrudOptions({ crudExpose: {} });
  const runTimers = () => { while (timers.length) timers.shift().fn(); };
  return { crudOptions, columns: crudOptions.columns, requests, routes, logged, timers, runTimers };
}

const openForm = (page, context) => page.columns.shield_machine.form.wrapper.onOpened(context);

test('new form fills the latest shield machine when none is chosen', async () => {
  const page = load();
  const empty = {};
  const cleared = { shield_machine: null };

  await openForm(page, { mode: 'add', form: empty });
  await openForm(page, { mode: 'add', form: cleared });
  page.runTimers();

  assert.equal(empty.shield_machine, 8);
  assert.equal(cleared.shield_machine, 8);
  assert.deepEqual(page.requests[0], {
    url: '/api/shield/shield_machine_basic_info/', method: 'get', params: { page: 1, limit: 1, ordering: '-id' },
  });
});

test('new form keeps a shield machine the user already chose', async () => {
  const page = load();
  const form = { shield_machine: 5 };

  await openForm(page, { mode: 'add', form });
  page.runTimers();

  assert.equal(form.shield_machine, 5);
});

test('a choice made while the default is loading is not overwritten', async () => {
  const pending = deferred();
  const page = load({ respond: () => pending.promise });
  const form = {};

  const opening = openForm(page, { mode: 'add', form });
  await settle();
  form.shield_machine = 3;
  pending.resolve({ code: 2000, data: [{ id: 8 }] });
  await opening;
  page.runTimers();

  assert.equal(form.shield_machine, 3);
});

test('edit form, empty machine list and failed lookup leave the form alone', async () => {
  const edit = load();
  const editForm = { shield_machine: 2 };
  await openForm(edit, { mode: 'edit', form: editForm });
  edit.runTimers();
  assert.deepEqual(edit.requests, []);
  assert.equal(editForm.shield_machine, 2);

  const none = load({ respond: async () => ({ code: 2000, data: [] }) });
  const noneForm = {};
  await openForm(none, { mode: 'add', form: noneForm });
  assert.equal(none.timers.length, 0);
  assert.deepEqual(noneForm, {});

  const failing = load({ respond: async () => { throw { code: 4000, msg: 'x' }; } });
  const failingForm = {};
  await openForm(failing, { mode: 'add', form: failingForm });
  assert.equal(failing.timers.length, 0);
  assert.equal(failing.logged.length, 1);
  assert.deepEqual(failingForm, {});
});

test('shield machine options request up to 999 records', () => {
  const { dict } = load().columns.shield_machine;

  assert.equal(dict.url, '/api/shield/shield_machine_basic_info/');
  assert.equal(dict.label, 'shield_model');
  assert.equal(dict.value, 'id');
  assert.deepEqual(plain(dict.params), { limit: 999 });
});

test('parent type options are the three tool types, with the same text as the table', () => {
  const column = load().columns.tool_parent_type;

  assert.equal(column.dict.url, undefined);
  assert.deepEqual(plain(column.dict.data), [
    { label: '滚刀', value: 'DISC' },
    { label: '撕裂刀', value: 'RIPPER' },
    { label: '刮刀', value: 'SCRAPER' },
  ]);
  for (const option of column.dict.data) {
    assert.equal(column.column.formatter({ row: { tool_parent_type: option.value } }), option.label);
  }
  assert.equal(column.column.formatter({ row: { tool_parent_type: 'OTHER' } }), 'OTHER');
});

test('成本信息 opens the cost page for the row', () => {
  const page = load();

  page.crudOptions.rowHandle.buttons.costInfo.click({ row: { id: 12, tool_type_name: '17寸滚刀', tool_number: 'DJ-01-001' } });

  assert.deepEqual(page.routes, [{
    path: '/shield/toolCost', query: { tool_info_id: 12, tool_info_name: '17寸滚刀', tool_number: 'DJ-01-001' },
  }]);
});
