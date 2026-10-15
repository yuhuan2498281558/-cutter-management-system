import type { EChartsOption } from 'echarts';
import type { CustomChartData, CustomLineSeries, CustomMatrixSeries } from '../types';
import { DEFAULT_GRID, TOOLTIP_STYLE } from './chartTheme';
import { escapeHtml } from './presentation';

// 格式化自定义分析图表与表格中的数值。
export function formatNumber(value: any) {
  if (value === null || value === undefined || value === '') return '-';
  const number = Number(value);
  if (Number.isNaN(number)) return value;
  return Number.isInteger(number) ? number.toLocaleString() : number.toFixed(2);
}

// 构造自定义分析的折线或柱图配置。
export function buildLineChartOption(data: CustomChartData): EChartsOption {
  const series = data.series as CustomLineSeries[];
  return {
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis' },
    legend: { data: series.map(item => item.name), bottom: 0, type: 'scroll' },
    grid: { ...DEFAULT_GRID, bottom: 72 },
    xAxis: {
      type: 'category',
      data: data.categories ?? [],
      name: data.x_field.label,
      axisLabel: { interval: 0, rotate: (data.categories?.length ?? 0) > 8 ? 35 : 0 },
    },
    yAxis: series.map((item, index) => ({
      type: 'value',
      name: item.unit ? `${item.name}（${item.unit}）` : item.name,
      position: index === 0 ? 'left' : 'right',
      axisLabel: { formatter: (value: number) => item.unit === '%' ? `${value}%` : value },
    })),
    series: series.map((item, index) => ({
      name: item.name,
      type: ['ring_no', 'month', 'open_time'].includes(data.x_field.value) ? 'line' : 'bar',
      barMaxWidth: 34,
      yAxisIndex: index,
      data: item.data,
      smooth: false,
      symbol: 'circle',
      symbolSize: 6,
    })),
  };
}

// 构造自定义分析的矩阵气泡图配置。
export function buildMatrixChartOption(data: CustomChartData, size: { width: number; height: string }): EChartsOption {
  const series = data.series as CustomMatrixSeries[];
  const sizeMetric = series[0];
  const colorMetric = series[1] || series[0];

  // 用双下划线分隔避免 "1-2" vs "12" 的 key 碰撞
  const colorValueMap = new Map<string, number>();
  colorMetric.data.forEach(item => {
    if (item[2] !== null) colorValueMap.set(`${item[0]}__${item[1]}`, Number(item[2]));
  });

  const rawScatter = sizeMetric.data.filter(item => item[2] !== null).map(item => {
    const sizeValue = Number(item[2]);
    const colorValue = colorValueMap.get(`${item[0]}__${item[1]}`) ?? null;
    return [item[0], item[1], sizeValue, colorValue] as [number, number, number, number | null];
  });

  const nonZeroSizes = rawScatter.map(d => d[2]).filter(v => v > 0);
  const colorValues = rawScatter.map(d => d[3]).filter((v): v is number => v !== null && Number.isFinite(v));
  const maxSize = nonZeroSizes.length ? Math.max(...nonZeroSizes) : 1;
  const minColor = colorValues.length ? Math.min(...colorValues) : 0;
  const maxColor = colorValues.length ? Math.max(...colorValues, minColor + 1) : 1;

  // 把每个点的样式内嵌到数据里，避免函数回调的 TS 类型问题
  const scatterData = rawScatter.map(([xi, yi, sv, cv]) => {
    const isZero = sv === 0;
    const norm = cv !== null && maxColor > minColor ? (cv - minColor) / (maxColor - minColor) : 0;
    return {
      value: [xi, yi, sv, cv],
      itemStyle: cv === null ? { color: '#a8abb2' } : isZero
        ? { color: '#d1d5db', opacity: 0.18, borderWidth: 0 }
        : { opacity: 0.88, borderColor: '#fff', borderWidth: 1 },
      label: { color: norm > 0.58 ? '#ffffff' : '#374151' },
    };
  });

  const xCount = data.x_categories?.length ?? 0;
  const yCount = data.y_categories?.length ?? 0;
  // 中文字符约 13px 宽，英文约 7px；取折中估算
  const width = size.width;
  const gridLeft = Math.min(Math.max(60, longestLabelLength(data.y_categories ?? []) * 13), width < 600 ? 100 : 180);
  // 每格可用像素（宽高取小值，使气泡不溢出格子）
  const gridW = Math.max(40, width - gridLeft - 70);
  const gridH = parseInt(size.height) - (xCount > 6 ? 160 : 120);
  const cellSize = Math.max(14, Math.min(56, Math.min(
    gridW / Math.max(xCount, 1),
    gridH / Math.max(yCount, 1),
  )));
  const showLabel = cellSize >= 26;

  return {
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: 'item',
      formatter: (params: any) => {
        const xName = escapeHtml(data.x_categories?.[params.value[0]] ?? '');
        const yName = escapeHtml(data.y_categories?.[params.value[1]] ?? '');
        const sizeVal = params.value[2];
        const colorVal = params.value[3];
        const sizeUnit = sizeMetric.unit ? ` ${sizeMetric.unit}` : '';
        const colorUnit = colorMetric.unit ? ` ${colorMetric.unit}` : '';
        const colorLine = colorMetric.metric !== sizeMetric.metric
          ? `<br/>${escapeHtml(colorMetric.name)}：${formatNumber(colorVal)}${escapeHtml(colorUnit)}`
          : '';
        return `<b>${escapeHtml(data.x_field.label)}：${xName}</b>`
          + `<br/>${escapeHtml(data.y_field?.label || 'Y轴')}：${yName}`
          + `<br/>${escapeHtml(sizeMetric.name)}：${formatNumber(sizeVal)}${escapeHtml(sizeUnit)}`
          + colorLine;
      },
    },
    grid: {
      top: 20,
      left: gridLeft,
      right: 70,
      bottom: xCount > 6 ? 108 : 72,
      containLabel: false,
    },
    xAxis: {
      type: 'category',
      data: data.x_categories ?? [],
      name: data.x_field.label,
      nameLocation: 'middle',
      nameGap: xCount > 6 ? 88 : 50,
      boundaryGap: true,
      axisTick: { alignWithLabel: true },
      axisLabel: {
        interval: 0,
        rotate: xCount > 6 ? 40 : 0,
        overflow: 'truncate',
        width: xCount > 6 ? 80 : 120,
        fontSize: 12,
      },
      splitLine: { show: true, lineStyle: { color: '#e5e7eb', type: 'dashed' as const } },
      splitArea: { show: true, areaStyle: { color: ['#fafafa', '#ffffff'] } },
    },
    yAxis: {
      type: 'category',
      data: data.y_categories ?? [],
      name: data.y_field?.label || 'Y轴',
      nameLocation: 'end' as const,
      nameGap: 10,
      axisLabel: {
        interval: 0,
        overflow: 'truncate',
        width: gridLeft - 10,
        fontSize: 12,
      },
      splitLine: { show: true, lineStyle: { color: '#e5e7eb', type: 'dashed' as const } },
      splitArea: { show: true, areaStyle: { color: ['#fafafa', '#ffffff'] } },
    },
    visualMap: {
      min: minColor,
      max: maxColor,
      dimension: 3,
      calculable: true,
      orient: 'vertical',
      right: 8,
      top: 'middle',
      itemWidth: 14,
      itemHeight: 120,
      text: [`高`, '低'],
      textStyle: { color: '#6b7280', fontSize: 11 },
      inRange: {
        color: ['#fffbeb', '#fde68a', '#fb923c', '#dc2626', '#7f1d1d'],
      },
    },
    series: [{
      name: sizeMetric.name,
      type: 'scatter',
      data: scatterData,
      symbolSize: (value: number[]) => {
        const v = Number(value[2]) || 0;
        if (v === 0) return 5;
        const ratio = Math.sqrt(v / maxSize);
        return Math.max(8, Math.min(cellSize * 0.84, 10 + ratio * cellSize * 0.74));
      },
      label: {
        show: showLabel,
        formatter: (params: any) => {
          const v = Number(params.value[2]);
          return v === 0 ? '' : formatNumber(v);
        },
        fontSize: Math.max(9, Math.min(12, Math.floor(cellSize / 4))),
      },
      itemStyle: {},
      emphasis: {
        focus: 'self',
        itemStyle: {
          opacity: 1,
          borderColor: '#111827',
          borderWidth: 2,
          shadowBlur: 10,
          shadowColor: 'rgba(0,0,0,0.2)',
        },
      },
    }],
  };
}

function longestLabelLength(labels: string[]) {
  return labels.reduce((max, label) => Math.max(max, String(label).length), 0);
}
