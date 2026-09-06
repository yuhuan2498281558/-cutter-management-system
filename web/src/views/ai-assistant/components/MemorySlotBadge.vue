<template>
  <div v-if="hasMemoryInfo" class="memory-badge-bar">
    <el-tooltip v-if="engineTip" :content="engineTip" placement="bottom">
      <div class="memory-badge-item engine-item">
        <el-icon class="badge-icon"><Cpu /></el-icon>
        <span class="badge-label">对话记忆</span>
      </div>
    </el-tooltip>
    <div v-else class="memory-badge-item">
      <el-icon class="badge-icon"><Cpu /></el-icon>
      <span class="badge-label">对话记忆</span>
    </div>

    <div v-if="memoryInfo?.message_count !== undefined" class="memory-badge-item">
      <span class="badge-label">已记住:</span>
      <span class="badge-value">{{ Math.floor((memoryInfo?.message_count || 0) / 2) }} 轮对话</span>
    </div>

    <div v-if="slotLabels.length" class="memory-badge-item slots-item">
      <span class="badge-label">当前上下文:</span>
      <div class="slots-container">
        <el-tag
          v-for="slot in slotLabels"
          :key="slot"
          size="small"
          type="primary"
          effect="light"
          class="slot-tag"
        >
          {{ slot }}
        </el-tag>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { Cpu } from '@element-plus/icons-vue';
import { MemoryMetadata } from '../types';

const props = defineProps<{
  memoryInfo?: MemoryMetadata;
}>();

const SLOT_NAME_MAP: Record<string, string> = {
  ring_range: '环号范围',
  tool_type: '刀具类型',
  cutter_position_no: '刀位号',
};

const hasMemoryInfo = computed(() => {
  return !!props.memoryInfo && (
    !!props.memoryInfo.backend ||
    (props.memoryInfo.slots && props.memoryInfo.slots.length > 0) ||
    props.memoryInfo.message_count !== undefined
  );
});

const slotLabels = computed(() => {
  if (!props.memoryInfo?.slots) return [];
  return props.memoryInfo.slots.map((s) => SLOT_NAME_MAP[s] || s);
});

// 引擎与摘要版本属于技术细节，收进悬浮提示，不占据状态栏
const engineTip = computed(() => {
  const parts: string[] = [];
  if (props.memoryInfo?.backend) {
    parts.push(`记忆引擎：${props.memoryInfo.backend === 'django' ? 'Django 持久化' : 'Legacy 会话'}`);
  }
  if (props.memoryInfo?.summary_revision) {
    parts.push(`摘要版本：v${props.memoryInfo.summary_revision}`);
  }
  return parts.join(' · ');
});
</script>

<style scoped lang="scss">
.memory-badge-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 6px 14px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  font-size: 12px;
  color: #64748b;

  .memory-badge-item {
    display: inline-flex;
    align-items: center;
    gap: 4px;

    &.engine-item {
      cursor: help;
    }

    .badge-icon {
      font-size: 14px;
      color: #3b82f6;
    }

    .badge-label {
      color: #94a3b8;
    }

    .badge-value {
      font-weight: 500;
      color: #334155;
    }
  }

  .slots-item {
    .slots-container {
      display: inline-flex;
      gap: 4px;
    }
    .slot-tag {
      font-size: 11px;
      padding: 0 6px;
      height: 20px;
      line-height: 18px;
    }
  }
}
</style>
