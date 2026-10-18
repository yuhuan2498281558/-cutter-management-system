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
    + '\nexports.input = { MAX_QUERY_LENGTH, inputText, inputRef, quickParams, selectedQuickParams, quickQuestionGroups, activeQuickGroup, activeQuickItemLabel, selectedQuickGroup, selectedQuickItem, quickParamHint, buildQuickLabel, handleQuickGroupChange, applyQuickQuestion, FOCUS_SOURCES, TOOL_TYPE_OPTIONS, selectedSources, selectedTemplateTitle, selectedTemplate, selectedTemplateParams, templateParams, templateParamHint, visibleTemplates, handleTemplateChange, composeModelQuestion, handleModelDataTypesChange, handleSwitchRoute, handleSend, handleEnterKey };';
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
  app.component('ElInput', {
    inheritAttrs: false,
    props: { type: String, maxlength: Number, showWordLimit: Boolean, placeholder: String, disabled: Boolean },
    setup: props => () => (props.type === 'textarea'
      ? vue.h('textarea', { 'data-maxlength': props.maxlength, 'data-word-limit': String(props.showWordLimit) })
      : vue.h('input', { 'data-placeholder': props.placeholder, 'data-disabled': String(props.disabled) })),
  });
  // Drop SSR fragment markers so the assertions read like the browser DOM.
  return (await renderToString(app)).replace(/<!--[[\]]-->/g, '');
}

const buttonAttrs = (html, text) => html.match(new RegExp(`<button([^>]*)>\\s*${text}\\s*</button>`))?.[1];
const isDisabled = attrs => /data-disabled="true"|\sdisabled(?=[\s>]|$)/.test(attrs);

function pick(h, groupTitle, label) {
  h.activeQuickGroup.value = groupTitle;
  h.activeQuickItemLabel.value = label;
  return h.selectedQuickItem.value;
}

test('every question starts from its own default and the first question is selected', () => {
  const h = loadInput();
  assert.equal(h.activeQuickGroup.value, '换刀与磨损');
  assert.equal(h.activeQuickItemLabel.value, '最近{n}环换刀');
  for (const item of constants.quickQuestionGroups.flatMap(group => group.items)) {
    assert.deepEqual({ ...h.quickParams.value[item.label] }, { n: item.defaultValue ?? null, tool: '全部刀具', id: '' }, item.label);
  }
});

test('the numbered questions generate their labels and text with the default numbers', () => {
  for (const [group, label, expectedLabel, expectedQuery] of [
    ['换刀与磨损', '最近{n}环换刀', '最近100环换刀', '统计最近100环的换刀情况，列出现场观测记录数、更换数、更换率、主要磨损类型和高频刀位'],
    ['趋势区间', '按{n}环分段', '按50环分段', '按50环为一段统计换刀情况，列出每段现场观测记录数、更换数、更换率和已分类异常率'],
    ['趋势区间', '最近{n}环变化', '最近100环变化', '分析最近100环换刀变化，比较首末环段的更换率'],
    ['趋势区间', '前后环段对比', '前后环段对比', '按50环为一段，对比前后各段的更换率和已分类异常率'],
    ['趋势区间', '换刀最多的环段', '换刀最多的环段', '按50环为一段，找出更换次数最多的环段并列出该段的主要刀位'],
    ['开仓与检查', '最近{n}次开仓', '最近5次开仓', '查询最近5次开仓情况，列出环号、开仓间隔、开仓时长、检查数、更换数和异常率'],
    ['开仓与检查', '异常率较高的开仓', '异常率较高的开仓', '列出最近10次开仓中已分类异常率较高的开仓'],
    ['刀位统计', '更换最多的刀位', '更换最多的刀位', '列出更换次数最多的前10个刀位，并说明刀具类型和主要磨损类型'],
    ['刀位统计', '异常集中的刀位', '异常集中的刀位', '找出异常磨损集中的前10个刀位，并列出异常类型'],
    ['掘进参数', '掘进参数概览', '掘进参数概览', '查询最近有记录的100环掘进参数概览，列出推力、扭矩、转速和贯入力'],
    ['掘进参数', '掘进分段变化', '掘进分段变化', '分析最近有记录的100环掘进参数分段变化'],
  ]) {
    const h = loadInput();
    const item = pick(h, group, label);
    assert.equal(h.buildQuickLabel(item), expectedLabel);
    h.applyQuickQuestion();
    assert.equal(h.inputText.value, expectedQuery);
  }
});

test('each question keeps its own number and questions without parameters are written verbatim', () => {
  const h = loadInput();
  pick(h, '开仓与检查', '最近{n}次开仓');
  h.quickParams.value['最近{n}次开仓'].n = 8;
  h.applyQuickQuestion();
  assert.equal(h.inputText.value, '查询最近8次开仓情况，列出环号、开仓间隔、开仓时长、检查数、更换数和异常率');
  pick(h, '开仓与检查', '异常率较高的开仓');
  h.applyQuickQuestion();
  assert.equal(h.inputText.value, '列出最近10次开仓中已分类异常率较高的开仓');
  pick(h, '换刀与磨损', '全项目换刀');
  h.applyQuickQuestion();
  assert.equal(h.inputText.value, '统计当前项目全部刀具的换刀情况，列出现场观测记录数、更换数、更换率和主要磨损类型');
});

test('tracing a tool needs a tool number before the question can be generated', async () => {
  const h = loadInput();
  h.inputText.value = '已有草稿';
  pick(h, '服役与选型', '追溯刀具');
  for (const id of ['', '   ']) {
    h.quickParams.value['追溯刀具'].id = id;
    assert.equal(h.quickParamHint.value, '请先填写刀具编号');
    h.applyQuickQuestion();
    assert.equal(h.inputText.value, '已有草稿');
  }
  const html = await renderInput(h);
  assert.ok(isDisabled(buttonAttrs(html, '生成问题')));
  assert.match(html, /<input data-placeholder="刀具编号" data-disabled="false">/);
  assert.match(html, /<span class="quick-hint">请先填写刀具编号<\/span>/);
  h.quickParams.value['追溯刀具'].id = ' GD-0123 ';
  assert.equal(h.quickParamHint.value, '');
  h.applyQuickQuestion();
  assert.equal(h.inputText.value, '追溯刀具 GD-0123 的安装、检查、拆下和返修过程');
});

const titles = templates => Array.from(templates, template => template.title);
const OPENING_REVIEW = '复盘最近5次开仓：列出环号、开仓间隔、开仓时长、换刀时长、检查数、更换数和异常率，找出异常率最高的几次开仓，并列出这几次的高频刀位和需关注未更换的刀。';

test('switching to the model path picks the first default template, ticks its data types and fills its question without a prefix', async () => {
  const h = loadInput();
  assert.deepEqual(titles(h.visibleTemplates.value), ['开仓复盘', '近期数据复核清单', '异常磨损待复核线索']);
  h.handleSwitchRoute('agent');
  assert.equal(h.selectedTemplateTitle.value, '开仓复盘');
  assert.deepEqual(Array.from(h.selectedSources.value), ['opening', 'inspection', 'position']);
  assert.equal(h.inputText.value, OPENING_REVIEW);
  await vue.nextTick();
  assert.deepEqual(h.emitted.map(([event, value]) => [event, typeof value === 'string' ? value : Array.from(value)]), [['update:routeMode', 'agent'], ['sources-change', ['opening', 'inspection', 'position']]]);
});

test('selected data types filter the templates and no selection shows the three defaults', () => {
  const h = loadInput({ routeMode: 'agent' });
  h.selectedSources.value = ['repair'];
  assert.deepEqual(titles(h.visibleTemplates.value), ['登记金额汇总', '返修进度', '失效原因与刀位', '近期数据复核清单']);
  h.selectedSources.value = ['lifecycle'];
  assert.deepEqual(titles(h.visibleTemplates.value), ['追溯一把刀']);
  h.selectedSources.value = [];
  assert.deepEqual(titles(h.visibleTemplates.value), ['开仓复盘', '近期数据复核清单', '异常磨损待复核线索']);
});

test('choosing a template adds its data types and writes its question with the chosen parameters', async () => {
  const h = loadInput({ routeMode: 'agent' });
  h.selectedSources.value = ['cost'];
  h.handleTemplateChange('型号选型参考');
  assert.deepEqual(Array.from(h.selectedSources.value), ['tool_change', 'manufacturer', 'cost']);
  assert.equal(h.inputText.value, '列出全部刀具各型号已拆下刀具的平均服役环数、样本数和各厂家新刀报价区间，按每环报价折算排序，作为选型参考，并说明样本量和报价的局限。');
  assert.match(await renderInput(h), /<div class="tool-select" data-disabled="false" data-loading="false"><span>全部刀具<\/span><span>滚刀<\/span><span>刮刀<\/span><\/div>/);
  h.templateParams.value['型号选型参考'].tool = '滚刀';
  h.composeModelQuestion();
  assert.equal(h.inputText.value, '列出滚刀各型号已拆下刀具的平均服役环数、样本数和各厂家新刀报价区间，按每环报价折算排序，作为选型参考，并说明样本量和报价的局限。');
  h.handleTemplateChange('前后环段对比');
  h.templateParams.value['前后环段对比'].n = 30;
  h.composeModelQuestion();
  assert.equal(h.inputText.value, '以30环为一段，对比各段的更换次数、更换率和已分类异常率，说明变化最大的环段和该段的高频刀位；只做逐段对比，不下趋势结论。');
});

test('model templates need their parameters before 生成问题 works', async () => {
  const h = loadInput({ routeMode: 'agent' });
  h.inputText.value = '已有草稿';
  h.handleTemplateChange('追溯一把刀');
  assert.equal(h.templateParamHint.value, '请先填写刀具编号');
  assert.equal(h.inputText.value, '已有草稿');
  let html = await renderInput(h);
  assert.ok(isDisabled(buttonAttrs(html, '生成问题')));
  assert.match(html, /<input data-placeholder="刀具编号" data-disabled="false">/);
  assert.match(html, /<span class="quick-hint">请先填写刀具编号<\/span>/);
  h.templateParams.value['追溯一把刀'].id = 'GD-0123';
  h.composeModelQuestion();
  assert.equal(h.inputText.value, '追溯刀具 GD-0123 的安装、检查、拆下和返修全过程，列出缺失的环节。');
  h.handleTemplateChange('开仓复盘');
  h.templateParams.value['开仓复盘'].n = null;
  assert.equal(h.templateParamHint.value, '请先填写数字');
  html = await renderInput(h);
  assert.ok(isDisabled(buttonAttrs(html, '生成问题')));
  assert.equal(/null|\{n\}/.test(html), false);
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
    h.quickParams.value['最近{n}环换刀'].n = cleared;
    assert.equal(h.buildQuickLabel(h.selectedQuickItem.value), '最近N环换刀');
    assert.equal(h.quickParamHint.value, '请先填写数字');
    h.applyQuickQuestion();
    assert.equal(h.inputText.value, '已有草稿');
    const html = await renderInput(h);
    assert.ok(isDisabled(buttonAttrs(html, '生成问题')), `生成问题 must be disabled for ${cleared}`);
    assert.match(html, /<span class="quick-hint">请先填写数字<\/span>/);
    assert.equal(/null|NaN|\{n\}/.test(html), false);
    pick(h, '换刀与磨损', '全项目换刀');
    assert.equal(h.quickParamHint.value, '', 'questions without numbers are unaffected');
    pick(h, '换刀与磨损', '最近{n}环换刀');
    h.quickParams.value['最近{n}环换刀'].n = 120;
    const filled = await renderInput(h);
    assert.equal(isDisabled(buttonAttrs(filled, '生成问题')), false);
    assert.equal(filled.includes('请先填写数字'), false);
  }
});

test('dropdown labels show the current numbers instead of {n}', async () => {
  const h = loadInput();
  const html = await renderInput(h);
  assert.match(html, /<span>最近100环换刀<\/span>/);
  assert.equal(html.includes('{n}'), false);
  pick(h, '趋势区间', '按{n}环分段');
  h.quickParams.value['按{n}环分段'].n = 30;
  assert.match(await renderInput(h), /<span>按30环分段<\/span><span>最近100环变化<\/span>/);
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
  const sourcesHandler = find(descriptor.template.ast).props.find(prop => prop.name === 'on' && prop.arg.content === 'sources-change');
  assert.equal(sourcesHandler.exp.content, 'focusSources = $event');
});

const DRAFT = '统计120环到180环刮刀S3L的更换次数';
const COVERAGE_CHECK = '先核对掘进数据和换刀数据各自覆盖的环号和时间；有共同环段时，并列列出推力、扭矩、贯入力和更换次数；没有共同环段时，分别概括两类数据并说明不能对照。';

test('switching to the model path or changing data types keeps a draft the user wrote', () => {
  const h = loadInput();
  h.inputText.value = DRAFT;
  h.handleSwitchRoute('agent');
  assert.equal(h.props.routeMode, 'agent');
  assert.equal(h.inputText.value, DRAFT);
  h.selectedSources.value = ['tunneling'];
  h.handleModelDataTypesChange();
  assert.equal(h.selectedTemplateTitle.value, '掘进与换刀覆盖核对');
  assert.equal(h.inputText.value, DRAFT);
  h.handleSwitchRoute('rule'); h.handleSwitchRoute('agent');
  assert.equal(h.inputText.value, DRAFT);
});

test('text the input area filled in itself is still replaced until the user edits it', () => {
  const h = loadInput();
  h.applyQuickQuestion();
  h.handleSwitchRoute('agent');
  assert.equal(h.inputText.value, OPENING_REVIEW);
  h.selectedSources.value = ['tunneling'];
  h.handleModelDataTypesChange();
  assert.equal(h.inputText.value, COVERAGE_CHECK);
  h.inputText.value += '重点看S1L';
  h.selectedSources.value = ['repair'];
  h.handleModelDataTypesChange();
  assert.equal(h.selectedTemplateTitle.value, '登记金额汇总');
  assert.equal(h.inputText.value, `${COVERAGE_CHECK}重点看S1L`);
  h.inputText.value = '   ';
  h.handleModelDataTypesChange();
  assert.equal(h.inputText.value, '汇总新装登记金额、厂家已确认的返修金额和待厂家反馈的返修金额，按厂家和刀型分别列出，并说明这些是登记金额不是实际支出。');
});

test('choosing a template or pressing 生成问题 always writes the chosen question', () => {
  const h = loadInput({ routeMode: 'agent' });
  const repairProgress = '统计旧刀返修的厂家反馈进度：待反馈、已确认、已归档各多少，已报废和待厂家确认的报废建议各多少，列出部件失效原因的分布。';
  h.inputText.value = '我自己的问题';
  h.handleTemplateChange('返修进度');
  assert.equal(h.inputText.value, repairProgress);
  h.inputText.value = '我自己的问题';
  h.composeModelQuestion();
  assert.equal(h.inputText.value, repairProgress);
  const rule = loadInput();
  rule.inputText.value = '我自己的问题';
  rule.applyQuickQuestion();
  assert.equal(rule.inputText.value, '统计最近100环的换刀情况，列出现场观测记录数、更换数、更换率、主要磨损类型和高频刀位');
});

test('each path explains how to fill the input', async () => {
  assert.match(await renderInput(loadInput()), /<span class="input-tip">规则路径：下拉选择后可直接生成问题 · Enter 发送，Shift \+ Enter 换行 <\/span>/);
  assert.match(await renderInput(loadInput({ routeMode: 'agent' })), /<span class="input-tip">模型路径：选择要用的数据，或选一个分析模板生成问题；也可以直接输入 · Enter 发送，Shift \+ Enter 换行 <\/span>/);
});
