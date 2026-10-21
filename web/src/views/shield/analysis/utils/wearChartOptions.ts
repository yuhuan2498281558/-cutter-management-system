import { CHART_COLORS, TOOLTIP_STYLE, DEFAULT_GRID } from './chartTheme';
import { escapeHtml, formatNumber, formatPercent } from './presentation';
import type { WearTrendItem } from '../types';

interface WearDistributionCounts { normal_count: number; abnormal_count: number; unrecorded_count: number }

// 构造磨损记录样本构成图配置。
export function buildWearDistributionOption(dist: WearDistributionCounts) {
  return {
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { ...DEFAULT_GRID, left: 28, right: 46, bottom: 35 },
    xAxis: { type: 'value', name: '记录数', minInterval: 1 },
    yAxis: { type: 'category', data: ['正常', '非正常', '未分类'], inverse: true },
    series: [{ name: '观察明细', type: 'bar', barMaxWidth: 34, label: { show: true, position: 'right' },
      data: [{ value: dist.normal_count, itemStyle: { color: CHART_COLORS.good } },
        { value: dist.abnormal_count, itemStyle: { color: CHART_COLORS.abnormal } },
        { value: dist.unrecorded_count, itemStyle: { color: CHART_COLORS.muted } }] }],
  };
}

// 构造按开仓环号的消耗数量与磨损比例图配置。
export function buildWearTrendOption(items: WearTrendItem[]) {
  return {
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: 'axis',
      formatter: (params: any[]) => {
        const item = items[params[0]?.dataIndex];
        if (!item) return '';
        return `${escapeHtml(item.ring_no)} 环 · ${escapeHtml(item.open_time)}<br/>有效观察：${formatNumber(item.checked_count)}<br/>实际更换：${formatNumber(item.replacement_count)}<br/>非正常 / 已分类磨损：${formatNumber(item.abnormal)} / ${formatNumber(item.total)}<br/>非正常比例：${formatPercent(item.abnormal_rate)}<br/>未分类磨损：${formatNumber(item.unrecorded_count)}<br/>地层：${escapeHtml(item.stratum_types || '未记录')}<br/>地质：${escapeHtml(item.geological_conditions || '未记录')}`;
      },
    },
    grid: { ...DEFAULT_GRID, left: 28, right: 44, bottom: 65 },
    legend: { bottom: 0, type: 'scroll' },
    xAxis: { type: 'category', data: items.map(item => `${item.ring_no}环`), axisLabel: { hideOverlap: true } },
    yAxis: [{ type: 'value', name: '记录 / 更换数', minInterval: 1 }, { type: 'value', name: '非正常比例', min: 0, max: 1, axisLabel: { formatter: (value: number) => `${Math.round(value * 100)}%` } }],
    dataZoom: items.length > 14 ? [{ type: 'inside' }] : [],
    series: [
      { name: '已分类磨损数', type: 'bar', color: CHART_COLORS.neutral, barMaxWidth: 22, data: items.map(item => item.total) },
      { name: '实际更换数', type: 'bar', color: CHART_COLORS.primary, barMaxWidth: 22, data: items.map(item => item.replacement_count ?? null) },
      { name: '非正常比例', type: 'line', yAxisIndex: 1, color: CHART_COLORS.abnormal, smooth: false, connectNulls: false, symbolSize: 6, data: items.map(item => item.abnormal_rate) },
    ],
  };
}
