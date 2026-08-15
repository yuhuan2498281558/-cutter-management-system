<template>
  <div class="mobile-page">
    <van-nav-bar title="刀位录入" left-arrow fixed placeholder @click-left="goBack" />
    <div v-if="task" class="summary">
      <div class="summary-head">
        <div>
          <div class="summary-title">{{ task.project_name }} · 第{{ task.ring_no }}环</div>
          <div class="summary-meta">{{ task.warehouse_id_name }} / {{ task.shield_machine }}</div>
        </div>
        <van-button
          class="summary-toggle"
          size="small"
          plain
          :icon="summaryCollapsed ? 'arrow-down' : 'arrow-up'"
          @click.stop="summaryCollapsed = !summaryCollapsed"
        >{{ summaryCollapsed ? '展开概况' : '收起概况' }}</van-button>
      </div>
      <div v-if="!summaryCollapsed" class="summary-extra">
        <div class="summary-meta" v-if="task.recorder_name">现场录入：{{ task.recorder_name }}</div>
        <div v-if="task.opening_info" class="opening-info">
          <span v-if="task.opening_info.tool_change_date">换刀日期：{{ task.opening_info.tool_change_date }}</span>
          <span v-if="task.opening_info.tool_change_duration !== null && task.opening_info.tool_change_duration !== undefined">换刀总时长：{{ task.opening_info.tool_change_duration }} 小时</span>
          <span v-if="task.opening_info.tool_change_ring_no">换刀环号：{{ task.opening_info.tool_change_ring_no }}</span>
          <span v-if="task.opening_info.last_tool_change_ring_no">上次换刀环号：{{ task.opening_info.last_tool_change_ring_no }}</span>
          <span v-if="task.opening_info.usage_distance !== null && task.opening_info.usage_distance !== undefined">本次使用距离：{{ task.opening_info.usage_distance }} m</span>
        </div>
      </div>
      <van-progress :percentage="progressPercent" stroke-width="6" />
      <div class="summary-meta">已保存 {{ savedCount }}/{{ details.length }}，换刀 {{ replacedCount }}，缺照片 {{ missingPhotoCount }}</div>
    </div>

    <van-search v-model="keyword" placeholder="搜索刀位号，如 G3R、46" />
    <div class="filters">
      <van-dropdown-menu>
        <van-dropdown-item v-model="statusFilter" :options="statusOptions" />
        <van-dropdown-item v-model="typeFilter" :options="typeOptions" />
      </van-dropdown-menu>
    </div>

    <van-pull-refresh v-model="refreshing" class="position-refresh" @refresh="loadTask">
      <van-list>
        <div v-for="detail in filteredDetails" :key="detail.id" class="position-card" @click="openEditor(detail)">
          <div class="position-row">
            <div class="position-no">{{ detail.cutter_position_no }}</div>
            <div class="position-tags">
              <van-tag v-if="detail.is_replaced" type="danger">已换刀</van-tag>
              <van-tag v-else-if="detail.is_checked" type="success">未换刀</van-tag>
              <van-tag v-else plain>未交互</van-tag>
            </div>
          </div>
          <div class="position-meta">{{ detail.tool_type_name || detail.tool_parent_type || '-' }}</div>
          <div class="position-track">
            <span class="track-label">刀位轨迹</span>
            <span :class="detail.trajectory?.status === 'CONFIRMED' ? 'track-value' : 'track-pending'">
              {{ detail.trajectory?.display || '待按最终图纸核对' }}
            </span>
          </div>
          <div v-if="detail.new_tool_uid" class="position-meta">新刀：{{ detail.new_tool_uid }}</div>
          <div v-if="detail.is_replaced && (!detail.old_photos || detail.old_photos.length === 0)" class="missing">缺旧刀照片</div>
        </div>
      </van-list>
    </van-pull-refresh>

    <div class="bottom-bar">
      <van-button block type="primary" :disabled="!task || readonly" @click="submitTask">提交任务</van-button>
    </div>

    <van-popup v-model:show="editorVisible" position="bottom" round :style="{ height: '88vh' }">
      <div v-if="current" class="editor">
        <div class="editor-header">
          <div class="editor-header-main">
            <van-button size="small" plain icon="cross" @click="closeEditor">关闭</van-button>
            <div class="editor-heading">
              <div class="editor-title">{{ current.cutter_position_no }}</div>
              <div class="editor-subtitle">{{ current.tool_type_name || current.tool_parent_type || '-' }}</div>
              <div class="editor-track">{{ current.trajectory?.display || '待按最终图纸核对' }}</div>
            </div>
            <van-tag :type="current.is_checked ? 'success' : 'primary'">{{ current.is_checked ? '已记录' : '待检查' }}</van-tag>
          </div>
          <div class="editor-nav">
            <van-button size="small" plain @click="move(-1)">上一刀</van-button>
            <span>录入完成后可关闭返回刀位列表</span>
            <van-button size="small" plain @click="move(1)">下一刀</van-button>
          </div>
          <!-- 保留一个独立的标题块，避免窄屏上操作按钮和刀位编号挤在同一行。 -->
          <div class="sr-only">{{ current.cutter_position_no }}</div>
        </div>

        <van-form @submit="saveCurrent">
          <van-cell-group inset>
            <van-field name="switch" label="是否换刀">
              <template #input>
                <van-switch v-model="form.is_replaced" :disabled="readonly" />
              </template>
            </van-field>
            <template v-if="form.is_replaced">
              <van-field v-model="form.tool_info_label" label="新刀类型" readonly placeholder="默认使用刀位绑定类型" />
              <van-field
                v-model="form.tool_cost_label"
                label="新刀成本库"
                readonly
                is-link
                :disabled="readonly || costPickerColumns.length === 0"
                :placeholder="costPickerColumns.length ? '请选择厂家 / 品牌 / 价格' : '当前类型暂无成本库记录'"
                @click="openCostPicker"
              />
              <div v-if="form.tool_cost_id" class="selection-summary">
                厂家：{{ form.cost_manufacturer || '-' }}　品牌：{{ form.cost_brand || '-' }}　价格：{{ form.cost_price || '-' }} 元
              </div>
              <template v-if="current.tool_parent_type === 'DISC'">
                <van-field v-model="form.ring_type_label" label="刀圈类型" readonly is-link placeholder="请选择" :disabled="readonly" @click="openOptionPicker('ring_type')" />
                <van-field v-model="form.ring_manufacturer" label="刀圈厂家" readonly placeholder="由成本库带入" :disabled="readonly" />
                <van-field v-model="form.shaft_condition_label" label="刀轴状况" readonly is-link placeholder="请选择" :disabled="readonly" @click="openOptionPicker('shaft_condition')" />
                <van-field v-model="form.shaft_manufacturer" label="刀轴厂家" readonly placeholder="由成本库带入" :disabled="readonly" />
                <van-field v-model="form.hub_condition_label" label="刀毂状况" readonly is-link placeholder="请选择" :disabled="readonly" @click="openOptionPicker('hub_condition')" />
                <van-field v-model="form.hub_manufacturer" label="刀毂厂家" readonly placeholder="由成本库带入" :disabled="readonly" />
              </template>
              <van-field v-if="current.tool_parent_type === 'SCRAPER'" v-model="form.scraper_manufacturer" label="新换刮刀厂家" readonly placeholder="由成本库带入" :disabled="readonly" />
              <van-field v-model="form.scan_text" label="扫码/备注" placeholder="可扫码或手输辅助信息" :disabled="readonly">
                <template #button>
                  <van-button size="small" type="primary" plain @click.prevent="startScan">扫码</van-button>
                </template>
              </van-field>
              <van-field label="旧刀照片" required>
                <template #input>
                  <van-uploader v-model="form.photos" multiple :max-count="5" result-type="file" :after-read="validatePhoto" :disabled="readonly" accept="image/jpeg,image/png" capture="environment" @update:model-value="onPhotoListChange" />
                </template>
              </van-field>
              <div class="hint">JPG/PNG 原图，至少 1 张，最多 5 张，不压缩。</div>
            </template>
            <template v-else>
              <van-field v-model="form.check_result" label="检查结果" readonly is-link @click="showResultPicker = !readonly" />
            </template>
            <van-field v-model="form.wear_condition" label="磨损描述" placeholder="可手动输入，也可点击选择" :disabled="readonly">
              <template #button>
                <van-button size="small" type="primary" plain :disabled="readonly" @click.prevent="openWearPicker">选择</van-button>
              </template>
            </van-field>
            <van-field v-model="form.blade_wear_amount" type="number" label="刀刃磨损量" placeholder="请输入数值" :disabled="readonly" />
            <van-field v-model="form.remark" rows="2" autosize type="textarea" label="备注" placeholder="可填写现场说明" :disabled="readonly" />
          </van-cell-group>
          <div class="editor-actions">
            <van-button block type="primary" native-type="submit" :loading="saving" :disabled="readonly">保存当前刀位</van-button>
            <van-button block plain icon="arrow-left" :disabled="saving || readonly" @click="saveAndClose">保存并返回刀位列表</van-button>
          </div>
        </van-form>
      </div>
    </van-popup>

    <van-popup v-model:show="showResultPicker" position="bottom">
      <van-picker :columns="resultColumns" @confirm="onResultConfirm" @cancel="showResultPicker = false" />
    </van-popup>

    <van-popup v-model:show="optionPickerVisible" position="bottom">
      <van-picker :columns="optionPickerColumns" @confirm="onOptionConfirm" @cancel="optionPickerVisible = false" />
    </van-popup>

    <van-popup v-model:show="costPickerVisible" position="bottom">
      <van-picker title="选择成本库记录" :columns="costPickerColumns" @confirm="onCostConfirm" @cancel="costPickerVisible = false" />
    </van-popup>

    <van-popup v-model:show="wearPickerVisible" position="bottom">
      <van-picker title="选择磨损描述" :columns="wearPickerColumns" @confirm="onWearConfirm" @cancel="wearPickerVisible = false" />
    </van-popup>

    <van-popup v-model:show="scannerVisible" position="bottom" round :style="{ height: '70vh' }">
      <div class="scanner">
        <div class="editor-title">扫码识别</div>
        <video v-if="!scannerFallback" ref="videoRef" class="scanner-video" autoplay muted playsinline />
        <div v-else class="scanner-fallback">当前浏览器或网络环境不支持摄像头扫码。</div>
        <van-field v-model="form.scan_text" label="编号/内容" placeholder="扫码失败时可直接手动输入" clearable />
        <div class="hint">支持扫码时会自动识别；不支持时，手动输入后点击“使用此内容”即可。</div>
        <van-button block type="primary" :disabled="!form.scan_text.trim()" @click="stopScan">使用此内容</van-button>
        <van-button block plain @click="stopScan">关闭</van-button>
      </div>
    </van-popup>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, toRaw } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { showConfirmDialog, showToast } from 'vant';
import { getMobileTask, saveMobileDetail, submitMobileTask } from '../api';

const route = useRoute();
const router = useRouter();
const task = ref<any>(null);
const details = ref<any[]>([]);
const refreshing = ref(false);
const keyword = ref('');
const statusFilter = ref('ALL');
const typeFilter = ref('ALL');
const summaryCollapsed = ref(false);
const editorVisible = ref(false);
const current = ref<any>(null);
const saving = ref(false);
const showResultPicker = ref(false);
const optionPickerVisible = ref(false);
const optionPickerKey = ref('');
const costPickerVisible = ref(false);
const wearPickerVisible = ref(false);
const fieldOptions = ref<any>({});
const scannerVisible = ref(false);
const scannerFallback = ref(false);
const videoRef = ref<HTMLVideoElement | null>(null);
let stream: MediaStream | null = null;
let scanTimer: number | null = null;

const form = reactive<any>({
  is_replaced: false,
  check_result: '未进行换刀',
  remark: '',
  photos: [],
  pendingPhotoFiles: [],
  scan_text: '',
  tool_info_label: '',
  tool_cost_id: '',
  tool_cost_label: '',
  cost_manufacturer: '',
  cost_brand: '',
  cost_price: '',
  ring_type: '',
  ring_type_label: '',
  ring_manufacturer: '',
  shaft_condition: '',
  shaft_condition_label: '',
  shaft_manufacturer: '',
  hub_condition: '',
  hub_condition_label: '',
  hub_manufacturer: '',
  scraper_manufacturer: '',
  wear_condition: '',
  blade_wear_amount: '',
});
const statusOptions = [
  { text: '全部状态', value: 'ALL' },
  { text: '未交互', value: 'PENDING' },
  { text: '已换刀', value: 'REPLACED' },
  { text: '未换刀', value: 'NOT_REPLACED' },
  { text: '缺照片', value: 'MISSING_PHOTO' },
];
const resultColumns = [
  { text: '未进行换刀', value: 'NOT_REPLACED' },
  { text: '正常', value: 'NORMAL' },
  { text: '需关注', value: 'ATTENTION' },
  { text: '异常未换', value: 'ABNORMAL_NOT_REPLACED' },
];
const resultMap: Record<string, string> = { NOT_REPLACED: '未进行换刀', NORMAL: '正常', ATTENTION: '需关注', ABNORMAL_NOT_REPLACED: '异常未换' };
const reverseResultMap: Record<string, string> = Object.fromEntries(Object.entries(resultMap).map(([k, v]) => [v, k]));
const optionKeyMap: Record<string, string> = {
  ring_type: 'ring_types',
  shaft_condition: 'component_conditions',
  hub_condition: 'component_conditions',
};

const optionPickerColumns = computed(() => {
  const options = fieldOptions.value[optionKeyMap[optionPickerKey.value]] || [];
  return options.map((item: any) => ({ text: item.label, value: item.value }));
});

const costOptions = computed(() => current.value?.tool_cost_options || []);
const costPickerColumns = computed(() => costOptions.value.map((item: any) => ({
  text: item.label,
  value: item.id,
})));
const wearPickerColumns = computed(() => (
  fieldOptions.value.wear_descriptions || []
).map((item: any) => ({ text: item.label, value: item.value })));

function cutterPositionSortKey(value: any): [number, number, number, string] {
  const code = String(value || '').trim().toUpperCase();
  if (/^\d+$/.test(code)) return [0, Number(code), 0, ''];
  const numberWithSuffix = code.match(/^(\d+)([A-Z])$/);
  if (numberWithSuffix) return [0, Number(numberWithSuffix[1]), numberWithSuffix[2].charCodeAt(0) - 64, ''];
  const yPosition = code.match(/^Y(\d+)$/);
  if (yPosition) return [1, Number(yPosition[1]), 0, ''];
  const sPosition = code.match(/^S(\d+)([A-Z]?)$/);
  if (sPosition) return [2, Number(sPosition[1]), ({ L: 0, R: 1 } as Record<string, number>)[sPosition[2]] ?? 2, ''];
  return [9, 0, 0, code];
}

function compareCutterPosition(a: any, b: any) {
  const left = cutterPositionSortKey(a?.cutter_position_no);
  const right = cutterPositionSortKey(b?.cutter_position_no);
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] < right[index]) return -1;
    if (left[index] > right[index]) return 1;
  }
  return 0;
}

const sortDetails = (items: any[]) => [...items].sort(compareCutterPosition);

// 已提交任务允许现场补充/更正，保存后会重新进入录入中；已完成和已取消任务才锁定。
const readonly = computed(() => ['COMPLETED', 'CANCELLED'].includes(task.value?.status));
const savedCount = computed(() => details.value.filter((d) => d.is_checked).length);
const replacedCount = computed(() => details.value.filter((d) => d.is_replaced).length);
const missingPhotoCount = computed(() => details.value.filter((d) => d.is_replaced && (!d.old_photos || d.old_photos.length === 0)).length);
const progressPercent = computed(() => details.value.length ? Math.round((savedCount.value / details.value.length) * 100) : 0);
const typeOptions = computed(() => {
  const types = Array.from(new Set(details.value.map((d) => d.tool_parent_type).filter(Boolean)));
  return [{ text: '全部类型', value: 'ALL' }, ...types.map((type) => ({ text: type, value: type }))];
});
const filteredDetails = computed(() => {
  const kw = keyword.value.trim().toLowerCase();
  return sortDetails(details.value.filter((item) => {
    if (kw && !String(item.cutter_position_no || '').toLowerCase().includes(kw)) return false;
    if (typeFilter.value !== 'ALL' && item.tool_parent_type !== typeFilter.value) return false;
    if (statusFilter.value === 'PENDING' && item.is_checked) return false;
    if (statusFilter.value === 'REPLACED' && !item.is_replaced) return false;
    if (statusFilter.value === 'NOT_REPLACED' && (!item.is_checked || item.is_replaced)) return false;
    if (statusFilter.value === 'MISSING_PHOTO' && !(item.is_replaced && (!item.old_photos || item.old_photos.length === 0))) return false;
    return true;
  }));
});

async function loadTask() {
  try {
    const res: any = await getMobileTask(route.params.id as string);
    task.value = res.data.task;
    details.value = sortDetails(res.data.details || []);
    fieldOptions.value = res.data.field_options || {};
  } catch (error: any) {
    showToast(errorMessage(error));
  } finally {
    refreshing.value = false;
  }
}
function openEditor(detail: any) {
  current.value = detail;
  form.is_replaced = !!detail.is_replaced;
  form.check_result = resultMap[detail.check_result] || '未进行换刀';
  form.remark = detail.remark || '';
  form.scan_text = '';
  form.tool_info_label = detail.tool_type_name || detail.tool_parent_type || '刀位绑定类型';
  const savedCost = (detail.tool_cost_options || []).find((item: any) => item.id === detail.tool_cost_id)
    || (detail.tool_cost_options || []).find((item: any) => (
      (item.manufacturer || '') === (detail.manufacturer || '')
      && (item.brand || '') === (detail.brand || '')
      && String(item.price ?? '') === String(detail.price ?? '')
    ));
  form.tool_cost_id = savedCost?.id || '';
  form.tool_cost_label = savedCost?.label || '';
  form.cost_manufacturer = savedCost?.manufacturer || detail.manufacturer || '';
  form.cost_brand = savedCost?.brand || detail.brand || '';
  form.cost_price = savedCost?.price || detail.price || '';
  const newTool = detail.new_tool || {};
  form.ring_type = newTool.ring_type || '';
  form.ring_type_label = newTool.ring_type_display || optionLabel('ring_types', form.ring_type);
  form.ring_manufacturer = newTool.ring_manufacturer || '';
  form.shaft_condition = newTool.shaft_condition || '';
  form.shaft_condition_label = newTool.shaft_condition_display || optionLabel('component_conditions', form.shaft_condition);
  form.shaft_manufacturer = newTool.shaft_manufacturer || '';
  form.hub_condition = newTool.hub_condition || '';
  form.hub_condition_label = newTool.hub_condition_display || optionLabel('component_conditions', form.hub_condition);
  form.hub_manufacturer = newTool.hub_manufacturer || '';
  form.scraper_manufacturer = newTool.scraper_manufacturer || '';
  form.wear_condition = detail.wear_condition || '';
  form.blade_wear_amount = detail.blade_wear_amount ?? '';
  form.photos = (detail.old_photos || []).map((p: any) => ({ id: p.id, url: p.image_url, isImage: true, message: p.original_filename }));
  form.pendingPhotoFiles = [];
  editorVisible.value = true;
}

function goBack() {
  if (editorVisible.value) {
    closeEditor();
    return;
  }
  router.push('/mobile/tasks');
}

function closeEditor() {
  stopScan();
  showResultPicker.value = false;
  optionPickerVisible.value = false;
  costPickerVisible.value = false;
  wearPickerVisible.value = false;
  editorVisible.value = false;
  current.value = null;
}

function optionLabel(group: string, value: string) {
  return (fieldOptions.value[group] || []).find((item: any) => item.value === value)?.label || '';
}

function openOptionPicker(key: string) {
  if (readonly.value) return;
  optionPickerKey.value = key;
  optionPickerVisible.value = true;
}

function openCostPicker() {
  if (readonly.value || costPickerColumns.value.length === 0) return;
  costPickerVisible.value = true;
}

function onCostConfirm({ selectedOptions }: any) {
  const selectedId = selectedOptions?.[0]?.value;
  const selected = costOptions.value.find((item: any) => item.id === selectedId);
  if (selected) {
    form.tool_cost_id = selected.id;
    form.tool_cost_label = selected.label;
    form.cost_manufacturer = selected.manufacturer || '';
    form.cost_brand = selected.brand || '';
    form.cost_price = selected.price || '';
    form.ring_manufacturer = selected.manufacturer || '';
    form.shaft_manufacturer = selected.manufacturer || '';
    form.hub_manufacturer = selected.manufacturer || '';
    form.scraper_manufacturer = selected.manufacturer || '';
  }
  costPickerVisible.value = false;
}

function openWearPicker() {
  if (readonly.value || wearPickerColumns.value.length === 0) return;
  wearPickerVisible.value = true;
}

function onWearConfirm({ selectedOptions }: any) {
  form.wear_condition = selectedOptions?.[0]?.text || form.wear_condition;
  wearPickerVisible.value = false;
}

function onOptionConfirm({ selectedOptions }: any) {
  const selected = selectedOptions?.[0];
  if (selected && optionPickerKey.value) {
    form[optionPickerKey.value] = selected.value;
    form[`${optionPickerKey.value}_label`] = selected.text;
  }
  optionPickerVisible.value = false;
}
function move(offset: number) {
  if (!current.value) return;
  const list = filteredDetails.value;
  const index = list.findIndex((item) => item.id === current.value.id);
  const next = list[index + offset];
  if (next) openEditor(next);
}
function toPhotoFile(value: any): File | Blob | null {
  if (!value || typeof value !== 'object') return null;
  const candidate = toRaw(value);
  const tag = Object.prototype.toString.call(candidate);
  if (tag === '[object File]' || tag === '[object Blob]') return candidate as File | Blob;
  if (
    typeof candidate.size === 'number'
    && typeof candidate.slice === 'function'
  ) {
    return candidate as File | Blob;
  }
  return null;
}

function getPhotoFile(item: any): File | Blob | null {
  for (const candidate of [item?.file, item?.raw, item?.originFileObj, item]) {
    const file = toPhotoFile(candidate);
    if (file) return file;
  }
  return null;
}

function onPhotoListChange(items: any[]) {
  form.photos = items || [];
  const activeFiles = new Set(
    form.photos.map((item: any) => getPhotoFile(item)).filter(Boolean),
  );
  form.pendingPhotoFiles = form.pendingPhotoFiles.filter((file: File | Blob) => activeFiles.has(file));
}

function collectUploadFiles() {
  const files: (File | Blob)[] = [];
  const addFile = (value: any) => {
    const file = getPhotoFile(value);
    if (file && !files.includes(file)) files.push(file);
  };
  form.pendingPhotoFiles.forEach(addFile);
  form.photos.forEach(addFile);
  return files;
}

function isSupportedPhoto(file: File | Blob, item: any) {
  const mimeType = String(file.type || '').toLowerCase();
  const fileName = String((file as File).name || '').toLowerCase();
  return ['image/jpeg', 'image/jpg', 'image/png'].includes(mimeType)
    || /\.(jpe?g|png)$/.test(fileName)
    || (!mimeType && !fileName)
    || item?.isImage === true;
}

function photoFileName(file: File | Blob) {
  const originalName = String((file as File).name || '').trim();
  if (/\.(jpe?g|png)$/i.test(originalName)) return originalName;
  return String(file.type || '').toLowerCase() === 'image/png' ? 'old-tool-photo.png' : 'old-tool-photo.jpg';
}

function retainedPhotoIds() {
  return form.photos
    .filter((item: any) => !getPhotoFile(item) && item.id !== undefined && item.id !== null)
    .map((item: any) => Number(item.id))
    .filter((id: number) => Number.isInteger(id) && id > 0);
}

function validatePhoto(file: any) {
  const files = Array.isArray(file) ? file : [file];
  for (const item of files) {
    const raw = getPhotoFile(item);
    if (!raw || !isSupportedPhoto(raw, item)) {
      showToast('仅支持 JPG/PNG 原图');
      form.photos = form.photos.filter((p: any) => p !== item && (!raw || getPhotoFile(p) !== raw));
      if (raw) form.pendingPhotoFiles = form.pendingPhotoFiles.filter((existing: File | Blob) => existing !== raw);
      return;
    }
    item.isImage = true;
    if (raw.size > 30 * 1024 * 1024) {
      showToast('单张照片不能超过 30MB');
      form.photos = form.photos.filter((p: any) => p !== item && getPhotoFile(p) !== raw);
      form.pendingPhotoFiles = form.pendingPhotoFiles.filter((existing: File | Blob) => existing !== raw);
      return;
    }
    if (!form.pendingPhotoFiles.includes(raw)) form.pendingPhotoFiles.push(raw);
  }
}
async function saveCurrent(): Promise<boolean> {
  if (!current.value || readonly.value) return false;
  if (form.is_replaced && form.photos.length === 0 && form.pendingPhotoFiles.length === 0) {
    showToast('换刀时必须上传旧刀照片');
    return false;
  }
  saving.value = true;
  try {
    const uploadFiles = collectUploadFiles();
    const keepPhotoIds = retainedPhotoIds();
    if (form.is_replaced && uploadFiles.length + keepPhotoIds.length === 0) {
      showToast('换刀时至少选择一张图片上传');
      saving.value = false;
      return false;
    }
    const data = new FormData();
    data.append('detail_id', String(current.value.id));
    data.append('is_replaced', String(form.is_replaced));
    data.append('check_result', reverseResultMap[form.check_result] || 'NOT_REPLACED');
    data.append('wear_condition', form.wear_condition || '');
    if (form.blade_wear_amount !== '' && form.blade_wear_amount !== null && form.blade_wear_amount !== undefined) {
      data.append('blade_wear_amount', String(form.blade_wear_amount));
    }
    if (form.is_replaced) {
      data.append('tool_cost_id', form.tool_cost_id ? String(form.tool_cost_id) : '');
      const newToolFields: Record<string, any> = {
        ring_type: form.ring_type,
        ring_manufacturer: form.ring_manufacturer,
        shaft_condition: form.shaft_condition,
        shaft_manufacturer: form.shaft_manufacturer,
        hub_condition: form.hub_condition,
        hub_manufacturer: form.hub_manufacturer,
        scraper_manufacturer: form.scraper_manufacturer,
      };
      Object.entries(newToolFields).forEach(([key, value]) => data.append(key, value || ''));
    }
    const remark = form.scan_text ? ((form.remark || '') + (form.remark ? '\n' : '') + '扫码/备注：' + form.scan_text) : (form.remark || '');
    data.append('remark', remark);
    data.append('old_photo_ids', JSON.stringify(keepPhotoIds));
    uploadFiles.forEach((file: File | Blob) => data.append('old_photos', file, photoFileName(file)));
    const res: any = await saveMobileDetail(route.params.id as string, data);
    const idx = details.value.findIndex((item) => item.id === current.value.id);
    if (idx >= 0) details.value[idx] = res.data;
    details.value = sortDetails(details.value);
    current.value = res.data;
    form.remark = res.data.remark || '';
    form.scan_text = '';
    form.pendingPhotoFiles = [];
    form.photos = (res.data.old_photos || []).map((photo: any) => ({
      id: photo.id,
      url: photo.image_url,
      isImage: true,
      message: photo.original_filename,
    }));
    showToast('已保存');
    return true;
  } catch (error: any) {
    showToast(errorMessage(error));
    return false;
  } finally {
    saving.value = false;
  }
}

async function saveAndClose() {
  if (await saveCurrent()) closeEditor();
}
function onResultConfirm({ selectedOptions }: any) {
  form.check_result = selectedOptions?.[0]?.text || '未进行换刀';
  showResultPicker.value = false;
}
async function submitTask() {
  if (readonly.value) return;
  if (saving.value) return;
  // Persist the open editor before submitting so a newly selected photo is not skipped.
  if (editorVisible.value && current.value) {
    const saved = await saveCurrent();
    if (!saved) return;
  }
  const pending = details.value.filter((d) => d.mobile_status === 'PENDING').length;
  if (pending > 0) {
     await showConfirmDialog({ title: '确认提交', message: `还有 ${pending} 个刀位未交互，提交后仍保持“尚未检查”。` });
  }
  try {
    await submitMobileTask(route.params.id as string);
    showToast('任务已提交');
    await loadTask();
  } catch (error: any) {
    showToast(errorMessage(error));
  }
}

function errorMessage(error: any) {
  const payload = error?.response?.data || error;
  return payload?.msg || payload?.detail || payload?.message || '操作失败，请稍后重试';
}
async function startScan() {
  scannerVisible.value = true;
  scannerFallback.value = false;
  await nextTick();
  if (!('BarcodeDetector' in window)) {
    scannerFallback.value = true;
    showToast('当前浏览器不支持扫码，请手输');
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    scannerFallback.value = true;
    showToast('当前网络环境不支持摄像头，请手输');
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
    if (videoRef.value) videoRef.value.srcObject = stream;
    const detector = new (window as any).BarcodeDetector({ formats: ['qr_code', 'code_128', 'code_39', 'ean_13'] });
    scanTimer = window.setInterval(async () => {
      if (!videoRef.value) return;
      try {
        const codes = await detector.detect(videoRef.value);
        if (codes?.length) {
          form.scan_text = codes[0].rawValue;
          showToast('已识别');
          stopScan();
        }
      } catch {
        if (scanTimer) window.clearInterval(scanTimer);
        scanTimer = null;
        stream?.getTracks().forEach((track) => track.stop());
        stream = null;
        scannerFallback.value = true;
        showToast('扫码识别失败，请手输');
      }
    }, 700);
  } catch {
    scannerFallback.value = true;
    showToast('无法打开摄像头，请手输');
  }
}
function stopScan() {
  scannerVisible.value = false;
  scannerFallback.value = false;
  if (scanTimer) window.clearInterval(scanTimer);
  scanTimer = null;
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
}
onMounted(loadTask);
onBeforeUnmount(stopScan);
</script>

<style scoped lang="scss">
.mobile-page {
  height: 100vh;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #eef2f4;
}
.summary {
  flex: 0 0 auto;
  background: #122b3d;
  color: #fff;
  padding: 16px 14px 13px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.summary-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.summary-title { font-size: 18px; font-weight: 700; color: #fff; letter-spacing: 0; }
.summary-meta { color: rgba(255, 255, 255, 0.72); font-size: 13px; margin-top: 7px; }
.summary-toggle { flex: 0 0 auto; color: #fff; border-color: rgba(255, 255, 255, 0.32); background: rgba(255, 255, 255, 0.06); }
.summary-toggle :deep(.van-button__icon) { font-size: 14px; }
.summary-extra { min-height: 0; }
.opening-info { display: flex; flex-wrap: wrap; gap: 5px 12px; color: rgba(255, 255, 255, 0.72); font-size: 12px; margin-top: 9px; line-height: 1.5; }
.summary .van-progress { margin-top: 12px; }
.summary :deep(.van-progress__pivot) { background: #e49a43; }
.filters { flex: 0 0 auto; position: relative; z-index: 2; }
.position-refresh {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}
.position-card {
  background: #fff;
  border: 1px solid #dbe4e9;
  border-radius: 8px;
  margin: 10px 12px;
  padding: 13px;
  box-shadow: 0 2px 8px rgba(18, 43, 61, 0.04);
  transition: border-color 160ms ease, transform 160ms ease, box-shadow 160ms ease;
}
.position-card:active { border-color: #e49a43; transform: translateY(1px); box-shadow: none; }
.position-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.position-no { font-size: 18px; font-weight: 700; color: #122b3d; }
.position-tags { display: flex; gap: 6px; }
.position-meta { color: #5d6b78; font-size: 13px; margin-top: 7px; }
.position-track { display: flex; align-items: baseline; gap: 8px; margin-top: 9px; font-size: 13px; }
.track-label { color: #84929c; }
.track-value { color: #a65c16; font-weight: 650; }
.track-pending { color: #84929c; }
.missing { color: #c2410c; font-size: 13px; margin-top: 7px; }
.bottom-bar {
  flex: 0 0 auto;
  padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
  background: #fff;
  border-top: 1px solid #e8eef2;
  z-index: 9;
}
.editor { height: 100%; overflow: auto; background: #eef2f4; padding-bottom: 18px; }
.editor-header { padding: 12px 14px 10px; background: #fff; border-bottom: 1px solid #dbe4e9; text-align: center; }
.editor-header-main { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.editor-heading { min-width: 0; flex: 1; }
.editor-nav { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 10px; }
.editor-nav > span { color: #84929c; font-size: 11px; line-height: 1.35; }
.editor-title { font-size: 18px; font-weight: 700; color: #122b3d; }
.editor-subtitle, .hint { color: #5d6b78; font-size: 13px; }
.editor-track { margin-top: 5px; color: #a65c16; font-size: 12px; font-weight: 650; }
.selection-summary { padding: 8px 16px 0; color: #a65c16; font-size: 12px; line-height: 1.5; }
.hint { padding: 8px 18px 0; }
.editor-actions { display: grid; gap: 10px; padding: 18px 16px; }
.editor :deep(.van-cell-group--inset) { margin: 12px; overflow: hidden; }
.editor :deep(.van-field__label) { color: #3f505d; }
.editor :deep(.van-button--primary) { background: #c66f20; border-color: #c66f20; }
.editor :deep(.van-switch--on) { background: #c66f20; }
.editor :deep(.van-uploader__upload) { border-color: #c6d2d9; }
.scanner { padding: 16px; }
.scanner-video { width: 100%; height: 42vh; background: #111827; border-radius: 8px; margin: 14px 0; object-fit: cover; }
.scanner-fallback { display: grid; place-items: center; min-height: 120px; margin: 14px 0; padding: 20px; color: #5d6b78; background: #eef2f4; border: 1px dashed #c6d2d9; border-radius: 8px; text-align: center; }
.scanner :deep(.van-button) { margin-top: 10px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }

@media (max-width: 390px) {
  .summary { padding-left: 12px; padding-right: 12px; }
  .summary-title { font-size: 16px; }
  .summary-toggle { padding-left: 8px; padding-right: 8px; }
  .editor-nav > span { max-width: 130px; }
}

@media (prefers-reduced-motion: reduce) {
  .position-card { transition: none; }
}
</style>
