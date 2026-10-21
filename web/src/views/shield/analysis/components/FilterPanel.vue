<template>
  <section class="filter-panel" aria-label="筛选条件">
    <!-- 下拉框改了就查询；两组范围输入在回车或失焦（change）且校验通过时查询 -->
    <el-form :model="form" class="filter-form" @submit.prevent="emitChange">
      <div class="filter-row">
        <el-select v-model="form.project" class="filter-project" clearable filterable placeholder="全部" aria-label="项目" @change="onProjectChange">
          <template #prefix><span class="filter-label">项目</span></template>
          <el-option v-for="item in projectList" :key="item.id" :label="item.project_name" :value="item.id" />
        </el-select>
        <el-select v-model="form.shield_machine" class="filter-machine" clearable filterable placeholder="全部" aria-label="盾构机" @change="onMainFilterChange">
          <template #prefix><span class="filter-label">盾构机</span></template>
          <el-option v-for="item in machineList" :key="item.id" :label="item.shield_model" :value="item.id" />
        </el-select>
        <el-select v-model="form.stratum_type" class="filter-stratum" clearable filterable placeholder="全部" aria-label="地层类型"
          :loading="optionsLoading" :disabled="!!optionsError" @change="onStratumChange">
          <template #prefix><span class="filter-label">地层类型</span></template>
          <el-option v-for="item in stratumTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-form-item class="range-field" :error="rangeError" inline-message>
          <span class="filter-label">环号范围</span>
          <el-input v-model="form.start_ring" class="range-input" aria-label="起始环号" inputmode="numeric" placeholder="起始环" @change="onScopeChange" />
          <span class="range-separator">至</span>
          <el-input v-model="form.end_ring" class="range-input" aria-label="结束环号" inputmode="numeric" placeholder="结束环" @change="onScopeChange" />
        </el-form-item>
        <el-select v-model="form.summary_status" class="filter-status" aria-label="开仓状态" @change="onScopeChange">
          <template #prefix><span class="filter-label">开仓状态</span></template>
          <el-option label="已确认开仓" value="CONFIRMED" />
          <el-option label="草稿开仓" value="DRAFT" />
          <el-option label="全部状态" value="ALL" />
        </el-select>
        <el-button class="more-toggle" :aria-expanded="moreOpen" aria-controls="analysis-more-filters" @click="moreOpen = !moreOpen">
          更多条件<span v-if="moreCount" class="more-badge">{{ moreCount }}</span>
        </el-button>
        <span class="filter-spacer" />
        <el-button @click="onReset">重置</el-button>
      </div>
      <div v-show="moreOpen" id="analysis-more-filters" class="filter-row">
        <el-select v-model="form.tool_parent_type" class="filter-tool-type" clearable placeholder="全部" aria-label="刀具类型" @change="onMainFilterChange">
          <template #prefix><span class="filter-label">刀具类型</span></template>
          <el-option v-for="item in toolTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="form.tool_type_name" class="filter-tool-name" clearable filterable placeholder="全部" aria-label="刀具细分类型" :loading="optionsLoading" @change="onToolTypeNameChange">
          <template #prefix><span class="filter-label">刀具细分类型</span></template>
          <el-option v-for="item in toolTypeNameOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="form.manufacturer" class="filter-manufacturer" clearable filterable placeholder="全部" aria-label="厂家" :loading="optionsLoading" @change="emitChange">
          <template #prefix><span class="filter-label">厂家</span></template>
          <el-option v-for="item in manufacturerList" :key="item" :label="item" :value="item" />
        </el-select>
        <el-form-item class="range-field" :error="trackRangeError" inline-message>
          <span class="filter-label">刀刃轨迹范围（mm）</span>
          <el-input v-model="form.blade_track_min" class="range-input" aria-label="刀刃轨迹最小值" inputmode="decimal" placeholder="最小半径" @change="onScopeChange" />
          <span class="range-separator">至</span>
          <el-input v-model="form.blade_track_max" class="range-input" aria-label="刀刃轨迹最大值" inputmode="decimal" placeholder="最大半径" @change="onScopeChange" />
        </el-form-item>
      </div>
    </el-form>
    <div v-if="optionsError || listsError" class="filter-error" role="alert">
      <span>{{ optionsError || listsError }}</span>
      <el-button link type="primary" @click="retryOptions">重试加载选项</el-button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { request } from '/@/utils/service';
import { getFilterOptions } from '../api';
import type { AnalysisFilter } from '../types';

const emit = defineEmits(['filter-change']);
const defaults = (): AnalysisFilter => ({ summary_status: 'CONFIRMED', start_ring: '', end_ring: '', blade_track_min: '', blade_track_max: '', tool_parent_type: '', tool_type_name: '', manufacturer: '', stratum_type: '' });
const form = reactive<AnalysisFilter>(defaults());
const appliedFilter = ref<AnalysisFilter>({ summary_status: 'CONFIRMED' });
const projectList = ref<Array<{ id: number; project_name: string }>>([]);
const machineList = ref<Array<{ id: number; shield_model: string }>>([]);
const toolTypeOptions = ref([{ label: '滚刀', value: 'DISC' }, { label: '刮刀', value: 'SCRAPER' }]);
const toolTypeNameOptions = ref<Array<{ value: string; label: string }>>([]);
const stratumTypeOptions = ref<Array<{ value: string; label: string }>>([]);
const manufacturerList = ref<string[]>([]);
const optionsLoading = ref(false);
const optionsError = ref('');
const listsError = ref('');
const rangeError = ref('');
const trackRangeError = ref('');
let optionGeneration = 0;
let listGeneration = 0;
let alive = true;
const moreOpen = ref(false);
// "更多条件"里有几项不是默认值：刀具类型、细分类型、厂家、刀刃轨迹范围（上下限算一项）
const moreCount = computed(() => [
  form.tool_parent_type, form.tool_type_name, form.manufacturer,
  String(form.blade_track_min ?? '').trim() || String(form.blade_track_max ?? '').trim(),
].filter(Boolean).length);
function validRange() {
  const start = String(form.start_ring ?? '').trim();
  const end = String(form.end_ring ?? '').trim();
  rangeError.value = [start, end].some(v => v && (!/^\d+$/.test(v) || Number(v) > 2147483647))
    ? '环号须为有效的非负整数' : start && end && Number(start) > Number(end) ? '起始环号不能大于结束环号' : '';
  const min = String(form.blade_track_min ?? '').trim();
  const max = String(form.blade_track_max ?? '').trim();
  trackRangeError.value = [min, max].some(v => v && (!/^\d+(\.\d+)?$/.test(v) || !Number.isFinite(Number(v))))
    ? '轨迹须为非负数，单位 mm，可输入小数' : min && max && Number(min) > Number(max) ? '最小轨迹不能大于最大轨迹' : '';
  return !rangeError.value && !trackRangeError.value;
}
function snapshot(includeManufacturer = true): AnalysisFilter {
  const result: AnalysisFilter = { summary_status: form.summary_status || 'CONFIRMED' };
  for (const key of ['project', 'shield_machine', 'tool_parent_type', 'tool_type_name', 'stratum_type', 'start_ring', 'end_ring', 'blade_track_min', 'blade_track_max', ...(includeManufacturer ? ['manufacturer'] : [])]) {
    const value = form[key as keyof AnalysisFilter];
    if (value !== undefined && value !== null && value !== '') (result as Record<string, unknown>)[key] = typeof value === 'string' ? value.trim() : value;
  }
  return result;
}
async function fetchLists() {
  const generation = ++listGeneration;
  listsError.value = '';
  try {
    const [projects, machines] = await Promise.all([
      request({ url: '/api/shield/project/', method: 'get', params: { limit: 999 } }),
      request({ url: '/api/shield/shield_machine_basic_info/', method: 'get', params: { limit: 999 } }),
    ]);
    if (!alive || generation !== listGeneration) return;
    const rows = (res: any) => res?.data?.results ?? res?.data ?? [];
    projectList.value = rows(projects);
    machineList.value = rows(machines);
  } catch {
    if (alive && generation === listGeneration) listsError.value = '项目或盾构机选项加载失败';
  }
}
async function fetchAnalysisOptions() {
  const generation = ++optionGeneration;
  if (!validRange()) { optionsLoading.value = false; return; }
  const filter = snapshot(false);
  delete filter.tool_type_name;
  delete filter.stratum_type;
  const selectedType = form.tool_type_name;
  const selectedStratum = form.stratum_type;
  optionsLoading.value = true;
  optionsError.value = '';
  try {
    const res = await getFilterOptions(filter);
    if (!alive || generation !== optionGeneration) return;
    const data = res?.data ?? res;
    toolTypeOptions.value = data?.tool_types ?? toolTypeOptions.value;
    toolTypeNameOptions.value = data?.tool_type_names ?? [];
    stratumTypeOptions.value = data?.stratum_types ?? [];
    let manufacturers = data?.manufacturers ?? [];
    if (selectedType || selectedStratum) {
      const response = await getFilterOptions({ ...filter,
        ...(selectedType ? { tool_type_name: selectedType } : {}),
        ...(selectedStratum ? { stratum_type: selectedStratum } : {}),
      });
      if (!alive || generation !== optionGeneration) return;
      manufacturers = (response?.data ?? response)?.manufacturers ?? [];
    }
    manufacturerList.value = manufacturers;
  } catch {
    if (alive && generation === optionGeneration) {
      optionsError.value = '分析选项加载失败，可重试；已应用的查询范围保持不变';
      toolTypeNameOptions.value = [];
      stratumTypeOptions.value = [];
      manufacturerList.value = [];
    }
  } finally {
    if (alive && generation === optionGeneration) optionsLoading.value = false;
  }
}
function emitChange() {
  if (!validRange()) return;
  const filter = snapshot();
  appliedFilter.value = { ...filter };
  emit('filter-change', filter);
}
function onProjectChange() { form.shield_machine = undefined; form.stratum_type = ''; onMainFilterChange(); }
function onMainFilterChange() { form.tool_type_name = ''; form.manufacturer = ''; onScopeChange(); }
function onToolTypeNameChange() { form.manufacturer = ''; onScopeChange(); }
function onStratumChange() { form.manufacturer = ''; onScopeChange(); }
function onScopeChange() { fetchAnalysisOptions(); emitChange(); }
function onReset() {
  for (const key of Object.keys(form)) delete form[key as keyof AnalysisFilter];
  Object.assign(form, defaults());
  onScopeChange();
}
function retryOptions() { fetchLists(); fetchAnalysisOptions(); }
onMounted(retryOptions);
onBeforeUnmount(() => { alive = false; optionGeneration++; listGeneration++; });
</script>

<style scoped>
.filter-panel { margin-bottom: 8px; }
.filter-form { display: grid; gap: 8px; }
.filter-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.filter-label { font-size: var(--el-font-size-extra-small); color: var(--dv-text-muted); white-space: nowrap; }
.filter-project { width: 260px; }
.filter-machine { width: 230px; }
.filter-stratum { width: 200px; }
.filter-status { width: 180px; }
.filter-tool-type { width: 170px; }
.filter-tool-name { width: 240px; }
.filter-manufacturer { width: 200px; }
.range-field { margin: 0; }
.range-field :deep(.el-form-item__content) { gap: 6px; flex-wrap: nowrap; }
.range-input { width: 84px; }
.range-separator { color: var(--dv-text-muted); font-size: var(--el-font-size-extra-small); }
.range-field :deep(.el-form-item__error--inline) { margin-left: 4px; white-space: nowrap; }
.more-badge { display: inline-block; min-width: 16px; margin-left: 6px; padding: 0 5px; border-radius: var(--dv-radius-pill); background: var(--dv-info-bg); color: var(--dv-info-text); font-size: var(--el-font-size-extra-small); line-height: 16px; text-align: center; }
.filter-spacer { flex: 1 1 0; }
.filter-error { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; color: var(--el-color-danger); font-size: var(--el-font-size-extra-small); margin-top: 8px; }
@media (max-width: 600px) {
  .filter-row > .el-select { width: 100%; }
  .range-field :deep(.el-form-item__content) { flex-wrap: wrap; }
}
</style>
