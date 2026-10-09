<template>
  <div class="mapper-container">
    <div class="toolbar">
      <div class="toolbar-title">
        <div>
          <h3>滚刀 1–80b、Y1/Y3/Y5 圆点标注</h3>
          <p>选择刀位后点击图纸中的正确位置，当前坐标会被直接覆盖。</p>
        </div>
        <button class="close-btn" @click="emit('close')">退出标注</button>
      </div>
      <div class="position-selector">
        <button
          v-for="pos in positions"
          :key="pos.code"
          :class="{ active: pos.code === currentCode }"
          @click="currentCode = pos.code"
        >
          {{ pos.code }}
          <span>{{ pos.x }}, {{ pos.y }}</span>
        </button>
      </div>
      <div class="controls">
        <div class="current-position">
          当前标注：<strong>{{ currentCode }}</strong>
          <span>左键重新定位 · 右键拖动 · 滚轮缩放</span>
        </div>
        <button :disabled="history.length === 0" @click="undoLast">撤销修改</button>
        <button @click="resetPositions">恢复原坐标</button>
        <button @click="exportData">导出 JSON</button>
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
          :src="CUTTERHEAD_IMAGE"
          @click="handleClick"
          @load="onImageLoad"
          draggable="false"
        />
        <svg class="overlay" :viewBox="`0 0 ${imageWidth} ${imageHeight}`">
          <g v-for="pos in positions" :key="pos.code">
            <circle
              :cx="pos.x"
              :cy="pos.y"
              :r="pos.code === currentCode ? 15 : 11"
              :fill="pos.code === currentCode ? 'rgba(255, 159, 67, 0.72)' : 'rgba(78, 205, 196, 0.58)'"
              :stroke="pos.code === currentCode ? '#ff9f43' : '#4ECDC4'"
              :stroke-width="pos.code === currentCode ? 4 : 3"
            />
            <text
              :x="pos.x"
              :y="pos.y - 17"
              fill="#fff"
              font-size="18"
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
      <h4>校准坐标（复制到 cutterPositions.ts 的 FINAL_POSITION_OVERRIDES）：</h4>
      <textarea v-model="outputCode" readonly></textarea>
      <button @click="copyCode" class="copy-btn">复制代码</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { ACTIVE_CUTTER_POSITIONS } from '/@/constants/cutterPositions';
import { CUTTERHEAD_IMAGE } from '/@/utils/engineeringAssets';

const emit = defineEmits<{
  close: [];
}>();

type MarkerPosition = { code: string; type: string; x: number; y: number };

const TARGET_CODES = [
  ...Array.from({ length: 79 }, (_, index) => String(index + 1)),
  '80a',
  '80b',
  'y1',
  'y3',
  'y5',
];
const clonePositions = (value: MarkerPosition[]) => value.map(position => ({ ...position }));
const initialPositions: MarkerPosition[] = TARGET_CODES.map(code => {
  const position = ACTIVE_CUTTER_POSITIONS.find(item => item.code.toUpperCase() === code.toUpperCase());
  if (!position) throw new Error(`未找到刀位 ${code} 的坐标`);
  return { ...position };
});

const imageRef = ref<HTMLImageElement>();
const containerRef = ref<HTMLDivElement>();
const imageWidth = ref(1900);
const imageHeight = ref(2100);
const currentCode = ref(TARGET_CODES[0]);
const positions = ref<MarkerPosition[]>(clonePositions(initialPositions));
const history = ref<MarkerPosition[][]>([]);

// 缩放和拖拽相关
const scale = ref(1);
const translateX = ref(0);
const translateY = ref(0);
const isDragging = ref(false);
const dragStartX = ref(0);
const dragStartY = ref(0);
const dragStartTranslateX = ref(0);
const dragStartTranslateY = ref(0);

const onImageLoad = () => {
  if (imageRef.value) {
    imageWidth.value = imageRef.value.naturalWidth;
    imageHeight.value = imageRef.value.naturalHeight;
  }
};

const handleClick = (e: MouseEvent) => {
  if (!currentCode.value) {
    alert('请先输入刀位编号');
    return;
  }
  // 只响应左键点击
  if (e.button !== 0) return;

  const rect = (e.target as HTMLElement).getBoundingClientRect();
  const x = (e.clientX - rect.left) / scale.value;
  const y = (e.clientY - rect.top) / scale.value;
  const scaleX = imageWidth.value / (rect.width / scale.value);
  const scaleY = imageHeight.value / (rect.height / scale.value);

  const actualX = Math.round(x * scaleX);
  const actualY = Math.round(y * scaleY);
  const positionIndex = positions.value.findIndex(position => position.code === currentCode.value);
  if (positionIndex < 0) return;

  history.value.push(clonePositions(positions.value));
  positions.value[positionIndex] = {
    ...positions.value[positionIndex],
    x: actualX,
    y: actualY,
  };

  const nextCode = TARGET_CODES[positionIndex + 1];
  if (nextCode) currentCode.value = nextCode;
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

const undoLast = () => {
  const previous = history.value.pop();
  if (previous) positions.value = previous;
};

const resetPositions = () => {
  history.value.push(clonePositions(positions.value));
  positions.value = clonePositions(initialPositions);
  currentCode.value = TARGET_CODES[0];
};

const outputCode = computed(() => {
  if (positions.value.length === 0) return '';

  return positions.value.map(position =>
    `  '${position.code.toUpperCase()}': { x: ${position.x}, y: ${position.y} },`
  ).join('\n');
});

const copyCode = async () => {
  await navigator.clipboard.writeText(outputCode.value);
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
  URL.revokeObjectURL(url);
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
  padding: 12px;
  gap: 12px;
  box-sizing: border-box;
}

.toolbar {
  background: #2a2a2a;
  padding: 12px;
  border-radius: 8px;
}

.toolbar h3 {
  margin: 0;
  color: #4ECDC4;
}

.toolbar-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.toolbar-title p {
  margin: 5px 0 0;
  color: #aeb7c2;
  font-size: 13px;
}

.close-btn {
  flex: none;
  padding: 7px 14px;
  border: 1px solid #59636f;
  border-radius: 5px;
  background: transparent;
  color: #dce3ea;
  cursor: pointer;
}

.position-selector {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(76px, 1fr));
  gap: 6px;
  margin-top: 12px;
  max-height: 118px;
  padding-right: 4px;
  overflow-y: auto;
}

.position-selector button {
  min-width: 0;
  padding: 6px 4px;
  border: 1px solid #53606c;
  border-radius: 5px;
  background: #343b43;
  color: #fff;
  font-weight: 700;
  cursor: pointer;
}

.position-selector button span {
  display: block;
  margin-top: 2px;
  color: #9aa7b3;
  font-size: 10px;
  font-weight: 400;
}

.position-selector button.active {
  border-color: #ff9f43;
  background: rgba(255, 159, 67, 0.18);
  color: #ffb66f;
}

.controls {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.controls button {
  padding: 7px 12px;
  background: #4ECDC4;
  border: none;
  border-radius: 4px;
  color: #000;
  cursor: pointer;
  font-weight: bold;
}

.controls button:disabled {
  cursor: not-allowed;
  opacity: 0.42;
}

.controls button:hover {
  background: #45B7D1;
}

.current-position {
  flex: 1;
  color: #dce3ea;
  font-size: 13px;
}

.current-position strong {
  margin: 0 8px;
  color: #ffb66f;
  font-size: 17px;
}

.current-position span {
  color: #8f9ba7;
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
  height: 100%;
  max-width: 100%;
  aspect-ratio: 1900 / 2100;
  transition: transform 0.1s ease-out;
  transform-origin: center center;
}

.image-wrapper img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: contain;
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
  padding: 10px 12px;
  border-radius: 8px;
}

.output h4 {
  margin: 0 0 10px 0;
  color: #4ECDC4;
}

.output textarea {
  width: 100%;
  height: 72px;
  background: #333;
  border: 1px solid #555;
  border-radius: 4px;
  color: #fff;
  padding: 10px;
  font-family: monospace;
  font-size: 11px;
  margin-bottom: 8px;
  box-sizing: border-box;
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
