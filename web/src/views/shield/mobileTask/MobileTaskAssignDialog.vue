<template>
  <el-dialog v-model="visible" title="分配录入任务" width="720px" :close-on-click-modal="false" @closed="resetForm">
    <div v-if="warehouse" class="assign-context">
      <span>开仓编号：{{ warehouse.warehouse_id || warehouse.warehouse_code || warehouse.id }}</span>
      <span>环号：{{ warehouse.ring_no || '-' }}</span>
      <span>项目：{{ warehouse.project_name || '-' }}</span>
    </div>

    <el-form ref="formRef" :model="form" label-width="96px" v-loading="loading">
      <el-form-item label="录入员" prop="recorder" :rules="[{ required: true, message: '请选择录入员' }]">
        <el-select v-model="form.recorder" placeholder="请选择录入员" filterable style="width: 100%">
          <el-option v-for="item in recorders" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>

      <el-form-item label="刀具类型" prop="toolType" :rules="[{ required: true, message: '请选择刀具类型' }]">
        <el-select v-model="form.toolType" placeholder="请选择刀具类型" style="width: 100%" @change="onToolTypeChange">
          <el-option
            v-for="item in toolTypes"
            :key="item.value"
            :label="`${item.label}（${typePositionCount(item.value)}个）`"
            :value="item.value"
          />
        </el-select>
      </el-form-item>

      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="起始刀位" prop="startPosition" :rules="[{ required: true, message: '请选择起始刀位' }]">
            <el-select v-model="form.startPosition" placeholder="请选择" filterable style="width: 100%" :disabled="!form.toolType" @change="onStartChange">
              <el-option v-for="item in filteredPositions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="结束刀位" prop="endPosition" :rules="[{ required: true, message: '请选择结束刀位' }]">
            <el-select v-model="form.endPosition" placeholder="请选择" filterable style="width: 100%" :disabled="!form.toolType">
              <el-option v-for="item in filteredPositions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
    </el-form>

    <div v-if="form.toolType" class="assign-summary">
      <template v-if="selectedPositions.length">
        已选 {{ selectedPositions.length }} 个刀位：{{ selectedPreview }}
      </template>
      <template v-else>
        当前刀具类型下没有可分配刀位，或刀位范围未选完整。
      </template>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">创建任务</el-button>
    </template>
  </el-dialog>
</template>

<script lang="ts" setup>
import { computed, reactive, ref } from 'vue';
import type { FormInstance } from 'element-plus';
import { ElMessage } from 'element-plus';
import { AddObj, GetAssignOptions } from './api';

type SelectOption = {
  value: string | number;
  label: string;
};

type PositionOption = SelectOption & {
  cutter_position_no: string;
  tool_parent_type: string;
  tool_parent_type_display: string;
  tool_type_name: string;
};

const emit = defineEmits<{ (event: 'created'): void }>();

const visible = ref(false);
const loading = ref(false);
const submitting = ref(false);
const formRef = ref<FormInstance>();
const warehouse = ref<any>(null);
const recorders = ref<SelectOption[]>([]);
const toolTypes = ref<SelectOption[]>([]);
const positions = ref<PositionOption[]>([]);
const form = reactive({
  recorder: undefined as number | string | undefined,
  toolType: '',
  startPosition: '',
  endPosition: '',
});

const filteredPositions = computed(() => positions.value.filter((item) => item.tool_parent_type === form.toolType));

const selectedPositions = computed(() => {
  const start = filteredPositions.value.findIndex((item) => item.value === form.startPosition);
  const end = filteredPositions.value.findIndex((item) => item.value === form.endPosition);
  if (start < 0 || end < 0 || end < start) return [];
  return filteredPositions.value.slice(start, end + 1);
});

const selectedPreview = computed(() => selectedPositions.value.map((item) => item.cutter_position_no).join('、'));

function resetForm() {
  form.recorder = undefined;
  form.toolType = '';
  form.startPosition = '';
  form.endPosition = '';
  formRef.value?.clearValidate();
}

function onToolTypeChange() {
  form.startPosition = '';
  form.endPosition = '';
}

function onStartChange() {
  const start = filteredPositions.value.findIndex((item) => item.value === form.startPosition);
  const end = filteredPositions.value.findIndex((item) => item.value === form.endPosition);
  if (end >= 0 && start >= 0 && end < start) {
    form.endPosition = '';
  }
}

function typePositionCount(type: string | number) {
  return positions.value.filter((item) => item.tool_parent_type === type).length;
}

async function loadOptions(warehouseId: string | number) {
  loading.value = true;
  try {
    const res: any = await GetAssignOptions(warehouseId);
    recorders.value = res.data?.recorders || [];
    toolTypes.value = res.data?.tool_types || [];
    positions.value = res.data?.positions || [];
  } finally {
    loading.value = false;
  }
}

async function open(row: any) {
  warehouse.value = row;
  visible.value = true;
  resetForm();
  await loadOptions(row.id);
}

async function submit() {
  await formRef.value?.validate();
  if (!warehouse.value) return;
  if (!selectedPositions.value.length) {
    ElMessage.warning('请选择有效的刀位范围');
    return;
  }

  submitting.value = true;
  try {
    await AddObj({
      warehouse: warehouse.value.id,
      recorder: form.recorder,
      scope_type: 'POSITION_LIST',
      tool_types: [form.toolType],
      position_nos: selectedPositions.value.map((item) => item.cutter_position_no),
      status: 'PENDING',
    } as any);
    ElMessage.success('录入任务已创建');
    visible.value = false;
    emit('created');
  } finally {
    submitting.value = false;
  }
}

defineExpose({ open });
</script>

<style scoped>
.assign-context {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  margin-bottom: 16px;
  color: #606266;
}

.assign-summary {
  min-height: 36px;
  margin-top: 4px;
  padding: 10px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  color: #303133;
  line-height: 1.5;
}
</style>
