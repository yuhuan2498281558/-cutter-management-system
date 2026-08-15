<template>
  <el-card class="kpi-card" shadow="never" :style="{ '--accent': accentColor }">
    <div class="kpi-inner">
      <div class="kpi-header">
        <span class="kpi-icon"><i :class="iconClass" /></span>
        <span class="kpi-label">{{ label }}</span>
      </div>
      <div class="kpi-value" :style="{ color: accentColor }">{{ formattedValue }}</div>
      <div v-if="subText" class="kpi-sub">{{ subText }}</div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{
  label: string;
  value: number | string;
  unit?: string;
  /** 格式化方式：'number' | 'currency' | 'percent' | 'decimal' */
  format?: string;
  subText?: string;
  /** iconfont class，如 'iconfont icon-xxx' */
  icon?: string;
  /** 主题色，默认蓝 */
  color?: string;
}>();

const accentColor = computed(() => props.color || '#1677ff');

const iconClass = computed(() => props.icon || 'iconfont icon-shujufenxi');

const formattedValue = computed(() => {
  const v = props.value;
  if (v === undefined || v === null) return '-';
  const fmt = props.format || 'number';
  if (fmt === 'currency') {
    return '¥' + Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }
  if (fmt === 'percent') {
    return (Number(v) * 100).toFixed(1) + '%';
  }
  if (fmt === 'decimal') {
    return Number(v).toFixed(1) + (props.unit || '');
  }
  return Number(v).toLocaleString() + (props.unit || '');
});
</script>

<style scoped>
.kpi-card {
  border-radius: 8px;
  border-left: 4px solid var(--accent);
  overflow: hidden;
}
.kpi-card :deep(.el-card__body) {
  padding: 16px 14px;
}
.kpi-inner {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.kpi-header {
  display: flex;
  align-items: center;
  gap: 6px;
}
.kpi-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.kpi-icon i {
  font-size: 15px;
  color: var(--accent);
}
.kpi-label {
  font-size: 12px;
  color: #666;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.kpi-value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
  padding-left: 2px;
}
.kpi-sub {
  font-size: 11px;
  color: #999;
  padding-left: 2px;
}
</style>
