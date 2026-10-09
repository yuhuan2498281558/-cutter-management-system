<template>
  <div class="overview-page">
    <div class="analysis-export-bar">
      <el-button :loading="loading" @click="load">重新加载</el-button>
      <el-button type="primary" plain :disabled="!ready" @click="exportPdf">导出 PDF</el-button>
    </div>
    <ScopeSummary :meta="data?.overview.meta" />
    <div v-if="data" class="analysis-metrics">
      <div class="analysis-metric"><span>范围内开仓</span><strong>{{ formatNumber(kpi?.total_openings) }} 次</strong><small>明细有检查证据 {{ formatNumber(kpi?.detail_checked_count) }} 条</small></div>
      <div class="analysis-metric"><span>实际更换明细</span><strong>{{ formatNumber(kpi?.total_replacements) }} 把次</strong><small>含未分类更换 {{ formatNumber(kpi?.total_untyped) }} 把次</small></div>
      <div class="analysis-metric"><span>新装刀具登记金额</span><strong>{{ formatCurrency(sources?.installation) }}</strong><small>缺登记价格 {{ formatNumber(sources?.missing_price_count) }} 条</small></div>
      <div class="analysis-metric"><span>已确认返修登记金额</span><strong>{{ formatCurrency(sources?.confirmed_repair) }}</strong><small>待反馈 {{ formatNumber(sources?.pending_repair_count) }} 条 · 缺返修价 {{ formatNumber(sources?.repair_missing_price_count) }} 条</small></div>
    </div>
    <p v-if="data" class="analysis-note">
      明确金额合计 {{ formatCurrency(sources?.total) }}，其中历史登记 {{ formatCurrency(sources?.legacy) }}；
      待核对候选金额 {{ formatCurrency(sources?.unresolved) }}（{{ formatNumber(sources?.unresolved_count) }} 次更换）不计入合计。
      平均开仓间隔 {{ formatNumber(kpi?.avg_rings_between_openings, 1) }} 环。
    </p>
    <div v-if="data" class="reconciliation">
      <strong>整仓数量核对</strong>
      <span>已确认人工更换汇总 {{ formatNumber(kpi?.summary_replaced_count) }}</span>
      <span>同仓全部有效明细 {{ formatNumber(kpi?.summary_detail_replaced_count) }}</span>
      <span :class="{ discrepancy: kpi?.replacement_gap }">差额 {{ formatNumber(kpi?.replacement_gap) }}</span>
      <small>此处比较整仓数量；上方实际更换数随刀型、厂家筛选。</small>
    </div>
    <div class="analysis-grid">
      <ChartCard title="更换消耗与刀具费用" description="按开仓环号归集；返修在确认后归回拆除开仓" :loading="loading" :error="error" :is-empty="!data?.trend.items.length" chart-height="340px" @retry="load">
        <template #toolbar><el-radio-group v-model="trendMode" size="small"><el-radio-button label="ring">按环</el-radio-button><el-radio-button label="month">按月</el-radio-button></el-radio-group></template>
        <div ref="trendRef" class="overview-chart" />
      </ChartCard>
      <ChartCard title="刀型消耗构成" description="实际更换把次，包含旧记录中的未分类更换" :loading="loading" :error="error" :is-empty="!data?.overview.type_trend.length" chart-height="340px" @retry="load">
        <template #toolbar><el-radio-group v-model="typeMode" size="small"><el-radio-button label="total">总量</el-radio-button><el-radio-button label="cumulative">累计</el-radio-button></el-radio-group></template>
        <div ref="typeRef" class="overview-chart" />
      </ChartCard>
    </div>
    <ChartCard title="近期开仓与来源核对" description="当前工程范围内最近 10 次开仓；查看入口为只读明细" :loading="loading" :error="error" :is-empty="!data?.overview.recent_openings.length" chart-height="auto" @retry="load">
      <el-table :data="data?.overview.recent_openings || []" stripe size="small">
        <el-table-column label="开仓 / 环号" min-width="135"><template #default="{ row }"><el-button link type="primary" @click="viewOpening(row)">{{ row.warehouse_id || row.id }} · {{ row.ring_no }} 环</el-button></template></el-table-column>
        <el-table-column prop="open_time" label="日期" width="110" />
        <el-table-column label="汇总状态" width="105"><template #default="{ row }">{{ STATUS_LABELS[row.summary_status] || '待核实' }}</template></el-table-column>
        <el-table-column prop="replaced_count" label="筛选明细 / 把次" width="125" align="right" />
        <el-table-column label="整仓确认 / 差额" width="130" align="right"><template #default="{ row }">{{ formatNumber(row.summary_replaced_count) }} / {{ formatNumber(row.replacement_gap) }}</template></el-table-column>
        <el-table-column label="新装登记 / 元" width="125" align="right"><template #default="{ row }">{{ formatCurrency(row.cost_sources?.installation) }}</template></el-table-column>
        <el-table-column label="确认返修 / 元" width="125" align="right"><template #default="{ row }">{{ formatCurrency(row.cost_sources?.confirmed_repair) }}</template></el-table-column>
        <el-table-column label="历史登记 / 元" width="125" align="right"><template #default="{ row }">{{ formatCurrency(row.cost_sources?.legacy) }}</template></el-table-column>
        <el-table-column label="明确合计 / 元" width="125" align="right"><template #default="{ row }">{{ formatCurrency(row.cost) }}</template></el-table-column>
        <el-table-column prop="geological_conditions" label="地层背景" min-width="180" />
      </el-table>
    </ChartCard>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import * as echarts from 'echarts';
import ChartCard from '../components/ChartCard.vue';
import ScopeSummary from '../components/ScopeSummary.vue';
import { getCostTrend, getOverview } from '../api';
import { useAnalysisQuery } from '../utils/useAnalysisQuery';
import { analysisExportMeta, formatCurrency, formatNumber, requireAnalysisV2, STATUS_LABELS } from '../utils/presentation';
import { DEFAULT_GRID, TOOLTIP_STYLE, TOOL_TYPE_COLORS, TOOL_TYPE_LABELS } from '../utils/chartTheme';
import { exportAnalysisPdf } from '../utils/pdfExport';
import type { AnalysisFilter, AnalysisMeta, CostTrendItem, OverviewData } from '../types';

const props = defineProps<{ filter: AnalysisFilter }>();
const router = useRouter();
type OverviewResult = OverviewData & { kpi: OverviewData['kpi'] & { summary_detail_replaced_count?: number } };
const { data, loading, error, ready, load } = useAnalysisQuery(() => props.filter, async filter => {
  const [overview, trend] = await Promise.all([getOverview(filter), getCostTrend(filter)]);
  return {
    overview: requireAnalysisV2<OverviewResult>(overview?.data ?? overview),
    trend: requireAnalysisV2<{ meta?: AnalysisMeta; items: CostTrendItem[] }>(trend?.data ?? trend),
  };
});
const kpi = computed(() => data.value?.overview.kpi);
const sources = computed(() => kpi.value?.cost_sources);
const trendMode = ref('ring');
const typeMode = ref('total');
const trendRef = ref<HTMLElement | null>(null);
const typeRef = ref<HTMLElement | null>(null);
let trendChart: echarts.ECharts | null = null;
let typeChart: echarts.ECharts | null = null;
let observer: ResizeObserver | null = null;
let resizeTimer: ReturnType<typeof setTimeout> | undefined;
function resizeCharts() {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { trendChart?.resize(); typeChart?.resize(); }, 80);
}
function renderCharts() {
  if (!data.value || !trendRef.value || !typeRef.value) return;
  if (!trendChart) trendChart = echarts.init(trendRef.value);
  if (!typeChart) typeChart = echarts.init(typeRef.value);
  if (!observer && typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(resizeCharts);
    observer.observe(trendRef.value); observer.observe(typeRef.value);
  }
  const overview = data.value.overview;
  const monthly = trendMode.value === 'month';
  const rows = data.value.trend.items;
  trendChart.setOption({
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis' },
    legend: { bottom: 0, type: 'scroll' }, grid: { ...DEFAULT_GRID, bottom: 78 },
    xAxis: { type: 'category', data: monthly ? overview.monthly_trend.map(r => r.month || '日期未记录') : rows.map(r => r.ring_no), name: monthly ? '月份' : '环号' },
    yAxis: [{ type: 'value', name: '实际更换 / 把次', minInterval: 1 }, { type: 'value', name: '明确金额 / 元' }],
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 14, bottom: 28 }],
    series: [
      { name: '实际更换', type: 'bar', barMaxWidth: 26, itemStyle: { color: '#5470c6' }, data: monthly ? overview.monthly_trend.map(r => r.total_replacements ?? 0) : rows.map(r => r.replacement_count ?? 0) },
      { name: '明确金额', type: 'line', yAxisIndex: 1, connectNulls: false, itemStyle: { color: '#c57932' }, data: monthly ? overview.monthly_trend.map(r => r.cost) : rows.map(r => r.total_cost) },
    ],
  }, true);
  const types = ['DISC', 'SCRAPER'];
  const cumulative = typeMode.value === 'cumulative';
  const last = overview.type_trend.at(-1);
  typeChart.setOption({
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis' }, grid: { ...DEFAULT_GRID, bottom: cumulative ? 70 : 35 },
    legend: { bottom: 0, show: cumulative },
    xAxis: cumulative ? { type: 'category', name: '环号', data: overview.type_trend.map(r => r.ring_no) } : { type: 'value', name: '把次', minInterval: 1 },
    yAxis: cumulative ? { type: 'value', name: '累计更换 / 把次', minInterval: 1 } : { type: 'category', data: types.map(t => TOOL_TYPE_LABELS[t]) },
    series: cumulative ? types.map(t => ({ name: TOOL_TYPE_LABELS[t], type: 'line', color: TOOL_TYPE_COLORS[t], data: overview.type_trend.map(r => r[t as 'DISC' | 'SCRAPER']) })) : [{
      type: 'bar', barMaxWidth: 34, label: { show: true, position: 'right' },
      data: types.map(t => ({ value: last?.[t as 'DISC' | 'SCRAPER'] ?? 0, itemStyle: { color: TOOL_TYPE_COLORS[t] } })),
    }],
  }, true);
  resizeCharts();
}
watch([data, trendMode, typeMode], async () => { await nextTick(); renderCharts(); });
async function viewOpening(row: { id: number; warehouse_id: string }) {
  try { await router.push({ path: '/shield/toolChangeDetail', query: { warehouse_id: row.id, warehouse_code: row.warehouse_id, mode: 'view' } }); }
  catch { ElMessage.error('打开明细失败，请从开仓信息进入查看'); }
}
function exportPdf() {
  if (!ready.value) return;
  exportAnalysisPdf('数据分析 · 概览', '.overview-page', analysisExportMeta(data.value?.overview.meta));
}
window.addEventListener('resize', resizeCharts);
onBeforeUnmount(() => { clearTimeout(resizeTimer); observer?.disconnect(); window.removeEventListener('resize', resizeCharts); trendChart?.dispose(); typeChart?.dispose(); });
</script>

<style scoped>
.overview-page { min-width: 0; padding-bottom: 12px; }
.overview-chart { width: 100%; height: 340px; }
.reconciliation { display: flex; flex-wrap: wrap; gap: 8px 20px; padding: 10px 12px; margin-bottom: 12px; background: var(--el-fill-color-light); border-left: 3px solid var(--el-border-color); font-size: 12px; line-height: 1.7; }
.reconciliation small { flex-basis: 100%; color: var(--el-text-color-secondary); }
.discrepancy { color: var(--el-color-warning-dark-2); font-weight: 600; }
</style>
