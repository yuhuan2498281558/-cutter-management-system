<template>
  <el-input :model-value="displayText" disabled placeholder="自动获取" />
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
  }>(),
  {
    modelValue: null,
    kind: 'between',
  },
);

const betweenItems = computed(() => (Array.isArray(props.modelValue) ? props.modelValue : []));
const betweenText = computed(() =>
  betweenItems.value.map((item) => `${item.stratum_type_name}（${item.ring_count} 环）`).join('、'),
);
const positionText = computed(() => (typeof props.modelValue === 'string' ? props.modelValue.trim() : ''));
const displayText = computed(() => (props.kind === 'between' ? betweenText.value : positionText.value));
</script>
