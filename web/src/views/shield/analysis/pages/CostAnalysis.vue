<template>
  <div class="cost-page">
    <div class="analysis-export-bar">
      <el-button type="primary" plain @click="exportCompositionPdf">导出构成图PDF</el-button>
      <el-button type="primary" plain @click="exportTrendPdf">导出厂家表现PDF</el-button>
    </div>

    <div class="cost-filter-bar">
      <el-form :model="costFilterForm" inline class="cost-filter-form">
        <el-form-item label="成本类型">
          <el-select
            v-model="costFilterForm.cost_type"
            clearable
            placeholder="全部成本"
            style="width: 150px"
            @change="onCostTypeChange"
          >
            <el-option
              v-for="item in costTypeOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
      </el-form>
    </div>

    <div class="cost-metrics" v-if="costOverview?.cost_per_ring">
      <div class="cost-metric">
        <span>统计环数</span>
        <strong>{{ costOverview.cost_per_ring.ring_count }}</strong>
      </div>
      <div class="cost-metric">
        <span>单环总成本</span>
        <strong>{{ formatCurrency(costOverview.cost_per_ring.total) }}</strong>
      </div>
      <div class="cost-metric">
        <span>整刀单环成本</span>
        <strong>{{ formatCurrency(costOverview.cost_per_ring.complete) }}</strong>
      </div>
      <div class="cost-metric">
        <span>维修单环成本</span>
        <strong>{{ formatCurrency(costOverview.cost_per_ring.repair) }}</strong>
      </div>
    </div>

    <el-row :gutter="12" class="cost-composition-section">
      <!-- 整刀 vs 维修 环形图 -->
      <el-col :span="8">
        <ChartCard title="成本类型构成" :loading="loading" chart-height="300px"
          :is-empty="!costOverview">
          <div ref="pieChartRef" style="width:100%;height:300px" />
        </ChartCard>
      </el-col>

      <!-- 各刀具类型成本贡献 水平柱状图 -->
      <el-col :span="16">
        <ChartCard title="各刀具类型成本贡献" :loading="loading" chart-height="300px"
          :is-empty="!costOverview?.type_breakdown?.length">
          <div ref="typeBarRef" style="width:100%;height:300px" />
        </ChartCard>
      </el-col>
    </el-row>

    <el-row :gutter="12" class="cost-trend-section">
      <!-- 成本时序双轴图 -->
      <el-col :span="12">
        <ChartCard title="单次开仓费用 + 累计费用走势" :loading="loading" chart-height="320px"
          :is-empty="!costTrend?.items?.length">
          <div ref="trendChartRef" style="width:100%;height:320px" />
        </ChartCard>
      </el-col>

      <!-- 厂家累计费用排名 -->
      <el-col :span="12" class="cost-brand-rank-section">
        <ChartCard title="各厂家累计费用排名" :loading="brandLoading" chart-height="320px"
          :is-empty="!brandCost?.items?.length">
          <div ref="brandChartRef" style="width:100%;height:320px" />
        </ChartCard>
      </el-col>
    </el-row>

    <div class="brand-filter-bar">
      <div class="brand-filter-title">厂家图表筛选</div>
      <el-form :model="brandFilterForm" inline class="brand-filter-form">
        <el-form-item label="刀具细分类型">
          <el-select
            v-model="brandFilterForm.tool_type_name"
            clearable
            filterable
            placeholder="如中心滚刀"
            style="width: 180px"
            @change="onBrandScopeChange"
          >
            <el-option
              v-for="item in brandToolTypeNameOptions"
              :key="item.value"
              :label="item.parent_label ? `${item.label}（${item.parent_label}）` : item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="环号范围">
          <el-input
            v-model="brandFilterForm.start_ring"
            placeholder="起始"
            style="width: 88px"
            @change="onBrandScopeChange"
          />
          <span style="margin: 0 4px; color: #999">-</span>
          <el-input
            v-model="brandFilterForm.end_ring"
            placeholder="结束"
            style="width: 88px"
            @change="onBrandScopeChange"
          />
        </el-form-item>
        <el-form-item label="地层类型">
          <el-select
            v-model="brandFilterForm.stratum_types"
            multiple
            collapse-tags
            collapse-tags-tooltip
            clearable
            filterable
            placeholder="全部地层"
            style="width: 220px"
            @change="onBrandScopeChange"
          >
            <el-option
              v-for="item in brandStratumTypeOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="厂家">
          <el-select
            v-model="brandFilterForm.manufacturers"
            multiple
            collapse-tags
            collapse-tags-tooltip
            clearable
            filterable
            placeholder="全部厂家"
            style="width: 260px"
            @change="loadBrandData"
          >
            <el-option
              v-for="m in brandManufacturerOptions"
              :key="m"
              :label="m"
              :value="m"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="展示">
          <el-select
            v-model="brandFilterForm.limit"
            style="width: 110px"
            :disabled="isBrandLimitDisabled"
            @change="renderBrandCharts"
          >
            <el-option :value="5" label="前 5 个" />
            <el-option :value="8" label="前 8 个" />
            <el-option :value="10" label="前 10 个" />
            <el-option :value="0" label="全部" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button @click="resetBrandFilter">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div class="cost-brand-section">
    <ChartCard title="厂家综合表现" :loading="brandLoading" chart-height="360px"
      :is-empty="!brandSummaryItems.length">
      <el-table
        :data="brandSummaryItems"
        height="360"
        size="small"
        border
      >
        <el-table-column prop="manufacturer" label="厂家" min-width="130" show-overflow-tooltip fixed />
        <el-table-column prop="total_cost" label="总成本" min-width="110" sortable align="right">
          <template #default="{ row }">{{ formatCurrency(row.total_cost) }}</template>
        </el-table-column>
        <el-table-column prop="cost_per_ring" label="单环成本" min-width="110" sortable align="right">
          <template #default="{ row }">{{ formatCurrency(row.cost_per_ring || 0) }}</template>
        </el-table-column>
        <el-table-column prop="avg_cost" label="平均单价" min-width="110" sortable align="right">
          <template #default="{ row }">{{ formatCurrency(row.avg_cost) }}</template>
        </el-table-column>
        <el-table-column prop="count" label="更换数" width="90" sortable align="right" />
        <el-table-column prop="opening_count" label="开仓数" width="90" sortable align="right" />
        <el-table-column prop="abnormal_rate" label="异常率" width="100" sortable align="right">
          <template #default="{ row }">{{ formatPercent(row.abnormal_rate || 0) }}</template>
        </el-table-column>
        <el-table-column prop="normal_rate" label="正常率" width="100" sortable align="right">
          <template #default="{ row }">{{ formatPercent(row.normal_rate || 0) }}</template>
        </el-table-column>
        <el-table-column prop="avg_lifespan" label="平均寿命" width="110" sortable align="right">
          <template #default="{ row }">{{ row.avg_lifespan ? `${row.avg_lifespan} 环` : '-' }}</template>
        </el-table-column>
      </el-table>
    </ChartCard>

    <div class="cost-brand-export-section">
      <!-- 厂家平均单价时序趋势（全宽） -->
      <div class="cost-brand-trend-section">
      <el-row>
        <el-col :span="24">
          <ChartCard title="各厂家平均单价随时间变化趋势" :loading="brandLoading" chart-height="360px"
            :is-empty="!brandPriceTrend?.series?.length">
            <div ref="priceTrendRef" style="width:100%;height:360px" />
          </ChartCard>
        </el-col>
      </el-row>
      </div>

      <!-- 厂家性能趋势：异常率 + 正常磨损率 + 使用寿命 -->
      <div class="cost-brand-line-section">
      <el-row :gutter="12">
        <el-col :span="8">
          <ChartCard title="各厂家异常磨损率趋势（越低越好）" :loading="brandLoading" chart-height="320px"
            :is-empty="!brandPerfTrend?.abnormal_rate_series?.length">
            <div ref="perfAbnormalRef" style="width:100%;height:320px" />
          </ChartCard>
        </el-col>
        <el-col :span="8">
          <ChartCard title="各厂家正常磨损率趋势（越高越好）" :loading="brandLoading" chart-height="320px"
            :is-empty="!brandPerfTrend?.normal_rate_series?.length">
            <div ref="perfNormalRef" style="width:100%;height:320px" />
          </ChartCard>
        </el-col>
        <el-col :span="8">
          <ChartCard title="各厂家刀具平均使用寿命趋势（环数）" :loading="brandLoading" chart-height="320px"
            :is-empty="!brandPerfTrend?.lifespan_series?.length">
            <div ref="perfLifespanRef" style="width:100%;height:320px" />
          </ChartCard>
        </el-col>
      </el-row>
      </div>
    </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue';
import * as echarts from 'echarts';
import ChartCard from '../components/ChartCard.vue';
import { getFilterOptions, getCostOverview, getCostTrend, getBrandCost, getBrandPriceTrend, getBrandPerformanceTrend } from '../api';
import { TOOL_TYPE_COLORS, TOOL_TYPE_LABELS, TOOLTIP_STYLE, DEFAULT_GRID } from '../utils/chartTheme';
import type { AnalysisFilter, CostOverviewData, CostTrendItem, BrandCostItem, BrandPriceTrendData, BrandPerformanceTrendData } from '../types';
import type { ExportColumn } from '/@/views/shield/utils/export';
import { exportAnalysisPdf } from '../utils/pdfExport';

const props = defineProps<{ filter: AnalysisFilter }>();

const loading = ref(false);
const brandLoading = ref(false);
const costOverview = ref<CostOverviewData | null>(null);
const costTrend = ref<{ items: CostTrendItem[] } | null>(null);
const brandCost = ref<{ items: BrandCostItem[] } | null>(null);
const brandPriceTrend = ref<BrandPriceTrendData | null>(null);
const brandPerfTrend = ref<BrandPerformanceTrendData | null>(null);

const exportColumns: ExportColumn[] = [
  { key: 'section', title: '数据项' },
  { key: 'name', title: '名称' },
  { key: 'value', title: '数值' },
  { key: 'extra', title: '补充信息' },
];

const brandSummaryItems = computed(() => {
  const visible = new Set(getVisibleManufacturers());
  return (brandCost.value?.items ?? []).filter(item => visible.has(item.manufacturer));
});

const exportRows = computed(() => {
  const rows: any[] = [];
  const overview = costOverview.value;
  if (overview?.cost_per_ring) {
    rows.push(
      { section: '单环成本', name: '统计环数', value: overview.cost_per_ring.ring_count, extra: '' },
      { section: '单环成本', name: '单环总成本', value: overview.cost_per_ring.total, extra: '' },
      { section: '单环成本', name: '整刀单环成本', value: overview.cost_per_ring.complete, extra: '' },
      { section: '单环成本', name: '维修单环成本', value: overview.cost_per_ring.repair, extra: '' },
    );
  }
  overview?.type_breakdown?.forEach(item => rows.push({
    section: '各刀具类型成本贡献',
    name: TOOL_TYPE_LABELS[item.tool_type] || item.tool_type,
    value: `整刀:${item.complete_cost}; 维修:${item.repair_cost}`,
    extra: `总成本:${item.total_cost}`,
  }));
  costTrend.value?.items?.forEach(item => rows.push({
    section: '成本时序',
    name: item.ring_no,
    value: `整刀:${item.complete_cost}; 维修:${item.repair_cost}; 累计:${item.cumulative_cost}`,
    extra: item.open_time || '',
  }));
  brandSummaryItems.value.forEach(item => rows.push({
    section: '厂家综合表现',
    name: item.manufacturer,
    value: `总成本:${item.total_cost}; 单环成本:${item.cost_per_ring || 0}; 平均单价:${item.avg_cost}`,
    extra: `更换:${item.count}; 开仓:${item.opening_count}; 异常率:${formatPercent(item.abnormal_rate || 0)}; 平均寿命:${item.avg_lifespan || ''}`,
  }));
  return rows;
});

function exportCompositionPdf() {
  exportAnalysisPdf('数据分析-成本构成', [
    { title: '成本构成与类型贡献', selector: '.cost-composition-section' },
    { title: '开仓费用趋势与厂家累计费用排名', selector: '.cost-trend-section' },
  ], buildExportFilterMeta());
}

function exportTrendPdf() {
  exportAnalysisPdf('数据分析-厂家表现趋势', [
    { title: '各厂家平均单价随时间变化趋势', selector: '.cost-brand-trend-section' },
    { title: '厂家性能趋势', selector: '.cost-brand-line-section' },
  ], buildExportFilterMeta());
}

function formatCurrency(value: number) {
  return `¥${Number(value || 0).toLocaleString()}`;
}

function formatPercent(value: number) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

interface ToolTypeNameOption {
  value: string;
  label: string;
  parent_type?: string;
  parent_label?: string;
}

interface StratumTypeOption {
  value: string;
  label: string;
}

const brandToolTypeNameOptions = ref<ToolTypeNameOption[]>([]);
const brandStratumTypeOptions = ref<StratumTypeOption[]>([]);
const brandManufacturerOptions = ref<string[]>([]);
const costTypeOptions = [
  { value: 'COMPLETE', label: '整刀更换成本' },
  { value: 'REPAIR', label: '维修成本' },
];
const costFilterForm = reactive({
  cost_type: '',
});
const brandFilterForm = reactive({
  tool_type_name: '',
  start_ring: '',
  end_ring: '',
  stratum_types: [] as string[],
  manufacturers: [] as string[],
  limit: 8,
});

const isBrandLimitDisabled = computed(() => Boolean(
  brandFilterForm.manufacturers.length,
));

function findLabel(options: { value: any; label: string }[], value: any) {
  return options.find(item => item.value === value)?.label || value || '全部';
}

function labelsFromOptions(options: { value: any; label: string }[], values: any[]) {
  if (!values?.length) return '全部';
  return values.map(value => findLabel(options, value)).join('、');
}

function getLimitLabel() {
  if (brandFilterForm.manufacturers.length) return '已按厂家筛选';
  if (!brandFilterForm.limit) return '全部';
  return `前 ${brandFilterForm.limit} 个`;
}

function buildExportFilterMeta() {
  const baseFilter = normalizeFilter(props.filter);
  return [
    { label: '项目', value: String(baseFilter.project || '全部') },
    { label: '盾构机', value: String(baseFilter.shield_machine || '全部') },
    { label: '全局环号范围', value: `${baseFilter.start_ring || '全部'} - ${baseFilter.end_ring || '全部'}` },
    { label: '刀具父类型', value: String(baseFilter.tool_parent_type || '全部') },
    { label: '刀具细分类型', value: String(baseFilter.tool_type_name || baseFilter.tool_type_names || '全部') },
    { label: '全局厂家', value: String(baseFilter.manufacturer || baseFilter.manufacturers || '全部') },
    { label: '成本类型', value: String(findLabel(costTypeOptions, costFilterForm.cost_type)) },
    { label: '厂家图表刀具类型', value: String(findLabel(brandToolTypeNameOptions.value, brandFilterForm.tool_type_name)) },
    { label: '厂家图表环号范围', value: `${brandFilterForm.start_ring || '全部'} - ${brandFilterForm.end_ring || '全部'}` },
    { label: '厂家图表地层类型', value: labelsFromOptions(brandStratumTypeOptions.value, brandFilterForm.stratum_types) },
    { label: '厂家图表厂家', value: brandFilterForm.manufacturers.length ? brandFilterForm.manufacturers.join('、') : '全部' },
    { label: '厂家图表展示数量', value: getLimitLabel() },
  ];
}

const pieChartRef = ref<HTMLElement | null>(null);
const typeBarRef = ref<HTMLElement | null>(null);
const trendChartRef = ref<HTMLElement | null>(null);
const brandChartRef = ref<HTMLElement | null>(null);
const priceTrendRef = ref<HTMLElement | null>(null);
const perfAbnormalRef = ref<HTMLElement | null>(null);
const perfNormalRef = ref<HTMLElement | null>(null);
const perfLifespanRef = ref<HTMLElement | null>(null);

let pieChart: echarts.ECharts | null = null;
let typeBarChart: echarts.ECharts | null = null;
let trendChart: echarts.ECharts | null = null;
let brandChart: echarts.ECharts | null = null;
let priceTrendChart: echarts.ECharts | null = null;
let perfAbnormalChart: echarts.ECharts | null = null;
let perfNormalChart: echarts.ECharts | null = null;
let perfLifespanChart: echarts.ECharts | null = null;

function ensureChart(instance: echarts.ECharts | null, el: HTMLElement) {
  if (instance && instance.getDom() !== el) {
    instance.dispose();
    instance = null;
  }
  return instance || echarts.init(el);
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

function buildCostFilter(): AnalysisFilter {
  const filter = normalizeFilter(props.filter);
  if (costFilterForm.cost_type) {
    filter.cost_type = costFilterForm.cost_type;
  } else {
    delete filter.cost_type;
    delete filter.cost_types;
  }
  return filter;
}

function buildBrandOptionFilter(): AnalysisFilter {
  const filter = buildCostFilter();
  delete filter.manufacturer;
  delete filter.manufacturers;
  delete filter.tool_type_name;
  delete filter.tool_type_names;
  if (brandFilterForm.start_ring) {
    filter.start_ring = brandFilterForm.start_ring;
  }
  if (brandFilterForm.end_ring) {
    filter.end_ring = brandFilterForm.end_ring;
  }
  if (brandFilterForm.stratum_types.length) {
    filter.stratum_types = brandFilterForm.stratum_types.join(',');
  }
  return filter;
}

function buildBrandFilter(): AnalysisFilter {
  const filter = buildCostFilter();
  delete filter.manufacturer;
  delete filter.manufacturers;
  if (brandFilterForm.start_ring) {
    filter.start_ring = brandFilterForm.start_ring;
  }
  if (brandFilterForm.end_ring) {
    filter.end_ring = brandFilterForm.end_ring;
  }
  if (brandFilterForm.stratum_types.length) {
    filter.stratum_types = brandFilterForm.stratum_types.join(',');
  }
  if (brandFilterForm.tool_type_name) {
    delete filter.tool_type_names;
    filter.tool_type_name = brandFilterForm.tool_type_name;
  }
  if (brandFilterForm.manufacturers.length) {
    filter.manufacturers = brandFilterForm.manufacturers.join(',');
  }
  return filter;
}

async function fetchBrandOptions() {
  const optionFilter = buildBrandOptionFilter();
  const res = await getFilterOptions(optionFilter);
  const data = res?.data ?? res;
  brandToolTypeNameOptions.value = data?.tool_type_names ?? [];
  brandStratumTypeOptions.value = data?.stratum_types ?? [];

  if (!brandFilterForm.tool_type_name) {
    brandManufacturerOptions.value = data?.manufacturers ?? [];
    return;
  }

  const manufacturerRes = await getFilterOptions({
    ...optionFilter,
    tool_type_name: brandFilterForm.tool_type_name,
  });
  const manufacturerData = manufacturerRes?.data ?? manufacturerRes;
  brandManufacturerOptions.value = manufacturerData?.manufacturers ?? [];
}

function getVisibleManufacturers(fallback: string[] = []) {
  const ranking = brandCost.value?.items?.map(item => item.manufacturer) ?? fallback;
  if (!ranking.length) return fallback;
  if (brandFilterForm.manufacturers.length) {
    return ranking;
  }
  return brandFilterForm.limit > 0 ? ranking.slice(0, brandFilterForm.limit) : ranking;
}

function hasEnoughTrendPoints(series: { data: (number | null)[] }) {
  return series.data.filter(value => value !== null && value !== undefined).length >= 2;
}

function getVisibleTrendManufacturers(
  seriesData: { manufacturer: string; data: (number | null)[] }[],
  fallback: string[] = [],
) {
  const base = getVisibleManufacturers(fallback);
  if (brandFilterForm.manufacturers.length) {
    return base;
  }
  const enoughData = new Set(
    seriesData
      .filter(hasEnoughTrendPoints)
      .map(series => series.manufacturer),
  );
  return base.filter(manufacturer => enoughData.has(manufacturer));
}

function renderBrandCharts() {
  nextTick(() => {
    renderBrandChart();
    renderPriceTrendChart();
    renderPerfAbnormalChart();
    renderPerfNormalChart();
    renderPerfLifespanChart();
  });
}

async function onBrandScopeChange() {
  brandFilterForm.manufacturers = [];
  await fetchBrandOptions();
  await loadBrandData();
}

async function onCostTypeChange() {
  brandFilterForm.manufacturers = [];
  await fetchBrandOptions();
  await loadData();
}

async function resetBrandFilter() {
  brandFilterForm.tool_type_name = '';
  brandFilterForm.start_ring = '';
  brandFilterForm.end_ring = '';
  brandFilterForm.stratum_types = [];
  brandFilterForm.manufacturers = [];
  brandFilterForm.limit = 8;
  await fetchBrandOptions();
  await loadBrandData();
}

async function loadData() {
  loading.value = true;
  brandLoading.value = true;
  try {
    const costFilter = buildCostFilter();
    const brandFilter = buildBrandFilter();
    const [r1, r2, r3, r4, r5] = await Promise.all([
      getCostOverview(costFilter),
      getCostTrend(costFilter),
      getBrandCost(brandFilter),
      getBrandPriceTrend(brandFilter),
      getBrandPerformanceTrend(brandFilter),
    ]);
    costOverview.value = r1?.data ?? r1;
    costTrend.value = r2?.data ?? r2;
    brandCost.value = r3?.data ?? r3;
    brandPriceTrend.value = r4?.data ?? r4;
    brandPerfTrend.value = r5?.data ?? r5;
    await nextTick();
    renderPieChart();
    renderTypeBarChart();
    renderTrendChart();
    renderBrandChart();
    renderPriceTrendChart();
    renderPerfAbnormalChart();
    renderPerfNormalChart();
    renderPerfLifespanChart();
  } finally {
    loading.value = false;
    brandLoading.value = false;
  }
}

async function loadBrandData() {
  brandLoading.value = true;
  try {
    const brandFilter = buildBrandFilter();
    const [r1, r2, r3] = await Promise.all([
      getBrandCost(brandFilter),
      getBrandPriceTrend(brandFilter),
      getBrandPerformanceTrend(brandFilter),
    ]);
    brandCost.value = r1?.data ?? r1;
    brandPriceTrend.value = r2?.data ?? r2;
    brandPerfTrend.value = r3?.data ?? r3;
    renderBrandCharts();
  } finally {
    brandLoading.value = false;
  }
}

// ── 整刀 vs 维修 环形图 ──────────────────────────────────────
function renderPieChart() {
  if (!pieChartRef.value || !costOverview.value) return;
  pieChart = ensureChart(pieChart, pieChartRef.value);
  const { complete, repair } = costOverview.value.replacement_vs_repair;
  pieChart.setOption({
    tooltip: { ...TOOLTIP_STYLE, trigger: 'item', formatter: '{b}: ¥{c} ({d}%)' },
    legend: { bottom: 0 },
    series: [{
      type: 'pie',
      radius: ['40%', '65%'],
      center: ['50%', '45%'],
      data: [
        { name: '整刀更换', value: complete, itemStyle: { color: TOOL_TYPE_COLORS.DISC } },
        { name: '维修', value: repair, itemStyle: { color: '#faad14' } },
      ],
      label: { formatter: '{b}\n¥{c}' },
    }],
  }, true);
}

// ── 各刀具类型成本水平柱状图 ──────────────────────────────────
function renderTypeBarChart() {
  if (!typeBarRef.value || !costOverview.value) return;
  typeBarChart = ensureChart(typeBarChart, typeBarRef.value);
  const data = costOverview.value.type_breakdown;
  const types = data.map(r => TOOL_TYPE_LABELS[r.tool_type] || r.tool_type);
  typeBarChart.setOption({
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['整刀更换', '维修'], bottom: 0 },
    grid: { ...DEFAULT_GRID, left: 80 },
    xAxis: { type: 'value', name: '费用（元）' },
    yAxis: { type: 'category', data: types },
    series: [
      { name: '整刀更换', type: 'bar', stack: 'total',
        data: data.map(r => r.complete_cost), color: TOOL_TYPE_COLORS.DISC, barMaxWidth: 30 },
      { name: '维修', type: 'bar', stack: 'total',
        data: data.map(r => r.repair_cost), color: '#faad14', barMaxWidth: 30 },
    ],
  }, true);
}

// ── 成本时序双轴图 ────────────────────────────────────────────
function renderTrendChart() {
  if (!trendChartRef.value || !costTrend.value?.items?.length) return;
  trendChart = ensureChart(trendChart, trendChartRef.value);
  const items = costTrend.value.items;
  trendChart.setOption({
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { data: ['整刀费用', '维修费用', '累计费用'], bottom: 0 },
    grid: DEFAULT_GRID,
    xAxis: { type: 'category', data: items.map(r => `环${r.ring_no}`), name: '开仓环号' },
    yAxis: [
      { type: 'value', name: '单次费用（元）' },
      { type: 'value', name: '累计费用（元）',
        axisLabel: { formatter: (v: number) => v >= 10000 ? (v / 10000).toFixed(1) + 'w' : v } },
    ],
    series: [
      { name: '整刀费用', type: 'bar', stack: 'single',
        data: items.map(r => r.complete_cost), color: TOOL_TYPE_COLORS.DISC, barMaxWidth: 40 },
      { name: '维修费用', type: 'bar', stack: 'single',
        data: items.map(r => r.repair_cost), color: '#faad14', barMaxWidth: 40 },
      { name: '累计费用', type: 'line', yAxisIndex: 1,
        data: items.map(r => r.cumulative_cost), color: '#52c41a', smooth: true,
        symbol: 'circle', symbolSize: 6 },
    ],
  }, true);
}

// ── 厂家累计费用排名 ──────────────────────────────────────────
function renderBrandChart() {
  if (!brandChartRef.value || !brandCost.value?.items?.length) return;
  brandChart = ensureChart(brandChart, brandChartRef.value);
  const visible = new Set(getVisibleManufacturers());
  const items = brandCost.value.items.filter(item => visible.has(item.manufacturer)).reverse();
  brandChart.setOption({
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any[]) => {
        const p = params[0];
        const item = brandCost.value!.items.find(r => r.manufacturer === p.name);
        if (!item) return '';
        return `${p.name}<br/>累计费用：¥${item.total_cost.toLocaleString()}<br/>使用次数：${item.count}<br/>平均费用：¥${item.avg_cost.toLocaleString()}`;
      },
    },
    grid: { ...DEFAULT_GRID, left: 100 },
    xAxis: { type: 'value', name: '费用（元）' },
    yAxis: { type: 'category', data: items.map(r => r.manufacturer) },
    series: [{
      type: 'bar',
      data: items.map(r => r.total_cost),
      color: '#1677ff',
      barMaxWidth: 30,
      label: { show: true, position: 'right', formatter: (p: any) => `¥${p.value.toLocaleString()}` },
    }],
  }, true);
}

// ── 厂家平均单价时序折线图 ────────────────────────────────────
const LINE_COLORS = [
  '#1677ff', '#52c41a', '#faad14', '#ff4d4f', '#722ed1', '#13c2c2',
  '#eb2f96', '#2f54eb', '#a0d911', '#fa8c16', '#531dab', '#08979c',
  '#c41d7f', '#389e0d', '#d48806', '#cf1322', '#1d39c4', '#7cb305',
];

function getGeneratedLineColor(index: number) {
  if (index < LINE_COLORS.length) {
    return LINE_COLORS[index];
  }
  const hue = Math.round((index * 137.508) % 360);
  return `hsl(${hue}, 70%, 42%)`;
}

function getManufacturerColor(manufacturer: string, scope: string[] = []) {
  const source = scope.length ? scope : brandCost.value?.items?.map(item => item.manufacturer) ?? [];
  const manufacturers = Array.from(new Set(source)).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
  const index = manufacturers.indexOf(manufacturer);
  if (index >= 0) {
    return getGeneratedLineColor(index);
  }
  return getGeneratedLineColor(manufacturers.length);
}

function renderPriceTrendChart() {
  const d = brandPriceTrend.value;
  if (!priceTrendRef.value || !d?.series?.length) return;
  priceTrendChart = ensureChart(priceTrendChart, priceTrendRef.value);

  const xLabels = d.time_axis.map(t => `${t.open_time}\n环${t.ring_no}`);
  const manufacturers = getVisibleTrendManufacturers(d.series, d.manufacturers);
  const visible = new Set(manufacturers);
  const series = d.series.filter(s => visible.has(s.manufacturer));

  priceTrendChart.setOption({
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: 'axis',
      formatter: (params: any[]) => {
        const idx = params[0].dataIndex;
        const t = d.time_axis[idx];
        let html = `${t.open_time}（环${t.ring_no}）<br/>`;
        params.forEach(p => {
          if (p.value !== null && p.value !== undefined) {
            html += `${p.marker}${p.seriesName}：¥${Number(p.value).toLocaleString()}<br/>`;
          }
        });
        return html;
      },
    },
    legend: { data: manufacturers, bottom: 0, type: 'scroll' },
    grid: { ...DEFAULT_GRID, bottom: 60 },
    xAxis: {
      type: 'category',
      data: xLabels,
      name: '开仓时间',
      axisLabel: { fontSize: 11, lineHeight: 16 },
    },
    yAxis: { type: 'value', name: '平均单价（元）' },
    series: series.map(s => ({
      name: s.manufacturer,
      type: 'line',
      data: s.data,
      color: getManufacturerColor(s.manufacturer, d.manufacturers),
      connectNulls: true,
      symbol: 'circle',
      symbolSize: 6,
      smooth: false,
    })),
  }, true);
}

// ── 厂家性能趋势公共渲染 ──────────────────────────────────────
function renderPerfChart(
  el: HTMLElement | null,
  instance: echarts.ECharts | null,
  seriesData: { manufacturer: string; data: (number | null)[] }[],
  timeAxis: { ring_no: string; open_time: string }[],
  manufacturers: string[],
  title: string,
): echarts.ECharts | null {
  if (!el || !seriesData?.length) return instance;
  instance = ensureChart(instance, el);
  const xLabels = timeAxis.map(t => `${t.open_time}\n环${t.ring_no}`);
  const visibleManufacturers = getVisibleTrendManufacturers(seriesData, manufacturers);
  const visible = new Set(visibleManufacturers);
  const visibleSeries = seriesData.filter(s => visible.has(s.manufacturer));
  instance.setOption({
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: 'axis',
      formatter: (params: any[]) => {
        const idx = params[0].dataIndex;
        const t = timeAxis[idx];
        let html = `${t.open_time}（环${t.ring_no}）<br/>`;
        params.forEach(p => {
          if (p.value !== null && p.value !== undefined) {
            html += `${p.marker}${p.seriesName}：${(Number(p.value) * 100).toFixed(1)}%<br/>`;
          }
        });
        return html;
      },
    },
    legend: { data: visibleManufacturers, bottom: 0, type: 'scroll' },
    grid: { ...DEFAULT_GRID, bottom: 60 },
    xAxis: {
      type: 'category',
      data: xLabels,
      name: '开仓时间',
      axisLabel: { fontSize: 11, lineHeight: 16 },
    },
    yAxis: {
      type: 'value',
      name: title,
      axisLabel: { formatter: (v: number) => (v * 100).toFixed(0) + '%' },
      max: 1,
      min: 0,
    },
    series: visibleSeries.map(s => ({
      name: s.manufacturer,
      type: 'line',
      data: s.data,
      color: getManufacturerColor(s.manufacturer, manufacturers),
      connectNulls: true,
      symbol: 'circle',
      symbolSize: 6,
      smooth: false,
    })),
  }, true);
  return instance;
}

function renderPerfAbnormalChart() {
  const d = brandPerfTrend.value;
  if (!d) return;
  perfAbnormalChart = renderPerfChart(
    perfAbnormalRef.value, perfAbnormalChart,
    d.abnormal_rate_series, d.time_axis, d.manufacturers, '异常率（%）'
  );
}

function renderPerfNormalChart() {
  const d = brandPerfTrend.value;
  if (!d) return;
  perfNormalChart = renderPerfChart(
    perfNormalRef.value, perfNormalChart,
    d.normal_rate_series, d.time_axis, d.manufacturers, '正常磨损率（%）'
  );
}

function renderPerfLifespanChart() {
  const d = brandPerfTrend.value;
  if (!d?.lifespan_series?.length || !perfLifespanRef.value) return;
  perfLifespanChart = ensureChart(perfLifespanChart, perfLifespanRef.value);
  const xLabels = d.time_axis.map(t => `${t.open_time}\n环${t.ring_no}`);
  const manufacturers = getVisibleTrendManufacturers(d.lifespan_series, d.manufacturers);
  const visible = new Set(manufacturers);
  const series = d.lifespan_series.filter(s => visible.has(s.manufacturer));
  perfLifespanChart.setOption({
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: 'axis',
      formatter: (params: any[]) => {
        const idx = params[0].dataIndex;
        const t = d.time_axis[idx];
        let html = `${t.open_time}（环${t.ring_no}）<br/>`;
        params.forEach(p => {
          if (p.value !== null && p.value !== undefined) {
            html += `${p.marker}${p.seriesName}：${p.value} 环<br/>`;
          }
        });
        return html;
      },
    },
    legend: { data: manufacturers, bottom: 0, type: 'scroll' },
    grid: { ...DEFAULT_GRID, bottom: 60 },
    xAxis: {
      type: 'category',
      data: xLabels,
      name: '开仓时间',
      axisLabel: { fontSize: 11, lineHeight: 16 },
    },
    yAxis: { type: 'value', name: '平均寿命（环）' },
    series: series.map(s => ({
      name: s.manufacturer,
      type: 'line',
      data: s.data,
      color: getManufacturerColor(s.manufacturer, d.manufacturers),
      connectNulls: true,
      symbol: 'circle',
      symbolSize: 6,
      smooth: false,
    })),
  }, true);
}

function onResize() {
  [pieChart, typeBarChart, trendChart, brandChart, priceTrendChart, perfAbnormalChart, perfNormalChart, perfLifespanChart].forEach(c => c?.resize());
}
window.addEventListener('resize', onResize);
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize);
  [pieChart, typeBarChart, trendChart, brandChart, priceTrendChart, perfAbnormalChart, perfNormalChart, perfLifespanChart].forEach(c => c?.dispose());
});

async function reloadByGlobalFilter() {
  brandFilterForm.manufacturers = [];
  await fetchBrandOptions();
  await loadData();
}

watch(() => props.filter, reloadByGlobalFilter, { deep: true });
onMounted(async () => {
  await fetchBrandOptions();
  await loadData();
});
</script>

<style scoped>
.cost-page {
  padding-bottom: 16px;
}
.analysis-export-bar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}
.cost-filter-bar {
  display: flex;
  align-items: center;
  padding: 10px 12px 0;
}
.cost-filter-form :deep(.el-form-item) {
  margin-bottom: 10px;
}
.cost-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.cost-metric {
  padding: 12px 14px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}
.cost-metric span {
  display: block;
  margin-bottom: 6px;
  color: #667085;
  font-size: 13px;
}
.cost-metric strong {
  color: #1f2f3d;
  font-size: 20px;
  font-weight: 600;
}
.brand-filter-bar {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 12px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
}
.brand-filter-title {
  flex: 0 0 auto;
  height: 32px;
  line-height: 32px;
  font-size: 14px;
  font-weight: 600;
  color: #1a1a1a;
}
.brand-filter-form {
  flex: 1;
}
.brand-filter-form :deep(.el-form-item) {
  margin-bottom: 0;
}
</style>
