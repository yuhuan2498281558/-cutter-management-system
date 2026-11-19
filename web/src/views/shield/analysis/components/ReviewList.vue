<template>
  <div class="review-list">
    <p v-for="item in pending" :key="item.name" class="review-item"><b>{{ item.lead }}</b>：{{ item.detail }}<InfoTip v-if="item.tip" :content="item.tip" /></p>
    <p v-if="!pending.length" class="review-quiet">没有需要核对的记录</p>
    <p v-else-if="quiet.length" class="review-quiet">{{ quiet.map(item => item.name).join('、') }}：均为 0</p>
  </div>
</template>

<script setup lang="ts">
// "需要核对"：只把不为 0 的项单独标出，为 0 的项合成一行。
import { computed } from 'vue';
import InfoTip from '/@/components/InfoTip.vue';

const props = defineProps<{
  items: Array<{ name: string; pending: boolean; lead: string; detail: string; tip?: string }>;
}>();

const pending = computed(() => props.items.filter(item => item.pending));
const quiet = computed(() => props.items.filter(item => !item.pending));
</script>

<style scoped>
.review-list { display: grid; gap: 8px; align-content: start; }
.review-list p { margin: 0; }
.review-item { padding: 8px 10px; border-radius: var(--dv-radius); background: var(--dv-warning-bg); color: var(--dv-warning-text); line-height: 1.6; }
.review-item b { font-weight: 600; }
.review-item :deep(.info-tip) { margin-left: 6px; }
.review-quiet { font-size: var(--el-font-size-extra-small); color: var(--dv-text-muted); }
</style>
