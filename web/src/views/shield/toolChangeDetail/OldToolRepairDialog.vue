<template>
  <el-dialog v-model="visible" :title="readOnly ? '查看旧刀厂家返修信息' : '旧刀厂家返修补录'" width="min(820px, calc(100vw - 32px))" top="5vh" class="old-tool-repair-dialog" :close-on-click-modal="false" :close-on-press-escape="false" :show-close="!saving">
    <dl v-if="row" class="record-context" aria-label="当前旧刀">
      <div><dt>刀位</dt><dd>{{ row.cutter_position_no || '-' }}</dd></div>
      <div><dt>刀具类型</dt><dd>{{ row.tool_type_name || row.tool_parent_type || '-' }}</dd></div>
      <div><dt>旧刀编号</dt><dd>{{ form.old_tool_number || resolvedOldToolNumber || '待确认' }}</dd></div>
      <div><dt>返修状态</dt><dd><el-tag size="small" :type="inspectionStatusType">{{ inspectionStatusText }}</el-tag></dd></div>
    </dl>

    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon class="load-error">
      <el-button link type="primary" @click="retryLoad">重新加载</el-button>
    </el-alert>
    <el-form v-loading="loading" :model="form" :disabled="!canSave" label-width="132px" class="repair-form" :class="{ 'is-readonly': readOnly || isClosed }">
      <fieldset class="repair-section">
        <legend>照片资料</legend>
      <el-form-item label="旧刀磨损照片">
        <div class="photo-links">
          <button
            v-for="(photo, index) in existingPhotos"
            :key="photo.id"
            type="button"
            class="photo-preview-button"
            aria-haspopup="dialog"
            @click="previewPhoto(photo.url, photo.name || `照片${index + 1}`)"
          >照片{{ index + 1 }}</button>
          <span v-if="existingPhotos.length === 0" class="empty-text">暂无</span>
        </div>
        <el-upload
          v-if="!readOnly"
          :file-list="fileList"
          action="#"
          :auto-upload="false"
          :limit="remainingPhotoSlots"
          :disabled="!canSave || remainingPhotoSlots <= 0"
          accept="image/jpeg,image/jpg,image/png"
          :on-change="handlePhotoChange"
          :on-remove="handlePhotoRemove"
          :on-exceed="handlePhotoExceed"
          multiple
          class="photo-upload"
        >
          <el-button :disabled="availablePhotoSlots <= 0">补充照片</el-button>
          <template #tip>
            <div class="photo-upload-hint">
              <div>JPG / JPEG / PNG，单张不超过 30MB，合计最多 5 张。</div>
              <div role="status" aria-live="polite">已保存 {{ existingPhotos.length }} 张，待保存 {{ fileList.length }} 张，还可选择 {{ availablePhotoSlots }} 张。</div>
            </div>
          </template>
        </el-upload>
      </el-form-item>
      </fieldset>

      <template v-if="toolParentType === 'DISC'">
        <fieldset class="repair-section">
          <legend>刀圈与磨损</legend>
          <div class="repair-grid">
        <el-form-item label="刀圈磨损量">
          <el-input-number v-model="form.ring_wear_amount" :min="0" :precision="2" controls-position="right" />
        </el-form-item>
        <el-form-item label="偏磨量">
          <el-input-number v-model="form.bias_wear_amount" :min="0" :precision="2" controls-position="right" />
        </el-form-item>
        <el-form-item label="刀位轨迹">
          <el-tooltip :content="row?.trajectory?.source || '图纸依据'" placement="top">
            <el-input :model-value="trajectoryDisplay" readonly />
          </el-tooltip>
        </el-form-item>
        <el-form-item label="刀圈掉齿数量">
          <el-input-number v-model="form.ring_tooth_loss_count" :min="0" :precision="0" controls-position="right" />
        </el-form-item>
        <el-form-item label="刀圈损坏情况" class="wide-field">
          <el-select v-model="form.ring_damage" multiple clearable filterable placeholder="请选择" class="full-width">
            <el-option v-for="item in options.ring_damage" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="刀圈其他情况" class="wide-field">
          <el-input v-model="form.ring_other_condition" type="textarea" :rows="2" />
        </el-form-item>
          </div>
        </fieldset>
        <fieldset class="repair-section">
          <legend>轴承检测</legend>
          <div class="repair-grid">
        <el-form-item label="轴承是否失效">
          <el-select v-model="form.bearing_failed" clearable placeholder="请选择">
            <el-option label="是" :value="true" />
            <el-option label="否" :value="false" />
          </el-select>
        </el-form-item>
        <el-form-item label="轴承失效原因">
          <el-select v-model="form.bearing_failure_reasons" multiple clearable placeholder="请选择" class="full-width">
            <el-option v-for="item in options.bearing_failure_reasons" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="轴承其他情况" class="wide-field">
          <el-input v-model="form.bearing_other_condition" type="textarea" :rows="2" />
        </el-form-item>
          </div>
        </fieldset>
        <fieldset class="repair-section">
          <legend>刀毂检测</legend>
          <div class="repair-grid">
        <el-form-item label="刀毂是否损坏">
          <el-select v-model="form.hub_damaged" clearable placeholder="请选择">
            <el-option label="是" :value="true" />
            <el-option label="否" :value="false" />
          </el-select>
        </el-form-item>
        <el-form-item label="刀毂失效原因">
          <el-select v-model="form.hub_failure_reasons" multiple clearable placeholder="请选择" class="full-width">
            <el-option v-for="item in options.hub_failure_reasons" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="刀毂其他情况" class="wide-field">
          <el-input v-model="form.hub_other_condition" type="textarea" :rows="2" />
        </el-form-item>
          </div>
        </fieldset>
      </template>

      <template v-if="toolParentType === 'SCRAPER'">
        <fieldset class="repair-section">
          <legend>刮刀检测</legend>
          <div class="repair-grid">
        <el-form-item label="换下刀具磨损量">
          <el-input-number v-model="form.scraper_wear_amount" :min="0" :precision="2" controls-position="right" />
        </el-form-item>
        <el-form-item label="刀位轨迹">
          <el-tooltip :content="row?.trajectory?.source || '图纸依据'" placement="top">
            <el-input :model-value="trajectoryDisplay" readonly />
          </el-tooltip>
        </el-form-item>
        <el-form-item label="是否崩裂">
          <el-select v-model="form.scraper_chipped" clearable placeholder="请选择">
            <el-option label="是" :value="true" />
            <el-option label="否" :value="false" />
          </el-select>
        </el-form-item>
        <el-form-item label="是否断裂">
          <el-select v-model="form.scraper_broken" clearable placeholder="请选择">
            <el-option label="是" :value="true" />
            <el-option label="否" :value="false" />
          </el-select>
        </el-form-item>
        <el-form-item label="是否脱落">
          <el-select v-model="form.scraper_detached" clearable placeholder="请选择">
            <el-option label="是" :value="true" />
            <el-option label="否" :value="false" />
          </el-select>
        </el-form-item>
          </div>
        </fieldset>
      </template>

      <fieldset class="repair-section">
        <legend>处置与返修</legend>
        <div class="repair-grid">
      <el-form-item label="报废 / 可维修">
        <el-select v-model="form.disposition" clearable placeholder="请选择">
          <el-option v-for="item in options.old_tool_dispositions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="维修价格">
        <el-input-number v-model="form.repair_price" :min="0" :precision="2" controls-position="right" />
      </el-form-item>
      <el-form-item label="厂家返修结果" class="wide-field">
        <el-input v-model="form.repair_result" type="textarea" :rows="2" placeholder="请输入厂家返修结果" />
      </el-form-item>
      <el-form-item label="补充说明" class="wide-field">
        <el-input v-model="form.remark" type="textarea" :rows="2" />
      </el-form-item>
        </div>
      </fieldset>
    </el-form>

    <template #footer>
      <el-button :disabled="saving" @click="visible = false">取消</el-button>
      <template v-if="!readOnly && !isClosed">
        <el-button :loading="saving" :disabled="!canSave" @click="save('SAVE_DRAFT')">保存草稿</el-button>
        <el-button
          v-if="inspectionStatus === 'PENDING_VENDOR_FEEDBACK'"
          type="primary"
          :loading="saving"
          :disabled="!canSave"
          @click="save('CONFIRM')"
        >确认厂家反馈</el-button>
        <el-button
          v-else-if="inspectionStatus === 'CONFIRMED'"
          type="warning"
          :loading="saving"
          :disabled="!canSave"
          @click="save('CLOSE')"
        >完成归档</el-button>
      </template>
      <el-button v-else type="primary" @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="photoPreviewVisible" title="旧刀磨损照片" width="min(760px, calc(100vw - 32px))" top="5vh" :close-on-press-escape="true" append-to-body destroy-on-close>
    <PhotoPreview :src="photoPreviewUrl" :name="photoPreviewName" :active="photoPreviewVisible" />
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import type { UploadFile, UploadFiles, UploadUserFile } from 'element-plus';
import { GetOldToolRecord, GetToolChangeOptions, UpdateOldToolRecord } from './api';
import PhotoPreview from './PhotoPreview.vue';

const emit = defineEmits<{ (event: 'saved'): void }>();

const visible = ref(false);
const loading = ref(false);
const loaded = ref(false);
const loadError = ref('');
let loadVersion = 0;
const saving = ref(false);
const readOnly = ref(false);
const row = ref<any>(null);
const existingPhotos = ref<any[]>([]);
const resolvedOldToolNumber = ref('');
const inspectionStatus = ref('PENDING_VENDOR_FEEDBACK');
const fileList = ref<UploadUserFile[]>([]);
const photoPreviewVisible = ref(false);
const photoPreviewUrl = ref('');
const photoPreviewName = ref('旧刀磨损照片');
type FieldOption = { value: string; label: string };
const options = reactive<Record<'ring_damage' | 'bearing_failure_reasons' | 'hub_failure_reasons' | 'old_tool_dispositions', FieldOption[]>>({
  ring_damage: [], bearing_failure_reasons: [], hub_failure_reasons: [], old_tool_dispositions: [],
});

const form = reactive<any>({
  old_tool_number: '',
  ring_wear_amount: null,
  bias_wear_amount: null,
  ring_damage: [],
  ring_tooth_loss_count: null,
  ring_other_condition: '',
  bearing_failed: null,
  bearing_failure_reasons: [],
  bearing_other_condition: '',
  hub_damaged: null,
  hub_failure_reasons: [],
  hub_other_condition: '',
  disposition: '',
  scraper_wear_amount: null,
  scraper_chipped: null,
  scraper_broken: null,
  scraper_detached: null,
  repair_result: '',
  repair_price: null,
  remark: '',
});

const toolParentType = computed(() => row.value?.tool_parent_type || '');
const trajectoryDisplay = computed(() => row.value?.trajectory?.display || '待按最终图纸核对');
const remainingPhotoSlots = computed(() => Math.max(0, 5 - existingPhotos.value.length));
const availablePhotoSlots = computed(() => Math.max(0, remainingPhotoSlots.value - fileList.value.length));
const isClosed = computed(() => inspectionStatus.value === 'CLOSED');
const canSave = computed(() => visible.value && loaded.value && !loading.value && !saving.value && !readOnly.value && !isClosed.value);
const inspectionStatusText = computed(() => ({
  PENDING_VENDOR_FEEDBACK: '待厂家反馈',
  CONFIRMED: '厂家反馈已确认',
  CLOSED: '已归档',
} as Record<string, string>)[inspectionStatus.value] || inspectionStatus.value);
const inspectionStatusType = computed(() => ({
  PENDING_VENDOR_FEEDBACK: 'warning',
  CONFIRMED: 'success',
  CLOSED: 'info',
} as Record<string, string>)[inspectionStatus.value] || 'info');

function resetForm() {
  Object.assign(form, {
    old_tool_number: '', ring_wear_amount: null, bias_wear_amount: null, ring_damage: [],
    ring_tooth_loss_count: null, ring_other_condition: '', bearing_failed: null, bearing_failure_reasons: [],
    bearing_other_condition: '', hub_damaged: null, hub_failure_reasons: [], hub_other_condition: '', disposition: '',
    scraper_wear_amount: null, scraper_chipped: null, scraper_broken: null, scraper_detached: null,
    repair_result: '', repair_price: null, remark: '',
  });
  existingPhotos.value = [];
  resolvedOldToolNumber.value = '';
  inspectionStatus.value = 'PENDING_VENDOR_FEEDBACK';
  fileList.value = [];
}

function applyRecord(record: any) {
  if (!record) return;
  resolvedOldToolNumber.value = record.old_tool_number_display || record.confirmed_tool_number || record.suggested_tool_number || '';
  inspectionStatus.value = record.inspection_status || 'PENDING_VENDOR_FEEDBACK';
  Object.keys(form).forEach((key) => {
    if (record[key] !== undefined && record[key] !== null) form[key] = record[key];
  });
  form.ring_damage = record.ring_damage || [];
  form.bearing_failure_reasons = record.bearing_failure_reasons || [];
  form.hub_failure_reasons = record.hub_failure_reasons || [];
  existingPhotos.value = record.photos || [];
}

function invalidateLoad() {
  loadVersion += 1;
  loaded.value = false;
  loading.value = false;
}

watch(visible, value => {
  if (!value) invalidateLoad();
}, { flush: 'sync' });
onUnmounted(invalidateLoad);

async function open(input: any, openOptions: { readOnly?: boolean } = {}) {
  if (saving.value) return;
  const version = ++loadVersion;
  row.value = input;
  readOnly.value = openOptions.readOnly === true;
  resetForm();
  loaded.value = false;
  loadError.value = '';
  Object.keys(options).forEach(key => { options[key as keyof typeof options] = []; });
  visible.value = true;
  loading.value = true;
  try {
    const [recordRes, optionRes] = await Promise.all([
      GetOldToolRecord(input.id),
      GetToolChangeOptions(),
    ]);
    if (version !== loadVersion || !visible.value) return;
    if (!recordRes.data || !optionRes.data || Object.keys(options).some(key => !Array.isArray(optionRes.data[key]))) {
      throw new Error('返修信息或选项数据不完整');
    }
    row.value = { ...input, trajectory: recordRes.data.trajectory ?? input.trajectory ?? null };
    applyRecord(recordRes.data?.old_tool_record_data);
    Object.keys(options).forEach(key => {
      options[key as keyof typeof options] = optionRes.data[key];
    });
    loaded.value = true;
  } catch {
    if (version === loadVersion && visible.value) {
      loadError.value = '返修信息加载失败，暂不能保存，请重新加载。';
    }
  } finally {
    if (version === loadVersion) loading.value = false;
  }
}

function retryLoad() {
  if (row.value && !loading.value && !saving.value) {
    return open(row.value, { readOnly: readOnly.value });
  }
}

function appendValue(data: FormData, key: string, value: any) {
  if (Array.isArray(value)) {
    data.append(key, JSON.stringify(value));
  } else if (value !== undefined && value !== null) {
    data.append(key, String(value));
  }
}

function photoValidationError(file: UploadUserFile) {
  if (!file.raw) return '无法读取照片，请重新选择';
  if (!['image/jpeg', 'image/jpg', 'image/png'].includes(file.raw.type)) return '仅支持 JPG / JPEG / PNG';
  if (file.raw.size > 30 * 1024 * 1024) return '单张照片不能超过 30MB';
  return '';
}

function handlePhotoChange(file: UploadFile, files: UploadFiles) {
  if (!canSave.value) return;
  // Keep the accepted list controlled: the upload's delayed model update must
  // not restore a rejected file after this synchronous change callback.
  fileList.value = files.filter(item => !photoValidationError(item));
  const error = photoValidationError(file);
  if (error) ElMessage.warning(`${file.name || '所选照片'}未加入：${error}`);
}

function handlePhotoRemove(_file: UploadFile, files: UploadFiles) {
  if (canSave.value) fileList.value = files.filter(item => !photoValidationError(item));
}

function handlePhotoExceed() {
  if (!canSave.value) return;
  ElMessage.warning(`照片合计最多 5 张，已保存 ${existingPhotos.value.length} 张、待保存 ${fileList.value.length} 张，本次最多再选 ${availablePhotoSlots.value} 张。请减少选择数量。`);
}

async function save(workflowAction: 'SAVE_DRAFT' | 'CONFIRM' | 'CLOSE') {
  if (!row.value || !canSave.value) return;
  if (fileList.value.length > remainingPhotoSlots.value) {
    handlePhotoExceed();
    return;
  }
  const invalidPhoto = fileList.value.find(item => photoValidationError(item));
  if (invalidPhoto) {
    ElMessage.warning(`${invalidPhoto.name || '所选照片'}：${photoValidationError(invalidPhoto)}，请移除后重新选择`);
    return;
  }
  if (workflowAction !== 'SAVE_DRAFT' && !form.disposition) {
    ElMessage.warning('请先选择旧刀处置结果');
    return;
  }
  if (workflowAction === 'CLOSE' && form.disposition === 'REPAIRABLE' && !String(form.repair_result || '').trim()) {
    ElMessage.warning('可维修旧刀归档前必须填写厂家返修结果');
    return;
  }
  const version = loadVersion;
  const recordId = row.value.id;
  saving.value = true;
  try {
    if (workflowAction === 'CLOSE') {
      await ElMessageBox.confirm('归档后将不能继续修改该旧刀返修信息，是否继续？', '完成归档', {
        confirmButtonText: '确认归档',
        cancelButtonText: '取消',
        type: 'warning',
      });
    }
    if (version !== loadVersion || !visible.value) return;
    const data = new FormData();
    data.append('workflow_action', workflowAction);
    Object.entries(form).forEach(([key, value]) => appendValue(data, key, value));
    fileList.value.forEach((item) => {
      if (item.raw) data.append('photos', item.raw);
    });
    const response: any = await UpdateOldToolRecord(recordId, data);
    if (version !== loadVersion || !visible.value) return;
    ElMessage.success(response.msg || (workflowAction === 'SAVE_DRAFT' ? '草稿已保存' : workflowAction === 'CONFIRM' ? '厂家反馈已确认' : '旧刀返修记录已归档'));
    visible.value = false;
    emit('saved');
  } catch (error: any) {
    if (error !== 'cancel' && error !== 'close' && version === loadVersion && visible.value) {
      ElMessage.error('保存未完成，已保留填写内容，请确认后重试');
    }
  } finally {
    saving.value = false;
  }
}

function previewPhoto(url: string, name = '旧刀磨损照片') {
  if (!url) return;
  photoPreviewUrl.value = url;
  photoPreviewName.value = name;
  photoPreviewVisible.value = true;
}

defineExpose({ open });
</script>

<style>
/* Dialog content is teleported; keep these rules namespaced to this dialog. */
.old-tool-repair-dialog { display: flex; flex-direction: column; max-height: 90vh; max-height: 90dvh; margin-bottom: 0; }
.old-tool-repair-dialog .el-dialog__body { min-height: 0; overflow-y: auto; padding-top: 12px; padding-bottom: 4px; }
.old-tool-repair-dialog .el-dialog__header,
.old-tool-repair-dialog .el-dialog__footer { flex-shrink: 0; }
.old-tool-repair-dialog .el-dialog__footer { border-top: 1px solid var(--el-border-color-lighter); padding-top: 14px; display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.old-tool-repair-dialog .el-dialog__footer .el-button + .el-button { margin-left: 0; }
@media (max-width: 480px) {
  .old-tool-repair-dialog .el-form-item { display: block; }
  .old-tool-repair-dialog .el-form-item__label { width: auto !important; height: auto; line-height: 22px; padding-bottom: 6px; }
}
</style>

<style scoped>
.record-context { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 20px; margin: 0 0 14px; padding: 12px; background: var(--el-fill-color-light); border-radius: 4px; font-size: 13px; line-height: 1.6; }
.record-context > div { display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 8px; align-items: baseline; min-width: 0; }
.record-context dt { color: var(--el-text-color-regular); }
.record-context dd { margin: 0; min-width: 0; color: var(--el-text-color-primary); overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.load-error { margin-bottom: 12px; }
.repair-section { min-width: 0; border: 0; padding: 0; margin: 0 0 6px; }
.repair-section legend { width: 100%; padding: 0 0 8px; margin-bottom: 12px; border-bottom: 1px solid var(--el-border-color-lighter); font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); }
.repair-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.wide-field { grid-column: 1 / -1; }
.repair-form :deep(.el-input-number), .repair-form :deep(.el-select) { width: 100%; }
.repair-form :deep(.el-form-item__content) { min-width: 0; }
.repair-form.is-readonly { --el-disabled-text-color: var(--el-text-color-regular); }
.repair-form.is-readonly :deep(.el-select__wrapper.is-disabled .el-select__selected-item:not(.is-transparent)),
.repair-form.is-readonly :deep(.el-select__wrapper.is-disabled .el-tag) { color: var(--el-text-color-regular); }
.repair-form.is-readonly :deep(.el-select__selected-item.is-transparent) { color: var(--el-text-color-placeholder); }
.repair-form.is-readonly :deep(.el-input__inner::placeholder),
.repair-form.is-readonly :deep(.el-textarea__inner::placeholder) { color: var(--el-text-color-placeholder); -webkit-text-fill-color: var(--el-text-color-placeholder); }
@media (max-width: 640px) {
  .repair-grid, .record-context { grid-template-columns: minmax(0, 1fr); }
}
.full-width { width: 100%; }
.photo-links { display: flex; flex-wrap: wrap; gap: 12px; margin-right: 8px; margin-bottom: 8px; }
.photo-preview-button { max-width: 100%; min-height: 24px; padding: 1px 0; border: 0; border-radius: 2px; background: transparent; color: color-mix(in srgb, var(--el-color-primary) 60%, var(--el-text-color-primary)); font: inherit; line-height: 1.5; text-align: left; white-space: normal; overflow-wrap: anywhere; cursor: pointer; }
.photo-preview-button:hover { text-decoration: underline; text-underline-offset: 3px; }
.photo-preview-button:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.photo-upload { display: block; width: 100%; min-width: 0; }
.photo-upload-hint { margin-top: 6px; color: var(--el-text-color-regular); font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.empty-text { color: #909399; }
</style>
