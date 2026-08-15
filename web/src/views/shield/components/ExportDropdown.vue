<template>
  <el-dropdown :disabled="exportRows.length === 0" @command="handleCommand">
    <el-button type="primary" plain :disabled="exportRows.length === 0">
      导出
      <el-icon class="export-icon"><Download /></el-icon>
    </el-button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item command="excel">Excel</el-dropdown-item>
        <el-dropdown-item command="csv">CSV</el-dropdown-item>
        <el-dropdown-item command="pdf">PDF</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { Download } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import { exportTableData, type ExportColumn, type ExportFormat, type ExportMetaItem } from '../utils/export';

const props = defineProps<{
  title: string;
  filename?: string;
  rows?: any[];
  columns?: ExportColumn[];
  meta?: ExportMetaItem[];
  crudBinding?: any;
}>();

const exportRows = computed(() => {
  if (props.rows) return props.rows;
  return props.crudBinding?.value?.data || [];
});

const exportColumns = computed<ExportColumn[]>(() => {
  if (props.columns?.length) return props.columns;
  const columns = props.crudBinding?.value?.columns || {};
  return Object.entries(columns)
    .filter(([key, config]: any) => key !== '_index' && config?.column?.show !== false)
    .map(([key, config]: any) => ({
      key,
      title: config?.title || key,
      formatter: (row: any, index: number) => {
        const formatter = config?.column?.formatter;
        if (typeof formatter === 'function') {
          return formatter({ row, index, value: row?.[key] });
        }
        return row?.[key];
      },
    }));
});

function handleCommand(format: ExportFormat) {
  if (!exportRows.value.length) {
    ElMessage.warning('暂无可导出的数据');
    return;
  }
  exportTableData({
    title: props.title,
    filename: props.filename || props.title,
    columns: exportColumns.value,
    rows: exportRows.value,
    meta: props.meta,
    format,
  });
}
</script>

<style scoped>
.export-icon {
  margin-left: 4px;
}
</style>
