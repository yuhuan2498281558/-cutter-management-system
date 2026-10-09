<template>
  <div class="photo-preview" :aria-busy="status === 'loading'">
    <img v-if="imageRequest" v-show="status === 'loaded'" :key="imageRequest.id"
      :src="imageRequest.src" :alt="name" @load="imageRequest.onLoad" @error="imageRequest.onError" />
    <div v-if="status === 'loading' || status === 'error'" class="photo-feedback" role="status" aria-live="polite">
      <span>{{ status === 'loading' ? '照片加载中…' : '照片加载失败，请检查网络后重试' }}</span>
      <el-button v-if="status === 'error'" type="primary" plain @click="retry">重新加载</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, shallowRef, watch, onScopeDispose } from 'vue';

const props = defineProps<{ src: string; name: string; active: boolean }>();
const status = ref<'idle' | 'loading' | 'loaded' | 'error'>('idle');
const imageRequest = shallowRef<{ id: number; src: string; onLoad: () => void; onError: () => void } | null>(null);
let generation = 0;

function loadPhoto() {
  const id = ++generation;
  if (!props.active || !props.src) {
    status.value = 'idle';
    imageRequest.value = null;
    return;
  }
  status.value = 'loading';
  // Each image owns its callbacks, so a replaced/closed image cannot update a new preview.
  imageRequest.value = {
    id,
    src: props.src,
    onLoad: () => { if (id === generation) status.value = 'loaded'; },
    onError: () => { if (id === generation) status.value = 'error'; },
  };
}

function retry() {
  if (status.value === 'error') loadPhoto();
}

watch(() => [props.src, props.active], loadPhoto, { immediate: true, flush: 'sync' });
onScopeDispose(() => { generation++; });
</script>

<style scoped>
.photo-preview {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: min(220px, 50vh);
  background: var(--el-fill-color-light);
}
.photo-preview img { display: block; max-width: 100%; max-height: 68vh; max-height: 68dvh; object-fit: contain; }
.photo-feedback { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 24px 16px; text-align: center; color: var(--el-text-color-regular); line-height: 1.6; }
</style>
