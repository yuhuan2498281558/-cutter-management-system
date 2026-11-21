<template>
  <el-tooltip :content="content" placement="top" :popper-style="{ maxWidth: '320px' }">
    <button type="button" class="info-tip" :aria-label="content" :data-info-tip="content">i</button>
  </el-tooltip>
</template>

<script setup lang="ts">
// 标题旁的 ⓘ：防止误读的统计口径收在这里，悬停或聚焦时显示原文。
// data-info-tip 供数据分析的 PDF 导出把口径还原成一行文字。
defineProps<{ content: string }>();
</script>

<style scoped>
.info-tip {
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  width: 15px;
  height: 15px;
  padding: 0;
  border: 1px solid var(--dv-text-muted);
  border-radius: var(--dv-radius-pill);
  background: transparent;
  color: var(--dv-text-muted);
  font: 400 10px/1 var(--dv-font-sans);
  font-style: normal;
  cursor: help;
  vertical-align: middle;
}
.info-tip:hover,
.info-tip:focus-visible {
  border-color: var(--dv-text-secondary);
  color: var(--dv-text-secondary);
}
.info-tip:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}
</style>
