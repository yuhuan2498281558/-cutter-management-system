<template>
  <div ref="pageRef" class="life-page">
    <AnalysisActions :target="actionsTarget" :generated-at="result?.meta?.generated_at" :refresh="loadData" :refreshing="loading"
      :exports="[{ label: '导出寿命与厂家 PDF', disabled: !ready, run: exportPdf }]" />

    <section class="life-summary-section">
      <ScopeSummary :meta="result?.meta">
        <p v-for="text in basisLines" :key="text">{{ text }}</p>
      </ScopeSummary>
      <div v-if="groups.length > 1" class="life-toolbar">
        <el-radio-group v-model="toolType" size="small" aria-label="刀型">
          <el-radio-button v-for="item in groups" :key="item.tool_parent_type" :value="item.tool_parent_type">{{ item.label }}</el-radio-button>
        </el-radio-group>
      </div>
      <div v-if="group" class="analysis-hero">
        <section class="hero-card analysis-card">
          <div class="hero-label">{{ group.label }}已拆刀计入里程<InfoTip :content="basis.life" /></div>
          <strong class="hero-value">{{ formatNumber(group.summary.removed_count) }} 段</strong>
          <div class="hero-sub">{{ formatNumber(trajectoryCount) }} 条轨迹 · {{ formatNumber(group.manufacturers.length) }} 家厂家</div>
        </section>
        <div class="hero-side">
          <section class="hero-card hero-stat analysis-card">
            <span class="hero-label">在役刀具<InfoTip :content="SERVICE_BASIS" /></span>
            <span class="hero-stat-main">
              <strong class="hero-stat-value">{{ formatNumber(group.summary.in_service_count) }} 把</strong>
              <small v-if="group.summary.in_service_km" class="hero-stat-sub">{{ serviceKmText }}</small>
            </span>
          </section>
          <section class="hero-card analysis-card">
            <h4 class="hero-card-title">需要核对</h4>
            <ReviewList :items="reviewItems" />
          </section>
        </div>
      </div>
    </section>

    <ChartCard class="life-matrix-section" chart-height="auto" :loading="loading" :error="error" :is-empty="!matrixRows.length" @retry="loadData">
      <template #heading>
        <h3 class="chart-title">按轨迹分带对比厂家</h3>
        <InfoTip :content="MATRIX_BASIS" />
      </template>
      <template #toolbar>
        <el-select v-model="metric" size="small" class="metric-select" aria-label="对比指标">
          <el-option v-for="item in LIFE_METRICS" :key="item.key" :label="item.label" :value="item.key" />
        </el-select>
      </template>
      <el-table :data="matrixRows" row-key="key" :tree-props="{ children: 'children' }" border size="small" :max-height="520"
        :row-class-name="({ row }) => row.key === selection?.key ? 'is-selected' : ''" class="life-table" @row-click="selectRow">
        <el-table-column label="轨迹" min-width="190" fixed>
          <template #default="{ row }"><span class="row-label">{{ row.label }}</span><span class="row-sub">{{ row.sub }}</span></template>
        </el-table-column>
        <el-table-column v-for="column in matrixColumns" :key="column.key" :label="column.label" min-width="118" align="right">
          <template #default="{ row }">
            <span v-if="row.views[column.key]" class="metric-cell" :title="row.views[column.key].tip">
              <span class="cell-main">{{ row.views[column.key].main }}</span>
              <span v-if="row.views[column.key].sub" class="cell-sub">{{ row.views[column.key].sub }}</span>
            </span>
            <span v-else class="cell-empty">—</span>
          </template>
        </el-table-column>
      </el-table>
    </ChartCard>

    <section class="life-curve-section">
      <ChartCard :title="`同等里程下的拆除分布 · ${selection?.label ?? ''}`" :description="CURVE_BASIS" chart-height="360px"
        :loading="loading" :error="error" :is-empty="!selectedSegments.length" empty-description="所选轨迹没有计入里程的已拆段" @retry="loadData">
        <div ref="curveRef" class="life-chart" style="height:360px" />
      </ChartCard>
    </section>

    <ChartCard class="analysis-detail-card" chart-height="auto" :loading="loading" :error="error" :is-empty="detailEmpty" @retry="loadData">
      <template #heading>
        <el-tabs v-model="detailTab" class="detail-tabs">
          <el-tab-pane :label="`已拆段 · ${selection?.label ?? ''} · ${formatNumber(selectedSegments.length)}`" name="segments" />
          <el-tab-pane :label="`刀位累计里程 · ${formatNumber(typedPositions.length)}`" name="positions" />
          <el-tab-pane :label="`在役刀具 · ${formatNumber(typedService.length)}`" name="service" />
          <el-tab-pane v-if="excludedCount" :label="`未计入里程 · ${formatNumber(excludedCount)}`" name="excluded" />
        </el-tabs>
        <InfoTip :content="DETAIL_BASIS[detailTab]" />
      </template>
      <!-- 外层 v-show 切换页签；导出选择器指向内层，未显示的页签也能导出 -->
      <div v-show="detailTab === 'segments'">
        <div class="life-segment-section">
          <el-table :data="selectedSegments" border size="small" :max-height="460" class="life-detail-table">
            <el-table-column prop="cutter_position_no" label="刀位" width="80" fixed />
            <el-table-column label="半径" width="110"><template #default="{ row }">{{ radiusText(row.radius_mm) }}</template></el-table-column>
            <el-table-column label="原安装厂家" min-width="140"><template #default="{ row }">{{ row.manufacturer || '未登记厂家' }}</template></el-table-column>
            <el-table-column label="服役环段" width="120"><template #default="{ row }">{{ row.installation_ring_no }}–{{ row.ring_no }} 环</template></el-table-column>
            <el-table-column label="里程（km）" width="100" align="right"><template #default="{ row }">{{ formatNumber(row.km, 1) }}</template></el-table-column>
            <el-table-column label="里程来源" width="110"><template #default="{ row }">{{ sourceText(row.estimated_share) }}</template></el-table-column>
            <el-table-column label="拆除时" width="80"><template #default="{ row }"><span :class="{ 'is-abnormal': row.wear_state === 'ABNORMAL' }">{{ wearStateLabel(row.wear_state) }}</span></template></el-table-column>
            <el-table-column label="刀刃磨损（mm）" width="125" align="right"><template #default="{ row }">{{ formatNumber(row.blade_wear_amount, 2) }}</template></el-table-column>
            <el-table-column label="每百公里磨损（mm）" width="150" align="right"><template #default="{ row }">{{ formatNumber(row.wear_per_100km, 2) }}</template></el-table-column>
            <el-table-column label="安装登记价（元）" width="135" align="right"><template #default="{ row }">{{ formatNumber(row.price, 2) }}</template></el-table-column>
          </el-table>
        </div>
      </div>
      <div v-show="detailTab === 'positions'">
        <div class="life-position-section">
          <el-table :data="typedPositions" border size="small" :max-height="460" class="life-detail-table">
            <el-table-column prop="cutter_position_no" label="刀位" width="80" fixed />
            <el-table-column label="半径" width="110"><template #default="{ row }">{{ radiusText(row.radius_mm) }}</template></el-table-column>
            <el-table-column prop="removed_count" label="已拆段" width="90" align="right" />
            <el-table-column label="已拆里程（km）" width="130" align="right"><template #default="{ row }">{{ formatNumber(row.removed_km, 1) }}</template></el-table-column>
            <el-table-column label="在役已走（km）" width="130" align="right"><template #default="{ row }">{{ row.in_service_km == null ? '—' : formatNumber(row.in_service_km, 1) }}</template></el-table-column>
            <el-table-column label="累计里程（km）" min-width="130" align="right"><template #default="{ row }">{{ formatNumber(row.covered_km, 1) }}</template></el-table-column>
          </el-table>
        </div>
      </div>
      <div v-show="detailTab === 'service'">
        <div class="life-service-section">
          <el-table :data="typedService" border size="small" :max-height="460" class="life-detail-table">
            <el-table-column prop="cutter_position_no" label="刀位" width="80" fixed />
            <el-table-column label="半径" width="110"><template #default="{ row }">{{ radiusText(row.radius_mm) }}</template></el-table-column>
            <el-table-column label="厂家" min-width="140"><template #default="{ row }">{{ row.manufacturer || '未登记厂家' }}</template></el-table-column>
            <el-table-column label="安装环" width="90" align="right"><template #default="{ row }">{{ row.installation_ring_no }}</template></el-table-column>
            <el-table-column label="截至环" width="90" align="right"><template #default="{ row }">{{ row.through_ring_no }}</template></el-table-column>
            <el-table-column label="已走里程（km）" width="130" align="right"><template #default="{ row }">{{ formatNumber(row.km, 1) }}</template></el-table-column>
            <el-table-column label="里程来源" min-width="110"><template #default="{ row }">{{ sourceText(row.estimated_share) }}</template></el-table-column>
          </el-table>
        </div>
      </div>
      <div v-show="detailTab === 'excluded'">
        <div class="life-excluded-section">
          <el-table :data="result?.excluded ?? []" border size="small" class="life-detail-table">
            <el-table-column prop="reason" label="未计入原因" min-width="220" />
            <el-table-column prop="count" label="已拆刀（把）" width="120" align="right" />
          </el-table>
        </div>
      </div>
    </ChartCard>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onActivated, onDeactivated, onBeforeUnmount, nextTick, computed } from 'vue';
import * as echarts from 'echarts';
import InfoTip from '/@/components/InfoTip.vue';
import AnalysisActions from '../components/AnalysisActions.vue';
import ChartCard from '../components/ChartCard.vue';
import ReviewList from '../components/ReviewList.vue';
import ScopeSummary from '../components/ScopeSummary.vue';
import { getLifeMileage } from '../api';
import { LIFE_METRICS, buildDistributionOption, cellView, radiusText, spreadText, wearStateLabel } from '../utils/lifeChartOptions';
import type { CellView, LifeMetric } from '../utils/lifeChartOptions';
import type { AnalysisFilter, LifeMileageData, MileageBand, MileageTrajectory } from '../types';
import { analysisExportMeta, formatNumber, formatPercent, requireAnalysisV2 } from '../utils/presentation';
import { useAnalysisQuery } from '../utils/useAnalysisQuery';
import { exportAnalysisPdf } from '../utils/pdfExport';

const props = defineProps<{ filter: AnalysisFilter; actionsTarget?: HTMLElement | null }>();

interface MatrixRow {
  key: string;
  label: string;
  sub: string;
  radius: [number, number];
  views: Record<string, CellView | null>;
  children?: MatrixRow[];
}

const MATRIX_BASIS = '一行一个 1000 mm 分带，展开看带内每条轨迹（同一半径的刀位）。不少于 5 段给中位数，否则列出各段的值；悬停格子看四分位。不排名，不评最佳厂家。点一行，下方分布图和已拆段明细换成这一行。';
const CURVE_BASIS = '每家一条曲线：横轴是里程，纵轴是该厂家已拆段中在这个里程之前换下的比例；实心点为非正常拆除，空心点为正常或未分类。只描述已拆样本，不是生存曲线，在役刀具不在图上。';
const SERVICE_BASIS = '范围内最后一次开仓时各刀位装着的刀，已走里程算到那次开仓；不进寿命统计。';
const DETAIL_BASIS: Record<string, string> = {
  segments: '按拆除环归入筛选范围；厂家是这把刀安装时登记的厂家。',
  positions: '累计里程 = 该刀位已拆段里程之和 + 在役刀具已走里程；初装刀具没有安装记录，不计入。',
  service: SERVICE_BASIS,
  excluded: '系统未能确认安装与拆除配对，或安装与拆除不在同一刀位、刀位半径未核实的已拆刀。',
};

const pageRef = ref<HTMLElement | null>(null);
const { data: result, loading, error, ready, load: loadData } = useAnalysisQuery(
  () => props.filter, async filter => requireAnalysisV2<LifeMileageData>((await getLifeMileage(filter)).data),
);

const groups = computed(() => result.value?.groups ?? []);
const toolType = ref('DISC');
const group = computed(() => groups.value.find(item => item.tool_parent_type === toolType.value) ?? groups.value[0]);
const basis = computed(() => result.value?.basis ?? {});
const basisLines = computed(() => Object.values(basis.value));
const trajectoryCount = computed(() => (group.value?.bands ?? []).reduce((total, band) => total + band.trajectory_count, 0));
const serviceKmText = computed(() => {
  const spread = group.value?.summary.in_service_km;
  return spread?.median != null ? `已走中位 ${spreadText(spread)} km` : `已走 ${spreadText(spread)} km`;
});

const excludedCount = computed(() => (result.value?.excluded ?? []).reduce((total, item) => total + item.count, 0));
function sourceText(share: number | null) {
  if (share == null) return '—';
  if (share >= 1) return '参考值估算';
  return share <= 0 ? '掘进推算' : `估算 ${formatPercent(share)}`;
}
const reviewItems = computed(() => {
  const revolutions = result.value?.revolution_basis;
  const share = revolutions?.estimated_share ?? 0;
  return [
    {
      name: '里程估算', pending: share > 0, lead: '里程含估算',
      detail: share >= 1 ? `全部按参考值约 ${formatNumber(revolutions?.reference_revolutions_per_ring)} 圈/环推算` : `${formatPercent(share)} 的圈数按参考值推算`,
      tip: basis.value.revolutions,
    },
    {
      name: '未计入里程', pending: excludedCount.value > 0, lead: '未计入里程', detail: `${formatNumber(excludedCount.value)} 把已拆刀`,
      tip: (result.value?.excluded ?? []).map(item => `${item.reason} ${item.count} 把`).join('；'),
    },
  ];
});

// 对比表：一行一个分带，子行是带内每条轨迹；列是全部厂家合计和各厂家
const metric = ref<LifeMetric>('life');
const matrixColumns = computed(() => [
  { key: '', label: '全部厂家' },
  ...(group.value?.manufacturers ?? []).map(name => ({ key: `厂家:${name}`, label: name || '未登记厂家' })),
]);
function views(item: MileageBand | MileageTrajectory): Record<string, CellView | null> {
  return {
    '': cellView(item.summary, metric.value),
    ...Object.fromEntries(item.cells.map(cell => [`厂家:${cell.manufacturer}`, cellView(cell, metric.value)])),
  };
}
const matrixRows = computed<MatrixRow[]>(() => (group.value?.bands ?? []).map(band => ({
  key: `band:${band.radius_min}`,
  label: `R${band.radius_min}–${band.radius_max} mm`,
  sub: `${band.trajectory_count} 条轨迹`,
  radius: [band.radius_min, band.radius_max],
  views: views(band),
  children: band.trajectories.map(track => ({
    key: `track:${track.radius_mm}`, label: radiusText(track.radius_mm), sub: track.positions.join('、'),
    radius: [track.radius_mm, track.radius_mm], views: views(track),
  })),
})));

// 选中的分带或轨迹；没选时默认已拆段最多的分带
const selectedKey = ref('');
const selection = computed<MatrixRow | undefined>(() => {
  const rows = matrixRows.value.flatMap(row => [row, ...(row.children ?? [])]);
  const chosen = rows.find(row => row.key === selectedKey.value);
  if (chosen) return chosen;
  const busiest = [...(group.value?.bands ?? [])].sort((a, b) => b.summary.removed_count - a.summary.removed_count)[0];
  return matrixRows.value.find(row => busiest && row.key === `band:${busiest.radius_min}`);
});
function selectRow(row: MatrixRow) { selectedKey.value = row.key; }
watch(toolType, () => { selectedKey.value = ''; });
watch(groups, items => {
  if (items.length && !items.some(item => item.tool_parent_type === toolType.value)) toolType.value = items[0].tool_parent_type;
});

const selectedSegments = computed(() => {
  const chosen = selection.value;
  if (!chosen) return [];
  const [lower, upper] = chosen.radius;
  return (result.value?.segments ?? []).filter(row => row.tool_parent_type === group.value?.tool_parent_type
    && (lower === upper ? row.radius_mm === lower : row.radius_mm >= lower && row.radius_mm < upper))
    .sort((a, b) => a.radius_mm - b.radius_mm || a.km - b.km);
});
const typedPositions = computed(() => (result.value?.positions ?? []).filter(row => row.tool_parent_type === group.value?.tool_parent_type));
const typedService = computed(() => (result.value?.in_service ?? []).filter(row => row.tool_parent_type === group.value?.tool_parent_type));

const detailTab = ref('segments');
const detailEmpty = computed(() => ({
  segments: !selectedSegments.value.length, positions: !typedPositions.value.length,
  service: !typedService.value.length, excluded: !excludedCount.value,
} as Record<string, boolean>)[detailTab.value]);

function exportPdf() {
  if (!ready.value || !group.value) return;
  const label = `${group.value.label} · ${selection.value?.label ?? ''}`;
  exportAnalysisPdf(`数据分析-寿命与厂家（${group.value.label}）`, [
    { title: '', selector: '.life-summary-section' },
    { title: `按轨迹分带对比厂家：${LIFE_METRICS.find(item => item.key === metric.value)?.label}`, selector: '.life-matrix-section', note: MATRIX_BASIS },
    { title: `同等里程下的拆除分布 · ${label}`, selector: '.life-curve-section', note: CURVE_BASIS },
    { title: `已拆段 · ${label}`, selector: '.life-segment-section', note: DETAIL_BASIS.segments },
    { title: `刀位累计里程 · ${group.value.label}`, selector: '.life-position-section', note: DETAIL_BASIS.positions },
  ], analysisExportMeta(result.value?.meta));
}

const curveRef = ref<HTMLElement | null>(null);
let curveChart: echarts.ECharts | null = null;
function renderCharts() {
  if (!ready.value || !curveRef.value) return;
  if (curveChart && curveChart.getDom() !== curveRef.value) { curveChart.dispose(); curveChart = null; }
  curveChart = curveChart || echarts.init(curveRef.value, 'dv');
  curveChart.setOption(buildDistributionOption(selectedSegments.value), true);
  curveChart.resize();
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
  resizeFrame = requestAnimationFrame(() => { resizeFrame = undefined; if (activeCharts) curveChart?.resize(); });
}
function cancelChartFrames() {
  if (resizeFrame !== undefined) cancelAnimationFrame(resizeFrame);
  if (renderFrame !== undefined) cancelAnimationFrame(renderFrame);
  resizeFrame = undefined; renderFrame = undefined;
}
let resizeObserver: ResizeObserver | undefined;
onMounted(() => { resizeObserver = new ResizeObserver(scheduleResize); if (pageRef.value) resizeObserver.observe(pageRef.value); scheduleRender(); });
watch([ready, curveRef, selectedSegments], scheduleRender, { flush: 'post' });
onDeactivated(() => { activeCharts = false; cancelChartFrames(); });
onActivated(() => { activeCharts = true; scheduleRender(); });
onBeforeUnmount(() => {
  activeCharts = false; cancelChartFrames();
  resizeObserver?.disconnect(); curveChart?.dispose();
});
</script>

<style scoped>
.life-page { min-width: 0; padding-bottom: 12px; }
.life-toolbar { margin: 0 0 12px; }
.life-matrix-section, .life-curve-section { margin-bottom: 12px; }
.metric-select { width: 170px; }
.life-chart { width: 100%; min-width: 0; }
.life-table, .life-detail-table { width: 100%; font-variant-numeric: tabular-nums; }
.life-table :deep(.el-table__row) { cursor: pointer; }
.life-table :deep(.el-table__row.is-selected > td.el-table__cell) { background: var(--dv-hover); }
.life-detail-table :deep(.el-table__cell) { padding: 6px 0; }
.row-label { font-weight: 600; color: var(--dv-text); }
.row-sub { margin-left: 8px; color: var(--dv-text-secondary); font-size: var(--el-font-size-extra-small); }
.metric-cell { display: inline-grid; justify-items: end; line-height: 1.35; }
.cell-main { color: var(--dv-text); }
.cell-sub { color: var(--dv-text-secondary); font-size: var(--el-font-size-extra-small); }
.cell-empty { color: var(--dv-text-muted); }
.is-abnormal { color: var(--dv-danger-text); }
</style>
