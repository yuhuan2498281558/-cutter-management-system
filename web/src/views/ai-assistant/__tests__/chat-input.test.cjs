// Run from web: node --test src/views/ai-assistant/__tests__/chat-input.test.cjs
// Run the actual ChatInputArea setup with the real question library; no browser or backend.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');

const transpile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText;
const componentPath = path.resolve(__dirname, '../components/ChatInputArea.vue');

const constants = (() => {
  const context = { exports: {} };
  vm.runInNewContext(transpile(fs.readFileSync(path.resolve(__dirname, '../constants.ts'), 'utf8')), context);
  return context.exports;
})();

function loadInput(overrides = {}) {
  const props = vue.reactive({ generating: false, disabled: false, routeMode: 'rule', ...overrides });
  const emitted = [];
  const context = { exports: {}, defineProps: () => props, defineEmits: () => (...args) => {
    emitted.push(args);
    if (args[0] === 'update:routeMode') props.routeMode = args[1];
  } };
  context.require = name => {
    if (name === 'vue') return vue;
    if (name === '../constants') return constants;
    throw new Error(`Unexpected import: ${name}`);
  };
  const source = fs.readFileSync(componentPath, 'utf8').match(/<script[^>]*>([\s\S]*?)<\/script>/)[1]
    + '\nexports.input = { MAX_QUERY_LENGTH, inputText, inputRef, quickParams, quickQuestionGroups, modelDataTypes, activeQuickGroup, activeQuickItemLabel, selectedQuickGroup, selectedQuickItem, quickNumberMissing, selectedModelDataTypes, selectedModelPrompt, modelPromptOptions, buildQuickLabel, handleQuickGroupChange, applyQuickQuestion, composeModelQuestion, handleModelDataTypesChange, handleSwitchRoute, handleSend, handleEnterKey };';
  vm.runInNewContext(transpile(source), context);
  return { props, emitted, ...context.exports.input };
}

// Element Plus stand-ins that expose only the state under test.
const stub = tag => ({
  inheritAttrs: false,
  props: ['disabled', 'loading', 'label'],
  setup: (props, { attrs, slots }) => () => vue.h(tag, { class: attrs.class, 'data-disabled': String(Boolean(props.disabled)), 'data-loading': String(Boolean(props.loading)) }, props.label ?? slots.default?.()),
});

async function renderInput(h) {
  const { renderToString } = require('@vue/server-renderer');
  const template = require('@vue/compiler-sfc').parse(fs.readFileSync(componentPath, 'utf8')).descriptor.template.content;
  const app = vue.createSSRApp({ template, setup: () => ({ ...h, routeMode: h.props.routeMode, generating: h.props.generating, disabled: h.props.disabled }) });
  for (const name of ['ElSelect', 'ElInputNumber']) app.component(name, stub('div'));
  app.component('ElOption', { inheritAttrs: false, props: ['label'], setup: props => () => vue.h('span', props.label) });
  app.component('ElButton', stub('button'));
  app.component('ElInput', { inheritAttrs: false, props: { maxlength: Number, showWordLimit: Boolean }, setup: props => () => vue.h('textarea', { 'data-maxlength': props.maxlength, 'data-word-limit': String(Boolean(props.showWordLimit)) }) });
  return renderToString(app);
}

const buttonAttrs = (html, text) => html.match(new RegExp(`<button([^>]*)>\\s*${text}\\s*</button>`))?.[1];
const isDisabled = attrs => /data-disabled="true"|\sdisabled(?=[\s>]|$)/.test(attrs);

function pick(h, groupTitle, label) {
  h.activeQuickGroup.value = groupTitle;
  h.activeQuickItemLabel.value = label;
  return h.selectedQuickItem.value;
}

test('default numbers stay inside each question bounds and start on the recent-ring question', () => {
  const h = loadInput();
  assert.deepEqual({ ...h.quickParams.value }, { openingLimit: 5, ringWindow: 100, topN: 10, interval: 50 });
  assert.equal(h.activeQuickGroup.value, '换刀/旧刀补录');
  assert.equal(h.activeQuickItemLabel.value, '近{n}环统计');
  for (const item of constants.quickQuestionGroups.flatMap(group => group.items).filter(entry => entry.numKey)) {
    const value = h.quickParams.value[item.numKey];
    assert.ok(value >= item.min && value <= item.max, `${item.label} default ${value}`);
  }
});

test('the six numbered questions generate the same labels and text as before', () => {
  for (const [group, label, expectedLabel, expectedQuery] of [
    ['换刀/旧刀补录', '近{n}环统计', '近100环统计', '统计最近100环的换刀情况，列出检查数、更换数、更换率、主要磨损类型和高频刀位'],
    ['趋势区间', '{n}环分段', '50环分段', '按50环为一段统计换刀趋势，列出每段检查数、更换数和更换率'],
    ['趋势区间', '近{n}环趋势', '近100环趋势', '分析最近100环换刀趋势，说明更换率是否上升'],
    ['开仓记录', '近{n}次开仓', '近5次开仓', '查询最近5次开仓情况，列出环号、开仓间隔、开仓时长、检查数、更换数和异常率'],
    ['刀位统计', '前{n}刀位', '前10刀位', '列出更换次数最高的前10个刀位，并说明刀具类型和主要磨损类型'],
    ['掘进动态', '近{n}环参数', '近100环参数', '分析最近100环掘进参数趋势'],
  ]) {
    const h = loadInput();
    const item = pick(h, group, label);
    assert.equal(h.buildQuickLabel(item), expectedLabel);
    h.applyQuickQuestion();
    assert.equal(h.inputText.value, expectedQuery);
  }
});

test('an edited number and a question without numbers are written verbatim', () => {
  const h = loadInput();
  pick(h, '换刀/旧刀补录', '近{n}环统计');
  h.quickParams.value.ringWindow = 120;
  h.applyQuickQuestion();
  assert.equal(h.inputText.value, '统计最近120环的换刀情况，列出检查数、更换数、更换率、主要磨损类型和高频刀位');
  pick(h, '换刀/旧刀补录', '换刀汇总');
  h.applyQuickQuestion();
  assert.equal(h.inputText.value, '统计当前项目全部刀具换刀情况，列出检查数、更换数、更换率和主要磨损类型');
});

test('switching to the model path composes the first template with the selected data types', () => {
  const h = loadInput();
  h.handleSwitchRoute('agent');
  assert.deepEqual(h.emitted, [['update:routeMode', 'agent']]);
  assert.equal(h.selectedModelPrompt.value, '分析近期换刀异常是否集中在特定磨损类型、刀具类型或刀位区域，并给出原因判断');
  assert.equal(h.inputText.value, '结合换刀/旧刀补录、地层信息数据，分析近期换刀异常是否集中在特定磨损类型、刀具类型或刀位区域，并给出原因判断');
});

test('model templates that already start with 结合 or 综合 are used as written', () => {
  const h = loadInput({ routeMode: 'agent' });
  h.selectedModelPrompt.value = '结合换刀明细识别异常磨损的主要模式、集中环段和需要复核的作业环节';
  h.composeModelQuestion();
  assert.equal(h.inputText.value, '结合换刀明细识别异常磨损的主要模式、集中环段和需要复核的作业环节');
  h.selectedModelDataTypes.value = ['掘进参数'];
  h.handleModelDataTypesChange();
  assert.equal(h.selectedModelPrompt.value, '分析掘进参数波动是否与异常磨损、换刀频率上升或刀位集中损伤有关');
  assert.equal(h.inputText.value, '结合掘进参数数据，分析掘进参数波动是否与异常磨损、换刀频率上升或刀位集中损伤有关');
  h.selectedModelDataTypes.value = [];
  h.handleModelDataTypesChange();
  assert.deepEqual(Array.from(h.modelPromptOptions.value), Array.from(constants.defaultModelPrompts));
  assert.equal(h.inputText.value, '结合地层、掘进参数和换刀记录，分析近期异常磨损的可能原因');
});

test('switching back to the rule path keeps the input and sending trims then clears it', () => {
  const h = loadInput({ routeMode: 'agent' });
  h.inputText.value = '  统计120环到180环刮刀S3L的更换次数  ';
  h.handleSwitchRoute('rule');
  assert.equal(h.props.routeMode, 'rule');
  assert.equal(h.inputText.value, '  统计120环到180环刮刀S3L的更换次数  ');
  h.handleSend();
  assert.deepEqual(h.emitted.at(-1), ['send', '统计120环到180环刮刀S3L的更换次数']);
  assert.equal(h.inputText.value, '');
});

test('a cleared number shows N in the label, disables 生成问题 with a reason and never writes null into the input', async () => {
  for (const cleared of [null, Number.NaN]) {
    const h = loadInput();
    h.inputText.value = '已有草稿';
    h.quickParams.value.ringWindow = cleared;
    assert.equal(h.buildQuickLabel(h.selectedQuickItem.value), '近N环统计');
    assert.equal(h.quickNumberMissing.value, true);
    h.applyQuickQuestion();
    assert.equal(h.inputText.value, '已有草稿');
    const html = await renderInput(h);
    assert.ok(isDisabled(buttonAttrs(html, '生成问题')), `生成问题 must be disabled for ${cleared}`);
    assert.match(html, /<span class="quick-hint">请先填写数字<\/span>/);
    assert.equal(/null|NaN|\{n\}/.test(html), false);
    pick(h, '换刀/旧刀补录', '换刀汇总');
    assert.equal(h.quickNumberMissing.value, false, 'questions without numbers are unaffected');
    pick(h, '换刀/旧刀补录', '近{n}环统计');
    h.quickParams.value.ringWindow = 120;
    const filled = await renderInput(h);
    assert.equal(isDisabled(buttonAttrs(filled, '生成问题')), false);
    assert.equal(filled.includes('请先填写数字'), false);
  }
});

test('dropdown labels show the current numbers instead of {n}', async () => {
  const h = loadInput();
  const html = await renderInput(h);
  assert.match(html, /<span>近100环统计<\/span>/);
  assert.equal(html.includes('{n}'), false);
  pick(h, '趋势区间', '{n}环分段');
  h.quickParams.value.interval = 30;
  assert.match(await renderInput(h), /<span>30环分段<\/span><span>近100环趋势<\/span>/);
});

test('the input shows its length against the backend limit of 10000 characters', async () => {
  const html = await renderInput(loadInput());
  assert.match(html, /<textarea data-maxlength="10000" data-word-limit="true"><\/textarea>/);
});

test('clicking the path that is already selected leaves the input alone', () => {
  const h = loadInput();
  h.handleSwitchRoute('agent');
  h.inputText.value = '我改写过的模型问题';
  h.handleSwitchRoute('agent');
  assert.equal(h.inputText.value, '我改写过的模型问题');
  assert.deepEqual(h.emitted, [['update:routeMode', 'agent']]);
  const rule = loadInput();
  rule.inputText.value = '统计120环到180环刮刀S3L的更换次数';
  rule.handleSwitchRoute('rule');
  assert.equal(rule.inputText.value, '统计120环到180环刮刀S3L的更换次数');
  assert.deepEqual(rule.emitted, []);
});

test('reset disables every control without a stop button; only generation shows stop and a spinner', async () => {
  for (const routeMode of ['rule', 'agent']) {
    const resetting = loadInput({ routeMode, generating: false, disabled: true });
    const html = await renderInput(resetting);
    assert.equal(html.includes('停止生成'), false);
    assert.equal(/data-disabled="false"/.test(html), false, `${routeMode}: every control is disabled during reset`);
    for (const text of ['规则路径', '模型路径', '发送']) assert.ok(isDisabled(buttonAttrs(html, text)), text);
    assert.match(buttonAttrs(html, '发送'), /data-loading="false"/);
    resetting.inputText.value = '重置中的问题';
    resetting.handleSend();
    assert.equal(resetting.emitted.some(([event]) => event === 'send'), false);
  }
  const generating = await renderInput(loadInput({ generating: true, disabled: true }));
  assert.ok(buttonAttrs(generating, '停止生成'));
  assert.match(buttonAttrs(generating, '发送'), /data-loading="true"/);
  const idle = await renderInput(loadInput());
  assert.equal(idle.includes('停止生成'), false);
  assert.equal(isDisabled(buttonAttrs(idle, '发送')), false);
  assert.match(buttonAttrs(idle, '发送'), /data-loading="false"/);
});

test('the page passes generation and reset state to the input area separately', () => {
  const { descriptor } = require('@vue/compiler-sfc').parse(fs.readFileSync(path.resolve(__dirname, '../index.vue'), 'utf8'));
  const find = node => node.tag === 'ChatInputArea' ? node : (node.children || []).map(find).find(Boolean);
  const bindings = Object.fromEntries(find(descriptor.template.ast).props.filter(prop => prop.name === 'bind').map(prop => [prop.arg.content, prop.exp.content]));
  assert.equal(bindings.generating, 'loading');
  assert.equal(bindings.disabled, 'loading || resetting');
  assert.equal(bindings.loading, undefined);
});

test('switching to the model path or changing data types keeps a draft the user wrote', () => {
  const h = loadInput();
  h.inputText.value = '统计120环到180环刮刀S3L的更换次数';
  h.handleSwitchRoute('agent');
  assert.equal(h.props.routeMode, 'agent');
  assert.equal(h.inputText.value, '统计120环到180环刮刀S3L的更换次数');
  h.selectedModelDataTypes.value = ['掘进参数'];
  h.handleModelDataTypesChange();
  assert.equal(h.inputText.value, '统计120环到180环刮刀S3L的更换次数');
  h.handleSwitchRoute('rule'); h.handleSwitchRoute('agent');
  assert.equal(h.inputText.value, '统计120环到180环刮刀S3L的更换次数');
});

test('text the input area filled in itself is still replaced until the user edits it', () => {
  const h = loadInput();
  h.applyQuickQuestion();
  h.handleSwitchRoute('agent');
  assert.equal(h.inputText.value, '结合换刀/旧刀补录、地层信息数据，分析近期换刀异常是否集中在特定磨损类型、刀具类型或刀位区域，并给出原因判断');
  h.selectedModelDataTypes.value = ['掘进参数'];
  h.handleModelDataTypesChange();
  assert.equal(h.inputText.value, '结合掘进参数数据，分析掘进参数波动是否与异常磨损、换刀频率上升或刀位集中损伤有关');
  h.inputText.value += '，重点看S1L';
  h.selectedModelDataTypes.value = ['地层信息'];
  h.handleModelDataTypesChange();
  assert.equal(h.inputText.value, '结合掘进参数数据，分析掘进参数波动是否与异常磨损、换刀频率上升或刀位集中损伤有关，重点看S1L');
  h.inputText.value = '   ';
  h.handleModelDataTypesChange();
  assert.equal(h.inputText.value, '结合地层信息数据，分析地层变化是否可能解释近期异常磨损，并指出对应磨损类型和高风险刀位');
});

test('choosing a template or pressing 生成问题 always writes the chosen question', () => {
  const h = loadInput({ routeMode: 'agent' });
  h.inputText.value = '我自己的问题';
  h.selectedModelPrompt.value = '结合换刀明细识别异常磨损的主要模式、集中环段和需要复核的作业环节';
  h.composeModelQuestion();
  assert.equal(h.inputText.value, '结合换刀明细识别异常磨损的主要模式、集中环段和需要复核的作业环节');
  const rule = loadInput();
  rule.inputText.value = '我自己的问题';
  rule.applyQuickQuestion();
  assert.equal(rule.inputText.value, '统计最近100环的换刀情况，列出检查数、更换数、更换率、主要磨损类型和高频刀位');
});
