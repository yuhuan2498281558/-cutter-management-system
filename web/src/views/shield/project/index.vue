<template>
  <fs-page>
    <fs-crud ref="crudRef" v-bind="crudBinding">
      <template #actionbar-right>
        <el-button type="primary" @click="openImportDialog">导入掘进动态数据</el-button>
        <ExportDropdown title="项目信息明细" :crud-binding="crudBinding" />
      </template>
    </fs-crud>
    <el-dialog v-model="importDialogVisible" title="导入掘进动态数据" width="560px" :close-on-click-modal="false">
      <el-form label-width="130px">
        <el-form-item label="项目">
          <el-select v-model="importForm.project" placeholder="请选择项目" filterable clearable style="width: 100%">
            <el-option v-for="item in projectOptions" :key="item.id" :label="item.project_name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="盾构机">
          <el-select v-model="importForm.shield_machine" placeholder="请选择盾构机" filterable clearable style="width: 100%">
            <el-option v-for="item in machineOptions" :key="item.id" :label="item.shield_model" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="共享文件夹路径">
          <el-input v-model="importForm.folder_path" placeholder="请输入服务器可访问的共享文件夹路径" />
        </el-form-item>
        <el-form-item label="起始环号">
          <el-input-number v-model="importForm.start_ring_no" :min="1" :precision="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="每环采样点数">
          <el-input-number v-model="importForm.files_per_ring" :min="1" :precision="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="覆盖已有环号">
          <el-switch v-model="importForm.overwrite" />
        </el-form-item>
        <el-form-item label="导入不足一环数据">
          <el-switch v-model="importForm.import_incomplete" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="importLoading" @click="submitImport">开始导入</el-button>
      </template>
    </el-dialog>
  </fs-page>
</template>

<script lang="ts" setup name="ShieldProject">
import { reactive, ref, onMounted } from 'vue';
import { useExpose, useCrud } from '@fast-crud/fast-crud';
import { ElMessage } from 'element-plus';
import { request } from '/@/utils/service';
import { createCrudOptions } from './crud';
import * as api from './api';
import ExportDropdown from '/@/views/shield/components/ExportDropdown.vue';

const defaultImportForm = () => ({
  project: undefined as number | undefined,
  shield_machine: undefined as number | undefined,
  folder_path: '',
  start_ring_no: undefined as number | undefined,
  files_per_ring: 10,
  overwrite: true,
  import_incomplete: false,
});

// crud组件的ref
const crudRef = ref();
// crud 配置的ref
const crudBinding = ref();
const importDialogVisible = ref(false);
const importLoading = ref(false);
const projectOptions = ref<any[]>([]);
const machineOptions = ref<any[]>([]);
const importForm = reactive(defaultImportForm());
// 暴露的方法
const { crudExpose } = useExpose({ crudRef, crudBinding });
// 你的crud配置
const { crudOptions } = createCrudOptions({ crudExpose });
// 初始化crud配置
const { resetCrudOptions } = useCrud({ crudExpose, crudOptions });

// 页面打开后获取列表数据
onMounted(() => {
  crudExpose.doRefresh();
});

async function loadImportOptions() {
  const [projectRes, machineRes] = await Promise.all([
    api.GetList({ page: 1, limit: 10000 } as any),
    request({ url: '/api/shield/shield_machine_basic_info/', method: 'get', params: { page: 1, limit: 10000 } }),
  ]);
  projectOptions.value = projectRes?.data?.results ?? projectRes?.data ?? [];
  machineOptions.value = machineRes?.data?.results ?? machineRes?.data ?? [];
}

async function openImportDialog() {
  Object.assign(importForm, defaultImportForm());
  importDialogVisible.value = true;
  await loadImportOptions();
}

async function submitImport() {
  if (!importForm.project) {
    ElMessage.warning('请选择项目');
    return;
  }
  if (!importForm.shield_machine) {
    ElMessage.warning('请选择盾构机');
    return;
  }
  if (!importForm.folder_path.trim()) {
    ElMessage.warning('请输入共享文件夹路径');
    return;
  }

  importLoading.value = true;
  try {
    const response = await api.ImportTunnelingXml(importForm.project, {
      shield_machine: importForm.shield_machine,
      folder_path: importForm.folder_path.trim(),
      start_ring_no: importForm.start_ring_no,
      files_per_ring: importForm.files_per_ring,
      overwrite: importForm.overwrite,
      import_incomplete: importForm.import_incomplete,
    });
    ElMessage.success(response?.msg || '导入成功');
    importDialogVisible.value = false;
    crudExpose.doRefresh();
  } catch (error: any) {
    ElMessage.error(error?.msg || error?.response?.data?.msg || '导入失败');
  } finally {
    importLoading.value = false;
  }
}
</script>
