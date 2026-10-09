// Real SFC setup/template/API with mocked HTTP and confirmation boundaries.
// VNode checks do not mount Element Plus or prove inherited disabled DOM behavior.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');
const ts = require('typescript');
const vue = require('vue');

const { descriptor, errors } = parse(fs.readFileSync(path.resolve(__dirname, '../OldToolRepairDialog.vue'), 'utf8'));
assert.deepEqual(errors, []);
const script = compileScript(descriptor, { id: 'repair-template-bindings' });
const template = compileTemplate({ source: descriptor.template.content, filename: 'OldToolRepairDialog.vue', id: 'repair-template-bindings' });
assert.deepEqual(template.errors, []);
const options = {
  ring_damage: [{ label: '崩裂', value: 'CHIPPED' }],
  bearing_failure_reasons: [{ label: '磨损', value: 'WEAR' }],
  hub_failure_reasons: [{ label: '断裂', value: 'BROKEN' }],
  old_tool_dispositions: [{ label: '报废', value: 'SCRAP' }],
};
const disc = {
  '刀圈磨损量': ['ring_wear_amount', 0], '偏磨量': ['bias_wear_amount', 1.25],
  '刀圈损坏情况': ['ring_damage', ['CHIPPED']], '刀圈掉齿数量': ['ring_tooth_loss_count', 0],
  '刀圈其他情况': ['ring_other_condition', '刀圈记录'], '轴承是否失效': ['bearing_failed', false],
  '轴承失效原因': ['bearing_failure_reasons', ['WEAR']], '轴承其他情况': ['bearing_other_condition', '轴承记录'],
  '刀毂是否损坏': ['hub_damaged', false], '刀毂失效原因': ['hub_failure_reasons', ['BROKEN']],
  '刀毂其他情况': ['hub_other_condition', '刀毂记录'],
};
const scraper = {
  '换下刀具磨损量': ['scraper_wear_amount', 0], '是否崩裂': ['scraper_chipped', false],
  '是否断裂': ['scraper_broken', false], '是否脱落': ['scraper_detached', false],
};
const common = {
  '报废 / 可维修': ['disposition', 'SCRAP'],
  '厂家返修结果': ['repair_result', '厂家结果'], '维修价格': ['repair_price', 0], '补充说明': ['remark', '补充记录'],
};

function compile(content, requireModule) {
  const context = { exports: {}, FormData, require: requireModule };
  vm.runInNewContext(ts.transpileModule(content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, context);
  return context.exports;
}
function children(node) {
  if (Array.isArray(node)) return node;
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node.children)) return node.children;
  if (typeof node.children === 'string') return [node.children];
  return Object.values(node.children || {}).filter(slot => typeof slot === 'function').flatMap(slot => slot());
}
function descendants(node) {
  if (!node || typeof node !== 'object') return [];
  return [...(Array.isArray(node) ? [] : [node]), ...children(node).flatMap(descendants)];
}
function textOf(node) {
  return typeof node === 'string' ? node : children(node).map(textOf).join('');
}
function only(nodes, predicate, label) {
  const found = nodes.filter(predicate);
  assert.equal(found.length, 1, label);
  return found[0];
}

async function setup(t, config = {}) {
  const requests = [], events = [], unmount = [];
  let confirmations = 0;
  const api = compile(fs.readFileSync(path.resolve(__dirname, '../api.ts'), 'utf8'), name => {
    assert.equal(name, '/@/utils/service');
    return { request: async request => {
      if (request.method === 'put') { requests.push(request); return { msg: '已保存' }; }
      assert.equal(request.method, 'get');
      if (config.failed) throw new Error('isolated load failure');
      if (request.url.endsWith('/field_options/')) return { data: options };
      assert.equal(request.url, '/api/shield/tool_change_detail/17/old_tool_record/');
      return { data: { trajectory: { status: 'CONFIRMED', display: config.type === 'SCRAPER' ? 'R5910 mm' : 'R1955 mm', source: '图纸依据' }, old_tool_record_data: {
        old_tool_number: 'OLD-17', inspection_status: config.status || 'PENDING_VENDOR_FEEDBACK',
        tool_track: '中心刀轨',
        photos: Array.from({ length: config.photos || 0 }, (_, id) => ({ id, name: `photo-${id}.png`, url: `/test-${id}.png` })),
      } } };
    } };
  });
  const component = compile(script.content, name => {
    if (name === 'vue') return { ...vue, onUnmounted: callback => unmount.push(callback) };
    if (name === './api') return api;
    if (name === './PhotoPreview.vue') return {};
    if (name === 'element-plus') return {
      ElMessage: { success() {}, warning() {}, error() {} },
      ElMessageBox: { confirm: async () => { confirmations++; } },
    };
    throw new Error(`Unexpected setup import ${name}`);
  }).default;
  const scope = vue.effectScope();
  const state = scope.run(() => component.setup({}, { expose() {}, emit: (...args) => events.push(args) }));
  t.after(() => { unmount.forEach(callback => callback()); scope.stop(); });
  await state.open({ id: 17, cutter_position_no: '17', tool_parent_type: config.type || 'DISC' }, { readOnly: config.readOnly === true });
  const { render } = compile(template.code, name => {
    assert.equal(name, 'vue');
    return { ...vue, resolveComponent: name => ({ name }), resolveDirective: () => ({}), withDirectives: node => node };
  });
  const root = () => render(vue.proxyRefs(state), []);
  const nodes = () => descendants(root());
  const mainDialog = () => only(nodes(), node => node.type?.name === 'el-dialog' && node.children?.footer, 'main dialog');
  const footer = () => descendants(mainDialog().children.footer()).filter(node => node.type?.name === 'el-button');
  const button = label => only(footer(), node => textOf(node).trim() === label, `footer ${label}`);
  const form = () => only(nodes(), node => node.type?.name === 'el-form', 'repair form');
  const control = label => {
    const item = only(nodes(), node => node.type?.name === 'el-form-item' && node.props?.label === label, `form item ${label}`);
    return only(descendants(item), node => ['el-input', 'el-input-number', 'el-select'].includes(node.type?.name), `control ${label}`);
  };
  return { state, requests, events, nodes, footer, button, form, control, confirmations: () => confirmations };
}

for (const [type, visible, hidden] of [['DISC', disc, scraper], ['SCRAPER', scraper, disc]]) {
  test(`${type} rendered controls are exclusive and serialize actual v-model edits`, async t => {
    const h = await setup(t, { type });
    const track = h.control('刀位轨迹');
    assert.ok(track.props.readonly !== undefined && track.props.readonly !== false);
    assert.equal(track.props['onUpdate:modelValue'], undefined);
    assert.equal(track.props['model-value'], type === 'SCRAPER' ? 'R5910 mm' : 'R1955 mm');
    for (const label of Object.keys(hidden)) assert.equal(h.nodes().some(node => node.type?.name === 'el-form-item' && node.props?.label === label), false);
    const values = { ...visible, ...common };
    for (const [label, [, value]] of Object.entries(values)) {
      const node = h.control(label);
      if (typeof value === 'boolean') {
        const booleanOptions = descendants(node).filter(child => child.type?.name === 'el-option');
        assert.deepEqual(booleanOptions.map(child => child.props.value), [true, false]);
      }
      if (Array.isArray(value)) assert.ok(node.props.multiple !== undefined && node.props.multiple !== false);
      node.props['onUpdate:modelValue'](value);
    }
    const upload = only(h.nodes(), node => node.type?.name === 'el-upload', 'photo upload');
    const photo = { uid: 1, name: 'isolated.png', status: 'ready', raw: new Blob(['isolated-photo'], { type: 'image/png' }) };
    upload.props['on-change'](photo, [photo]);
    await h.button('保存草稿').props.onClick();
    assert.equal(h.requests.length, 1);
    const request = h.requests[0];
    assert.equal(request.url, '/api/shield/tool_change_detail/17/old_tool_record/');
    assert.equal(request.method, 'put');
    assert.equal(request.timeout, 60000);
    assert.equal(request.data.get('workflow_action'), 'SAVE_DRAFT');
    assert.equal(request.data.get('old_tool_number'), 'OLD-17');
    assert.equal(request.data.has('tool_track'), false);
    for (const [, [key, value]] of Object.entries(values)) assert.equal(request.data.get(key), Array.isArray(value) ? JSON.stringify(value) : String(value), key);
    assert.equal(request.data.getAll('photos').length, 1);
    assert.equal(h.events.filter(([name]) => name === 'saved').length, 1);
  });
}

for (const [status, action, expected] of [['PENDING_VENDOR_FEEDBACK', '确认厂家反馈', 'CONFIRM'], ['CONFIRMED', '完成归档', 'CLOSE']]) {
  test(`${status} footer invokes its original workflow action`, async t => {
    const h = await setup(t, { status });
    assert.deepEqual(h.footer().map(node => textOf(node).trim()), ['取消', '保存草稿', action]);
    assert.equal(h.button(action).props.disabled, false);
    h.control('报废 / 可维修').props['onUpdate:modelValue']('SCRAP');
    await h.button(action).props.onClick();
    assert.equal(h.requests.length, 1);
    assert.equal(h.requests[0].data.get('workflow_action'), expected);
    assert.equal(h.confirmations(), expected === 'CLOSE' ? 1 : 0);
  });
}

for (const [name, config] of [['archived', { status: 'CLOSED' }], ['readonly', { readOnly: true }], ['failed load', { failed: true }]]) {
  test(`${name} template has no enabled write action and protects upload`, async t => {
    const h = await setup(t, config);
    assert.equal(h.form().props.disabled, true);
    const writeButtons = h.footer().filter(node => ['保存草稿', '确认厂家反馈', '完成归档'].includes(textOf(node).trim()));
    if (!config.failed) assert.equal(writeButtons.length, 0);
    for (const button of writeButtons) { assert.equal(button.props.disabled, true); await button.props.onClick(); }
    assert.equal(h.requests.length, 0);
    const uploads = h.nodes().filter(node => node.type?.name === 'el-upload');
    if (config.readOnly) assert.equal(uploads.length, 0);
    // Existing upload protection is inherited from the enclosing disabled ElForm.
    assert.equal(descendants(h.form()).filter(node => node.type?.name === 'el-upload').length, uploads.length);
  });
}

test('saving state locks footer, form and close icon in the actual template', async t => {
  const h = await setup(t);
  h.state.saving.value = true;
  assert.equal(h.form().props.disabled, true);
  assert.ok(h.footer().every(node => node.props.disabled === true));
  const dialog = only(h.nodes(), node => node.type?.name === 'el-dialog' && node.children?.footer, 'main dialog');
  assert.equal(dialog.props['show-close'], false);
});

test('upload retains manual image selection and the remaining five-photo allowance', async t => {
  for (const photos of [0, 4, 5]) {
    const h = await setup(t, { photos });
    const upload = only(h.nodes(), node => node.type?.name === 'el-upload', 'photo upload');
    assert.equal(upload.props.limit, 5 - photos);
    assert.equal(upload.props['auto-upload'], false);
    assert.equal(upload.props.accept, 'image/jpeg,image/jpg,image/png');
    const add = only(descendants(upload), node => node.type?.name === 'el-button', 'add photo');
    assert.equal(add.props.disabled, photos === 5);
    assert.equal(h.requests.length, 0);
  }
});

test('native selection and exceed handlers are wired and pending photos disable only the add button', async t => {
  const h = await setup(t, { photos: 4 });
  const upload = () => only(h.nodes(), node => node.type?.name === 'el-upload', 'photo upload');
  const file = { uid: 1, name: 'selected.png', status: 'ready', raw: new Blob(['photo'], { type: 'image/png' }) };
  upload().props['on-change'](file, [file]);
  assert.equal(h.state.fileList.value.length, 1);
  assert.equal(upload().props.disabled, false, 'pending files must remain removable at the limit');
  assert.equal(only(descendants(upload()), node => node.type?.name === 'el-button', 'add photo').props.disabled, true);
  assert.match(textOf(upload()), /待保存 1 张，还可选择 0 张/);
  upload().props['on-exceed']();
  assert.equal(h.state.fileList.value.length, 1);
  assert.equal(h.requests.length, 0);
  upload().props['on-remove'](file, []);
  assert.equal(h.state.availablePhotoSlots.value, 1);
  assert.equal(only(descendants(upload()), node => node.type?.name === 'el-button', 'add photo').props.disabled, false);
});

test('actual Element Plus file-list synchronization never restores rejected files and removal frees a slot', async t => {
  const { useHandlers } = await import('element-plus/es/components/upload/src/use-handlers.mjs');
  const h = await setup(t, { photos: 1 });
  let driver;
  const UploadDriver = {
    props: ['fileList', 'onChange', 'onRemove', 'listType'],
    setup(props) {
      driver = useHandlers(props, vue.ref());
      return () => null;
    },
  };
  // No DOM is needed for the real upload state machine and its update events.
  const renderer = vue.createRenderer({
    createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
    insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
    parentNode: () => null, nextSibling: () => null,
  });
  const app = renderer.createApp({ setup: () => () => {
    const upload = only(h.nodes(), node => node.type?.name === 'el-upload', 'photo upload');
    return vue.h(UploadDriver, { ...upload.props, listType: 'text' });
  } });
  app.mount({});
  t.after(() => app.unmount());
  driver.handleStart(new File(['unsupported'], 'bad.gif', { type: 'image/gif' }));
  driver.handleStart(new File(['valid'], 'valid.png', { type: 'image/png' }));
  await vue.nextTick();
  assert.equal(h.state.fileList.value.length, 1);
  assert.equal(driver.uploadFiles.value.length, 1);
  assert.equal(driver.uploadFiles.value[0].name, 'valid.png');
  const large = new File(['large'], 'large.png', { type: 'image/png' });
  Object.defineProperty(large, 'size', { value: 30 * 1024 * 1024 + 1 });
  driver.handleStart(large);
  await vue.nextTick();
  assert.equal(h.state.fileList.value.length, 1);
  assert.equal(driver.uploadFiles.value.length, 1);
  await driver.handleRemove(driver.uploadFiles.value[0]);
  await vue.nextTick();
  assert.equal(h.state.fileList.value.length, 0);
  assert.equal(h.state.availablePhotoSlots.value, 4);
  assert.equal(h.requests.length, 0);
});
