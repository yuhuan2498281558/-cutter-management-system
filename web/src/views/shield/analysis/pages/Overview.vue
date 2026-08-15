<template>
  <div class="overview-page">
    <div class="analysis-export-bar">
      <el-button type="primary" plain @click="exportPdf">导出PDF</el-button>
    </div>

    <!-- KPI 卡片区 -->
    <el-row :gutter="12" class="kpi-row">
      <el-col :span="4" v-for="card in kpiCards" :key="card.label">
        <KpiCard
          :label="card.label"
          :value="kpi[card.key]"
          :format="card.format"
          :unit="card.unit"
          :sub-text="card.subText"
          :icon="card.icon"
          :color="card.color"
        />
      </el-col>
    </el-row>

    <!-- 图表区 -->
    <el-row :gutter="12">
      <!-- 月度换刀趋势 -->
      <el-col :span="12">
        <ChartCard title="月度换刀趋势（整刀 + 维修）" :loading="loading" chart-height="320px" :is-empty="!overviewData?.monthly_trend?.length">
          <div ref="monthlyChartRef" style="width:100%;height:320px" />
        </ChartCard>
      </el-col>

      <!-- 各类型累计换刀 -->
      <el-col :span="12">
        <ChartCard title="各刀具类型累计换刀次数（按环号）" :loading="loading" chart-height="320px" :is-empty="!overviewData?.type_trend?.length">
          <div ref="typeChartRef" style="width:100%;height:320px" />
        </ChartCard>
      </el-col>
    </el-row>

    <!-- 近期开仓记录 -->
    <ChartCard title="近期开仓换刀概况（最近 10 次）" :loading="loading" :is-empty="!overviewData?.recent_openings?.length">
      <el-table :data="overviewData?.recent_openings ?? []" stripe size="small" style="width:100%">
        <el-table-column prop="ring_no" label="开仓环号" width="90" align="center" />
        <el-table-column prop="open_time" label="开仓日期" width="110" align="center" />
        <el-table-column prop="replaced_count" label="换刀数" width="80" align="center" />
        <el-table-column prop="cost" label="费用（元）" width="110" align="right">
          <template #default="{ row }">
            {{ row.cost ? '¥' + row.cost.toLocaleString() : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="abnormal_count" label="异常数" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.abnormal_count > 0" type="danger" size="small">{{ row.abnormal_count }}</el-tag>
            <span v-else>0</span>
          </template>
        </el-table-column>
        <el-table-column prop="geological_conditions" label="地质情况" min-width="120" show-overflow-tooltip />
      </el-table>
    </ChartCard>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch, onMounted, onBeforeUnmount, nextTick, computed } from 'vue';
import * as echarts from 'echarts';
import KpiCard from '../components/KpiCard.vue';
import ChartCard from '../components/ChartCard.vue';
import { getOverview } from '../api';
import { TOOL_TYPE_COLORS, TOOL_TYPE_LABELS, TOOLTIP_STYLE, DEFAULT_GRID } from '../utils/chartTheme';
import type { AnalysisFilter, OverviewKpi, OverviewData } from '../types';
import type { ExportColumn } from '/@/views/shield/utils/export';
import { exportAnalysisPdf } from '../utils/pdfExport';

const props = defineProps<{ filter: AnalysisFilter }>();

// ─── 数据状态 ────────────────────────────────────────────────
const loading = ref(false);
const overviewData = ref<OverviewData | null>(null);
const kpi = reactive<OverviewKpi>({
  total_openings: 0,
  total_replacements: 0,
  total_repairs: 0,
  total_cost: 0,
  avg_rings_between_openings: 0,
  abnormal_wear_rate: 0,
  healthy_rate: 0,
});

// ─── KPI 卡片配置 ────────────────────────────────────────────
const kpiCards = [
  { label: '累计开仓次数', key: 'total_openings' as keyof OverviewKpi, format: 'number', unit: '次', icon: 'iconfont icon-kucun', color: '#1677ff' },
  { label: '累计整刀更换', key: 'total_replacements' as keyof OverviewKpi, format: 'number', unit: '次', icon: 'iconfont icon-gongju', color: '#e84749' },
  { label: '累计维修次数', key: 'total_repairs' as keyof OverviewKpi, format: 'number', unit: '次', icon: 'iconfont icon-weixiu', color: '#fa8c16' },
  { label: '累计换刀费用', key: 'total_cost' as keyof OverviewKpi, format: 'currency', icon: 'iconfont icon-feiyong', color: '#52c41a' },
  { label: '平均换刀间距', key: 'avg_rings_between_openings' as keyof OverviewKpi, format: 'decimal', unit: ' 环', icon: 'iconfont icon-juli', color: '#722ed1' },
  { label: '最近开仓完好率', key: 'healthy_rate' as keyof OverviewKpi, format: 'percent', icon: 'iconfont icon-jiankang', color: '#13c2c2' },
];

const exportColumns: ExportColumn[] = [
  { key: 'section', title: '数据项' },
  { key: 'name', title: '名称' },
  { key: 'value', title: '数值' },
  { key: 'extra', title: '补充信息' },
];

const exportRows = computed(() => {
  const rows: any[] = kpiCards.map(card => ({
    section: 'KPI',
    name: card.label,
    value: kpi[card.key],
    extra: card.unit || '',
  }));
  (overviewData.value?.monthly_trend ?? []).forEach(item => rows.push({
    section: '月度换刀趋势',
    name: item.month,
    value: `整刀更换:${item.replacements}; 维修:${item.repairs}; 费用:${item.cost}`,
    extra: '',
  }));
  (overviewData.value?.type_trend ?? []).forEach(item => rows.push({
    section: '各类型累计换刀',
    name: item.ring_no,
    value: `滚刀:${(item as any).DISC ?? 0}; 撕裂刀:${(item as any).RIPPER ?? 0}; 刮刀:${(item as any).SCRAPER ?? 0}`,
    extra: '',
  }));
  (overviewData.value?.recent_openings ?? []).forEach(item => rows.push({
    section: '近期开仓概况',
    name: item.ring_no,
    value: `换刀:${item.replaced_count}; 费用:${item.cost}; 异常:${item.abnormal_count}`,
    extra: item.geological_conditions || '',
  }));
  return rows;
});

function exportPdf() {
  exportAnalysisPdf('数据分析-概览', '.overview-page');
}

// ─── 图表实例 ────────────────────────────────────────────────
const monthlyChartRef = ref<HTMLElement | null>(null);
const typeChartRef = ref<HTMLElement | null>(null);
let monthlyChart: echarts.ECharts | null = null;
let typeChart: echarts.ECharts | null = null;

// ─── 加载数据 ────────────────────────────────────────────────
async function loadData() {
  loading.value = true;
  try {
    const res = await getOverview(props.filter);
    const data: OverviewData = res?.data ?? res;
    overviewData.value = data;
    Object.assign(kpi, data.kpi);
    await nextTick();
    renderMonthlyChart(data);
    renderTypeChart(data);
  } finally {
    loading.value = false;
  }
}

// ─── 月度趋势图（堆叠柱状 + 费用折线） ──────────────────────
function renderMonthlyChart(data: OverviewData) {
  if (!monthlyChartRef.value) return;
  if (!monthlyChart) monthlyChart = echarts.init(monthlyChartRef.value);

  const months = data.monthly_trend.map(r => r.month);
  const replacements = data.monthly_trend.map(r => r.replacements);
  const repairs = data.monthly_trend.map(r => r.repairs);
  const costs = data.monthly_trend.map(r => r.cost);

  monthlyChart.setOption({
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { data: ['整刀更换', '维修', '费用'], bottom: 0 },
    grid: DEFAULT_GRID,
    xAxis: { type: 'category', data: months },
    yAxis: [
      { type: 'value', name: '换刀次数', minInterval: 1 },
      { type: 'value', name: '费用（元）', axisLabel: { formatter: (v: number) => v >= 10000 ? (v / 10000).toFixed(1) + 'w' : v } },
    ],
    series: [
      { name: '整刀更换', type: 'bar', stack: 'total', data: replacements, color: TOOL_TYPE_COLORS.DISC, barMaxWidth: 40 },
      { name: '维修', type: 'bar', stack: 'total', data: repairs, color: '#faad14', barMaxWidth: 40 },
      { name: '费用', type: 'line', yAxisIndex: 1, data: costs, color: '#52c41a', smooth: true,
        symbol: 'circle', symbolSize: 6 },
    ],
  }, true);
}

// ─── 各类型累计换刀折线图 ─────────────────────────────────────
function renderTypeChart(data: OverviewData) {
  if (!typeChartRef.value) return;
  if (!typeChart) typeChart = echarts.init(typeChartRef.value);

  const rings = data.type_trend.map(r => r.ring_no);
  const types = props.filter.tool_parent_type
    ? [props.filter.tool_parent_type]
    : ['DISC', 'RIPPER', 'SCRAPER'];

  typeChart.setOption({
    tooltip: { ...TOOLTIP_STYLE, trigger: 'axis' },
    legend: { data: types.map(t => TOOL_TYPE_LABELS[t]), bottom: 0 },
    grid: DEFAULT_GRID,
    xAxis: { type: 'category', data: rings, name: '环号' },
    yAxis: { type: 'value', name: '累计换刀次数', minInterval: 1 },
    series: types.map(t => ({
      name: TOOL_TYPE_LABELS[t],
      type: 'line',
      data: data.type_trend.map(r => (r as any)[t] ?? 0),
      color: TOOL_TYPE_COLORS[t],
      smooth: false,
      symbol: 'circle',
      symbolSize: 5,
    })),
  }, true);
}

// ─── 响应筛选变化 ─────────────────────────────────────────────
watch(() => props.filter, loadData, { deep: true });
onMounted(loadData);

// ─── 响应窗口 resize ─────────────────────────────────────────
function onResize() {
  monthlyChart?.resize();
  typeChart?.resize();
}
window.addEventListener('resize', onResize);
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize);
  monthlyChart?.dispose();
  typeChart?.dispose();
});
</script>

<style scoped>
.overview-page {
  padding-bottom: 16px;
}
.analysis-export-bar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}
.kpi-row {
  margin-bottom: 12px;
}
</style>
