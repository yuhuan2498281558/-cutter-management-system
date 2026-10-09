const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');

const source = fs.readFileSync(path.resolve(__dirname, '../components/MemorySlotBadge.vue'), 'utf8');
function setup(memoryInfo) {
  const props = vue.reactive({ memoryInfo, contextMode: 'auto', pendingClears: [], disabled: false });
  const script = source.match(/<script[^>]*>([\s\S]*?)<\/script>/)[1];
  const context = { exports: {}, defineProps: () => props, defineEmits: () => () => {}, require: name => {
    if (name === 'vue') return vue;
    throw new Error(`Unexpected import ${name}`);
  } };
  vm.runInNewContext(ts.transpileModule(script + '\nexports.state = { slotLabels, modeHint };', { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, context);
  return { props, ...context.exports.state };
}

test('shows actual range/type/position and never revives stale names when values are empty', () => {
  const h = setup({ activeSlots: { ring_range: [100, 300], tool_type: 'DISC', cutter_position_no: '30' }, slots: ['tool_type'] });
  assert.deepEqual(Array.from(h.slotLabels.value, item => item.label), ['100–300 环', '滚刀', '刀位 30']);
  h.props.memoryInfo.activeSlots = {};
  assert.equal(h.slotLabels.value.length, 0);
});

test('old server values remain explicitly unknown and internal fields are hidden', () => {
  const h = setup({ slots: ['ring_range', 'project_id', 'user_id'] });
  assert.deepEqual(Array.from(h.slotLabels.value, item => item.label), ['环号范围（值未提供）']);
  h.props.contextMode = 'new';
  assert.equal(h.modeHint.value, '按本次问题重新确定条件');
});

test('actual component script and controls template compile together', () => {
  const { descriptor } = parse(source);
  const script = compileScript(descriptor, { id: 'memory-controls' });
  const result = compileTemplate({ source: descriptor.template.content, filename: 'MemorySlotBadge.vue', id: 'memory-controls', compilerOptions: { bindingMetadata: script.bindings } });
  assert.deepEqual(result.errors, []);
  assert.match(descriptor.template.content, /已保存/);
  assert.doesNotMatch(descriptor.template.content, /已记住/);
});
