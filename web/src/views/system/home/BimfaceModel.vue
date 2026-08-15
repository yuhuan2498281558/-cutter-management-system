<template>
  <div ref="wrapRef" class="bm-wrap">
    <!-- 加载/错误遮罩 -->
    <div v-if="modelState !== 'ready'" class="bm-overlay" :class="{ error: modelState === 'error' }">
      <template v-if="modelState === 'loading'">
        <el-icon class="spin"><Loading /></el-icon>
        <span>正在加载 BIM 模型...</span>
      </template>
      <template v-else>
        <el-icon><WarningFilled /></el-icon>
        <span>{{ errorMsg }}</span>
        <el-button size="small" type="primary" style="margin-top:8px" @click="initModel">重试</el-button>
      </template>
    </div>

    <!-- BIMFace 容器 -->
    <div ref="bimContainer" class="bm-viewer"></div>

    <!-- 热点 SVG 层 -->
    <svg
      v-if="modelState === 'ready' && hasPositions"
      class="bm-hotspot-svg"
      :width="svgW"
      :height="svgH"
      :viewBox="`0 0 ${svgW} ${svgH}`"
    >
      <g
        v-for="pos in screenPositions"
        :key="pos.code"
        style="cursor:pointer"
        @click="onHotspotClick(pos)"
      >
        <!-- 彩色标签框 -->
        <rect
          :x="pos.px * svgW - LABEL_W / 2"
          :y="pos.py * svgH - LABEL_H / 2"
          :width="LABEL_W"
          :height="LABEL_H"
          rx="3"
          :fill="labelFill(pos.code)"
          :stroke="selectedCode === pos.code ? '#fff' : labelStroke(pos.code)"
          :stroke-width="selectedCode === pos.code ? 2 : 1"
          opacity="0.92"
        />
        <text
          :x="pos.px * svgW"
          :y="pos.py * svgH + 4"
          text-anchor="middle"
          font-size="9"
          font-weight="600"
          :fill="labelTextColor(pos.code)"
          style="pointer-events:none;text-shadow:none"
        >{{ pos.code }}</text>
      </g>
    </svg>

    <!-- 图例 -->
    <div v-if="modelState === 'ready' && hasPositions" class="bm-legend">
      <div v-for="item in LEGEND" :key="item.label" class="legend-item">
        <span class="legend-dot" :style="{ background: item.fill, border: `1px solid ${item.stroke}` }"></span>
        <span>{{ item.label }}</span>
      </div>
    </div>

    <!-- 刀位信息面板 -->
    <transition name="panel-slide">
      <div v-if="false" class="bm-panel">
        <div class="bm-panel-header">
          <span>刀位详情 — {{ selectedCutter.code }}</span>
          <button class="bm-close" @click="selectedCutter = null; selectedCode = ''">×</button>
        </div>
        <div v-if="infoLoading" class="bm-loading">
          <el-icon class="spin"><Loading /></el-icon> 加载中...
        </div>
        <div v-else class="bm-panel-body">
          <section>
            <h6>基本信息</h6>
            <div class="row"><span>刀位编号</span><span>{{ selectedCutter.code }}</span></div>
            <div class="row"><span>刀具类型</span><span>{{ selectedCutter.type }}</span></div>
            <div class="row">
              <span>磨损状态</span>
              <span :style="{ color: statusColor(selectedCutter.code) }">{{ wearLabel(selectedCutter.code) }}</span>
            </div>
          </section>
          <section>
            <h6>当前刀具</h6>
            <template v-if="selectedCutter.current">
              <div class="row"><span>刀具名称</span><span>{{ selectedCutter.current.name }}</span></div>
              <div class="row"><span>刀具编号</span><span>{{ selectedCutter.current.serialNumber }}</span></div>
              <div class="row"><span>开始环号</span><span>{{ selectedCutter.current.startRing }}</span></div>
              <div v-if="selectedCutter.current.installDate" class="row">
                <span>安装日期</span><span>{{ selectedCutter.current.installDate }}</span>
              </div>
            </template>
            <div v-else class="empty">暂无数据</div>
          </section>
          <section>
            <h6>历史记录</h6>
            <div v-if="selectedCutter.history?.length" class="history">
              <div v-for="(h, i) in selectedCutter.history" :key="i" class="history-item">
                <div class="history-title">
                  <span class="badge">{{ i + 1 }}</span>{{ h.serialNumber }}
                </div>
                <div class="detail">使用环号：{{ h.startRing }} → {{ h.endRing }}</div>
                <div v-if="h.ringsUsed != null" class="detail">使用环数：{{ h.ringsUsed }} 环</div>
                <div v-if="h.replacePart" class="detail">更换部位：{{ h.replacePart }}</div>
                <div v-if="h.wearType" class="detail">磨损类型：{{ h.wearType }}</div>
                <div v-if="h.wearDegree" class="detail">磨损程度：{{ h.wearDegree }}</div>
                <div class="detail">更换日期：{{ h.replaceDate }}</div>
              </div>
            </div>
            <div v-else class="empty">暂无历史记录</div>
          </section>
          <section class="structured-history">
            <h6>更换历史</h6>
            <div v-if="selectedCutter.history?.length" class="history">
              <div v-for="(h, i) in selectedCutter.history" :key="`clean-${i}`" class="history-item">
                <div class="history-title">
                  <span class="badge">{{ i + 1 }}</span>
                  <span class="history-name">{{ h.toolTypeName || '刀具' }} / {{ h.serialNumber || '-' }}</span>
                </div>
                <div class="history-grid">
                  <div class="detail"><span>厂家来源</span><b>{{ h.manufacturer || '-' }}</b></div>
                  <div v-if="h.brand" class="detail"><span>品牌</span><b>{{ h.brand }}</b></div>
                  <div class="detail"><span>环号区间</span><b>{{ h.startRing }} - {{ h.endRing }}</b></div>
                  <div class="detail"><span>使用环数</span><b>{{ h.ringsUsed ?? '-' }}</b></div>
                  <div class="detail"><span>成本类型</span><b>{{ costTypeText(h) }}</b></div>
                  <div v-if="h.wearType" class="detail"><span>磨损程度</span><b>{{ h.wearType }}</b></div>
                  <div v-if="h.replacePart" class="detail"><span>维修部件</span><b>{{ h.replacePart }}</b></div>
                  <div class="detail"><span>费用</span><b>{{ moneyText(h.price) }}</b></div>
                  <div class="detail"><span>更换时间</span><b>{{ h.replaceDate }}</b></div>
                  <div v-if="h.remark" class="detail"><span>备注</span><b>{{ h.remark }}</b></div>
                </div>
              </div>
            </div>
            <div v-else class="empty">暂无更换历史</div>
          </section>
        </div>
      </div>
    </transition>
    <transition name="panel-slide">
      <div v-if="selectedCutter" class="bm-panel">
        <div class="bm-panel-header">
          <span>刀位详情 - {{ selectedCutter.code }}</span>
          <el-button class="bm-close" text circle :icon="Close" @click="closePanel" />
        </div>
        <div v-if="infoLoading" class="bm-loading">
          <el-icon class="spin"><Loading /></el-icon> 正在加载...
        </div>
        <div v-else class="bm-panel-body">
          <section>
            <h6>基础信息</h6>
            <div class="info-grid">
              <div class="row"><span>刀位编号</span><span>{{ selectedCutter.code }}</span></div>
              <div class="row"><span>刀具类型</span><span>{{ selectedCutter.type }}</span></div>
              <div class="row">
                <span>磨损状态</span>
                <span :style="{ color: statusColor(selectedCutter.code) }">{{ selectedCutter.latestWearType || '-' }}</span>
              </div>
            </div>
          </section>
          <section>
            <h6>当前刀具</h6>
            <template v-if="selectedCutter.current">
              <div class="info-grid">
                <div class="row"><span>刀具名称</span><span>{{ selectedCutter.current.name || '-' }}</span></div>
                <div class="row"><span>刀具编号</span><span>{{ selectedCutter.current.serialNumber || '-' }}</span></div>
                <div class="row"><span>厂家来源</span><span>{{ selectedCutter.current.manufacturer || '-' }}</span></div>
                <div v-if="selectedCutter.current.brand" class="row"><span>品牌</span><span>{{ selectedCutter.current.brand }}</span></div>
                <div class="row"><span>开始环号</span><span>{{ selectedCutter.current.startRing ?? '-' }}</span></div>
                <div v-if="selectedCutter.current.installDate" class="row">
                  <span>安装日期</span><span>{{ selectedCutter.current.installDate }}</span>
                </div>
              </div>
            </template>
            <div v-else class="empty">暂无当前刀具数据</div>
          </section>
          <section>
            <h6>更换历史</h6>
            <div v-if="selectedCutter.history?.length" class="history">
              <div v-for="(h, i) in selectedCutter.history" :key="i" class="history-item">
                <div class="history-title">
                  <span class="badge">{{ i + 1 }}</span>
                  <span class="history-name">{{ h.serialNumber || '-' }}</span>
                </div>
                <div class="history-grid">
                  <div class="detail"><span>厂家来源</span><b>{{ h.manufacturer || '-' }}</b></div>
                  <div v-if="h.brand" class="detail"><span>品牌</span><b>{{ h.brand }}</b></div>
                  <div class="detail"><span>环号区间</span><b>{{ h.startRing }} - {{ h.endRing }}</b></div>
                  <div v-if="h.ringsUsed != null" class="detail"><span>使用环数</span><b>{{ h.ringsUsed }}</b></div>
                  <div v-if="h.replacementTypeDisplay || h.wearDegree" class="detail"><span>成本类型</span><b>{{ h.replacementTypeDisplay || h.wearDegree }}</b></div>
                  <div v-if="h.wearType" class="detail"><span>磨损程度</span><b>{{ h.wearType }}</b></div>
                  <div v-if="h.replacePart" class="detail"><span>维修部件</span><b>{{ h.replacePart }}</b></div>
                  <div v-if="h.price" class="detail"><span>费用</span><b>{{ h.price }}</b></div>
                  <div class="detail"><span>更换时间</span><b>{{ h.replaceDate }}</b></div>
                  <div v-if="h.remark" class="detail full"><span>备注</span><b>{{ h.remark }}</b></div>
                </div>
              </div>
            </div>
            <div v-else class="empty">暂无更换历史</div>
          </section>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue';
import { Close, Loading, WarningFilled } from '@element-plus/icons-vue';
import { request } from '/@/utils/service';
import { isActiveCutterPosition } from '/@/constants/cutterPositions';
import {
  getCutterInfo,
  getAllCutterStatus,
  getActiveCutterModelMappings,
  getBimfaceViewToken,
  type CutterPositionInfo,
  type WearCondition,
  type CutterStatus,
} from './cutterApi';

// 标定完成后，把 BimfaceMapper 导出的内容粘贴到此文件：
// src/constants/cutterScreenPositions.ts
// 然后取消下面两行注释：
// import { CUTTER_VIEWPOINT, CUTTER_SCREEN_POSITIONS } from '/@/constants/cutterScreenPositions';
// const SCREEN_POSITIONS = CUTTER_SCREEN_POSITIONS;
// const SAVED_VIEWPOINT = CUTTER_VIEWPOINT;

// 标定前临时占位
const screenPositions = ref<{ code: string; type: string; px: number; py: number }[]>([]);
const componentPositions = ref<Record<string, { code: string; type: string }>>({});
const SAVED_VIEWPOINT: any = null;

const BIMFACE_OFFICIAL_SDK_URL = 'https://static.bimface.com/api/BimfaceSDKLoader/BimfaceSDKLoader@latest-release.js';
const BIMFACE_LOCAL_SDK_URL = `${import.meta.env.BASE_URL === './' ? '/' : import.meta.env.BASE_URL}vendor/bimface/BimfaceSDKLoader@latest-release.js`;
const BIMFACE_SDK_URLS = [BIMFACE_LOCAL_SDK_URL, BIMFACE_OFFICIAL_SDK_URL];

// 标签尺寸
const LABEL_W = 36;
const LABEL_H = 16;

// 磨损状态颜色映射（参考刀盘巡检图配色）
const WEAR_COLORS: Record<string, { fill: string; stroke: string; text: string; label: string }> = {
  GOOD:     { fill: '#4caf50', stroke: '#2e7d32', text: '#fff', label: '良好' },
  NORMAL:   { fill: '#9e9e9e', stroke: '#616161', text: '#fff', label: '正常磨损' },
  MODERATE: { fill: '#ff9800', stroke: '#e65100', text: '#fff', label: '中度磨损' },
  SEVERE:   { fill: '#e53935', stroke: '#b71c1c', text: '#fff', label: '严重磨损' },
  ABNORMAL: { fill: '#e91e9e', stroke: '#880e4f', text: '#fff', label: '异常磨损' },
  UNKNOWN:  { fill: '#37474f', stroke: '#263238', text: '#ccc', label: '未检测' },
};

const LEGEND = Object.entries(WEAR_COLORS).map(([, v]) => ({
  fill: v.fill, stroke: v.stroke, label: v.label,
}));

const wrapRef = ref<HTMLDivElement>();
const bimContainer = ref<HTMLDivElement>();
const modelState = ref<'loading' | 'ready' | 'error'>('loading');
const errorMsg = ref('');

const svgW = ref(0);
const svgH = ref(0);

const selectedCode = ref('');
const selectedCutter = ref<CutterPositionInfo | null>(null);
const infoLoading = ref(false);

// 所有刀位状态（从后端批量拉取）
const allStatus = ref<Record<string, CutterStatus>>({});

const hasPositions = computed(() => screenPositions.value.length > 0);

let bimApp: any = null;
let viewer: any = null;
let ro: ResizeObserver | null = null;
let initSeq = 0;
let viewAddedTimer: ReturnType<typeof setTimeout> | null = null;
let contextRestoreTimer: ReturnType<typeof setTimeout> | null = null;
let webglCanvas: HTMLCanvasElement | null = null;

function getWearColors(code: string) {
  const wc = allStatus.value[code]?.wear_condition ?? 'UNKNOWN';
  return WEAR_COLORS[wc] ?? WEAR_COLORS.UNKNOWN;
}

function labelFill(code: string) { return getWearColors(code).fill; }
function labelStroke(code: string) { return getWearColors(code).stroke; }
function labelTextColor(code: string) { return getWearColors(code).text; }
function statusColor(code: string) { return getWearColors(code).fill; }
function wearLabel(code: string) { return getWearColors(code).label; }

function closePanel() {
  selectedCutter.value = null;
  selectedCode.value = '';
}

function costTypeText(h: any) {
  const type = h.replacementTypeDisplay || h.wearDegree || '-';
  if (h.replacePart) return `${type} (repair cost, part: ${h.replacePart})`;
  if (type.includes('REPAIR') || type.includes('repair')) return type + ' (repair cost)';
  if (type.includes('COMPLETE') || type.includes('complete')) return type + ' (whole cutter cost)';
  return type;
}

function moneyText(value: number | undefined) {
  return value ? String(value) + ' CNY' : '-';
}

function syncSize() {
  if (!wrapRef.value) return;
  const { width, height } = wrapRef.value.getBoundingClientRect();
  svgW.value = width;
  svgH.value = height;
}

function restoreViewpoint() {
  if (!viewer || !SAVED_VIEWPOINT) return;
  try {
    viewer.setViewpoint?.(SAVED_VIEWPOINT)
      ?? viewer.setCameraStatus?.(SAVED_VIEWPOINT)
      ?? viewer.setCamera?.(SAVED_VIEWPOINT);
  } catch (_) {}
}

function fitModelToView() {
  if (!viewer) return;
  try {
    viewer.resize?.();
    viewer.zoomToSelectedComponents?.([]);
    viewer.zoomToFit?.();
    viewer.fitAll?.();
    viewer.home?.();
    viewer.render?.();
  } catch (_) {
    try {
      viewer.render?.();
    } catch (_) {}
  }
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) { resolve(); return; }
    const s = document.createElement('script');
    s.src = src; s.charset = 'utf-8';
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('BIMFace SDK 脚本加载失败'));
    document.head.appendChild(s);
  });
}

async function loadBimfaceSdk() {
  let lastError: unknown = null;
  for (const src of BIMFACE_SDK_URLS) {
    try {
      await loadScript(src);
      return;
    } catch (e) {
      lastError = e;
    }
  }
  throw lastError ?? new Error('BIMFace SDK load failed');
}

async function fetchViewToken(): Promise<string> {
  const res = await request({ url: '/api/bimface/view-token/', method: 'get' });
  const token = res?.viewToken ?? res?.data?.viewToken;
  if (!token) throw new Error('未获取到 viewToken');
  return token;
}

function scheduleModelReinit(seq: number, delay = 800) {
  if (contextRestoreTimer) {
    clearTimeout(contextRestoreTimer);
    contextRestoreTimer = null;
  }
  contextRestoreTimer = setTimeout(() => {
    contextRestoreTimer = null;
    if (seq !== initSeq) return;
    initModel();
  }, delay);
}

function handleWebglContextLost(event: Event) {
  event.preventDefault();
  modelState.value = 'loading';
  errorMsg.value = '';
  scheduleModelReinit(initSeq);
}

function handleWebglContextRestored() {
  scheduleModelReinit(initSeq, 100);
}

function clearWebglContextHandlers() {
  if (webglCanvas) {
    webglCanvas.removeEventListener('webglcontextlost', handleWebglContextLost);
    webglCanvas.removeEventListener('webglcontextrestored', handleWebglContextRestored);
    webglCanvas = null;
  }
}

function bindWebglContextHandlers() {
  const canvas = bimContainer.value?.querySelector('canvas') as HTMLCanvasElement | null;
  if (!canvas || canvas === webglCanvas) return;
  clearWebglContextHandlers();
  webglCanvas = canvas;
  webglCanvas.addEventListener('webglcontextlost', handleWebglContextLost);
  webglCanvas.addEventListener('webglcontextrestored', handleWebglContextRestored);
}

function destroyBimfaceInstance() {
  if (viewAddedTimer) {
    clearTimeout(viewAddedTimer);
    viewAddedTimer = null;
  }
  if (contextRestoreTimer) {
    clearTimeout(contextRestoreTimer);
    contextRestoreTimer = null;
  }
  clearWebglContextHandlers();
  try {
    viewer?.destroy?.();
  } catch (_) {}
  try {
    bimApp?.destroy?.();
  } catch (_) {}
  viewer = null;
  bimApp = null;
  if (bimContainer.value) {
    bimContainer.value.innerHTML = '';
  }
}

async function initModel() {
  const seq = ++initSeq;
  destroyBimfaceInstance();
  modelState.value = 'loading';
  errorMsg.value = '';
  try {
    await loadBimfaceSdk();
    const viewToken = await getBimfaceViewToken(true);

    const W = window as any;
    if (!W.BimfaceSDKLoaderConfig || !W.BimfaceSDKLoader || !W.Glodon?.Bimface) {
      throw new Error('BIMFace SDK not ready');
    }
    const loaderConfig = new W.BimfaceSDKLoaderConfig();
    loaderConfig.viewToken = viewToken;

    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));

    W.BimfaceSDKLoader.load(
      loaderConfig,
      () => {
        if (seq !== initSeq) return;
        const cfg = new W.Glodon.Bimface.Application.WebApplication3DConfig();
        cfg.domElement = bimContainer.value;
        bimApp = new W.Glodon.Bimface.Application.WebApplication3D(cfg);
        viewer = bimApp.getViewer();
        const onViewAdded = () => {
          if (seq !== initSeq) return;
          if (viewAddedTimer) {
            clearTimeout(viewAddedTimer);
            viewAddedTimer = null;
          }
          fitModelToView();
          modelState.value = 'ready';
          syncSize();
          restoreViewpoint();
          bindWebglContextHandlers();
          bindModelSelection(W);
        };
        viewer.addEventListener(W.Glodon.Bimface.Viewer.Viewer3DEvent.ViewAdded, onViewAdded);
        bimApp.addView(viewToken);
        viewAddedTimer = setTimeout(() => {
          if (seq !== initSeq || modelState.value === 'ready') return;
          modelState.value = 'error';
          errorMsg.value = 'BIM 模型加载超时，请检查 BIMFace 模型资源网络或 viewToken 是否有效';
        }, 8000);
      },
      (err: any) => {
        if (seq !== initSeq) return;
        modelState.value = 'error';
        errorMsg.value = `BIMFace init failed: ${JSON.stringify(err)}`;
      },
    );
  } catch (e: any) {
    if (seq !== initSeq) return;
    modelState.value = 'error';
    errorMsg.value = e.message ?? 'Model load failed';
  }
}

async function onHotspotClick(pos: { code: string; type: string }) {
  selectedCode.value = pos.code;
  selectedCutter.value = { code: pos.code, type: pos.type };
  infoLoading.value = true;
  try {
    selectedCutter.value = await getCutterInfo(pos.code);
  } finally {
    infoLoading.value = false;
  }
}

function extractComponentId(payload: any): string {
  const candidates = [
    payload?.objectId,
    payload?.objectID,
    payload?.elementId,
    payload?.elementID,
    payload?.componentId,
    payload?.componentID,
    payload?.id,
    payload?.object?.objectId,
    payload?.object?.id,
    payload?.data?.objectId,
    payload?.data?.id,
  ];
  const found = candidates.find((v) => v !== undefined && v !== null && String(v).trim() !== '');
  return found ? String(found) : '';
}

function readSelectedComponentId(): string {
  const selected =
    viewer?.getSelectedComponents?.()
    ?? viewer?.getSelectedIds?.()
    ?? viewer?.getSelection?.()
    ?? viewer?.getSelectedElements?.();
  if (Array.isArray(selected)) {
    return extractComponentId(selected[0]) || (selected[0] != null ? String(selected[0]) : '');
  }
  return extractComponentId(selected);
}

function bindModelSelection(W: any) {
  const events = W?.Glodon?.Bimface?.Viewer?.Viewer3DEvent ?? {};
  const eventNames = [
    events.SelectionChanged,
    events.ComponentsSelectionChanged,
    events.MouseClicked,
    events.MouseClick,
    'SelectionChanged',
    'ComponentsSelectionChanged',
    'MouseClicked',
    'MouseClick',
  ].filter(Boolean);

  const handler = (payload: any) => {
    const componentId = extractComponentId(payload) || readSelectedComponentId();
    const mapped = componentPositions.value[componentId];
    if (mapped) onHotspotClick(mapped);
  };

  eventNames.forEach((eventName: string) => {
    try {
      viewer?.addEventListener?.(eventName, handler);
    } catch (_) {}
  });
}

onMounted(async () => {
  initModel();
  const [mappings, status] = await Promise.all([
    getActiveCutterModelMappings(),
    getAllCutterStatus(),
  ]);
  screenPositions.value = mappings
    .filter(item => isActiveCutterPosition(item.cutter_position_no) && item.screen_x != null && item.screen_y != null)
    .map(item => ({
      code: item.cutter_position_no,
      type: item.tool_type_display || item.tool_type || '',
      px: Number(item.screen_x),
      py: Number(item.screen_y),
    }));
  componentPositions.value = mappings.reduce((acc, item) => {
    if (item.component_id) {
      if (!isActiveCutterPosition(item.cutter_position_no)) return acc;
      acc[String(item.component_id)] = {
        code: item.cutter_position_no,
        type: item.tool_type_display || item.tool_type || '',
      };
    }
    return acc;
  }, {} as Record<string, { code: string; type: string }>);
  allStatus.value = status;
  ro = new ResizeObserver(syncSize);
  if (wrapRef.value) ro.observe(wrapRef.value);
});

onUnmounted(() => {
  ro?.disconnect();
  initSeq += 1;
  destroyBimfaceInstance();
});
</script>

<style scoped>
.bm-wrap {
  position: absolute;
  inset: 0;
}

.bm-viewer {
  position: absolute;
  inset: 0;
}

.bm-hotspot-svg {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
}

/* SVG rect/text need pointer-events: all via the parent <g> */

/* 遮罩 */
.bm-overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: rgba(10, 10, 10, 0.82);
  color: #aaa;
  font-size: 14px;
}
.bm-overlay.error { color: #e74c3c; }

/* 图例 */
.bm-legend {
  position: absolute;
  bottom: 12px;
  left: 12px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  background: rgba(15, 15, 15, 0.78);
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  padding: 8px 12px;
  z-index: 25;
  pointer-events: none;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11px;
  color: #ccc;
}

.legend-dot {
  width: 12px;
  height: 12px;
  border-radius: 2px;
  flex-shrink: 0;
}

/* 信息面板 */
.bm-panel {
  position: absolute;
  top: 16px;
  right: 16px;
  width: min(380px, calc(100% - 32px));
  max-height: calc(100% - 32px);
  overflow-y: auto;
  background: rgba(18, 22, 27, 0.97);
  border: 1px solid rgba(89, 201, 194, 0.24);
  border-radius: 8px;
  color: #e8edf1;
  z-index: 30;
  backdrop-filter: blur(6px);
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.35);
}

.bm-panel-header {
  position: sticky;
  top: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 12px 12px 14px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  background: rgba(18, 22, 27, 0.98);
  font-size: 13px;
  font-weight: 600;
  z-index: 1;
}

.bm-close {
  color: #d7e2e5;
  font-size: 16px;
  flex-shrink: 0;
}
.bm-close:hover {
  color: #fff;
  background: rgba(255,255,255,0.1);
}

.bm-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 20px 14px;
  color: #888;
  font-size: 13px;
}

.bm-panel-body { padding: 0 0 10px; }

section {
  padding: 12px 14px;
  border-bottom: 1px solid rgba(255,255,255,0.07);
}
section:last-child { border-bottom: none; }
.bm-panel-body > section:nth-of-type(3):not(.structured-history) { display: none; }

h6 {
  margin: 0 0 8px;
  font-size: 11px;
  color: #4ecdc4;
  text-transform: uppercase;
  letter-spacing: 0.6px;
}

.info-grid {
  display: grid;
  gap: 6px;
}

.row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 10px;
  font-size: 12px;
  padding: 6px 0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
}
.row:last-child { border-bottom: none; }
.row span:first-child { color: #8a969b; }
.row span:last-child {
  color: #eef4f6;
  font-weight: 500;
  min-width: 0;
  overflow-wrap: anywhere;
  text-align: right;
}

.empty { color: #7b858a; font-size: 12px; text-align: center; padding: 10px 0; }

.history {
  display: grid;
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
  padding-right: 2px;
}

.history-item {
  background: rgba(255,255,255,0.045);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 6px;
  padding: 9px 10px;
  font-size: 12px;
}

.history-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  margin-bottom: 8px;
  padding-bottom: 7px;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  font-size: 13px;
}

.history-name {
  min-width: 0;
  overflow-wrap: anywhere;
}

.badge {
  background: #4ecdc4;
  color: #000;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  flex-shrink: 0;
}

.history-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0;
}

.detail {
  display: grid;
  grid-template-columns: 86px minmax(0, 1fr);
  gap: 10px;
  color: #96a1a6;
  margin: 0;
  padding: 6px 0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  min-width: 0;
}

.detail:last-child { border-bottom: none; }

.detail span {
  font-size: 11px;
  color: #7f8a8f;
}

.detail b {
  color: #edf4f6;
  font-weight: 500;
  overflow-wrap: anywhere;
  text-align: right;
}

.spin { animation: spin 1s linear infinite; font-size: 24px; }
@keyframes spin { to { transform: rotate(360deg); } }

.panel-slide-enter-active,
.panel-slide-leave-active { transition: opacity 0.2s, transform 0.2s; }
.panel-slide-enter-from,
.panel-slide-leave-to { opacity: 0; transform: translateX(16px); }
</style>
