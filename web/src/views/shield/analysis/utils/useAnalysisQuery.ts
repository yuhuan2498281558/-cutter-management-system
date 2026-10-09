import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, shallowRef, watch } from 'vue';
import type { AnalysisFilter } from '../types';

/** A result is only ready for the exact applied filter and active page generation. */
export function useAnalysisQuery<T>(
  filter: () => AnalysisFilter,
  fetchData: (snapshot: AnalysisFilter) => Promise<T>,
) {
  const data = shallowRef<T | null>(null);
  const loading = ref(false);
  const error = ref('');
  let generation = 0;
  let active = true;
  let deactivated = false;
  const ready = computed(() => data.value !== null && !loading.value && !error.value);
  function invalidate() { generation++; data.value = null; loading.value = false; }
  async function load() {
    if (!active) return;
    const current = ++generation;
    data.value = null;
    loading.value = true;
    error.value = '';
    try {
      const snapshot: AnalysisFilter = JSON.parse(JSON.stringify(filter()));
      const result = await fetchData(snapshot);
      if (result && [snapshot.blade_track_min, snapshot.blade_track_max].some(value => value !== undefined && value !== '')) {
        const payload = result as Record<string, any>;
        const metas = payload.meta ? [payload.meta] : Object.values(payload).map(value => value?.meta).filter(Boolean);
        if (!metas.length || metas.some(meta => !meta.filter_capabilities?.includes('blade_track_range'))) {
          throw new Error('当前分析服务尚不支持刀刃轨迹范围，未展示未筛选结果。请加载新版后端后重新查询。');
        }
      }
      if (active && current === generation) data.value = result;
    } catch (cause) {
      if (active && current === generation) error.value = cause instanceof Error ? cause.message : '数据加载失败，请重新加载';
    } finally {
      if (active && current === generation) loading.value = false;
    }
  }
  function scheduleLoad() {
    invalidate();
    if (!active) return;
    const queued = generation;
    loading.value = true;
    error.value = '';
    // Disable stale results immediately, then fetch only the final filter after linked resets.
    void Promise.resolve().then(() => {
      if (active && queued === generation) return load();
    });
  }
  watch(filter, scheduleLoad, { deep: true, flush: 'sync' });
  onMounted(load);
  onDeactivated(() => { active = false; deactivated = true; invalidate(); });
  onActivated(() => { if (deactivated) { active = true; deactivated = false; load(); } });
  onBeforeUnmount(() => { active = false; invalidate(); });
  return { data, loading, error, ready, load, invalidate };
}
