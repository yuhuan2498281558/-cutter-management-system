<template>
  <el-dialog
    v-model="visible" title="确认开仓汇总" width="min(560px, calc(100vw - 32px))" top="5vh" destroy-on-close
    class="opening-summary-dialog"
    :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving"
    :before-close="beforeClose"
  >
    <dl class="opening-context" aria-label="当前开仓">
      <div><dt>开仓编号</dt><dd>{{ opening?.warehouse_id || '-' }}</dd></div>
      <div><dt>换刀环号</dt><dd>{{ opening?.ring_no ?? '-' }}</dd></div>
    </dl>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="检查数和更换数已按移动端明细自动统计，可人工校正；确认后移动端将锁定，如需修改须先撤回确认。"
      class="summary-hint"
    />
    <el-alert v-if="submitError" :title="submitError" type="error" :closable="false" show-icon class="summary-hint" />
    <el-form ref="formRef" :model="form" :rules="rules" :disabled="saving || !opening?.id" label-width="170px">
      <fieldset class="summary-section">
        <legend>作业时长 <span>人工补录，单位：小时</span></legend>
      <el-form-item label="开仓持续时间（小时）" prop="opening_duration">
        <el-input-number v-model="form.opening_duration" :min="0" :precision="2" controls-position="right" />
      </el-form-item>
      <el-form-item label="换刀总时长（小时）" prop="tool_change_duration">
        <el-input-number v-model="form.tool_change_duration" :min="0" :precision="2" controls-position="right" />
      </el-form-item>
      </fieldset>
      <fieldset class="summary-section">
        <legend>刀具数量 <span>已自动带入，可人工校正</span></legend>
      <el-form-item label="检查刀具数量（把）" prop="checked_tool_count">
        <el-input-number v-model="form.checked_tool_count" :min="0" :precision="0" controls-position="right" />
      </el-form-item>
      <el-form-item label="更换刀具数量（把）" prop="replaced_tool_count">
        <el-input-number v-model="form.replaced_tool_count" :min="0" :precision="0" controls-position="right" />
      </el-form-item>
      </fieldset>
      <el-form-item label="本次使用距离（m）">
        <el-input :model-value="opening?.usage_distance ?? '-'" disabled class="summary-distance" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button :disabled="saving" @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="saving || !opening?.id" @click="submit">确认并进入补录</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, reactive, ref, watch } from 'vue';
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
const submitError = ref('');
let session = 0;
let disposed = false;
const form = reactive<api.OpeningCompletionPayload>({
  opening_duration: undefined as unknown as number,
  tool_change_duration: undefined as unknown as number,
  checked_tool_count: 0,
  replaced_tool_count: 0,
});

const visible = computed({
  get: () => props.modelValue,
  set: value => {
    if (!saving.value) emit('update:modelValue', value);
  },
});
const beforeClose = (done: () => void) => {
  if (!saving.value) done();
};
watch(() => [props.modelValue, props.opening?.id] as const, ([value]) => {
  const currentSession = ++session;
  saving.value = false;
  submitError.value = '';
  if (value && props.opening) {
    form.opening_duration = props.opening.opening_duration as number;
    form.tool_change_duration = props.opening.tool_change_duration as number;
    form.checked_tool_count = props.opening.checked_tool_count ?? 0;
    form.replaced_tool_count = props.opening.replaced_tool_count ?? 0;
    nextTick(() => {
      if (!disposed && currentSession === session) formRef.value?.clearValidate();
    });
  }
}, { immediate: true, flush: 'sync' });
onUnmounted(() => {
  disposed = true;
  session++;
});

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
  if (disposed || saving.value || !visible.value || !props.opening?.id || !formRef.value) return;
  const currentSession = session;
  const openingId = props.opening.id;
  const isCurrent = () => !disposed && currentSession === session && props.modelValue && props.opening?.id === openingId;
  // Lock before async validation; the button's next render alone cannot stop rapid clicks.
  saving.value = true;
  submitError.value = '';
  try {
    let valid = false;
    try {
      valid = await formRef.value.validate();
    } catch {
      // Element Plus displays field errors; invalid input is not a network failure.
      return;
    }
    if (!valid || !isCurrent()) return;
    const response = await api.CompleteSummary(openingId, { ...form });
    if (!isCurrent()) return;
    if (!response.data || response.data.id !== openingId) {
      submitError.value = '确认结果与当前开仓不一致，请关闭弹窗并刷新列表核对状态。';
      return;
    }
    ElMessage.success(response.msg || '开仓汇总信息已保存');
    saving.value = false;
    emit('update:modelValue', false);
    emit('saved', response.data as WarehouseOpeningBasicInfoType);
  } catch {
    if (isCurrent()) submitError.value = '未能获取确认结果，填写内容已保留。请核对网络及列表中的汇总状态后再重试。';
  } finally {
    if (currentSession === session && !disposed) saving.value = false;
  }
};
</script>

<style>
.opening-summary-dialog { display: flex; flex-direction: column; max-height: 90vh; max-height: 90dvh; margin-bottom: 0; }
.opening-summary-dialog .el-dialog__body { min-height: 0; overflow-y: auto; padding-top: 12px; padding-bottom: 8px; }
.opening-summary-dialog .el-dialog__header,
.opening-summary-dialog .el-dialog__footer { flex-shrink: 0; }
.opening-summary-dialog .el-dialog__footer { border-top: 1px solid var(--el-border-color-lighter); padding-top: 14px; }
@media (max-width: 480px) {
  .opening-summary-dialog .el-form-item { display: block; }
  .opening-summary-dialog .el-form-item__label { width: auto !important; height: auto; line-height: 22px; padding-bottom: 6px; }
}
</style>

<style scoped>
.opening-context { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; margin: 0 0 12px; padding: 10px 12px; background: var(--el-fill-color-light); border-radius: 4px; font-size: 13px; line-height: 22px; }
.opening-context > div { display: grid; grid-template-columns: 64px minmax(0, 1fr); align-items: baseline; gap: 8px; min-width: 0; }
.opening-context dt { color: var(--el-text-color-regular); }
.opening-context dd { margin: 0; font-weight: 600; color: var(--el-text-color-primary); overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.summary-section { min-width: 0; border: 0; padding: 0; margin: 0 0 8px; }
.summary-section legend { width: 100%; margin-bottom: 12px; padding: 0; font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); }
.summary-section legend span { margin-left: 8px; font-size: 12px; font-weight: 400; color: var(--el-text-color-secondary); }
@media (max-width: 480px) {
  .opening-context { grid-template-columns: minmax(0, 1fr); gap: 6px; }
  .summary-section legend span { display: block; margin: 4px 0 0; }
}
.summary-distance { --el-disabled-text-color: var(--el-text-color-regular); }
.summary-distance :deep(.el-input__inner) { text-align: center; font-variant-numeric: tabular-nums; }
.summary-hint {
  margin-bottom: 12px;
}

:deep(.el-input-number),
:deep(.el-input) {
  width: 100%;
}
</style>
