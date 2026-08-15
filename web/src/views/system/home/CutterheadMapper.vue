<template>
  <div class="mapper-container">
    <div class="toolbar">
      <h3>刀位坐标标注工具</h3>
      <div class="controls">
        <input v-model="currentCode" placeholder="输入刀位编号（如：中1, G1, S1L）" @keyup.enter="focusType" />
        <input v-model="currentType" placeholder="输入刀具类型" ref="typeInput" @keyup.enter="focusCode" />
        <button @click="clearLast">撤销上一个</button>
        <button @click="exportData">导出配置</button>
      </div>
      <div class="info">
        <p>已标注: {{ positions.length }} 个刀位</p>
        <p v-if="currentCode">点击图片标注: {{ currentCode }}</p>
        <p class="hint">提示：左键点击标注，右键拖动移动，滚轮缩放</p>
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
              fill="rgba(78, 205, 196, 0.5)"
              stroke="#4ECDC4"
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
      <h4>配置代码（复制到CutterheadImage.vue）：</h4>
      <textarea v-model="outputCode" readonly></textarea>
      <button @click="copyCode" class="copy-btn">复制代码</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';

const imageRef = ref<HTMLImageElement>();
const containerRef = ref<HTMLDivElement>();
const typeInput = ref<HTMLInputElement>();
const imageWidth = ref(1000);
const imageHeight = ref(1000);
const currentCode = ref('');
const currentType = ref('');
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

  positions.value.push({
    code: currentCode.value,
    type: currentType.value || '刀具',
    x: actualX,
    y: actualY
  });

  console.log(`已添加: ${currentCode.value} at (${actualX}, ${actualY})`);

  // 自动清空输入框，准备下一个
  currentCode.value = '';
  currentType.value = '';
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

const clearLast = () => {
  positions.value.pop();
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

const focusType = () => {
  typeInput.value?.focus();
};

const focusCode = () => {
  // 标注后自动聚焦到编号输入框
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
  padding: 15px;
  border-radius: 8px;
}

.toolbar h3 {
  margin: 0 0 15px 0;
  color: #4ECDC4;
}

.controls {
  display: flex;
  gap: 10px;
  margin-bottom: 10px;
}

.controls input {
  flex: 1;
  padding: 8px;
  background: #333;
  border: 1px solid #555;
  border-radius: 4px;
  color: #fff;
}

.controls button {
  padding: 8px 16px;
  background: #4ECDC4;
  border: none;
  border-radius: 4px;
  color: #000;
  cursor: pointer;
  font-weight: bold;
}

.controls button:hover {
  background: #45B7D1;
}

.info {
  margin-top: 10px;
}

.info p {
  margin: 5px 0;
  color: #999;
  font-size: 14px;
}

.info .hint {
  color: #4ECDC4;
  font-size: 13px;
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
