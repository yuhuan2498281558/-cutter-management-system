<template>
  <div class="mapper-wrap">
    <!-- 左侧控制面板 -->
    <div class="ctrl-panel">
      <div class="ctrl-title">BIM 刀位标定工具</div>

      <!-- 第一步：锁定视角 -->
      <div class="ctrl-section">
        <div class="ctrl-step">① 调整视角后锁定</div>
        <el-button
          :type="viewpoint ? 'success' : 'primary'"
          style="width:100%"
          :disabled="modelState !== 'ready'"
          @click="saveViewpoint"
        >
          {{ viewpoint ? '✓ 已锁定视角（点击重新锁定）' : '锁定当前视角' }}
        </el-button>
        <div class="ctrl-hint">所有刀位都在此视角下标定，展示时也会恢复此视角</div>
      </div>

      <!-- 第二步：标定刀位 -->
      <div class="ctrl-section">
        <div class="ctrl-step">② 选刀位 → 点击标定</div>
        <el-select
          v-model="currentCode"
          filterable
          placeholder="选择刀位编号"
          style="width:100%"
          :disabled="!viewpoint"
        >
          <el-option
            v-for="pos in ALL_POSITIONS"
            :key="pos.code"
            :label="`${pos.code}（${pos.type}）${mapped[pos.code] ? ' ✓' : ''}`"
            :value="pos.code"
          />
        </el-select>
        <el-button
          type="warning"
          style="width:100%;margin-top:8px"
          :disabled="!currentCode || !viewpoint || modelState !== 'ready'"
          @click="startMark"
        >
          {{ waitingClick ? '⏳ 等待点击...' : '开始标定此刀位' }}
        </el-button>
        <div class="ctrl-hint">点按钮后，在右侧模型上点击对应刀位位置</div>
      </div>

      <!-- 进度 -->
      <div class="ctrl-section">
        <div class="ctrl-label">已标定 {{ doneCount }} / {{ ALL_POSITIONS.length }}</div>
        <el-progress :percentage="Math.round(doneCount / ALL_POSITIONS.length * 100)" />
      </div>

      <!-- 已标定列表 -->
      <div class="ctrl-section">
        <div class="ctrl-label">已标定列表</div>
        <div class="mapped-list">
          <div
            v-for="(v, k) in mapped"
            :key="k"
            class="mapped-item"
            :class="{ selected: currentCode === k }"
            @click="currentCode = k"
          >
            <span class="mapped-code">{{ k }}</span>
            <span class="mapped-xy">{{ v.componentId ? `构件 ${v.componentId}` : `${(v.px * 100).toFixed(1)}%, ${(v.py * 100).toFixed(1)}%` }}</span>
            <el-button size="small" type="danger" text @click.stop="delete mapped[k]">删</el-button>
          </div>
        </div>
      </div>

      <!-- 导出 -->
      <div class="ctrl-section">
        <el-button type="primary" style="width:100%" :disabled="!viewpoint || doneCount === 0" @click="exportData">
          导出标定数据
        </el-button>
        <el-button style="width:100%;margin-top:8px" @click="importData">
          导入已有标定
        </el-button>
      </div>

      <div v-if="exportText" class="export-box">
        <div class="ctrl-label">复制以下内容，粘贴到 cutterScreenPositions.ts：</div>
        <textarea
          class="export-textarea"
          readonly
          :value="exportText"
          @click="($event.target as HTMLTextAreaElement).select()"
        />
      </div>
    </div>

    <!-- 右侧 BIM 模型 -->
    <div ref="viewerWrap" class="viewer-wrap">
      <div class="mapper-actions">
        <el-button size="small" :disabled="saving || doneCount === 0" type="primary" @click="saveToDatabase">
          保存映射
        </el-button>
        <el-button size="small" @click="emit('close')">返回首页</el-button>
      </div>
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

      <div ref="bimContainer" class="bm-viewer"></div>

      <!-- 点击捕获层：仅标定时激活 -->
      <div
        v-if="false"
        class="click-layer"
        @click="onViewerClick"
      ></div>

      <!-- 已标定热点 SVG -->
      <svg
        v-if="modelState === 'ready'"
        class="hotspot-svg"
        :width="svgW"
        :height="svgH"
        :viewBox="`0 0 ${svgW} ${svgH}`"
      >
        <g v-for="(v, k) in mapped" :key="k">
          <circle
            :cx="v.px * svgW"
            :cy="v.py * svgH"
            r="9"
            :fill="currentCode === k ? '#4ecdc4' : 'rgba(255,107,107,0.7)'"
            stroke="white"
            stroke-width="1.5"
            style="pointer-events:none"
          />
          <text
            :x="v.px * svgW + 12"
            :y="v.py * svgH + 4"
            font-size="11"
            fill="white"
            style="pointer-events:none;text-shadow:0 1px 3px #000"
          >{{ k }}</text>
        </g>
        <!-- 十字准星 -->
        <template v-if="waitingClick">
          <line :x1="cursor.x" y1="0" :x2="cursor.x" :y2="svgH" stroke="rgba(255,200,0,0.6)" stroke-width="1"/>
          <line x1="0" :y1="cursor.y" :x2="svgW" :y2="cursor.y" stroke="rgba(255,200,0,0.6)" stroke-width="1"/>
          <circle :cx="cursor.x" :cy="cursor.y" r="5" fill="none" stroke="yellow" stroke-width="1.5"/>
        </template>
      </svg>

      <!-- 底部提示 -->
      <div v-if="modelState === 'ready'" class="viewer-hint" :class="{ active: waitingClick }">
        <template v-if="waitingClick">🎯 点击模型上「{{ currentCode }}」的位置</template>
        <template v-else-if="!viewpoint">先调整好视角，点击「锁定当前视角」</template>
        <template v-else>视角已锁定 — 选刀位后点「开始标定」</template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue';
import { Loading, WarningFilled } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import { request } from '/@/utils/service';
import { ACTIVE_CUTTER_POSITIONS } from '/@/constants/cutterPositions';
import { getActiveCutterModelMappings, getBimfaceViewToken, saveCutterModelMappings } from './cutterApi';

const ALL_POSITIONS = ACTIVE_CUTTER_POSITIONS;
const BIMFACE_OFFICIAL_SDK_URL = 'https://static.bimface.com/api/BimfaceSDKLoader/BimfaceSDKLoader@latest-release.js';
const BIMFACE_LOCAL_SDK_URL = `${import.meta.env.BASE_URL === './' ? '/' : import.meta.env.BASE_URL}vendor/bimface/BimfaceSDKLoader@latest-release.js`;
const BIMFACE_SDK_URLS = [BIMFACE_LOCAL_SDK_URL, BIMFACE_OFFICIAL_SDK_URL];
const emit = defineEmits<{ (e: 'close'): void }>();

const viewerWrap = ref<HTMLDivElement>();
const bimContainer = ref<HTMLDivElement>();
const modelState = ref<'loading' | 'ready' | 'error'>('loading');
const errorMsg = ref('');
const svgW = ref(0);
const svgH = ref(0);
const cursor = reactive({ x: 0, y: 0 });

const currentCode = ref('');
const waitingClick = ref(false);
const saving = ref(false);
// 保存比例坐标 { px: 0~1, py: 0~1 }
const mapped = reactive<Record<string, { px: number; py: number; componentId?: string }>>({});
const viewpoint = ref<any>(null); // 保存的相机视角
const exportText = ref('');

const doneCount = computed(() => Object.keys(mapped).length);

let bimApp: any = null;
let viewer: any = null;
let ro: ResizeObserver | null = null;

function syncSize() {
  if (!viewerWrap.value) return;
  const r = viewerWrap.value.getBoundingClientRect();
  svgW.value = r.width;
  svgH.value = r.height;
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) { resolve(); return; }
    const s = document.createElement('script');
    s.src = src; s.charset = 'utf-8';
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('SDK 加载失败'));
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

async function initModel() {
  modelState.value = 'loading';
  errorMsg.value = '';
  try {
    await loadBimfaceSdk();
    const viewToken = await getBimfaceViewToken();
    const W = window as any;
    const loaderConfig = new W.BimfaceSDKLoaderConfig();
    loaderConfig.viewToken = viewToken;
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
    W.BimfaceSDKLoader.load(
      loaderConfig,
      () => {
        const cfg = new W.Glodon.Bimface.Application.WebApplication3DConfig();
        cfg.domElement = bimContainer.value;
        bimApp = new W.Glodon.Bimface.Application.WebApplication3D(cfg);
        bimApp.addView(viewToken);
        viewer = bimApp.getViewer();
        viewer.addEventListener(W.Glodon.Bimface.Viewer.Viewer3DEvent.ViewAdded, () => {
          viewer.render();
          modelState.value = 'ready';
          syncSize();
        });
        bindModelSelection(W);
      },
      (err: any) => {
        modelState.value = 'error';
        errorMsg.value = `初始化失败: ${JSON.stringify(err)}`;
      },
    );
  } catch (e: any) {
    modelState.value = 'error';
    errorMsg.value = e.message ?? '加载失败';
  }
}

function saveViewpoint() {
  if (!viewer) return;
  try {
    // 尝试多种 API 获取相机状态
    const vp = viewer.getViewpoint?.()
      ?? viewer.getCameraStatus?.()
      ?? viewer.getCamera?.();
    if (vp) {
      viewpoint.value = JSON.parse(JSON.stringify(vp));
      ElMessage.success('视角已锁定');
    } else {
      // BIMFace 某些版本没有 getViewpoint，直接标记已锁定
      viewpoint.value = { locked: true };
      ElMessage.success('视角已锁定（将使用当前视角）');
    }
  } catch (e) {
    viewpoint.value = { locked: true };
    ElMessage.success('视角已锁定');
  }
}

function startMark() {
  if (!currentCode.value || !viewpoint.value) return;
  // 如果 viewpoint 有实际数据，先恢复视角确保一致
  if (viewpoint.value && !viewpoint.value.locked) {
    try {
      viewer?.setViewpoint?.(viewpoint.value)
        ?? viewer?.setCameraStatus?.(viewpoint.value)
        ?? viewer?.setCamera?.(viewpoint.value);
    } catch (_) {}
  }
  waitingClick.value = true;
  ElMessage.info('请直接点击模型中的单个刀具构件');
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
    if (!waitingClick.value || !currentCode.value) return;
    const componentId = extractComponentId(payload) || readSelectedComponentId();
    if (!componentId) {
      ElMessage.warning('没有识别到模型构件，请点单个刀具构件再试');
      return;
    }

    waitingClick.value = false;
    mapped[currentCode.value] = {
      px: 0,
      py: 0,
      componentId,
    };
    ElMessage.success(`已绑定刀位 ${currentCode.value} -> 构件 ${componentId}`);

    const idx = ALL_POSITIONS.findIndex(p => p.code === currentCode.value);
    const next = ALL_POSITIONS.slice(idx + 1).find(p => !mapped[p.code]);
    if (next) currentCode.value = next.code;
  };

  eventNames.forEach((eventName: string) => {
    try {
      viewer?.addEventListener?.(eventName, handler);
    } catch (_) {}
  });
}

function onViewerClick(e: MouseEvent) {
  waitingClick.value = false;
  if (!currentCode.value) return;

  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
  const px = (e.clientX - rect.left) / rect.width;
  const py = (e.clientY - rect.top) / rect.height;

  mapped[currentCode.value] = {
    px: +px.toFixed(5),
    py: +py.toFixed(5),
  };
  ElMessage.success(`已标定 ${currentCode.value}`);

  // 自动跳到下一个未标定刀位
  const idx = ALL_POSITIONS.findIndex(p => p.code === currentCode.value);
  const next = ALL_POSITIONS.slice(idx + 1).find(p => !mapped[p.code]);
  if (next) currentCode.value = next.code;
}

function onMouseMove(e: MouseEvent) {
  if (!viewerWrap.value || !waitingClick.value) return;
  const rect = viewerWrap.value.getBoundingClientRect();
  cursor.x = e.clientX - rect.left;
  cursor.y = e.clientY - rect.top;
}

function exportData() {
  const posType = ALL_POSITIONS.reduce((m, p) => { m[p.code] = p.type; return m; }, {} as Record<string, string>);
  const positions = Object.entries(mapped).map(([code, v]) =>
    `  { code: '${code}', type: '${posType[code] ?? ''}', px: ${v.px}, py: ${v.py} },`
  );
  const vpStr = JSON.stringify(viewpoint.value);

  exportText.value =
`// 粘贴此内容到 src/constants/cutterScreenPositions.ts
export const CUTTER_VIEWPOINT = ${vpStr};

export const CUTTER_SCREEN_POSITIONS = [
${positions.join('\n')}
];
`;
  ElMessage.success(`已生成 ${positions.length} 条`);
}

function importData() {
  const input = prompt('粘贴已有标定 JSON（格式：{"1":{"px":0.5,"py":0.3},...}）');
  if (!input) return;
  try {
    const data = JSON.parse(input);
    Object.assign(mapped, data);
    ElMessage.success(`已导入 ${Object.keys(data).length} 条`);
  } catch {
    ElMessage.error('JSON 格式错误');
  }
}

async function loadExistingMappings() {
  const mappings = await getActiveCutterModelMappings();
  mappings.forEach((item) => {
    if (item.cutter_position_no && item.component_id) {
      mapped[item.cutter_position_no] = {
        px: Number(item.screen_x ?? 0),
        py: Number(item.screen_y ?? 0),
        componentId: String(item.component_id),
      };
    } else if (item.cutter_position_no && item.screen_x != null && item.screen_y != null) {
      mapped[item.cutter_position_no] = {
        px: Number(item.screen_x),
        py: Number(item.screen_y),
      };
    }
  });
}

async function saveToDatabase() {
  const items = Object.entries(mapped).map(([code, v], index) => ({
    cutter_position_no: code,
    model_point_code: code,
    component_id: v.componentId || null,
    screen_x: v.componentId ? null : v.px,
    screen_y: v.componentId ? null : v.py,
    sort_no: index,
    is_active: true,
  }));
  if (!items.length) return;

  saving.value = true;
  try {
    const res = await saveCutterModelMappings(items);
    const savedCount = res?.saved_count ?? items.length;
    const missingCount = res?.missing_count ?? 0;
    if (missingCount > 0) {
      ElMessage.warning(`已保存 ${savedCount} 个，${missingCount} 个刀位未在数据库找到`);
    } else {
      ElMessage.success(`已保存 ${savedCount} 个刀位映射`);
    }
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  initModel();
  loadExistingMappings();
  ro = new ResizeObserver(syncSize);
  if (viewerWrap.value) {
    ro.observe(viewerWrap.value);
    viewerWrap.value.addEventListener('mousemove', onMouseMove);
  }
});

onUnmounted(() => {
  ro?.disconnect();
  viewerWrap.value?.removeEventListener('mousemove', onMouseMove);
  bimApp?.destroy?.();
  bimApp = null;
});
</script>

<style scoped>
.mapper-wrap {
  display: flex;
  width: 100%;
  height: 100%;
  background: #0d0d0d;
  color: #e0e0e0;
}

.ctrl-panel {
  width: 280px;
  flex-shrink: 0;
  overflow-y: auto;
  background: #1a1a1a;
  border-right: 1px solid #333;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.ctrl-title {
  font-size: 14px;
  font-weight: 700;
  color: #4ecdc4;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #333;
}

.ctrl-step {
  font-size: 12px;
  font-weight: 600;
  color: #f0a500;
  margin-bottom: 6px;
}

.ctrl-section { margin-bottom: 16px; }

.ctrl-label {
  font-size: 11px;
  color: #888;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.ctrl-hint { font-size: 11px; color: #555; margin-top: 5px; line-height: 1.4; }

.mapped-list {
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid #2a2a2a;
  border-radius: 4px;
}

.mapped-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  font-size: 12px;
  border-bottom: 1px solid #222;
  cursor: pointer;
}
.mapped-item:hover { background: #252525; }
.mapped-item.selected { background: #1a3a3a; }
.mapped-item:last-child { border-bottom: none; }
.mapped-code { color: #4ecdc4; font-weight: 600; min-width: 50px; }
.mapped-xy { color: #666; flex: 1; font-size: 10px; }

.export-box { margin-top: 8px; }
.export-textarea {
  width: 100%;
  height: 180px;
  background: #111;
  color: #7fff7f;
  border: 1px solid #333;
  border-radius: 4px;
  padding: 8px;
  font-size: 10px;
  font-family: monospace;
  resize: vertical;
  box-sizing: border-box;
}

.viewer-wrap { flex: 1; position: relative; overflow: hidden; }
.bm-viewer { position: absolute; inset: 0; }
.mapper-actions {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 40;
  display: flex;
  gap: 8px;
}

.click-layer {
  position: absolute;
  inset: 0;
  z-index: 10;
  cursor: crosshair;
  background: rgba(255, 200, 0, 0.05);
}

.hotspot-svg {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 11;
  pointer-events: none;
}

.viewer-hint {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0,0,0,0.65);
  color: #ccc;
  font-size: 12px;
  padding: 6px 16px;
  border-radius: 20px;
  pointer-events: none;
  z-index: 20;
  white-space: nowrap;
  transition: background 0.2s, color 0.2s;
}
.viewer-hint.active {
  background: rgba(255,165,0,0.9);
  color: #000;
  font-weight: 600;
}

.bm-overlay {
  position: absolute;
  inset: 0;
  z-index: 30;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: rgba(10,10,10,0.85);
  color: #aaa;
  font-size: 14px;
}
.bm-overlay.error { color: #e74c3c; }

.spin { animation: spin 1s linear infinite; font-size: 24px; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
