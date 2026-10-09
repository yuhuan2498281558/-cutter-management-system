<template>
  <div class="memory-badge-bar">
    <div class="memory-badge-item">
      <span>本次提问</span>
      <el-radio-group
        :model-value="contextMode"
        :disabled="disabled"
        size="small"
        aria-label="查询条件继承方式"
        @update:model-value="emit('update:contextMode', $event)"
      >
        <el-radio-button value="auto">自动判断</el-radio-button>
        <el-radio-button value="new">新查询</el-radio-button>
        <el-radio-button value="continue">延续上问</el-radio-button>
      </el-radio-group>
    </div>
    <span class="mode-hint">{{ modeHint }}</span>
    <div v-if="slotLabels.length" class="memory-badge-item slots-item">
      <span>上次条件</span>
      <el-tag
        v-for="slot in slotLabels"
        :key="slot.key"
        size="small"
        :type="isPendingSlot(slot.key) ? 'warning' : 'info'"
        :title="isLinkedClear(slot.key) ? '撤销刀型清除后可保留此刀位；本次问题明确指定的新刀位仍优先' : pendingClears.includes(slot.key) ? '点击关闭按钮撤销清除' : slot.key === 'tool_type' ? '下次清除刀型及其旧刀位条件，保留环号范围' : '下次提问清除此条件，保留其他条件'"
      >
        {{ isLinkedClear(slot.key) ? '随刀型清除 · ' : isPendingSlot(slot.key) ? '待清除 · ' : '' }}{{ slot.label }}
        <button
          v-if="!isLinkedClear(slot.key)"
          type="button"
          class="slot-clear"
          :disabled="disabled"
          :aria-label="`${isPendingSlot(slot.key) ? '撤销清除' : '清除'}${slot.label}`"
          @click="emit('toggleClear', slot.key)"
        >×</button>
      </el-tag>
    </div>
    <span v-else-if="memoryInfo?.activeSlots !== undefined" class="scope-empty">上次无附加筛选</span>
    <el-tooltip v-if="memoryInfo?.message_count !== undefined" content="已保存的历史轮数；每次回答只使用与问题相关且在长度限制内的上下文。新查询保留历史，不沿用上一问的筛选条件。" placement="bottom">
      <span class="saved-count">已保存 {{ Math.floor((memoryInfo.message_count || 0) / 2) }} 轮</span>
    </el-tooltip>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { ContextMode, MemoryMetadata, QuerySlot } from '../types';

const props = defineProps<{
  memoryInfo?: MemoryMetadata;
  contextMode: ContextMode;
  pendingClears: QuerySlot[];
  disabled?: boolean;
}>();
const emit = defineEmits<{
  (event: 'update:contextMode', mode: ContextMode): void;
  (event: 'toggleClear', slot: QuerySlot): void;
}>();

const names: Record<QuerySlot, string> = { ring_range: '环号范围', tool_type: '刀具类型', cutter_position_no: '刀位号' };
const toolNames: Record<string, string> = { DISC: '滚刀', SCRAPER: '刮刀', RIPPER: '撕裂刀' };
const isLinkedClear = (slot: QuerySlot) => slot === 'cutter_position_no' && props.pendingClears.includes('tool_type') && !props.pendingClears.includes(slot);
const isPendingSlot = (slot: QuerySlot) => props.pendingClears.includes(slot) || isLinkedClear(slot);
const modeHint = computed(() => ({
  auto: '独立问题重新查询，追问沿用条件',
  new: '按本次问题重新确定条件',
  continue: '沿用上问条件，本次指定优先',
}[props.contextMode]));

const slotLabels = computed(() => {
  const values = props.memoryInfo?.activeSlots;
  // 空对象代表确实没有条件，不能退回旧版本的名称列表。
  const keys = values !== undefined ? Object.keys(values) : props.memoryInfo?.slots || [];
  return keys.filter((key): key is QuerySlot => key in names).map((key) => {
    const value = values?.[key];
    let label = `${names[key]}（值未提供）`;
    if (value !== undefined && value !== null) {
      if (key === 'ring_range' && Array.isArray(value)) label = `${value[0]}–${value[1]} 环`;
      else if (key === 'tool_type') label = toolNames[String(value)] || String(value);
      else label = `刀位 ${value}`;
    }
    return { key, label };
  });
});
</script>

<style scoped lang="scss">
.memory-badge-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  padding: 8px 16px;
  flex-shrink: 0;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  font-size: 12px;
  color: #64748b;
}
.memory-badge-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.mode-hint, .scope-empty { color: #64748b; }
.saved-count { margin-left: auto; white-space: nowrap; cursor: help; }
.slot-clear {
  margin-left: 4px;
  padding: 0 2px;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  &:focus-visible { outline: 2px solid #409eff; outline-offset: 1px; }
  &:disabled { opacity: 0.5; cursor: default; }
}
</style>
