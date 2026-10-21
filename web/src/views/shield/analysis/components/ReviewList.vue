<template>
  <div class="review-list">
    <p v-for="item in pending" :key="item.name" class="review-item"><b>{{ item.lead }}</b>：{{ item.detail }}</p>
    <p v-if="!pending.length" class="review-quiet">没有需要核对的记录</p>
    <p v-else-if="quiet.length" class="review-quiet">{{ quiet.map(item => item.name).join('、') }}：均为 0</p>
  </div>
</template>

<script setup lang="ts">
// "需要核对"：只把不为 0 的项单独标出，为 0 的项合成一行。
import { computed } from 'vue';

const props = defineProps<{
  items: Array<{ name: string; pending: boolean; lead: string; detail: string }>;
}>();

const pending = computed(() => props.items.filter(item => item.pending));
const quiet = computed(() => props.items.filter(item => !item.pending));
</script>

<style scoped>
.review-list { display: grid; gap: 8px; align-content: start; }
.review-list p { margin: 0; }
.review-item { padding: 8px 10px; border-radius: var(--dv-radius); background: var(--dv-warning-bg); color: var(--dv-warning-text); line-height: 1.6; }
.review-item b { font-weight: 600; }
.review-quiet { font-size: var(--el-font-size-extra-small); color: var(--dv-text-muted); }
</style>
