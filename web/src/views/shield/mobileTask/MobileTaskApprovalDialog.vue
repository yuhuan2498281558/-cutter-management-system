<template>
  <el-dialog v-model="visible" title="查看现场录入" width="1100px" :close-on-click-modal="false">
    <div v-loading="loading">
      <div v-if="task" class="approval-summary">
        <span>开仓编号：{{ task.warehouse_id_name || '-' }}</span>
        <span>项目：{{ task.project_name || '-' }}</span>
        <span>环号：{{ task.ring_no || '-' }}</span>
        <span>录入员：{{ task.recorder_name || '-' }}</span>
        <span>状态：{{ statusText(task.status) }}</span>
      </div>

      <el-table :data="details" border height="560px" class="approval-table">
        <el-table-column prop="cutter_position_no" label="刀位" width="90" fixed />
        <el-table-column prop="tool_type_name" label="刀具类型" min-width="140" />
        <el-table-column label="是否更换" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_replaced ? 'warning' : 'info'">{{ row.is_replaced ? '更换' : '未更换' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="检查结果" width="120">
          <template #default="{ row }">{{ checkResultText(row.check_result) }}</template>
        </el-table-column>
        <el-table-column prop="new_tool_uid" label="新刀编号" min-width="210" show-overflow-tooltip />
        <el-table-column label="旧刀照片" min-width="180">
          <template #default="{ row }">
            <div v-if="row.old_photos?.length" class="photo-list">
              <el-link
                v-for="photo in row.old_photos"
                :key="photo.id"
                type="primary"
                @click="previewPhoto(photo.image_url, photo.original_filename || '照片')"
              >{{ photo.original_filename || '照片' }}</el-link>
            </div>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="180" show-overflow-tooltip />
        <el-table-column prop="checked_at" label="录入时间" width="170" />
      </el-table>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="photoPreviewVisible" title="旧刀磨损照片" width="760px" append-to-body destroy-on-close>
    <div class="photo-preview">
      <img v-if="photoPreviewUrl" :src="photoPreviewUrl" :alt="photoPreviewName" />
    </div>
  </el-dialog>
</template>

<script lang="ts" setup>
import { ref } from 'vue';
import { ApprovalDetail } from './api';

const visible = ref(false);
const loading = ref(false);
const task = ref<any>(null);
const details = ref<any[]>([]);
const photoPreviewVisible = ref(false);
const photoPreviewUrl = ref('');
const photoPreviewName = ref('旧刀磨损照片');

const statusMap: Record<string, string> = {
  UNASSIGNED: '待分配',
  PENDING: '待处理',
  IN_PROGRESS: '录入中',
  SUBMITTED: '待审批',
  RETURNED: '已退回',
  COMPLETED: '已通过',
  CANCELLED: '已取消',
};

const checkResultMap: Record<string, string> = {
  PENDING: '待检查',
  NORMAL: '已更换',
  NOT_REPLACED: '未更换',
};

function statusText(value: string) {
  return statusMap[value] || value || '-';
}

function checkResultText(value: string) {
  return checkResultMap[value] || value || '-';
}

async function load(id: string | number) {
  loading.value = true;
  try {
    const res: any = await ApprovalDetail(id);
    task.value = res.data?.task || null;
    details.value = res.data?.details || [];
  } finally {
    loading.value = false;
  }
}

async function open(row: any) {
  visible.value = true;
  task.value = row;
  details.value = [];
  await load(row.id);
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
.approval-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  margin-bottom: 14px;
  color: #606266;
}

.approval-table :deep(.el-table__cell) {
  vertical-align: top;
}

.photo-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
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

</style>
