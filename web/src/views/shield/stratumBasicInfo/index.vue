<template>
  <fs-page>
    <fs-crud ref="crudRef" v-bind="crudBinding">
      <template #actionbar-right>
        <ExportDropdown title="地层基本信息明细" :crud-binding="crudBinding" />
        <!-- PDF 地层提取 -->
        <el-button type="warning" :loading="pdfImporting" @click="handleImportFromPdf">从PDF提取地层</el-button>
        <!-- 下载模板按钮 -->
        <el-button type="success" @click="handleDownloadTemplate">下载模板</el-button>
        <!-- 导入按钮 -->
        <el-upload
          class="upload-demo"
          :action="importApi"
          :headers="uploadHeaders"
          :show-file-list="false"
          accept=".xls,.xlsx"
          :on-success="handleImportSuccess"
          :on-error="handleImportError"
          style="display: inline-block; margin-left: 10px;"
        >
          <el-button type="primary" icon="Upload">导入</el-button>
        </el-upload>
      </template>
    </fs-crud>
  </fs-page>
</template>

<script lang="ts" setup name="ShieldStratumBasicInfo">
import { ref, onMounted } from 'vue';
import { useExpose, useCrud } from '@fast-crud/fast-crud';
import { createCrudOptions } from './crud';
import { ElMessage, ElMessageBox } from 'element-plus';
import * as api from './api';
import { getAuthHeader } from '/@/utils/storage';
import ExportDropdown from '/@/views/shield/components/ExportDropdown.vue';

const crudRef = ref();
const crudBinding = ref();
const { crudExpose } = useExpose({ crudRef, crudBinding });
const { crudOptions } = createCrudOptions({ crudExpose });
const { resetCrudOptions } = useCrud({ crudExpose, crudOptions });

onMounted(() => {
  crudExpose.doRefresh();
});

// 导入相关配置
const importApi = '/api/shield/stratum_basic_info/import_data/';
const uploadHeaders = {
  get Authorization() { return getAuthHeader().Authorization; },
};

// 导入成功回调
const handleImportSuccess = (response: any) => {
  if (response.code === 2000 || response.code === 200) {
    ElMessage.success('导入成功');
    crudExpose.doRefresh();
  } else {
    ElMessage.error(response.msg || '导入失败');
  }
};

// 导入失败回调
const handleImportError = (_error: any) => {
  ElMessage.error('导入失败，请检查文件格式或网络连接');
};

// 下载模板
const handleDownloadTemplate = async () => {
  try {
    const response = await api.downloadTemplate();
    const blob = new Blob([response], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = '导入地层基本信息模板.xlsx';
    link.click();
    window.URL.revokeObjectURL(url);
    ElMessage.success('模板下载成功');
  } catch (error: any) {
    ElMessage.error('模板下载失败');
  }
};

// PDF 提取地层
const pdfImporting = ref(false);

const handleImportFromPdf = async () => {
  try {
    await ElMessageBox.confirm(
      '将从地质纵断面 PDF 自动提取每环地层信息并导入，已有数据会被覆盖，是否继续？',
      '从PDF提取地层',
      { confirmButtonText: '确定导入', cancelButtonText: '取消', type: 'warning' }
    );
  } catch {
    return;
  }
  pdfImporting.value = true;
  try {
    const res: any = await api.importFromPdf({ project: 1 });
    if (res.code === 2000 || res.code === 200) {
      const d = res.data;
      ElMessage.success(`导入完成：新建 ${d.created} 条，更新 ${d.updated} 条，共 ${d.total} 环`);
      crudExpose.doRefresh();
    } else {
      ElMessage.error(res.msg || '导入失败');
    }
  } catch (e: any) {
    ElMessage.error('导入失败：' + (e?.message || '网络错误'));
  } finally {
    pdfImporting.value = false;
  }
};
</script>
