<template>
  <fs-page class="warehouse-opening-page">
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
import { ref, watchEffect, onActivated, onDeactivated, onMounted, onUnmounted } from 'vue';
import { isNavigationFailure, NavigationFailureType, useRouter } from 'vue-router';
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
const withdrawingId = ref<number | null>(null);
let withdrawalGeneration = 0;
let withdrawalPageActive = true;
let completionGeneration = 0;
const invalidateCompletion = () => {
  completionGeneration++;
  completionVisible.value = false;
  selectedOpening.value = null;
};
const invalidateWithdrawal = () => {
  withdrawalPageActive = false;
  withdrawalGeneration++;
  withdrawingId.value = null;
  invalidateCompletion();
};
onActivated(() => { withdrawalPageActive = true; });
onDeactivated(invalidateWithdrawal);
onUnmounted(invalidateWithdrawal);

const openCompletion = (row: WarehouseOpeningBasicInfoType) => {
  if (!withdrawalPageActive) return;
  completionGeneration++;
  selectedOpening.value = row;
  completionVisible.value = true;
};

const handleCompletionSaved = async (opening: WarehouseOpeningBasicInfoType) => {
  if (!withdrawalPageActive || !opening.id || selectedOpening.value?.id !== opening.id) return;
  const generation = ++completionGeneration;
  const isCurrent = () => withdrawalPageActive && generation === completionGeneration;
  const target = {
    path: '/shield/toolChangeDetail',
    query: {
      warehouse_id: opening.id,
      warehouse_code: opening.warehouse_id,
      mode: 'supplement',
    },
  };
  // Reflect the confirmed server record even if the following list read fails.
  Object.assign(selectedOpening.value, opening);
  completionVisible.value = false;
  selectedOpening.value = null;
  try {
    await crudExpose.doRefresh();
  } catch {
    if (isCurrent()) ElMessage.warning('开仓汇总已确认，但列表刷新失败，将继续进入补录；返回列表后请刷新核对状态。');
  }
  if (!isCurrent()) return;
  const warnNavigation = () => {
    if (isCurrent()) ElMessage.warning('开仓汇总已确认，但未能进入补录页，请从列表重新点击“补录明细”，无需重复确认。');
  };
  try {
    const failure = await router.push(target);
    if (isNavigationFailure(failure, NavigationFailureType.aborted)) warnNavigation();
  } catch {
    warnNavigation();
  }
};

const withdrawCompletion = async (opening: WarehouseOpeningBasicInfoType) => {
  if (!opening.id || !withdrawalPageActive || withdrawingId.value !== null) return;
  invalidateCompletion();
  const openingId = opening.id;
  const generation = ++withdrawalGeneration;
  const isCurrent = () => withdrawalPageActive && generation === withdrawalGeneration;
  // The lock includes the confirmation dialog, not only the HTTP request.
  withdrawingId.value = openingId;
  try {
    try {
      await ElMessageBox.confirm(
        '撤回后将关闭桌面补录，并按移动端明细重新计算检查数和更换数；移动任务会退回待复核。是否继续？',
        '撤回汇总确认',
        { type: 'warning', confirmButtonText: '确认撤回', cancelButtonText: '取消' },
      );
    } catch {
      return;
    }
    if (!isCurrent()) return;
    const response = await api.WithdrawSummary(openingId);
    if (!isCurrent()) return;
    ElMessage.success(response.msg || '开仓汇总已撤回');
    try {
      await crudExpose.doRefresh();
    } catch {
      if (isCurrent()) ElMessage.warning('开仓汇总已撤回，但列表刷新失败，请刷新页面核对最新状态。');
    }
  } catch {
    if (isCurrent()) ElMessage.warning('未能获取撤回结果，请刷新列表核对汇总状态后再重试。');
  } finally {
    if (generation === withdrawalGeneration) withdrawingId.value = null;
  }
};

// createCrudOptions 只调用一次（setup 上下文），保证 useRouter() 正常
const { crudOptions } = createCrudOptions({
  crudExpose,
  onSupplement: openCompletion,
  onWithdraw: withdrawCompletion,
  withdrawingId,
});
const { resetCrudOptions } = useCrud({ crudExpose, crudOptions });

// Fast-CRUD's menu items do not inherit button disabled/loading props.
// Lock the whole menu while the existing withdrawal confirmation/request is pending.
watchEffect(() => {
  const dropdown = crudBinding.value?.rowHandle?.dropdown;
  if (!dropdown?.more) return;
  const pending = withdrawingId.value !== null;
  dropdown.disabled = pending;
  dropdown.more.disabled = pending;
  dropdown.more.loading = pending;
  dropdown.more.text = pending ? '撤回中' : '更多';
});

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

<style>
/* Fast-CRUD teleports this dialog; keep the layout local to this wrapper. */
.warehouse-opening-form-dialog.el-dialog {
  display: flex;
  flex-direction: column;
  max-height: 90vh;
  max-height: 90dvh;
  margin-bottom: 0;
}
.warehouse-opening-form-dialog .el-dialog__header { flex-shrink: 0; }
.warehouse-opening-form-dialog .el-dialog__body,
.warehouse-opening-form-dialog .fs-form-wrapper-body {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.warehouse-opening-form-dialog .el-dialog__body { padding: 12px 20px 16px; }
.warehouse-opening-form-dialog .fs-form-body {
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}
.warehouse-opening-form-dialog .fs-form-footer-btns {
  display: flex;
  flex-shrink: 0;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.warehouse-opening-form-dialog .fs-form-footer-btns .el-button + .el-button { margin-left: 0; }
@media (max-width: 767px) {
  .warehouse-opening-form-dialog .el-dialog__body { padding: 12px 16px 16px; }
  .warehouse-opening-form-dialog .el-form-item { display: block !important; }
  .warehouse-opening-form-dialog .el-form-item__label {
    width: 100% !important;
    height: auto;
    line-height: 20px;
    justify-content: flex-start;
    padding: 0 0 4px;
  }
  .warehouse-opening-form-dialog .fs-form-item-label-text { white-space: normal; }
  .warehouse-opening-form-dialog .el-form-item__content { margin-left: 0 !important; min-width: 0; }
}
</style>

<style scoped>
@media (max-width: 767px) {
  .warehouse-opening-page :deep(.el-table__cell.el-table-fixed-column--right) {
    position: relative !important;
    right: auto !important;
  }

  .warehouse-opening-page :deep(.el-table__cell.el-table-fixed-column--right::before) {
    display: none;
  }

  .warehouse-opening-page :deep(.fs-search .fs-search-columns) {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }

  .warehouse-opening-page :deep(.fs-search .fs-search-col) {
    width: auto;
    min-width: 0 !important;
    max-width: none;
    margin: 0;
    padding: 0;
  }

  .warehouse-opening-page :deep(.fs-search .fs-search-slot:empty) { display: none; }
  .warehouse-opening-page :deep(.fs-search .fs-search-buttons-group) { grid-column: 1 / -1; }
  .warehouse-opening-page :deep(.fs-search .el-form-item) { display: block !important; margin: 0 !important; }
  .warehouse-opening-page :deep(.fs-search .el-form-item__label) {
    width: 100% !important;
    height: auto;
    line-height: 20px;
    margin-bottom: 4px;
    padding: 0;
    justify-content: flex-start;
  }
  .warehouse-opening-page :deep(.fs-search .el-form-item__content) { min-width: 0; margin-left: 0 !important; gap: 8px; }
  .warehouse-opening-page :deep(.fs-search .el-input),
  .warehouse-opening-page :deep(.fs-search .el-select) { width: 100%; }
  .warehouse-opening-page :deep(.fs-search-buttons-group .el-button) { margin: 0; }
}
</style>
