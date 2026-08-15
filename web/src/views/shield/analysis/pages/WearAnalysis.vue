<template>
  <div class="wear-page">
    <div class="analysis-export-bar">
      <el-button type="primary" plain @click="exportPdf">导出PDF</el-button>
    </div>

    <el-row :gutter="12">
      <!-- 磨损等级分布饼图 -->
      <el-col :span="8">
        <ChartCard title="磨损等级分布" :loading="loading" chart-height="320px"
          :is-empty="!wearDist?.items?.length">
          <div ref="pieChartRef" style="width:100%;height:320px" />
        </ChartCard>
      </el-col>

      <!-- 磨损率时序折线图 -->
      <el-col :span="16">
        <ChartCard title="异常磨损率变化趋势（按环号）" :loading="loading" chart-height="320px"
          :is-empty="!wearTrend?.items?.length">
          <div ref="trendChartRef" style="width:100%;height:320px" />
        </ChartCard>
      </el-col>
    </el-row>

    <!-- 磨损明细表格 -->
    <ChartCard title="各次开仓磨损情况明细" :loading="loading" :is-empty="!wearTrend?.items?.length">
      <el-table :data="wearTrend?.items ?? []" stripe size="small" style="width:100%">
        <el-table-column prop="ring_no" label="环号" width="80" align="center" />
        <el-table-column prop="open_time" label="开仓日期" width="110" align="center" />
        <el-table-column prop="total" label="检查刀具数" width="100" align="center" />
        <el-table-column prop="abnormal" label="异常数" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.abnormal > 0" type="danger" size="small">{{ row.abnormal }}</el-tag>
            <span v-else>0</span>
          </template>
        </el-table-column>
        <el-table-column prop="abnormal_rate" label="异常率" width="90" align="center">
          <template #default="{ row }">
            {{ (row.abnormal_rate * 100).toFixed(1) }}%
          </template>
        </el-table-column>
        <el-table-column prop="geological_conditions" label="地质情况" min-width="120" show-overflow-tooltip />
        <el-table-column prop="stratum_types" label="地层类型" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.stratum_types">{{ row.stratum_types }}</span>
            <span v-else class="text-placeholder">—</span>
          </template>
        </el-table-column>
      </el-table>
    </ChartCard>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, nextTick, computed } from 'vue';
import * as echarts from 'echarts';
import ChartCard from '../components/ChartCard.vue';
import { getWearDistribution, getWearTrend } from '../api';
import { WEAR_LEVEL_COLORS, TOOLTIP_STYLE, DEFAULT_GRID } from '../utils/chartTheme';
import type { AnalysisFilter, WearDistributionItem, WearTrendItem } from '../types';
import type { ExportColumn } from '/@/views/shield/utils/export';
import { exportAnalysisPdf } from '../utils/pdfExport';

const props = defineProps<{ filter: AnalysisFilter }>();

const loading = ref(false);
const wearDist = ref<{ items: WearDistributionItem[]; total: number } | null>(null);
const wearTrend = ref<{ items: WearTrendItem[] } | null>(null);

const exportColumns: ExportColumn[] = [
  { key: 'section', title: '数据项' },
  { key: 'name', title: '名称' },
  { key: 'value', title: '数值' },
  { key: 'extra', title: '补充信息' },
];

const exportRows = computed(() => {
  const rows: any[] = [];
  (wearDist.value?.items ?? []).forEach(item => rows.push({
    section: '磨损等级分布',
    name: item.wear_condition,
    value: item.count,
    extra: wearDist.value?.total ? `${((item.count / wearDist.value.total) * 100).toFixed(1)}%` : '',
  }));
  (wearTrend.value?.items ?? []).forEach(item => rows.push({
    section: '各次开仓磨损情况',
    name: item.ring_no,
    value: `检查:${item.total}; 异常:${item.abnormal}; 异常率:${(item.abnormal_rate * 100).toFixed(1)}%`,
    extra: `${item.open_time || ''} ${item.geological_conditions || ''} ${item.stratum_types || ''}`.trim(),
  }));
  return rows;
});

function exportPdf() {
  exportAnalysisPdf('数据分析-磨损分析', '.wear-page');
}

const pieChartRef = ref<HTMLElement | null>(null);
const trendChartRef = ref<HTMLElement | null>(null);

let pieChart: echarts.ECharts | null = null;
let trendChart: echarts.ECharts | null = null;

async function loadData() {
  loading.value = true;
  try {
    const [r1, r2] = await Promise.all([
      getWearDistribution(props.filter),
      getWearTrend(props.filter),
    ]);
    wearDist.value = r1?.data ?? r1;
    wearTrend.value = r2?.data ?? r2;
    await nextTick();
    renderPieChart();
    renderTrendChart();
  } finally {
    loading.value = false;
  }
}

// ── 磨损等级分布饼图 ──────────────────────────────────────────
function renderPieChart() {
  if (!pieChartRef.value || !wearDist.value?.items?.length) return;
  if (!pieChart) pieChart = echarts.init(pieChartRef.value);
  const items = wearDist.value.items;
  pieChart.setOption({
    tooltip: { ...TOOLTIP_STYLE, trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, type: 'scroll' },
    series: [{
      type: 'pie',
      radius: ['35%', '60%'],
      center: ['50%', '45%'],
      data: items.map(r => ({
        name: r.wear_condition,
        value: r.count,
        itemStyle: { color: WEAR_LEVEL_COLORS[r.wear_condition] || '#999' },
      })),
      label: { formatter: '{b}\n{c}' },
    }],
  }, true);
}

// ── 异常磨损率时序折线图 ──────────────────────────────────────
function renderTrendChart() {
  if (!trendChartRef.value || !wearTrend.value?.items?.length) return;
  if (!trendChart) trendChart = echarts.init(trendChartRef.value);
  const items = wearTrend.value.items;
  trendChart.setOption({
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: 'axis',
      formatter: (params: any[]) => {
        const p = params[0];
        const item = items[p.dataIndex];
        return `环号 ${item.ring_no}<br/>异常率：${(item.abnormal_rate * 100).toFixed(1)}%<br/>异常数：${item.abnormal} / ${item.total}<br/>地质：${item.geological_conditions || '-'}`;
      },
    },
    grid: DEFAULT_GRID,
    xAxis: { type: 'category', data: items.map(r => `环${r.ring_no}`), name: '开仓环号' },
    yAxis: { type: 'value', name: '异常磨损率（%）', axisLabel: { formatter: (v: number) => (v * 100).toFixed(0) } },
    series: [{
      type: 'line',
      data: items.map(r => r.abnormal_rate),
      color: '#ff4d4f',
      smooth: false,
      symbol: 'circle',
      symbolSize: 6,
      areaStyle: { color: 'rgba(255,77,79,0.1)' },
      markLine: {
        silent: true,
        data: [{ type: 'average', name: '平均值', lineStyle: { color: '#faad14', type: 'dashed' } }],
      },
    }],
  }, true);
}

function onResize() {
  [pieChart, trendChart].forEach(c => c?.resize());
}
window.addEventListener('resize', onResize);
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize);
  [pieChart, trendChart].forEach(c => c?.dispose());
});

watch(() => props.filter, loadData, { deep: true });
onMounted(loadData);
</script>

<style scoped>
.wear-page {
  padding-bottom: 16px;
}
.analysis-export-bar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}
.text-placeholder {
  color: #ccc;
}
</style>
