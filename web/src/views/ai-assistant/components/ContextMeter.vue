<template>
  <el-popover
    v-model:visible="panelOpen"
    placement="top-end"
    :width="320"
    trigger="click"
    popper-class="context-meter-popper"
  >
    <template #reference>
      <button
        type="button"
        class="context-meter"
        :class="`level-${level}`"
        :aria-label="tooltipLines.join('，')"
        :title="panelOpen ? '' : tooltipLines.join('\n')"
      >
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <circle class="ring-track" cx="10" cy="10" r="8" />
          <circle class="ring-fill" cx="10" cy="10" r="8" :stroke-dasharray="`${dash} ${CIRCUMFERENCE}`" />
        </svg>
      </button>
    </template>

    <div class="context-panel">
      <div class="panel-head">
        <span class="panel-title">上下文<small>（估算）</small></span>
        <span v-if="usedPercent !== null" :class="['panel-percent', `level-${level}`]">{{ usedPercent }}%</span>
      </div>

      <template v-if="info && info.used !== null && info.parts">
        <div class="panel-total">
          <span>{{ info.kind === 'baseline' ? '下一问起步' : info.exceeded ? '上一问超出上限' : '本轮最大一次调用' }}</span>
          <span class="mono">{{ formatTokens(info.used) }} / {{ formatTokens(info.input_budget) }}</span>
        </div>
        <div class="usage-bar" aria-hidden="true">
          <span v-for="row in barRows" :key="row.key" :class="`seg seg-${row.key}`" :style="{ width: `${row.share}%` }" />
        </div>
        <ul class="usage-rows">
          <li v-for="row in rows" :key="row.key">
            <span :class="`dot seg-${row.key}`" />
            <span class="row-label">{{ row.label }}</span>
            <span v-if="row.note" class="row-note">{{ row.note }}</span>
            <span class="row-value mono">{{ formatTokens(row.value) }}</span>
          </li>
        </ul>
      </template>
      <p v-else-if="info?.kind === 'rule'" class="panel-empty">直连查库不调用模型，不占模型上下文。</p>
      <p v-else class="panel-empty">还没有用量数据，发一次模型分析后显示。</p>

      <div v-if="info" class="panel-rules">
        <div class="rules-title">查询结果怎么进上下文</div>
        <ul>
          <li>汇总在全量数据上先算好，原样交给模型</li>
          <li>长列表只给第 1 页并标明总数，模型需要时自己翻页或按相同条件重查原始数据{{ pagingNote }}</li>
          <li>单个结果超过 {{ formatTokens(info.thresholds.compaction_min_tokens) }} 改成表格式编码，数据不删{{ compactNote }}</li>
          <li v-if="softLimitReachable">早前结果合计超过 {{ formatTokens(info.thresholds.evidence_soft_tokens) }} 时换成摘要，写明怎么取回{{ summarizedNote }}</li>
          <li>处理后仍超过 {{ formatTokens(info.input_budget) }}：本问不生成回答，请缩小环号范围或拆分问题</li>
        </ul>
        <div class="rules-title">对话记忆</div>
        <ul>
          <li>{{ memoryNote }}</li>
        </ul>
      </div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { ContextInfo } from '../types';

const props = defineProps<{ info?: ContextInfo | null }>();

const CIRCUMFERENCE = 2 * Math.PI * 8;
const panelOpen = ref(false);

const formatTokens = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(Math.round(value));
};

const usedPercent = computed(() => {
  const info = props.info;
  if (!info || info.used === null || !info.input_budget) return null;
  return Math.round((info.used / info.input_budget) * 100);
});

// 70% 以下正常，70–90% 接近上限，90% 以上或超限为危险；直连查库和无数据为灰色
const level = computed(() => {
  if (props.info?.exceeded) return 'danger';
  const percent = usedPercent.value;
  if (percent === null) return 'idle';
  if (percent >= 90) return 'danger';
  if (percent >= 70) return 'warning';
  return 'normal';
});

const dash = computed(() => (CIRCUMFERENCE * Math.min(100, usedPercent.value ?? 0)) / 100);

const tooltipLines = computed(() => {
  const info = props.info;
  if (!info) return ['上下文用量：还没有数据'];
  if (info.kind === 'rule' || info.used === null) return ['直连查库不调用模型，不占模型上下文'];
  const head = info.kind === 'baseline' ? '下一问起步（估算）' : info.exceeded ? '上一问超出上限（估算）' : '本轮模型上下文（估算）';
  const lines = [head, `已用 ${formatTokens(info.used)} / ${formatTokens(info.input_budget)} · ${usedPercent.value}%`];
  if (level.value === 'warning') lines.push('接近上限，大范围查询可能超出');
  if (level.value === 'danger') lines.push('建议缩小环号范围或拆分问题');
  return lines;
});

const PART_LABELS = {
  system: '系统提示',
  tools: '工具说明',
  memory: '对话记忆',
  question: '本次问题',
  results: '查询结果',
  other: '其他开销',
} as const;

const rows = computed(() => {
  const info = props.info;
  if (!info?.parts || info.used === null) return [];
  const memory = info.memory;
  const notes: Partial<Record<keyof typeof PART_LABELS, string>> = {
    memory: memory.summary_tokens ? `最近 ${memory.included_turns} 轮 + 摘要` : `最近 ${memory.included_turns} 轮`,
    results: info.results_raw && info.results_raw > info.parts.results ? `原 ${formatTokens(info.results_raw)}` : '',
  };
  const parts = (Object.keys(PART_LABELS) as (keyof typeof PART_LABELS)[])
    .map((key) => ({ key, label: PART_LABELS[key], value: info.parts![key], note: notes[key] || '' }))
    .filter((row) => row.value > 0);
  const remaining = Math.max(0, info.input_budget - info.used);
  return [
    ...parts,
    { key: 'free', label: '剩余', value: remaining, note: '' },
    { key: 'reserve', label: '预留回答 + 余量', value: info.output_reserve + info.safety_margin, note: '' },
  ];
});

// 进度条按整个窗口画：已用各项、剩余、预留
const barRows = computed(() => {
  const window = props.info?.window || 0;
  if (!window) return [];
  return rows.value.map((row) => ({ ...row, share: (row.value / window) * 100 }));
});

const pagingNote = computed(() => {
  const info = props.info;
  if (!info || info.paged_lists === undefined) return '';
  const parts = [];
  if (info.paged_lists) parts.push(`分页 ${info.paged_lists} 处`);
  if (info.page_requests) parts.push(`翻页 ${info.page_requests} 次`);
  return parts.length ? `（本轮${parts.join('，')}）` : '';
});
const compactNote = computed(() => (props.info?.compacted_results ? `（本轮 ${props.info.compacted_results} 条）` : ''));
const summarizedNote = computed(() => (props.info?.summarized_results ? `（本轮 ${props.info.summarized_results} 条）` : ''));
// 软上限高于输入上限时，换摘要之前就已超限，这条规则实际不会发生，不显示
const softLimitReachable = computed(() => Boolean(props.info && props.info.thresholds.evidence_soft_tokens < props.info.input_budget));

const memoryNote = computed(() => {
  const memory = props.info?.memory;
  if (!memory) return '';
  const recent = `只带最近 ${memory.recent_turns} 轮原文（不超过 ${formatTokens(memory.recent_budget)}）`;
  if (memory.summary_trigger_tokens === null || memory.pending_tokens === null) return `${recent}，更早的对话不带入`;
  return `${recent}；更早的对话累计 ${formatTokens(memory.pending_tokens)} / ${formatTokens(memory.summary_trigger_tokens)}，到了自动整理成摘要`;
});
</script>

<style scoped lang="scss">
.context-meter {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  cursor: pointer;

  &:hover {
    background: var(--dv-hover);
  }

  svg {
    width: 18px;
    height: 18px;
    transform: rotate(-90deg);
  }

  circle {
    fill: none;
    stroke-width: 2.4;
  }

  .ring-track {
    stroke: var(--dv-border-strong);
  }

  .ring-fill {
    stroke: var(--dv-text-secondary);
    stroke-linecap: round;
    transition: stroke-dasharray 0.3s ease;
  }

  &.level-warning .ring-fill {
    stroke: var(--dv-warning);
  }

  &.level-danger .ring-fill {
    stroke: var(--dv-danger);
  }
}
</style>

<style lang="scss">
// 浮层挂在 body 上，不能用 scoped
.context-meter-popper {
  .context-panel {
    font-size: 12.5px;
    color: var(--dv-text);
  }

  .mono {
    font-variant-numeric: tabular-nums;
  }

  .panel-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 6px;

    .panel-title {
      font-weight: 600;
      font-size: 13px;

      small {
        font-weight: 400;
        color: var(--dv-text-secondary);
      }
    }

    .panel-percent {
      font-weight: 600;

      &.level-warning {
        color: var(--dv-warning);
      }

      &.level-danger {
        color: var(--dv-danger);
      }
    }
  }

  .panel-total {
    display: flex;
    justify-content: space-between;
    color: var(--dv-text-secondary);
    margin-bottom: 6px;
  }

  .usage-bar {
    display: flex;
    height: 6px;
    border-radius: 3px;
    overflow: hidden;
    background: var(--dv-fill);
    margin-bottom: 8px;

    .seg {
      height: 100%;
    }
  }

  .usage-rows {
    list-style: none;
    margin: 0 0 10px;
    padding: 0;

    li {
      display: flex;
      align-items: center;
      gap: 8px;
      line-height: 24px;
    }

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 2px;
      flex-shrink: 0;
    }

    .row-label {
      color: var(--dv-text);
    }

    .row-note {
      color: var(--dv-text-muted);
      font-size: 12px;
    }

    .row-value {
      margin-left: auto;
      color: var(--dv-text-secondary);
    }
  }

  // 已用各项用主题色系的深浅区分，剩余和预留用灰
  .seg-system { background: var(--dv-text-secondary); }
  .seg-tools { background: var(--dv-text-muted); }
  .seg-memory { background: var(--el-color-primary-light-3); }
  .seg-question { background: var(--el-color-primary-light-5); }
  .seg-results { background: var(--el-color-primary); }
  .seg-other { background: var(--dv-border-strong); }
  .seg-free { background: var(--dv-fill); box-shadow: inset 0 0 0 1px var(--dv-border); }
  .seg-reserve { background: var(--dv-border); }

  .panel-empty {
    margin: 4px 0 10px;
    color: var(--dv-text-secondary);
  }

  .panel-rules {
    border-top: 1px solid var(--dv-border);
    padding-top: 8px;

    .rules-title {
      font-weight: 600;
      margin: 4px 0 2px;
    }

    ul {
      margin: 0 0 4px;
      padding-left: 16px;
      color: var(--dv-text-secondary);
      line-height: 1.6;
    }
  }
}
</style>
