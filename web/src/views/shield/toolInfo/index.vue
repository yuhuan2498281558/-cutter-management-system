<template>
  <fs-page>
    <fs-crud ref="crudRef" v-bind="crudBinding">
      <template #actionbar-right>
        <ExportDropdown title="刀具明细" :crud-binding="crudBinding" />
      </template>
    </fs-crud>
  </fs-page>
</template>

<script lang="ts" setup name="ShieldToolInfo">
import { ref, onMounted } from 'vue';
import { useExpose, useCrud } from '@fast-crud/fast-crud';
import { createCrudOptions } from './crud';
import ExportDropdown from '/@/views/shield/components/ExportDropdown.vue';

const crudRef = ref();
const crudBinding = ref();
const { crudExpose } = useExpose({ crudRef, crudBinding });
const { crudOptions } = createCrudOptions({ crudExpose });
const { resetCrudOptions } = useCrud({ crudExpose, crudOptions });

onMounted(() => {
  crudExpose.doRefresh();
});
</script>
