<template>
  <div ref="pageRef" class="cost-page">
    <AnalysisActions :target="actionsTarget" :generated-at="costOverview?.meta?.generated_at" :refresh="loadData" :refreshing="costLoading"
      :exports="[{ label: '导出费用来源 PDF', disabled: !costReady, run: exportCompositionPdf }]" />
    <ScopeSummary :meta="costOverview?.meta" />
    <section class="cost-composition-section">
      <div v-if="sources" class="analysis-hero">
        <section class="hero-card analysis-card">
          <div class="hero-label">已明确刀具费用<InfoTip content="新装登记、已确认返修、历史登记三类之和，不是财务结算额" /></div>
          <strong class="hero-value">{{ formatCurrency(sources.total) }}</strong>
          <AmountShare :parts="shareParts" :total="sources.total" />
        </section>
        <div class="hero-side">
          <section v-if="perRing" class="hero-card hero-stat analysis-card">
            <span class="hero-label">按环号跨度摊销<InfoTip v-if="perRing.tip" :content="perRing.tip" /></span>
            <strong class="hero-stat-value">{{ perRing.value }}</strong>
          </section>
          <section class="hero-card analysis-card">
            <h4 class="hero-card-title">需要核对</h4>
            <ReviewList :items="reviewItems" />
          </section>
        </div>
      </div>
    </section>
    <section class="analysis-grid cost-chart-row cost-trend-section">
      <ChartCard :title="costMode === 'consumption' ? '按开仓环号：费用与更换数量' : '按开仓环号：单次与累计费用'"
        description="返修确认后归回换刀开仓，历史环段金额可能更新；更换数量与费用来源不是同一计数。" chart-height="330px"
        :loading="costLoading" :error="costError" :is-empty="!costTrend?.items.length" @retry="loadData">
        <template #toolbar><el-radio-group v-model="costMode" size="small"><el-radio-button label="consumption">更换数量</el-radio-button><el-radio-button label="cumulative">累计费用</el-radio-button></el-radio-group></template>
        <div ref="costTrendRef" class="cost-chart" style="height:330px" />
      </ChartCard>
      <ChartCard title="刀具类型的费用贡献" description="分开新装、已确认返修及历史登记，待核对金额不进入堆叠。" chart-height="330px"
        :loading="costLoading" :error="costError" :is-empty="!costOverview?.type_breakdown.length" @retry="loadData">
        <div ref="typeRef" class="cost-chart" style="height:330px" />
      </ChartCard>
    </section>
    <ChartCard :title="costReady ? `费用来源明细 · ${formatNumber(sourceRows.length)} 条` : '费用来源明细'" :description="SOURCE_DETAIL_BASIS" chart-height="auto"
      :loading="costLoading" :error="costError" :is-empty="!sourceRows.length" @retry="loadData">
      <div class="cost-source-section">
        <p v-if="costOverview?.source_rows_truncated" class="detail-truncated" role="status">只返回了前 {{ formatNumber(sourceRows.length) }} 条（共 {{ formatNumber(costOverview.source_rows_total ?? sourceRows.length) }} 条）</p>
        <el-table :data="visibleSourceRows" size="small" border :max-height="420" class="cost-table" row-key="id" data-analysis-table="sources">
          <el-table-column label="开仓" min-width="135" fixed><template #default="{ row }"><el-button link type="primary" @click="openOpening(row)">{{ row.ring_no }} 环 · {{ row.warehouse_id }}</el-button></template></el-table-column>
          <el-table-column prop="cutter_position_no" label="刀位" width="65" />
          <el-table-column label="金额来源" min-width="135"><template #default="{ row }">{{ sourceLabel(row) }}</template></el-table-column>
          <el-table-column label="登记金额（元）" min-width="135" align="right"><template #default="{ row }">{{ formatCurrency(row.amount) }}</template></el-table-column>
          <el-table-column label="来源厂家" min-width="130"><template #default="{ row }">{{ row.manufacturer || '未核实' }}</template></el-table-column>
          <el-table-column label="装入 / 换下编号" min-width="190"><template #default="{ row }">装入 {{ row.new_tool_number || '未记录' }}<small class="cell-detail">换下 {{ row.old_tool_number || '未记录' }}</small></template></el-table-column>
          <el-table-column label="纳入情况" min-width="220"><template #default="{ row }"><span :class="{ 'needs-review': !row.included }">{{ row.included ? '已计入明确合计' : row.reason || '未纳入' }}</span></template></el-table-column>
        </el-table>
        <el-pagination v-if="sourceRows.length > 50" v-model:current-page="sourcePage" v-model:page-size="sourcePageSize"
          :page-sizes="[50, 100, 200]" :total="sourceRows.length" layout="total, sizes, prev, pager, next" small class="detail-pagination" />
      </div>
    </ChartCard>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import * as echarts from 'echarts';
import InfoTip from '/@/components/InfoTip.vue';
import AmountShare from '../components/AmountShare.vue';
import AnalysisActions from '../components/AnalysisActions.vue';
import ChartCard from '../components/ChartCard.vue';
import ReviewList from '../components/ReviewList.vue';
import ScopeSummary from '../components/ScopeSummary.vue';
import { getCostOverview, getCostTrend } from '../api';
import { CHART_COLORS } from '../utils/chartTheme';
import { buildCostTrendOption, buildTypeOption } from '../utils/costChartOptions';
import { analysisExportMeta, formatCurrency, formatNumber, requireAnalysisV2, SOURCE_LABELS } from '../utils/presentation';
import { useAnalysisQuery } from '../utils/useAnalysisQuery';
import { exportAnalysisPdf } from '../utils/pdfExport';
import type { AnalysisFilter, AnalysisMeta, CostOverviewData, CostSourceRow, CostTrendItem } from '../types';

interface TrendData { meta?: AnalysisMeta; items: CostTrendItem[] }
// 防止误读的口径：页面上在 ⓘ 里，PDF 里写在对应小节标题下
const SOURCE_DETAIL_BASIS = '对应上方工程费用合计。每行一项来源，保留未纳入原因。零价保留为 ¥0，缺价不补零。';
const props = defineProps<{ filter: AnalysisFilter; actionsTarget?: HTMLElement | null }>();
const router = useRouter();
const pageRef = ref<HTMLElement | null>(null);
const costMode = ref('consumption');
const { data: costResult, loading: costLoading, error: costError, ready: costReady, load: loadData } = useAnalysisQuery(
  () => props.filter, async filter => {
    const [overview, trend] = await Promise.all([getCostOverview(filter), getCostTrend(filter)]);
    return { overview: requireAnalysisV2<CostOverviewData>(overview.data), trend: requireAnalysisV2<TrendData>(trend.data) };
  },
);
const costOverview = computed(() => costResult.value?.overview);
const costTrend = computed(() => costResult.value?.trend);
const sources = computed(() => costOverview.value?.cost_sources);
const sourceRows = computed(() => costOverview.value?.source_rows ?? []);
const sourcePage = ref(1);
const sourcePageSize = ref(50);
const visibleSourceRows = computed(() => sourceRows.value.slice((sourcePage.value - 1) * sourcePageSize.value, sourcePage.value * sourcePageSize.value));
watch([sourceRows, sourcePageSize], () => { sourcePage.value = 1; }, { flush: 'sync' });
const shareParts = computed(() => sources.value ? [
  { label: '新装刀具登记', amount: sources.value.installation, color: CHART_COLORS.primary, tip: '装入刀具登记，可能包含维修件' },
  { label: '已确认返修', amount: sources.value.confirmed_repair, color: CHART_COLORS.good, tip: '按对应拆除开仓归集' },
  { label: '历史登记', amount: sources.value.legacy, color: CHART_COLORS.neutral, tip: '保留旧式整刀、维修与未分类来源' },
] : []);
const perRing = computed(() => {
  const allocation = costOverview.value?.cost_per_ring;
  if (!allocation) return null;
  return allocation.available
    ? { value: `${formatCurrency(allocation.total)} / 环`, tip: `分母 ${allocation.ring_count} 环（最大减最小开仓环号加 1），不是实际掘进单环成本` }
    : { value: '暂不计算', tip: allocation.reason || '' };
});
const reviewItems = computed(() => {
  const value = sources.value;
  if (!value) return [];
  const count = (number: number) => formatNumber(number);
  return [
    { name: '缺登记价格', pending: value.missing_price_count > 0, lead: `${count(value.missing_price_count)} 条缺登记价格`, detail: '没有计入金额，合计偏小' },
    { name: '返修待确认', pending: value.pending_repair_count > 0, lead: `${count(value.pending_repair_count)} 条返修待确认`, detail: '确认后，返修金额和合计还会增加' },
    { name: '已确认返修缺价', pending: value.repair_missing_price_count > 0, lead: `${count(value.repair_missing_price_count)} 条已确认返修缺价`, detail: '未计入返修金额' },
    { name: '金额归属待核对', pending: value.unresolved_count > 0, lead: `${count(value.unresolved_count)} 条金额归属待核对（${formatCurrency(value.unresolved)}）`, detail: '未计入合计' },
  ];
});
function sourceLabel(row: CostSourceRow) { return row.source === 'confirmed_repair' && !['CONFIRMED', 'CLOSED'].includes(row.inspection_status || '') ? '返修登记（待确认）' : SOURCE_LABELS[row.source] || row.source; }
function openOpening(row: { opening_id: number; warehouse_id: string }) {
  if (row.opening_id) router.push({ path: '/shield/toolChangeDetail', query: { warehouse_id: String(row.opening_id), warehouse_code: row.warehouse_id, mode: 'view' } });
}
function exportCompositionPdf() {
  if (!costReady.value) return;
  exportAnalysisPdf('数据分析-刀具费用来源', [
    { title: '费用来源与明确合计', selector: '.cost-composition-section' },
    { title: '环号变化与刀型贡献', selector: '.cost-trend-section' },
    { title: '费用来源明细', selector: '.cost-source-section', note: SOURCE_DETAIL_BASIS },
  ], analysisExportMeta(costOverview.value?.meta), [{
    id: 'sources', headers: ['开仓', '刀位', '金额来源', '登记金额（元）', '来源厂家', '装入 / 换下编号', '纳入情况'],
    rows: sourceRows.value.map(row => [
      `${row.ring_no} 环 · ${row.warehouse_id}`, row.cutter_position_no || '', sourceLabel(row), formatCurrency(row.amount),
      row.manufacturer || '未核实', `装入 ${row.new_tool_number || '未记录'}；换下 ${row.old_tool_number || '未记录'}`,
      row.included ? '已计入明确合计' : row.reason || '未纳入',
    ]),
  }]);
}
const costTrendRef = ref<HTMLElement | null>(null);
const typeRef = ref<HTMLElement | null>(null);
const chartInstances = new Map<string, echarts.ECharts>();
const chartInputs = new Map<string, unknown[]>();
function updateChart(key: string, element: HTMLElement | null, option: any) {
  if (!element) return;
  const inputs = key === 'costTrend' ? [costTrend.value, costMode.value] : [costOverview.value?.type_breakdown];
  let chart = chartInstances.get(key);
  if (chart && chart.getDom() !== element) { chart.dispose(); chart = undefined; }
  const previous = chartInputs.get(key);
  if (chart && previous && inputs.every((value, index) => value === previous[index])) return;
  if (!chart) { chart = echarts.init(element, 'dv'); chartInstances.set(key, chart); }
  chart.setOption(option, true); chart.resize();
  chartInputs.set(key, inputs);
}
function renderCharts() {
  if (!costReady.value || !sources.value) return;
  updateChart('costTrend', costTrendRef.value, buildCostTrendOption(costTrend.value, costMode.value));
  updateChart('type', typeRef.value, buildTypeOption(costOverview.value?.type_breakdown ?? []));
}
let activeCharts = true, resizeFrame: number | undefined, renderFrame: number | undefined;
function scheduleRender() {
  nextTick(() => {
    if (!activeCharts) return;
    if (renderFrame !== undefined) cancelAnimationFrame(renderFrame);
    renderFrame = requestAnimationFrame(() => { renderFrame = undefined; if (activeCharts) renderCharts(); });
  });
}
function scheduleResize() {
  if (!activeCharts || resizeFrame !== undefined) return;
  resizeFrame = requestAnimationFrame(() => { resizeFrame = undefined; if (activeCharts) chartInstances.forEach(chart => chart.resize()); });
}
function cancelChartFrames() {
  if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame);
  if (renderFrame !== undefined) cancelAnimationFrame(renderFrame);
  resizeFrame = undefined; renderFrame = undefined;
}
let resizeObserver: ResizeObserver | undefined;
onMounted(() => { resizeObserver = new ResizeObserver(scheduleResize); if (pageRef.value) resizeObserver.observe(pageRef.value); scheduleRender(); });
watch([costReady, costMode, costTrendRef, typeRef], scheduleRender, { flush: 'post' });
onDeactivated(() => { activeCharts = false; cancelChartFrames(); });
onActivated(() => { activeCharts = true; scheduleRender(); scheduleResize(); });
onBeforeUnmount(() => { activeCharts = false; cancelChartFrames(); resizeObserver?.disconnect(); chartInstances.forEach(chart => chart.dispose()); chartInstances.clear(); chartInputs.clear(); });
</script>

<style scoped>
.cost-page { min-width: 0; padding-bottom: 12px; }
.cost-chart { width: 100%; min-width: 0; }
.needs-review { color: var(--dv-warning-text); }
.cost-page .analysis-grid.cost-chart-row { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); }
.detail-truncated { margin: 0 0 8px; font-size: var(--el-font-size-extra-small); color: var(--dv-warning-text); }
.cell-detail { display: block; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.5; margin-top: 3px; }
.cost-table { width: 100%; font-variant-numeric: tabular-nums; }
.cost-table :deep(.el-table__cell) { padding: 5px 0; }
.cost-table :deep(.el-button) { white-space: normal; height: auto; text-align: left; line-height: 1.5; }
.detail-pagination { margin-top: 10px; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
@media (max-width: 900px) {
  .cost-page .analysis-grid.cost-chart-row { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 600px) {
  .cost-page :deep(.chart-card-header) { align-items: flex-start; flex-wrap: wrap; }
}
</style>
