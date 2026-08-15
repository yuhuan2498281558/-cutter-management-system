<template>
	<fs-page>
		<template #header>
			<el-page-header @back="goBack" :content="`刀具成本信息 - ${toolInfoName}`" />
		</template>
		<fs-crud ref="crudRef" v-bind="crudBinding">
			<template #actionbar-right>
				<ExportDropdown title="刀具成本明细" :crud-binding="crudBinding" />
			</template>
		</fs-crud>
	</fs-page>
</template>

<script lang="ts" setup name="ShieldToolCost">
import { ref, onMounted } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useExpose, useCrud } from '@fast-crud/fast-crud';
import { createCrudOptions } from './crud';
import ExportDropdown from '/@/views/shield/components/ExportDropdown.vue';

const router = useRouter();
const route = useRoute();
const toolInfoName = ref(route.query.tool_info_name as string || '未知刀具');

const crudRef = ref();
const crudBinding = ref();
const { crudExpose } = useExpose({ crudRef, crudBinding });
const { crudOptions } = createCrudOptions({ crudExpose });
const { resetCrudOptions } = useCrud({ crudExpose, crudOptions });

const goBack = () => {
	router.back();
};

onMounted(() => {
	resetCrudOptions(crudOptions);
	crudExpose.doRefresh();
});
</script>
