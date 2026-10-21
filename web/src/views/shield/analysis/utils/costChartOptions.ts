import { CHART_COLORS, DV_PALETTE, TOOL_TYPE_LABELS, TOOLTIP_STYLE, DEFAULT_GRID } from './chartTheme';
import { escapeHtml, formatCurrency, formatNumber, formatPercent } from './presentation';
import type { BrandCostItem, BrandPerfTrendSeries, BrandPriceTrendData, BrandPriceTrendSeries, CostSources, CostTrendItem, CostTypeBreakdownItem } from '../types';

const sourceConfig = [
  { key: 'installation', trend: 'installation_cost', name: '新装登记', color: CHART_COLORS.primary },
  { key: 'confirmed_repair', trend: 'confirmed_repair_cost', name: '已确认返修', color: CHART_COLORS.good },
  { key: 'legacy', trend: 'legacy_cost', name: '历史登记', color: CHART_COLORS.neutral },
] as const;
const palette = DV_PALETTE;

// 按厂家名称生成稳定颜色。
export function manufacturerColor(name: string) { let hash = 0; for (const character of name || '') hash = (hash * 31 + character.charCodeAt(0)) >>> 0; return palette[hash % palette.length]; }

// 格式化已拆刀服役环数。
export function serviceValue(value: unknown) { return value == null ? '无闭合样本' : `${formatNumber(value, 1)} 环`; }

// 构造费用来源构成图配置。
export function buildCompositionOption(sources: CostSources) {
  return {
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis', valueFormatter: (value: number) => formatCurrency(value) },
    legend: { bottom: 0 }, grid: { left: 28, right: 30, top: 16, bottom: 48, containLabel: true },
    xAxis: { type: 'value', name: '元' }, yAxis: { type: 'category', data: ['明确金额'], axisTick: { show: false } },
    series: sourceConfig.map(item => ({ name: item.name, type: 'bar', stack: 'sources', barMaxWidth: 32, color: item.color, data: [sources[item.key]] })),
  };
}

// 构造开仓环号费用趋势图配置。
export function buildCostTrendOption(costTrend: { items: CostTrendItem[] } | undefined, costMode: string) {
  const items = costTrend?.items ?? [], cumulative = costMode === 'cumulative';
  return {
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis', axisPointer: { type: 'shadow' } }, legend: { bottom: 0, type: 'scroll' }, grid: { ...DEFAULT_GRID, top: 38, right: 48, bottom: 75 },
    xAxis: { type: 'category', data: items.map(item => `${item.ring_no}环`), axisLabel: { hideOverlap: true } },
    yAxis: [{ type: 'value', name: '登记金额（元）' }, { type: 'value', name: cumulative ? '累计金额（元）' : '更换数量（把）', minInterval: cumulative ? undefined : 1 }],
    dataZoom: items.length > 14 ? [{ type: 'inside' }] : [],
    series: [...sourceConfig.map(source => ({ name: source.name, type: 'bar', stack: 'cost', barMaxWidth: 28, color: source.color, data: items.map(item => item[source.trend] ?? null) })),
      { name: cumulative ? '累计明确金额' : '实际更换数量', type: 'line', yAxisIndex: 1, color: CHART_COLORS.ink, smooth: false, symbol: 'circle', symbolSize: 5, data: items.map(item => cumulative ? item.cumulative_cost : item.replacement_count ?? null) }],
  };
}

// 构造刀具类型费用贡献图配置。
export function buildTypeOption(types: CostTypeBreakdownItem[]) {
  return {
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (value: number) => formatCurrency(value) },
    legend: { bottom: 0 }, grid: { ...DEFAULT_GRID, left: 30, right: 45 },
    xAxis: { type: 'value', name: '元' }, yAxis: { type: 'category', data: types.map(item => TOOL_TYPE_LABELS[item.tool_type] || item.tool_type) },
    series: sourceConfig.map(source => ({ name: source.name, type: 'bar', stack: 'sources', barMaxWidth: 34, color: source.color, data: types.map(item => item.cost_sources?.[source.key] ?? null) })),
  };
}

// 构造厂家安装均价与服役环数关系图配置。
export function buildRelationshipOption(relationshipItems: BrandCostItem[]) {
  return {
    tooltip: { ...TOOLTIP_STYLE, trigger: 'item', formatter: (parameter: any) => {
      const item = parameter.data.sample as BrandCostItem;
      return `${escapeHtml(item.manufacturer)}<br/>安装记录均价：${formatCurrency(item.avg_cost)}（${formatNumber(item.priced_count)} 个有价样本）<br/>已拆刀平均服役：${serviceValue(item.avg_lifespan)}（${formatNumber(item.lifespan_count)} 个闭合段）<br/>非正常磨损：${formatPercent(item.abnormal_rate)}（${formatNumber(item.wear_recorded_count)} 个有记录样本）`;
    } },
    grid: { ...DEFAULT_GRID, top: 35, right: 32, bottom: 55 },
    xAxis: { type: 'value', name: '安装均价（元）', nameLocation: 'middle', nameGap: 32 }, yAxis: { type: 'value', name: '服役环数（环）' },
    series: [{ type: 'scatter', symbolSize: 13, data: relationshipItems.map(item => ({ name: item.manufacturer, value: [item.avg_cost, item.avg_lifespan], sample: item, itemStyle: { color: manufacturerColor(item.manufacturer) } })),
      label: { show: relationshipItems.length <= 8, position: 'top', formatter: '{b}', fontSize: 11 }, labelLayout: { hideOverlap: true } }],
  };
}

// 构造厂家指标趋势图配置。
export function buildBrandTrendOption(trend: BrandPriceTrendSeries[], axis: BrandPriceTrendData['time_axis'], brandMetric: string, trendConfig: { unit: string; ratio: boolean }) {
  return {
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis', formatter: (parameters: any[]) => {
      if (!parameters.length) return '';
      const index = parameters[0].dataIndex, point = axis[index];
      if (!point) return '';
      return `${escapeHtml(point.ring_no)} 环 · ${escapeHtml(point.open_time)}<br/>` + parameters.map(parameter => {
        const sample = trend.find(item => item.manufacturer === parameter.seriesName), value = sample?.data[index];
        const formatted = value == null ? '无有效样本' : trendConfig.ratio ? formatPercent(value) : brandMetric === 'price' ? formatCurrency(value) : serviceValue(value);
        const recordedCount = sample?.count_data?.[index];
        if (trendConfig.ratio) {
          const abnormalCount = (sample as BrandPerfTrendSeries | undefined)?.abnormal_count_data?.[index];
          const categoryCount = brandMetric === 'normal'
            ? recordedCount != null && abnormalCount != null ? recordedCount - abnormalCount : undefined
            : abnormalCount;
          const category = brandMetric === 'normal' ? '正常数' : '非正常数';
          return `${escapeHtml(parameter.seriesName)}：${formatted}<br/>${category} / 有记录数：${formatNumber(categoryCount)} / ${formatNumber(recordedCount)}（已闭合配对旧刀）`;
        }
        return `${escapeHtml(parameter.seriesName)}：${formatted}（${brandMetric === 'price' ? '有价新装记录' : '闭合服役段'} ${formatNumber(recordedCount)}）`;
      }).join('<br/>');
    } },
    legend: { bottom: 0, type: 'scroll' }, grid: { ...DEFAULT_GRID, top: 30, right: 30, bottom: 70 },
    xAxis: { type: 'category', data: axis.map(item => `${item.ring_no}环`), axisLabel: { hideOverlap: true } },
    yAxis: { type: 'value', name: trendConfig.unit, min: 0, max: trendConfig.ratio ? 1 : undefined, axisLabel: { formatter: (value: number) => trendConfig.ratio ? `${Math.round(value * 100)}%` : value } },
    dataZoom: axis.length > 14 ? [{ type: 'inside' }] : [],
    series: trend.map(item => ({ name: item.manufacturer, type: 'line', data: item.data, color: manufacturerColor(item.manufacturer), connectNulls: false, smooth: false, symbol: 'circle', symbolSize: 6 })),
  };
}
