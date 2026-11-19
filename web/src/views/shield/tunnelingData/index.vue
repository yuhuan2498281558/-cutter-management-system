<template>
	<fs-page>
		<fs-crud ref="crudRef" v-bind="crudBinding">
			<template #actionbar-right>
				<el-button type="primary" icon="Upload" @click="openImport">导入CSV</el-button>
				<ExportDropdown title="掘进动态数据" :crud-binding="crudBinding" />
			</template>
		</fs-crud>

		<el-dialog v-model="importVisible" title="导入掘进 CSV" width="420px" append-to-body>
			<el-form label-width="72px">
				<el-form-item label="项目" required>
					<el-select v-model="importForm.project" placeholder="选择项目" filterable class="import-select">
						<el-option v-for="item in projectOptions" :key="item.id" :label="item.project_name" :value="item.id" />
					</el-select>
				</el-form-item>
				<el-form-item label="盾构机" required>
					<el-select v-model="importForm.shield_machine" placeholder="选择盾构机" filterable class="import-select">
						<el-option v-for="item in machineOptions" :key="item.id" :label="item.shield_model" :value="item.id" />
					</el-select>
				</el-form-item>
			</el-form>
			<template #footer>
				<el-button :disabled="importing" @click="importVisible = false">取消</el-button>
				<el-upload class="import-upload" accept=".csv" :show-file-list="false" :disabled="importing" :before-upload="handleBeforeUpload">
					<el-button type="primary" :loading="importing">选择文件并导入</el-button>
				</el-upload>
			</template>
		</el-dialog>
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

const importVisible = ref(false);
const importForm = reactive({
	project: undefined as number | undefined,
	shield_machine: undefined as number | undefined,
});
const projectOptions = ref<any[]>([]);
const machineOptions = ref<any[]>([]);
const importing = ref(false);

onMounted(() => {
	crudExpose.doRefresh();
});

async function loadOptions() {
	try {
		const [projectRes, machineRes] = await Promise.all([
			request({ url: '/api/shield/project/', method: 'get', params: { limit: 10000 } }),
			request({ url: '/api/shield/shield_machine_basic_info/', method: 'get', params: { limit: 10000 } }),
		]);
		const projectData = projectRes?.data?.results ?? projectRes?.data ?? [];
		const machineData = machineRes?.data?.results ?? machineRes?.data ?? [];
		projectOptions.value = Array.isArray(projectData) ? projectData : [];
		machineOptions.value = Array.isArray(machineData) ? machineData : [];
	} catch {
		// 请求层已弹出错误提示，这里只防止未处理的 Promise 拒绝
	}
}

// 导入目标默认取上方查询条件里选的项目和盾构机；只有一个可选时直接选上
async function openImport() {
	importVisible.value = true;
	if (!projectOptions.value.length || !machineOptions.value.length) await loadOptions();
	const search = crudExpose.getSearchFormData?.() || {};
	importForm.project = search.project ?? importForm.project ?? (projectOptions.value.length === 1 ? projectOptions.value[0].id : undefined);
	importForm.shield_machine = search.shield_machine ?? importForm.shield_machine ?? (machineOptions.value.length === 1 ? machineOptions.value[0].id : undefined);
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

	importing.value = true;
	try {
		const response: any = await ImportCsv(formData);
		ElMessage.success(response?.msg || '导入成功');
		importVisible.value = false;
		crudExpose.doRefresh();
	} catch (error: any) {
		ElMessage.error(error?.msg || error?.response?.data?.msg || '导入失败，请检查CSV格式');
	} finally {
		importing.value = false;
	}
	return false;
}
</script>

<style scoped>
.import-select {
	width: 100%;
}

.import-upload {
	display: inline-block;
	margin-left: 12px;
}
</style>
