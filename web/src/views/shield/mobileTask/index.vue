<template>
  <fs-page>
    <fs-crud ref="crudRef" v-bind="crudBinding" />
    <MobileTaskApprovalDialog ref="approvalDialogRef" @approved="crudExpose.doRefresh()" />
  </fs-page>
</template>

<script lang="ts" setup name="ShieldMobileTask">
import { ref, onMounted } from 'vue';
import { useExpose, useCrud } from '@fast-crud/fast-crud';
import { createCrudOptions } from './crud';
import MobileTaskApprovalDialog from './MobileTaskApprovalDialog.vue';

const crudRef = ref();
const crudBinding = ref();
const approvalDialogRef = ref();
const { crudExpose } = useExpose({ crudRef, crudBinding });
const { crudOptions } = createCrudOptions({
  crudExpose,
  openApproval: (row: any) => approvalDialogRef.value?.open(row),
});
useCrud({ crudExpose, crudOptions });

onMounted(() => {
  crudExpose.doRefresh();
});
</script>
