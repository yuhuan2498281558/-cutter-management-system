<template>
  <Teleport v-if="target" :to="target">
    <span v-if="generatedText" class="analysis-generated">生成于 {{ generatedText }}</span>
    <el-button v-if="refresh" :disabled="refreshing" @click="refresh()">刷新</el-button>
    <el-dropdown v-if="exports.length > 1" trigger="click" @command="runExport">
      <el-button :disabled="exports.every(item => item.disabled)">导出<el-icon class="el-icon--right"><ele-ArrowDown /></el-icon></el-button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item v-for="(item, index) in exports" :key="item.label" :command="index" :disabled="item.disabled">{{ item.label }}</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
    <el-button v-else-if="exports.length" :disabled="exports[0].disabled" @click="runExport(0)">{{ exports[0].label }}</el-button>
  </Teleport>
</template>

<script setup lang="ts">
// 当前页签的操作区：由各页面渲染，传送到外壳标题行右侧。
import { computed } from 'vue';

interface AnalysisExportAction {
  label: string;
  disabled: boolean;
  run: () => unknown;
}

const props = defineProps<{
  target?: HTMLElement | null;
  generatedAt?: string;
  refresh?: () => unknown;
  refreshing?: boolean;
  exports: AnalysisExportAction[];
}>();

const generatedText = computed(() => {
  const date = props.generatedAt ? new Date(props.generatedAt) : null;
  if (!date || Number.isNaN(date.getTime())) return '';
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
});
function runExport(index: number) {
  const item = props.exports[index];
  if (item && !item.disabled) item.run();
}
</script>

<style scoped>
.analysis-generated {
  font-size: var(--el-font-size-extra-small);
  color: var(--dv-text-secondary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
</style>
