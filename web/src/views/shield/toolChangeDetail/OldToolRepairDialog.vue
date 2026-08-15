<template>
  <el-dialog v-model="visible" title="旧刀厂家返修补录" width="820px" :close-on-click-modal="false">
    <div v-if="row" class="record-context">
      <span>刀位：{{ row.cutter_position_no || '-' }}</span>
      <span>刀具类型：{{ row.tool_type_name || row.tool_parent_type || '-' }}</span>
      <span>旧刀编号：{{ form.old_tool_number || row.tool_number || '-' }}</span>
    </div>

    <el-form v-loading="loading" :model="form" label-width="132px" class="repair-form">
      <el-form-item label="旧刀磨损照片">
        <div class="photo-links">
          <el-link
            v-for="(photo, index) in existingPhotos"
            :key="photo.id"
            type="primary"
            @click="previewPhoto(photo.url, photo.name || `照片${index + 1}`)"
          >照片{{ index + 1 }}</el-link>
          <span v-if="existingPhotos.length === 0" class="empty-text">暂无</span>
        </div>
        <el-upload
          v-model:file-list="fileList"
          action="#"
          :auto-upload="false"
          :limit="remainingPhotoSlots"
          accept="image/jpeg,image/png"
          multiple
          class="photo-upload"
        >
          <el-button :disabled="remainingPhotoSlots <= 0">补充照片</el-button>
        </el-upload>
      </el-form-item>

      <template v-if="toolParentType === 'DISC'">
        <el-form-item label="刀圈磨损量">
          <el-input-number v-model="form.ring_wear_amount" :min="0" :precision="2" controls-position="right" />
        </el-form-item>
        <el-form-item label="偏磨量">
          <el-input-number v-model="form.bias_wear_amount" :min="0" :precision="2" controls-position="right" />
        </el-form-item>
        <el-form-item label="刀具轨迹">
          <el-input v-model="form.tool_track" placeholder="请输入刀具轨迹" />
        </el-form-item>
        <el-form-item label="刀圈损坏情况">
          <el-select v-model="form.ring_damage" multiple clearable filterable placeholder="请选择" class="full-width">
            <el-option v-for="item in options.ring_damage" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="刀圈掉齿数量">
          <el-input-number v-model="form.ring_tooth_loss_count" :min="0" :precision="0" controls-position="right" />
        </el-form-item>
        <el-form-item label="刀圈其他情况">
          <el-input v-model="form.ring_other_condition" type="textarea" :rows="2" />
        </el-form-item>
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
        <el-form-item label="轴承其他情况">
          <el-input v-model="form.bearing_other_condition" type="textarea" :rows="2" />
        </el-form-item>
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
        <el-form-item label="刀毂其他情况">
          <el-input v-model="form.hub_other_condition" type="textarea" :rows="2" />
        </el-form-item>
      </template>

      <template v-if="toolParentType === 'SCRAPER'">
        <el-form-item label="换下刀具磨损量">
          <el-input-number v-model="form.scraper_wear_amount" :min="0" :precision="2" controls-position="right" />
        </el-form-item>
        <el-form-item label="刀具轨迹">
          <el-input v-model="form.tool_track" placeholder="请输入刀具轨迹" />
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
      </template>

      <el-form-item label="报废 / 可维修">
        <el-select v-model="form.disposition" clearable placeholder="请选择">
          <el-option v-for="item in options.old_tool_dispositions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="厂家返修结果">
        <el-input v-model="form.repair_result" type="textarea" :rows="2" placeholder="请输入厂家返修结果" />
      </el-form-item>
      <el-form-item label="维修价格">
        <el-input-number v-model="form.repair_price" :min="0" :precision="2" controls-position="right" />
      </el-form-item>
      <el-form-item label="补充说明">
        <el-input v-model="form.remark" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="photoPreviewVisible" title="旧刀磨损照片" width="760px" append-to-body destroy-on-close>
    <div class="photo-preview">
      <img v-if="photoPreviewUrl" :src="photoPreviewUrl" :alt="photoPreviewName" />
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { GetOldToolRecord, GetToolChangeOptions, UpdateOldToolRecord } from './api';

const emit = defineEmits<{ (event: 'saved'): void }>();

const visible = ref(false);
const loading = ref(false);
const saving = ref(false);
const row = ref<any>(null);
const existingPhotos = ref<any[]>([]);
const fileList = ref<any[]>([]);
const photoPreviewVisible = ref(false);
const photoPreviewUrl = ref('');
const photoPreviewName = ref('旧刀磨损照片');
const options = reactive<any>({ ring_damage: [], bearing_failure_reasons: [], hub_failure_reasons: [], old_tool_dispositions: [] });

const form = reactive<any>({
  old_tool_number: '',
  ring_wear_amount: null,
  bias_wear_amount: null,
  tool_track: '',
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
const remainingPhotoSlots = computed(() => Math.max(0, 5 - existingPhotos.value.length));

function resetForm() {
  Object.assign(form, {
    old_tool_number: '', ring_wear_amount: null, bias_wear_amount: null, tool_track: '', ring_damage: [],
    ring_tooth_loss_count: null, ring_other_condition: '', bearing_failed: null, bearing_failure_reasons: [],
    bearing_other_condition: '', hub_damaged: null, hub_failure_reasons: [], hub_other_condition: '', disposition: '',
    scraper_wear_amount: null, scraper_chipped: null, scraper_broken: null, scraper_detached: null,
    repair_result: '', repair_price: null, remark: '',
  });
  existingPhotos.value = [];
  fileList.value = [];
}

function applyRecord(record: any) {
  if (!record) return;
  Object.keys(form).forEach((key) => {
    if (record[key] !== undefined && record[key] !== null) form[key] = record[key];
  });
  form.ring_damage = record.ring_damage || [];
  form.bearing_failure_reasons = record.bearing_failure_reasons || [];
  form.hub_failure_reasons = record.hub_failure_reasons || [];
  existingPhotos.value = record.photos || [];
}

async function open(input: any) {
  row.value = input;
  resetForm();
  visible.value = true;
  loading.value = true;
  try {
    const [recordRes, optionRes] = await Promise.all([
      GetOldToolRecord(input.id),
      GetToolChangeOptions(),
    ]);
    applyRecord(recordRes.data?.old_tool_record_data);
    Object.assign(options, optionRes.data || {});
  } finally {
    loading.value = false;
  }
}

function appendValue(data: FormData, key: string, value: any) {
  if (Array.isArray(value)) {
    data.append(key, JSON.stringify(value));
  } else if (value !== undefined && value !== null) {
    data.append(key, String(value));
  }
}

async function save() {
  if (!row.value) return;
  saving.value = true;
  try {
    const data = new FormData();
    Object.entries(form).forEach(([key, value]) => appendValue(data, key, value));
    fileList.value.forEach((item) => {
      if (item.raw) data.append('photos', item.raw);
    });
    await UpdateOldToolRecord(row.value.id, data);
    ElMessage.success('旧刀返修信息已保存');
    visible.value = false;
    emit('saved');
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

<style scoped>
.record-context { display: flex; flex-wrap: wrap; gap: 8px 20px; margin-bottom: 16px; color: #606266; }
.repair-form { max-height: 62vh; overflow-y: auto; padding-right: 10px; }
.full-width { width: 100%; }
.photo-links { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 8px; }
.photo-upload { display: block; }
.empty-text { color: #909399; }
.photo-preview { display: flex; justify-content: center; align-items: center; min-height: 240px; background: #f4f6f8; }
.photo-preview img { display: block; max-width: 100%; max-height: 68vh; object-fit: contain; }
</style>
