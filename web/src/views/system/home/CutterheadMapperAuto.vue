<template>
  <div class="mapper-container">
    <div class="toolbar">
      <h3>刀位快速标注工具</h3>
      <div class="current-cutter">
        <div class="cutter-card">
          <div class="cutter-number">{{ currentIndex + 1 }} / {{ cutterList.length }}</div>
          <div class="cutter-code">{{ currentCutter?.code }}</div>
          <div class="cutter-type">{{ currentCutter?.type }}</div>
          <div class="hint">点击图片上对应的刀位位置</div>
        </div>
      </div>
      <div class="controls">
        <button @click="prevCutter" :disabled="currentIndex === 0">上一个</button>
        <button @click="skipCurrent">跳过</button>
        <button @click="nextCutter" :disabled="currentIndex >= cutterList.length - 1">下一个</button>
        <button @click="clearLast" :disabled="positions.length === 0">撤销</button>
        <button @click="exportData" class="primary">导出配置</button>
      </div>
      <div class="progress">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
        </div>
        <div class="progress-text">已标注: {{ positions.length }} / {{ cutterList.length }}</div>
      </div>
    </div>

    <div class="image-area" ref="containerRef">
      <div class="zoom-controls">
        <button @click="zoomIn" title="放大">+</button>
        <span class="zoom-level">{{ Math.round(scale * 100) }}%</span>
        <button @click="zoomOut" title="缩小">-</button>
        <button @click="resetZoom" title="重置">重置</button>
      </div>
      <div
        class="image-wrapper"
        :style="{
          transform: `scale(${scale}) translate(${translateX}px, ${translateY}px)`,
          cursor: isDragging ? 'grabbing' : 'crosshair'
        }"
        @mousedown="startDrag"
        @mousemove="onDrag"
        @mouseup="endDrag"
        @mouseleave="endDrag"
        @wheel="handleWheel"
        @contextmenu.prevent
      >
        <img
          ref="imageRef"
          src="/cutterhead-placeholder.svg"
          @click="handleClick"
          @load="onImageLoad"
          draggable="false"
        />
        <svg class="overlay" :viewBox="`0 0 ${imageWidth} ${imageHeight}`">
          <g v-for="(pos, i) in positions" :key="i">
            <circle
              :cx="pos.x"
              :cy="pos.y"
              r="8"
              :fill="pos.code === currentCutter?.code ? 'rgba(255, 215, 0, 0.6)' : 'rgba(78, 205, 196, 0.5)'"
              :stroke="pos.code === currentCutter?.code ? '#ffd700' : '#4ECDC4'"
              stroke-width="2"
            />
            <text
              :x="pos.x"
              :y="pos.y - 12"
              fill="#fff"
              font-size="11"
              font-weight="bold"
              text-anchor="middle"
              style="text-shadow: 1px 1px 3px #000"
            >
              {{ pos.code }}
            </text>
          </g>
        </svg>
      </div>
    </div>

    <div class="output">
      <h4>配置代码：</h4>
      <textarea v-model="outputCode" readonly></textarea>
      <button @click="copyCode" class="copy-btn">复制代码</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';

const imageRef = ref<HTMLImageElement>();
const containerRef = ref<HTMLDivElement>();
const imageWidth = ref(1000);
const imageHeight = ref(1000);
const currentIndex = ref(0);
const positions = ref<Array<{code: string, type: string, x: number, y: number}>>([]);

// 缩放和拖拽相关
const scale = ref(1);
const translateX = ref(0);
const translateY = ref(0);
const isDragging = ref(false);
const dragStartX = ref(0);
const dragStartY = ref(0);
const dragStartTranslateX = ref(0);
const dragStartTranslateY = ref(0);

// 预设的刀位列表（基于完整清单和图纸）
const cutterList = ref([
  // 主切削刀1（36个）
  ...Array.from({ length: 36 }, (_, i) => ({
    code: `主刀1-${i + 1}`,
    type: '主切削刀1'
  })),

  // 主切削刀2（6个）
  ...Array.from({ length: 6 }, (_, i) => ({
    code: `主刀2-${i + 1}`,
    type: '主切削刀2'
  })),

  // 边刮刀A+B+C（6个）
  ...Array.from({ length: 6 }, (_, i) => ({
    code: `边刮刀-${i + 1}`,
    type: '边刮刀A+B+C'
  })),

  // 中心滚刀（12个）
  ...Array.from({ length: 12 }, (_, i) => ({
    code: `中${i + 1}`,
    type: '中心滚刀'
  })),

  // H=180 双联滚刀(单密封)（4个）
  ...Array.from({ length: 4 }, (_, i) => ({
    code: `H180-${i + 1}`,
    type: 'H=180 双联滚刀(单密封)'
  })),

  // H=200 双联滚刀（2个）
  ...Array.from({ length: 2 }, (_, i) => ({
    code: `H200-${i + 1}`,
    type: 'H=200 双联滚刀'
  })),

  // H=240 双联滚刀（27个）
  ...Array.from({ length: 27 }, (_, i) => ({
    code: `H240-${i + 1}`,
    type: 'H=240 双联滚刀'
  })),

  // 单联滚刀（6个）
  ...Array.from({ length: 6 }, (_, i) => ({
    code: `单联-${i + 1}`,
    type: '单联滚刀'
  })),

  // S1-S7 刮刀（左右各7个，共14个）
  { code: 'S1L', type: '可更换式刮刀' },
  { code: 'S1R', type: '可更换式刮刀' },
  { code: 'S2L', type: '可更换式刮刀' },
  { code: 'S2R', type: '可更换式刮刀' },
  { code: 'S3L', type: '可更换式刮刀' },
  { code: 'S3R', type: '可更换式刮刀' },
  { code: 'S4L', type: '可更换式刮刀' },
  { code: 'S4R', type: '可更换式刮刀' },
  { code: 'S5L', type: '可更换式刮刀' },
  { code: 'S5R', type: '可更换式刮刀' },
  { code: 'S6L', type: '可更换式刮刀' },
  { code: 'S6R', type: '可更换式刮刀' },
  { code: 'S7L', type: '可更换式刮刀' },
  { code: 'S7R', type: '可更换式刮刀' },

  // S8-S19 特殊刮刀
  { code: 'S8L', type: '可更换式刮刀H=370' },
  { code: 'S8R', type: '可更换式刮刀H=370' },
  { code: 'S9L', type: '可更换式刮刀H=370' },
  { code: 'S9R', type: '可更换式刮刀H=370' },
  { code: 'S10L', type: '可更换式刮刀' },
  { code: 'S10R', type: '可更换式刮刀' },
  { code: 'S11L', type: '可更换式刮刀H=380' },
  { code: 'S11R', type: '可更换式刮刀H=380' },
  { code: 'S12L', type: '可更换式刮刀H=400' },
  { code: 'S12R', type: '可更换式刮刀H=400' },
  { code: 'S13L', type: '可更换式刮刀H=400' },
  { code: 'S13R', type: '可更换式刮刀H=400' },
  { code: 'S14L', type: '可更换式刮刀H=380' },
  { code: 'S14R', type: '可更换式刮刀H=380' },
  { code: 'S15L', type: '可更换式刮刀H=380' },
  { code: 'S15R', type: '可更换式刮刀H=380' },
  { code: 'S16L', type: '可更换式刮刀H=380' },
  { code: 'S16R', type: '可更换式刮刀H=380' },
  { code: 'S17L', type: '可更换式刮刀H=380' },
  { code: 'S17R', type: '可更换式刮刀H=380' },
  { code: 'S18L', type: '可更换式刮刀H=380' },
  { code: 'S18R', type: '可更换式刮刀H=380' },
  { code: 'S19L', type: '可更换式刮刀H=380' },
  { code: 'S19R', type: '可更换式刮刀H=380' },
]);

const currentCutter = computed(() => cutterList.value[currentIndex.value]);
const progressPercent = computed(() => (positions.value.length / cutterList.value.length) * 100);

const onImageLoad = () => {
  if (imageRef.value) {
    imageWidth.value = imageRef.value.naturalWidth;
    imageHeight.value = imageRef.value.naturalHeight;
  }
};

const handleClick = (e: MouseEvent) => {
  if (!currentCutter.value) return;
  // 只响应左键点击
  if (e.button !== 0) return;

  const rect = (e.target as HTMLElement).getBoundingClientRect();
  const x = (e.clientX - rect.left) / scale.value;
  const y = (e.clientY - rect.top) / scale.value;
  const scaleX = imageWidth.value / (rect.width / scale.value);
  const scaleY = imageHeight.value / (rect.height / scale.value);

  const actualX = Math.round(x * scaleX);
  const actualY = Math.round(y * scaleY);

  positions.value.push({
    code: currentCutter.value.code,
    type: currentCutter.value.type,
    x: actualX,
    y: actualY
  });

  console.log(`已标注: ${currentCutter.value.code} at (${actualX}, ${actualY})`);

  // 自动跳到下一个
  if (currentIndex.value < cutterList.value.length - 1) {
    currentIndex.value++;
  }
};

// 缩放功能
const zoomIn = () => {
  scale.value = Math.min(scale.value + 0.2, 5);
};

const zoomOut = () => {
  scale.value = Math.max(scale.value - 0.2, 0.5);
};

const resetZoom = () => {
  scale.value = 1;
  translateX.value = 0;
  translateY.value = 0;
};

const handleWheel = (e: WheelEvent) => {
  e.preventDefault();
  if (e.deltaY < 0) {
    zoomIn();
  } else {
    zoomOut();
  }
};

// 拖拽功能（只响应右键）
const startDrag = (e: MouseEvent) => {
  if (e.button !== 2) return; // 只响应右键
  e.preventDefault();
  isDragging.value = true;
  dragStartX.value = e.clientX;
  dragStartY.value = e.clientY;
  dragStartTranslateX.value = translateX.value;
  dragStartTranslateY.value = translateY.value;
};

const onDrag = (e: MouseEvent) => {
  if (!isDragging.value) return;
  e.preventDefault();
  const dx = (e.clientX - dragStartX.value) / scale.value;
  const dy = (e.clientY - dragStartY.value) / scale.value;
  translateX.value = dragStartTranslateX.value + dx;
  translateY.value = dragStartTranslateY.value + dy;
};

const endDrag = () => {
  isDragging.value = false;
};

const prevCutter = () => {
  if (currentIndex.value > 0) {
    currentIndex.value--;
  }
};

const nextCutter = () => {
  if (currentIndex.value < cutterList.value.length - 1) {
    currentIndex.value++;
  }
};

const skipCurrent = () => {
  nextCutter();
};

const clearLast = () => {
  positions.value.pop();
  if (currentIndex.value > 0) {
    currentIndex.value--;
  }
};

const outputCode = computed(() => {
  if (positions.value.length === 0) return '';

  return `const cutterPositions = ref([\n${positions.value.map(p =>
    `  { code: '${p.code}', type: '${p.type}', x: ${p.x}, y: ${p.y} },`
  ).join('\n')}\n]);`;
});

const copyCode = () => {
  navigator.clipboard.writeText(outputCode.value);
  alert('配置代码已复制到剪贴板！');
};

const exportData = () => {
  const data = JSON.stringify(positions.value, null, 2);
  const blob = new Blob([data], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'cutter-positions.json';
  a.click();
};
</script>

<style scoped>
.mapper-container {
  width: 100%;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #1a1a1a;
  color: #fff;
  padding: 20px;
  gap: 20px;
}

.toolbar {
  background: #2a2a2a;
  padding: 20px;
  border-radius: 8px;
}

.toolbar h3 {
  margin: 0 0 20px 0;
  color: #4ECDC4;
  text-align: center;
}

.current-cutter {
  margin-bottom: 20px;
}

.cutter-card {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
  border-radius: 12px;
  text-align: center;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
}

.cutter-number {
  font-size: 14px;
  opacity: 0.9;
  margin-bottom: 10px;
}

.cutter-code {
  font-size: 32px;
  font-weight: bold;
  margin-bottom: 8px;
}

.cutter-type {
  font-size: 16px;
  opacity: 0.9;
  margin-bottom: 12px;
}

.hint {
  font-size: 14px;
  opacity: 0.8;
  font-style: italic;
}

.controls {
  display: flex;
  gap: 10px;
  margin-bottom: 15px;
}

.controls button {
  flex: 1;
  padding: 10px;
  background: #333;
  border: 1px solid #555;
  border-radius: 6px;
  color: #fff;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
}

.controls button:hover:not(:disabled) {
  background: #444;
  border-color: #666;
}

.controls button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.controls button.primary {
  background: #4ECDC4;
  color: #000;
  font-weight: bold;
}

.controls button.primary:hover {
  background: #45B7D1;
}

.progress {
  margin-top: 15px;
}

.progress-bar {
  width: 100%;
  height: 8px;
  background: #333;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #4ECDC4 0%, #45B7D1 100%);
  transition: width 0.3s;
}

.progress-text {
  text-align: center;
  color: #999;
  font-size: 14px;
}

.image-area {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: #0a0a0a;
  border-radius: 8px;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 400px;
}

.zoom-controls {
  position: absolute;
  top: 20px;
  left: 20px;
  z-index: 10;
  background: rgba(42, 42, 42, 0.95);
  padding: 10px;
  border-radius: 8px;
  display: flex;
  gap: 8px;
  align-items: center;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.5);
}

.zoom-controls button {
  width: 36px;
  height: 36px;
  background: #4ECDC4;
  border: none;
  border-radius: 6px;
  color: #000;
  font-size: 18px;
  font-weight: bold;
  cursor: pointer;
  transition: all 0.2s;
}

.zoom-controls button:hover {
  background: #45B7D1;
  transform: scale(1.05);
}

.zoom-controls button:active {
  transform: scale(0.95);
}

.zoom-controls button:last-child {
  width: auto;
  padding: 0 12px;
  font-size: 14px;
}

.zoom-level {
  color: #fff;
  font-size: 14px;
  font-weight: bold;
  min-width: 50px;
  text-align: center;
}

.image-wrapper {
  position: relative;
  transition: transform 0.1s ease-out;
  transform-origin: center center;
}

.image-wrapper img {
  max-width: 100%;
  max-height: 100%;
  display: block;
  user-select: none;
}

.overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.output {
  background: #2a2a2a;
  padding: 15px;
  border-radius: 8px;
}

.output h4 {
  margin: 0 0 10px 0;
  color: #4ECDC4;
}

.output textarea {
  width: 100%;
  height: 120px;
  background: #333;
  border: 1px solid #555;
  border-radius: 4px;
  color: #fff;
  padding: 10px;
  font-family: monospace;
  font-size: 11px;
  margin-bottom: 10px;
}

.copy-btn {
  width: 100%;
  padding: 10px;
  background: #4ECDC4;
  border: none;
  border-radius: 6px;
  color: #000;
  cursor: pointer;
  font-weight: bold;
  font-size: 14px;
}

.copy-btn:hover {
  background: #45B7D1;
}
</style>
