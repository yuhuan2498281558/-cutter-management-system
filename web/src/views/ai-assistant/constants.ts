import { FocusSource, ModelPromptTemplate, QuickQuestionGroup } from './types';

export const SECTION_TITLES = [
  '结论',
  '关键依据',
  '数据依据',
  '关键发现',
  '注意事项',
  '注意事项/建议',
  '建议',
  '待复核线索',
  '数据范围和限制',
];

// 模型路径可选的数据类型；value 作为请求字段 focus_sources 发给后端
export const FOCUS_SOURCES: Array<{ value: FocusSource; label: string }> = [
  { value: 'tool_change', label: '换刀与磨损' },
  { value: 'opening', label: '开仓记录' },
  { value: 'inspection', label: '现场检查' },
  { value: 'position', label: '刀位' },
  { value: 'stratum', label: '地层' },
  { value: 'tunneling', label: '掘进参数' },
  { value: 'manufacturer', label: '厂家表现' },
  { value: 'cost', label: '报价与登记金额' },
  { value: 'repair', label: '旧刀返修' },
  { value: 'lifecycle', label: '单把刀追溯' },
];

// 模板参数 {tool} 的可选刀型
export const TOOL_TYPE_OPTIONS = ['全部刀具', '滚刀', '刮刀'];

// 模型路径分析模板。sources 是关联的数据类型，isDefault 的三条在一个类型都没选时显示。
// {n} 的含义同规则路径的 numKey，{tool} 是刀型，{id} 是用户填写的刀具编号（必填）。
export const modelPromptTemplates: ModelPromptTemplate[] = [
  { title: '近期异常磨损分布', query: '统计最近{n}环的现场观测记录，按磨损类型、刀具类型和刀位列出异常磨损的数量和占比，指出异常集中的刀位和环段，并列出需要复核的记录。', sources: ['tool_change', 'position'], numKey: 'ringWindow', min: 20, max: 500, step: 10, defaultValue: 100 },
  { title: '前后环段对比', query: '以{n}环为一段，对比各段的更换次数、更换率和已分类异常率，说明变化最大的环段和该段的高频刀位；只做逐段对比，不下趋势结论。', sources: ['tool_change', 'position'], numKey: 'interval', min: 10, max: 200, step: 10, defaultValue: 50 },
  { title: '开仓复盘', query: '复盘最近{n}次开仓：列出环号、开仓间隔、开仓时长、换刀时长、检查数、更换数和异常率，找出异常率最高的几次开仓，并列出这几次的高频刀位和需关注未更换的刀。', sources: ['opening', 'inspection', 'position'], numKey: 'openingLimit', min: 1, max: 20, defaultValue: 5, isDefault: true },
  { title: '检查完成情况', query: '检查最近{n}次开仓的现场检查完成情况：各次开仓已检查、未检查和需关注未更换的数量，列出还没检查的刀位。', sources: ['inspection', 'opening'], numKey: 'openingLimit', min: 1, max: 20, defaultValue: 5 },
  { title: '异常集中的刀位', query: '找出异常观测数最多的前{n}个刀位，列出每个刀位的现场观测数、异常类型和更换次数，并给出这些刀位最近几次开仓的检查记录。', sources: ['position', 'tool_change', 'inspection'], numKey: 'topN', min: 3, max: 30, defaultValue: 10 },
  { title: '开仓位置地层对照', query: '列出最近{n}次开仓所在位置的地层和仓间经过的地层（按纵断面面积），与每次开仓的异常率、高频刀位并列对照；只做并列，不判断地层是否导致磨损。', sources: ['stratum', 'opening', 'tool_change'], numKey: 'openingLimit', min: 1, max: 20, defaultValue: 5 },
  { title: '地层组成与换刀', query: '统计最近{n}环的纵断面六类面积占比，并与同一范围的换刀次数、更换率和异常率并列列出。', sources: ['stratum', 'tool_change'], numKey: 'ringWindow', min: 20, max: 500, step: 10, defaultValue: 100 },
  { title: '掘进与换刀覆盖核对', query: '先核对掘进数据和换刀数据各自覆盖的环号和时间；有共同环段时，并列列出推力、扭矩、贯入度和更换次数；没有共同环段时，分别概括两类数据并说明不能对照。', sources: ['tunneling', 'tool_change'] },
  { title: '掘进分段均值偏高筛查', query: '筛查已导入的掘进数据中推力、扭矩、贯入度分段均值偏高的记录，列出环号、时间段和数值，并说明这类数据能说明什么、不能说明什么。', sources: ['tunneling'] },
  { title: '厂家寿命与异常率', query: '按刀具原安装时的厂家，对比已确认拆下刀具的平均服役环数、已分类异常率和样本量，另列各厂家本次新装的供货次数和登记金额；样本少的厂家单独说明。', sources: ['manufacturer', 'cost'] },
  { title: '型号选型参考', query: '列出{tool}各型号已拆下刀具的平均服役环数、样本数和各厂家新刀报价区间，按每环报价折算排序，作为选型参考，并说明样本量和报价的局限。', sources: ['cost', 'manufacturer', 'tool_change'], toolParam: true },
  { title: '登记金额汇总', query: '汇总新装登记金额、厂家已确认的返修金额和待厂家反馈的返修金额，按厂家和刀型分别列出，并说明这些是登记金额不是实际支出。', sources: ['cost', 'repair'] },
  { title: '返修进度', query: '统计旧刀返修的厂家反馈进度：待反馈、已确认、已归档各多少，已报废和待厂家确认的报废建议各多少，列出部件失效原因的分布。', sources: ['repair'] },
  { title: '失效原因与刀位', query: '列出轴承、刀圈等部件失效的旧刀，对照这些刀拆下时所在的刀位和开仓，指出重复出现的刀位。', sources: ['repair', 'position', 'opening'] },
  { title: '追溯一把刀', query: '追溯刀具 {id} 的安装、检查、拆下和返修全过程，列出缺失的环节。', sources: ['lifecycle'], textKey: 'id' },
  { title: '近期数据复核清单', query: '汇总最近{n}环的换刀、开仓检查、刀位、地层和旧刀返修数据，生成一份数据复核清单：每条写明对象（刀位、开仓或环段）、依据的数字和建议的复核动作，不推断原因。', sources: ['tool_change', 'opening', 'inspection', 'position', 'stratum', 'repair'], numKey: 'ringWindow', min: 20, max: 500, step: 10, defaultValue: 100, isDefault: true },
  { title: '异常磨损待复核线索', query: '结合最近{n}环的换刀、地层和掘进数据，列出异常磨损的待复核线索；某类数据覆盖不到这个范围时如实说明，不断言原因。', sources: ['tool_change', 'stratum', 'tunneling'], numKey: 'ringWindow', min: 20, max: 500, step: 10, defaultValue: 100, isDefault: true },
];

// 规则路径快捷问题。{n} 的含义由 numKey 决定：ringWindow 最近环数、interval 分段环数、
// openingLimit 最近开仓次数、topN 排行数量；defaultValue 是这条问题自己的默认数字。
// {id} 是用户填写的刀具编号，必填。问法要能被后端规则路由命中，改文字前先回放验证。
export const quickQuestionGroups: QuickQuestionGroup[] = [
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
    desc: '推力、扭矩、转速、贯入度和分段均值',
    items: [
      { label: '掘进参数概览', query: '查询最近有记录的{n}环掘进参数概览，列出推力、扭矩、转速和贯入度', numKey: 'ringWindow', min: 20, max: 500, step: 10, defaultValue: 100 },
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
