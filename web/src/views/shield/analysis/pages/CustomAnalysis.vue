<template>
  <div class="custom-analysis-page">
    <div class="analysis-export-bar">
      <el-button type="primary" plain :disabled="!ready" @click="exportPdf">导出 PDF</el-button>
    </div>

    <el-card class="custom-config-card analysis-no-export" shadow="never">
      <el-form :model="form" :disabled="fieldsLoading || !fieldConfig" label-position="top" class="custom-config-form">
        <el-form-item label="图表类型">
          <el-radio-group v-model="form.chart_type" @change="onChartTypeChange">
            <el-radio-button label="line">单维比较</el-radio-button>
            <el-radio-button label="matrix">双维矩阵</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="X轴">
          <el-select
            v-model="form.x_field"
            filterable
            placeholder="选择X轴"
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
          <el-button type="primary" :loading="loading || fieldsLoading" :disabled="!form.metrics.length || !!validationError" @click="loadChart">生成图表</el-button>
        </el-form-item>
      </el-form>
    </el-card>
    <p v-if="validationError" role="alert" class="analysis-note">{{ validationError }}</p>
    <div v-if="fieldsError" role="alert" class="analysis-note">{{ fieldsError }} <el-button size="small" @click="retryFields">重新读取字段</el-button></div>
    <ScopeSummary :meta="chartData?.meta" />
    <p v-if="chartData" class="analysis-note">本次聚合 {{ formatNumber(chartData.record_count) }} 条记录，展示 {{ tableRows.length }} 个分组。未记录与零值分别显示；地层分组可能重叠，不能直接加总。</p>

    <ChartCard
      :title="chartTitle"
      :loading="loading || fieldsLoading"
      :chart-height="chartHeight"
      :is-empty="isChartEmpty"
      :error="error"
      :empty-description="!form.metrics.length ? '请选择至少一个指标' : '当前范围没有可分析的数据'"
      @retry="loadChart"
    >
      <div ref="chartRef" class="custom-chart" :style="{ height: chartHeight }" />
      <div v-if="chartData?.chart_type === 'matrix' && !isChartEmpty" class="matrix-note">
        气泡大小表示{{ selectedMetricMeta[0]?.label || '主指标' }}，颜色表示{{ selectedMetricMeta[1]?.label || selectedMetricMeta[0]?.label || '指标值' }}。
      </div>
    </ChartCard>

    <ChartCard
      title="自定义分析数据表"
      :loading="loading"
      :is-empty="!tableRows.length"
      :error="error"
      chart-height="auto"
      @retry="loadChart"
    >
      <el-table :data="tableRows" stripe size="small" style="width: 100%">
        <el-table-column prop="x" :label="chartData?.x_field?.label || 'X轴'" min-width="140" />
        <el-table-column
          v-if="chartData?.chart_type === 'matrix'"
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
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue';
import * as echarts from 'echarts';
import ChartCard from '../components/ChartCard.vue';
import ScopeSummary from '../components/ScopeSummary.vue';
import { getCustomChart, getCustomFields } from '../api';
import { buildLineChartOption, buildMatrixChartOption, formatNumber } from '../utils/customChartOptions';
import { exportAnalysisPdf } from '../utils/pdfExport';
import { analysisExportMeta, requireAnalysisV2 } from '../utils/presentation';
import { useAnalysisQuery } from '../utils/useAnalysisQuery';
import type {
  AnalysisFilter,
  CustomChartData,
  CustomFieldOption,
  CustomFieldsData,
  CustomMatrixSeries,
} from '../types';

const props = defineProps<{ filter: AnalysisFilter }>();

const fieldsLoading = ref(false);
const fieldsError = ref('');
const fieldConfig = ref<CustomFieldsData | null>(null);
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
  return chartData.value?.metrics ?? [];
});

const tableRows = computed(() => chartData.value?.rows ?? []);

const isChartEmpty = computed(() => {
  if (!chartData.value) return true;
  if (chartData.value.chart_type === 'line') return !(chartData.value.categories?.length);
  return !(chartData.value.x_categories?.length && chartData.value.y_categories?.length);
});

const chartTitle = computed(() => {
  const xLabel = chartData.value?.x_field?.label || 'X轴';
  const yLabel = chartData.value?.y_field?.label;
  const metrics = selectedMetricMeta.value.map(item => item.label).join('、');
  if (chartData.value?.chart_type === 'matrix') {
    return `${xLabel} × ${yLabel || 'Y轴'} 与 ${metrics || '指标'} 的散点矩阵`;
  }
  return `${xLabel} · ${metrics || '请选择指标'}${chartData.value && ['ring_no', 'month', 'open_time'].includes(chartData.value.x_field.value) ? '变化' : '比较'}`;
});

const chartHeight = computed(() => {
  if (chartData.value?.chart_type === 'matrix') {
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
  if (!ready.value) return;
  exportAnalysisPdf('数据分析 · 自定义分析', '.custom-analysis-page', analysisExportMeta(chartData.value?.meta));
}

function formatMetricLabel(metric: CustomFieldOption) {
  return metric.unit ? `${metric.label}（${metric.unit}）` : metric.label;
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

let fieldGeneration = 0;
let alive = true;
async function loadFields() {
  const generation = ++fieldGeneration;
  fieldsLoading.value = true;
  fieldsError.value = '';
  try {
    const res = await getCustomFields();
    if (alive && generation === fieldGeneration) fieldConfig.value = res?.data ?? res;
  } catch {
    if (alive && generation === fieldGeneration) fieldsError.value = '分析字段读取失败，请重试';
  } finally {
    if (alive && generation === fieldGeneration) fieldsLoading.value = false;
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
}

function validateQuery(params: AnalysisFilter & { chart_type: string; x_field: string; y_field?: string; metrics: string }) {
  const metrics = params.metrics.split(',');
  const vendor = params.x_field === 'manufacturer' || (params.chart_type === 'matrix' && params.y_field === 'manufacturer') || params.manufacturer || params.manufacturers;
  if (vendor && metrics.some(m => ['abnormal_count', 'abnormal_rate', 'normal_rate'].includes(m))) return '厂家磨损请在成本分析的厂家表现中查看，按已配对旧刀归属。';
  if (vendor && metrics.some(m => ['total_cost', 'cost_per_opening'].includes(m)) && metrics.some(m => !['total_cost', 'cost_per_opening', 'opening_count'].includes(m))) return '厂家费用与数量、均价来自不同样本，请分别查询。';
  if (params.chart_type === 'matrix' && params.x_field === params.y_field) return '矩阵的两个维度不能相同。';
  return '';
}
const queryFilter = computed(() => ({ ...normalizeFilter(props.filter), chart_type: form.chart_type, x_field: form.x_field, y_field: form.chart_type === 'matrix' ? form.y_field : undefined, metrics: form.metrics.join(',') }));
const validationError = computed(() => validateQuery(queryFilter.value));
const { data: chartData, loading, error, ready, load: loadChart } = useAnalysisQuery(() => queryFilter.value, async snapshot => {
  if (!fieldConfig.value) await loadFields();
  if (fieldsError.value) throw new Error(fieldsError.value);
  const params = snapshot as typeof queryFilter.value;
  if (!params.metrics) return null;
  const validation = validateQuery(params);
  if (validation) throw new Error(validation);
  const res = await getCustomChart(params);
  return requireAnalysisV2<CustomChartData>(res?.data ?? res);
});
async function retryFields() {
  await loadFields();
  if (!fieldsError.value) loadChart();
}
watch(chartData, async () => { await nextTick(); if (alive) renderChart(); });

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
  instance.setOption(buildLineChartOption(data), true);
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

  const width = instance.getWidth();
  const height = chartHeight.value;
  instance.setOption(buildMatrixChartOption(data, { width, height }), true);
  instance.resize();
}

let observer: ResizeObserver | null = null;
let resizeTimer: ReturnType<typeof setTimeout> | undefined;
function onResize() { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (!alive) return; chart?.resize(); if (chartData.value?.chart_type === 'matrix') renderChart(); }, 80); }
watch(chartRef, element => { observer?.disconnect(); if (element && typeof ResizeObserver !== 'undefined') { observer = new ResizeObserver(onResize); observer.observe(element); } });

window.addEventListener('resize', onResize);
onBeforeUnmount(() => {
  alive = false; fieldGeneration++; clearTimeout(resizeTimer); observer?.disconnect();
  window.removeEventListener('resize', onResize);
  chart?.dispose();
});

watch(chartHeight, async () => {
  await nextTick();
  chart?.resize();
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
  margin: 0;
}
.custom-config-form { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; align-items: end; padding-bottom: 12px; }
.custom-config-form :deep(.el-select) { width: 100%; }
@media (max-width: 900px) { .custom-config-form { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 520px) { .custom-config-form { grid-template-columns: 1fr; } }

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
