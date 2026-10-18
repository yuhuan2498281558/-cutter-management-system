import { DEFAULT_GRID, TOOLTIP_STYLE, TOOL_TYPE_COLORS, TOOL_TYPE_LABELS } from './chartTheme';
import type { CostTrendItem, OverviewData, TypeTrendItem } from '../types';

// 构造按环或按月的更换消耗与费用趋势图配置。
export function buildOverviewTrendOption(overview: Pick<OverviewData, 'monthly_trend'>, trendItems: CostTrendItem[], trendMode: string) {
  const monthly = trendMode === 'month';
  return {
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis' },
    legend: { bottom: 0, type: 'scroll' }, grid: { ...DEFAULT_GRID, bottom: 78 },
    xAxis: { type: 'category', data: monthly ? overview.monthly_trend.map(r => r.month || '日期未记录') : trendItems.map(r => r.ring_no), name: monthly ? '月份' : '环号' },
    yAxis: [{ type: 'value', name: '实际更换 / 把次', minInterval: 1 }, { type: 'value', name: '明确金额 / 元' }],
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 14, bottom: 28 }],
    series: [
      { name: '实际更换', type: 'bar', barMaxWidth: 26, itemStyle: { color: '#5470c6' }, data: monthly ? overview.monthly_trend.map(r => r.total_replacements ?? 0) : trendItems.map(r => r.replacement_count ?? 0) },
      { name: '明确金额', type: 'line', yAxisIndex: 1, connectNulls: false, itemStyle: { color: '#c57932' }, data: monthly ? overview.monthly_trend.map(r => r.cost) : trendItems.map(r => r.total_cost) },
    ],
  };
}

// 构造刀型消耗总量或累计趋势图配置。
export function buildOverviewTypeOption(typeTrend: TypeTrendItem[], typeMode: string) {
  const types = ['DISC', 'SCRAPER'];
  const cumulative = typeMode === 'cumulative';
  const last = typeTrend.at(-1);
  return {
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis' }, grid: { ...DEFAULT_GRID, bottom: cumulative ? 70 : 35 },
    legend: { bottom: 0, show: cumulative },
    xAxis: cumulative ? { type: 'category', name: '环号', data: typeTrend.map(r => r.ring_no) } : { type: 'value', name: '把次', minInterval: 1 },
    yAxis: cumulative ? { type: 'value', name: '累计更换 / 把次', minInterval: 1 } : { type: 'category', data: types.map(t => TOOL_TYPE_LABELS[t]) },
    series: cumulative ? types.map(t => ({ name: TOOL_TYPE_LABELS[t], type: 'line', color: TOOL_TYPE_COLORS[t], data: typeTrend.map(r => r[t as 'DISC' | 'SCRAPER']) })) : [{
      type: 'bar', barMaxWidth: 34, label: { show: true, position: 'right' },
      data: types.map(t => ({ value: last?.[t as 'DISC' | 'SCRAPER'] ?? 0, itemStyle: { color: TOOL_TYPE_COLORS[t] } })),
    }],
  };
}
