<template>
  <div class="custom-analysis-page">
    <div class="analysis-export-bar">
      <el-button type="primary" plain @click="exportPdf">导出PDF</el-button>
    </div>

    <el-card class="custom-config-card" shadow="never">
      <el-form :model="form" inline class="custom-config-form">
        <el-form-item label="图表类型">
          <el-radio-group v-model="form.chart_type" @change="onChartTypeChange">
            <el-radio-button value="line">折线图</el-radio-button>
            <el-radio-button value="matrix">散点矩阵图</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="X轴">
          <el-select
            v-model="form.x_field"
            filterable
            placeholder="选择X轴"
            style="width: 230px"
            @change="loadChart"
          >
            <el-option
              v-for="item in dimensionOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>

        <el-form-item v-if="form.chart_type === 'matrix'" label="Y轴">
          <el-select
            v-model="form.y_field"
            filterable
            placeholder="选择Y轴"
            style="width: 230px"
            @change="loadChart"
          >
            <el-option
              v-for="item in matrixYOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="指标">
          <el-select
            v-model="form.metrics"
            multiple
            collapse-tags
            collapse-tags-tooltip
            :multiple-limit="2"
            filterable
            placeholder="最多选择2个指标"
            style="width: 260px"
            @change="loadChart"
          >
            <el-option
              v-for="item in metricOptions"
              :key="item.value"
              :label="formatMetricLabel(item)"
              :value="item.value"
            />
          </el-select>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="loadChart">生成图表</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <ChartCard
      :title="chartTitle"
      :loading="loading || fieldsLoading"
      :chart-height="chartHeight"
      :is-empty="isChartEmpty"
    >
      <div ref="chartRef" class="custom-chart" :style="{ height: chartHeight }" />
      <div v-if="form.chart_type === 'matrix' && !isChartEmpty" class="matrix-note">
        气泡大小表示{{ selectedMetricMeta[0]?.label || '主指标' }}，颜色表示{{ selectedMetricMeta[1]?.label || selectedMetricMeta[0]?.label || '指标值' }}。
      </div>
    </ChartCard>

    <ChartCard
      title="自定义分析数据表"
      :loading="loading"
      :is-empty="!tableRows.length"
    >
      <el-table :data="tableRows" stripe size="small" style="width: 100%">
        <el-table-column prop="x" :label="chartData?.x_field?.label || 'X轴'" min-width="140" />
        <el-table-column
          v-if="form.chart_type === 'matrix'"
          prop="y"
          :label="chartData?.y_field?.label || 'Y轴'"
          min-width="140"
        />
        <el-table-column
          v-for="metric in selectedMetricMeta"
          :key="metric.value"
          :prop="metric.value"
          :label="formatMetricLabel(metric)"
          min-width="120"
          align="right"
        >
          <template #default="{ row }">
            {{ formatNumber(row[metric.value]) }}
          </template>
        </el-table-column>
      </el-table>
    </ChartCard>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import * as echarts from 'echarts';
import { ElMessage } from 'element-plus';
import ChartCard from '../components/ChartCard.vue';
import { getCustomChart, getCustomFields } from '../api';
import { DEFAULT_GRID, TOOLTIP_STYLE } from '../utils/chartTheme';
import { exportAnalysisPdf } from '../utils/pdfExport';
import type {
  AnalysisFilter,
  CustomChartData,
  CustomFieldOption,
  CustomFieldsData,
  CustomLineSeries,
  CustomMatrixSeries,
} from '../types';

const props = defineProps<{ filter: AnalysisFilter }>();

const loading = ref(false);
const fieldsLoading = ref(false);
const fieldConfig = ref<CustomFieldsData | null>(null);
const chartData = ref<CustomChartData | null>(null);
const chartRef = ref<HTMLElement | null>(null);
let chart: echarts.ECharts | null = null;

const form = reactive({
  chart_type: 'line' as 'line' | 'matrix',
  x_field: 'ring_no',
  y_field: 'tool_parent_type',
  metrics: ['replacement_count', 'abnormal_rate'] as string[],
});

const dimensionOptions = computed(() => {
  return (fieldConfig.value?.dimensions ?? []).filter(item => item.chart_types?.includes(form.chart_type));
});

const matrixYOptions = computed(() => {
  return dimensionOptions.value.filter(item => item.value !== form.x_field);
});

const metricOptions = computed(() => fieldConfig.value?.metrics ?? []);

const selectedMetricMeta = computed(() => {
  const optionMap = new Map(metricOptions.value.map(item => [item.value, item]));
  return form.metrics.map(value => optionMap.get(value)).filter(Boolean) as CustomFieldOption[];
});

const tableRows = computed(() => chartData.value?.rows ?? []);

const isChartEmpty = computed(() => {
  if (!chartData.value) return true;
  if (form.chart_type === 'line') return !(chartData.value.categories?.length);
  return !(chartData.value.x_categories?.length && chartData.value.y_categories?.length);
});

const chartTitle = computed(() => {
  const xLabel = chartData.value?.x_field?.label || 'X轴';
  const yLabel = chartData.value?.y_field?.label;
  const metrics = selectedMetricMeta.value.map(item => item.label).join('、');
  if (form.chart_type === 'matrix') {
    return `${xLabel} × ${yLabel || 'Y轴'} 与 ${metrics || '指标'} 的散点矩阵`;
  }
  return `${xLabel} 与 ${metrics || '指标'} 趋势`;
});

const chartHeight = computed(() => {
  if (form.chart_type === 'matrix') {
    const yCount = chartData.value?.y_categories?.length ?? 0;
    return `${Math.min(Math.max(380, yCount * 50 + 160), 860)}px`;
  }
  return '420px';
});

function ensureMatrixFields() {
  if (form.chart_type !== 'matrix') return true;

  if (!dimensionOptions.value.some(item => item.value === form.x_field)) {
    form.x_field = dimensionOptions.value[0]?.value || '';
  }

  if (!matrixYOptions.value.some(item => item.value === form.y_field)) {
    form.y_field = matrixYOptions.value[0]?.value || '';
  }

  return Boolean(form.x_field && form.y_field && form.x_field !== form.y_field);
}

function exportPdf() {
  exportAnalysisPdf('数据分析-自定义分析', '.custom-analysis-page');
}

function formatMetricLabel(metric: CustomFieldOption) {
  return metric.unit ? `${metric.label}（${metric.unit}）` : metric.label;
}

function formatNumber(value: any) {
  if (value === null || value === undefined || value === '') return '-';
  const number = Number(value);
  if (Number.isNaN(number)) return value;
  return Number.isInteger(number) ? number.toLocaleString() : number.toFixed(2);
}

function normalizeFilter(filter: AnalysisFilter): AnalysisFilter {
  const result: AnalysisFilter = {};
  Object.entries(filter).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      (result as any)[key] = value;
    }
  });
  return result;
}

async function loadFields() {
  fieldsLoading.value = true;
  try {
    const res = await getCustomFields();
    fieldConfig.value = res?.data ?? res;
  } finally {
    fieldsLoading.value = false;
  }
}

function syncDefaults() {
  const defaults = fieldConfig.value?.defaults?.[form.chart_type];
  if (!defaults) return;
  form.metrics = defaults.metrics?.length ? defaults.metrics.slice(0, 2) : form.metrics;
  if (form.chart_type === 'matrix') {
    form.x_field = defaults.x_field || form.x_field;
    if ('y_field' in defaults) {
      form.y_field = defaults.y_field || form.y_field;
    }
    ensureMatrixFields();
  } else {
    form.x_field = defaults.x_field || form.x_field;
  }
}

async function onChartTypeChange() {
  syncDefaults();
  if (form.chart_type === 'line' && !dimensionOptions.value.some(item => item.value === form.x_field)) {
    form.x_field = dimensionOptions.value[0]?.value || 'ring_no';
  }
  if (form.chart_type === 'matrix') {
    ensureMatrixFields();
  }
  await loadChart();
}

async function loadChart() {
  if (!form.metrics.length) return;
  if (form.chart_type === 'line' && !form.x_field) return;
  if (form.chart_type === 'matrix' && !ensureMatrixFields()) {
    ElMessage.warning('请至少选择一个X轴属性和一个不同的Y轴属性');
    return;
  }
  loading.value = true;
  try {
    const params = {
      ...normalizeFilter(props.filter),
      chart_type: form.chart_type,
      x_field: form.x_field,
      y_field: form.chart_type === 'matrix' ? form.y_field : undefined,
      metrics: form.metrics.join(','),
    };
    const res = await getCustomChart(params);
    chartData.value = res?.data ?? res;
    if (
      form.chart_type === 'matrix'
      && !(chartData.value?.x_categories?.length && chartData.value?.y_categories?.length)
    ) {
      ElMessage.warning('当前筛选条件下没有可用于散点矩阵图的数据，请调整X轴、Y轴或筛选条件');
    }
    await nextTick();
    renderChart();
  } catch (error) {
    console.error('生成自定义图表失败', error);
    ElMessage.error('生成图表失败，请检查筛选条件或稍后重试');
  } finally {
    loading.value = false;
    await nextTick();
    chart?.resize();
  }
}

function ensureChart() {
  if (!chartRef.value) return null;
  if (chart && chart.getDom() !== chartRef.value) {
    chart.dispose();
    chart = null;
  }
  if (!chart) chart = echarts.init(chartRef.value);
  return chart;
}

function renderChart() {
  if (!chartData.value) return;
  if (chartData.value.chart_type === 'matrix') {
    renderMatrixChart(chartData.value);
    return;
  }
  renderLineChart(chartData.value);
}

function renderLineChart(data: CustomChartData) {
  const instance = ensureChart();
  if (!instance) return;
  const series = data.series as CustomLineSeries[];
  instance.setOption({
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
      type: 'line',
      yAxisIndex: index,
      data: item.data,
      smooth: false,
      symbol: 'circle',
      symbolSize: 6,
    })),
  }, true);
}

function renderMatrixChart(data: CustomChartData) {
  const instance = ensureChart();
  if (!instance) return;

  const series = data.series as CustomMatrixSeries[];
  const sizeMetric = series[0];
  const colorMetric = series[1] || series[0];
  if (!sizeMetric || !colorMetric) {
    instance.clear();
    return;
  }

  // 用双下划线分隔避免 "1-2" vs "12" 的 key 碰撞
  const colorValueMap = new Map<string, number>();
  colorMetric.data.forEach(item => {
    colorValueMap.set(`${item[0]}__${item[1]}`, Number(item[2]) || 0);
  });

  const rawScatter = sizeMetric.data.map(item => {
    const sizeValue = Number(item[2]) || 0;
    const colorValue = colorValueMap.get(`${item[0]}__${item[1]}`) ?? sizeValue;
    return [item[0], item[1], sizeValue, colorValue] as [number, number, number, number];
  });

  const nonZeroSizes = rawScatter.map(d => d[2]).filter(v => v > 0);
  const colorValues = rawScatter.map(d => d[3]).filter(v => !Number.isNaN(v));
  const maxSize = nonZeroSizes.length ? Math.max(...nonZeroSizes) : 1;
  const minColor = colorValues.length ? Math.min(...colorValues) : 0;
  const maxColor = colorValues.length ? Math.max(...colorValues, minColor + 1) : 1;

  // 把每个点的样式内嵌到数据里，避免函数回调的 TS 类型问题
  const scatterData = rawScatter.map(([xi, yi, sv, cv]) => {
    const isZero = sv === 0;
    const norm = maxColor > minColor ? (cv - minColor) / (maxColor - minColor) : 0;
    return {
      value: [xi, yi, sv, cv],
      itemStyle: isZero
        ? { color: '#d1d5db', opacity: 0.18, borderWidth: 0 }
        : { opacity: 0.88, borderColor: '#fff', borderWidth: 1 },
      label: { color: norm > 0.58 ? '#ffffff' : '#374151' },
    };
  });

  const xCount = data.x_categories?.length ?? 0;
  const yCount = data.y_categories?.length ?? 0;
  // 中文字符约 13px 宽，英文约 7px；取折中估算
  const gridLeft = Math.min(Math.max(72, longestLabelLength(data.y_categories ?? []) * 13), 220);
  // 每格可用像素（宽高取小值，使气泡不溢出格子）
  const gridW = 780 - gridLeft;
  const gridH = parseInt(chartHeight.value) - (xCount > 6 ? 160 : 120);
  const cellSize = Math.max(14, Math.min(56, Math.min(
    gridW / Math.max(xCount, 1),
    gridH / Math.max(yCount, 1),
  )));
  const showLabel = cellSize >= 26;

  instance.setOption({
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: 'item',
      formatter: (params: any) => {
        const xName = data.x_categories?.[params.value[0]] ?? '';
        const yName = data.y_categories?.[params.value[1]] ?? '';
        const sizeVal = params.value[2];
        const colorVal = params.value[3];
        const sizeUnit = sizeMetric.unit ? ` ${sizeMetric.unit}` : '';
        const colorUnit = colorMetric.unit ? ` ${colorMetric.unit}` : '';
        const colorLine = colorMetric.metric !== sizeMetric.metric
          ? `<br/>${colorMetric.name}：${formatNumber(colorVal)}${colorUnit}`
          : '';
        return `<b>${data.x_field.label}：${xName}</b>`
          + `<br/>${data.y_field?.label || 'Y轴'}：${yName}`
          + `<br/>${sizeMetric.name}：${formatNumber(sizeVal)}${sizeUnit}`
          + colorLine;
      },
    },
    grid: {
      top: 20,
      left: gridLeft,
      right: 110,
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
  }, true);
  instance.resize();
}

function longestLabelLength(labels: string[]) {
  return labels.reduce((max, label) => Math.max(max, String(label).length), 0);
}

function onResize() {
  chart?.resize();
}

window.addEventListener('resize', onResize);
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize);
  chart?.dispose();
});

watch(() => props.filter, loadChart, { deep: true });
watch(chartHeight, async () => {
  await nextTick();
  chart?.resize();
});

onMounted(async () => {
  await loadFields();
  syncDefaults();
  await loadChart();
});
</script>

<style scoped>
.custom-analysis-page {
  padding-bottom: 16px;
}

.analysis-export-bar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}

.custom-config-card {
  margin-bottom: 12px;
  border-radius: 8px;
}

.custom-config-card :deep(.el-card__body) {
  padding: 12px 14px 2px;
}

.custom-config-form :deep(.el-form-item) {
  margin-bottom: 10px;
}

.custom-chart {
  width: 100%;
}

.matrix-note {
  margin: -4px 16px 12px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}
</style>
