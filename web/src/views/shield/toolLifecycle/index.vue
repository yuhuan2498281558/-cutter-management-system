<template>
  <div class="tool-lifecycle-page">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <div class="scope-toolbar">
      <el-select v-model="scopeKey" placeholder="选择项目 / 盾构机" style="width: 340px" @change="searchList">
        <el-option v-for="scope in scopes" :key="`${scope.project}:${scope.shield_machine}`"
          :value="`${scope.project}:${scope.shield_machine}`" :label="`${scope.project_name} / ${scope.machine_name}`" />
      </el-select>
      <el-select v-model="position" filterable style="width: 180px" @change="searchList">
        <el-option v-for="item in ACTIVE_CUTTER_POSITIONS" :key="item.code" :value="item.code" :label="`${item.code} 号刀位`" />
      </el-select>
      <el-button @click="loadScopes">刷新范围</el-button>
    </div>
    <div class="lifecycle-workspace">
    <aside class="drawing-column">
      <CutterheadHistory v-model="position" @update:model-value="searchList" />
    </aside>
    <section class="history-column" aria-label="所选刀位服役历史">
    <h3 class="history-heading">{{ position }} 号刀位服役历史 <small>按安装时间升序</small></h3>
    <el-form :model="query" inline class="toolbar">
      <el-form-item label="刀具编号">
        <el-input v-model="query.search" clearable placeholder="唯一编号/短编号/类型" @keyup.enter="searchList" />
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="query.status" clearable placeholder="全部" style="width: 160px">
          <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="刀具类型">
        <el-select v-model="query.tool_parent_type" clearable placeholder="全部" style="width: 160px">
          <el-option label="滚刀（DISC）" value="DISC" />
          <el-option label="刮刀（SCRAPER）" value="SCRAPER" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" icon="Search" @click="searchList">查询</el-button>
        <el-button icon="Refresh" @click="resetQuery">重置</el-button>
      </el-form-item>
    </el-form>

    <el-row v-loading="loading" :gutter="12">
      <el-col v-for="item in tools" :key="item.service_id" :xs="24" :sm="12" :lg="12" :xl="8">
        <el-card class="tool-card" shadow="hover" @click="openDetail(item)">
          <div class="card-head">
            <div>
              <div class="tool-no">{{ item.display_tool_no }}</div>
              <div class="tool-uid">{{ item.tool_uid }}</div>
            </div>
            <el-tag size="small">{{ statusText(item.status) }}</el-tag>
          </div>
          <div class="meta-row">类型：{{ item.tool_type_name || item.tool_parent_type || '-' }}</div>
          <div class="meta-row">厂家：{{ item.manufacturer || '-' }}，品牌：{{ item.brand || '-' }}</div>
          <div class="meta-row">价格：{{ moneyText(item.price) }}</div>
          <div class="meta-row">使用环号：安装 {{ ringText(item.install_ring_no) }}，换下 {{ ringText(item.remove_ring_no, '未换下') }}</div>
          <div class="meta-row">服役环数：{{ usageRingsText(item.usage_rings) }}</div>
          <div class="meta-row">经历地层：{{ exposureText(item) }}</div>
          <div v-if="item.stratum_exposure?.engineering_condition_names?.length" class="meta-row">历史工程地质条件：{{ item.stratum_exposure.engineering_condition_names.join('、') }}（非面积岩性）</div>
          <div v-if="!item.installation_known" class="meta-row">安装未知；首次记录 {{ ringText(item.first_observed_ring_no) }}</div>
          <div class="meta-row">{{ item.installation_known ? '安装时间' : '首次记录时间' }}：{{ formatTime(item.create_datetime) }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-if="!loading && tools.length === 0" description="暂无刀具生命周期记录" />

    <div v-if="pagination.total > 0" class="pagination-bar">
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.limit"
        :page-sizes="[24, 48, 96, 200]"
        :total="pagination.total"
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="handlePageSizeChange"
        @current-change="loadList"
      />
    </div>
    </section>
    </div>

    <el-drawer v-model="drawerVisible" size="min(560px, 100vw)" title="刀具生命周期卡片">
      <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
      <div v-if="detailLoading" role="status">正在加载刀具完整档案…</div>
      <template v-if="current">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="唯一编号">{{ current.tool_uid }}</el-descriptions-item>
          <el-descriptions-item label="短编号">{{ current.display_tool_no }}</el-descriptions-item>
          <el-descriptions-item label="刀具类型">{{ current.tool_type_name || current.tool_parent_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusText(current.status) }}</el-descriptions-item>
          <el-descriptions-item label="厂家">{{ current.manufacturer || '-' }}</el-descriptions-item>
          <el-descriptions-item label="品牌">{{ current.brand || '-' }}</el-descriptions-item>
          <el-descriptions-item label="价格">{{ moneyText(current.price) }}</el-descriptions-item>
          <el-descriptions-item label="安装环号">{{ ringText(current.install_ring_no) }}</el-descriptions-item>
          <el-descriptions-item :label="current.installation_known ? '安装时间' : '首次记录时间'">{{ formatTime(current.create_datetime) }}</el-descriptions-item>
          <el-descriptions-item v-if="!current.installation_known" label="首次记录环号">{{ ringText(current.first_observed_ring_no) }}（安装未知）</el-descriptions-item>
          <el-descriptions-item label="换下环号">{{ ringText(current.remove_ring_no, '未换下') }}</el-descriptions-item>
          <el-descriptions-item label="服役环数">{{ usageRingsText(current.usage_rings) }}</el-descriptions-item>
          <el-descriptions-item label="经历地层">{{ exposureText(current) }}</el-descriptions-item>
          <el-descriptions-item label="历史工程地质条件">{{ current.stratum_exposure?.engineering_condition_names?.join('、') || '暂无' }}（非面积岩性）</el-descriptions-item>
          <el-descriptions-item label="服役段依据">{{ current.pairing_source === 'confirmed' ? '已确认刀具配对' : '同项目、盾构机和刀位的更换顺序' }}</el-descriptions-item>
        </el-descriptions>

        <el-timeline class="timeline">
          <el-timeline-item
            v-for="event in current.timeline || []"
            :key="`${event.event}-${event.detail_id}-${event.time}`"
            :timestamp="formatTime(event.time)"
            placement="top"
          >
            <div class="event-title">{{ event.event_name }}</div>
            <div class="event-line">项目：{{ event.project_name || '-' }}，使用环号：{{ event.ring_no || '-' }}，刀位：{{ event.cutter_position_no || '-' }}</div>
            <div v-if="event.operator" class="event-line">录入员：{{ event.operator }}</div>
            <div v-if="event.new_tool_components" class="event-line">
              新刀部件：{{ newToolSummary(event.new_tool_components) }}
            </div>
            <div v-if="event.wear_condition" class="event-line">磨损：{{ event.wear_condition }}</div>
            <div v-if="event.manufacturer || event.brand || event.price" class="event-line">厂家：{{ event.manufacturer || '-' }}，品牌：{{ event.brand || '-' }}，价格：{{ moneyText(event.price) }}</div>
            <div v-if="event.inspection_status" class="event-line">补录状态：{{ inspectionText(event.inspection_status) }}</div>
            <div v-if="event.photo_count !== undefined" class="event-line">旧刀照片：{{ event.photo_count }} 张</div>
            <div v-if="event.repair_result" class="event-line">维修结果：{{ event.repair_result }}</div>
            <div v-if="event.old_tool_inspection" class="event-line">
              返修检查：{{ oldToolSummary(event.old_tool_inspection) }}
            </div>
            <div v-if="event.old_tool_inspection?.photo_links?.length" class="event-line photo-links">
              照片：
              <el-link
                v-for="(photo, index) in event.old_tool_inspection.photo_links"
                :key="photo.id"
                type="primary"
                @click="previewPhoto(photo.url, photo.name || `照片${index + 1}`)"
              >照片{{ index + 1 }}</el-link>
            </div>
            <div v-if="event.remark" class="event-line">备注：{{ event.remark }}</div>
          </el-timeline-item>
          </el-timeline>
      </template>
    </el-drawer>

    <el-dialog v-model="photoPreviewVisible" title="旧刀磨损照片" width="min(760px, 94vw)" append-to-body destroy-on-close>
      <div class="photo-preview">
        <img v-if="photoPreviewUrl" :src="photoPreviewUrl" :alt="photoPreviewName" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts" name="ShieldToolLifecycle">
import { onMounted, onBeforeUnmount, reactive, ref } from 'vue';
import { getLifecycleScopes, getPositionHistory, getToolLifecycleDetail } from './api';
import CutterheadHistory from './CutterheadHistory.vue';
import { ACTIVE_CUTTER_POSITIONS } from '/@/constants/cutterPositions';
import { mergeServiceTimeline } from './serviceTimeline';

const scopes = ref<any[]>([]);
const scopeKey = ref('');
const position = ref('1');
const error = ref('');
let requestSequence = 0;
let scopeSequence = 0;
let detailSequence = 0;
const detailLoading = ref(false);
const detailError = ref('');
const exposureText = (item: any) => {
  if (item.identity_conflict) return '旧刀确认身份冲突，服役地层待核实';
  const value = item.stratum_exposure;
  if (!value) return '安装环号未知，无法确定完整服役区间';
  const codes = value.encountered_names?.join('、') || '暂无可识别的占比岩层，不以工程标签替代';
  return `${codes}；图示断面占比为估算值，完整占比 ${value.known_rings} 环 / 不完整或缺失 ${value.missing_rings} 环${item.exposure_is_open ? `（截至本刀位最新记录 ${item.exposure_end_ring} 环）` : ''}`;
};

const statusOptions = [
  { label: '待确认', value: 'PENDING_VERIFY' },
  { label: '已安装', value: 'INSTALLED' },
  { label: '已换下', value: 'REMOVED' },
  { label: '待厂家检测', value: 'REMOVED_PENDING_INSPECTION' },
  { label: '厂家已确认', value: 'INSPECTED' },
  { label: '返修闭环', value: 'REPAIRED_CLOSED' },
  { label: '已报废', value: 'SCRAPPED' },
];

const statusText = (value: string) => statusOptions.find((item) => item.value === value)?.label || value || '-';
const inspectionText = (value: string) => ({ PENDING_VENDOR_FEEDBACK: '待厂家反馈', CONFIRMED: '已确认', CLOSED: '已归档' } as Record<string, string>)[value] || value;
const formatTime = (value: string) => value ? String(value).replace('T', ' ').slice(0, 19) : '-';
const moneyText = (value: any) => value !== undefined && value !== null && value !== '' ? `¥${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '-';
const ringText = (value: any, emptyText = '暂无') => value !== undefined && value !== null && value !== '' ? `${value} 环` : emptyText;
const usageRingsText = (value: any) => value !== undefined && value !== null && value !== '' ? `${value} 环` : '暂无';
const newToolSummary = (value: any) => {
  const parts = [
    value.ring_type_display && `刀圈${value.ring_type_display}`,
    value.ring_manufacturer && `刀圈厂家${value.ring_manufacturer}`,
    value.shaft_condition_display && `刀轴${value.shaft_condition_display}`,
    value.shaft_manufacturer && `刀轴厂家${value.shaft_manufacturer}`,
    value.hub_condition_display && `刀毂${value.hub_condition_display}`,
    value.hub_manufacturer && `刀毂厂家${value.hub_manufacturer}`,
    value.scraper_manufacturer && `刮刀厂家${value.scraper_manufacturer}`,
  ].filter(Boolean);
  return parts.join('，') || '-';
};
const oldToolSummary = (value: any) => {
  const parts = [
    value.inspection_status_display,
    value.disposition_display,
    value.repair_result,
    value.ring_wear_amount !== null && value.ring_wear_amount !== undefined ? `刀圈磨损${value.ring_wear_amount}` : '',
    value.scraper_wear_amount !== null && value.scraper_wear_amount !== undefined ? `刮刀磨损${value.scraper_wear_amount}` : '',
  ].filter(Boolean);
  return parts.join('，') || '-';
};

const query = reactive({ search: '', status: '', tool_parent_type: '' });
const pagination = reactive({ page: 1, limit: 48, total: 0 });
const tools = ref<any[]>([]);
const current = ref<any>();
const loading = ref(false);
const drawerVisible = ref(false);
const photoPreviewVisible = ref(false);
const photoPreviewUrl = ref('');
const photoPreviewName = ref('旧刀磨损照片');

const loadList = async () => {
  const sequence = ++requestSequence;
  tools.value = [];
  pagination.total = 0;
  drawerVisible.value = false;
  detailSequence++;
  error.value = '';
  if (!scopeKey.value) { loading.value = false; return; }
  loading.value = true;
  try {
    const [project, shield_machine] = scopeKey.value.split(':');
    const res: any = await getPositionHistory({ project, shield_machine, position: position.value });
    if (sequence !== requestSequence) return;
    const filtered = (res.data || []).filter((item: any) =>
      (!query.search || `${item.tool_uid} ${item.display_tool_no} ${item.tool_type_name}`.includes(query.search)) &&
      (!query.status || item.status === query.status) && (!query.tool_parent_type || item.tool_parent_type === query.tool_parent_type));
    pagination.total = filtered.length;
    tools.value = filtered.slice((pagination.page - 1) * pagination.limit, pagination.page * pagination.limit);
  } catch (cause: any) {
    if (sequence === requestSequence) error.value = cause.message || '加载刀位服役历史失败，请重试';
  } finally {
    if (sequence === requestSequence) loading.value = false;
  }
};

const loadScopes = async () => {
  const sequence = ++scopeSequence;
  try {
    const res: any = await getLifecycleScopes();
    if (sequence !== scopeSequence) return;
    scopes.value = res.data || [];
    if (!scopes.value.some(item => `${item.project}:${item.shield_machine}` === scopeKey.value)) {
      const first = scopes.value[0];
      scopeKey.value = first ? `${first.project}:${first.shield_machine}` : '';
    }
    await searchList();
  } catch (cause: any) {
    if (sequence === scopeSequence) error.value = cause.message || '加载项目范围失败';
  }
};

const searchList = () => {
  pagination.page = 1;
  loadList();
};

const handlePageSizeChange = () => {
  pagination.page = 1;
  loadList();
};

const resetQuery = () => {
  query.search = '';
  query.status = '';
  query.tool_parent_type = '';
  pagination.page = 1;
  loadList();
};

const openDetail = async (item: any) => {
  const sequence = ++detailSequence;
  current.value = item;
  drawerVisible.value = true;
  detailLoading.value = true;
  detailError.value = '';
  try {
    const res: any = await getToolLifecycleDetail(item.id);
    if (sequence !== detailSequence) return;
    current.value = { ...item, timeline: mergeServiceTimeline(item.timeline || [], item.identity_conflict ? [] : res.data?.timeline || []) };
  } catch (cause: any) {
    if (sequence === detailSequence) detailError.value = cause.message || '完整档案加载失败，当前服役段仍可查看';
  } finally {
    if (sequence === detailSequence) detailLoading.value = false;
  }
};

const previewPhoto = (url: string, name = '旧刀磨损照片') => {
  if (!url) return;
  photoPreviewUrl.value = url;
  photoPreviewName.value = name;
  photoPreviewVisible.value = true;
};

onMounted(loadScopes);
onBeforeUnmount(() => { requestSequence++; scopeSequence++; detailSequence++; });
</script>

<style scoped lang="scss">
.tool-lifecycle-page {
  padding: 16px;
  .scope-toolbar { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }
  .scope-toolbar :deep(.el-select) { max-width: 100%; }
  h3 small { font-size: 12px; font-weight: normal; color: #606266; }
  .lifecycle-workspace { display: grid; grid-template-columns: minmax(340px, 520px) minmax(0, 1fr); align-items: start; gap: 16px; }
  .drawing-column { position: sticky; top: 12px; min-width: 0; }
  .history-column { min-width: 0; }
  .history-heading { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 12px; margin: 0 0 12px; font-size: 16px; font-weight: 600; color: #303133; }

  .toolbar {
    padding: 16px 16px 0;
    background: #fff;
    border-radius: 6px;
    margin-bottom: 12px;
  }

  .tool-card {
    margin-bottom: 12px;
    cursor: pointer;

    .card-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
    }

    .tool-no {
      font-size: 18px;
      font-weight: 600;
      color: #303133;
    }

    .tool-uid,
    .meta-row {
      margin-top: 8px;
      color: #606266;
      word-break: break-all;
    }
  }

  .pagination-bar {
    display: flex;
    justify-content: flex-end;
    padding: 8px 0 16px;
    overflow-x: auto;
  }

  .timeline {
    margin-top: 20px;
  }

  .event-title {
    font-weight: 600;
    color: #303133;
    margin-bottom: 6px;
  }

  .event-line {
    color: #606266;
    line-height: 1.7;
  }

  .photo-links {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }

  .photo-preview {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 240px;
    background: #f4f6f8;
  }

  .photo-preview img {
    display: block;
    max-width: 100%;
    max-height: 68vh;
    object-fit: contain;
  }
}
@media (max-width: 1100px) {
  .tool-lifecycle-page {
    .lifecycle-workspace { grid-template-columns: minmax(0, 1fr); }
    .drawing-column { position: static; width: 100%; max-width: 600px; margin: 0 auto; }
  }
}
@media (max-width: 600px) {
  .tool-lifecycle-page {
    padding: 10px;
    .toolbar { padding: 12px 12px 0; }
    .toolbar :deep(.el-form-item) { margin-right: 0; max-width: 100%; }
    .toolbar :deep(.el-input), .toolbar :deep(.el-select) { max-width: 100%; }
    .pagination-bar { justify-content: flex-start; }
  }
}
</style>
