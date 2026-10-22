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
/* 数据分析里所有卡片的外观只在这里定义一次（图表卡片、结论卡片都带 analysis-card） */
.analysis-container :deep(.analysis-card) {
  background: var(--dv-card-bg, var(--el-bg-color));
  border: 1px solid var(--dv-card-border, var(--el-border-color));
  border-radius: var(--dv-radius-card, var(--dv-radius-lg));
  box-shadow: var(--dv-shadow-card, none);
}
/* 各页结论区：左边主结论，右边次要数字和"需要核对" */
.analysis-container :deep(.analysis-hero) { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr); gap: 12px; margin-bottom: 12px; }
.analysis-container :deep(.hero-side) { display: grid; grid-template-rows: auto 1fr; gap: 12px; min-width: 0; }
.analysis-container :deep(.hero-card) { display: grid; gap: 12px; align-content: start; min-width: 0; padding: 16px 18px; }
.analysis-container :deep(.hero-label) { display: flex; align-items: center; gap: 6px; font-size: var(--el-font-size-small); color: var(--dv-text-secondary); }
.analysis-container :deep(.hero-value) { font-size: 34px; font-weight: 600; line-height: 1.1; color: var(--dv-text); font-variant-numeric: tabular-nums; }
.analysis-container :deep(.hero-stat) { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 14px; padding-bottom: 14px; }
.analysis-container :deep(.hero-stat-value) { font-size: var(--el-font-size-extra-large); font-weight: 600; color: var(--dv-text); font-variant-numeric: tabular-nums; white-space: nowrap; }
.analysis-container :deep(.hero-card-title) { margin: 0; font-size: var(--el-font-size-small); font-weight: 600; color: var(--dv-text); }
.analysis-container :deep(.hero-sub) { display: flex; align-items: center; gap: 6px; font-size: var(--el-font-size-small); color: var(--dv-text-secondary); font-variant-numeric: tabular-nums; }
.analysis-container :deep(.hero-stat-main) { display: grid; justify-items: end; gap: 2px; }
.analysis-container :deep(.hero-stat-sub) { font-size: var(--el-font-size-extra-small); color: var(--dv-text-secondary); }
/* 两张以上明细表合成的卡片：页签当卡片标题 */
.analysis-container :deep(.analysis-detail-card .el-card__header) { padding-top: 4px; padding-bottom: 0; }
.analysis-container :deep(.detail-tabs) { flex: 1 1 auto; min-width: 0; }
.analysis-container :deep(.detail-tabs .el-tabs__header) { margin: 0; }
.analysis-container :deep(.detail-tabs .el-tabs__content) { display: none; }
.analysis-container :deep(.analysis-note) { margin: 8px 0 12px; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.7; }
.analysis-container :deep(.analysis-grid) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
@media (max-width: 900px) {
  .analysis-container :deep(.analysis-hero) { grid-template-columns: minmax(0, 1fr); }
  .analysis-container :deep(.analysis-grid) { grid-template-columns: 1fr; }
}
</style>
