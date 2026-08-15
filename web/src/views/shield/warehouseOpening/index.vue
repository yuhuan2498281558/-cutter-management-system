<template>
  <fs-page>
    <fs-crud ref="crudRef" v-bind="crudBinding">
      <template #actionbar-right>
        <ExportDropdown title="开仓明细" :crud-binding="crudBinding" />
      </template>
    </fs-crud>
  </fs-page>
</template>

<script lang="ts" setup name="ShieldWarehouseOpening">
import { ref, onMounted } from 'vue';
import { useExpose, useCrud } from '@fast-crud/fast-crud';
import { createCrudOptions } from './crud';
import { request } from '/@/utils/service';
import ExportDropdown from '/@/views/shield/components/ExportDropdown.vue';

const crudRef = ref();
const crudBinding = ref();
const { crudExpose } = useExpose({ crudRef, crudBinding });

// createCrudOptions 只调用一次（setup 上下文），保证 useRouter() 正常
const { crudOptions } = createCrudOptions({
  crudExpose,
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
