<template>
  <fs-page>
    <fs-crud ref="crudRef" v-bind="crudBinding">
      <template #actionbar-right>
        <ExportDropdown title="盾构机基础信息" :crud-binding="crudBinding" />
      </template>
    </fs-crud>

    <!-- 刀位信息全屏对话框 -->
    <el-dialog
      v-model="cutterPositionDialogVisible"
      title="刀位信息管理"
      fullscreen
      :close-on-click-modal="false"
      class="cutter-position-dialog"
    >
      <CutterPositionDetail
        v-if="cutterPositionDialogVisible && currentShieldMachine"
        :shield-machine="currentShieldMachine"
        @close="cutterPositionDialogVisible = false"
      />
    </el-dialog>
  </fs-page>
</template>

<script lang="ts" setup name="ShieldMachineBasicInfo">
import { ref, onMounted } from 'vue';
import { useExpose, useCrud } from '@fast-crud/fast-crud';
import { createCrudOptions } from './crud';
import CutterPositionDetail from './components/CutterPositionDetail.vue';
import ExportDropdown from '/@/views/shield/components/ExportDropdown.vue';

const crudRef = ref();
const crudBinding = ref();
const { crudExpose } = useExpose({ crudRef, crudBinding });
const { crudOptions, cutterPositionDialogVisible, currentShieldMachine } = createCrudOptions({ crudExpose });
const { resetCrudOptions } = useCrud({ crudExpose, crudOptions });

onMounted(() => {
  crudExpose.doRefresh();
});
</script>

<style>
.cutter-position-dialog .el-dialog__body {
  padding: 0;
  height: calc(100vh - 60px);
}
</style>
