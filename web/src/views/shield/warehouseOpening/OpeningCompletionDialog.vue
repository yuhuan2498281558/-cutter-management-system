<template>
  <el-dialog v-model="visible" title="确认开仓汇总" width="560px" destroy-on-close>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="检查数和更换数已按移动端明细自动统计，可人工校正；确认后移动端将锁定，如需修改须先撤回确认。"
      class="summary-hint"
    />
    <el-form ref="formRef" :model="form" :rules="rules" label-width="150px">
      <el-form-item label="开仓持续时间（小时）" prop="opening_duration">
        <el-input-number v-model="form.opening_duration" :min="0" :precision="2" controls-position="right" />
      </el-form-item>
      <el-form-item label="换刀总时长（小时）" prop="tool_change_duration">
        <el-input-number v-model="form.tool_change_duration" :min="0" :precision="2" controls-position="right" />
      </el-form-item>
      <el-form-item label="检查刀具数量（把）" prop="checked_tool_count">
        <el-input-number v-model="form.checked_tool_count" :min="0" :precision="0" controls-position="right" />
      </el-form-item>
      <el-form-item label="更换刀具数量（把）" prop="replaced_tool_count">
        <el-input-number v-model="form.replaced_tool_count" :min="0" :precision="0" controls-position="right" />
      </el-form-item>
      <el-form-item label="本次使用距离（m）">
        <el-input :model-value="opening?.usage_distance ?? '-'" disabled />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">确认并进入补录</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue';
import type { FormInstance, FormRules } from 'element-plus';
import { ElMessage } from 'element-plus';
import * as api from './api';
import type { WarehouseOpeningBasicInfoType } from './types';

const props = defineProps<{
  modelValue: boolean;
  opening: WarehouseOpeningBasicInfoType | null;
}>();
const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void;
  (event: 'saved', opening: WarehouseOpeningBasicInfoType): void;
}>();

const formRef = ref<FormInstance>();
const saving = ref(false);
const form = reactive<api.OpeningCompletionPayload>({
  opening_duration: undefined as unknown as number,
  tool_change_duration: undefined as unknown as number,
  checked_tool_count: 0,
  replaced_tool_count: 0,
});

const visible = ref(false);
watch(() => props.modelValue, (value) => {
  visible.value = value;
  if (value && props.opening) {
    form.opening_duration = props.opening.opening_duration as number;
    form.tool_change_duration = props.opening.tool_change_duration as number;
    form.checked_tool_count = props.opening.checked_tool_count ?? 0;
    form.replaced_tool_count = props.opening.replaced_tool_count ?? 0;
  }
}, { immediate: true });
watch(visible, value => emit('update:modelValue', value));

const requiredNumber = { required: true, message: '请填写该项', trigger: 'change' };
const rules: FormRules = {
  opening_duration: [requiredNumber],
  tool_change_duration: [requiredNumber],
  checked_tool_count: [requiredNumber],
  replaced_tool_count: [
    requiredNumber,
    {
      validator: (_rule, value, callback) => {
        if (value > form.checked_tool_count) callback(new Error('更换刀具数量不能大于检查刀具数量'));
        else callback();
      },
      trigger: 'change',
    },
  ],
};

const submit = async () => {
  if (!props.opening?.id || !formRef.value) return;
  await formRef.value.validate();
  saving.value = true;
  try {
    const response = await api.CompleteSummary(props.opening.id, { ...form });
    ElMessage.success(response.msg || '开仓汇总信息已保存');
    visible.value = false;
    emit('saved', response.data as WarehouseOpeningBasicInfoType);
  } finally {
    saving.value = false;
  }
};
</script>

<style scoped>
.summary-hint {
  margin-bottom: 20px;
}

:deep(.el-input-number),
:deep(.el-input) {
  width: 100%;
}
</style>
