<template>
  <div class="analysis-container">
    <header class="analysis-heading">
      <h2>数据分析</h2>
      <div ref="actionsRef" class="analysis-actions" />
    </header>
    <el-tabs v-model="activeTab" class="analysis-tabs">
      <el-tab-pane label="概览" name="overview" />
      <el-tab-pane label="成本" name="cost" />
      <el-tab-pane label="磨损" name="wear" />
      <el-tab-pane label="自定义" name="custom" />
    </el-tabs>
    <FilterPanel @filter-change="onFilterChange" />

    <div class="analysis-content" role="tabpanel" :aria-labelledby="`tab-${activeTab}`">
      <Overview v-if="activeTab === 'overview'" :filter="currentFilter" :actions-target="actionsRef" />
      <CostAnalysis v-else-if="activeTab === 'cost'" :filter="currentFilter" :actions-target="actionsRef" />
      <WearAnalysis v-else-if="activeTab === 'wear'" :filter="currentFilter" :actions-target="actionsRef" />
      <CustomAnalysis v-else-if="activeTab === 'custom'" :filter="currentFilter" :actions-target="actionsRef" />
    </div>
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
// 各页面把生成时间、刷新、导出传送到这里
const actionsRef = ref<HTMLElement | null>(null);

function onFilterChange(filter: AnalysisFilter) {
  currentFilter.value = { summary_status: 'CONFIRMED', ...filter };
}
</script>

<style scoped>
.analysis-container {
  padding: var(--dv-page-gutter);
  background: var(--dv-bg);
  min-height: 100%;
  min-width: 0;
}
.analysis-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px 16px; flex-wrap: wrap; margin-bottom: 4px; }
.analysis-heading h2 { margin: 0; font-family: var(--dv-font-sans); font-size: var(--el-font-size-extra-large); font-weight: 600; line-height: 32px; color: var(--dv-text); }
.analysis-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px; min-height: 32px; }
.analysis-tabs { margin-bottom: 12px; }
.analysis-tabs :deep(.el-tabs__header) { margin: 0; }
.analysis-tabs :deep(.el-tabs__content) { display: none; }
.analysis-content { min-width: 0; }
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
  .analysis-container :deep(.analysis-metric) { padding: 12px; }
}
</style>
