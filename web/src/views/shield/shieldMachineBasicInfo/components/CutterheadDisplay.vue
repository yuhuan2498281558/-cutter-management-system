<template>
  <div class="cutterhead-display">
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
          cursor: isDragging ? 'grabbing' : 'default'
        }"
        @mousedown="startDrag"
        @mousemove="onDrag"
        @mouseup="endDrag"
        @mouseleave="endDrag"
        @wheel="handleWheel"
        @contextmenu.prevent
      >
        <div class="image-container">
          <img src="/cutterhead-placeholder.svg" alt="刀盘" draggable="false" />
          <svg
            class="hotspot-layer"
            :width="IMAGE_WIDTH"
            :height="IMAGE_HEIGHT"
            :viewBox="`0 0 ${IMAGE_WIDTH} ${IMAGE_HEIGHT}`"
          >
            <g
              v-for="pos in displayPositions"
              :key="pos.code"
              class="cutter-point-hit"
              :class="{ 'cutter-point-selected': pos.code === selectedCutterCode }"
              @click="selectCutter(pos)"
            >
              <title>{{ '刀位 ' + pos.code }}</title>
              <circle :cx="pos.x" :cy="pos.y" :r="pos.code === selectedCutterCode ? 24 : 16" class="cutter-point" />
              <text :x="pos.x" :y="pos.y - 26" class="cutter-label">{{ pos.code }}</text>
            </g>
          </svg>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, withDefaults } from 'vue';
import { ACTIVE_CUTTER_POSITIONS, CUTTERHEAD_IMAGE_SIZE } from '/@/constants/cutterPositions';
import type { CutterInfo } from '/@/types/cutter.types';

interface Props {
  selectedCutterCode?: string;
}

const props = withDefaults(defineProps<Props>(), {
  selectedCutterCode: '',
});

const emit = defineEmits<{
  (e: 'cutter-selected', cutterInfo: CutterInfo): void;
}>();

const containerRef = ref<HTMLDivElement>();
const IMAGE_WIDTH = CUTTERHEAD_IMAGE_SIZE.width;
const IMAGE_HEIGHT = CUTTERHEAD_IMAGE_SIZE.height;

// 缩放和拖拽相关
const scale = ref(1);
const translateX = ref(0);
const translateY = ref(0);
const isDragging = ref(false);
const dragStartX = ref(0);
const dragStartY = ref(0);
const dragStartTranslateX = ref(0);
const dragStartTranslateY = ref(0);

// 使用共享的刀位坐标配置
const displayPositions = ACTIVE_CUTTER_POSITIONS;

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
  if (e.button !== 2) return;
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

const selectCutter = (pos: CutterInfo) => {
  emit('cutter-selected', pos);
};

</script>

<style scoped>
.cutterhead-display {
  width: 100%;
  height: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  background: #0a0a0a;
}

.image-area {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: #0a0a0a;
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 100%;
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
  max-width: 95%;
  max-height: 95%;
  display: flex;
  justify-content: center;
  align-items: center;
}

.image-container {
  position: relative;
  display: inline-block;
  line-height: 0;
}

.image-container img {
  display: block;
  width: 100%;
  height: auto;
  user-select: none;
}

.hotspot-layer {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: auto;
}

.cutter-point-hit {
  cursor: pointer;
  pointer-events: all;
}

.cutter-point {
  fill: rgba(255, 107, 107, 0.82);
  stroke: #351414;
  stroke-width: 3;
  vector-effect: non-scaling-stroke;
  transition: fill 0.2s ease, stroke 0.2s ease, filter 0.2s ease, r 0.2s ease;
}

.cutter-label {
  fill: #fff;
  font-size: 28px;
  font-weight: 700;
  text-anchor: middle;
  paint-order: stroke;
  stroke: rgba(0, 0, 0, 0.9);
  stroke-width: 5px;
  pointer-events: none;
}

.cutter-point-hit:hover .cutter-point,
.cutter-point-selected .cutter-point {
  fill: #2563eb;
  stroke: #fff;
  filter: drop-shadow(0 0 8px rgba(37, 99, 235, 0.8));
}
</style>
