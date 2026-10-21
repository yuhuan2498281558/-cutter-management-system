import * as echarts from 'echarts';

// 图表配色集中在这里。取值要和 web/src/theme/tokens.scss 的设计变量保持一致，改一边时同步另一边。

// 按语义取用的系列颜色
export const CHART_COLORS = {
  primary: '#3f5f7a',
  neutral: '#c2b8a3',
  good: '#6f8f6a',
  warn: '#b98a4a',
  abnormal: '#b5533c',
  muted: '#9a978e',
  ink: '#6b6962',
};

// 分类色板：没有指定颜色的系列按这个顺序取色，厂家颜色也从这里按名称取
export const DV_PALETTE = [CHART_COLORS.primary, CHART_COLORS.neutral, CHART_COLORS.good, CHART_COLORS.warn, '#8a6f9e', '#5f8f8c', '#a3666f', '#7d8794'];

const CHART_TEXT = CHART_COLORS.ink;
const CHART_INK = '#1f1e1d';
const CHART_AXIS = '#d6d2c6';
const CHART_SPLIT = '#ece9e1';
const CHART_BORDER = '#e5e2d9';
const CHART_SURFACE = '#ffffff';

export const TOOL_TYPE_COLORS: Record<string, string> = {
  DISC: CHART_COLORS.primary,
  SCRAPER: CHART_COLORS.warn,
};

export const TOOL_TYPE_LABELS: Record<string, string> = {
  DISC: '滚刀',
  RIPPER: '撕裂刀',
  SCRAPER: '刮刀',
};

// 自定义分析矩阵气泡图
export const MATRIX_COLORS = {
  empty: CHART_COLORS.muted, // 没有颜色指标值的气泡
  zero: CHART_AXIS, // 数量为 0 的气泡
  bubbleBorder: CHART_SURFACE,
  labelOnDark: CHART_SURFACE,
  labelOnLight: CHART_INK,
  splitLine: CHART_SPLIT,
  splitArea: ['#fafafa', CHART_SURFACE],
  legendText: CHART_TEXT,
  range: ['#fffbeb', '#fde68a', '#fb923c', '#dc2626', '#7f1d1d'], // 颜色指标从低到高
  emphasisBorder: CHART_INK,
  emphasisShadow: 'rgba(0,0,0,0.2)',
};

export const TOOLTIP_STYLE = {
  backgroundColor: CHART_SURFACE,
  borderColor: CHART_BORDER,
  borderWidth: 1,
  textStyle: { color: CHART_INK, fontSize: 12 },
  extraCssText: 'box-shadow: 0 2px 6px rgba(31, 30, 29, 0.06); border-radius: 8px;',
};

export const DEFAULT_GRID = {
  top: 40,
  right: 24,
  bottom: 60,
  left: 60,
  containLabel: true,
};

const AXIS_STYLE = {
  axisLine: { lineStyle: { color: CHART_AXIS } },
  axisTick: { lineStyle: { color: CHART_AXIS } },
  axisLabel: { color: CHART_TEXT },
  nameTextStyle: { color: CHART_TEXT },
  splitLine: { lineStyle: { color: [CHART_SPLIT] } },
};

// 分析页面统一的 ECharts 主题，页面里用 echarts.init(el, 'dv')
export const DV_CHART_THEME = {
  color: DV_PALETTE,
  backgroundColor: 'transparent',
  textStyle: { color: CHART_TEXT },
  legend: { textStyle: { color: CHART_TEXT } },
  tooltip: TOOLTIP_STYLE,
  categoryAxis: AXIS_STYLE,
  valueAxis: AXIS_STYLE,
  logAxis: AXIS_STYLE,
  timeAxis: AXIS_STYLE,
};

echarts.registerTheme('dv', DV_CHART_THEME);
