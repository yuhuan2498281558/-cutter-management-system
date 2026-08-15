<template>
  <div class="cutterhead-image-container">
    <div v-if="selectedCutter" class="cutter-info-panel">
      <div class="panel-header">
        <h4>刀位详情 - {{ selectedCutter.code }}</h4>
        <button @click="selectedCutter = null" class="close-btn">×</button>
      </div>
      <div class="panel-content">
        <div class="section">
          <h5>基本信息</h5>
          <div class="info-row">
            <span class="label">刀位编号:</span>
            <span class="value">{{ selectedCutter.code }}</span>
          </div>
          <div class="info-row">
            <span class="label">刀具类型:</span>
            <span class="value">{{ selectedCutter.type }}</span>
          </div>
        </div>
        <div class="section">
          <h5>当前刀具</h5>
          <div v-if="selectedCutter.current">
            <div class="info-row">
              <span class="label">刀具名称:</span>
              <span class="value">{{ selectedCutter.current.name }}</span>
            </div>
            <div class="info-row">
              <span class="label">刀具编号:</span>
              <span class="value">{{ selectedCutter.current.serialNumber }}</span>
            </div>
            <div class="info-row">
              <span class="label">开始使用环号:</span>
              <span class="value">{{ selectedCutter.current.startRing }}</span>
            </div>
          </div>
          <div v-else class="empty">暂无数据</div>
        </div>
        <div class="section">
          <h5>历史记录</h5>
          <div v-if="selectedCutter.history?.length" class="history-list">
            <div v-for="(h, i) in selectedCutter.history" :key="i" class="history-item">
              <div class="history-header">
                <span class="num">{{ i + 1 }}</span>
                <span>{{ h.serialNumber }}</span>
              </div>
              <div class="detail">使用环号: {{ h.startRing }} - {{ h.endRing }}</div>
              <div class="detail">使用时间: {{ h.usageDuration }}小时</div>
              <div class="detail">掘进里程: {{ h.drivingDistance }}米</div>
              <div class="detail">价格: ¥{{ h.price.toLocaleString() }}</div>
              <div class="detail">厂家: {{ h.manufacturer }}</div>
              <div class="detail">更换日期: {{ h.replaceDate }}</div>
            </div>
          </div>
          <div v-else class="empty">暂无历史记录</div>
        </div>
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
          <img src="/cutterhead-placeholder.svg" alt="刀盘" @load="onImageLoad" ref="imageRef" draggable="false" />
          <svg
            class="hotspot-layer"
            :width="imageWidth"
            :height="imageHeight"
            :viewBox="`0 0 ${imageWidth} ${imageHeight}`"
          >
            <g
              v-for="pos in cutterPositions"
              :key="pos.code"
              class="cutter-outline-hit"
              :class="{ 'cutter-outline-selected': pos.code === selectedCutter?.code }"
              :transform="getCutterOutline(pos).transform"
              @click="selectCutter(pos)"
            >
              <title>{{ '刀位 ' + pos.code }}</title>
              <path :d="getCutterOutline(pos).path" class="cutter-outline" />
              <path :d="getCutterOutline(pos).detailPath" class="cutter-outline-detail" />
            </g>
          </svg>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { getCutterInfo, type CutterPositionInfo } from './cutterApi';
import { ACTIVE_CUTTER_POSITIONS } from '/@/constants/cutterPositions';
import { getCutterOutline } from '/@/constants/cutterOutlines';

const imageRef = ref<HTMLImageElement>();
const containerRef = ref<HTMLDivElement>();
const imageWidth = ref(1000);
const imageHeight = ref(1000);
const selectedCutter = ref<CutterPositionInfo | null>(null);

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

// 使用共享的刀位坐标配置
const cutterPositions = ref(ACTIVE_CUTTER_POSITIONS);

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

const selectCutter = async (pos: any) => {
  const info = await getCutterInfo(pos.code);
  selectedCutter.value = info;
};
</script>

<style scoped>
.cutterhead-image-container {
  width: 100%;
  height: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  background: #0a0a0a;
  position: relative;
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
  width: 100%;
  height: 100%;
  padding: 20px;
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

.cutter-outline-hit {
  cursor: pointer;
  pointer-events: all;
}

.cutter-outline {
  fill: rgba(255, 107, 107, 0.18);
  stroke: #ff6b6b;
  stroke-width: 2;
  vector-effect: non-scaling-stroke;
  transition: fill 0.2s ease, stroke 0.2s ease, filter 0.2s ease;
}

/* 真实剖面线很密，描边必须细，否则糊成色块 */
.cutter-outline-detail {
  fill: none;
  stroke: #8f2d2d;
  stroke-width: 1.2;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
  pointer-events: none;
}

.cutter-outline-hit:hover .cutter-outline,
.cutter-outline-selected .cutter-outline {
  fill: rgba(255, 107, 107, 0.6);
  stroke: #fff;
  filter: drop-shadow(0 0 8px rgba(255, 107, 107, 0.8));
}

.cutter-outline-hit:hover .cutter-outline-detail,
.cutter-outline-selected .cutter-outline-detail {
  stroke: #fff;
}

.cutter-info-panel {
  position: absolute;
  top: 20px;
  right: 20px;
  width: 350px;
  max-height: 90vh;
  overflow-y: auto;
  background: rgba(30, 30, 30, 0.95);
  border: 1px solid #444;
  border-radius: 8px;
  padding: 16px;
  color: #fff;
  z-index: 100;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  border-bottom: 1px solid #555;
  padding-bottom: 8px;
}

.panel-header h4 {
  margin: 0;
  font-size: 16px;
}

.close-btn {
  background: none;
  border: none;
  color: #fff;
  font-size: 24px;
  cursor: pointer;
}

.section {
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid #444;
}

.section:last-child {
  border-bottom: none;
}

.section h5 {
  margin: 0 0 12px 0;
  font-size: 15px;
  color: #4ECDC4;
}

.info-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #333;
}

.info-row:last-child {
  border-bottom: none;
}

.label {
  color: #999;
  font-size: 14px;
}

.value {
  color: #fff;
  font-size: 14px;
  font-weight: bold;
}

.empty {
  text-align: center;
  color: #666;
  padding: 12px;
  font-size: 13px;
}

.history-list {
  max-height: 300px;
  overflow-y: auto;
}

.history-item {
  background: rgba(50, 50, 50, 0.5);
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 10px;
}

.history-header {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid #555;
  font-weight: bold;
}

.num {
  background: #4ECDC4;
  color: #000;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  margin-right: 8px;
}

.detail {
  font-size: 12px;
  color: #ccc;
  margin: 4px 0;
}
</style>
