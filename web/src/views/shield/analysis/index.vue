<template>
  <div class="analysis-container">
    <header class="analysis-heading">
      <h2>数据分析</h2>
      <p>从刀具消耗、厂家服役表现到费用来源，逐层核对工程数据。</p>
    </header>
    <FilterPanel @filter-change="onFilterChange" />

    <el-tabs v-model="activeTab" class="analysis-tabs">
      <el-tab-pane label="概览仪表盘" name="overview">
        <Overview v-if="activeTab === 'overview'" :filter="currentFilter" />
      </el-tab-pane>
      <el-tab-pane label="成本分析" name="cost">
        <CostAnalysis v-if="activeTab === 'cost'" :filter="currentFilter" />
      </el-tab-pane>
      <el-tab-pane label="磨损分析" name="wear">
        <WearAnalysis v-if="activeTab === 'wear'" :filter="currentFilter" />
      </el-tab-pane>
      <el-tab-pane label="自定义分析" name="custom">
        <CustomAnalysis v-if="activeTab === 'custom'" :filter="currentFilter" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import FilterPanel from './components/FilterPanel.vue';
import Overview from './pages/Overview.vue';
import CostAnalysis from './pages/CostAnalysis.vue';
import WearAnalysis from './pages/WearAnalysis.vue';
import CustomAnalysis from './pages/CustomAnalysis.vue';
import type { AnalysisFilter } from './types';

const activeTab = ref('overview');
const currentFilter = ref<AnalysisFilter>({ summary_status: 'CONFIRMED' });

function onFilterChange(filter: AnalysisFilter) {
  currentFilter.value = { summary_status: 'CONFIRMED', ...filter };
}
</script>

<style scoped>
.analysis-container {
  padding: 16px 18px;
  background: var(--el-bg-color-page);
  min-height: 100%;
  min-width: 0;
}
.analysis-heading { margin-bottom: 14px; }
.analysis-heading h2 { margin: 0; font-size: 20px; font-weight: 600; color: var(--el-text-color-primary); }
.analysis-heading p { margin: 5px 0 0; font-size: 13px; line-height: 1.6; color: var(--el-text-color-secondary); }
.analysis-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
  background: var(--el-bg-color);
  padding: 0 16px;
  border-radius: 8px 8px 0 0;
}
.analysis-tabs :deep(.el-tabs__content) {
  padding-top: 14px;
}
.analysis-container :deep(.analysis-export-bar) { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; margin-bottom: 12px; }
.analysis-container :deep(.analysis-note) { margin: 8px 0 12px; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.7; }
.analysis-container :deep(.analysis-grid) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.analysis-container :deep(.analysis-metrics) { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin-bottom: 14px; border: 1px solid var(--el-border-color-light); border-radius: 6px; overflow: hidden; background: var(--el-border-color-lighter); }
.analysis-container :deep(.analysis-metric) { padding: 14px 16px; background: var(--el-bg-color); }
.analysis-container :deep(.analysis-metric span) { display: block; font-size: 12px; color: var(--el-text-color-secondary); }
.analysis-container :deep(.analysis-metric strong) { display: block; margin-top: 7px; font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--el-text-color-primary); }
.analysis-container :deep(.analysis-metric small) { display: block; margin-top: 5px; font-size: 12px; color: var(--el-text-color-secondary); }
@media (max-width: 900px) {
  .analysis-container :deep(.analysis-grid) { grid-template-columns: 1fr; }
  .analysis-container :deep(.analysis-metrics) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 600px) {
  .analysis-container { padding: 10px; }
  .analysis-container :deep(.analysis-metric) { padding: 12px; }
  .analysis-heading p { font-size: 12px; }
}
</style>
