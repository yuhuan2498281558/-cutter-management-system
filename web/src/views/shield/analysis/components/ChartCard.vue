<template>
  <el-card class="chart-card" shadow="never" :style="{ height: height || 'auto' }">
    <template #header>
      <div class="chart-card-header">
        <span class="chart-title">{{ title }}</span>
        <slot name="toolbar" />
      </div>
    </template>
    <div
      class="chart-card-body"
      :style="{ height: chartHeight }"
      v-loading="loading"
      element-loading-text="加载中..."
    >
      <div v-if="!loading && isEmpty" class="empty-tip">
        <el-empty description="暂无足够数据，请继续录入" :image-size="80" />
      </div>
      <slot v-else />
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{
  title: string;
  loading?: boolean;
  height?: string;
  chartHeight?: string;
  isEmpty?: boolean;
}>();

const chartHeight = computed(() => props.chartHeight || '300px');
</script>

<style scoped>
.chart-card {
  border-radius: 8px;
  margin-bottom: 16px;
}
.chart-card :deep(.el-card__header) {
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
}
.chart-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.chart-title {
  font-size: 14px;
  font-weight: 600;
  color: #1a1a1a;
}
.chart-card-body {
  position: relative;
}
.empty-tip {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 200px;
}
</style>
