<template>
  <div ref="pageRef" class="cost-page">
    <div class="analysis-export-bar">
      <el-button plain :disabled="costLoading" @click="loadData">刷新费用</el-button>
      <el-button type="primary" plain :disabled="!costReady" @click="exportCompositionPdf">导出费用来源 PDF</el-button>
      <el-button type="primary" plain :disabled="!brandReady" @click="exportTrendPdf">导出厂家表现 PDF</el-button>
    </div>
    <ScopeSummary :meta="costOverview?.meta" />
    <section class="cost-composition-section">
      <div v-if="sources" class="analysis-metrics">
        <div class="analysis-metric"><span>已明确刀具费用合计</span><strong>{{ formatCurrency(sources.total) }}</strong><small>三类明确来源之和，非财务结算额</small></div>
        <div class="analysis-metric"><span>新装刀具登记金额</span><strong>{{ formatCurrency(sources.installation) }}</strong><small>装入刀具登记，可能包含维修件</small></div>
        <div class="analysis-metric"><span>已确认返修登记金额</span><strong>{{ formatCurrency(sources.confirmed_repair) }}</strong><small>按对应拆除开仓归集</small></div>
        <div class="analysis-metric"><span>历史登记金额</span><strong>{{ formatCurrency(sources.legacy) }}</strong><small>保留旧式整刀、维修与未分类来源</small></div>
      </div>
      <div v-if="sources" class="cost-quality" role="status">
        <span>缺登记价格 {{ sources.missing_price_count }} 条</span><span>返修待确认 {{ sources.pending_repair_count }} 条</span>
        <span>已确认返修缺价 {{ sources.repair_missing_price_count }} 条</span>
        <span :class="{ 'needs-review': sources.unresolved_count > 0 }">金额归属待核对 {{ sources.unresolved_count }} 条 / {{ formatCurrency(sources.unresolved) }}，未计入合计</span>
      </div>
      <p v-if="costOverview?.cost_per_ring" class="analysis-note allocation-note">
        <template v-if="costOverview.cost_per_ring.available">按开仓环号跨度摊销：<strong>{{ formatCurrency(costOverview.cost_per_ring.total) }}/环</strong>，分母 {{ costOverview.cost_per_ring.ring_count }} 环（最大开仓环号 − 最小开仓环号 + 1）。不是实际掘进单环成本。</template>
        <template v-else>按开仓环号跨度摊销：暂不计算。{{ costOverview.cost_per_ring.reason }}</template>
      </p>
      <ChartCard title="费用来源构成" description="三类明确来源可以相加；同次换刀的新装登记与旧刀返修是两项费用来源。" chart-height="160px"
        :loading="costLoading" :error="costError" :is-empty="!sourceRows.length" @retry="loadData">
        <div ref="compositionRef" class="cost-chart" style="height:160px" />
      </ChartCard>
    </section>
    <section class="analysis-grid cost-trend-section">
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
    <section class="brand-filter-bar" aria-label="厂家对比条件">
      <h3>厂家对比</h3><p>继承上方项目、盾构机、环段、刀型及地层类型条件；以下选择仅收窄厂家范围。</p>
      <el-form label-position="top" class="brand-filter-form">
        <el-form-item label="对比厂家"><el-select v-model="brandFilterForm.manufacturers" multiple clearable filterable collapse-tags collapse-tags-tooltip
          placeholder="当前范围全部厂家" :disabled="optionsLoading || !!optionsError" @change="applyBrandFilter">
          <el-option v-for="name in manufacturerOptions" :key="name" :label="name" :value="name" />
        </el-select></el-form-item>
        <el-form-item label="图形展示"><el-select v-model="brandFilterForm.limit" :disabled="!!focusedManufacturer || !!appliedBrandFilter.manufacturers.length">
          <el-option :value="5" label="按金额前 5 家" /><el-option :value="8" label="按金额前 8 家" /><el-option :value="0" label="全部厂家" />
        </el-select></el-form-item>
        <el-form-item class="brand-filter-actions"><el-button @click="resetBrandFilter">重置厂家条件</el-button></el-form-item>
      </el-form>
      <div v-if="optionsError" class="option-error" role="alert">厂家筛选项加载失败，当前统计范围未改变。<el-button link type="primary" @click="loadOptions">重新加载</el-button></div>
    </section>
    <section class="cost-brand-section">
      <ScopeSummary :meta="brandCost?.meta" />
      <ChartCard title="厂家综合对照" chart-height="auto" :loading="brandLoading" :error="brandError" :is-empty="!brandSummaryItems.length" @retry="loadBrandData"
        description="表格保留全部厂家，按明确金额排序。安装均价、旧刀磨损与服役环数各有不同样本，不能直接据此判断厂家优劣。">
        <el-table :data="brandSummaryItems" size="small" border :max-height="480" row-key="manufacturer" class="cost-table">
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
        <p class="analysis-note">厂家缺失的更换记录 {{ formatNumber(brandCost?.unknown_manufacturer_count) }} 条；厂家未核实的明确金额 {{ formatCurrency(unknownManufacturerAmount) }}（{{ unknownManufacturerRows.length }} 项金额来源）。全范围配对待核对 {{ formatNumber(brandCost?.pairing_unresolved_count) }} 条。厂家表不含未知厂家，不能将表内合计当作工程总计。</p>
      </ChartCard>
      <div v-if="brandReady" class="graph-scope" role="status"><span>{{ focusedManufacturer ? `图形聚焦：${focusedManufacturer}` : `图形显示 ${visibleBrands.length} 家；表格共 ${brandSummaryItems.length} 家` }}</span><el-button v-if="focusedManufacturer" link type="primary" @click="focusedManufacturer = ''">查看全部对比厂家</el-button></div>
      <div class="analysis-grid cost-brand-export-section">
        <section class="cost-brand-trend-section">
          <ChartCard title="安装均价与已拆刀服役环数" chart-height="350px" :loading="brandLoading" :error="brandError" :is-empty="!relationshipItems.length" @retry="loadBrandData"
            empty-description="当前厂家没有同时具备安装价格和闭合服役段的数据；已有单项数据仍保留在上表。"
            description="每点一个厂家。两个坐标来自不同样本群，只表达并列观察，不代表单把刀具的价格与服役关系。">
            <div ref="relationshipRef" class="cost-chart" style="height:350px" />
          </ChartCard>
        </section>
        <section class="cost-brand-line-section">
          <ChartCard :title="trendConfig.title" chart-height="350px" :loading="brandLoading" :error="brandError" :is-empty="!hasTrendData" @retry="loadBrandData"
            empty-description="当前图形范围没有该指标的有效样本，请查看其他指标或上表缺失说明。"
            :description="trendConfig.ratio ? '仅统计已闭合配对旧刀中有现场磨损记录的样本。100% 表示这些样本全部归入当前类别，不表示全部供货刀具失效。缺测处断开。' : '单个样本点仍显示，缺测处断开。价格按安装开仓，旧刀表现按拆除开仓归集。'">
            <template #toolbar><el-select v-model="brandMetric" size="small" class="metric-select"><el-option label="安装记录均价" value="price" /><el-option label="已拆刀服役环数" value="service" /><el-option label="非正常磨损比例" value="abnormal" /><el-option label="正常磨损比例" value="normal" /></el-select></template>
            <div ref="brandTrendRef" class="cost-chart" style="height:350px" />
          </ChartCard>
        </section>
      </div>
      <ChartCard title="厂家旧刀配对与服役段来源" chart-height="auto" :loading="brandLoading" :error="brandError" :is-empty="!serviceRows.length" @retry="loadBrandData"
        description="完整保留厂家查询返回的已拆刀及待核对样本。服役段不是失效寿命；原安装信息只在系统配对可追溯时展示。">
        <el-table :data="visibleServiceRows" size="small" border :max-height="380" class="cost-table" data-analysis-table="service" row-key="detail_id">
          <el-table-column label="拆除开仓" min-width="135" fixed><template #default="{ row }"><el-button link type="primary" @click="openOpening(row)">{{ row.ring_no }} 环 · {{ row.warehouse_id }}</el-button></template></el-table-column>
          <el-table-column prop="cutter_position_no" label="刀位" width="65" />
          <el-table-column label="原安装厂家" min-width="130"><template #default="{ row }">{{ row.manufacturer || '待核实' }}</template></el-table-column>
          <el-table-column label="换下旧刀编号" min-width="140"><template #default="{ row }">{{ row.old_tool_number || '未记录' }}</template></el-table-column>
          <el-table-column label="原安装环号" width="100" align="right"><template #default="{ row }">{{ row.installation_ring_no ?? '未配对' }}</template></el-table-column>
          <el-table-column label="服役环数" width="110" align="right"><template #default="{ row }">{{ serviceValue(row.service_rings) }}</template></el-table-column>
          <el-table-column label="现场磨损" min-width="120"><template #default="{ row }">{{ row.wear_condition || '未记录' }}</template></el-table-column>
          <el-table-column label="配对状态 / 依据" min-width="210"><template #default="{ row }">{{ row.paired ? '系统已确认配对' : row.reason || '待核对' }}</template></el-table-column>
        </el-table>
        <el-pagination v-if="serviceRows.length > 50" v-model:current-page="servicePage" v-model:page-size="servicePageSize"
          :page-sizes="[50, 100, 200]" :total="serviceRows.length" layout="total, sizes, prev, pager, next" small class="detail-pagination" />
        <p class="analysis-note">{{ serviceRows.length }} / {{ brandCost?.service_rows_total ?? serviceRows.length }} 条{{ brandCost?.service_rows_truncated ? '（服务端已截取）' : '，分页查看，PDF 导出全部返回记录' }}。</p>
      </ChartCard>
    </section>
    <section class="cost-source-section">
      <ChartCard title="工程范围费用来源明细" chart-height="auto" :loading="costLoading" :error="costError" :is-empty="!sourceRows.length" @retry="loadData"
        description="对应上方工程费用合计，不随厂家图形聚焦变化。每行一项来源，保留未纳入原因；查看开仓仅进入只读明细。">
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
        <p class="analysis-note">{{ sourceRows.length }} / {{ costOverview?.source_rows_total ?? sourceRows.length }} 条{{ costOverview?.source_rows_truncated ? '（服务端已截取）' : '，分页查看，PDF 导出全部返回记录' }}。零价保留为 ¥0，缺价不补零。</p>
      </ChartCard>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import * as echarts from 'echarts';
import ChartCard from '../components/ChartCard.vue';
import ScopeSummary from '../components/ScopeSummary.vue';
import { getFilterOptions, getCostOverview, getCostTrend, getBrandCost, getBrandPriceTrend, getBrandPerformanceTrend } from '../api';
import { TOOL_TYPE_LABELS, TOOLTIP_STYLE, DEFAULT_GRID } from '../utils/chartTheme';
import { analysisExportMeta, escapeHtml, formatCurrency, formatNumber, formatPercent, requireAnalysisV2, SOURCE_LABELS } from '../utils/presentation';
import { useAnalysisQuery } from '../utils/useAnalysisQuery';
import { exportAnalysisPdf } from '../utils/pdfExport';
import type { AnalysisFilter, AnalysisMeta, BrandCostItem, BrandPerfTrendSeries, BrandPerformanceTrendData, BrandPriceTrendData, CostOverviewData, CostSourceRow, CostTrendItem } from '../types';

interface ServiceRow {
  detail_id: number; opening_id: number; warehouse_id: string; ring_no: string; cutter_position_no: string;
  manufacturer: string; old_tool_number: string; installation_ring_no: string | null; service_rings: number | null;
  paired: boolean; reason: string; wear_condition: string;
}
interface BrandItem extends BrandCostItem { installation_count?: number; legacy_replacement_count?: number }
interface BrandData {
  meta?: AnalysisMeta; items: BrandItem[]; service_rows?: ServiceRow[]; service_rows_total?: number;
  service_rows_truncated?: boolean; pairing_unresolved_count?: number; unknown_manufacturer_count?: number;
  source_rows?: CostSourceRow[];
}
interface TrendData { meta?: AnalysisMeta; items: CostTrendItem[] }
interface OptionData { manufacturers: string[] }
function requireBrandData(data: BrandData): BrandData {
  requireAnalysisV2(data);
  const nullableNumber = (value: unknown) => value === null || (typeof value === 'number' && Number.isFinite(value));
  const sampleCount = (value: unknown) => typeof value === 'number' && Number.isInteger(value) && value >= 0;
  const valid = Array.isArray(data.items) && Array.isArray(data.service_rows) && data.items.every(item => (
    item !== null && typeof item === 'object'
    && nullableNumber(item.avg_lifespan) && nullableNumber(item.avg_cost)
    && sampleCount(item.lifespan_count) && sampleCount(item.paired_count) && sampleCount(item.priced_count)
  ));
  if (!valid) throw new Error('厂家分析服务尚未更新，缺少完整的服役与配对数据。请重启后端后重新加载。');
  return data;
}
const props = defineProps<{ filter: AnalysisFilter }>();
const router = useRouter();
const pageRef = ref<HTMLElement | null>(null);
const costMode = ref('consumption');
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
const { data: costResult, loading: costLoading, error: costError, ready: costReady, load: loadData } = useAnalysisQuery(
  () => props.filter, async filter => {
    const [overview, trend] = await Promise.all([getCostOverview(filter), getCostTrend(filter)]);
    return { overview: requireAnalysisV2<CostOverviewData>(overview.data), trend: requireAnalysisV2<TrendData>(trend.data) };
  },
);
watch(() => props.filter, () => {
  brandFilterForm.manufacturers = [];
  appliedBrandFilter.value = { manufacturers: [] }; focusedManufacturer.value = '';
}, { deep: true, flush: 'sync' });
const { data: brandResult, loading: brandLoading, error: brandError, ready: brandReady, load: loadBrandData } = useAnalysisQuery(
  buildBrandFilter, async filter => {
    const [cost, price, performance] = await Promise.all([getBrandCost(filter), getBrandPriceTrend(filter), getBrandPerformanceTrend(filter)]);
    return { cost: requireBrandData(cost.data), price: requireAnalysisV2<BrandPriceTrendData>(price.data), performance: requireAnalysisV2<BrandPerformanceTrendData>(performance.data) };
  },
);
const { data: optionData, loading: optionsLoading, error: optionsError, load: loadOptions } = useAnalysisQuery<OptionData>(
  () => props.filter, async filter => (await getFilterOptions(filter)).data,
);
const costOverview = computed(() => costResult.value?.overview);
const costTrend = computed(() => costResult.value?.trend);
const sources = computed(() => costOverview.value?.cost_sources);
const sourceRows = computed(() => costOverview.value?.source_rows ?? []);
const brandCost = computed(() => brandResult.value?.cost);
const serviceRows = computed(() => brandCost.value?.service_rows ?? []);
const servicePage = ref(1), sourcePage = ref(1);
const servicePageSize = ref(50), sourcePageSize = ref(50);
const visibleServiceRows = computed(() => serviceRows.value.slice((servicePage.value - 1) * servicePageSize.value, servicePage.value * servicePageSize.value));
const visibleSourceRows = computed(() => sourceRows.value.slice((sourcePage.value - 1) * sourcePageSize.value, sourcePage.value * sourcePageSize.value));
watch([serviceRows, servicePageSize], () => { servicePage.value = 1; }, { flush: 'sync' });
watch([sourceRows, sourcePageSize], () => { sourcePage.value = 1; }, { flush: 'sync' });
const brandSummaryItems = computed(() => brandCost.value?.items ?? []);
const unknownManufacturerRows = computed(() => (brandCost.value?.source_rows ?? []).filter(row => !row.manufacturer && row.included));
const unknownManufacturerAmount = computed(() => unknownManufacturerRows.value.reduce((total, row) => total + (row.amount ?? 0), 0));
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
  const list = brandMetric.value === 'price' ? data.price.series : brandMetric.value === 'service' ? data.performance.lifespan_series : brandMetric.value === 'normal' ? data.performance.normal_rate_series : data.performance.abnormal_rate_series;
  const visible = new Set(visibleBrands.value.map(item => item.manufacturer));
  return list.filter(item => visible.has(item.manufacturer));
});
const hasTrendData = computed(() => selectedTrend.value.some(item => item.data.some(value => value != null)));
function serviceValue(value: unknown) { return value == null ? '无闭合样本' : `${formatNumber(value, 1)} 环`; }
function focusManufacturer(name: string) { focusedManufacturer.value = focusedManufacturer.value === name ? '' : name; }
function sourceLabel(row: CostSourceRow) { return row.source === 'confirmed_repair' && !['CONFIRMED', 'CLOSED'].includes(row.inspection_status || '') ? '返修登记（待确认）' : SOURCE_LABELS[row.source] || row.source; }
function openOpening(row: { opening_id: number; warehouse_id: string }) {
  if (row.opening_id) router.push({ path: '/shield/toolChangeDetail', query: { warehouse_id: String(row.opening_id), warehouse_code: row.warehouse_id, mode: 'view' } });
}
function exportCompositionPdf() {
  if (!costReady.value) return;
  exportAnalysisPdf('数据分析-刀具费用来源', [
    { title: '费用来源与明确合计', selector: '.cost-composition-section' },
    { title: '环号变化与刀型贡献', selector: '.cost-trend-section' },
    { title: '费用来源明细', selector: '.cost-source-section' },
  ], analysisExportMeta(costOverview.value?.meta), [{
    id: 'sources', headers: ['开仓', '刀位', '金额来源', '登记金额（元）', '来源厂家', '装入 / 换下编号', '纳入情况'],
    rows: sourceRows.value.map(row => [
      `${row.ring_no} 环 · ${row.warehouse_id}`, row.cutter_position_no || '', sourceLabel(row), formatCurrency(row.amount),
      row.manufacturer || '未核实', `装入 ${row.new_tool_number || '未记录'}；换下 ${row.old_tool_number || '未记录'}`,
      row.included ? '已计入明确合计' : row.reason || '未纳入',
    ]),
  }]);
}
function exportTrendPdf() {
  if (!brandReady.value) return;
  exportAnalysisPdf('数据分析-厂家对照与服役表现', [{ title: '厂家对照、指标与配对依据', selector: '.cost-brand-section' }], [
    ...analysisExportMeta(brandCost.value?.meta),
    { label: '图形展示', value: focusedManufacturer.value || (appliedBrandFilter.value.manufacturers.length ? '选定厂家' : brandFilterForm.limit ? `按明确金额前 ${brandFilterForm.limit} 家；表格保留全部` : '全部厂家') },
    { label: '当前趋势指标', value: trendConfig.value.title },
  ], [{
    id: 'service', headers: ['拆除开仓', '刀位', '原安装厂家', '换下旧刀编号', '原安装环号', '服役环数', '现场磨损', '配对状态 / 依据'],
    rows: serviceRows.value.map(row => [
      `${row.ring_no} 环 · ${row.warehouse_id}`, row.cutter_position_no || '', row.manufacturer || '待核实',
      row.old_tool_number || '未记录', String(row.installation_ring_no ?? '未配对'), serviceValue(row.service_rings),
      row.wear_condition || '未记录', row.paired ? '系统已确认配对' : row.reason || '待核对',
    ]),
  }]);
}
const sourceConfig = [
  { key: 'installation', trend: 'installation_cost', name: '新装登记', color: '#35689b' },
  { key: 'confirmed_repair', trend: 'confirmed_repair_cost', name: '已确认返修', color: '#6f9483' },
  { key: 'legacy', trend: 'legacy_cost', name: '历史登记', color: '#b7a078' },
] as const;
const palette = ['#35689b', '#7d6aa8', '#427c70', '#ae783c', '#a45f6d', '#537f92', '#687947', '#8c6b54'];
function manufacturerColor(name: string) { let hash = 0; for (const character of name || '') hash = (hash * 31 + character.charCodeAt(0)) >>> 0; return palette[hash % palette.length]; }
const compositionRef = ref<HTMLElement | null>(null);
const costTrendRef = ref<HTMLElement | null>(null);
const typeRef = ref<HTMLElement | null>(null);
const relationshipRef = ref<HTMLElement | null>(null);
const brandTrendRef = ref<HTMLElement | null>(null);
const chartInstances = new Map<string, echarts.ECharts>();
const chartInputs = new Map<string, unknown[]>();
function updateChart(key: string, element: HTMLElement | null, option: any) {
  if (!element) return;
  const inputs = key === 'composition' ? [sources.value] : key === 'costTrend' ? [costTrend.value, costMode.value]
    : key === 'type' ? [costOverview.value?.type_breakdown] : key === 'relationship' ? [visibleBrands.value]
    : [selectedTrend.value, brandMetric.value];
  let chart = chartInstances.get(key);
  if (chart && chart.getDom() !== element) { chart.dispose(); chart = undefined; }
  const previous = chartInputs.get(key);
  if (chart && previous && inputs.every((value, index) => value === previous[index])) return;
  if (!chart) { chart = echarts.init(element); chartInstances.set(key, chart); }
  chart.setOption(option, true); chart.resize();
  chartInputs.set(key, inputs);
}
function renderCharts() {
  if (costReady.value && sources.value) {
    updateChart('composition', compositionRef.value, {
      tooltip: { ...TOOLTIP_STYLE, trigger: 'axis', valueFormatter: (value: number) => formatCurrency(value) },
      legend: { bottom: 0 }, grid: { left: 28, right: 30, top: 16, bottom: 48, containLabel: true },
      xAxis: { type: 'value', name: '元' }, yAxis: { type: 'category', data: ['明确金额'], axisTick: { show: false } },
      series: sourceConfig.map(item => ({ name: item.name, type: 'bar', stack: 'sources', barMaxWidth: 32, color: item.color, data: [sources.value![item.key]] })),
    });
    const items = costTrend.value?.items ?? [], cumulative = costMode.value === 'cumulative';
    updateChart('costTrend', costTrendRef.value, {
      tooltip: { ...TOOLTIP_STYLE, trigger: 'axis', axisPointer: { type: 'shadow' } }, legend: { bottom: 0, type: 'scroll' }, grid: { ...DEFAULT_GRID, top: 38, right: 48, bottom: 75 },
      xAxis: { type: 'category', data: items.map(item => `${item.ring_no}环`), axisLabel: { hideOverlap: true } },
      yAxis: [{ type: 'value', name: '登记金额（元）' }, { type: 'value', name: cumulative ? '累计金额（元）' : '更换数量（把）', minInterval: cumulative ? undefined : 1 }],
      dataZoom: items.length > 14 ? [{ type: 'inside' }] : [],
      series: [...sourceConfig.map(source => ({ name: source.name, type: 'bar', stack: 'cost', barMaxWidth: 28, color: source.color, data: items.map(item => item[source.trend] ?? null) })),
        { name: cumulative ? '累计明确金额' : '实际更换数量', type: 'line', yAxisIndex: 1, color: '#4b5563', smooth: false, symbol: 'circle', symbolSize: 5, data: items.map(item => cumulative ? item.cumulative_cost : item.replacement_count ?? null) }],
    });
    const types = costOverview.value?.type_breakdown ?? [];
    updateChart('type', typeRef.value, {
      tooltip: { ...TOOLTIP_STYLE, trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (value: number) => formatCurrency(value) },
      legend: { bottom: 0 }, grid: { ...DEFAULT_GRID, left: 30, right: 45 },
      xAxis: { type: 'value', name: '元' }, yAxis: { type: 'category', data: types.map(item => TOOL_TYPE_LABELS[item.tool_type] || item.tool_type) },
      series: sourceConfig.map(source => ({ name: source.name, type: 'bar', stack: 'sources', barMaxWidth: 34, color: source.color, data: types.map(item => item.cost_sources?.[source.key] ?? null) })),
    });
  }
  if (!brandReady.value || !brandResult.value) return;
  updateChart('relationship', relationshipRef.value, {
    tooltip: { ...TOOLTIP_STYLE, trigger: 'item', formatter: (parameter: any) => {
      const item = parameter.data.sample as BrandCostItem;
      return `${escapeHtml(item.manufacturer)}<br/>安装记录均价：${formatCurrency(item.avg_cost)}（${formatNumber(item.priced_count)} 个有价样本）<br/>已拆刀平均服役：${serviceValue(item.avg_lifespan)}（${formatNumber(item.lifespan_count)} 个闭合段）<br/>非正常磨损：${formatPercent(item.abnormal_rate)}（${formatNumber(item.wear_recorded_count)} 个有记录样本）`;
    } },
    grid: { ...DEFAULT_GRID, top: 35, right: 32, bottom: 55 },
    xAxis: { type: 'value', name: '安装均价（元）', nameLocation: 'middle', nameGap: 32 }, yAxis: { type: 'value', name: '服役环数（环）' },
    series: [{ type: 'scatter', symbolSize: 13, data: relationshipItems.value.map(item => ({ name: item.manufacturer, value: [item.avg_cost, item.avg_lifespan], sample: item, itemStyle: { color: manufacturerColor(item.manufacturer) } })),
      label: { show: relationshipItems.value.length <= 8, position: 'top', formatter: '{b}', fontSize: 11 }, labelLayout: { hideOverlap: true } }],
  });
  const trend = selectedTrend.value;
  const axis = brandMetric.value === 'price' ? brandResult.value.price.time_axis : brandResult.value.performance.time_axis;
  updateChart('brandTrend', brandTrendRef.value, {
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis', formatter: (parameters: any[]) => {
      if (!parameters.length) return '';
      const index = parameters[0].dataIndex, point = axis[index];
      if (!point) return '';
      return `${escapeHtml(point.ring_no)} 环 · ${escapeHtml(point.open_time)}<br/>` + parameters.map(parameter => {
        const sample = trend.find(item => item.manufacturer === parameter.seriesName), value = sample?.data[index];
        const formatted = value == null ? '无有效样本' : trendConfig.value.ratio ? formatPercent(value) : brandMetric.value === 'price' ? formatCurrency(value) : serviceValue(value);
        const recordedCount = sample?.count_data?.[index];
        if (trendConfig.value.ratio) {
          const abnormalCount = (sample as BrandPerfTrendSeries | undefined)?.abnormal_count_data?.[index];
          const categoryCount = brandMetric.value === 'normal'
            ? recordedCount != null && abnormalCount != null ? recordedCount - abnormalCount : undefined
            : abnormalCount;
          const category = brandMetric.value === 'normal' ? '正常数' : '非正常数';
          return `${escapeHtml(parameter.seriesName)}：${formatted}<br/>${category} / 有记录数：${formatNumber(categoryCount)} / ${formatNumber(recordedCount)}（已闭合配对旧刀）`;
        }
        return `${escapeHtml(parameter.seriesName)}：${formatted}（${brandMetric.value === 'price' ? '有价新装记录' : '闭合服役段'} ${formatNumber(recordedCount)}）`;
      }).join('<br/>');
    } },
    legend: { bottom: 0, type: 'scroll' }, grid: { ...DEFAULT_GRID, top: 30, right: 30, bottom: 70 },
    xAxis: { type: 'category', data: axis.map(item => `${item.ring_no}环`), axisLabel: { hideOverlap: true } },
    yAxis: { type: 'value', name: trendConfig.value.unit, min: 0, max: trendConfig.value.ratio ? 1 : undefined, axisLabel: { formatter: (value: number) => trendConfig.value.ratio ? `${Math.round(value * 100)}%` : value } },
    dataZoom: axis.length > 14 ? [{ type: 'inside' }] : [],
    series: trend.map(item => ({ name: item.manufacturer, type: 'line', data: item.data, color: manufacturerColor(item.manufacturer), connectNulls: false, smooth: false, symbol: 'circle', symbolSize: 6 })),
  });
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
watch([costReady, brandReady, costMode, brandMetric, visibleBrands, compositionRef, costTrendRef, typeRef, relationshipRef, brandTrendRef], scheduleRender, { flush: 'post' });
onDeactivated(() => { activeCharts = false; cancelChartFrames(); });
onActivated(() => { activeCharts = true; scheduleRender(); scheduleResize(); });
onBeforeUnmount(() => { activeCharts = false; cancelChartFrames(); resizeObserver?.disconnect(); chartInstances.forEach(chart => chart.dispose()); chartInstances.clear(); chartInputs.clear(); });
</script>

<style scoped>
.cost-page { min-width: 0; padding-bottom: 12px; }
.cost-chart { width: 100%; min-width: 0; }
.cost-quality { display: flex; flex-wrap: wrap; gap: 6px 20px; margin: -4px 0 12px; font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.6; }
.needs-review { color: var(--el-color-warning-dark-2); }
.allocation-note { padding: 8px 12px; border-left: 2px solid var(--el-border-color); }
.brand-filter-bar { margin: 4px 0 12px; padding: 14px 16px 2px; background: var(--el-bg-color); border: 1px solid var(--el-border-color-light); border-radius: 6px; }
.brand-filter-bar h3 { margin: 0; font-size: 15px; font-weight: 600; }
.brand-filter-bar p { margin: 5px 0 12px; font-size: 12px; color: var(--el-text-color-secondary); }
.brand-filter-form { display: grid; grid-template-columns: minmax(0, 1fr) minmax(150px, 0.8fr) max-content; align-items: end; gap: 12px 16px; margin-bottom: 12px; }
.brand-filter-form :deep(.el-form-item) { min-width: 0; margin: 0; }
.brand-filter-form :deep(.el-form-item__label) { margin-bottom: 6px; padding: 0; line-height: 20px; }
.brand-filter-form :deep(.el-form-item__content) { min-width: 0; }
.brand-filter-form :deep(.el-select) { width: 100%; }
.brand-filter-actions { align-self: end; }
.brand-filter-actions :deep(.el-form-item__content) { min-height: 32px; align-items: center; }
.option-error { padding-bottom: 12px; font-size: 12px; color: var(--el-color-danger); }
.metric-select { width: 160px; }
.cell-detail { display: block; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.5; margin-top: 3px; }
.manufacturer-button { display: inline-flex; align-items: center; gap: 7px; padding: 2px 0; border: 0; color: var(--el-color-primary); background: transparent; text-align: left; font: inherit; cursor: pointer; overflow-wrap: anywhere; }
.manufacturer-button i { width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%; }
.manufacturer-button[aria-pressed="true"] { font-weight: 600; text-decoration: underline; text-underline-offset: 4px; }
.manufacturer-button:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.graph-scope { display: flex; align-items: center; gap: 12px; font-size: 12px; margin: 2px 0 10px; color: var(--el-text-color-secondary); }
.cost-table { width: 100%; font-variant-numeric: tabular-nums; }
.cost-table :deep(.el-table__cell) { padding: 5px 0; }
.cost-table :deep(.el-button) { white-space: normal; height: auto; text-align: left; line-height: 1.5; }
.detail-pagination { margin-top: 10px; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
.cost-brand-export-section > section { min-width: 0; }
@media (max-width: 600px) {
  .brand-filter-form { grid-template-columns: minmax(0, 1fr); }
  .brand-filter-actions :deep(.el-button) { width: 100%; }
  .metric-select { width: 138px; }
  .cost-page :deep(.chart-card-header) { align-items: flex-start; flex-wrap: wrap; }
}
</style>
