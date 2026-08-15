<template>
  <el-card class="filter-panel" shadow="never">
    <el-form :model="form" inline>
      <el-form-item label="项目">
        <el-select
          v-model="form.project"
          clearable
          placeholder="全部项目"
          style="width: 160px"
          @change="onProjectChange"
        >
          <el-option
            v-for="p in projectList"
            :key="p.id"
            :label="p.project_name"
            :value="p.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="盾构机">
        <el-select
          v-model="form.shield_machine"
          clearable
          placeholder="全部盾构机"
          style="width: 160px"
          @change="onMainFilterChange"
        >
          <el-option
            v-for="m in machineList"
            :key="m.id"
            :label="m.shield_model"
            :value="m.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="刀具类型">
        <el-select
          v-model="form.tool_parent_type"
          clearable
          placeholder="全部类型"
          style="width: 130px"
          @change="onMainFilterChange"
        >
          <el-option
            v-for="item in toolTypeOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="刀具细分类型">
        <el-select
          v-model="form.tool_type_name"
          clearable
          filterable
          placeholder="如中心滚刀"
          style="width: 180px"
          @change="onToolTypeNameChange"
        >
          <el-option
            v-for="item in toolTypeNameOptions"
            :key="item.value"
            :label="item.parent_label ? `${item.label}（${item.parent_label}）` : item.label"
            :value="item.value"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="厂家">
        <el-select
          v-model="form.manufacturer"
          clearable
          filterable
          placeholder="全部厂家"
          style="width: 180px"
          @change="emitChange"
        >
          <el-option
            v-for="m in manufacturerList"
            :key="m"
            :label="m"
            :value="m"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="环号范围">
        <el-input
          v-model="form.start_ring"
          placeholder="起始环号"
          style="width: 90px"
          @change="onRangeChange"
        />
        <span style="margin: 0 4px; color: #999">-</span>
        <el-input
          v-model="form.end_ring"
          placeholder="结束环号"
          style="width: 90px"
          @change="onRangeChange"
        />
      </el-form-item>

      <el-form-item>
        <el-button @click="onReset">重置</el-button>
        <el-button type="primary" @click="emitChange">查询</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue';
import { request } from '/@/utils/service';
import { getFilterOptions } from '../api';
import type { AnalysisFilter } from '../types';

const emit = defineEmits(['filter-change']);

const form = reactive<AnalysisFilter>({
  project: undefined,
  shield_machine: undefined,
  start_ring: '',
  end_ring: '',
  tool_parent_type: '',
  tool_type_name: '',
  manufacturer: '',
});

const defaultToolTypeOptions = [
  { label: '滚刀', value: 'DISC' },
  { label: '撕裂刀', value: 'RIPPER' },
  { label: '刮刀', value: 'SCRAPER' },
];

// ─── 项目列表 ───────────────────────────────────────────────
const projectList = ref<any[]>([]);
async function fetchProjects() {
  const res = await request({ url: '/api/shield/project/', method: 'get', params: { limit: 999 } });
  projectList.value = res?.data?.results ?? res?.data ?? [];
}
fetchProjects();

// ─── 盾构机列表（全量加载，不依赖项目） ───────────────────────
const machineList = ref<any[]>([]);
async function fetchMachines() {
  const res = await request({
    url: '/api/shield/shield_machine_basic_info/',
    method: 'get',
    params: { limit: 999 },
  });
  machineList.value = res?.data?.results ?? res?.data ?? [];
}
fetchMachines();

const toolTypeOptions = ref(defaultToolTypeOptions);
const toolTypeNameOptions = ref<ToolTypeNameOption[]>([]);
const manufacturerList = ref<string[]>([]);

interface ToolTypeNameOption {
  value: string;
  label: string;
  parent_type?: string;
  parent_label?: string;
}

function buildOptionFilter(includeToolTypeName = false): AnalysisFilter {
  const filter: AnalysisFilter = {};
  if (form.project) filter.project = form.project;
  if (form.shield_machine) filter.shield_machine = form.shield_machine;
  if (form.start_ring) filter.start_ring = form.start_ring;
  if (form.end_ring) filter.end_ring = form.end_ring;
  if (form.tool_parent_type) filter.tool_parent_type = form.tool_parent_type;
  if (includeToolTypeName && form.tool_type_name) filter.tool_type_name = form.tool_type_name;
  return filter;
}

async function fetchAnalysisOptions() {
  const res = await getFilterOptions(buildOptionFilter());
  const data = res?.data ?? res;
  toolTypeOptions.value = data?.tool_types?.length ? data.tool_types : defaultToolTypeOptions;
  toolTypeNameOptions.value = data?.tool_type_names ?? [];
  if (
    form.tool_type_name &&
    !toolTypeNameOptions.value.some(item => item.value === form.tool_type_name)
  ) {
    form.tool_type_name = '';
  }

  if (!form.tool_type_name) {
    manufacturerList.value = data?.manufacturers ?? [];
    return;
  }

  const manufacturerRes = await getFilterOptions(buildOptionFilter(true));
  const manufacturerData = manufacturerRes?.data ?? manufacturerRes;
  manufacturerList.value = manufacturerData?.manufacturers ?? [];
}
fetchAnalysisOptions();

function onProjectChange() {
  form.shield_machine = undefined;
  form.tool_type_name = '';
  form.manufacturer = '';
  fetchAnalysisOptions();
  emitChange();
}

function onMainFilterChange() {
  form.tool_type_name = '';
  form.manufacturer = '';
  fetchAnalysisOptions();
  emitChange();
}

function onToolTypeNameChange() {
  form.manufacturer = '';
  fetchAnalysisOptions();
  emitChange();
}

function onRangeChange() {
  fetchAnalysisOptions();
  emitChange();
}

// ─── 发射筛选事件 ───────────────────────────────────────────
function emitChange() {
  const filter: AnalysisFilter = {};
  if (form.project) filter.project = form.project;
  if (form.shield_machine) filter.shield_machine = form.shield_machine;
  if (form.start_ring) filter.start_ring = form.start_ring;
  if (form.end_ring) filter.end_ring = form.end_ring;
  if (form.tool_parent_type) filter.tool_parent_type = form.tool_parent_type;
  if (form.tool_type_name) filter.tool_type_name = form.tool_type_name;
  if (form.manufacturer) filter.manufacturer = form.manufacturer;
  emit('filter-change', filter);
}

function onReset() {
  form.project = undefined;
  form.shield_machine = undefined;
  form.start_ring = '';
  form.end_ring = '';
  form.tool_parent_type = '';
  form.tool_type_name = '';
  form.manufacturer = '';
  fetchAnalysisOptions();
  emit('filter-change', {});
}
</script>

<style scoped>
.filter-panel {
  margin-bottom: 16px;
  border-radius: 8px;
}
.filter-panel :deep(.el-card__body) {
  padding: 12px 16px;
}
</style>
