<template>
  <div class="mobile-page">
    <van-nav-bar title="现场录入" fixed placeholder>
      <template #right>
        <van-icon name="replay" size="18" aria-label="刷新" @click="loadTasks" />
      </template>
    </van-nav-bar>
    <div class="task-overview">
      <div class="overview-kicker">刀具检查 / 换刀记录</div>
      <div class="overview-title">按开仓进入现场录入</div>
      <div class="overview-caption">一个开仓只锁定一名现场录入员，未打开的刀位保持尚未检查。</div>
      <div class="overview-stats">
        <div><strong>{{ tasks.length }}</strong><span>{{ tab === 'active' ? '待处理' : '已提交' }}</span></div>
        <div><strong>{{ inProgressCount }}</strong><span>录入中</span></div>
        <div><strong>{{ returnedCount }}</strong><span>待补录</span></div>
      </div>
    </div>
    <van-tabs v-model:active="tab" class="mobile-tabs" @change="loadTasks">
      <van-tab title="待处理" name="active" />
      <van-tab title="已提交" name="submitted" />
    </van-tabs>
    <van-pull-refresh v-model="refreshing" class="task-refresh" @refresh="loadTasks">
      <div class="task-list">
        <van-empty v-if="!loading && tasks.length === 0" description="暂无任务" />
        <van-skeleton v-if="loading" title :row="5" />
        <div v-for="(task, index) in tasks" :key="task.id" class="task-card" :style="{ animationDelay: `${Math.min(index, 8) * 25}ms` }" @click="openTask(task)">
          <div class="task-main">
            <div class="title-block">
              <div class="title">{{ task.project_name || '-' }} · 第{{ task.ring_no }}环</div>
              <div class="task-id">{{ task.warehouse_id_name || '-' }}</div>
            </div>
            <van-tag :type="statusType(task.status)">{{ statusText(task.status) }}</van-tag>
          </div>
          <div class="meta">{{ task.shield_machine || '-' }}<span class="dot">·</span>{{ scopeText(task) }}</div>
          <van-progress :percentage="progressPercent(task)" stroke-width="6" />
          <div class="progress-row">
            <span>已保存 {{ task.progress?.saved || 0 }}/{{ task.progress?.total || 0 }}</span>
            <span>换刀 {{ task.progress?.replaced || 0 }}</span>
            <span v-if="task.progress?.missing_photo">缺照片 {{ task.progress.missing_photo }}</span>
            <van-icon name="arrow" size="15" />
          </div>
          <div v-if="task.returned_reason" class="returned">退回原因：{{ task.returned_reason }}</div>
        </div>
      </div>
    </van-pull-refresh>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { showToast } from 'vant';
import { getMobileTasks } from './api';

const router = useRouter();
const tab = ref('active');
const tasks = ref<any[]>([]);
const loading = ref(false);
const refreshing = ref(false);
const inProgressCount = computed(() => tasks.value.filter((item) => item.status === 'IN_PROGRESS').length);
const returnedCount = computed(() => tasks.value.filter((item) => item.status === 'RETURNED').length);

function statusText(status: string) {
  return ({ UNASSIGNED: '待进入', PENDING: '已锁定', IN_PROGRESS: '录入中', SUBMITTED: '已提交', RETURNED: '待补录', COMPLETED: '已完成', CANCELLED: '已取消' } as any)[status] || status;
}
function statusType(status: string) {
  return status === 'RETURNED' ? 'danger' : status === 'SUBMITTED' || status === 'COMPLETED' ? 'success' : 'primary';
}
function scopeText(task: any) {
  if (task.scope_type === 'ALL') return '全部刀位';
  if (task.scope_type === 'TOOL_TYPE') return (task.tool_types || []).join('、') || '刀具类型';
  return (task.position_nos || []).join('、') || '指定刀位';
}
function progressPercent(task: any) {
  const total = task.progress?.total || 0;
  if (!total) return 0;
  return Math.round(((task.progress?.saved || 0) / total) * 100);
}
function openTask(task: any) {
  router.push(`/mobile/tasks/${task.id}`);
}
async function loadTasks() {
  loading.value = true;
  try {
    const res: any = await getMobileTasks(tab.value === 'submitted' ? '' : 'active');
    tasks.value = (res.data || []).filter((item: any) => tab.value === 'submitted' ? ['SUBMITTED', 'COMPLETED'].includes(item.status) : !['SUBMITTED', 'COMPLETED', 'CANCELLED'].includes(item.status));
  } catch (e: any) {
    showToast(e?.msg || e?.response?.data?.msg || e?.message || '任务加载失败');
  } finally {
    loading.value = false;
    refreshing.value = false;
  }
}
onMounted(loadTasks);
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
.task-overview {
  flex: 0 0 auto;
  padding: 18px 16px 16px;
  color: #fff;
  background: #122b3d;
}
.overview-kicker { color: #e49a43; font-size: 12px; font-weight: 700; letter-spacing: 0.08em; }
.overview-title { margin-top: 7px; font-size: 21px; font-weight: 700; }
.overview-caption { margin-top: 7px; color: rgba(255, 255, 255, 0.68); font-size: 12px; line-height: 1.55; }
.overview-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 16px; }
.overview-stats > div { padding: 9px 10px; border-left: 2px solid #e49a43; background: rgba(255, 255, 255, 0.08); }
.overview-stats strong, .overview-stats span { display: block; }
.overview-stats strong { font-size: 21px; line-height: 1; }
.overview-stats span { margin-top: 6px; color: rgba(255, 255, 255, 0.66); font-size: 12px; }
.mobile-tabs {
  flex: 0 0 auto;
}
.task-refresh {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}
.task-list {
  min-height: 100%;
  box-sizing: border-box;
  padding: 12px;
}
.task-card {
  background: #fff;
  border: 1px solid #dbe4e9;
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 10px;
  box-shadow: 0 2px 8px rgba(18, 43, 61, 0.04);
  animation: task-enter 220ms ease both;
}
.task-main { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }
.title { font-size: 16px; font-weight: 700; color: #122b3d; min-width: 0; }
.task-id { margin-top: 4px; color: #84929c; font-size: 12px; }
.meta, .progress-row { color: #5d6b78; font-size: 13px; margin-top: 8px; }
.dot { margin: 0 6px; color: #c0cbd1; }
.returned { color: #c2410c; font-size: 13px; margin-top: 8px; }
.van-progress { margin-top: 12px; }
.progress-row { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.progress-row span { white-space: nowrap; }
.progress-row .van-icon { margin-left: auto; color: #a9b5bc; }
.task-card :deep(.van-progress__pivot) { background: #c66f20; }

@keyframes task-enter {
  from { opacity: 0; transform: translateY(5px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .task-card { animation: none; }
}
</style>
