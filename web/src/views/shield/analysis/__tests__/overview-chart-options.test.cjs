const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { compile, plain, root, echartsStub } = require('./helpers.cjs');

function load(file) {
  return compile(fs.readFileSync(file, 'utf8'), name => name === 'echarts' ? echartsStub : load(path.resolve(path.dirname(file), `${name}.ts`)));
}
const { buildOverviewTrendOption, buildOverviewTypeOption } = load(path.resolve(root, 'utils/overviewChartOptions.ts'));

const overview = { monthly_trend: [{ month: '2026-09', total_replacements: 4, cost: 50 }, { month: '', cost: null }] };
const trendItems = [{ ring_no: '100', total_cost: 50, replacement_count: 4 }, { ring_no: '120', total_cost: null }];
const typeTrend = [{ ring_no: '100', DISC: 3, SCRAPER: 1 }, { ring_no: '120', DISC: 5, SCRAPER: 2 }];

test('trend builder reads ring items by ring and monthly totals by month', () => {
  const ring = buildOverviewTrendOption(overview, trendItems, 'ring');
  assert.deepEqual(plain(ring.xAxis), { type: 'category', data: ['100', '120'], name: '环号' });
  assert.deepEqual(plain(ring.series.map(item => item.data)), [[4, 0], [50, null]]);
  const month = buildOverviewTrendOption(overview, trendItems, 'month');
  assert.deepEqual(plain(month.xAxis), { type: 'category', data: ['2026-09', '日期未记录'], name: '月份' });
  assert.deepEqual(plain(month.series.map(item => item.data)), [[4, 0], [50, null]]);
  for (const option of [ring, month]) {
    assert.equal(option.grid.bottom, 78); assert.equal(option.yAxis.length, 2); assert.equal(option.dataZoom.length, 2);
    assert.equal(option.series[1].yAxisIndex, 1); assert.equal(option.series[1].connectNulls, false);
  }
});

test('type builder switches between latest-ring bars and cumulative lines', () => {
  const total = buildOverviewTypeOption(typeTrend, 'total');
  assert.deepEqual(plain(total.series[0].data.map(item => item.value)), [5, 2]);
  assert.equal(total.legend.show, false); assert.equal(total.grid.bottom, 35);
  const cumulative = buildOverviewTypeOption(typeTrend, 'cumulative');
  assert.deepEqual(plain(cumulative.series.map(item => [item.name, item.data])), [['滚刀', [3, 5]], ['刮刀', [1, 2]]]);
  assert.equal(cumulative.legend.show, true); assert.equal(cumulative.grid.bottom, 70);
});

test('type builder shows zero bars when no ring has type data', () => {
  const option = buildOverviewTypeOption([], 'total');
  assert.deepEqual(plain(option.series[0].data.map(item => item.value)), [0, 0]);
  assert.deepEqual(plain(buildOverviewTypeOption([], 'cumulative').xAxis.data), []);
});
