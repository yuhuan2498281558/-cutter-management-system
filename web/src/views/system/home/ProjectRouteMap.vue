<template>
  <section :class="['route-map-panel', { fullscreen: isFullscreen }]">
    <header class="route-map-header">
      <div class="route-title">
        <h3>二维地质纵断面与开仓环号</h3>
        <p>{{ projectName || '示例盾构项目地质纵断面' }}</p>
      </div>
      <button class="fullscreen-btn" type="button" @click="toggleFullscreen">
        {{ isFullscreen ? '退出全屏' : '全屏' }}
      </button>
    </header>

    <div class="route-map-body" ref="bodyRef">
      <div class="profile-stage" ref="stageRef" @dblclick="toggleFullscreen">
        <canvas ref="canvasRef" class="pdf-canvas" />

        <!-- 标注层：与 canvas 等高等宽，叠加在上方 -->
        <div class="ring-overlay">
          <div class="ring-axis">
            <i class="axis-line"></i>
            <i class="axis-progress" :style="{ width: `${currentPercent}%` }"></i>
          </div>

          <button
            v-for="point in openingPoints"
            :key="point.id"
            class="ring-marker opening-marker"
            type="button"
            :style="{ left: `${point.percent}%` }"
            :title="`第${point.ringNo}环开仓`"
            @click="selectPoint(point)"
          >
            {{ point.ringNo }}
          </button>

          <button
            v-if="currentPoint"
            class="ring-marker current-marker"
            type="button"
            :style="{ left: `${currentPoint.percent}%` }"
            :title="`当前第${currentPoint.ringNo}环`"
            @click="selectPoint(currentPoint)"
          >
            当前 {{ currentPoint.ringNo }}
          </button>

          <div v-if="selectedPoint" class="point-popover" :style="{ left: popoverLeft }">
            <div class="popover-title">第 {{ selectedPoint.ringNo }} 环</div>
            <div class="popover-row">
              <span>类型</span>
              <strong>{{ selectedPoint.kind === 'current' ? '当前掘进位置' : '开仓记录' }}</strong>
            </div>
            <div class="popover-row">
              <span>日期</span>
              <strong>{{ formatDate(selectedPoint.openTime) }}</strong>
            </div>
            <div class="popover-row">
              <span>地层</span>
              <strong>{{ selectedPoint.stratumText || '待导入' }}</strong>
            </div>
          </div>
        </div>

        <div v-if="pdfLoading" class="pdf-loading">PDF 加载中…</div>
        <div v-if="pdfError" class="pdf-error">{{ pdfError }}</div>
      </div>
    </div>

    <footer class="route-footer">
      <span><i class="dot completed"></i>当前进度 {{ currentPercent }}%</span>
      <span><i class="dot opening"></i>开仓 {{ openingPoints.length }} 次</span>
      <span><i class="dot remaining"></i>地层信息 {{ stratumCount }} 环</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { request } from '/@/utils/service';
import { GetHomeProjectInfo } from './api';

type RingPoint = {
  id: string;
  ringNo: string;
  ringValue: number;
  percent: number;
  kind: 'opening' | 'current';
  openTime?: string;
  stratumText?: string;
};

type StratumItem = {
  ring_no: string;
  stratum_info?: string;
  stratum_types_list?: { name?: string; code?: string }[];
};

const bodyRef = ref<HTMLDivElement | null>(null);
const stageRef = ref<HTMLDivElement | null>(null);
const canvasRef = ref<HTMLCanvasElement | null>(null);
const pdfLoading = ref(false);
const pdfError = ref('');

const projectName = ref('');
const estimatedTotalRings = ref(0);
const openingPoints = ref<RingPoint[]>([]);
const selectedPoint = ref<RingPoint | null>(null);
const isFullscreen = ref(false);
const stratumMap = ref<Record<string, string>>({});
const stratumCount = ref(0);
// ringNo(string) → x百分比，来自PDF真实坐标
const pdfRingMap = ref<Record<string, number>>({});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let pdfPage: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let pdfDoc: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let renderTask: any = null;
let resizeObserver: ResizeObserver | null = null;
let resizeTimer: ReturnType<typeof window.setTimeout> | null = null;

const MAX_CANVAS_PIXELS = 16000000;

const currentPoint = computed<RingPoint | null>(() => {
  const latest = openingPoints.value[openingPoints.value.length - 1];
  if (!latest) return null;
  return { ...latest, id: 'current-ring', kind: 'current' };
});

const currentPercent = computed(() => (currentPoint.value ? Math.round(currentPoint.value.percent) : 0));

const popoverLeft = computed(() => {
  if (!selectedPoint.value) return '16px';
  const percent = selectedPoint.value.percent;
  if (percent < 18) return '16px';
  if (percent > 82) return 'calc(100% - 248px)';
  return `calc(${percent}% - 116px)`;
});

// 线性兜底：当 PDF 坐标未覆盖某环号时使用
function ringToPercentLinear(ring: number, total: number) {
  return Math.min(100, Math.max(0, (ring / Math.max(total, 1)) * 100));
}

function ringNoToPercent(ringNo: string, ringValue: number, total: number): number {
  const fromPdf = pdfRingMap.value[ringNo];
  if (fromPdf !== undefined) return fromPdf;

  // 尝试用数字值查找
  const fromPdfByValue = pdfRingMap.value[String(ringValue)];
  if (fromPdfByValue !== undefined) return fromPdfByValue;

  // 使用线性兜底
  return ringToPercentLinear(ringValue, total);
}

function buildStratumText(item: StratumItem) {
  const names = (item.stratum_types_list || []).map((type) => type.name || type.code).filter(Boolean);
  if (names.length) return names.join('、');
  return item.stratum_info || '';
}

async function renderPdf() {
  if (!canvasRef.value || !stageRef.value) return;
  if (!pdfPage) {
    const canvas = canvasRef.value;
    const width = Math.max(stageRef.value.clientWidth, 900);
    const height = isFullscreen.value ? Math.max(window.innerHeight - 160, 320) : 320;
    const dpr = Math.min(Math.max(window.devicePixelRatio || 1, 1), 2);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.fillStyle = '#eef3f6';
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = '#c8d5dd';
    ctx.lineWidth = 1;
    for (let x = 0; x <= width; x += 80) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
    for (let y = 0; y <= height; y += 40) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }
    ctx.strokeStyle = '#567b8f';
    ctx.lineWidth = 3;
    ctx.beginPath();
    for (let x = 0; x <= width; x += 12) {
      const y = height * 0.58 + Math.sin(x / 90) * 18 + Math.sin(x / 31) * 5;
      if (x === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.fillStyle = '#567b8f';
    ctx.font = '14px sans-serif';
    ctx.fillText('示例地层剖面（请导入已获授权的项目资料）', 20, 28);
    return;
  }
  // 提高清晰度：最低 3 倍 DPR
  const dpr = Math.min(Math.max(window.devicePixelRatio || 1, 1), isFullscreen.value ? 1.5 : 2);
  const viewport1 = pdfPage.getViewport({ scale: 1, rotation: 0 });

  // PDF 是超宽图（9524×652），必须按高度缩放，让内容水平滚动
  // 全屏：撑满可用高度；普通：固定 320px 高度
  let targetH: number;
  if (isFullscreen.value) {
    const headerEl = stageRef.value.closest('.route-map-panel')?.querySelector('.route-map-header') as HTMLElement | null;
    const footerEl = stageRef.value.closest('.route-map-panel')?.querySelector('.route-footer') as HTMLElement | null;
    const headerH = headerEl ? headerEl.offsetHeight : 52;
    const footerH = footerEl ? footerEl.offsetHeight : 40;
    targetH = window.innerHeight - 32 - headerH - footerH - 4;
  } else {
    targetH = 320;
  }

  const scale = Math.max(0.05, targetH / viewport1.height);
  let renderScale = scale * dpr;
  let scaledViewport = pdfPage.getViewport({ scale: renderScale, rotation: 0 });
  const pixels = scaledViewport.width * scaledViewport.height;
  if (pixels > MAX_CANVAS_PIXELS) {
    renderScale *= Math.sqrt(MAX_CANVAS_PIXELS / pixels);
    scaledViewport = pdfPage.getViewport({ scale: renderScale, rotation: 0 });
  }
  const canvas = canvasRef.value;
  canvas.width = Math.round(scaledViewport.width);
  canvas.height = Math.round(scaledViewport.height);
  canvas.style.width = Math.round((scaledViewport.width / renderScale) * scale) + 'px';
  canvas.style.height = Math.round((scaledViewport.height / renderScale) * scale) + 'px';

  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  // 取消上一次未完成的渲染
  if (renderTask) {
    renderTask.cancel();
    renderTask = null;
  }

  renderTask = pdfPage.render({ canvasContext: ctx, viewport: scaledViewport });
  try {
    await renderTask.promise;
  } catch (e: any) {
    if (e?.name !== 'RenderingCancelledException') throw e;
  } finally {
    renderTask = null;
  }
}

async function waitLayout() {
  await nextTick();
  await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
}

// 蓝色环号在 y≈540（PyMuPDF 坐标），倒数第二行
// 里程数字在 y≈580，最下面一行，需要排除
async function extractRingPositions() {
  if (!pdfPage) return;
  try {
    const viewport = pdfPage.getViewport({ scale: 1, rotation: 0 });
    const textContent = await pdfPage.getTextContent();

    // 只取蓝色环号行：vy≈559.5（PDF.js坐标）
    const ringYMin = 555;
    const ringYMax = 565;
    const anchors: { ring: number; vx: number }[] = [];

    for (const item of textContent.items as any[]) {
      const str = (item.str || '').trim();
      // 只匹配 "数字环" 格式，排除纯数字（里程）
      const m = str.match(/^(\d{1,5})环$/);
      if (!m) continue;
      const val = parseInt(m[1], 10);
      if (val < 0 || val > 20000) continue;

      const tx = item.transform[4];
      const ty = item.transform[5];
      const [vx, vy] = viewport.convertToViewportPoint(tx, ty);
      // 只取倒数第二行（环号），排除最下面一行（里程）
      if (vy < ringYMin || vy > ringYMax) continue;

      anchors.push({ ring: val, vx });
    }

    if (anchors.length < 2) return;

    // 去重：同环号保留最小 vx
    const seen = new Map<number, number>();
    for (const a of anchors.sort((x, y) => x.vx - y.vx)) {
      if (!seen.has(a.ring)) seen.set(a.ring, a.vx);
    }

    const sorted = [...seen.entries()]
      .map(([ring, vx]) => ({ ring, vx }))
      .sort((a, b) => a.ring - b.ring);

    if (sorted.length < 2) return;

    // PDF 原始宽度（从 PyMuPDF 得知是 9524）
    const pdfWidth = 9524;

    const map: Record<string, number> = {};
    // 锚点：直接用 vx / pdfWidth 计算百分比
    for (const a of sorted) {
      map[String(a.ring)] = Math.min(100, Math.max(0, (a.vx / pdfWidth) * 100));
    }
    // 锚点间插值
    for (let i = 0; i < sorted.length - 1; i++) {
      const lo = sorted[i];
      const hi = sorted[i + 1];
      for (let r = lo.ring + 1; r < hi.ring; r++) {
        const t = (r - lo.ring) / (hi.ring - lo.ring);
        const vx = lo.vx + t * (hi.vx - lo.vx);
        map[String(r)] = Math.min(100, Math.max(0, (vx / pdfWidth) * 100));
      }
    }

    pdfRingMap.value = map;
  } catch (err) {
    console.error('PDF 环号提取失败:', err);
  }
}

async function loadPdf() {
  pdfLoading.value = true;
  pdfError.value = '';
  pdfRingMap.value = {};
  await renderPdf();
  pdfLoading.value = false;
}

async function loadProject() {
  try {
    const res: any = await GetHomeProjectInfo();
    const data = res?.data ?? res;
    projectName.value = data?.project_name || '';
    const length = Number(data?.tunnel_length);
    estimatedTotalRings.value = Number.isFinite(length) && length > 0 ? Math.round(length / 1.2) : 0;
  } catch {
    projectName.value = '示例盾构项目';
  }
}

async function loadStratum() {
  try {
    const res: any = await request({ url: '/api/shield/stratum_basic_info/', method: 'get', params: { limit: 5000, ordering: 'ring_no' } });
    const records: StratumItem[] = res.data?.results ?? res.data ?? [];
    const map: Record<string, string> = {};
    records.forEach((item) => {
      const ringNo = String(item.ring_no || '').trim();
      if (!ringNo) return;
      map[ringNo] = buildStratumText(item);
    });
    stratumMap.value = map;
    stratumCount.value = Object.keys(map).length;
  } catch {
    stratumMap.value = {};
    stratumCount.value = 0;
  }
}

async function loadOpenings() {
  try {
    const res: any = await request({ url: '/api/shield/warehouse_opening/', method: 'get', params: { limit: 500, ordering: 'ring_no' } });
    const records: any[] = res.data?.results ?? res.data ?? [];
    const sorted = records
      .filter((item) => Number.isFinite(Number(item.ring_no)))
      .sort((a, b) => Number(a.ring_no) - Number(b.ring_no));
    const maxRing = Math.max(...sorted.map((item) => Number(item.ring_no)), 0);
    const markerTotal = Math.max(estimatedTotalRings.value, maxRing, 1);

    openingPoints.value = sorted.map((item) => {
      const ringValue = Number(item.ring_no);
      const ringNo = String(item.ring_no);
      return {
        id: String(item.id ?? ringNo),
        ringNo,
        ringValue,
        percent: ringNoToPercent(ringNo, ringValue, markerTotal),
        kind: 'opening' as const,
        openTime: item.open_time,
        stratumText:
          stratumMap.value[ringNo] ||
          item.stratum_info_between_list?.map((s: any) => s.stratum_type_name).join('、') ||
          '',
      };
    });
    selectedPoint.value = currentPoint.value;
  } catch {
    openingPoints.value = [];
  }
}

function selectPoint(point: RingPoint) {
  selectedPoint.value = point;
}

function formatDate(value?: string) {
  return value ? value.slice(0, 10) : '-';
}

async function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value;
  await waitLayout();
  await renderPdf();
  if (isFullscreen.value) scrollToCurrentRing();
}

function scrollToCurrentRing() {
  if (!bodyRef.value || !canvasRef.value || !currentPoint.value) return;
  const canvasW = canvasRef.value.clientWidth || canvasRef.value.width;
  const bodyW = bodyRef.value.clientWidth;
  const targetX = (currentPoint.value.percent / 100) * canvasW;
  bodyRef.value.scrollLeft = targetX - bodyW / 2;
}

onMounted(async () => {
  await loadProject();
  await loadStratum();
  await loadPdf();  // 使用脱敏示意剖面；项目资料由部署者自行导入
  await loadOpenings();  // 再加载开仓数据，使用映射

  if (stageRef.value) {
    resizeObserver = new ResizeObserver(() => {
      if (resizeTimer) window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => renderPdf(), 120);
    });
    resizeObserver.observe(stageRef.value);
  }
});

onUnmounted(() => {
  resizeObserver?.disconnect();
  if (resizeTimer) {
    window.clearTimeout(resizeTimer);
    resizeTimer = null;
  }
  if (renderTask) {
    renderTask.cancel();
    renderTask = null;
  }
  pdfPage = null;
  pdfDoc?.destroy?.();
  pdfDoc = null;
  if (canvasRef.value) {
    canvasRef.value.width = 0;
    canvasRef.value.height = 0;
  }
});
</script>

<style scoped>
.route-map-panel {
  width: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.route-map-panel.fullscreen {
  position: fixed;
  inset: 16px;
  z-index: 3000;
  border: 1px solid rgba(15, 23, 42, 0.18);
  box-shadow: 0 24px 80px rgba(15, 23, 42, 0.35);
}

.route-map-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  background: #f8fafc;
  border-bottom: 1px solid #e5e7eb;
}

.route-title { min-width: 0; }

.route-map-header h3 {
  margin: 0;
  color: #111827;
  font-size: 14px;
  font-weight: 700;
}

.route-map-header p {
  margin: 3px 0 0;
  overflow: hidden;
  color: #6b7280;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fullscreen-btn {
  flex: 0 0 auto;
  height: 26px;
  padding: 0 9px;
  border: 1px solid #dbe3ef;
  border-radius: 6px;
  background: #fff;
  color: #2563eb;
  font-size: 12px;
  cursor: pointer;
}

.route-map-body {
  position: relative;
  min-height: 220px;
  background: #edf2f7;
  overflow: auto;
  flex: 1 1 0;
  min-width: 0;
}

.profile-stage {
  position: relative;
  display: inline-block;
  min-width: 100%;
}

.pdf-canvas {
  display: block;
  pointer-events: none;
}

/* 标注叠加层：撑满 canvas，绝对定位在上方 */
.ring-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.ring-overlay .ring-marker {
  pointer-events: auto;
}

.ring-axis {
  position: absolute;
  left: 3%;
  right: 3%;
  bottom: 34px;
  height: 8px;
  pointer-events: none;
}

.axis-line,
.axis-progress {
  position: absolute;
  top: 3px;
  left: 0;
  height: 3px;
  border-radius: 99px;
}

.axis-line {
  width: 100%;
  background: rgba(71, 85, 105, 0.42);
}

.axis-progress {
  background: #00897b;
}

.ring-marker {
  position: absolute;
  z-index: 2;
  border: 2px solid #fff;
  border-radius: 999px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.25);
  transform: translateX(-50%);
  cursor: pointer;
}

.opening-marker {
  bottom: 25px;
  min-width: 26px;
  height: 22px;
  padding: 0 6px;
  background: #7c3aed;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
}

.current-marker {
  bottom: 52px;
  height: 28px;
  padding: 0 10px;
  background: #d32f2f;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}

.point-popover {
  position: absolute;
  z-index: 3;
  bottom: 88px;
  width: 232px;
  padding: 10px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.18);
  pointer-events: auto;
}

.popover-title {
  margin-bottom: 6px;
  color: #111827;
  font-size: 13px;
  font-weight: 700;
}

.popover-row {
  display: grid;
  grid-template-columns: 42px 1fr;
  gap: 8px;
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.popover-row strong {
  color: #1f2937;
  font-weight: 600;
  word-break: break-word;
}

.pdf-loading,
.pdf-error {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: #6b7280;
  background: rgba(237, 242, 247, 0.85);
}

.pdf-error { color: #dc2626; }

.route-footer {
  display: flex;
  justify-content: space-around;
  gap: 8px;
  padding: 8px 10px;
  border-top: 1px solid #e5e7eb;
  color: #374151;
  font-size: 12px;
}

.dot {
  display: inline-block;
  width: 9px;
  height: 9px;
  margin-right: 5px;
  border-radius: 50%;
}

.dot.completed { background: #00897b; }
.dot.opening { background: #7c3aed; }
.dot.remaining { background: #f57c00; }
</style>
