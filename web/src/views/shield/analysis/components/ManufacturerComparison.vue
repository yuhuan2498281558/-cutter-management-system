<template>
  <div ref="rootRef" class="brand-comparison">
    <div class="section-heading" role="group" aria-label="厂家对比条件">
      <h3>厂家对比</h3><InfoTip :content="BRAND_TABLE_BASIS" />
      <span class="section-note">沿用上方条件，只收窄厂家</span>
      <el-form class="brand-filter-form" @submit.prevent>
        <el-select v-model="brandFilterForm.manufacturers" class="brand-select" aria-label="对比厂家" multiple clearable filterable collapse-tags collapse-tags-tooltip
          placeholder="当前范围全部厂家" :disabled="optionsLoading || !!optionsError" @change="applyBrandFilter">
          <template #prefix><span class="control-label">对比厂家</span></template>
          <el-option v-for="name in manufacturerOptions" :key="name" :label="name" :value="name" />
        </el-select>
        <el-select v-model="brandFilterForm.limit" class="limit-select" aria-label="图上显示" :disabled="!!focusedManufacturer || !!appliedBrandFilter.manufacturers.length">
          <template #prefix><span class="control-label">图上显示</span></template>
          <el-option :value="5" label="按金额前 5 家" /><el-option :value="8" label="按金额前 8 家" /><el-option :value="0" label="全部厂家" />
        </el-select>
        <el-button @click="resetBrandFilter">重置厂家条件</el-button>
      </el-form>
    </div>
    <div v-if="optionsError" class="option-error" role="alert">厂家筛选项加载失败，当前统计范围未改变。<el-button link type="primary" @click="loadOptions">重新加载</el-button></div>
    <section class="brand-section">
      <ChartCard title="厂家综合对照" chart-height="auto" :loading="brandLoading" :error="brandError" :is-empty="!brandSummaryItems.length" @retry="loadBrandData"
        description="表格保留全部厂家，按明确金额排序。安装均价、旧刀磨损与服役环数各有不同样本，不能直接据此判断厂家优劣。">
        <el-table :data="brandSummaryItems" size="small" border :max-height="480" row-key="manufacturer" class="brand-table">
          <el-table-column prop="manufacturer" label="厂家 / 图形聚焦" min-width="170" fixed><template #default="{ row }"><button class="manufacturer-button" :aria-pressed="focusedManufacturer === row.manufacturer" @click="focusManufacturer(row.manufacturer)"><i :style="{ background: manufacturerColor(row.manufacturer) }" />{{ row.manufacturer }}</button></template></el-table-column>
          <el-table-column label="安装与费用来源">
            <el-table-column label="更换 / 新装记录" min-width="130" align="right"><template #default="{ row }">{{ formatNumber(row.count) }} 次更换<small class="cell-detail">现代新装 {{ formatNumber(row.installation_count) }} / 历史 {{ formatNumber(row.legacy_replacement_count) }}</small></template></el-table-column>
            <el-table-column prop="total_cost" label="明确金额（元）" min-width="135" sortable align="right"><template #default="{ row }">{{ formatCurrency(row.total_cost) }}</template></el-table-column>
            <el-table-column label="安装记录均价 / 样本" min-width="165" align="right"><template #default="{ row }">{{ formatCurrency(row.avg_cost) }}<small class="cell-detail">有价 {{ formatNumber(row.priced_count) }} / 缺价 {{ formatNumber(row.missing_price_count) }}</small></template></el-table-column>
          </el-table-column>
          <el-table-column label="换下旧刀的原安装厂家表现">
            <el-table-column label="已拆刀平均服役环数" min-width="175" align="right"><template #default="{ row }">{{ serviceValue(row.avg_lifespan) }}<small class="cell-detail">闭合服役段 {{ formatNumber(row.lifespan_count) }}</small></template></el-table-column>
            <el-table-column label="非正常磨损比例 / 样本" min-width="175" align="right"><template #default="{ row }">{{ formatPercent(row.abnormal_rate) }}<small class="cell-detail">非正常 {{ formatNumber(row.abnormal_count) }} / 有记录 {{ formatNumber(row.wear_recorded_count) }}</small></template></el-table-column>
            <el-table-column label="记录待完善" min-width="150" align="right"><template #default="{ row }">磨损未分类 {{ formatNumber(row.unrecorded_wear_count) }}<small class="cell-detail">配对待核对 {{ formatNumber(row.pairing_unresolved_count) }}</small></template></el-table-column>
          </el-table-column>
        </el-table>
        <p v-if="unknownManufacturerLine" class="analysis-note">{{ unknownManufacturerLine }}</p>
      </ChartCard>
      <div v-if="brandReady" class="graph-scope" role="status"><span>{{ focusedManufacturer ? `图形聚焦：${focusedManufacturer}` : `图形显示 ${visibleBrands.length} 家；表格共 ${brandSummaryItems.length} 家` }}</span><el-button v-if="focusedManufacturer" link type="primary" @click="focusedManufacturer = ''">查看全部对比厂家</el-button></div>
      <div class="analysis-grid brand-chart-row">
        <section>
          <ChartCard title="安装均价与已拆刀服役环数" chart-height="350px" :loading="brandLoading" :error="brandError" :is-empty="!relationshipItems.length" @retry="loadBrandData"
            empty-description="当前厂家没有同时具备安装价格和闭合服役段的数据；已有单项数据仍保留在上表。"
            description="每点一个厂家。两个坐标来自不同样本群，只表达并列观察，不代表单把刀具的价格与服役关系。">
            <div ref="relationshipRef" class="brand-chart" style="height:350px" />
          </ChartCard>
        </section>
        <section>
          <ChartCard :title="trendConfig.title" chart-height="350px" :loading="brandLoading" :error="brandError" :is-empty="!hasTrendData" @retry="loadBrandData"
            empty-description="当前图形范围没有该指标的有效样本，请查看其他指标或上表缺失说明。"
            :description="trendConfig.ratio ? '仅统计已闭合配对旧刀中有现场磨损记录的样本。100% 表示这些样本全部归入当前类别，不表示全部供货刀具失效。缺测处断开。' : '单个样本点仍显示，缺测处断开。价格按安装开仓，旧刀表现按拆除开仓归集。'">
            <template #toolbar><el-select v-model="brandMetric" size="small" class="metric-select"><el-option label="安装记录均价" value="price" /><el-option label="已拆刀服役环数" value="service" /><el-option label="非正常磨损比例" value="abnormal" /><el-option label="正常磨损比例" value="normal" /></el-select></template>
            <div ref="brandTrendRef" class="brand-chart" style="height:350px" />
          </ChartCard>
        </section>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
// 厂家对比：从成本页搬来的一整块（厂家筛选、综合对照表、两张图和厂家对照 PDF），刷新和导出交给所在页面的操作区
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue';
import * as echarts from 'echarts';
import InfoTip from '/@/components/InfoTip.vue';
import ChartCard from './ChartCard.vue';
import { getFilterOptions, getBrandComparison } from '../api';
import { buildRelationshipOption, buildBrandTrendOption, manufacturerColor, serviceValue } from '../utils/costChartOptions';
import { analysisExportMeta, formatCurrency, formatNumber, formatPercent, requireAnalysisV2 } from '../utils/presentation';
import { useAnalysisQuery } from '../utils/useAnalysisQuery';
import { exportAnalysisPdf } from '../utils/pdfExport';
import type { AnalysisFilter, BrandComparisonData } from '../types';

interface OptionData { manufacturers: string[] }
// 防止误读的口径：页面上在 ⓘ 里，PDF 里写在对应小节标题下
const BRAND_TABLE_BASIS = '厂家表不含未知厂家，不能将表内合计当作工程总计。';
function requireBrandData(data: BrandComparisonData): BrandComparisonData {
  requireAnalysisV2(data);
  const nullableNumber = (value: unknown) => value === null || (typeof value === 'number' && Number.isFinite(value));
  const sampleCount = (value: unknown) => typeof value === 'number' && Number.isInteger(value) && value >= 0;
  const series = [data.series, data.lifespan_series, data.abnormal_rate_series, data.normal_rate_series];
  const valid = Array.isArray(data.items) && Array.isArray(data.time_axis) && series.every(Array.isArray) && data.items.every(item => (
    item !== null && typeof item === 'object'
    && nullableNumber(item.avg_lifespan) && nullableNumber(item.avg_cost)
    && sampleCount(item.lifespan_count) && sampleCount(item.paired_count) && sampleCount(item.priced_count)
  ));
  if (!valid) throw new Error('厂家分析服务尚未更新，缺少完整的服役与配对数据。请重启后端后重新加载。');
  return data;
}
const props = defineProps<{ filter: AnalysisFilter }>();
const rootRef = ref<HTMLElement | null>(null);
const brandMetric = ref('price');
const focusedManufacturer = ref('');
const brandFilterForm = reactive({ manufacturers: [] as string[], limit: 8 });
const appliedBrandFilter = ref({ manufacturers: [] as string[] });
function values(value: unknown): string[] {
  return (Array.isArray(value) ? value : String(value ?? '').split(',')).map(String).map(item => item.trim()).filter(Boolean);
}
function restrictedSelection(selected: string[], inherited: string[]): string[] { return inherited.length ? selected.filter(value => inherited.includes(value)) : selected; }
function buildBrandFilter(): AnalysisFilter {
  const filter = { ...props.filter };
  const selected = restrictedSelection(appliedBrandFilter.value.manufacturers, [...values(filter.manufacturer), ...values(filter.manufacturers)]);
  if (selected.length) {
    // API combines these parameters with OR; an explicit subset must replace the inherited list.
    delete filter.manufacturer; filter.manufacturers = selected.join(',');
  }
  return filter;
}
watch(() => props.filter, () => {
  brandFilterForm.manufacturers = [];
  appliedBrandFilter.value = { manufacturers: [] }; focusedManufacturer.value = '';
}, { deep: true, flush: 'sync' });
const { data: brandResult, loading: brandLoading, error: brandError, ready: brandReady, load: loadBrandData } = useAnalysisQuery(
  buildBrandFilter, async filter => requireBrandData((await getBrandComparison(filter)).data),
);
const { data: optionData, loading: optionsLoading, error: optionsError, load: loadOptions } = useAnalysisQuery<OptionData>(
  () => props.filter, async filter => (await getFilterOptions(filter)).data,
);
const brandSummaryItems = computed(() => brandResult.value?.items ?? []);
const unknownManufacturerLine = computed(() => {
  const count = Number(brandResult.value?.unknown_manufacturer_count) || 0;
  const amount = Number(brandResult.value?.unknown_manufacturer_amount) || 0;
  if (!count && !amount) return '';
  return `${formatNumber(count)} 条更换记录缺厂家、${formatCurrency(amount)}明确金额厂家未核实，不在本表`;
});
const manufacturerOptions = computed(() => restrictedSelection(
  [...new Set([...(optionData.value?.manufacturers ?? []), ...brandSummaryItems.value.map(item => item.manufacturer)])],
  [...values(props.filter.manufacturer), ...values(props.filter.manufacturers)],
));
function applyBrandFilter() {
  appliedBrandFilter.value = {
    manufacturers: brandFilterForm.manufacturers.filter(name => manufacturerOptions.value.includes(name)),
  };
  focusedManufacturer.value = '';
}
function resetBrandFilter() {
  brandFilterForm.manufacturers = []; brandFilterForm.limit = 8;
  appliedBrandFilter.value = { manufacturers: [] }; focusedManufacturer.value = '';
}
const visibleBrands = computed(() => {
  const rows = brandSummaryItems.value;
  if (focusedManufacturer.value) return rows.filter(row => row.manufacturer === focusedManufacturer.value);
  return appliedBrandFilter.value.manufacturers.length || !brandFilterForm.limit ? rows : rows.slice(0, brandFilterForm.limit);
});
const relationshipItems = computed(() => visibleBrands.value.filter(row => row.avg_cost != null && row.avg_lifespan != null && (row.priced_count ?? 0) > 0 && (row.lifespan_count ?? 0) > 0));
const trendConfig = computed(() => ({
  price: { title: '按开仓环号：安装记录均价', unit: '元', ratio: false },
  service: { title: '按拆除环号：已拆刀平均服役环数', unit: '环', ratio: false },
  abnormal: { title: '按拆除环号：非正常磨损比例', unit: '%', ratio: true },
  normal: { title: '按拆除环号：正常磨损比例', unit: '%', ratio: true },
}[brandMetric.value] || { title: '', unit: '', ratio: false }));
const selectedTrend = computed(() => {
  if (!brandResult.value) return [];
  const data = brandResult.value;
  const list = brandMetric.value === 'price' ? data.series : brandMetric.value === 'service' ? data.lifespan_series : brandMetric.value === 'normal' ? data.normal_rate_series : data.abnormal_rate_series;
  const visible = new Set(visibleBrands.value.map(item => item.manufacturer));
  return list.filter(item => visible.has(item.manufacturer));
});
const hasTrendData = computed(() => selectedTrend.value.some(item => item.data.some(value => value != null)));
function focusManufacturer(name: string) { focusedManufacturer.value = focusedManufacturer.value === name ? '' : name; }
function exportPdf() {
  if (!brandReady.value) return;
  exportAnalysisPdf('数据分析-厂家对照与服役表现', [
    { title: '厂家对照与指标', selector: '.brand-section', note: BRAND_TABLE_BASIS },
  ], [
    ...analysisExportMeta(brandResult.value?.meta),
    { label: '图形展示', value: focusedManufacturer.value || (appliedBrandFilter.value.manufacturers.length ? '选定厂家' : brandFilterForm.limit ? `按明确金额前 ${brandFilterForm.limit} 家；表格保留全部` : '全部厂家') },
    { label: '当前趋势指标', value: trendConfig.value.title },
  ]);
}
// 所在页面的标题行操作区用这些刷新、导出和判断是否在加载
defineExpose({ load: loadBrandData, loading: brandLoading, ready: brandReady, exportPdf });

const relationshipRef = ref<HTMLElement | null>(null);
const brandTrendRef = ref<HTMLElement | null>(null);
const chartInstances = new Map<string, echarts.ECharts>();
const chartInputs = new Map<string, unknown[]>();
function updateChart(key: string, element: HTMLElement | null, option: any) {
  if (!element) return;
  const inputs = key === 'relationship' ? [visibleBrands.value] : [selectedTrend.value, brandMetric.value];
  let chart = chartInstances.get(key);
  if (chart && chart.getDom() !== element) { chart.dispose(); chart = undefined; }
  const previous = chartInputs.get(key);
  if (chart && previous && inputs.every((value, index) => value === previous[index])) return;
  if (!chart) { chart = echarts.init(element, 'dv'); chartInstances.set(key, chart); }
  chart.setOption(option, true); chart.resize();
  chartInputs.set(key, inputs);
}
function renderCharts() {
  if (!brandReady.value || !brandResult.value) return;
  updateChart('relationship', relationshipRef.value, buildRelationshipOption(relationshipItems.value));
  updateChart('brandTrend', brandTrendRef.value, buildBrandTrendOption(selectedTrend.value, brandResult.value.time_axis, brandMetric.value, trendConfig.value));
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
onMounted(() => { resizeObserver = new ResizeObserver(scheduleResize); if (rootRef.value) resizeObserver.observe(rootRef.value); scheduleRender(); });
watch([brandReady, brandMetric, visibleBrands, relationshipRef, brandTrendRef], scheduleRender, { flush: 'post' });
onDeactivated(() => { activeCharts = false; cancelChartFrames(); });
onActivated(() => { activeCharts = true; scheduleRender(); scheduleResize(); });
onBeforeUnmount(() => { activeCharts = false; cancelChartFrames(); resizeObserver?.disconnect(); chartInstances.forEach(chart => chart.dispose()); chartInstances.clear(); chartInputs.clear(); });
</script>

<style scoped>
.brand-comparison { min-width: 0; margin-bottom: 12px; }
.brand-chart { width: 100%; min-width: 0; }
.section-heading { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin: 8px 0 12px; }
.section-heading h3 { margin: 0; font-size: var(--el-font-size-medium); font-weight: 600; color: var(--dv-text); }
.section-note { font-size: var(--el-font-size-extra-small); color: var(--dv-text-muted); }
.brand-filter-form { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-left: auto; }
.control-label { font-size: var(--el-font-size-extra-small); color: var(--dv-text-muted); white-space: nowrap; }
.brand-select { width: 300px; }
.limit-select { width: 200px; }
.option-error { margin: -4px 0 12px; font-size: var(--el-font-size-extra-small); color: var(--el-color-danger); }
.metric-select { width: 160px; }
.cell-detail { display: block; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.5; margin-top: 3px; }
.manufacturer-button { display: inline-flex; align-items: center; gap: 7px; padding: 2px 0; border: 0; color: var(--el-color-primary); background: transparent; text-align: left; font: inherit; cursor: pointer; overflow-wrap: anywhere; }
.manufacturer-button i { width: 7px; height: 7px; flex: 0 0 7px; border-radius: var(--dv-radius-pill); }
.manufacturer-button[aria-pressed="true"] { font-weight: 600; text-decoration: underline; text-underline-offset: 4px; }
.manufacturer-button:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.graph-scope { display: flex; align-items: center; gap: 12px; font-size: 12px; margin: 2px 0 10px; color: var(--el-text-color-secondary); }
.brand-table { width: 100%; font-variant-numeric: tabular-nums; }
.brand-table :deep(.el-table__cell) { padding: 5px 0; }
.brand-chart-row > section { min-width: 0; }
@media (max-width: 600px) {
  .brand-filter-form { margin-left: 0; width: 100%; }
  .brand-select, .limit-select { width: 100%; }
  .metric-select { width: 138px; }
  .brand-comparison :deep(.chart-card-header) { align-items: flex-start; flex-wrap: wrap; }
}
</style>
