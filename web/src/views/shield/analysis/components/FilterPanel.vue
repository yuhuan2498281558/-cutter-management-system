<template>
  <el-card class="filter-panel" shadow="never">
    <el-form :model="form" label-position="top" class="filter-form" @submit.prevent="emitChange">
      <el-form-item label="项目">
        <el-select v-model="form.project" clearable filterable placeholder="全部项目" @change="onProjectChange">
          <el-option v-for="item in projectList" :key="item.id" :label="item.project_name" :value="item.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="盾构机">
        <el-select v-model="form.shield_machine" clearable filterable placeholder="全部盾构机" @change="onMainFilterChange">
          <el-option v-for="item in machineList" :key="item.id" :label="item.shield_model" :value="item.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="刀具类型">
        <el-select v-model="form.tool_parent_type" clearable placeholder="全部类型" @change="onMainFilterChange">
          <el-option v-for="item in toolTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="刀具细分类型">
        <el-select v-model="form.tool_type_name" clearable filterable placeholder="全部细分类型" :loading="optionsLoading" @change="onToolTypeNameChange">
          <el-option v-for="item in toolTypeNameOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="厂家">
        <el-select v-model="form.manufacturer" clearable filterable placeholder="全部厂家" :loading="optionsLoading" @change="emitChange">
          <el-option v-for="item in manufacturerList" :key="item" :label="item" :value="item" />
        </el-select>
      </el-form-item>
      <el-form-item label="地层类型">
        <el-select v-model="form.stratum_type" clearable filterable placeholder="全部地层类型" aria-label="地层类型"
          :loading="optionsLoading" :disabled="!!optionsError" @change="onStratumChange">
          <el-option v-for="item in stratumTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="环号范围" class="ring-filter" :error="rangeError">
        <div class="ring-inputs">
          <el-input v-model="form.start_ring" aria-label="起始环号" inputmode="numeric" placeholder="起始环" @change="onScopeChange" />
          <span>至</span>
          <el-input v-model="form.end_ring" aria-label="结束环号" inputmode="numeric" placeholder="结束环" @change="onScopeChange" />
        </div>
      </el-form-item>
      <el-form-item label="开仓状态">
        <el-select v-model="form.summary_status" @change="onScopeChange">
          <el-option label="已确认开仓" value="CONFIRMED" />
          <el-option label="草稿开仓" value="DRAFT" />
          <el-option label="全部状态" value="ALL" />
        </el-select>
      </el-form-item>
      <el-form-item label="刀刃轨迹范围（mm）" class="ring-filter" :error="trackRangeError">
        <div class="ring-inputs">
          <el-input v-model="form.blade_track_min" aria-label="刀刃轨迹最小值" inputmode="decimal" placeholder="最小半径" @change="onScopeChange" />
          <span>至</span>
          <el-input v-model="form.blade_track_max" aria-label="刀刃轨迹最大值" inputmode="decimal" placeholder="最大半径" @change="onScopeChange" />
        </div>
      </el-form-item>
      <div class="filter-actions">
        <el-button @click="onReset">重置</el-button>
        <el-button type="primary" native-type="submit">查询</el-button>
      </div>
    </el-form>
    <div class="applied-scope" role="status"><span>查询范围</span>{{ appliedSummary }}</div>
    <div v-if="optionsError || listsError" class="filter-error" role="alert">
      <span>{{ optionsError || listsError }}</span>
      <el-button link type="primary" @click="retryOptions">重试加载选项</el-button>
    </div>
  </el-card>
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
const statusLabels: Record<string, string> = { CONFIRMED: '已确认开仓', DRAFT: '草稿开仓', ALL: '全部状态' };
const appliedSummary = computed(() => {
  const f = appliedFilter.value;
  return [
    projectList.value.find(p => String(p.id) === String(f.project))?.project_name || (f.project ? `项目 ${f.project}` : '全部项目'),
    machineList.value.find(m => String(m.id) === String(f.shield_machine))?.shield_model || (f.shield_machine ? `盾构机 ${f.shield_machine}` : '全部盾构机'),
    statusLabels[f.summary_status || 'CONFIRMED'],
    f.start_ring || f.end_ring ? `${f.start_ring || '起点'} 至 ${f.end_ring || '终点'} 环` : '全部环号',
    f.blade_track_min || f.blade_track_max ? `刀刃轨迹 ${f.blade_track_min || '不限下界'} 至 ${f.blade_track_max || '不限上界'} mm` : '',
    toolTypeOptions.value.find(t => t.value === f.tool_parent_type)?.label, f.tool_type_name, f.manufacturer,
    f.stratum_type ? `地层：${stratumTypeOptions.value.find(item => item.value === f.stratum_type)?.label || f.stratum_type}（开仓环段）` : '',
  ].filter(Boolean).join(' · ');
});
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
.filter-panel { margin-bottom: 14px; border-radius: 6px; }
.filter-panel :deep(.el-card__body) { padding: 14px 16px 10px; }
.filter-form { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; align-items: end; }
.filter-form :deep(.el-form-item) { margin: 0; min-width: 0; }
.filter-form :deep(.el-form-item__label) { margin-bottom: 5px; padding: 0; font-size: 12px; line-height: 18px; }
.filter-form :deep(.el-select) { width: 100%; }
.ring-inputs { display: flex; width: 100%; gap: 6px; align-items: center; color: var(--el-text-color-secondary); }
.ring-inputs :deep(.el-input) { min-width: 0; }
.filter-actions { display: flex; justify-content: flex-end; grid-column: 1 / -1; }
.applied-scope { margin-top: 13px; border-top: 1px solid var(--el-border-color-lighter); padding-top: 10px; font-size: 12px; color: var(--el-text-color-regular); line-height: 1.7; overflow-wrap: anywhere; }
.applied-scope > span { color: var(--el-text-color-secondary); margin-right: 12px; }
.filter-error { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; color: var(--el-color-danger); font-size: 12px; margin-top: 8px; }
@media (max-width: 760px) { .filter-form { grid-template-columns: repeat(2, minmax(0, 1fr)); row-gap: 16px; } }
@media (max-width: 400px) { .filter-panel :deep(.el-card__body) { padding: 12px; } .ring-filter { grid-column: 1 / -1; } }
</style>
