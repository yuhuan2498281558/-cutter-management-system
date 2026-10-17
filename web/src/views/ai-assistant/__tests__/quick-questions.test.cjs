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
    title: '换刀与磨损',
    desc: '现场观测、更换率、磨损类型和高频刀位',
    items: [
      { label: '最近{n}环换刀', query: '统计最近{n}环的换刀情况，列出现场观测记录数、更换数、更换率、主要磨损类型和高频刀位', numKey: 'ringWindow', min: 20, max: 500, step: 10, defaultValue: 100 },
      { label: '全项目换刀', query: '统计当前项目全部刀具的换刀情况，列出现场观测记录数、更换数、更换率和主要磨损类型' },
      { label: '异常磨损类型', query: '统计异常磨损记录，列出异常类型、数量和占比' },
      { label: '更换率与主要刀位', query: '统计换刀更换率，并列出主要更换刀位' },
      { label: '滚刀换刀', query: '统计滚刀换刀情况，列出现场观测记录数、更换数和主要磨损类型' },
      { label: '刮刀换刀', query: '统计刮刀换刀情况，列出现场观测记录数、更换数和主要磨损类型' },
    ],
  },
  {
    title: '趋势区间',
    desc: '按环段比较更换率和异常率',
    items: [
      { label: '按{n}环分段', query: '按{n}环为一段统计换刀情况，列出每段现场观测记录数、更换数、更换率和已分类异常率', numKey: 'interval', min: 10, max: 200, step: 10, defaultValue: 50 },
      { label: '最近{n}环变化', query: '分析最近{n}环换刀变化，比较首末环段的更换率', numKey: 'ringWindow', min: 20, max: 500, step: 10, defaultValue: 100 },
      { label: '前后环段对比', query: '按{n}环为一段，对比前后各段的更换率和已分类异常率', numKey: 'interval', min: 10, max: 200, step: 10, defaultValue: 50 },
      { label: '换刀最多的环段', query: '按{n}环为一段，找出更换次数最多的环段并列出该段的主要刀位', numKey: 'interval', min: 10, max: 200, step: 10, defaultValue: 50 },
      { label: '100–300环分段', query: '统计100环到300环的换刀分段情况' },
    ],
  },
  {
    title: '开仓与检查',
    desc: '开仓汇总、检查完成情况和作业效率',
    items: [
      { label: '最近{n}次开仓', query: '查询最近{n}次开仓情况，列出环号、开仓间隔、开仓时长、检查数、更换数和异常率', numKey: 'openingLimit', min: 1, max: 20, defaultValue: 5 },
      { label: '异常率较高的开仓', query: '列出最近{n}次开仓中已分类异常率较高的开仓', numKey: 'openingLimit', min: 1, max: 20, defaultValue: 10 },
      { label: '检查效率', query: '结合开仓时长和检查刀具数量，统计平均检查一把刀需要多长时间' },
      { label: '更换效率', query: '结合换刀总时长和更换刀具数量，统计平均更换一把刀需要多长时间' },
      { label: '开仓间隔', query: '统计平均多少环开一次仓，并列出最近开仓间隔' },
      { label: '需关注未更换', query: '列出需要关注但还没更换的刀，给出刀位、环号和磨损情况' },
      { label: '未检查刀位', query: '列出还没检查的刀位和所在开仓' },
    ],
  },
  {
    title: '刀位统计',
    desc: '更换次数和异常集中的刀位',
    items: [
      { label: '更换最多的刀位', query: '列出更换次数最多的前{n}个刀位，并说明刀具类型和主要磨损类型', numKey: 'topN', min: 3, max: 30, defaultValue: 10 },
      { label: '异常集中的刀位', query: '找出异常磨损集中的前{n}个刀位，并列出异常类型', numKey: 'topN', min: 3, max: 30, defaultValue: 10 },
      { label: '全刀盘磨损分布', query: '列出全部有效刀位的更换次数和磨损情况' },
      { label: '单个刀位', query: '分析S1L刀位的换刀和磨损情况' },
    ],
  },
  {
    title: '地层',
    desc: '地层面积占比、地层标签和开仓位置地层',
    items: [
      { label: '地层面积占比', query: '统计当前项目各地层的面积占比' },
      { label: '环段地层面积', query: '统计100环到300环各地层的面积占比' },
      { label: '地层标签分布', query: '统计100环到300环的历史地层标签分布' },
      { label: '开仓位置地层', query: '查询最近一次开仓的位置地层和上次开仓以来经过的地层' },
      { label: '地层与换刀', query: '分析不同地层标签下的换刀数量和更换率' },
      { label: '刀位与地层', query: '列出刀位与地层标签的关联次数和实际更换次数' },
    ],
  },
  {
    title: '掘进参数',
    desc: '推力、扭矩、转速、贯入力和分段均值',
    items: [
      { label: '掘进参数概览', query: '查询最近有记录的{n}环掘进参数概览，列出推力、扭矩、转速和贯入力', numKey: 'ringWindow', min: 20, max: 500, step: 10, defaultValue: 100 },
      { label: '分段均值偏高筛查', query: '筛查掘进参数分段均值偏高的记录，列出环号、时间段和数值' },
      { label: '掘进分段变化', query: '分析最近有记录的{n}环掘进参数分段变化', numKey: 'ringWindow', min: 20, max: 500, step: 10, defaultValue: 100 },
      { label: '掘进与换刀对照', query: '分析掘进参数与换刀磨损的关联' },
    ],
  },
  {
    title: '厂家与报价',
    desc: '厂家寿命、异常率、报价和登记金额',
    items: [
      { label: '厂家寿命与异常率', query: '对比各厂家刀具的使用寿命和异常磨损率' },
      { label: '厂家磨损类型', query: '分析主要厂家的异常磨损类型' },
      { label: '型号报价', query: '查询各型号的新刀和维修报价，按厂家列出' },
      { label: '登记金额', query: '统计项目登记金额，按厂家分别列出' },
    ],
  },
  {
    title: '旧刀返修',
    desc: '返修进度、报废和部件失效原因',
    items: [
      { label: '返修进度', query: '统计旧刀返修进度，列出待厂家反馈、已确认、已归档的数量' },
      { label: '报废情况', query: '统计已经报废了多少把刀，另列待厂家确认的报废建议' },
      { label: '返修登记金额', query: '统计已确认的返修登记了多少钱' },
      { label: '部件失效原因', query: '统计旧刀的部件失效原因，列出轴承、刀圈等损坏数量' },
    ],
  },
  {
    title: '服役与选型',
    desc: '服役环数、选型参考、单刀追溯和可查数据',
    items: [
      { label: '滚刀服役环数', query: '统计滚刀平均寿命和集中更换环段' },
      { label: '刮刀服役环数', query: '统计刮刀平均寿命和集中更换环段' },
      { label: '滚刀选型参考', query: '推荐滚刀型号，列出平均服役环数、样本数和新刀报价区间' },
      { label: '刮刀选型参考', query: '推荐刮刀型号，列出平均服役环数、样本数和新刀报价区间' },
      { label: '追溯刀具', query: '追溯刀具 {id} 的安装、检查、拆下和返修过程', textKey: 'id' },
      { label: '可查数据', query: '现在有哪些数据可以查，各类数据覆盖到哪里' },
    ],
  },
];

// Which backend parameter each {n} feeds: recent ring window, segment interval, recent opening count, ranking size.
const NUMBER_PHRASES = {
  ringWindow: /最近(?:有记录的)?\{n\}环/,
  interval: /按\{n\}环为一段/,
  openingLimit: /最近\{n\}次开仓/,
  topN: /前\{n\}个/,
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

test('every {n} question declares bounds, its own default and a parameter that matches its wording', () => {
  const items = loadConstants().quickQuestionGroups.flatMap(group => group.items);
  assert.equal(new Set(items.map(item => item.label)).size, items.length, 'labels are unique because parameters are kept per label');
  const numbered = items.filter(item => item.numKey || item.query.includes('{n}') || item.label.includes('{n}'));
  assert.equal(numbered.length, 11);
  for (const item of numbered) {
    assert.equal(item.query.split('{n}').length, 2, `${item.label} must use {n} once in the question`);
    assert.ok(Object.hasOwn(NUMBER_PHRASES, item.numKey), `${item.label} has unknown numKey ${item.numKey}`);
    assert.ok(Number.isInteger(item.min) && Number.isInteger(item.max) && item.min < item.max, `${item.label} needs integer min < max`);
    assert.ok(Number.isInteger(item.defaultValue) && item.defaultValue >= item.min && item.defaultValue <= item.max, `${item.label} default ${item.defaultValue}`);
    for (const [numKey, phrase] of Object.entries(NUMBER_PHRASES)) {
      assert.equal(phrase.test(item.query), numKey === item.numKey, `${item.label}: ${phrase} belongs to ${numKey}`);
    }
  }
});

test('only the trace question takes a tool number and it is written into the question once', () => {
  const items = loadConstants().quickQuestionGroups.flatMap(group => group.items);
  const withId = items.filter(item => item.textKey || item.query.includes('{id}'));
  assert.deepEqual(plain(withId.map(item => [item.label, item.textKey, item.query.split('{id}').length])), [['追溯刀具', 'id', 2]]);
});

test('all six welcome shortcuts resolve to library questions without parameters, word for word', () => {
  const constants = loadConstants();
  const chips = plain(loadMessageList(constants).welcomeChips);
  const expected = [
    ['换刀与磨损', '全项目换刀'],
    ['换刀与磨损', '异常磨损类型'],
    ['刀位统计', '全刀盘磨损分布'],
    ['开仓与检查', '开仓间隔'],
    ['地层', '地层面积占比'],
    ['服役与选型', '可查数据'],
  ].map(([title, label]) => {
    const item = quickQuestionGroups.find(group => group.title === title).items.find(entry => entry.label === label);
    assert.equal(item.numKey || item.textKey, undefined, `${label} must not need a parameter`);
    return { label: item.label, query: item.query };
  });
  assert.deepEqual(chips, expected);
});
