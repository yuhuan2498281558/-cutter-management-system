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

    <div class="progress-summary">
      <div class="progress-heading">
        <strong>掘进进度 <b>{{ progressText }}</b></strong>
        <span>最新开仓 {{ openingStatusText }} / 图纸总量 {{ totalRings > 0 ? `${totalRings} 环` : pdfLoading ? '读取中…' : '读取失败' }}</span>
      </div>
      <div
        class="summary-track"
        :class="{ 'progress-unknown': currentPercent === null }"
        role="progressbar"
        aria-label="掘进进度（按最新开仓记录估算）"
        :aria-valuenow="currentPercent ?? undefined"
        :aria-valuetext="progressText"
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <i v-if="currentPercent !== null" class="summary-completed" :style="{ width: `${currentPercent}%` }"></i>
      </div>
      <div class="progress-caption">
        <span><i class="line-key completed"></i>已完成（估算）</span>
        <span><i class="line-key remaining"></i>待完成</span>
        <span>按最新开仓记录估算 · 总量取自图纸环号范围</span>
      </div>
    </div>

    <div class="route-map-body" ref="bodyRef">
      <div class="profile-stage" ref="stageRef" @dblclick="toggleFullscreen">
        <canvas ref="canvasRef" class="pdf-canvas" />

        <!-- 标注层：与 canvas 等高等宽，叠加在上方 -->
        <div v-if="ringRange" class="ring-overlay">
          <div class="ring-axis" :style="axisStyle">
            <i class="axis-line"></i>
            <i v-if="axisProgressPercent !== null" class="axis-progress" :style="{ width: `${axisProgressPercent}%` }"></i>
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
            :title="`最新开仓第${currentPoint.ringNo}环`"
            @click="selectPoint(currentPoint)"
          >
            最新开仓 {{ currentPoint.ringNo }}
          </button>

          <div v-if="selectedPoint" class="point-popover" :style="{ left: popoverLeft }">
            <div class="popover-title">第 {{ selectedPoint.ringNo }} 环</div>
            <div class="popover-row">
              <span>类型</span>
              <strong>{{ selectedPoint.kind === 'current' ? '最新开仓位置' : '开仓记录' }}</strong>
            </div>
            <div class="popover-row">
              <span>日期</span>
              <strong>{{ formatDate(selectedPoint.openTime) }}</strong>
            </div>
            <div class="popover-row">
              <span>工程条件</span>
              <strong>{{ selectedStratumText }}</strong>
            </div>
            <div class="popover-row">
              <span>岩性占比</span>
              <strong>{{ selectedRatioText }}</strong>
            </div>
            <p class="section-note">图示断面估算（13.1 m），层界按水平方向延伸；标记位于本环中点，进度止于本环末边界。</p>
          </div>
        </div>

        <div v-if="pdfLoading" class="pdf-loading">PDF 加载中…</div>
        <div v-if="pdfError" class="pdf-error">{{ pdfError }}</div>
      </div>
    </div>

    <footer class="route-footer">
      <span><i class="dot completed"></i>最新开仓位置</span>
      <span><i class="dot opening"></i>开仓 {{ openingsLoading ? '加载中…' : openingsError ? '加载失败' : `${openingPoints.length} 次` }}</span>
      <span><i class="dot remaining"></i>地层信息 {{ stratumLoading ? '加载中…' : `${stratumCount} 环` }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue';
import * as pdfjsLib from 'pdfjs-dist';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.js?url';
import { request } from '/@/utils/service';
import { GetHomeProjectInfo } from './api';
import { PROFILE_CALIBRATION, ringPositionPercent } from './profileCalibration';

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

const GEOLOGY_PROFILE_PDF_URL = PROFILE_CALIBRATION.source;

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
  stratum_type_ratios?: Record<string, number>;
  stratum_ratio_labels?: Record<string, string>;
};

const bodyRef = ref<HTMLDivElement | null>(null);
const stageRef = ref<HTMLDivElement | null>(null);
const canvasRef = ref<HTMLCanvasElement | null>(null);
const pdfLoading = ref(true);
const pdfError = ref('');
const openingsLoading = ref(true);
const openingsError = ref(false);
const stratumLoading = ref(true);

const projectName = ref('');
const ringRange = ref<{ start: number; end: number } | null>(null);
const totalRings = computed(() => ringRange.value ? ringRange.value.end - ringRange.value.start : 0);
const openingPoints = ref<RingPoint[]>([]);
const selectedPoint = ref<RingPoint | null>(null);
const isFullscreen = ref(false);
const stratumMap = ref<Record<string, string>>({});
const ratioMap = ref<Record<string, StratumItem>>({});
const selectedStratumText = computed(() => {
  const point = selectedPoint.value;
  return (point && (stratumMap.value[String(point.ringValue)] || point.stratumText))
    || (stratumLoading.value ? '加载中…' : '待导入');
});
const selectedRatioText = computed(() => {
  if (stratumLoading.value) return '加载中…';
  const item = selectedPoint.value ? ratioMap.value[String(selectedPoint.value.ringValue)] : undefined;
  const ratios = item?.stratum_type_ratios;
  if (!ratios || !Object.keys(ratios).length) return '暂无占比数据';
  return Object.entries(ratios).map(([code, value]) => `${item?.stratum_ratio_labels?.[code] || code} ${Number(value).toFixed(2)}%`).join('；');
});
const stratumCount = ref(0);

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let pdfPage: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let pdfDoc: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let renderTask: any = null;
let renderGeneration = 0;
let disposed = false;
let resizeObserver: ResizeObserver | null = null;
let resizeTimer: ReturnType<typeof window.setTimeout> | null = null;

const MAX_CANVAS_PIXELS = 16000000;

const currentPoint = computed<RingPoint | null>(() => {
  const latest = openingPoints.value[openingPoints.value.length - 1];
  if (!latest) return null;
  return { ...latest, id: 'current-ring', kind: 'current' };
});

// PDF 横坐标包含图纸边距，只用于标记定位，不能作为工程完成比例。
const currentPercent = computed(() => {
  if (!currentPoint.value || !ringRange.value || totalRings.value <= 0) return null;
  return Math.round(Math.min(100, Math.max(0, (currentPoint.value.ringValue - ringRange.value.start) / totalRings.value * 100)) * 10) / 10;
});

const openingStatusText = computed(() => openingsLoading.value ? '读取中…'
  : openingsError.value ? '读取失败'
  : currentPoint.value ? `${currentPoint.value.ringValue} 环` : '暂无记录');

const progressText = computed(() => {
  if (currentPercent.value !== null) return `${currentPercent.value}%`;
  if (openingsLoading.value || pdfLoading.value) return '加载中…';
  if (openingsError.value || pdfError.value) return '加载失败，请刷新重试';
  return '暂不可计算';
});

const axisStyle = computed(() => {
  if (!ringRange.value) return { visibility: 'hidden' as const };
  const start = ringPositionPercent(ringRange.value.start, 'end');
  const end = ringPositionPercent(ringRange.value.end, 'end');
  return { left: `${start}%`, right: `${100 - end}%` };
});

const axisProgressPercent = computed(() => {
  if (!ringRange.value || !currentPoint.value) return null;
  const start = ringPositionPercent(ringRange.value.start, 'end');
  const end = ringPositionPercent(ringRange.value.end, 'end');
  if (!(end > start)) return null;
  return Math.min(100, Math.max(0, (ringPositionPercent(currentPoint.value.ringValue, 'end') - start) / (end - start) * 100));
});

const popoverLeft = computed(() => {
  if (!selectedPoint.value) return '16px';
  const percent = selectedPoint.value.percent;
  if (percent < 18) return '16px';
  if (percent > 82) return 'calc(100% - 316px)';
  return `calc(${percent}% - 150px)`;
});


function buildStratumText(item: StratumItem) {
  const names = (item.stratum_types_list || []).map((type) => type.name || type.code).filter(Boolean);
  if (names.length) return names.join('、');
  return item.stratum_info || '';
}

async function renderPdf() {
  const generation = ++renderGeneration;
  const previousTask = renderTask;
  if (previousTask) {
    previousTask.cancel();
    try {
      await previousTask.promise;
    } catch (error: any) {
      if (error?.name !== 'RenderingCancelledException' && !disposed) {
        pdfError.value = 'PDF 渲染失败，请刷新重试';
      }
    }
    if (renderTask === previousTask) renderTask = null;
  }
  // Cancellation settles before resizing/reusing the canvas. Only the newest
  // fullscreen/ResizeObserver request may start the next render.
  if (disposed || generation !== renderGeneration || !canvasRef.value || !stageRef.value) return;
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
    const summaryEl = stageRef.value.closest('.route-map-panel')?.querySelector('.progress-summary') as HTMLElement | null;
    const headerH = headerEl ? headerEl.offsetHeight : 52;
    const footerH = footerEl ? footerEl.offsetHeight : 40;
    targetH = Math.max(160, window.innerHeight - 32 - headerH - footerH - (summaryEl?.offsetHeight || 0) - 4);
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

  let task: any = null;
  try {
    task = pdfPage.render({ canvasContext: ctx, viewport: scaledViewport });
    renderTask = task;
    await task.promise;
  } catch (e: any) {
    if (e?.name !== 'RenderingCancelledException' && !disposed && generation === renderGeneration) {
      pdfError.value = 'PDF 渲染失败，请刷新重试';
    }
  } finally {
    if (renderTask === task) renderTask = null;
  }
}

async function waitLayout() {
  await nextTick();
  await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
}


async function loadPdf() {
  pdfLoading.value = true;
  pdfError.value = '';
  ringRange.value = null;
  try {
    pdfDoc = await pdfjsLib.getDocument(GEOLOGY_PROFILE_PDF_URL).promise;
    if (disposed) { pdfDoc.destroy(); pdfDoc = null; return; }
    pdfPage = await pdfDoc.getPage(1);
    if (disposed) { pdfPage = null; return; }
    // Hash is checked against the shipped artifact in the calibration regression.
    // Runtime dimension/label checks also work on non-HTTPS engineering LANs.
    const viewport = pdfPage.getViewport({ scale: 1, rotation: 0 });
    const text = await pdfPage.getTextContent();
    const ringLabels = new Set(text.items.map((item: any) => String(item.str || '').trim())
      .filter((label: string) => /^\d{4}环$/.test(label)));
    if (Math.abs(viewport.width - PROFILE_CALIBRATION.pdfWidth) > 0.1 || ringLabels.size !== 281
      || !ringLabels.has('0000环') || !ringLabels.has('2800环')) throw new Error('PDF calibration mismatch');
    if (disposed) return;
    ringRange.value = { start: PROFILE_CALIBRATION.startRing, end: PROFILE_CALIBRATION.endRing };
    await renderPdf();
  } catch {
    pdfPage = null;
    pdfDoc?.destroy?.();
    pdfDoc = null;
    pdfError.value = 'PDF 加载失败，请刷新重试';
  } finally {
    pdfLoading.value = false;
  }
}

async function loadProject() {
  try {
    const res: any = await GetHomeProjectInfo();
    if (disposed) return;
    const data = res?.data ?? res;
    projectName.value = data?.project_name || '';
  } catch {
    projectName.value = '示例盾构项目';
  }
}

async function loadStratum() {
  try {
    const res: any = await request({ url: '/api/shield/stratum_basic_info/', method: 'get', params: { project: 1, limit: 5000, ordering: 'ring_no' } });
    if (disposed) return;
    const records: StratumItem[] = res.data?.results ?? res.data ?? [];
    const map: Record<string, string> = {};
    const ratios: Record<string, StratumItem> = {};
    records.forEach((item) => {
      if (item.ring_no == null || String(item.ring_no).trim() === '' || !Number.isInteger(Number(item.ring_no))) return;
      const ringNo = String(Number(item.ring_no));
      map[ringNo] = buildStratumText(item);
      ratios[ringNo] = item;
    });
    stratumMap.value = map;
    ratioMap.value = ratios;
    stratumCount.value = Object.keys(map).length;
  } catch {
    stratumMap.value = {};
    ratioMap.value = {};
    stratumCount.value = 0;
  } finally {
    stratumLoading.value = false;
  }
}

async function loadOpenings() {
  openingsLoading.value = true;
  openingsError.value = false;
  try {
    const res: any = await request({ url: '/api/shield/warehouse_opening/', method: 'get', params: { project: 1, limit: 500, ordering: 'ring_no' } });
    if (disposed) return;
    const records: any[] = res.data?.results ?? res.data ?? [];
    const sorted = records
      .filter((item) => item.ring_no != null && String(item.ring_no).trim() !== '' && Number.isInteger(Number(item.ring_no)) && Number(item.ring_no) >= 0)
      .sort((a, b) => Number(a.ring_no) - Number(b.ring_no));

    openingPoints.value = sorted.map((item) => {
      const ringValue = Number(item.ring_no);
      const ringNo = String(item.ring_no);
      return {
        id: String(item.id ?? ringNo),
        ringNo,
        ringValue,
        percent: ringPositionPercent(ringValue),
        kind: 'opening' as const,
        openTime: item.open_time,
        stratumText:
          stratumMap.value[String(ringValue)] ||
          item.stratum_info_between_list?.map((s: any) => s.stratum_type_name).join('、') ||
          '',
      };
    });
    selectedPoint.value = currentPoint.value;
  } catch {
    openingPoints.value = [];
    openingsError.value = true;
  } finally {
    openingsLoading.value = false;
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
  // Progress depends only on openings and the calibrated PDF. Stratum details
  // fill in reactively when ready instead of blocking the map and progress.
  const projectTask = loadProject();
  const stratumTask = loadStratum();
  await Promise.all([loadPdf(), loadOpenings()]);

  if (!disposed && stageRef.value) {
    resizeObserver = new ResizeObserver(() => {
      if (resizeTimer) window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => renderPdf(), 120);
    });
    resizeObserver.observe(stageRef.value);
  }
  await Promise.all([projectTask, stratumTask]);
});

onUnmounted(() => {
  disposed = true;
  renderGeneration++;
  resizeObserver?.disconnect();
  if (resizeTimer) {
    window.clearTimeout(resizeTimer);
    resizeTimer = null;
  }
  const pendingTask = renderTask;
  pendingTask?.cancel();
  renderTask = null;
  pdfPage = null;
  pdfDoc?.destroy?.();
  pdfDoc = null;
  const canvas = canvasRef.value;
  const releaseCanvas = () => {
    if (canvas) { canvas.width = 0; canvas.height = 0; }
  };
  if (pendingTask) pendingTask.promise.then(releaseCanvas, releaseCanvas);
  else releaseCanvas();
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

.progress-summary {
  flex: 0 0 auto;
  padding: 10px 12px;
  border-bottom: 1px solid #e5e7eb;
}

.progress-heading,
.progress-caption {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 12px;
  color: #475569;
  font-size: 12px;
}

.progress-heading { justify-content: space-between; }
.progress-heading strong { color: #1e293b; }
.progress-heading b { margin-left: 8px; color: #00796b; font-size: 18px; font-variant-numeric: tabular-nums; }
.summary-track {
  height: 14px;
  margin: 8px 0;
  overflow: hidden;
  border: 1px solid #94a3b8;
  border-radius: 4px;
  background: repeating-linear-gradient(135deg, #cbd5e1 0 7px, #f1f5f9 7px 14px);
}
.summary-track.progress-unknown { background: #e2e8f0; }
.summary-completed { display: block; height: 100%; background: #00897b; }
.progress-caption { font-size: 11px; }
.line-key { display: inline-block; width: 22px; height: 6px; margin-right: 5px; vertical-align: middle; }
.line-key.completed { background: #00897b; }
.line-key.remaining { background: repeating-linear-gradient(90deg, #64748b 0 6px, transparent 6px 9px); }

.profile-stage {
  position: relative;
  display: inline-block;
  min-width: 100%;
  min-height: 220px;
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
  left: 0;
  right: 0;
  bottom: 34px;
  height: 12px;
  pointer-events: none;
}

.axis-line,
.axis-progress {
  position: absolute;
  top: 0;
  left: 0;
  height: 10px;
  border-radius: 99px;
}

.axis-line {
  width: 100%;
  background: repeating-linear-gradient(90deg, #64748b 0 14px, #e2e8f0 14px 21px);
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.9);
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
  width: 300px;
  box-sizing: border-box;
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
  grid-template-columns: 56px 1fr;
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
.section-note { margin: 8px 0 0; color: #64748b; font-size: 11px; line-height: 1.5; }

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
  flex-wrap: wrap;
  flex: 0 0 auto;
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
