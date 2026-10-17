// Characterization tests for the actual mobile detail SFC setup. Every API is a stub:
// the real task GET claims the task and writes to the database, so only its count and timing are locked here.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { parse, compileScript } = require('@vue/compiler-sfc');
const ts = require('typescript');
const vue = require('vue');

const { descriptor } = parse(fs.readFileSync(path.resolve(__dirname, '../tool-change/detail.vue'), 'utf8'));
const script = compileScript(descriptor, { id: 'mobile-tool-change-detail-test' });
const compiled = ts.transpileModule(script.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
// Values created inside the vm belong to another realm; copy them before deepEqual.
const plain = value => JSON.parse(JSON.stringify(value));
const nos = list => Array.from(list, item => item.cutter_position_no);
const detail = (id, no, extra = {}) => ({
  id, cutter_position_no: no, tool_parent_type: 'DISC', is_checked: false, is_replaced: false,
  mobile_status: 'PENDING', old_photos: [], ...extra,
});
const jpeg = name => new File(['x'], name, { type: 'image/jpeg' });
const fieldsOf = data => Object.fromEntries([...data.entries()].filter(([, value]) => typeof value === 'string'));
const photoNames = data => data.getAll('old_photos').map(file => file.name);

function mount(t, options = {}) {
  const {
    details = [detail(1, '1'), detail(2, '2'), detail(3, '3')],
    task = { id: 7, status: 'IN_PROGRESS' },
    fieldOptions = {},
    getTask, save, submit, confirm,
  } = options;
  const hooks = {}, toasts = [], confirms = [], pushes = [], events = [], gets = [], saves = [], submits = [];
  let state;
  const api = {
    getMobileTask: async id => {
      gets.push(id); events.push('get');
      if (getTask) return getTask(id);
      return { code: 2000, msg: 'success', data: { task: { ...task }, details: structuredClone(details), field_options: structuredClone(fieldOptions) } };
    },
    saveMobileDetail: async (taskId, data) => {
      saves.push({ taskId, data }); events.push('save');
      if (save) return save(data);
      const row = state.details.value.find(item => item.id === Number(data.get('detail_id')));
      return { data: { ...plain(row), is_checked: true, mobile_status: 'SAVED' } };
    },
    submitMobileTask: async taskId => {
      submits.push(taskId); events.push('submit');
      return submit ? submit(taskId) : { code: 2000, msg: 'success' };
    },
  };
  const context = {
    exports: {}, console, FormData, Blob, File,
    window: { setInterval, clearInterval }, navigator: {},
    require(name) {
      if (name === 'vue') return { ...vue, onMounted: fn => { hooks.onMounted = fn; }, onBeforeUnmount: fn => { hooks.onBeforeUnmount = fn; } };
      if (name === 'vue-router') return { useRoute: () => ({ params: { id: '7' } }), useRouter: () => ({ push: target => pushes.push(target) }) };
      if (name === 'vant') {
        return {
          showToast: message => toasts.push(message),
          showConfirmDialog: async dialog => { confirms.push(dialog); events.push('confirm'); if (confirm) return confirm(dialog); },
        };
      }
      if (name === '../api') return api;
      throw new Error(`Unexpected import: ${name}`);
    },
  };
  vm.runInNewContext(compiled, context);
  const scope = vue.effectScope();
  state = scope.run(() => context.exports.default.setup({}, { expose() {} }));
  t.after(() => { hooks.onBeforeUnmount?.(); scope.stop(); });
  return { s: state, hooks, toasts, confirms, pushes, events, gets, saves, submits };
}

test('positions sort numbers (with A/B suffix), then Y, then S (L, R, bare), then anything else', async t => {
  const order = ['1', ' 5 ', '10', '80', '80A', '80B', 'Y1', 'Y3', 's1r', 'S2L', 'S2R', 'S4', 'S10L', 'G3R', 'X9'];
  const shuffled = ['S10L', 'X9', '80B', 'Y3', ' 5 ', 'S2R', '1', 'G3R', 's1r', '80', 'Y1', 'S4', '10', 'S2L', '80A'];
  const { s } = mount(t, { details: shuffled.map((no, index) => detail(index + 1, no)) });
  await s.loadTask();
  assert.deepEqual(nos(s.details.value), order);
  assert.deepEqual(nos(s.filteredDetails.value), order);
  assert.deepEqual(nos(s.sortDetails([detail(1, 'S1R'), detail(2, 'S1L'), detail(3, '2')])), ['2', 'S1L', 'S1R']);
});

for (const [shape, wrap] of [
  ['standard {code, data}', payload => ({ code: 2000, msg: 'success', data: payload })],
  ['bare payload', payload => payload],
  ['double-wrapped {data: {data}}', payload => ({ data: { data: payload } })],
]) {
  test(`task payload unwraps the ${shape} shell`, async t => {
    const fieldOptions = { ring_types: [{ label: '标准刀圈', value: 'STD' }] };
    const payload = { task: { id: 7, status: 'IN_PROGRESS' }, details: [detail(2, '2'), detail(1, '1')], field_options: fieldOptions };
    const { s, toasts } = mount(t, { getTask: async () => wrap(payload) });
    await s.loadTask();
    assert.equal(s.task.value.id, 7);
    assert.deepEqual(nos(s.details.value), ['1', '2']);
    assert.deepEqual(plain(s.fieldOptions.value), fieldOptions);
    assert.equal(s.loadError.value, '');
    assert.deepEqual(toasts, []);
  });
}

test('task payload prefers response.data and tolerates bad details/field_options', async t => {
  const { s } = mount(t, { getTask: async () => ({ task: { id: 1 }, data: { task: { id: 2 }, details: 'bad', field_options: 'bad' } }) });
  await s.loadTask();
  assert.equal(s.task.value.id, 2);
  assert.deepEqual(plain(s.details.value), []);
  assert.deepEqual(plain(s.fieldOptions.value), {});
});

for (const [name, response, message] of [
  ['outer msg', { code: 4000, msg: '无权访问该任务' }, '无权访问该任务'],
  ['inner msg', { data: { msg: '任务已被他人锁定' } }, '任务已被他人锁定'],
  ['no msg', { code: 2000, data: null }, '任务详情返回异常，请重新登录后再试'],
]) {
  test(`a response without task reports the ${name}`, async t => {
    const { s, toasts } = mount(t, { getTask: async () => response });
    s.refreshing.value = true;
    await s.loadTask();
    assert.equal(s.loadError.value, message);
    assert.deepEqual(toasts, [message]);
    assert.equal(s.task.value, null);
    assert.equal(s.refreshing.value, false);
  });
}

for (const [name, error, message] of [
  ['response.data.msg', { response: { data: { msg: '登录已过期' } } }, '登录已过期'],
  ['msg', { msg: '服务器繁忙' }, '服务器繁忙'],
  ['detail', { detail: '未找到' }, '未找到'],
  ['message', new Error('Network Error'), 'Network Error'],
  ['fallback', {}, '操作失败，请稍后重试'],
]) {
  test(`a rejected task request shows the ${name} text`, async t => {
    const { s, toasts } = mount(t, { getTask: async () => { throw error; } });
    s.refreshing.value = true;
    await s.loadTask();
    assert.equal(s.loadError.value, message);
    assert.deepEqual(toasts, [message]);
    assert.equal(s.refreshing.value, false);
  });
}

const filterFixture = () => [
  detail(1, '1'),
  detail(2, '2', { is_checked: true, mobile_status: 'SAVED' }),
  detail(3, '3', { is_checked: true, is_replaced: true, mobile_status: 'SAVED', old_photos: [{ id: 31 }] }),
  detail(4, '4', { is_checked: true, is_replaced: true, mobile_status: 'SAVED', old_photos: [] }),
  detail(5, 'S1L', { tool_parent_type: 'SCRAPER', is_checked: true, is_replaced: true, mobile_status: 'SAVED', old_photos: undefined }),
  detail(6, 'S1R', { tool_parent_type: 'SCRAPER' }),
  detail(7, '10', { tool_parent_type: '', is_checked: true, mobile_status: 'SAVED' }),
];

test('five status filters, type filter and keyword combine on the sorted list', async t => {
  const { s } = mount(t, { details: filterFixture() });
  await s.loadTask();
  assert.deepEqual(plain(s.statusOptions).map(item => item.value), ['ALL', 'PENDING', 'REPLACED', 'NOT_REPLACED', 'MISSING_PHOTO']);
  assert.deepEqual(plain(s.typeOptions.value).map(item => item.value), ['ALL', 'DISC', 'SCRAPER']);
  assert.equal(s.typeOptions.value[0].text, '全部类型');
  const expectations = {
    ALL: ['1', '2', '3', '4', '10', 'S1L', 'S1R'],
    PENDING: ['1', 'S1R'],
    REPLACED: ['3', '4', 'S1L'],
    NOT_REPLACED: ['2', '10'],
    MISSING_PHOTO: ['4', 'S1L'],
  };
  for (const [status, expected] of Object.entries(expectations)) {
    s.statusFilter.value = status;
    assert.deepEqual(nos(s.filteredDetails.value), expected, status);
  }
  s.statusFilter.value = 'ALL';
  s.typeFilter.value = 'SCRAPER';
  assert.deepEqual(nos(s.filteredDetails.value), ['S1L', 'S1R']);
  s.typeFilter.value = 'DISC';
  s.statusFilter.value = 'MISSING_PHOTO';
  assert.deepEqual(nos(s.filteredDetails.value), ['4']);
  s.typeFilter.value = 'ALL';
  s.statusFilter.value = 'ALL';
  s.keyword.value = ' s1 ';
  assert.deepEqual(nos(s.filteredDetails.value), ['S1L', 'S1R']);
  s.keyword.value = '1';
  assert.deepEqual(nos(s.filteredDetails.value), ['1', '10', 'S1L', 'S1R']);
});

test('summary counts saved, replaced and missing-photo positions', async t => {
  const { s } = mount(t, { details: filterFixture() });
  assert.equal(s.progressPercent.value, 0);
  await s.loadTask();
  assert.equal(s.savedCount.value, 5);
  assert.equal(s.replacedCount.value, 3);
  assert.equal(s.missingPhotoCount.value, 2);
  assert.equal(s.progressPercent.value, 71);
});

test('only completed and cancelled tasks are read-only', async t => {
  for (const [status, readonly] of [['IN_PROGRESS', false], ['RETURNED', false], ['SUBMITTED', false], ['COMPLETED', true], ['CANCELLED', true]]) {
    const { s } = mount(t, { task: { id: 7, status } });
    await s.loadTask();
    assert.equal(s.readonly.value, readonly, status);
  }
});

const costOptions = [
  { id: 11, label: 'A厂 / 甲 / 1000', manufacturer: 'A厂', brand: '甲', price: '1000' },
  { id: 12, label: 'B厂 / 乙 / 1200', manufacturer: 'B厂', brand: '乙', price: 1200 },
  { id: 13, label: 'C厂 / - / 900', manufacturer: 'C厂', brand: '', price: '900.00' },
];

test('opening a position matches the saved cost by id, then by manufacturer/brand/price', async t => {
  const rows = [
    detail(1, '1', { tool_cost_options: costOptions, tool_cost_id: 12, manufacturer: 'X', brand: 'Y', price: 1 }),
    detail(2, '2', { tool_cost_options: costOptions, tool_cost_id: 99, manufacturer: 'B厂', brand: '乙', price: '1200' }),
    detail(3, '3', { tool_cost_options: costOptions, tool_cost_id: null, manufacturer: 'C厂', brand: null, price: '900.00' }),
    detail(4, '4', { tool_cost_options: costOptions, manufacturer: 'D厂', brand: '丁', price: 800 }),
    detail(5, '5', { manufacturer: 'E厂' }),
  ];
  const { s } = mount(t, { details: rows });
  await s.loadTask();
  const opened = id => {
    s.openEditor(s.details.value.find(item => item.id === id));
    return [s.form.tool_cost_id, s.form.tool_cost_label, s.form.cost_manufacturer, s.form.cost_brand, s.form.cost_price];
  };
  assert.deepEqual(opened(1), [12, 'B厂 / 乙 / 1200', 'B厂', '乙', 1200]);
  assert.deepEqual(opened(2), [12, 'B厂 / 乙 / 1200', 'B厂', '乙', 1200]);
  assert.deepEqual(opened(3), [13, 'C厂 / - / 900', 'C厂', '', '900.00']);
  assert.deepEqual(opened(4), ['', '', 'D厂', '丁', 800]);
  assert.deepEqual(opened(5), ['', '', 'E厂', '', '']);
});

test('opening a position fills the form from the row and resets per-edit state', async t => {
  const fieldOptions = {
    ring_types: [{ label: '标准刀圈', value: 'STD' }],
    component_conditions: [{ label: '良好', value: 'GOOD' }, { label: '磨损', value: 'WORN' }],
  };
  const rows = [
    detail(1, '1', {
      is_replaced: true, is_checked: true, check_result: 'ATTENTION', remark: null, tool_type_name: '17寸滚刀',
      new_tool: { ring_type: 'STD', ring_manufacturer: 'A厂', shaft_condition: 'GOOD', shaft_condition_display: '轴良好', hub_condition: 'WORN', hub_manufacturer: 'C厂', scraper_manufacturer: 'D厂' },
      wear_condition: '偏磨', blade_wear_amount: 0,
      old_photos: [{ id: 5, image_url: '/media/a.jpg', original_filename: 'a.jpg' }],
    }),
    detail(2, '2', { check_result: 'PENDING', blade_wear_amount: null }),
    detail(3, '3', { tool_parent_type: '' }),
  ];
  const { s } = mount(t, { details: rows, fieldOptions });
  await s.loadTask();
  s.form.scan_text = 'old scan';
  s.form.pendingPhotoFiles = [jpeg('stale.jpg')];
  s.openEditor(s.details.value[0]);
  assert.equal(s.editorVisible.value, true);
  assert.equal(s.current.value.id, 1);
  assert.equal(s.form.is_replaced, true);
  assert.equal(s.form.check_result, '需关注');
  assert.equal(s.form.remark, '');
  assert.equal(s.form.scan_text, '');
  assert.equal(s.form.tool_info_label, '17寸滚刀');
  assert.deepEqual(
    [s.form.ring_type, s.form.ring_type_label, s.form.ring_manufacturer, s.form.shaft_condition, s.form.shaft_condition_label,
      s.form.shaft_manufacturer, s.form.hub_condition, s.form.hub_condition_label, s.form.hub_manufacturer, s.form.scraper_manufacturer],
    ['STD', '标准刀圈', 'A厂', 'GOOD', '轴良好', '', 'WORN', '磨损', 'C厂', 'D厂'],
  );
  assert.equal(s.form.wear_condition, '偏磨');
  assert.equal(s.form.blade_wear_amount, 0);
  assert.deepEqual(plain(s.form.photos), [{ id: 5, url: '/media/a.jpg', isImage: true, message: 'a.jpg' }]);
  assert.equal(s.form.pendingPhotoFiles.length, 0);

  s.openEditor(s.details.value[1]);
  assert.equal(s.form.check_result, '未进行换刀');
  assert.equal(s.form.blade_wear_amount, '');
  assert.equal(s.form.tool_info_label, 'DISC');
  s.openEditor(s.details.value[2]);
  assert.equal(s.form.tool_info_label, '刀位绑定类型');
});

test('photo files are found on file/raw/originFileObj/self; only saved server ids are retained', async t => {
  const { s } = mount(t);
  const file = jpeg('a.jpg');
  const duck = { size: 3, slice() {} };
  assert.equal(s.getPhotoFile({ file }), file);
  assert.equal(s.getPhotoFile({ raw: file }), file);
  assert.equal(s.getPhotoFile({ originFileObj: file }), file);
  assert.equal(s.getPhotoFile(file), file);
  assert.equal(s.getPhotoFile({ file: duck }), duck);
  assert.equal(s.getPhotoFile({ url: '/media/a.jpg', id: 1 }), null);
  assert.equal(s.getPhotoFile(null), null);
  s.form.photos = [
    { id: 5, url: '/a' }, { id: '6', url: '/b' }, { id: 0 }, { id: -1 }, { id: 'abc' }, { id: 1.5 }, { url: '/c' },
    { id: 9, file },
  ];
  assert.deepEqual(Array.from(s.retainedPhotoIds()), [5, 6]);
});

test('photo validation keeps JPG/PNG up to 30MB and removes anything else', async t => {
  const { s, toasts } = mount(t);
  const accepted = [
    { file: jpeg('a.jpg') },
    { file: new File(['x'], 'b.PNG', { type: '' }) },
    { file: new File(['x'], 'c', { type: 'image/jpg' }) },
    { file: new Blob(['x']) },
    { file: { size: 30 * 1024 * 1024, type: 'image/jpeg', name: 'limit.jpg', slice() {} } },
  ];
  for (const item of accepted) {
    s.form.photos = [...s.form.photos, item];
    s.validatePhoto(item);
    assert.equal(item.isImage, true);
  }
  s.validatePhoto(accepted[0]);
  assert.equal(s.form.pendingPhotoFiles.length, accepted.length);
  assert.deepEqual(toasts, []);

  const gif = { file: new File(['x'], 'd.gif', { type: 'image/gif' }) };
  s.form.photos = [...s.form.photos, gif];
  s.validatePhoto(gif);
  assert.deepEqual(toasts, ['仅支持 JPG/PNG 原图']);
  assert.equal(s.form.photos.includes(gif), false);

  const big = { file: { size: 30 * 1024 * 1024 + 1, type: 'image/jpeg', name: 'big.jpg', slice() {} } };
  s.form.photos = [...s.form.photos, big];
  s.validatePhoto(big);
  assert.deepEqual(toasts, ['仅支持 JPG/PNG 原图', '单张照片不能超过 30MB']);
  assert.equal(s.form.photos.includes(big), false);
  assert.equal(s.form.pendingPhotoFiles.length, accepted.length);
  assert.equal(s.form.photos.length, accepted.length);

  const batch = [{ file: jpeg('e.jpg') }, { file: jpeg('f.jpg') }];
  s.validatePhoto(batch);
  assert.equal(s.form.pendingPhotoFiles.length, accepted.length + 2);
});

test('removing a photo from the uploader drops its pending file', async t => {
  const { s } = mount(t);
  const items = [{ file: jpeg('a.jpg') }, { file: jpeg('b.jpg') }];
  s.onPhotoListChange(items);
  s.validatePhoto(items);
  s.onPhotoListChange([items[1]]);
  assert.deepEqual(Array.from(s.form.pendingPhotoFiles, file => file.name), ['b.jpg']);
  s.onPhotoListChange(null);
  assert.equal(s.form.photos.length, 0);
  assert.equal(s.form.pendingPhotoFiles.length, 0);
});

test('saving an unreplaced position sends the inspection fields only', async t => {
  const rows = [detail(2, '2', { remark: '原备注', wear_condition: '轻微', blade_wear_amount: 1.5 })];
  const { s, saves } = mount(t, { details: rows });
  await s.loadTask();
  s.openEditor(s.details.value[0]);
  s.onResultConfirm({ selectedOptions: [{ text: '需关注', value: 'ATTENTION' }] });
  assert.equal(await s.saveCurrent(), true);
  assert.equal(saves[0].taskId, '7');
  const data = saves[0].data;
  assert.deepEqual(Object.keys(fieldsOf(data)).sort(), ['blade_wear_amount', 'check_result', 'detail_id', 'is_replaced', 'old_photo_ids', 'remark', 'wear_condition']);
  assert.deepEqual(fieldsOf(data), {
    detail_id: '2', is_replaced: 'false', check_result: 'ATTENTION', wear_condition: '轻微', blade_wear_amount: '1.5', remark: '原备注', old_photo_ids: '[]',
  });
  assert.deepEqual(photoNames(data), []);

  s.openEditor(s.details.value[0]);
  s.form.check_result = '无法识别';
  await s.saveCurrent();
  assert.equal(saves[1].data.get('check_result'), 'NOT_REPLACED');
});

test('saving a replaced position sends cost, new-tool fields, scan text, kept ids and renamed photos', async t => {
  const fieldOptions = { ring_types: [{ label: '标准刀圈', value: 'STD' }] };
  const rows = [detail(1, '1', {
    tool_cost_options: costOptions, blade_wear_amount: '2',
    old_photos: [{ id: 31, image_url: '/media/31.jpg', original_filename: '31.jpg' }],
  })];
  const { s, saves } = mount(t, { details: rows, fieldOptions });
  await s.loadTask();
  s.openEditor(s.details.value[0]);
  s.form.is_replaced = true;
  s.openCostPicker();
  s.onCostConfirm({ selectedOptions: [{ value: 12 }] });
  s.openOptionPicker('ring_type');
  s.onOptionConfirm({ selectedOptions: [{ text: '标准刀圈', value: 'STD' }] });
  assert.equal(s.form.ring_type_label, '标准刀圈');
  const files = [jpeg('IMG_1.JPG'), new Blob(['x'], { type: 'image/png' }), new File(['x'], 'camera', { type: 'image/jpeg' })];
  const items = files.map(file => ({ file, status: '', message: '' }));
  s.onPhotoListChange([...s.form.photos, ...items]);
  s.validatePhoto(items);
  s.form.scan_text = 'QR-001';
  assert.equal(await s.saveCurrent(), true);
  const data = saves[0].data;
  assert.deepEqual(fieldsOf(data), {
    detail_id: '1', is_replaced: 'true', check_result: 'NOT_REPLACED', wear_condition: '', blade_wear_amount: '2',
    tool_cost_id: '12', ring_type: 'STD', ring_manufacturer: 'B厂', shaft_condition: '', shaft_manufacturer: 'B厂',
    hub_condition: '', hub_manufacturer: 'B厂', scraper_manufacturer: 'B厂',
    remark: '扫码/备注：QR-001', old_photo_ids: '[31]',
  });
  assert.deepEqual(photoNames(data), ['IMG_1.JPG', 'old-tool-photo.png', 'old-tool-photo.jpg']);
});

test('remark merges scan text; an unselected cost and new-tool fields are sent empty', async t => {
  const rows = [detail(1, '1', { is_replaced: true, is_checked: true, old_photos: [{ id: 8, image_url: '/8.jpg' }], blade_wear_amount: 3 })];
  for (const [remark, scan, expected] of [['', 'QR', '扫码/备注：QR'], ['现场说明', 'QR', '现场说明\n扫码/备注：QR'], ['现场说明', '', '现场说明']]) {
    const { s, saves } = mount(t, { details: rows });
    await s.loadTask();
    s.openEditor(s.details.value[0]);
    s.form.remark = remark;
    s.form.scan_text = scan;
    await s.saveCurrent();
    const fields = fieldsOf(saves[0].data);
    assert.equal(fields.remark, expected);
    assert.deepEqual(
      ['tool_cost_id', 'ring_type', 'ring_manufacturer', 'shaft_condition', 'shaft_manufacturer', 'hub_condition', 'hub_manufacturer', 'scraper_manufacturer'].map(key => fields[key]),
      ['', '', '', '', '', '', '', ''],
    );
    assert.equal(fields.old_photo_ids, '[8]');
  }
});

test('upload files are the pending files first, then uploader files, without duplicates', async t => {
  const { s, saves } = mount(t, { details: [detail(1, '1', { blade_wear_amount: 1 })] });
  await s.loadTask();
  s.openEditor(s.details.value[0]);
  s.form.is_replaced = true;
  const [first, second] = [jpeg('first.jpg'), jpeg('second.jpg')];
  s.form.pendingPhotoFiles = [first];
  s.form.photos = [{ file: second }, { file: first }];
  await s.saveCurrent();
  assert.deepEqual(photoNames(saves[0].data), ['first.jpg', 'second.jpg']);
});

test('a replaced position without photos is not saved', async t => {
  const { s, saves, toasts } = mount(t);
  await s.loadTask();
  s.openEditor(s.details.value[0]);
  s.form.is_replaced = true;
  assert.equal(await s.saveCurrent(), false);
  s.form.photos = [{ url: '/not-saved.jpg' }];
  assert.equal(await s.saveCurrent(), false);
  assert.equal(s.saving.value, false);
  assert.equal(saves.length, 0);
  assert.deepEqual(toasts, ['换刀时必须上传旧刀照片', '换刀时至少选择一张图片上传']);
});

test('a read-only task never sends a save', async t => {
  const { s, saves } = mount(t, { task: { id: 7, status: 'COMPLETED' } });
  await s.loadTask();
  s.openEditor(s.details.value[0]);
  assert.equal(await s.saveCurrent(), false);
  assert.equal(saves.length, 0);
});

test('a successful save replaces the row, keeps the sort and refreshes the form from the response', async t => {
  const wait = deferred();
  const rows = [detail(1, '1'), detail(2, '2'), detail(3, '3')];
  const { s, toasts } = mount(t, { details: rows, save: () => wait.promise });
  await s.loadTask();
  s.openEditor(s.details.value[1]);
  s.form.is_replaced = true;
  s.form.scan_text = 'QR';
  const items = [{ file: jpeg('a.jpg') }];
  s.onPhotoListChange(items);
  s.validatePhoto(items);
  const saving = s.saveCurrent();
  assert.equal(s.saving.value, true);
  const saved = detail(2, '2', {
    is_checked: true, is_replaced: true, mobile_status: 'SAVED', remark: '扫码/备注：QR',
    old_photos: [{ id: 41, image_url: '/media/41.jpg', original_filename: 'a.jpg' }],
  });
  wait.resolve({ data: saved });
  assert.equal(await saving, true);
  assert.equal(s.saving.value, false);
  assert.deepEqual(nos(s.details.value), ['1', '2', '3']);
  assert.equal(s.details.value[1].is_checked, true);
  assert.equal(s.current.value.mobile_status, 'SAVED');
  assert.equal(s.form.remark, '扫码/备注：QR');
  assert.equal(s.form.scan_text, '');
  assert.equal(s.form.pendingPhotoFiles.length, 0);
  assert.deepEqual(plain(s.form.photos), [{ id: 41, url: '/media/41.jpg', isImage: true, message: 'a.jpg' }]);
  assert.deepEqual(toasts, ['已保存']);
});

test('a failed save keeps the row and the pending photos for a retry', async t => {
  const { s, toasts } = mount(t, { save: async () => { throw { msg: '刀位已锁定' }; } });
  await s.loadTask();
  s.openEditor(s.details.value[0]);
  s.form.is_replaced = true;
  const items = [{ file: jpeg('a.jpg') }];
  s.onPhotoListChange(items);
  s.validatePhoto(items);
  assert.equal(await s.saveCurrent(), false);
  assert.equal(s.saving.value, false);
  assert.equal(s.details.value[0].is_checked, false);
  assert.equal(s.form.pendingPhotoFiles.length, 1);
  assert.deepEqual(toasts, ['刀位已锁定']);
});

test('save and close closes the editor only after a successful save', async t => {
  let fail = true;
  const { s } = mount(t, { save: async data => { if (fail) throw new Error('offline'); return { data: detail(Number(data.get('detail_id')), '1', { is_checked: true }) }; } });
  await s.loadTask();
  s.openEditor(s.details.value[0]);
  await s.saveAndClose();
  assert.equal(s.editorVisible.value, true);
  fail = false;
  await s.saveAndClose();
  assert.equal(s.editorVisible.value, false);
  assert.equal(s.current.value, null);
});

test('previous/next follow the sorted filtered list and stop at both ends', async t => {
  const { s } = mount(t, { details: [detail(3, '10'), detail(1, '1'), detail(4, 'S1L'), detail(2, '2')] });
  await s.loadTask();
  s.move(1);
  assert.equal(s.current.value, null);
  s.openEditor(s.details.value[1]);
  const steps = [[1, '10'], [1, 'S1L'], [1, 'S1L'], [-1, '10'], [-1, '2'], [-1, '1'], [-1, '1']];
  for (const [offset, expected] of steps) {
    s.move(offset);
    assert.equal(s.current.value.cutter_position_no, expected);
  }
  s.keyword.value = '1';
  s.move(1);
  assert.equal(s.current.value.cutter_position_no, '10');
  s.move(1);
  assert.equal(s.current.value.cutter_position_no, 'S1L');
});

test('closing the editor clears the current position; back closes the editor before leaving', async t => {
  const { s, pushes } = mount(t);
  await s.loadTask();
  s.openEditor(s.details.value[0]);
  s.showResultPicker.value = true;
  s.costPickerVisible.value = true;
  s.goBack();
  assert.equal(s.editorVisible.value, false);
  assert.equal(s.current.value, null);
  assert.equal(s.showResultPicker.value, false);
  assert.equal(s.costPickerVisible.value, false);
  assert.deepEqual(pushes, []);
  s.goBack();
  assert.deepEqual(pushes, ['/mobile/tasks']);
});

// Pending fixtures keep is_checked and mobile_status consistent, so B-13 can change the counting field freely.
const submitFixture = () => [
  detail(1, '1'),
  detail(2, '2'),
  detail(3, '3', { is_checked: true, mobile_status: 'SAVED' }),
];

test('submit with the editor open saves first, then confirms, submits and reloads', async t => {
  const { s, hooks, events, confirms, toasts, submits } = mount(t, { details: submitFixture() });
  await hooks.onMounted();
  s.openEditor(s.details.value[0]);
  await s.submitTask();
  assert.deepEqual(events, ['get', 'save', 'confirm', 'submit', 'get']);
  assert.equal(confirms[0].title, '确认提交');
  assert.match(confirms[0].message, /还有 1 个刀位未交互/);
  assert.deepEqual(submits, ['7']);
  assert.deepEqual(toasts, ['已保存', '任务已提交']);
});

test('submit stops when saving the open editor fails or is rejected locally', async t => {
  const failing = mount(t, { details: submitFixture(), save: async () => { throw { msg: '保存失败' }; } });
  await failing.hooks.onMounted();
  failing.s.openEditor(failing.s.details.value[0]);
  await failing.s.submitTask();
  assert.deepEqual(failing.events, ['get', 'save']);
  assert.deepEqual(failing.toasts, ['保存失败']);

  const invalid = mount(t, { details: submitFixture() });
  await invalid.hooks.onMounted();
  invalid.s.openEditor(invalid.s.details.value[0]);
  invalid.s.form.is_replaced = true;
  await invalid.s.submitTask();
  assert.deepEqual(invalid.events, ['get']);
});

test('submit without pending positions skips the confirmation', async t => {
  const rows = submitFixture().map(row => ({ ...row, is_checked: true, mobile_status: 'SAVED' }));
  const { s, hooks, events } = mount(t, { details: rows });
  await hooks.onMounted();
  await s.submitTask();
  assert.deepEqual(events, ['get', 'submit', 'get']);
});

test('cancelling the confirmation never submits', async t => {
  const { s, hooks, events } = mount(t, { details: submitFixture(), confirm: () => Promise.reject('cancel') });
  await hooks.onMounted();
  await s.submitTask().catch(() => {});
  assert.deepEqual(events, ['get', 'confirm']);
});

test('a failed submit shows the error and does not reload', async t => {
  const rows = submitFixture().map(row => ({ ...row, is_checked: true, mobile_status: 'SAVED' }));
  const { s, hooks, events, toasts } = mount(t, { details: rows, submit: async () => { throw { response: { data: { msg: '当前任务不可提交' } } }; } });
  await hooks.onMounted();
  await s.submitTask();
  assert.deepEqual(events, ['get', 'submit']);
  assert.deepEqual(toasts, ['当前任务不可提交']);
});

test('submit does nothing on a read-only task or while a save is in flight', async t => {
  const locked = mount(t, { task: { id: 7, status: 'CANCELLED' } });
  await locked.hooks.onMounted();
  await locked.s.submitTask();
  assert.deepEqual(locked.events, ['get']);

  const wait = deferred();
  const busy = mount(t, { save: () => wait.promise });
  await busy.hooks.onMounted();
  busy.s.openEditor(busy.s.details.value[0]);
  const saving = busy.s.saveCurrent();
  await busy.s.submitTask();
  assert.deepEqual(busy.events, ['get', 'save']);
  wait.resolve({ data: detail(1, '1', { is_checked: true }) });
  await saving;
});

test('task GET runs once on mount, once per pull refresh and once after a successful submit', async t => {
  const { s, hooks, gets } = mount(t);
  assert.equal(typeof hooks.onMounted, 'function');
  assert.deepEqual(gets, []);
  await hooks.onMounted();
  assert.deepEqual(gets, ['7']);
  s.keyword.value = '2';
  s.statusFilter.value = 'PENDING';
  s.typeFilter.value = 'DISC';
  s.openEditor(s.details.value[0]);
  s.move(1);
  await s.saveCurrent();
  await s.saveAndClose();
  s.closeEditor();
  assert.equal(gets.length, 1);
  await s.loadTask();
  assert.equal(gets.length, 2);
  await s.submitTask();
  assert.equal(gets.length, 3);

  const template = descriptor.template.content;
  assert.match(template, /<van-pull-refresh\b[^>]*@refresh="loadTask"/);
  assert.match(template, /<van-button\b[^>]*@click="loadTask"[^>]*>重新加载<\/van-button>/);
  assert.equal(template.match(/"loadTask"/g).length, 2);
});

test.todo('B-01 a save still in flight when the user moves or closes must update the row it saved, without duplicates or a false error');
test.todo('B-02 closing the scanner by the overlay, or leaving during the camera prompt, must stop the camera');
test.todo('B-03 object URLs of photos that are no longer shown must be revoked');
test.todo('B-08 every unsupported or oversized photo in a multi-select batch must be removed, not only the first');
test.todo('B-09 clearing the blade wear amount must send an empty field so the old value is cleared');
test.todo('B-10 double-tapping submit must send one request; cancelling the confirmation must not leave an unhandled rejection');
test.todo('B-11 with a status filter, previous/next after a save must go to the nearest sorted position that still matches');
test.todo('B-13 the pending reminder before submit must count positions the same way as the list');
