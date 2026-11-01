<template>
  <div class="left-panel">
    <div class="panel-section">
      <div class="section-title"><span class="dot blue"></span>项目基本信息</div>
      <template v-if="projectState === 'ready' && project">
        <div class="info-row"><span class="lbl">项目名称</span><span class="val">{{ project.project_name }}</span></div>
        <div class="info-row"><span class="lbl">所在地</span><span class="val">{{ project.location || '-' }}</span></div>
        <div class="info-row"><span class="lbl">开挖直径</span><span class="val">{{ project.excavation_diameter != null ? project.excavation_diameter + ' m' : '-' }}</span></div>
        <div class="info-row"><span class="lbl">隧洞长度</span><span class="val">{{ project.tunnel_length != null ? project.tunnel_length + ' m' : '-' }}</span></div>
        <div class="info-row"><span class="lbl">盾构机型号</span><span class="val">{{ shieldMachine?.shield_model || '-' }}</span></div>
        <div class="info-row"><span class="lbl">最新开仓环号</span><span class="val accent">{{ latestRingNo || '-' }}</span></div>
      </template>
      <div v-else-if="projectState === 'error'" class="muted">加载失败，请点刷新重试</div>
      <div v-else-if="projectState === 'empty'" class="muted">暂无项目信息</div>
      <div v-else class="muted">加载中...</div>
    </div>

    <div class="panel-section">
      <div class="section-title">
        <span class="dot red"></span>换刀预警
        <span class="sub-hint">距上次换刀环数最大</span>
      </div>
      <div v-if="warningLoading" class="muted">加载中...</div>
      <div v-else-if="warningError" class="muted">预警加载失败</div>
      <div v-else-if="warningPositions.length === 0" class="muted">暂无预警</div>
      <div v-for="w in warningPositions" :key="w.position" class="warn-item">
        <div class="warn-left">
          <span class="pos-badge">{{ w.position }}</span>
          <span class="pos-type">{{ w.type }}</span>
        </div>
        <div class="warn-right">
          <span class="warn-rings">+{{ w.ringsSince }} 环</span>
          <span class="warn-ring-label">上次 {{ w.lastRing }} 环</span>
        </div>
      </div>
    </div>

    <div class="panel-section">
      <div class="section-title">
        <span class="dot orange"></span>最近换刀记录
        <span class="refresh-btn" @click="refresh" title="刷新">↻</span>
      </div>
      <div class="change-list">
        <div v-if="changesError" class="muted">换刀记录加载失败</div>
        <div v-else-if="recentChanges.length === 0" class="muted">暂无换刀记录</div>
        <button v-for="item in recentChanges" :key="item.id" class="change-item" type="button" @click="goToToolChangeDetail(item)">
          <div class="change-top">
            <span class="ring-badge">环 {{ item.ring_no }}</span>
            <span class="change-date">{{ formatDate(item.open_time) }}</span>
          </div>
          <div class="change-bot">
            <span>{{ item.section || '未设置区间' }}</span>
            <span v-if="item.rings_between_openings" class="gap-hint">间隔 {{ item.rings_between_openings }} 环</span>
          </div>
        </button>
      </div>
    </div>

    <ProjectRouteMap class="map-section" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { request } from '/@/utils/service';
import ProjectRouteMap from './ProjectRouteMap.vue';

const router = useRouter();
const project = ref<any>(null);
const projectState = ref<'loading' | 'ready' | 'empty' | 'error'>('loading');
const shieldMachine = ref<any>(null);
const latestRingNo = ref<string>('');
const recentChanges = ref<any[]>([]);
const changesError = ref(false);
const warningPositions = ref<any[]>([]);
const warningLoading = ref(false);
const warningError = ref(false);

async function loadData() {
  try {
    const [projRes, smRes] = await Promise.all([
      request({ url: '/api/shield/project/', method: 'get', params: { limit: 1 } }),
      request({ url: '/api/shield/shield_machine_basic_info/', method: 'get', params: { limit: 1 } }),
    ]);
    const projects = projRes.data?.results ?? projRes.data ?? [];
    project.value = (Array.isArray(projects) ? projects[0] : projects) ?? null;
    const machines = smRes.data?.results ?? smRes.data ?? [];
    shieldMachine.value = Array.isArray(machines) ? machines[0] : machines;
    projectState.value = project.value ? 'ready' : 'empty';
  } catch (e) {
    project.value = null;
    projectState.value = 'error';
    console.error('首页项目信息加载失败:', e);
  }

  try {
    // ring_no 是字符串字段，按后端注解的数字环号排序后再截取最近 5 条。
    const warehouseRes = await request({
      url: '/api/shield/warehouse_opening/',
      method: 'get',
      params: { limit: 5, ordering: '-ring_int,-open_time' },
    });
    const allRecords: any[] = warehouseRes.data?.results ?? warehouseRes.data ?? [];
    const sorted = [...allRecords].sort((a, b) => {
      const diff = Number(b.ring_no) - Number(a.ring_no);
      return diff !== 0 ? diff : new Date(b.open_time).getTime() - new Date(a.open_time).getTime();
    });
    recentChanges.value = sorted.slice(0, 5);
    latestRingNo.value = sorted.length > 0 ? String(sorted[0].ring_no) : '';
    changesError.value = false;
  } catch (e) {
    recentChanges.value = [];
    changesError.value = true;
    console.error('首页换刀记录加载失败:', e);
  }
}

async function loadWarnings() {
  warningLoading.value = true;
  warningError.value = false;
  try {
    const res = await request({
      url: '/api/shield/tool_change_detail/home_warnings/',
      method: 'get',
      params: { limit: 5 },
    });
    let data = res?.data ?? res ?? {};
    if (data && !Array.isArray(data) && data.code !== undefined && data.data !== undefined) {
      data = data.data;
    }
    if (!latestRingNo.value && data.current_ring) {
      latestRingNo.value = String(data.current_ring);
    }
    // 后端已经按刀位台账筛选，首页不要再使用旧版静态白名单二次过滤。
    warningPositions.value = (Array.isArray(data?.warnings) ? data.warnings : [])
      .map((item: any) => ({
        position: item.position,
        type: formatType(item.type),
        lastRing: item.lastRing,
        ringsSince: item.ringsSince,
      }));
  } catch (e) {
    warningPositions.value = [];
    warningError.value = true;
    console.error('首页换刀预警加载失败:', e);
  } finally {
    warningLoading.value = false;
  }
}

function refresh() {
  loadData();
  loadWarnings();
}

function goToToolChangeDetail(row: any) {
  router.push({
    path: '/shield/toolChangeDetail',
    query: {
      warehouse_id: row.id,
      warehouse_code: row.warehouse_id,
    },
  });
}

function formatType(code: string) {
  const map: Record<string, string> = { DISC: '滚刀', RIPPER: '撕裂刀', TEAR: '撕裂刀', SCRAPER: '刮刀' };
  return map[code] || code || '-';
}

function formatDate(dt: string) {
  if (!dt) return '-';
  return dt.slice(0, 10);
}

onMounted(refresh);
</script>

<style scoped>
.left-panel {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  background: #f4f5f9;
  padding: 10px;
  box-sizing: border-box;
}

.panel-section {
  background: #fff;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  flex-shrink: 0;
}

.map-section {
  margin-bottom: 8px;
  flex: 0 0 320px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: #333;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 5px;
}

.sub-hint { font-size: 10px; color: #aaa; font-weight: 400; margin-left: 2px; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot.blue { background: #1976D2; }
.dot.orange { background: #F57C00; }
.dot.red { background: #D32F2F; }
.dot.green { background: #00897B; }
.refresh-btn { margin-left: auto; cursor: pointer; color: #777; font-size: 13px; user-select: none; }
.refresh-btn:hover { color: #1976D2; }

.module-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.module-card {
  border: 1px solid #e6edf2;
  border-radius: 7px;
  background: #f8fbfd;
  padding: 9px 10px;
  text-align: left;
  cursor: pointer;
  min-height: 72px;
}

.module-card:hover {
  background: #eef8f6;
  border-color: #9bd1c8;
}

.module-name {
  display: block;
  color: #667;
  font-size: 11px;
  margin-bottom: 5px;
}

.module-main {
  display: block;
  color: #00897B;
  font-size: 20px;
  line-height: 22px;
  font-weight: 700;
}

.module-sub {
  display: block;
  color: #99a;
  font-size: 10px;
  margin-top: 4px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 4px 0;
  border-bottom: 1px solid #f5f5f5;
  font-size: 12px;
}

.info-row:last-child { border-bottom: none; }
.lbl { color: #999; flex-shrink: 0; }
.val { color: #333; font-weight: 500; text-align: right; max-width: 60%; word-break: break-all; }
.val.accent { color: #1976D2; font-weight: 700; font-size: 14px; }

.warn-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 10px;
  border-radius: 5px;
  background: #FFF8F0;
  margin-bottom: 5px;
  font-size: 12px;
}

.warn-item:last-child { margin-bottom: 0; }
.warn-left { display: flex; align-items: center; gap: 6px; }
.pos-badge {
  background: #FFEBEE;
  color: #D32F2F;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 10px;
  font-size: 11px;
}
.pos-type { color: #888; font-size: 11px; }
.warn-right { text-align: right; }
.warn-rings { color: #D32F2F; font-weight: 600; font-size: 12px; display: block; }
.warn-ring-label { color: #bbb; font-size: 10px; }

.change-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.change-item {
  width: 100%;
  border: 0;
  background: #f7f8fc;
  border-radius: 6px;
  padding: 7px 10px;
  text-align: left;
  cursor: pointer;
}

.change-item:hover {
  background: #eef6ff;
}

.change-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 3px;
}

.ring-badge {
  background: #FFF3E0;
  color: #F57C00;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 10px;
}

.change-date { font-size: 10px; color: #999; }
.change-bot { display: flex; justify-content: space-between; font-size: 11px; color: #666; }
.gap-hint { color: #1976D2; }
.muted { font-size: 12px; color: #aaa; padding: 6px 0; text-align: center; }
</style>
