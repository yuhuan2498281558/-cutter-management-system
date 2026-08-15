<template>
  <div class="analysis-container">
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
import { ref, reactive } from 'vue';
import FilterPanel from './components/FilterPanel.vue';
import Overview from './pages/Overview.vue';
import CostAnalysis from './pages/CostAnalysis.vue';
import WearAnalysis from './pages/WearAnalysis.vue';
import CustomAnalysis from './pages/CustomAnalysis.vue';
import type { AnalysisFilter } from './types';

const activeTab = ref('overview');
const currentFilter = reactive<AnalysisFilter>({});

function onFilterChange(filter: AnalysisFilter) {
  Object.assign(currentFilter, {
    project: undefined,
    shield_machine: undefined,
    start_ring: undefined,
    end_ring: undefined,
    tool_parent_type: undefined,
    tool_type_name: undefined,
    tool_type_names: undefined,
    manufacturer: undefined,
    manufacturers: undefined,
    ...filter,
  });
}
</script>

<style scoped>
.analysis-container {
  padding: 16px;
  background: #f5f6fa;
  min-height: 100%;
}
.analysis-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
  background: #fff;
  padding: 0 16px;
  border-radius: 8px 8px 0 0;
}
.analysis-tabs :deep(.el-tabs__content) {
  background: #f5f6fa;
  padding-top: 16px;
}
.coming-soon {
  background: #fff;
  border-radius: 8px;
  padding: 48px;
  text-align: center;
}
</style>
