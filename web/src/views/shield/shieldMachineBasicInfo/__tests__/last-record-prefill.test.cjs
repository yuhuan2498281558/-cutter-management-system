const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vue = require('vue');
const { compile, plain, settle } = require('../../analysis/__tests__/helpers.cjs');

const source = fs.readFileSync(path.resolve(__dirname, '../crud.tsx'), 'utf8');

// Each load compiles a fresh module, so the module-level lastInputValues starts empty.
async function load(respond) {
  const queries = [], timers = [];
  const api = { GetList: async query => { queries.push(plain(query)); return respond(query); } };
  const { crudOptions } = compile(source, name => {
    if (name === './api') return api;
    if (name === 'vue') return vue;
    if (name === 'element-plus') return { ElMessage: {} };
    if (name === '@fast-crud/fast-crud') return {};
    throw new Error(`Unexpected import ${name}`);
  }, { setTimeout: fn => timers.push(fn) }).createCrudOptions({ crudExpose: {} });
  await settle();
  const openAdd = form => { crudOptions.form.wrapper.onOpened({ mode: 'add', form }); while (timers.length) timers.shift()(); return form; };
  return { crudOptions, queries, openAdd };
}

test('"沿用上一条" asks the backend for the newest shield machine with ordering=-id', async () => {
  const { queries } = await load(async () => ({ code: 2000, data: [] }));

  assert.deepEqual(queries, [{ page: 1, limit: 1, ordering: '-id' }]);
});

test('new form is prefilled from the newest record', async () => {
  const { openAdd } = await load(async () => ({ code: 2000, data: [{ id: 6, shield_model_id: 'SM-06', shield_model: 'ZTE6250' }] }));

  assert.deepEqual(openAdd({}), { shield_model_id: 'SM-06', shield_model: 'ZTE6250' });
});

test('no record or a failed lookup leaves the new form empty', async () => {
  const empty = await load(async () => ({ code: 2000, data: [] }));
  assert.deepEqual(empty.openAdd({}), {});

  const failing = await load(async () => { throw { code: 4000, msg: 'x' }; });
  assert.deepEqual(failing.openAdd({}), {});
});
