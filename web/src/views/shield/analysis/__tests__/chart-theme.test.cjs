const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { compile, plain, root } = require('./helpers.cjs');

const read = file => fs.readFileSync(path.resolve(root, file), 'utf8');
const pages = ['pages/CostAnalysis.vue', 'pages/CustomAnalysis.vue', 'pages/Overview.vue', 'pages/WearAnalysis.vue'];
const optionFiles = ['utils/costChartOptions.ts', 'utils/customChartOptions.ts', 'utils/overviewChartOptions.ts', 'utils/wearChartOptions.ts'];
const oldColors = ['#e84749', '#fa8c16', '#1677ff', '#5470c6', '#c57932', '#35689b', '#6f9483', '#b7a078', '#b76558', '#9ba5b1', '#4b5563',
  '#7d6aa8', '#427c70', '#ae783c', '#a45f6d', '#537f92', '#687947', '#8c6b54', '#a8abb2', '#d1d5db', '#374151', '#e5e7eb', '#6b7280', '#111827', '#64748b'];

function loadTheme() {
  const registered = [];
  const theme = compile(read('utils/chartTheme.ts'), name => {
    assert.equal(name, 'echarts');
    return { registerTheme: (themeName, value) => registered.push([themeName, value]) };
  });
  return { theme, registered };
}

test('every analysis chart is created with the dv theme', () => {
  const calls = pages.flatMap(file => [...read(file).matchAll(/echarts\.init\(([^)]*)\)/g)].map(match => [file, match[1]]));
  assert.equal(calls.length, 5);
  for (const [file, args] of calls) assert.match(args, /, 'dv'$/, file);
});

test('chart option files take every colour from chartTheme', () => {
  for (const file of optionFiles) {
    const source = read(file);
    assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, file);
  }
  for (const file of [...optionFiles, ...pages]) {
    const source = read(file).toLowerCase();
    for (const color of oldColors) assert.equal(source.includes(color), false, `${file} ${color}`);
  }
});

test('chartTheme registers the dv theme with the agreed palette, axes and tooltip', () => {
  const { theme, registered } = loadTheme();
  assert.equal(registered.length, 1);
  assert.equal(registered[0][0], 'dv');
  assert.equal(registered[0][1], theme.DV_CHART_THEME);
  const dv = plain(theme.DV_CHART_THEME);
  assert.deepEqual(dv.color, ['#3f5f7a', '#c2b8a3', '#6f8f6a', '#b98a4a', '#8a6f9e', '#5f8f8c', '#a3666f', '#7d8794']);
  assert.equal(theme.DV_PALETTE, theme.DV_CHART_THEME.color);
  assert.equal(dv.backgroundColor, 'transparent');
  assert.equal(dv.textStyle.color, '#6b6962');
  for (const axis of ['categoryAxis', 'valueAxis', 'logAxis', 'timeAxis']) {
    assert.equal(dv[axis].axisLine.lineStyle.color, '#d6d2c6', axis);
    assert.equal(dv[axis].axisTick.lineStyle.color, '#d6d2c6', axis);
    assert.equal(dv[axis].axisLabel.color, '#6b6962', axis);
    assert.deepEqual(dv[axis].splitLine.lineStyle.color, ['#ece9e1'], axis);
  }
  const tooltip = plain(theme.TOOLTIP_STYLE);
  assert.deepEqual({ ...tooltip, extraCssText: undefined }, { backgroundColor: '#ffffff', borderColor: '#e5e2d9', borderWidth: 1, textStyle: { color: '#1f1e1d', fontSize: 12 }, extraCssText: undefined });
  assert.match(tooltip.extraCssText, /border-radius: 8px;/);
  assert.deepEqual(plain(theme.CHART_COLORS), { primary: '#3f5f7a', neutral: '#c2b8a3', good: '#6f8f6a', warn: '#b98a4a', abnormal: '#b5533c', muted: '#9a978e', ink: '#6b6962' });
  assert.deepEqual(plain(theme.TOOL_TYPE_COLORS), { DISC: '#3f5f7a', SCRAPER: '#b98a4a' });
});
