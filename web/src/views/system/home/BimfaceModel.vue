<template>
  <div ref="wrapRef" class="bm-wrap">
    <!-- 加载/错误遮罩：浅底，模型就绪后淡出 -->
    <transition name="bm-fade">
      <div v-if="modelState !== 'ready'" class="bm-overlay" :class="{ error: modelState === 'error' }">
        <template v-if="modelState === 'loading'">
          <span class="bm-spinner" aria-hidden="true"></span>
          <span class="bm-overlay-text">正在加载 BIM 模型</span>
        </template>
        <template v-else>
          <el-icon class="bm-overlay-icon"><WarningFilled /></el-icon>
          <span class="bm-overlay-text">{{ errorMsg }}</span>
          <el-button size="small" type="primary" @click="retryModel">重试</el-button>
        </template>
      </div>
    </transition>

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
    <div v-if="modelState === 'ready' && (hasPositions || dataError)" class="bm-legend">
      <div v-if="dataError" class="legend-error">刀位数据加载失败</div>
      <template v-if="hasPositions">
        <div v-for="item in LEGEND" :key="item.label" class="legend-item">
          <span class="legend-dot" :style="{ background: item.fill, border: `1px solid ${item.stroke}` }"></span>
          <span>{{ item.label }}</span>
        </div>
      </template>
    </div>

    <!-- 刀位信息面板 -->
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
            <div v-else class="empty">{{ selectedCutter.loadFailed ? '刀位数据加载失败' : '暂无当前刀具数据' }}</div>
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
            <div v-else class="empty">{{ selectedCutter.loadFailed ? '刀位数据加载失败' : '暂无更换历史' }}</div>
          </section>
        </div>
      </div>
    </transition>
  </div>
</template>

<script lang="ts">
// 模块级缓存：同一个 SDK 脚本在页面里只下载一次。加载中的重复调用共用同一个过程，
// 加载失败时移除标签并删掉缓存，点"重试"才会真正重新下载。
const scriptLoads = new Map<string, Promise<void>>();

function loadScript(src: string): Promise<void> {
  const loading = scriptLoads.get(src);
  if (loading) return loading;
  const next = new Promise<void>((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src; s.charset = 'utf-8';
    s.onload = () => resolve();
    s.onerror = () => {
      s.remove();
      scriptLoads.delete(src);
      reject(new Error('BIMFace SDK 脚本加载失败'));
    };
    document.head.appendChild(s);
  });
  scriptLoads.set(src, next);
  return next;
}
</script>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue';
import { Close, Loading, WarningFilled } from '@element-plus/icons-vue';
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
// 刀位状态或模型映射接口失败：和"没有数据"区分开显示。
const dataError = ref(false);

// 遮罩上给用户看的错误提示，原始错误只在开发环境输出到控制台。
const BIM_ERRORS = {
  webgl: '当前浏览器无法创建 WebGL 上下文，请释放系统内存后完全退出并重启浏览器，并确认硬件加速已开启',
  sdkNotReady: 'BIM 组件未就绪，请点击重试',
  initFailed: 'BIM 模型初始化失败，请点击重试',
  loadFailed: 'BIM 模型加载失败，请点击重试',
};

// 60 秒内 WebGL 上下文丢失超过 2 次就不再自动重建，避免在 GPU 资源不足时反复加载。
const WEBGL_LOSS_WINDOW_MS = 60 * 1000;
const MAX_WEBGL_REBUILDS = 2;

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
// 刀位详情请求序号：只采用最新一次点击的结果，关闭面板后迟到的结果也丢弃。
let infoSeq = 0;
let webglLossTimes: number[] = [];
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
  infoSeq += 1;
  infoLoading.value = false;
  selectedCutter.value = null;
  selectedCode.value = '';
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
  const now = Date.now();
  webglLossTimes = [...webglLossTimes.filter(time => now - time < WEBGL_LOSS_WINDOW_MS), now];
  if (webglLossTimes.length > MAX_WEBGL_REBUILDS) {
    initSeq += 1;
    destroyBimfaceInstance();
    modelState.value = 'error';
    errorMsg.value = BIM_ERRORS.webgl;
    return;
  }
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

function canCreateWebglContext() {
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('webgl2')
    || canvas.getContext('webgl')
    || canvas.getContext('experimental-webgl');
  if (!context) return false;
  (context as WebGLRenderingContext).getExtension('WEBGL_lose_context')?.loseContext();
  return true;
}

function showModelError(seq: number, message: string, error?: unknown) {
  if (seq !== initSeq) return;
  modelState.value = 'error';
  errorMsg.value = message;
  if (import.meta.env.DEV && error) console.warn('BIMFace error:', error);
}

function retryModel() {
  webglLossTimes = [];
  initModel();
}

async function initModel() {
  const seq = ++initSeq;
  destroyBimfaceInstance();
  modelState.value = 'loading';
  errorMsg.value = '';
  if (!canCreateWebglContext()) {
    showModelError(seq, BIM_ERRORS.webgl);
    return;
  }
  // 当前这一步失败时给用户看的提示。
  let failureMessage = BIM_ERRORS.sdkNotReady;
  try {
    await loadBimfaceSdk();
    if (seq !== initSeq) return;
    failureMessage = BIM_ERRORS.loadFailed;
    const viewToken = await getBimfaceViewToken(true);
    if (seq !== initSeq) return;

    const W = window as any;
    if (!W.BimfaceSDKLoaderConfig || !W.BimfaceSDKLoader || !W.Glodon?.Bimface) {
      showModelError(seq, BIM_ERRORS.sdkNotReady);
      return;
    }
    const loaderConfig = new W.BimfaceSDKLoaderConfig();
    loaderConfig.viewToken = viewToken;

    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
    if (seq !== initSeq) return;

    W.BimfaceSDKLoader.load(
      loaderConfig,
      () => {
        if (seq !== initSeq) return;
        let initStage = '创建 BIM 应用';
        try {
          const cfg = new W.Glodon.Bimface.Application.WebApplication3DConfig();
          cfg.domElement = bimContainer.value;
          bimApp = new W.Glodon.Bimface.Application.WebApplication3D(cfg);
          initStage = '加载 BIM 视图';
          bimApp.addView(viewToken);
          initStage = '获取 BIM 查看器';
          viewer = bimApp.getViewer();
          initStage = '注册 BIM 事件';
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
          viewAddedTimer = setTimeout(() => {
            if (seq !== initSeq || modelState.value === 'ready') return;
            modelState.value = 'error';
            errorMsg.value = 'BIM 模型加载超时，请检查 BIMFace 模型资源网络或 viewToken 是否有效';
          }, 8000);
        } catch (e: any) {
          showModelError(seq, BIM_ERRORS.initFailed, `${initStage}: ${e?.message || e}`);
        }
      },
      (err: any) => showModelError(seq, BIM_ERRORS.initFailed, err),
    );
  } catch (e: any) {
    showModelError(seq, failureMessage, e);
  }
}

async function onHotspotClick(pos: { code: string; type: string }) {
  // 同一刀位正在加载时不再重复请求。
  if (infoLoading.value && selectedCode.value === pos.code) return;
  const seq = ++infoSeq;
  selectedCode.value = pos.code;
  selectedCutter.value = { code: pos.code, type: pos.type };
  infoLoading.value = true;
  try {
    const info = await getCutterInfo(pos.code);
    if (seq === infoSeq) selectedCutter.value = info;
  } finally {
    if (seq === infoSeq) infoLoading.value = false;
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
  // SDK 的枚举值可能就是同名字符串，去重后再注册，避免一次点击发多次请求。
  const eventNames = [...new Set([
    events.SelectionChanged,
    events.ComponentsSelectionChanged,
    events.MouseClicked,
    events.MouseClick,
    'SelectionChanged',
    'ComponentsSelectionChanged',
    'MouseClicked',
    'MouseClick',
  ].filter(Boolean))];

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
  const markDataError = () => { dataError.value = true; };
  const [mappings, status] = await Promise.all([
    getActiveCutterModelMappings(markDataError),
    getAllCutterStatus(markDataError),
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
  infoSeq += 1;
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

/* 遮罩：与页面一致的浅底，居中一个细圆环和一行文字 */
.bm-overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 24px;
  box-sizing: border-box;
  background: var(--dv-tile);
  color: var(--dv-text-secondary);
  font-size: var(--dv-font-size);
}

.bm-spinner {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 2px solid var(--dv-border-strong);
  border-top-color: var(--dv-accent);
  box-sizing: border-box;
  animation: spin 0.9s linear infinite;
}

.bm-overlay-text {
  max-width: 360px;
  line-height: var(--dv-line-height);
  text-align: center;
}

.bm-overlay.error { color: var(--dv-text-regular); }
.bm-overlay-icon { font-size: 26px; color: var(--dv-danger); }

.bm-fade-leave-active { transition: opacity 0.2s ease; }
.bm-fade-leave-to { opacity: 0; }

@media (prefers-reduced-motion: reduce) {
  .bm-spinner { animation-duration: 2.4s; }
}

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

.legend-error {
  font-size: 11px;
  color: #ff8a80;
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
