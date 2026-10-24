<template>
  <details v-if="meta" class="analysis-scope" aria-label="本次统计范围">
    <summary>
      <span class="scope-counts">{{ countsText }}</span>
      <span class="scope-toggle">统计口径与已排除记录</span>
    </summary>
    <div class="scope-details analysis-card">
      <p v-if="meta.draft_opening_count">工程范围草稿 {{ meta.draft_opening_count }} 次{{ meta.summary_status === 'CONFIRMED' ? '（未纳入）' : '（已按当前状态选择）' }}</p>
      <p v-if="meta.unobserved_count">{{ meta.unobserved_count }} 条预建未观察记录未纳入</p>
      <p v-if="meta.excluded_inactive_count">{{ meta.excluded_inactive_count }} 条历史无效刀位已排除</p>
      <p v-if="meta.excluded_invalid_ring_opening_count">{{ meta.excluded_invalid_ring_opening_count }} 次开仓环号不可用，已排除</p>
      <p v-for="warning in meta.warnings" :key="warning">{{ warning }}</p>
      <p>{{ meta.wear_basis }}</p>
      <p>“轻微磨损”归正常，“中度磨损”“偏磨”等计入非正常描述；非正常比例为 100% 表示本次有记录样本全部归为非正常。</p>
      <p v-if="meta.scope.blade_track_min || meta.scope.blade_track_max">{{ meta.blade_track_basis }}</p>
      <p v-if="stratumSelected">{{ meta.stratum_basis || '地层类型按各次开仓所在环段筛选' }}</p>
      <p v-if="meta.observed_basis">{{ meta.observed_basis }}</p>
      <slot />
    </div>
  </details>
</template>
<script setup lang="ts">
import { computed } from 'vue';
import type { AnalysisMeta } from '../types';
import { formatNumber } from '../utils/presentation';
const props = defineProps<{ meta?: AnalysisMeta }>();
const stratumSelected = computed(() => {
  const scope = props.meta?.scope;
  return [scope?.stratum_type, scope?.stratum_types].flat().some(value => String(value ?? '').trim());
});
const countsText = computed(() => {
  const meta = props.meta;
  if (!meta) return '';
  const openings = `${formatNumber(meta.opening_count)} 次开仓`;
  return meta.observed_count != null ? `${openings} · ${formatNumber(meta.observed_count)} 条有效观察` : openings;
});
</script>
<style scoped>
.analysis-scope { margin: 0 0 12px; font-size: var(--el-font-size-extra-small); color: var(--dv-text-secondary); line-height: 1.7; }
.analysis-scope summary { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 14px; width: fit-content; cursor: pointer; list-style: none; }
.analysis-scope summary::-webkit-details-marker { display: none; }
.analysis-scope summary:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.scope-counts { font-variant-numeric: tabular-nums; }
.scope-toggle { color: var(--dv-text); border-bottom: 1px dashed var(--dv-text-muted); }
.scope-details { margin-top: 6px; padding: 8px 12px; }
.scope-details p { margin: 2px 0; }
</style>
