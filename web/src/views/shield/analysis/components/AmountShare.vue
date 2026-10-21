<template>
  <div class="amount-share" :class="{ 'is-inline': inline }">
    <div class="share-bar" role="img" :aria-label="barLabel">
      <span v-for="part in rows" :key="part.label" :style="{ width: part.width, background: part.color }" />
    </div>
    <table class="share-legend">
      <tbody>
        <tr v-for="part in rows" :key="part.label">
          <td class="share-swatch-cell"><i class="share-swatch" :style="{ background: part.color }" /></td>
          <th scope="row"><span class="share-name">{{ part.label }}<InfoTip v-if="part.tip" :content="part.tip" /></span></th>
          <td class="share-amount">{{ formatCurrency(part.amount) }}</td>
          <td class="share-percent">{{ part.percent }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
// 合计下方的堆叠比例条和图例：每项的金额和占合计的比例；合计为 0 或缺失时占比显示"—"。
// inline 时图例排成一行，用在一排数字下面。
import { computed } from 'vue';
import InfoTip from '/@/components/InfoTip.vue';
import { formatCurrency, formatPercent } from '../utils/presentation';

const props = defineProps<{
  parts: Array<{ label: string; amount: number | null | undefined; color: string; tip?: string }>;
  total: number | null | undefined;
  inline?: boolean;
}>();

const rows = computed(() => {
  const total = Number(props.total);
  const divisible = props.total != null && Number.isFinite(total) && total > 0;
  return props.parts.map(part => {
    const amount = Number(part.amount);
    const share = divisible && part.amount != null && Number.isFinite(amount) ? amount / total : null;
    return {
      ...part,
      percent: share == null ? '—' : formatPercent(share),
      width: `${share == null ? 0 : Math.min(Math.max(share, 0), 1) * 100}%`,
    };
  });
});
const barLabel = computed(() => rows.value.map(part => `${part.label} ${part.percent}`).join('，'));
</script>

<style scoped>
.amount-share { display: grid; gap: 10px; }
.share-bar { display: flex; height: 10px; overflow: hidden; border-radius: var(--dv-radius-pill); background: var(--dv-surface-muted); }
.share-bar span { display: block; height: 100%; }
.share-legend { width: 100%; border-collapse: collapse; font-size: var(--el-font-size-small); font-variant-numeric: tabular-nums; }
.share-legend th, .share-legend td { padding: 3px 0; border: 0; text-align: left; font-weight: 400; }
.share-legend th { width: 100%; padding-left: 8px; color: var(--dv-text); }
.share-name { display: inline-flex; align-items: center; gap: 6px; }
.share-swatch-cell { width: 10px; }
.share-swatch { display: block; width: 10px; height: 10px; border-radius: 2px; }
.share-legend .share-amount { padding-left: 16px; text-align: right; white-space: nowrap; color: var(--dv-text); }
.share-legend .share-percent { min-width: 56px; padding-left: 12px; text-align: right; white-space: nowrap; color: var(--dv-text-secondary); }
.is-inline { gap: 8px; }
.is-inline .share-bar { height: 6px; }
.is-inline .share-legend tbody { display: flex; flex-wrap: wrap; gap: 4px 20px; }
.is-inline .share-legend tr { display: flex; align-items: center; gap: 6px; }
.is-inline .share-legend th, .is-inline .share-legend td, .is-inline .share-legend .share-amount, .is-inline .share-legend .share-percent { width: auto; min-width: 0; padding: 0; }
</style>
