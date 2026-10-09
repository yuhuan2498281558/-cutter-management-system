<template>
  <section v-if="meta" class="analysis-scope" aria-label="本次统计范围">
    <div class="scope-main"><strong>{{ scopeSummary(meta) }}</strong><span>生成于 {{ generatedTime }}</span></div>
    <div class="scope-counts">
      <span>{{ meta.opening_count }} 次开仓</span>
      <span v-if="meta.draft_opening_count">工程范围草稿 {{ meta.draft_opening_count }} 次{{ meta.summary_status === 'CONFIRMED' ? '（未纳入）' : '（已按当前状态选择）' }}</span>
      <span v-if="meta.unobserved_count">{{ meta.unobserved_count }} 条预建未观察记录未纳入</span>
      <span v-if="meta.excluded_inactive_count">{{ meta.excluded_inactive_count }} 条历史无效刀位已排除</span>
      <span v-if="meta.excluded_invalid_ring_opening_count">{{ meta.excluded_invalid_ring_opening_count }} 次开仓环号不可用，已排除</span>
      <span v-if="meta.observed_count != null">{{ meta.observed_count }} 条有效观察</span>
    </div>
    <details class="scope-details">
      <summary>统计口径与数据范围</summary>
      <p v-for="warning in meta.warnings" :key="warning">{{ warning }}</p>
      <p>{{ meta.wear_basis }}</p>
      <p>“轻微磨损”“中度磨损”等有记录但非正常词，按现有规则计入非正常描述；非正常比例为 100% 表示本次有记录样本全部归为非正常。</p>
      <p v-if="meta.scope.blade_track_min || meta.scope.blade_track_max">{{ meta.blade_track_basis }}</p>
      <p v-if="meta.observed_basis">{{ meta.observed_basis }}</p>
    </details>
  </section>
</template>
<script setup lang="ts">
import { computed } from 'vue';
import type { AnalysisMeta } from '../types';
import { scopeSummary } from '../utils/presentation';
const props = defineProps<{ meta?: AnalysisMeta }>();
const generatedTime = computed(() => props.meta?.generated_at ? new Date(props.meta.generated_at).toLocaleString('zh-CN') : '');
</script>
<style scoped>
.analysis-scope { margin: 0 0 14px; font-size: 13px; color: var(--el-text-color-regular); line-height: 1.7; }
.scope-main { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.scope-main strong { flex: 1 1 420px; min-width: 0; font-weight: 500; color: var(--el-text-color-primary); overflow-wrap: anywhere; }
.scope-main > span { flex: 0 0 auto; }
.scope-counts { display: flex; flex-wrap: wrap; gap: 4px 16px; margin-top: 4px; }
.scope-details { margin-top: 4px; }
.scope-details summary { cursor: pointer; width: fit-content; }
.scope-details summary:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.scope-details p { margin: 4px 0; }
</style>
