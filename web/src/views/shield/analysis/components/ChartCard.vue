<template>
  <el-card class="chart-card analysis-card" shadow="never" :style="{ height: height || 'auto' }">
    <template #header>
      <div class="chart-card-header">
        <div class="chart-heading">
          <slot name="heading">
            <h3 class="chart-title">{{ title }}</h3>
            <InfoTip v-if="description" :content="description" />
          </slot>
        </div>
        <slot name="toolbar" />
      </div>
    </template>
    <div
      class="chart-card-body"
      :style="{ height: chartHeight }"
      :aria-busy="loading"
      v-loading="loading"
      element-loading-text="加载中..."
    >
      <div v-if="!loading && error" class="state-tip" role="alert">
        <span>{{ error }}</span>
        <el-button size="small" @click="$emit('retry')">重新加载</el-button>
      </div>
      <div v-else-if="!loading && isEmpty" class="state-tip" role="status">
        <span>{{ emptyDescription || '当前范围没有可分析的数据' }}</span>
      </div>
      <div v-show="!error && !isEmpty" class="chart-content"><slot /></div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import InfoTip from '/@/components/InfoTip.vue';

const props = defineProps<{
  title?: string;
  description?: string;
  loading?: boolean;
  height?: string;
  chartHeight?: string;
  isEmpty?: boolean;
  error?: string;
  emptyDescription?: string;
}>();
defineEmits(['retry']);

const chartHeight = computed(() => props.chartHeight || '300px');
</script>

<style scoped>
.chart-card {
  margin-bottom: 12px;
  min-width: 0;
}
.chart-card :deep(.el-card__header) {
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.chart-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.chart-heading { display: flex; align-items: center; gap: 6px; min-width: 0; }
.chart-title {
  margin: 0;
  font-size: var(--el-font-size-base);
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.chart-card :deep(.el-card__body) { padding: 12px; }
.chart-content { min-width: 0; height: 100%; }
.chart-card-body {
  position: relative;
}
.state-tip {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 120px;
  flex-direction: column;
  gap: 12px;
  color: var(--el-text-color-secondary);
}
</style>
