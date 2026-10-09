<template>
  <div class="auto-stratum" :aria-busy="status === 'loading'">
    <el-input :model-value="displayText" disabled :placeholder="placeholder" />
    <div class="auto-stratum-status" :class="{ 'is-error': status === 'error' }" role="status" aria-live="polite">
      <span>{{ statusText }}</span>
      <el-button v-if="status === 'error'" type="primary" link @click="$emit('retry')">重试</el-button>
    </div>
  </div>
</template>

<script lang="ts" setup>
import { computed } from 'vue';

interface StratumItem {
  stratum_type_code: string;
  stratum_type_name: string;
  ring_count: number;
}

const props = withDefaults(
  defineProps<{
    modelValue?: StratumItem[] | string | null;
    kind?: 'between' | 'position';
    placeholder?: string;
    status?: 'waiting' | 'loading' | 'ready' | 'error';
    firstOpening?: boolean;
  }>(),
  {
    modelValue: null,
    kind: 'between',
    placeholder: '自动获取',
    status: 'waiting',
    firstOpening: false,
  },
);
defineEmits<{ retry: [] }>();

const betweenItems = computed(() => (Array.isArray(props.modelValue) ? props.modelValue : []));
const betweenText = computed(() =>
  betweenItems.value.map((item) => `${item.stratum_type_name}（${item.ring_count} 环）`).join('、'),
);
const positionText = computed(() => (typeof props.modelValue === 'string' ? props.modelValue.trim() : ''));
const displayText = computed(() => (props.kind === 'between' ? betweenText.value : positionText.value));
const statusText = computed(() => {
  if (props.status === 'waiting') return '请选择项目并输入换刀环号';
  if (props.status === 'loading') return '正在获取地层信息…';
  if (props.status === 'error') return '获取失败，请重试';
  if (displayText.value) return '已自动获取';
  if (props.kind === 'between' && props.firstOpening) return '首次开仓，暂无期间地层';
  return props.kind === 'between' ? '该环段暂无地层数据' : '该位置暂无地层数据';
});
</script>

<style scoped>
.auto-stratum { width: 100%; min-width: 0; }
.auto-stratum-status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0 8px;
  min-height: 22px;
  font-size: 12px;
  line-height: 20px;
  color: var(--el-text-color-secondary);
}
.auto-stratum-status.is-error { color: var(--el-color-danger); }
.auto-stratum-status .el-button { padding: 0; min-height: 22px; font-size: 12px; }
</style>
