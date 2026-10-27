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
        <span class="panel-title">上下文<small>（{{ measured ? '实测' : '估算' }}）</small></span>
        <span v-if="usedPercent !== null" :class="['panel-percent', `level-${level}`]">{{ usedPercent }}%</span>
      </div>

      <template v-if="info && info.used !== null && info.parts">
        <div class="panel-total">
          <span>{{ info.kind === 'baseline' ? '下一问起步' : info.exceeded ? '上一问超出上限' : '本轮最大一次调用' }}</span>
          <span class="mono">{{ formatTokens(info.used) }} / {{ formatTokens(info.window) }}</span>
        </div>
        <div class="usage-bar" aria-hidden="true">
          <span v-for="row in barRows" :key="row.key" :class="`seg seg-${row.key}`" :style="{ width: `${row.share}%` }" />
          <i v-if="triggerShare !== null" class="trigger-mark" :style="{ left: `${triggerShare}%` }" />
        </div>
        <ul class="usage-rows" :title="measured ? '总数是接口实测值，分项按估算比例分摊' : ''">
          <li v-for="row in rows" :key="row.key">
            <span :class="`dot seg-${row.key}`" />
            <span class="row-label">{{ row.label }}</span>
            <span v-if="row.note" class="row-note">{{ row.note }}</span>
            <span class="row-value mono">{{ formatTokens(row.value) }}</span>
          </li>
        </ul>
        <p v-if="billingLine" class="panel-billing mono">{{ billingLine }}</p>
        <p v-if="compactionLine" class="panel-billing mono">{{ compactionLine }}</p>
      </template>
      <p v-else-if="info?.kind === 'rule'" class="panel-empty">直连查库不调用模型，不占模型上下文。</p>
      <p v-else class="panel-empty">还没有用量数据，发一次模型分析后显示。</p>

      <div v-if="info" class="panel-rules">
        <div class="rules-title">上下文怎么管理</div>
        <ul>
          <li>整段对话原文带入，包括之前同一项目的查询结果{{ historyNote }}</li>
          <li>长列表只给第 1 页并标明总数，模型需要时自己翻页或按相同条件重查{{ pagingNote }}</li>
          <li>单个结果超过 {{ formatTokens(info.thresholds.compaction_min_tokens) }} 改成表格式编码，数据不删{{ compactNote }}</li>
          <li v-if="autoCompaction">用到 {{ formatTokens(trigger) }}（窗口的 {{ triggerPercent }}%）时，先精简早前的大查询结果，仍不够再把早前对话整理成摘要，最近的原文保留</li>
          <li v-else>超过 {{ formatTokens(hardLimit) }} 本问不生成回答，请缩小环号范围或重置对话</li>
        </ul>
      </div>
      <div v-if="canCompact" class="panel-actions">
        <el-button size="small" :disabled="busy" @click="requestCompact">整理早前对话</el-button>
      </div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { ContextInfo } from '../types';

// busy：生成、重置或整理中，不能再点整理
const props = defineProps<{ info?: ContextInfo | null; busy?: boolean }>();
const emit = defineEmits<{ (e: 'compact'): void }>();

const CIRCUMFERENCE = 2 * Math.PI * 8;
const panelOpen = ref(false);

const formatTokens = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return value >= 1000 ? `${(value / 1000).toFixed(1).replace(/\.0$/, '')}k` : String(Math.round(value));
};

const measured = computed(() => props.info?.measurement === 'actual');
const hardLimit = computed(() => props.info?.hard_input_limit ?? props.info?.input_budget ?? 0);
// 旧后端没有触发线：按输入上限算比例，70% / 90% 提醒
const trigger = computed(() => props.info?.trigger_tokens ?? null);
const autoCompaction = computed(() => props.info?.compaction?.auto === true);
const triggerPercent = computed(() => (props.info && trigger.value ? Math.round((trigger.value / props.info.window) * 100) : null));

const usedPercent = computed(() => {
  const info = props.info;
  if (!info || info.used === null) return null;
  const total = trigger.value ? info.window : info.input_budget;
  return total ? Math.round((info.used / total) * 100) : null;
});

// 正常 → 接近触发线（75%）→ 到达触发线或超限；直连查库和无数据为灰色
const level = computed(() => {
  const info = props.info;
  if (info?.exceeded) return 'danger';
  if (!info || info.used === null || usedPercent.value === null) return 'idle';
  if (trigger.value) {
    if (info.used >= trigger.value) return 'danger';
    return info.used >= trigger.value * 0.75 ? 'warning' : 'normal';
  }
  if (usedPercent.value >= 90) return 'danger';
  return usedPercent.value >= 70 ? 'warning' : 'normal';
});

const dash = computed(() => (CIRCUMFERENCE * Math.min(100, usedPercent.value ?? 0)) / 100);

const tooltipLines = computed(() => {
  const info = props.info;
  if (!info) return ['上下文用量：还没有数据'];
  if (info.kind === 'rule' || info.used === null) return ['直连查库不调用模型，不占模型上下文'];
  const source = measured.value ? '实测' : '估算';
  const head = info.kind === 'baseline' ? `下一问起步（${source}）` : info.exceeded ? `上一问超出上限（${source}）` : `本轮模型上下文（${source}）`;
  const lines = [head, `已用 ${formatTokens(info.used)} / ${formatTokens(trigger.value ? info.window : info.input_budget)} · ${usedPercent.value}%`];
  if (level.value === 'warning') lines.push(autoCompaction.value ? `接近 ${formatTokens(trigger.value)}，到了会自动整理早前对话` : '接近上限，大范围查询可能超出');
  if (level.value === 'danger') lines.push(autoCompaction.value && !info.exceeded ? '下一问会先整理早前对话' : '建议缩小环号范围或重置对话');
  return lines;
});

const PART_LABELS = {
  system: '系统提示',
  tools: '工具说明',
  memory: '对话历史',
  question: '本次问题',
  results: '本轮查询结果',
  other: '其他开销',
} as const;

const rows = computed(() => {
  const info = props.info;
  if (!info?.parts || info.used === null) return [];
  const history = info.history;
  const notes: Partial<Record<keyof typeof PART_LABELS, string>> = {
    memory: history ? `${history.turns} 轮 · ${history.tool_results} 个查询结果` : `${info.memory.included_turns} 轮`,
    results: info.results_raw && info.results_raw > info.parts.results ? `原 ${formatTokens(info.results_raw)}` : '',
  };
  // 实测时总数以接口为准，分项按估算比例分摊，各行相加仍等于已用
  const estimated = Object.values(info.parts).reduce((sum, value) => sum + value, 0);
  const scale = measured.value && estimated > 0 ? info.used / estimated : 1;
  const parts = (Object.keys(PART_LABELS) as (keyof typeof PART_LABELS)[])
    .map((key) => ({ key, label: PART_LABELS[key], value: Math.round(info.parts![key] * scale), note: notes[key] || '' }))
    .filter((row) => row.value > 0);
  return [
    ...parts,
    { key: 'free', label: '剩余', value: Math.max(0, hardLimit.value - info.used), note: '' },
    { key: 'reserve', label: '预留回答 + 余量', value: info.output_reserve + info.safety_margin, note: '' },
  ];
});

// 进度条按整个窗口画：已用各项、剩余、预留；触发线另画一道竖线
const barRows = computed(() => {
  const window = props.info?.window || 0;
  if (!window) return [];
  return rows.value.map((row) => ({ ...row, share: (row.value / window) * 100 }));
});
const triggerShare = computed(() => (props.info?.window && trigger.value ? (trigger.value / props.info.window) * 100 : null));

const billingLine = computed(() => {
  const usage = props.info?.kind === 'turn' ? props.info.provider_usage : null;
  if (!usage || usage.prompt_tokens === null) return '';
  const cache = usage.cache_hit_tokens ? `（缓存命中 ${formatTokens(usage.cache_hit_tokens)}）` : '';
  return `本轮接口计费：输入 ${formatTokens(usage.prompt_tokens)}${cache} · 输出 ${formatTokens(usage.completion_tokens)}`;
});

const historyNote = computed(() => {
  const history = props.info?.history;
  if (!history) return '';
  const parts = [];
  if (history.other_project_turns) parts.push(`${history.other_project_turns} 轮属于其他项目`);
  if (history.legacy_qa_turns) parts.push(`${history.legacy_qa_turns} 轮是改版前的记录`);
  return parts.length ? `（${parts.join('、')}，只带问答文字）` : '';
});

const compactionLine = computed(() => {
  const compaction = props.info?.compaction;
  if (!compaction?.last_before || !compaction.last_after) return '';
  return `早前对话已整理：${formatTokens(compaction.last_before)} → ${formatTokens(compaction.last_after)}`;
});

// 后端支持手动整理、并且至少有两轮历史时才给按钮
const canCompact = computed(() => props.info?.compaction?.manual === true && (props.info.history?.turns ?? 0) >= 2);
const requestCompact = () => {
  panelOpen.value = false;
  emit('compact');
};

const pagingNote = computed(() => {
  const info = props.info;
  if (!info || info.paged_lists === undefined) return '';
  const parts = [];
  if (info.paged_lists) parts.push(`分页 ${info.paged_lists} 处`);
  if (info.page_requests) parts.push(`翻页 ${info.page_requests} 次`);
  return parts.length ? `（本轮${parts.join('，')}）` : '';
});
const compactNote = computed(() => (props.info?.compacted_results ? `（本轮 ${props.info.compacted_results} 条）` : ''));
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
    position: relative;
    display: flex;
    height: 6px;
    border-radius: 3px;
    overflow: hidden;
    background: var(--dv-fill);
    margin-bottom: 8px;

    .seg {
      height: 100%;
    }

    .trigger-mark {
      position: absolute;
      top: -2px;
      bottom: -2px;
      width: 2px;
      margin-left: -1px;
      background: var(--dv-warning);
    }
  }

  .panel-billing {
    margin: -4px 0 10px;
    color: var(--dv-text-secondary);
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

  .panel-actions {
    display: flex;
    justify-content: flex-end;
    padding-top: 8px;
    border-top: 1px solid var(--dv-border);
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
