<template>
  <section class="cutterhead-panel">
    <header class="drawing-controls">
      <h3>刀盘刀位</h3>
      <el-button size="small" :aria-pressed="zoomed" @click="zoomed = !zoomed">{{ zoomed ? '适应窗口' : '放大刀盘' }}</el-button>
    </header>
    <div class="cutterhead-scroll" :class="{ zoomed }">
    <svg class="cutterhead" :viewBox="drawingViewBox" aria-label="刀盘刀位，选择刀位查看服役历史">
      <defs>
        <clipPath id="lifecycle-cutter-face" clipPathUnits="userSpaceOnUse">
          <circle :cx="CUTTERHEAD_IMAGE_CENTER.x" :cy="CUTTERHEAD_IMAGE_CENTER.y" :r="FACE_RADIUS" />
        </clipPath>
      </defs>
      <image :href="CUTTERHEAD_IMAGE" :width="CUTTERHEAD_IMAGE_SIZE.width" :height="CUTTERHEAD_IMAGE_SIZE.height" clip-path="url(#lifecycle-cutter-face)" />
      <g v-for="position in ACTIVE_CUTTER_POSITIONS" :key="position.code"
        role="button" tabindex="0" :aria-label="`${position.code}号刀位`" :aria-pressed="modelValue === position.code"
        @click="$emit('update:modelValue', position.code)" @keydown.enter.prevent="$emit('update:modelValue', position.code)"
        @keydown.space.prevent="$emit('update:modelValue', position.code)">
        <circle class="position-marker" :cx="position.x" :cy="position.y" r="24" :class="{ selected: modelValue === position.code }" />
        <text :x="position.x" :y="position.y + 7" text-anchor="middle">{{ position.code }}</text>
      </g>
    </svg>
    </div>
    <footer class="drawing-caption"><span>点击刀位查看服役历史</span><strong>已选 {{ modelValue }} 号刀位</strong></footer>
  </section>
</template>
<script setup lang="ts">
import { ACTIVE_CUTTER_POSITIONS, CUTTERHEAD_IMAGE_SIZE, CUTTERHEAD_IMAGE_CENTER } from '/@/constants/cutterPositions';
import { CUTTERHEAD_IMAGE } from '/@/utils/engineeringAssets';
import { ref } from 'vue';
const zoomed = ref(false);
// Crop only the drawing background; marker coordinates stay in the original
// engineering image space, including the three positions outside the rim.
const FACE_RADIUS = 738;
const VIEW_RADIUS = 810;
const drawingViewBox = `${CUTTERHEAD_IMAGE_CENTER.x - VIEW_RADIUS} ${CUTTERHEAD_IMAGE_CENTER.y - VIEW_RADIUS} ${VIEW_RADIUS * 2} ${VIEW_RADIUS * 2}`;
defineProps<{ modelValue: string }>();
defineEmits<{ (event: 'update:modelValue', value: string): void }>();
</script>
<style scoped>
.cutterhead-panel { min-width: 0; padding: 16px; border: 1px solid #e4e7ed; border-radius: 6px; background: #fff; }
.drawing-controls { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.drawing-controls h3 { margin: 0; color: #303133; font-size: 16px; font-weight: 600; }
.cutterhead-scroll { overflow: auto; max-height: min(640px, 70vh); background: #fff; }
.cutterhead { display: block; width: 100%; max-width: 560px; aspect-ratio: 1; margin: auto; }
.zoomed .cutterhead { width: 1000px; min-width: 1000px; max-width: none; }
.drawing-caption { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 12px; padding-top: 12px; border-top: 1px solid #ebeef5; color: #606266; font-size: 12px; }
.drawing-caption strong { color: #337ecc; font-weight: 600; }
g { cursor: pointer; }
.position-marker { fill: #fff; stroke: #337ecc; stroke-width: 3; }
.position-marker.selected { fill: #a0cfff; stroke-width: 6; }
g:focus-visible { outline: none; }
g:focus-visible .position-marker { stroke: #e6a23c; stroke-width: 6; }
text { font-size: 20px; fill: #172b4d; font-weight: 600; pointer-events: none; }
@media (max-width: 600px) { .cutterhead-panel { padding: 12px; } }
</style>
