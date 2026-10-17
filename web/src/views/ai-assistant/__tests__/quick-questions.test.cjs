// Run from web: node --test src/views/ai-assistant/__tests__/quick-questions.test.cjs
// Quick questions and model prompts are an executable business contract: the backend parses
// these exact words. Any wording change must be deliberate and update this snapshot.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');

const transpile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText;
const plain = value => JSON.parse(JSON.stringify(value));

function loadConstants() {
  const context = { exports: {} };
  vm.runInNewContext(transpile(fs.readFileSync(path.resolve(__dirname, '../constants.ts'), 'utf8')), context);
  return context.exports;
}

function loadMessageList(constants) {
  const context = { exports: {}, defineProps: () => ({ messages: [] }), defineEmits: () => () => {}, defineExpose() {} };
  context.require = name => {
    if (name === 'vue') return { ...vue, onUnmounted() {} };
    if (name === '../constants') return constants;
    if (name === 'element-plus') return { ElMessage: { success() {}, error() {} } };
    if (name === '@element-plus/icons-vue' || name.endsWith('.vue')) return {};
    throw new Error(`Unexpected import: ${name}`);
  };
  const source = fs.readFileSync(path.resolve(__dirname, '../components/ChatMessageList.vue'), 'utf8').match(/<script[^>]*>([\s\S]*?)<\/script>/)[1] + '\nexports.component = { welcomeChips };';
  vm.runInNewContext(transpile(source), context);
  return context.exports.component;
}

const SECTION_TITLES = ['结论', '关键依据', '数据依据', '关键发现', '注意事项', '注意事项/建议', '建议'];

const modelDataTypes = ['换刀/旧刀补录', '开仓记录', '刀位统计', '地层信息', '掘进参数', '厂家表现', '寿命预警', '备刀建议', '趋势分析', '跨源联动'];

const modelPromptLibrary = {
  '换刀/旧刀补录': [
    '分析近期换刀异常是否集中在特定磨损类型、刀具类型或刀位区域，并给出原因判断',
    '结合换刀明细识别异常磨损的主要模式、集中环段和需要复核的作业环节',
  ],
  '开仓记录': [
    '结合最近开仓记录分析异常率较高开仓的共同特征，以及与换刀工作量的关系',
    '分析开仓间隔、开仓时长、检查数量和更换数量之间是否存在异常联动',
  ],
  '刀位统计': [
    '分析高频刀位是否呈现局部集中、相邻刀位联动或刀盘区域性磨损风险',
    '结合刀位统计识别需要优先复核的刀位组合，并解释可能的受力或安装原因',
  ],
  '地层信息': [
    '分析地层变化是否可能解释近期异常磨损，并指出对应磨损类型和高风险刀位',
    '结合地层分布判断不同地层对换刀频率、异常率和刀位风险的影响',
  ],
  '掘进参数': [
    '分析掘进参数波动是否与异常磨损、换刀频率上升或刀位集中损伤有关',
    '结合推力、扭矩、转速和贯入力变化，判断近期刀具磨损风险的可能工况原因',
  ],
  '厂家表现': [
    '结合厂家表现、地层条件和刀具类型，分析异常磨损差异是否具有稳定性',
    '评估近期厂家刀具表现差异，并给出后续选型和复核建议',
  ],
  '寿命预警': [
    '结合平均寿命、累计推进和高频刀位，判断近期是否存在集中到寿风险',
    '分析寿命预警刀位与近期异常磨损、地层变化和开仓记录之间的关系',
  ],
  '备刀建议': [
    '结合近期消耗、异常磨损、地层变化和厂家表现，形成下一阶段备刀策略',
    '基于高风险刀位、失效模式和厂家表现，给出备刀优先级和关注原因',
  ],
  '趋势分析': [
    '分析近期换刀趋势是否出现阶段性抬升，并解释可能的地层、刀位或工况原因',
    '对比前后阶段换刀频率、异常磨损和高频刀位变化，判断风险是否加剧',
  ],
  '跨源联动': [
    '结合最近开仓、地层和换刀数据，分析哪些开仓异常率高以及对应地层和高频刀位',
    '结合地层、掘进参数和换刀记录，分析近期异常磨损的可能原因',
    '综合换刀、开仓、地层、刀位、厂家和寿命数据，生成近期风险清单和处理建议',
  ],
};

const defaultModelPrompts = [
  '结合地层、掘进参数和换刀记录，分析近期异常磨损的可能原因',
  '结合最近开仓、地层和换刀数据，分析哪些开仓异常率高以及对应地层和高频刀位',
  '综合换刀、开仓、地层、刀位、厂家和寿命数据，生成近期风险清单和处理建议',
];

const quickQuestionGroups = [
  {
    title: '换刀/旧刀补录',
    desc: '检查数、更换数、旧刀补录磨损类型和高频刀位',
    items: [
      { label: '近{n}环统计', query: '统计最近{n}环的换刀情况，列出检查数、更换数、更换率、主要磨损类型和高频刀位', numKey: 'ringWindow', min: 20, max: 500, step: 10 },
      { label: '换刀汇总', query: '统计当前项目全部刀具换刀情况，列出检查数、更换数、更换率和主要磨损类型' },
      { label: '异常磨损', query: '统计异常磨损记录，列出异常类型、数量和占比' },
      { label: '更换率', query: '统计换刀更换率，并列出主要更换刀位' },
      { label: '滚刀统计', query: '统计滚刀换刀情况，列出检查数、更换数和主要磨损类型' },
      { label: '刮刀统计', query: '统计刮刀换刀情况，列出检查数、更换数和主要磨损类型' },
    ],
  },
  {
    title: '趋势区间',
    desc: '按环段观察换刀频率和异常变化',
    items: [
      { label: '{n}环分段', query: '按{n}环为一段统计换刀趋势，列出每段检查数、更换数和更换率', numKey: 'interval', min: 10, max: 200, step: 10 },
      { label: '近{n}环趋势', query: '分析最近{n}环换刀趋势，说明更换率是否上升', numKey: 'ringWindow', min: 20, max: 500, step: 10 },
      { label: '阶段对比', query: '对比前后阶段换刀频率和异常磨损变化' },
      { label: '峰值环段', query: '找出换刀频率最高的环段并列出主要刀位' },
      { label: '100-300环', query: '统计100环到300环的换刀趋势和主要磨损类型' },
    ],
  },
  {
    title: '开仓记录',
    desc: '开仓间隔、时长、异常率和换刀数量',
    items: [
      { label: '近{n}次开仓', query: '查询最近{n}次开仓情况，列出环号、开仓间隔、开仓时长、检查数、更换数和异常率', numKey: 'openingLimit', min: 1, max: 20 },
      { label: '开仓异常', query: '分析最近开仓记录中异常磨损率较高的开仓' },
      { label: '开仓效率', query: '结合开仓时长和检查刀具数量，统计平均检查一把刀需要多长时间' },
      { label: '更换效率', query: '结合开仓时长和更换刀具数量，统计平均更换一把刀需要多长时间' },
      { label: '开仓间隔', query: '统计平均多少环开一次仓，并列出最近开仓间隔' },
    ],
  },
  {
    title: '刀位统计',
    desc: '定位高频更换和高风险刀位',
    items: [
      { label: '前{n}刀位', query: '列出更换次数最高的前{n}个刀位，并说明刀具类型和主要磨损类型', numKey: 'topN', min: 3, max: 30 },
      { label: '高频刀位', query: '分析高频更换刀位，列出更换次数和主要磨损类型' },
      { label: '异常刀位', query: '找出异常磨损集中的刀位，并列出异常类型' },
      { label: '刀盘分布', query: '分析刀盘不同刀位的磨损分布情况' },
      { label: '指定刀位', query: '分析S1L刀位的换刀和磨损情况' },
    ],
  },
  {
    title: '地层信息',
    desc: '地层分布和地层-磨损关联',
    items: [
      { label: '地层分布', query: '统计当前项目地层分布，列出各地层类型占比' },
      { label: '区间地层', query: '查询100环到300环的地层分布情况' },
      { label: '地层磨损', query: '分析地层类型与刀具磨损的关联' },
      { label: '地层换刀', query: '分析不同地层下的换刀数量和更换率' },
      { label: '刀位地层', query: '分析刀位受地层影响的情况，列出高风险刀位' },
    ],
  },
  {
    title: '掘进动态',
    desc: '推力、扭矩、转速、贯入力趋势',
    items: [
      { label: '参数概览', query: '查询近期掘进动态参数概览，列出推力、扭矩、转速和贯入力' },
      { label: '异常检查', query: '检查近期掘进参数异常，列出偏高或波动明显的环段' },
      { label: '近{n}环参数', query: '分析最近{n}环掘进参数趋势', numKey: 'ringWindow', min: 20, max: 500, step: 10 },
      { label: '参数磨损', query: '分析掘进参数与换刀磨损的关联' },
      { label: '波动原因', query: '结合掘进参数和换刀记录，分析异常磨损可能原因' },
    ],
  },
  {
    title: '厂家刀具',
    desc: '厂家表现、异常率和成本线索',
    items: [
      { label: '厂家表现', query: '评估各厂家刀具表现，列出更换数量、异常数量和异常率' },
      { label: '厂家对比', query: '对比不同厂家在异常磨损率和使用寿命上的差异' },
      { label: '厂家异常', query: '分析主要厂家的异常磨损模式' },
      { label: '厂家刀位', query: '分析不同厂家在高频刀位上的表现差异' },
    ],
  },
  {
    title: '寿命预测',
    desc: '平均寿命、状态分布和预警刀位',
    items: [
      { label: '寿命概况', query: '统计当前刀具平均寿命、已推进环数和剩余寿命分布' },
      { label: '预警刀位', query: '查询需要重点关注的寿命预警刀位，并列出当前状态' },
      { label: '滚刀寿命', query: '统计滚刀平均寿命和集中更换环段' },
      { label: '刮刀寿命', query: '统计刮刀平均寿命和集中更换环段' },
    ],
  },
  {
    title: '备刀建议',
    desc: '根据近期消耗和异常做备刀规划',
    items: [
      { label: '备刀规划', query: '根据近期换刀消耗和磨损趋势，给出下一阶段备刀建议' },
      { label: '滚刀备刀', query: '给出滚刀备刀建议，列出重点规格和关注刀位' },
      { label: '刮刀备刀', query: '给出刮刀备刀建议，列出重点规格和关注刀位' },
      { label: '高风险备刀', query: '结合高频异常刀位，给出应急备刀建议' },
    ],
  },
  {
    title: '综合诊断',
    desc: '跨模块联合分析与风险清单',
    items: [
      { label: '开仓-地层联动', query: '结合最近开仓记录和地层分布，分析哪些开仓异常率高以及对应地层' },
      { label: '参数-换刀联动', query: '结合掘进参数和换刀记录，分析近期异常磨损的可能原因' },
      { label: '全面体检', query: '综合换刀、开仓、地层、刀位、厂家和寿命数据，生成近期风险清单和处理建议' },
    ],
  },
];

// Which backend parameter each {n} feeds: recent ring window, segment interval, recent opening count, ranking size.
const NUMBER_PHRASES = {
  ringWindow: '最近{n}环',
  interval: '按{n}环为一段',
  openingLimit: '最近{n}次开仓',
  topN: '前{n}个',
};

test('quick questions, model prompts and section titles match the verified wording exactly', () => {
  const constants = loadConstants();
  assert.deepEqual(plain(constants.quickQuestionGroups), quickQuestionGroups);
  assert.deepEqual(plain(constants.modelPromptLibrary), modelPromptLibrary);
  assert.deepEqual(plain(constants.defaultModelPrompts), defaultModelPrompts);
  assert.deepEqual(plain(constants.modelDataTypes), modelDataTypes);
  assert.deepEqual(plain(constants.SECTION_TITLES), SECTION_TITLES);
  assert.equal(quickQuestionGroups.flatMap(group => group.items).length, 46);
  assert.equal(Object.values(modelPromptLibrary).flat().length, 21);
});

test('every {n} question declares bounds and a parameter that matches its wording', () => {
  const items = loadConstants().quickQuestionGroups.flatMap(group => group.items);
  const numbered = items.filter(item => item.numKey || item.query.includes('{n}') || item.label.includes('{n}'));
  assert.equal(numbered.length, 6);
  for (const item of numbered) {
    assert.ok(item.query.includes('{n}') && item.label.includes('{n}'), `${item.label} must show {n} in label and query`);
    assert.equal(item.query.split('{n}').length, 2, `${item.label} must use {n} once`);
    assert.ok(Object.hasOwn(NUMBER_PHRASES, item.numKey), `${item.label} has unknown numKey ${item.numKey}`);
    assert.ok(Number.isInteger(item.min) && Number.isInteger(item.max) && item.min < item.max, `${item.label} needs integer min < max`);
    for (const [numKey, phrase] of Object.entries(NUMBER_PHRASES)) {
      assert.equal(item.query.includes(phrase), numKey === item.numKey, `${item.label}: "${phrase}" belongs to ${numKey}`);
    }
  }
});

test('all six welcome shortcuts resolve to library questions word for word', () => {
  const constants = loadConstants();
  const chips = plain(loadMessageList(constants).welcomeChips);
  const expected = [
    ['换刀/旧刀补录', '换刀汇总'],
    ['换刀/旧刀补录', '异常磨损'],
    ['刀位统计', '高频刀位'],
    ['开仓记录', '开仓间隔'],
    ['地层信息', '地层分布'],
    ['寿命预测', '寿命概况'],
  ].map(([title, label]) => {
    const item = quickQuestionGroups.find(group => group.title === title).items.find(entry => entry.label === label);
    return { label: item.label, query: item.query };
  });
  assert.deepEqual(chips, expected);
});
