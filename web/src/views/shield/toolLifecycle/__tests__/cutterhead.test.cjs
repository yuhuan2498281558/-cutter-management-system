const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');

test('history uses all 122 real mapped cutter positions within the real image', () => {
  const source = fs.readFileSync(path.resolve(__dirname, '../../../../constants/cutterPositions.ts'), 'utf8');
  const context = { exports: {} };
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
  const positions = context.exports.ACTIVE_CUTTER_POSITIONS;
  assert.equal(positions.length, 122);
  assert.equal(new Set(positions.map(x => x.code)).size, 122);
  for (const item of positions) {
    assert.ok(item.x >= 0 && item.x <= 1900 && item.y >= 0 && item.y <= 2100, item.code);
    assert.ok(!item.code.startsWith('G') && !item.code.startsWith('H'));
  }
});

test('both history SFCs compile script and template without errors', () => {
  for (const filename of ['index.vue', 'CutterheadHistory.vue']) {
    const source = fs.readFileSync(path.resolve(__dirname, '..', filename), 'utf8');
    const { descriptor, errors } = parse(source, { filename });
    assert.deepEqual(errors, []);
    const script = compileScript(descriptor, { id: filename });
    const template = compileTemplate({ source: descriptor.template.content, filename, id: filename,
      compilerOptions: { bindingMetadata: script.bindings } });
    assert.deepEqual(template.errors, []);
  }
});

test('cropped drawing keeps all original hit targets visible and selectable, including outer cutters', t => {
  const { setup } = require('../../analysis/__tests__/helpers.cjs');
  const context = { exports: {} };
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../../../../constants/cutterPositions.ts'), 'utf8'),
    { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
  const emitted = [];
  const h = setup(t, '../toolLifecycle/CutterheadHistory.vue', {
    props: { modelValue: '3', $emit: (...args) => emitted.push(args) },
    modules: { '/@/constants/cutterPositions': context.exports, '/@/utils/engineeringAssets': { CUTTERHEAD_IMAGE: '/configured-cutterhead.png' } },
  });
  const nodes = h.nodes();
  const svg = nodes.find(node => node.type === 'svg');
  const [left, top, width, height] = svg.props.viewBox.split(' ').map(Number);
  const groups = nodes.filter(node => node.type === 'g');
  assert.equal(groups.length, 122);
  for (const position of context.exports.ACTIVE_CUTTER_POSITIONS) {
    const group = groups.find(node => node.props['aria-label'] === `${position.code}号刀位`);
    const marker = group.children.find(node => node.type === 'circle');
    assert.equal(marker.props.cx, position.x);
    assert.equal(marker.props.cy, position.y);
    assert.ok(position.x - 28 >= left && position.x + 28 <= left + width, position.code);
    assert.ok(position.y - 28 >= top && position.y + 28 <= top + height, position.code);
    assert.equal(group.props['clip-path'], undefined, 'background crop must never clip hit targets');
  }
  const outer = groups.find(node => node.props['aria-label'] === 'y5号刀位');
  outer.props.onClick();
  assert.deepEqual(emitted.at(-1), ['update:modelValue', 'y5']);
  const keyHandlers = Array.isArray(outer.props.onKeydown) ? outer.props.onKeydown : [outer.props.onKeydown];
  keyHandlers.forEach(handler => handler({ key: 'Enter', preventDefault() {} }));
  assert.deepEqual(emitted.at(-1), ['update:modelValue', 'y5']);
  h.props.modelValue = 'y5';
  assert.equal(h.nodes().find(node => node.type === 'g' && node.props['aria-label'] === 'y5号刀位').props['aria-pressed'], true);
  assert.equal(nodes.find(node => node.type === 'image').props['clip-path'], 'url(#lifecycle-cutter-face)');
  assert.equal(nodes.find(node => node.type === 'image').props.href, '/configured-cutterhead.png');
});

test('segment details never import another deployment or unconfirmed removal', () => {
  const source = fs.readFileSync(path.resolve(__dirname, '../serviceTimeline.ts'), 'utf8');
  const context = { exports: {} };
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
  const result = context.exports.mergeServiceTimeline(
    [{ event: 'INSTALL', detail_id: 1, time: 'opening-time' }, { event: 'REMOVE', detail_id: 2 }],
    [{ event: 'INSTALL', detail_id: 1, time: 'entry-time', operator: 'A' },
      { event: 'INSTALL', detail_id: 9, operator: 'other-project' },
      { event: 'REMOVE_INSPECT', detail_id: 2, pairing_confirmed: false, repair_result: 'other-tool' },
      { event: 'REMOVE_INSPECT', detail_id: 10, repair_result: 'other-deployment' }]);
  assert.equal(result.length, 2);
  assert.equal(result[0].operator, 'A');
  assert.equal(result[0].time, 'opening-time');
  assert.equal(result[1].repair_result, undefined);
});
