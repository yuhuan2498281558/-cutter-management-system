<template>
  <fs-page>
    <fs-crud ref="crudRef" v-bind="crudBinding">
      <template #actionbar-right>
        <ExportDropdown title="开仓明细" :crud-binding="crudBinding" />
      </template>
    </fs-crud>
    <OpeningCompletionDialog
      v-model="completionVisible"
      :opening="selectedOpening"
      @saved="handleCompletionSaved"
    />
  </fs-page>
</template>

<script lang="ts" setup name="ShieldWarehouseOpening">
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useExpose, useCrud } from '@fast-crud/fast-crud';
import { ElMessage, ElMessageBox } from 'element-plus';
import { createCrudOptions } from './crud';
import * as api from './api';
import { request } from '/@/utils/service';
import ExportDropdown from '/@/views/shield/components/ExportDropdown.vue';
import OpeningCompletionDialog from './OpeningCompletionDialog.vue';
import type { WarehouseOpeningBasicInfoType } from './types';

const crudRef = ref();
const crudBinding = ref();
const { crudExpose } = useExpose({ crudRef, crudBinding });
const router = useRouter();
const completionVisible = ref(false);
const selectedOpening = ref<WarehouseOpeningBasicInfoType | null>(null);

const openCompletion = (row: WarehouseOpeningBasicInfoType) => {
  selectedOpening.value = row;
  completionVisible.value = true;
};

const handleCompletionSaved = async (opening: WarehouseOpeningBasicInfoType) => {
  await crudExpose.doRefresh();
  router.push({
    path: '/shield/toolChangeDetail',
    query: {
      warehouse_id: opening.id,
      warehouse_code: opening.warehouse_id,
      mode: 'supplement',
    },
  });
};

const withdrawCompletion = async (opening: WarehouseOpeningBasicInfoType) => {
  if (!opening.id) return;
  try {
    await ElMessageBox.confirm(
      '撤回后将关闭桌面补录，并按移动端明细重新计算检查数和更换数；移动任务会退回待复核。是否继续？',
      '撤回汇总确认',
      { type: 'warning', confirmButtonText: '确认撤回', cancelButtonText: '取消' },
    );
  } catch {
    return;
  }
  const response = await api.WithdrawSummary(opening.id);
  ElMessage.success(response.msg || '开仓汇总已撤回');
  await crudExpose.doRefresh();
};

// createCrudOptions 只调用一次（setup 上下文），保证 useRouter() 正常
const { crudOptions } = createCrudOptions({
  crudExpose,
  onSupplement: openCompletion,
  onWithdraw: withdrawCompletion,
});
const { resetCrudOptions } = useCrud({ crudExpose, crudOptions });

onMounted(async () => {
  try {
    const [projectRes, smRes] = await Promise.all([
      request({ url: '/api/shield/project/', method: 'get', params: { limit: 1 } }),
      request({ url: '/api/shield/shield_machine_basic_info/', method: 'get', params: { limit: 1 } }),
    ]);
    const projects = Array.isArray(projectRes.data) ? projectRes.data : [];
    const shields = Array.isArray(smRes.data) ? smRes.data : [];

    // 直接修改 crudOptions 的列默认值，然后 resetCrudOptions 重建 crudBinding
    // 这样每次打开新增表单时 fast-crud 都会读取到正确的默认值
    if (projects[0]) {
      crudOptions.columns.project.form.value = projects[0].id;
    }
    if (shields[0]) {
      crudOptions.columns.shield_model.form.value = shields[0].id;
    }

    if (projects[0] || shields[0]) {
      resetCrudOptions(crudOptions);
    }
  } catch {}

  crudExpose.doRefresh();
});
</script>
