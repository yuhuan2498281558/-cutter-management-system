<template>
  <fs-page>
    <el-row class="mx-2">
      <el-col xs="24" class="p-1">
        <el-card :body-style="{ height: '100%' }">
          <fs-crud ref="crudRef" v-bind="crudBinding">
            <template #actionbar-right>
              <!-- 导入按钮 -->
              <el-upload
                class="upload-demo"
                :action="importApi"
                :headers="uploadHeaders"
                :show-file-list="false"
                accept=".xls,.xlsx"
                :on-success="handleImportSuccess"
                :on-error="handleImportError"
              >
                <el-button type="primary" icon="Upload">导入 Excel</el-button>
              </el-upload>
            </template>
          </fs-crud>
        </el-card>
      </el-col>
    </el-row>
  </fs-page>
</template>

<script lang="ts" setup>
import { ref, onMounted } from 'vue';
import { useExpose, useCrud } from '@fast-crud/fast-crud';
import { createCrudOptions } from './crud';
import { ElMessage } from 'element-plus';

// CRUD 组件的 ref
const crudRef = ref();
// CRUD 配置的 ref
const crudBinding = ref();

// 暴露的方法
const { crudExpose } = useExpose({ crudRef, crudBinding });
// CRUD 配置
const context = {}; // Provide an appropriate context object
const { crudOptions } = createCrudOptions({ crudExpose, context });
// 初始化 CRUD 配置
const { resetCrudOptions } = useCrud({ crudExpose, crudOptions });

// 页面加载后刷新数据
onMounted(() => {
  crudExpose.doRefresh();
});

// 导入相关配置
const importApi = '/api/system/realtime_params/import'; // 后端导入接口
const uploadHeaders = {
  Authorization: `Bearer ${localStorage.getItem('token')}`, // 添加认证头
};

// 导入成功回调
const handleImportSuccess = (response: any) => {
  if (response.code === 200) {
    ElMessage.success('导入成功');
    crudExpose.doRefresh(); // 刷新数据
  } else {
    ElMessage.error(response.msg || '导入失败');
  }
};

// 导入失败回调
const handleImportError = (error: any) => {
  console.error('导入失败:', error);
  ElMessage.error('导入失败，请检查文件格式或网络连接');
};
</script>

<style lang="scss" scoped>
.el-row {
  height: 100%;
  .el-col {
    height: 100%;
  }
}

.el-card {
  height: 100%;
}
</style>