<template>
	<fs-page>
		<div class="import-toolbar">
			<el-select v-model="importForm.project" placeholder="选择项目" clearable filterable class="toolbar-select">
				<el-option v-for="item in projectOptions" :key="item.id" :label="item.project_name" :value="item.id" />
			</el-select>
			<el-select v-model="importForm.shield_machine" placeholder="选择盾构机" clearable filterable class="toolbar-select">
				<el-option v-for="item in machineOptions" :key="item.id" :label="item.shield_model" :value="item.id" />
			</el-select>
			<el-upload accept=".csv" :show-file-list="false" :before-upload="handleBeforeUpload">
				<el-button type="primary" icon="Upload">导入CSV</el-button>
			</el-upload>
			<ExportDropdown title="掘进动态数据" :crud-binding="crudBinding" />
		</div>
		<fs-crud ref="crudRef" v-bind="crudBinding"></fs-crud>
	</fs-page>
</template>

<script lang="ts" setup name="ShieldTunnelingData">
import { reactive, ref, onMounted } from 'vue';
import { useExpose, useCrud } from '@fast-crud/fast-crud';
import { createCrudOptions } from './crud';
import { ElMessage } from 'element-plus';
import { request } from '/@/utils/service';
import { ImportCsv } from './api';
import ExportDropdown from '/@/views/shield/components/ExportDropdown.vue';

const crudRef = ref();
const crudBinding = ref();
const { crudExpose } = useExpose({ crudRef, crudBinding });
const { crudOptions } = createCrudOptions({ crudExpose });
useCrud({ crudExpose, crudOptions });

const importForm = reactive({
	project: undefined as number | undefined,
	shield_machine: undefined as number | undefined,
});
const projectOptions = ref<any[]>([]);
const machineOptions = ref<any[]>([]);

onMounted(() => {
	loadOptions();
	crudExpose.doRefresh();
});

async function loadOptions() {
	const [projectRes, machineRes] = await Promise.all([
		request({ url: '/api/shield/project/', method: 'get', params: { limit: 10000 } }),
		request({ url: '/api/shield/shield_machine_basic_info/', method: 'get', params: { limit: 10000 } }),
	]);
	const projectData = projectRes?.data?.results ?? projectRes?.data ?? [];
	const machineData = machineRes?.data?.results ?? machineRes?.data ?? [];
	projectOptions.value = Array.isArray(projectData) ? projectData : [];
	machineOptions.value = Array.isArray(machineData) ? machineData : [];
}

async function handleBeforeUpload(file: File) {
	if (!importForm.project || !importForm.shield_machine) {
		ElMessage.warning('请先选择项目和盾构机');
		return false;
	}

	const formData = new FormData();
	formData.append('file', file);
	formData.append('project', String(importForm.project));
	formData.append('shield_machine', String(importForm.shield_machine));

	try {
		const response: any = await ImportCsv(formData);
		ElMessage.success(response?.msg || '导入成功');
		crudExpose.doRefresh();
	} catch (error: any) {
		ElMessage.error(error?.msg || error?.response?.data?.msg || '导入失败，请检查CSV格式');
	}
	return false;
}
</script>

<style scoped>
.import-toolbar {
	display: flex;
	align-items: center;
	gap: 10px;
	margin-bottom: 10px;
}

.toolbar-select {
	width: 220px;
}
</style>
