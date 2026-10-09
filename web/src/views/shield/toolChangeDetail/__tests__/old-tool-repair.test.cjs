// Run from web: node --test src/views/shield/toolChangeDetail/__tests__/old-tool-repair.test.cjs
// Executes the real SFC setup with Vue reactivity and mocked API boundaries (no database writes).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');
const ts = require('typescript');
const vue = require('vue');

const source = process.env.REPAIR_TEST_REF
  ? execFileSync('git', ['show', `${process.env.REPAIR_TEST_REF}:web/src/views/shield/toolChangeDetail/OldToolRepairDialog.vue`], { encoding: 'utf8' })
  : fs.readFileSync(path.resolve(__dirname, '../OldToolRepairDialog.vue'), 'utf8');
const { descriptor, errors } = parse(source);
assert.deepEqual(errors, []);
const script = compileScript(descriptor, { id: 'old-tool-repair-test' });
const compiled = ts.transpileModule(script.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

const fields = {
  ring_damage: [{ value: 'CHIPPED', label: '崩裂' }],
  bearing_failure_reasons: [{ value: 'WEAR', label: '磨损' }],
  hub_failure_reasons: [{ value: 'BROKEN', label: '断裂' }],
  old_tool_dispositions: [{ value: 'SCRAP', label: '报废' }, { value: 'REPAIRABLE', label: '可维修' }],
};
const record = (number = 'OLD-1', status = 'PENDING_VENDOR_FEEDBACK') => ({
  data: { old_tool_record_data: { old_tool_number: number, inspection_status: status, remark: '原补充说明' } },
});
function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
function setup(t, overrides = {}) {
  const writes = [], emitted = [], notices = [], unmount = [];
  const api = {
    GetOldToolRecord: async () => record(),
    GetToolChangeOptions: async () => ({ data: structuredClone(fields) }),
    UpdateOldToolRecord: async (id, data) => { writes.push({ id, data }); return { msg: '已保存' }; },
    ...overrides,
  };
  const context = {
    exports: {}, FormData,
    require(name) {
      if (name === 'vue') return { ...vue, onUnmounted: fn => unmount.push(fn) };
      if (name === './api') return api;
      if (name === './PhotoPreview.vue') return {};
      if (name === 'element-plus') return {
        ElMessage: Object.fromEntries(['success', 'error', 'warning'].map(level => [level, text => notices.push({ level, text })])),
        ElMessageBox: { confirm: overrides.confirm || (async () => {}) },
      };
      throw new Error(`Unexpected module ${name}`);
    },
  };
  vm.runInNewContext(compiled, context);
  const scope = vue.effectScope();
  const state = scope.run(() => context.exports.default.setup({}, { expose() {}, emit: (...args) => emitted.push(args) }));
  t.after(() => { unmount.forEach(fn => fn()); scope.stop(); });
  return { state, writes, emitted, notices, unmount };
}

test('loads backend options into the rendered reactive state', async t => {
  const { state: s } = setup(t);
  const openOptions = { readOnly: false };
  await s.open({ id: 1, tool_parent_type: 'DISC' }, openOptions);
  for (const key of Object.keys(fields)) {
    assert.equal(JSON.stringify(s.options[key]), JSON.stringify(fields[key]));
  }
  assert.deepEqual(openOptions, { readOnly: false });
  assert.equal(s.form.old_tool_number, 'OLD-1');
});

test('repair uses the latest position trajectory without resubmitting legacy free text', async t => {
  const trajectory = { status: 'CONFIRMED', radius_mm: 1955, display: 'R1955 mm', source: '图纸依据' };
  const { state: s, writes } = setup(t, {
    GetOldToolRecord: async () => ({ data: { trajectory, old_tool_record_data: { tool_track: '中心刀轨' } } }),
  });
  await s.open({ id: 17, tool_parent_type: 'DISC', trajectory: { display: '旧刀位值' } });
  assert.equal(s.trajectoryDisplay.value, 'R1955 mm');
  assert.equal(s.form.tool_track, undefined);
  assert.equal(writes.length, 0);
  await s.save('SAVE_DRAFT');
  assert.equal(writes[0].data.has('tool_track'), false);
});

test('switching to a pending or missing trajectory never reuses a prior radius or legacy track', async t => {
  const { state: s, writes } = setup(t, {
    GetOldToolRecord: async id => ({ data: {
      trajectory: id === 1
        ? { status: 'CONFIRMED', radius_mm: 5910, display: 'R5910 mm' }
        : id === 2 ? { status: 'PENDING_REVIEW', radius_mm: null, display: '待按最终图纸核对' } : null,
      old_tool_record_data: { tool_track: '外周刀轨' },
    } }),
  });
  await s.open({ id: 1, tool_parent_type: 'SCRAPER' });
  assert.equal(s.trajectoryDisplay.value, 'R5910 mm');
  for (const id of [2, 3]) {
    await s.open({ id, tool_parent_type: 'SCRAPER' });
    assert.equal(s.trajectoryDisplay.value, '待按最终图纸核对');
    await s.save('SAVE_DRAFT');
    assert.equal(writes.at(-1).data.has('tool_track'), false);
  }
});

test('archived repair shows the position trajectory without writing the historical record', async t => {
  const { state: s, writes } = setup(t, {
    GetOldToolRecord: async () => ({ data: {
      trajectory: { status: 'CONFIRMED', radius_mm: 1555, display: 'R1555 mm' },
      old_tool_record_data: { tool_track: '中心刀轨', inspection_status: 'CLOSED' },
    } }),
  });
  await s.open({ id: 13, tool_parent_type: 'DISC' }, { readOnly: true });
  assert.equal(s.trajectoryDisplay.value, 'R1555 mm');
  await s.save('SAVE_DRAFT');
  assert.equal(writes.length, 0);
});

function setupPhoto(t, values = {}) {
  const { descriptor } = parse(fs.readFileSync(path.resolve(__dirname, '../PhotoPreview.vue'), 'utf8'));
  const script = compileScript(descriptor, { id: 'photo-preview-test' });
  const context = { exports: {}, require(name) { assert.equal(name, 'vue'); return vue; } };
  vm.runInNewContext(ts.transpileModule(script.content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, context);
  const props = vue.reactive({ active: true, src: '/photo-a.png?signature=original', name: '测试照片', ...values });
  const scope = vue.effectScope();
  const state = scope.run(() => context.exports.default.setup(props, { expose() {} }));
  t.after(() => scope.stop());
  return { state, props, scope };
}

function selectedPhoto(name, type, size = 1024, uid = name) {
  return { uid, name, status: 'ready', raw: { name, type, size } };
}

test('photo selection rejects unsupported types and over-30MB files without dropping valid selections', async t => {
  const { state: s, notices, writes } = setup(t);
  await s.open({ id: 1 });
  const valid = selectedPhoto('valid.png', 'image/png');
  const wrong = selectedPhoto('animation.gif', 'image/gif');
  const large = selectedPhoto('large.jpg', 'image/jpeg', 30 * 1024 * 1024 + 1);
  s.handlePhotoChange(valid, [valid]);
  s.handlePhotoChange(wrong, [valid, wrong]);
  assert.equal(s.fileList.value.length, 1);
  s.handlePhotoChange(large, [valid, wrong, large]);
  assert.equal(s.fileList.value.length, 1);
  assert.equal(s.fileList.value[0].name, 'valid.png');
  assert.match(notices[0].text, /animation.gif.*JPG \/ JPEG \/ PNG/);
  assert.match(notices[1].text, /large.jpg.*30MB/);
  assert.equal(writes.length, 0);
});

test('a mixed native selection cannot reintroduce an earlier rejected file', async t => {
  const { state: s } = setup(t);
  await s.open({ id: 1 });
  const invalid = selectedPhoto('not-a-photo.pdf', 'application/pdf');
  const valid = selectedPhoto('photo.png', 'image/png');
  s.handlePhotoChange(invalid, [invalid]);
  s.handlePhotoChange(valid, [invalid, valid]);
  assert.equal(s.fileList.value.length, 1);
  assert.equal(s.fileList.value[0].name, 'photo.png');
});

test('all server-supported MIME types accept the exact 30MB boundary', async t => {
  const { state: s, notices } = setup(t);
  await s.open({ id: 1 });
  for (const type of ['image/jpeg', 'image/jpg', 'image/png']) {
    const file = selectedPhoto('boundary-photo', type, 30 * 1024 * 1024);
    s.handlePhotoChange(file, [file]);
    assert.equal(s.fileList.value.length, 1);
  }
  assert.equal(notices.length, 0);
});

test('photo allowance includes pending files, recovers after removal and resets for another record', async t => {
  const { state: s, notices } = setup(t, {
    GetOldToolRecord: async id => ({ data: { old_tool_record_data: { photos: id === 1 ? [{ id: 1 }, { id: 2 }] : [] } } }),
  });
  await s.open({ id: 1 });
  const files = ['a.png', 'b.png', 'c.png'].map(name => selectedPhoto(name, 'image/png'));
  s.handlePhotoChange(files[2], files);
  assert.equal(s.availablePhotoSlots.value, 0);
  s.handlePhotoExceed();
  assert.match(notices[0].text, /已保存 2 张、待保存 3 张.*再选 0 张/);
  assert.equal(s.fileList.value.length, 3);
  s.fileList.value.splice(1, 1);
  assert.equal(s.availablePhotoSlots.value, 1);
  await s.open({ id: 2 });
  assert.equal(s.fileList.value.length, 0);
  assert.equal(s.availablePhotoSlots.value, 5);
});

test('all save actions reject invalid or excessive pending photos before posting', async t => {
  for (const action of ['SAVE_DRAFT', 'CONFIRM', 'CLOSE']) {
    const { state: s, writes } = setup(t);
    await s.open({ id: 1 });
    s.form.disposition = 'SCRAP';
    s.fileList.value = [selectedPhoto('bad.gif', 'image/gif')];
    await s.save(action);
    assert.equal(writes.length, 0);
    s.fileList.value = Array.from({ length: 6 }, (_, i) => selectedPhoto(`${i}.png`, 'image/png'));
    await s.save(action);
    assert.equal(writes.length, 0);
    assert.equal(s.saving.value, false);
    assert.equal(s.visible.value, true);
  }
});

test('photo failure retries the unchanged URL once and accepts the new load', t => {
  const { state: s, props } = setupPhoto(t);
  assert.equal(s.status.value, 'loading');
  const first = s.imageRequest.value;
  first.onError(); assert.equal(s.status.value, 'error');
  s.retry(); const retried = s.imageRequest.value;
  assert.notEqual(retried.id, first.id);
  assert.equal(retried.src, props.src);
  s.retry(); assert.equal(s.imageRequest.value, retried);
  first.onLoad(); assert.equal(s.status.value, 'loading');
  retried.onLoad(); assert.equal(s.status.value, 'loaded');
});

test('switching photos rejects both success and failure callbacks from the previous image', t => {
  const { state: s, props } = setupPhoto(t);
  const first = s.imageRequest.value;
  props.src = '/photo-b.png';
  const second = s.imageRequest.value;
  first.onLoad(); assert.equal(s.status.value, 'loading');
  second.onLoad(); first.onError();
  assert.equal(s.status.value, 'loaded');
  assert.equal(second.src, '/photo-b.png');
});

test('closing and reopening the same photo restarts loading and ignores late events', t => {
  const { state: s, props } = setupPhoto(t);
  const first = s.imageRequest.value;
  props.active = false;
  first.onError(); assert.equal(s.status.value, 'idle');
  assert.equal(s.imageRequest.value, null);
  props.active = true;
  assert.equal(s.status.value, 'loading');
  first.onLoad(); assert.equal(s.status.value, 'loading');
  assert.notEqual(s.imageRequest.value.id, first.id);
});

test('unmounting a photo preview prevents callbacks from altering its state', t => {
  const { state: s, scope } = setupPhoto(t);
  const image = s.imageRequest.value;
  scope.stop(); image.onLoad(); image.onError();
  assert.equal(s.status.value, 'loading');
});

test('an inactive or empty photo source never creates an image request', t => {
  const { state: s, props } = setupPhoto(t, { active: false });
  assert.equal(s.imageRequest.value, null);
  props.src = ''; props.active = true;
  assert.equal(s.imageRequest.value, null);
  assert.equal(s.status.value, 'idle');
});

test('loading blocks writes, including direct handler calls', async t => {
  const pending = deferred();
  const { state: s, writes } = setup(t, { GetOldToolRecord: () => pending.promise });
  const opening = s.open({ id: 1 });
  assert.equal(s.canSave.value, false);
  await s.save('SAVE_DRAFT');
  assert.equal(writes.length, 0);
  pending.resolve(record());
  await opening;
  assert.equal(s.canSave.value, true);
});

test('failed load blocks writes and retry recovers', async t => {
  let fail = true;
  const { state: s, writes } = setup(t, {
    GetToolChangeOptions: async () => { if (fail) throw new Error('network'); return { data: fields }; },
  });
  await s.open({ id: 1 });
  assert.ok(s.loadError.value);
  assert.equal(s.loading.value, false);
  await s.save('SAVE_DRAFT');
  assert.equal(writes.length, 0);
  fail = false;
  await s.retryLoad();
  assert.equal(s.loadError.value, '');
  assert.equal(s.canSave.value, true);
});

test('malformed options are not treated as a successful load', async t => {
  const { state: s } = setup(t, { GetToolChangeOptions: async () => ({ data: {} }) });
  await s.open({ id: 1 });
  assert.equal(s.loaded.value, false);
  assert.ok(s.loadError.value);
});

test('late response from A cannot overwrite already loaded B', async t => {
  const first = deferred();
  const { state: s } = setup(t, { GetOldToolRecord: id => id === 1 ? first.promise : Promise.resolve(record('OLD-B')) });
  const a = s.open({ id: 1 });
  await s.open({ id: 2 });
  first.resolve(record('OLD-A'));
  await a;
  assert.equal(s.row.value.id, 2);
  assert.equal(s.form.old_tool_number, 'OLD-B');
  assert.equal(s.canSave.value, true);
});

test('stale failure does not clear B loading state or show an error', async t => {
  const first = deferred(), second = deferred();
  const { state: s } = setup(t, { GetOldToolRecord: id => id === 1 ? first.promise : second.promise });
  const a = s.open({ id: 1 });
  const b = s.open({ id: 2 });
  first.reject(new Error('A failed'));
  await a;
  assert.equal(s.loading.value, true);
  assert.equal(s.loadError.value, '');
  second.resolve(record('OLD-B'));
  await b;
  assert.equal(s.form.old_tool_number, 'OLD-B');
});

test('closing and unmounting invalidate outstanding loads', async t => {
  for (const close of ['close', 'unmount']) {
    const pending = deferred();
    const { state: s, unmount } = setup(t, { GetOldToolRecord: () => pending.promise });
    const opening = s.open({ id: 1 });
    if (close === 'close') s.visible.value = false;
    else unmount.forEach(fn => fn());
    pending.resolve(record());
    await opening;
    assert.equal(s.loaded.value, false);
    assert.equal(s.form.old_tool_number, '');
  }
});

test('read-only and archived records reject all save actions', async t => {
  for (const readOnly of [true, false]) {
    const { state: s, writes } = setup(t, {
      GetOldToolRecord: async () => record('OLD-1', readOnly ? 'PENDING_VENDOR_FEEDBACK' : 'CLOSED'),
    });
    await s.open({ id: 1 }, { readOnly });
    for (const action of ['SAVE_DRAFT', 'CONFIRM', 'CLOSE']) await s.save(action);
    assert.equal(writes.length, 0);
    assert.equal(s.canSave.value, false);
  }
});

test('draft preserves identity, false/zero values, arrays and files in the multipart contract', async t => {
  const { state: s, writes, emitted } = setup(t);
  await s.open({ id: 7 });
  Object.assign(s.form, { bearing_failed: false, ring_wear_amount: 0, ring_damage: ['CHIPPED'], remark: '补录说明' });
  s.fileList.value = [{ raw: new Blob(['test-photo'], { type: 'image/png' }) }];
  await s.save('SAVE_DRAFT');
  assert.equal(writes.length, 1);
  assert.equal(writes[0].id, 7);
  const data = writes[0].data;
  assert.equal(data.get('workflow_action'), 'SAVE_DRAFT');
  assert.equal(data.get('old_tool_number'), 'OLD-1');
  assert.equal(data.get('bearing_failed'), 'false');
  assert.equal(data.get('ring_wear_amount'), '0');
  assert.equal(data.get('ring_damage'), '["CHIPPED"]');
  assert.equal(data.get('remark'), '补录说明');
  assert.equal(data.getAll('photos').length, 1);
  assert.equal(emitted.length, 1);
  assert.equal(s.visible.value, false);
});

test('save lock prevents duplicates and switching records while saving', async t => {
  const pending = deferred();
  let count = 0;
  const { state: s } = setup(t, { UpdateOldToolRecord: () => { count++; return pending.promise; } });
  await s.open({ id: 1 });
  const saving = s.save('SAVE_DRAFT');
  await s.save('SAVE_DRAFT');
  await s.open({ id: 2 });
  assert.equal(count, 1);
  assert.equal(s.row.value.id, 1);
  pending.resolve({ msg: 'ok' });
  await saving;
  assert.equal(s.saving.value, false);
});

test('failed save keeps user input for retry', async t => {
  const { state: s, emitted } = setup(t, { UpdateOldToolRecord: async () => { throw new Error('network'); } });
  await s.open({ id: 1 });
  s.form.remark = '保留填写内容';
  await s.save('SAVE_DRAFT');
  assert.equal(s.form.remark, '保留填写内容');
  assert.equal(s.visible.value, true);
  assert.equal(s.canSave.value, true);
  assert.equal(emitted.length, 0);
});

test('archive confirmation is locked and cancellation performs no write', async t => {
  const pending = deferred();
  const { state: s, writes } = setup(t, {
    GetOldToolRecord: async () => record('OLD-1', 'CONFIRMED'),
    confirm: () => pending.promise,
  });
  await s.open({ id: 1 });
  s.form.disposition = 'SCRAP';
  const saving = s.save('CLOSE');
  await s.save('SAVE_DRAFT');
  assert.equal(s.saving.value, true);
  pending.reject('cancel');
  await saving;
  assert.equal(writes.length, 0);
  assert.equal(s.canSave.value, true);
});

test('template compiles and save controls bind to the same readiness guard', () => {
  const result = compileTemplate({ source: descriptor.template.content, filename: 'OldToolRepairDialog.vue', id: 'repair-test', compilerOptions: { bindingMetadata: script.bindings } });
  assert.deepEqual(result.errors, []);
  assert.equal((descriptor.template.content.match(/:disabled="!canSave"/g) || []).length, 4);
  assert.match(descriptor.template.content, /v-if="loadError"/);
  assert.match(descriptor.template.content, /@click="retryLoad"/);
});

test('missing old record can still start a new draft after successful loading', async t => {
  const { state: s, writes } = setup(t, { GetOldToolRecord: async () => ({ data: { old_tool_record_data: null } }) });
  await s.open({ id: 1 });
  assert.equal(s.canSave.value, true);
  await s.save('SAVE_DRAFT');
  assert.equal(writes.length, 1);
});

test('confirmation requires disposition and preserves the CONFIRM action', async t => {
  const { state: s, writes } = setup(t);
  await s.open({ id: 1 });
  await s.save('CONFIRM');
  assert.equal(writes.length, 0);
  s.form.disposition = 'SCRAP';
  await s.save('CONFIRM');
  assert.equal(writes[0].data.get('workflow_action'), 'CONFIRM');
  assert.equal(writes[0].data.get('disposition'), 'SCRAP');
});

test('repair archive requires repair result and preserves the CLOSE action', async t => {
  const { state: s, writes } = setup(t, { GetOldToolRecord: async () => record('OLD-1', 'CONFIRMED') });
  await s.open({ id: 1 });
  s.form.disposition = 'REPAIRABLE';
  await s.save('CLOSE');
  assert.equal(writes.length, 0);
  s.form.repair_result = '维修完成';
  await s.save('CLOSE');
  assert.equal(writes[0].data.get('workflow_action'), 'CLOSE');
  assert.equal(writes[0].data.get('repair_result'), '维修完成');
});
