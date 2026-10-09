<template>
  <div ref="pageRef" class="wear-page">
    <div class="analysis-export-bar">
      <el-button plain :disabled="loading" @click="loadData">刷新数据</el-button>
      <el-button type="primary" plain :disabled="!ready" @click="exportPdf">导出磨损分析 PDF</el-button>
    </div>

    <ScopeSummary :meta="wearDist?.meta" />
    <div v-if="wearDist" class="analysis-metrics">
      <div class="analysis-metric"><span>有效现场观察明细</span><strong>{{ formatNumber(wearDist.checked_count) }}</strong><small>来自明确检查 / 更换等证据，非整仓人工汇总数</small></div>
      <div class="analysis-metric"><span>已分类磨损样本</span><strong>{{ formatNumber(wearDist.wear_recorded_count) }}</strong><small>正常 {{ formatNumber(wearDist.normal_count) }} · 非正常 {{ formatNumber(wearDist.abnormal_count) }}</small></div>
      <div class="analysis-metric"><span>磨损未分类</span><strong>{{ formatNumber(wearDist.unrecorded_count) }}</strong><small>含未记录或未识别，不计入比例分母</small></div>
      <div class="analysis-metric"><span>已分类样本的非正常比例</span><strong>{{ formatPercent(overallRate) }}</strong><small>非正常样本数 ÷ 已分类磨损样本数</small></div>
    </div>
    <p class="analysis-note">当前页面展示现场磨损观察。“轻微磨损”“无异常”归正常，“中度磨损”“异常磨损”归非正常，比例不等于设备故障率。100% 表示当前已分类样本全部归为非正常；未记录或未识别的描述不参与分母，原始描述保留。厂家检查结果仍在旧刀返修记录；筛选厂家时按已确认旧刀配对归属原安装厂家。</p>
    <section class="analysis-grid wear-charts-section">
      <ChartCard title="磨损记录的样本构成" description="正常、非正常、未分类相加为有效观察明细数；比例分母仅包含前两类。" :loading="loading" :error="error" chart-height="320px" :is-empty="!wearDist?.total" @retry="loadData">
        <div ref="distributionRef" class="wear-chart" style="height:320px" />
      </ChartCard>
      <ChartCard title="按开仓环号：消耗数量与磨损比例" description="柱形读左轴（记录 / 更换数），折线读右轴（比例）。无磨损样本处断开，不画各仓比例的简单均值。" :loading="loading" :error="error" chart-height="320px" :is-empty="!trendRows.length" @retry="loadData">
        <div ref="trendChartRef" class="wear-chart" style="height:320px" />
      </ChartCard>
    </section>
    <section class="wear-opening-section">
      <ChartCard title="逐仓磨损、消耗与地层对照" description="地层是同次开仓的工程背景，关联不等于原因；一仓可能跨多个地层，不能将各地层组重复加总。" :loading="loading" :error="error" chart-height="auto" :is-empty="!trendRows.length" @retry="loadData">
        <el-table :data="trendRows" border size="small" :max-height="480" class="wear-table">
          <el-table-column label="开仓环号" width="100" fixed><template #default="{ row }"><el-button v-if="row.opening_id || row.id" link type="primary" @click="openOpening(row)">{{ row.ring_no }} 环</el-button><span v-else>{{ row.ring_no }} 环</span></template></el-table-column>
          <el-table-column prop="open_time" label="开仓日期" width="110" />
          <el-table-column label="有效观察明细" width="115" align="right"><template #default="{ row }">{{ formatNumber(row.checked_count) }}</template></el-table-column>
          <el-table-column label="实际更换数" width="105" align="right"><template #default="{ row }">{{ formatNumber(row.replacement_count) }}</template></el-table-column>
          <el-table-column prop="total" label="已分类磨损数" width="115" align="right" />
          <el-table-column label="未分类数" width="95" align="right"><template #default="{ row }">{{ formatNumber(row.unrecorded_count) }}</template></el-table-column>
          <el-table-column prop="abnormal" label="非正常数" width="95" align="right" />
          <el-table-column label="非正常比例" width="130" align="right"><template #default="{ row }">{{ formatPercent(row.abnormal_rate) }}</template></el-table-column>
          <el-table-column label="地层类型" min-width="180"><template #default="{ row }">{{ row.stratum_types || '未记录' }}</template></el-table-column>
          <el-table-column label="地质情况" min-width="200"><template #default="{ row }">{{ row.geological_conditions || '未记录' }}</template></el-table-column>
        </el-table>
        <p class="analysis-note">共 {{ trendRows.length }} 次开仓，保留当前范围全部返回记录。点击环号进入既有只读开仓明细。</p>
      </ChartCard>
    </section>
    <section class="wear-description-section">
      <ChartCard title="现场磨损描述明细" description="保留原始描述及系统归类；占比以全部有效观察明细为分母，与上方非正常比例不同。" :loading="loading" :error="error" chart-height="auto" :is-empty="!wearDist?.items.length" @retry="loadData">
        <el-table :data="wearDist?.items ?? []" border size="small" :max-height="340" class="wear-table">
          <el-table-column prop="wear_condition" label="现场描述" min-width="220" />
          <el-table-column label="系统归类" min-width="120"><template #default="{ row }">{{ stateLabel(row.state) }}</template></el-table-column>
          <el-table-column prop="count" label="记录数" min-width="100" align="right" />
          <el-table-column label="占全部观察明细" min-width="160" align="right"><template #default="{ row }">{{ formatPercent(wearDist?.total ? row.count / wearDist.total : null) }}</template></el-table-column>
        </el-table>
      </ChartCard>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onActivated, onDeactivated, onBeforeUnmount, nextTick, computed } from 'vue';
import { useRouter } from 'vue-router';
import * as echarts from 'echarts';
import ChartCard from '../components/ChartCard.vue';
import ScopeSummary from '../components/ScopeSummary.vue';
import { getWearDistribution, getWearTrend } from '../api';
import { TOOLTIP_STYLE, DEFAULT_GRID } from '../utils/chartTheme';
import type { AnalysisFilter, AnalysisMeta, WearDistributionItem, WearTrendItem } from '../types';
import { analysisExportMeta, escapeHtml, formatNumber, formatPercent, requireAnalysisV2 } from '../utils/presentation';
import { useAnalysisQuery } from '../utils/useAnalysisQuery';
import { exportAnalysisPdf } from '../utils/pdfExport';

const props = defineProps<{ filter: AnalysisFilter }>();

interface DistributionData {
  meta?: AnalysisMeta; items: (WearDistributionItem & { state: string | null })[]; total: number;
  checked_count: number; wear_recorded_count: number; unrecorded_count: number; abnormal_count: number; normal_count: number;
}
interface TrendRow extends WearTrendItem { opening_id?: number; wear_recorded_count?: number }
interface TrendData { meta?: AnalysisMeta; items: TrendRow[] }
const router = useRouter();
const pageRef = ref<HTMLElement | null>(null);
const { data, loading, error, ready, load: loadData } = useAnalysisQuery(
  () => props.filter, async filter => {
    const [distribution, trend] = await Promise.all([getWearDistribution(filter), getWearTrend(filter)]);
    return { distribution: requireAnalysisV2<DistributionData>(distribution.data), trend: requireAnalysisV2<TrendData>(trend.data) };
  },
);
const wearDist = computed(() => data.value?.distribution);
const trendRows = computed(() => data.value?.trend.items ?? []);
const overallRate = computed(() => wearDist.value?.wear_recorded_count ? wearDist.value.abnormal_count / wearDist.value.wear_recorded_count : null);
function stateLabel(state: string | null) { return state === 'NORMAL' ? '正常' : state === 'ABNORMAL' ? '非正常' : '未分类'; }
function openOpening(row: TrendRow) {
  const opening = row.opening_id || row.id;
  if (opening) router.push({ path: '/shield/toolChangeDetail', query: { warehouse_id: String(opening), mode: 'view' } });
}

function exportPdf() {
  if (!ready.value) return;
  exportAnalysisPdf('数据分析-现场磨损与刀具消耗', '.wear-page', analysisExportMeta(wearDist.value?.meta));
}

const distributionRef = ref<HTMLElement | null>(null);
const trendChartRef = ref<HTMLElement | null>(null);

let distributionChart: echarts.ECharts | null = null;
let trendChart: echarts.ECharts | null = null;

function ensureChart(instance: echarts.ECharts | null, element: HTMLElement) {
  if (instance && instance.getDom() !== element) { instance.dispose(); instance = null; }
  return instance || echarts.init(element);
}
function renderCharts() {
  if (!ready.value || !wearDist.value) return;
  if (distributionRef.value) {
    distributionChart = ensureChart(distributionChart, distributionRef.value);
    distributionChart.setOption({
      tooltip: { ...TOOLTIP_STYLE, trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { ...DEFAULT_GRID, left: 28, right: 46, bottom: 35 },
      xAxis: { type: 'value', name: '记录数', minInterval: 1 },
      yAxis: { type: 'category', data: ['正常', '非正常', '未分类'], inverse: true },
      series: [{ name: '观察明细', type: 'bar', barMaxWidth: 34, label: { show: true, position: 'right' },
        data: [{ value: wearDist.value.normal_count, itemStyle: { color: '#6f9483' } },
          { value: wearDist.value.abnormal_count, itemStyle: { color: '#b76558' } },
          { value: wearDist.value.unrecorded_count, itemStyle: { color: '#9ba5b1' } }] }],
    }, true);
    distributionChart.resize();
  }
  if (!trendChartRef.value) return;
  trendChart = ensureChart(trendChart, trendChartRef.value);
  const items = trendRows.value;
  trendChart.setOption({
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
      { name: '已分类磨损数', type: 'bar', color: '#9ba5b1', barMaxWidth: 22, data: items.map(item => item.total) },
      { name: '实际更换数', type: 'bar', color: '#35689b', barMaxWidth: 22, data: items.map(item => item.replacement_count ?? null) },
      { name: '非正常比例', type: 'line', yAxisIndex: 1, color: '#b76558', smooth: false, connectNulls: false, symbolSize: 6, data: items.map(item => item.abnormal_rate) },
    ],
  }, true);
  trendChart.resize();
}
let activeCharts = true, resizeFrame: number | undefined;
function scheduleRender() {
  nextTick(() => {
    if (!activeCharts) return;
    if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => { resizeFrame = undefined; if (activeCharts) renderCharts(); });
  });
}
let resizeObserver: ResizeObserver | undefined;
onMounted(() => { resizeObserver = new ResizeObserver(scheduleRender); if (pageRef.value) resizeObserver.observe(pageRef.value); scheduleRender(); });
watch([ready, distributionRef, trendChartRef], scheduleRender, { flush: 'post' });
onDeactivated(() => { activeCharts = false; if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame); });
onActivated(() => { activeCharts = true; scheduleRender(); });
onBeforeUnmount(() => {
  activeCharts = false; if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame);
  resizeObserver?.disconnect(); [distributionChart, trendChart].forEach(chart => chart?.dispose());
});
</script>

<style scoped>
.wear-page { min-width: 0; padding-bottom: 12px; }
.wear-chart { width: 100%; min-width: 0; }
.wear-table { width: 100%; font-variant-numeric: tabular-nums; }
.wear-table :deep(.el-table__cell) { padding: 6px 0; }
.wear-table :deep(.cell) { overflow-wrap: anywhere; }
</style>
