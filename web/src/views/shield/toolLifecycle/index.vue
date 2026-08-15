<template>
  <div class="tool-lifecycle-page">
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
          <el-option label="撕裂刀（RIPPER）" value="RIPPER" />
          <el-option label="刮刀（SCRAPER）" value="SCRAPER" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" icon="Search" @click="searchList">查询</el-button>
        <el-button icon="Refresh" @click="resetQuery">重置</el-button>
      </el-form-item>
    </el-form>

    <el-row :gutter="12">
      <el-col v-for="item in tools" :key="item.id" :xs="24" :sm="12" :lg="8">
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
          <div class="meta-row">寿命：{{ usageRingsText(item.usage_rings) }}</div>
          <div class="meta-row">建档：{{ formatTime(item.create_datetime) }}</div>
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

    <el-drawer v-model="drawerVisible" size="560px" title="刀具生命周期卡片">
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
          <el-descriptions-item label="换下环号">{{ ringText(current.remove_ring_no, '未换下') }}</el-descriptions-item>
          <el-descriptions-item label="刀具寿命">{{ usageRingsText(current.usage_rings) }}</el-descriptions-item>
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

    <el-dialog v-model="photoPreviewVisible" title="旧刀磨损照片" width="760px" append-to-body destroy-on-close>
      <div class="photo-preview">
        <img v-if="photoPreviewUrl" :src="photoPreviewUrl" :alt="photoPreviewName" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts" name="ShieldToolLifecycle">
import { onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { getToolLifecycleDetail, getToolLifecycleList } from './api';

const statusOptions = [
  { label: '待确认', value: 'PENDING_VERIFY' },
  { label: '已安装', value: 'INSTALLED' },
  { label: '已换下', value: 'REMOVED' },
  { label: '待补录', value: 'REMOVED_PENDING_INSPECTION' },
  { label: '已检查', value: 'INSPECTED' },
  { label: '维修归档', value: 'REPAIRED_CLOSED' },
  { label: '报废', value: 'SCRAPPED' },
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
  loading.value = true;
  try {
    const res: any = await getToolLifecycleList({ ...query, page: pagination.page, limit: pagination.limit });
    tools.value = res.data || [];
    pagination.total = Number(res.total) || 0;
  } finally {
    loading.value = false;
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
  try {
    const res: any = await getToolLifecycleDetail(item.id);
    current.value = res.data;
    drawerVisible.value = true;
  } catch (error: any) {
    ElMessage.error(error.message || '加载生命周期失败');
  }
};

const previewPhoto = (url: string, name = '旧刀磨损照片') => {
  if (!url) return;
  photoPreviewUrl.value = url;
  photoPreviewName.value = name;
  photoPreviewVisible.value = true;
};

onMounted(loadList);
</script>

<style scoped lang="scss">
.tool-lifecycle-page {
  padding: 16px;

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
</style>
