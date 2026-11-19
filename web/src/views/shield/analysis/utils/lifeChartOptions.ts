import { TOOLTIP_STYLE, DEFAULT_GRID } from './chartTheme';
import { manufacturerColor } from './costChartOptions';
import { escapeHtml, formatNumber } from './presentation';
import type { MileageSegment, MileageSpread, MileageSummary } from '../types';

// 对比表可切换的指标；单位写在下拉选项里，格子里只写数
export const LIFE_METRICS = [
  { key: 'life', label: '至更换里程（km）' },
  { key: 'abnormal', label: '非正常拆除' },
  { key: 'wear', label: '每百公里磨损（mm）' },
  { key: 'cost', label: '成本强度（元/km）' },
  { key: 'service', label: '在役刀具' },
] as const;
export type LifeMetric = typeof LIFE_METRICS[number]['key'];

export interface CellView { main: string; sub: string; tip: string }

// 不少于 5 段给中位数，否则列出各段的值
export function spreadText(spread: MileageSpread | null | undefined, digits = 1): string {
  if (!spread) return '—';
  if (spread.median != null) return formatNumber(spread.median, digits);
  return (spread.values ?? []).map(value => formatNumber(value, digits)).join('、');
}

export function spreadTip(spread: MileageSpread | null | undefined, unit: string, digits = 1): string {
  if (!spread) return '';
  if (spread.median != null) {
    return `中位 ${formatNumber(spread.median, digits)} ${unit}，四分位 ${formatNumber(spread.q1, digits)}–${formatNumber(spread.q3, digits)} ${unit}，${spread.count} 段`;
  }
  return `${spread.count} 段，各段 ${spreadText(spread, digits)} ${unit}；少于 5 段不给中位数`;
}

// 对比表一个格子显示什么；这一组没有对应样本时返回 null，表格显示"—"
export function cellView(summary: MileageSummary | undefined, metric: LifeMetric): CellView | null {
  if (!summary) return null;
  if (metric === 'service') {
    if (!summary.in_service_count) return null;
    return { main: `${summary.in_service_count} 把`, sub: `已走 ${spreadText(summary.in_service_km)}`, tip: spreadTip(summary.in_service_km, 'km') };
  }
  if (!summary.removed_count) return null;
  if (metric === 'life') return { main: spreadText(summary.life_km), sub: `${summary.removed_count} 段`, tip: spreadTip(summary.life_km, 'km') };
  if (metric === 'wear') {
    if (!summary.wear_per_100km) return null;
    return { main: spreadText(summary.wear_per_100km, 2), sub: `${summary.wear_per_100km.count} 段`, tip: spreadTip(summary.wear_per_100km, 'mm/100km', 2) };
  }
  if (metric === 'abnormal') {
    return {
      main: `${summary.abnormal_count}/${summary.classified_count}`,
      sub: summary.unclassified_count ? `未分类 ${summary.unclassified_count}` : '',
      tip: '非正常拆除段数 / 拆除时磨损已分类的段数',
    };
  }
  if (summary.cost_per_km == null) return { main: '—', sub: `${summary.priced_count} 段有价`, tip: '有安装登记价的已拆段少于 5 段，不给出' };
  return { main: formatNumber(summary.cost_per_km, 1), sub: `${summary.priced_count} 段`, tip: '安装登记价合计 ÷ 里程合计' };
}

// 半径是图纸标注值，不加千分位
export function radiusText(radius: number) { return `R${Number(radius)} mm`; }

const STATE_LABELS: Record<string, string> = { NORMAL: '正常', ABNORMAL: '非正常' };
export function wearStateLabel(state: string | null) { return state ? STATE_LABELS[state] ?? '未分类' : '未分类'; }

// 同等里程下的拆除分布：每家一条累计曲线，横轴里程，纵轴该厂家已拆段中在此里程前换下的比例
export function buildDistributionOption(segments: MileageSegment[]) {
  const names = [...new Set(segments.map(row => row.manufacturer))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
  const series = names.map(name => {
    const rows = segments.filter(row => row.manufacturer === name).sort((a, b) => a.km - b.km);
    const color = manufacturerColor(name);
    return {
      name: name || '未登记厂家', type: 'line', step: 'end', color, symbolSize: 7, lineStyle: { width: 1.5 },
      data: [
        { value: [0, 0], symbol: 'none' },
        ...rows.map((row, index) => ({
          value: [row.km, Math.round(((index + 1) / rows.length) * 1000) / 10],
          symbol: row.wear_state === 'ABNORMAL' ? 'circle' : 'emptyCircle',
          segment: row,
        })),
      ],
    };
  });
  return {
    tooltip: {
      ...TOOLTIP_STYLE, trigger: 'item',
      formatter: (params: { seriesName: string; data?: { segment?: MileageSegment; value: number[] } }) => {
        const row = params.data?.segment;
        if (!row) return '';
        return `${escapeHtml(params.seriesName)}<br/>刀位 ${escapeHtml(row.cutter_position_no)} · ${radiusText(row.radius_mm)}<br/>`
          + `第 ${escapeHtml(row.installation_ring_no)}–${escapeHtml(row.ring_no)} 环 · ${formatNumber(row.km, 1)} km<br/>`
          + `拆除时${wearStateLabel(row.wear_state)} · 本厂家已拆 ${formatNumber(params.data?.value[1], 1)}%`;
      },
    },
    legend: { bottom: 0, type: 'scroll' },
    grid: { ...DEFAULT_GRID, top: 30, right: 32, bottom: 50 },
    xAxis: { type: 'value', name: '里程（km）', min: 0 },
    yAxis: { type: 'value', name: '已拆比例', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
    series,
  };
}
