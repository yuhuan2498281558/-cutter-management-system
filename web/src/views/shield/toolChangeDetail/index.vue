<template>
  <fs-page>
    <p v-if="loading" role="status" class="detail-loading">正在加载开仓及换刀明细…</p>
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon class="detail-load-error">
      <div class="load-error-actions">
        <el-button @click="getWarehouseInfo" :disabled="loading">重新加载</el-button>
        <el-button @click="goBack">返回列表</el-button>
      </div>
    </el-alert>
    <!-- 开仓信息卡片 -->
    <el-card class="warehouse-info-card" shadow="never" v-if="warehouseInfo">
      <template #header>
        <div class="card-header">
          <div class="title-with-mode">
            <span class="card-title">开仓基本信息</span>
            <el-tag :type="isEditable ? 'warning' : 'info'" size="small">
              {{ isEditable ? '补录模式' : '只读查看' }}
            </el-tag>
          </div>
          <div class="header-actions">
            <el-button link type="primary" aria-controls="warehouse-information" :aria-expanded="!warehouseCollapsed" @click="warehouseCollapsed = !warehouseCollapsed">{{ warehouseCollapsed ? '展开开仓信息' : '收起开仓信息' }}</el-button>
            <el-button type="primary" size="small" @click="goBack">返回列表</el-button>
          </div>
        </div>
      </template>
      <div v-if="warehouseCollapsed" class="warehouse-summary">第 {{ warehouseInfo.ring_no }} 环 · {{ warehouseInfo.warehouse_id }}</div>
      <div id="warehouse-information" v-show="!warehouseCollapsed" class="warehouse-information">
        <dl class="warehouse-fields">
          <div><dt>换刀环号</dt><dd>{{ warehouseInfo.ring_no }}</dd></div>
          <div><dt>项目</dt><dd>{{ warehouseInfo.project_name || '-' }}</dd></div>
          <div><dt>开仓时间</dt><dd>{{ warehouseInfo.open_time }}</dd></div>
          <div><dt>区间</dt><dd>{{ warehouseInfo.section || '-' }}</dd></div>
          <div><dt>盾构机编号</dt><dd>{{ warehouseInfo.shield_model_name || '-' }}</dd></div>
          <div><dt>开仓编号</dt><dd>{{ warehouseInfo.warehouse_id }}</dd></div>
          <div><dt>换刀日期</dt><dd>{{ warehouseInfo.tool_change_date || '-' }}</dd></div>
          <div><dt>上次换刀环号</dt><dd>{{ warehouseInfo.last_ring_no || '-' }}</dd></div>
          <div><dt>期间掘进环数（环）</dt><dd>{{ warehouseInfo.rings_between_openings !== null && warehouseInfo.rings_between_openings !== undefined ? warehouseInfo.rings_between_openings : '-' }}</dd></div>
          <div><dt>开仓持续时间（小时）</dt><dd>{{ warehouseInfo.opening_duration ?? '-' }}</dd></div>
          <div><dt>换刀总时长（小时）</dt><dd>{{ warehouseInfo.tool_change_duration ?? '-' }}</dd></div>
          <div><dt>检查刀具数量（把）</dt><dd>{{ warehouseInfo.checked_tool_count ?? '-' }}</dd></div>
          <div><dt>更换刀具数量（把）</dt><dd>{{ warehouseInfo.replaced_tool_count ?? '-' }}</dd></div>
          <div><dt>本次使用距离（m）</dt><dd>{{ warehouseInfo.usage_distance ?? '-' }}</dd></div>
        </dl>
        <dl class="warehouse-geology">
          <div><dt>两次开仓间地层信息</dt><dd>{{ stratumInfoDisplay }}</dd></div>
          <div><dt>开仓位置地层信息</dt><dd>{{ warehouseInfo.geological_conditions || '-' }}</dd></div>
        </dl>
      </div>
    </el-card>

    <!-- 换刀明细表格 -->
    <el-card shadow="never" v-if="dataLoaded" class="tool-change-detail-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">换刀明细记录</span>
          <div class="header-actions">
            <span class="export-scope">导出全部刀位及完整字段，不受筛选影响</span>
            <ExportDropdown title="换刀明细记录" :filename="exportFilename" :rows="tableData" :columns="exportColumns" :meta="exportMeta" />
          </div>
        </div>
      </template>

      <el-alert v-if="isEditable" title="现场检查和新刀信息仅供查看。请通过“旧刀返修”补录厂家检测结果；现场记录有误时，先撤回开仓汇总，再由移动端更正。" type="info" :closable="false" show-icon class="supplement-notice" />

      <div class="detail-filters">
        <div class="filter-field detail-search">
          <label class="filter-label" for="tool-detail-search">刀位 / 刀具编号</label>
          <el-input id="tool-detail-search" v-model="searchText" placeholder="输入刀位或编号" aria-label="搜索刀位或刀具编号" clearable />
        </div>
        <div class="filter-field">
          <span class="filter-label">检查状态</span>
        <el-select v-model="checkFilter" aria-label="检查状态筛选">
          <el-option label="全部检查状态" value="ALL" />
          <el-option label="尚未检查" value="UNCHECKED" />
          <el-option label="已检查未换" value="CHECKED_ONLY" />
          <el-option label="已更换" value="REPLACED" />
        </el-select>
        </div>
        <div class="filter-field">
          <span class="filter-label">返修状态</span>
        <el-select v-model="repairFilter" aria-label="返修状态筛选">
          <el-option label="全部返修状态" value="ALL" />
          <el-option v-for="(label, value) in repairLabels" :key="value" :label="label" :value="value" />
        </el-select>
        </div>
        <el-button @click="resetFilters" :disabled="!hasActiveFilters">重置筛选</el-button>
      </div>
      <div v-if="hasActiveFilters" class="active-filters" aria-label="当前筛选条件">
        <span class="filter-label">当前条件</span>
        <el-button v-if="searchText.trim()" size="small" class="filter-chip" aria-label="清除刀位和编号搜索" @click="searchText = ''">搜索：{{ searchText.trim() }} <span aria-hidden="true">×</span></el-button>
        <el-button v-if="checkFilter !== 'ALL'" size="small" class="filter-chip" aria-label="清除检查状态条件" @click="checkFilter = 'ALL'">{{ checkFilterLabel }} <span aria-hidden="true">×</span></el-button>
        <el-button v-if="repairFilter !== 'ALL'" size="small" class="filter-chip" aria-label="清除返修状态条件" @click="repairFilter = 'ALL'">{{ repairLabels[repairFilter] }} <span aria-hidden="true">×</span></el-button>
      </div>
      <div class="table-scope">
        <span role="status" aria-live="polite">显示 <strong>{{ filteredTableData.length }}</strong> / 全部 {{ tableData.length }} 个刀位</span>
        <span class="detail-hint">点击刀位号或箭头查看详情</span>
      </div>

      <el-table
        ref="detailTableRef"
        :data="filteredTableData"
        class="detail-table"
        border
        stripe
        size="small"
        max-height="max(240px, calc(100dvh - 280px))"
        style="width: 100%"
        :row-key="(row: any) => row.cutter_position_no"
        table-layout="fixed"
        empty-text="没有符合筛选条件的刀位"
      >
        <template #empty>
          <el-empty class="detail-empty" :image-size="64" :description="tableData.length ? '没有符合筛选条件的刀位' : '暂无刀位数据'">
            <el-button v-if="tableData.length && hasActiveFilters" type="primary" plain @click="resetFilters">清除筛选，显示全部</el-button>
            <span v-else class="detail-hint">请核对该开仓关联的盾构机及刀位配置</span>
          </el-empty>
        </template>
        <el-table-column prop="cutter_position_no" label="刀位号" width="60" fixed="left">
          <template #default="{ row, expanded }">
            <button
              type="button"
              class="position-detail-button"
              :aria-label="`${expanded ? '收起' : '展开'}刀位 ${row.cutter_position_no} 的详情`"
              :aria-expanded="expanded"
              :aria-controls="`tool-detail-${warehouseId}-${row.cutter_position_no}`"
              @click.stop="detailTableRef?.toggleRowExpansion(row)"
            >{{ row.cutter_position_no }}</button>
          </template>
        </el-table-column>
        <el-table-column type="expand" width="36">
          <template #default="{ row }">
            <div :id="`tool-detail-${warehouseId}-${row.cutter_position_no}`" class="expanded-detail">
              <div class="detail-groups">
                <section class="detail-group" aria-label="新刀信息">
                  <h3>新刀信息</h3>
                  <div class="new-tool-summary">{{ newToolSummary(row) }}</div>
                </section>
                <section class="detail-group" aria-label="磨损与更换">
                  <h3>磨损与更换</h3>
                  <dl class="detail-fields">
                    <div><dt>刀刃磨损量</dt><dd>{{ row.blade_wear_amount ?? '-' }}</dd></div>
                    <div><dt>刀位轨迹</dt><dd><el-tooltip :content="row.trajectory?.source || '图纸依据'" placement="top"><span>{{ row.trajectory?.display || '待按最终图纸核对' }}</span></el-tooltip></dd></div>
                    <div><dt>累计更换次数</dt><dd>{{ row.replacement_count }}</dd></div>
                    <div><dt>更换类型</dt><dd>{{ row.replacement_type === 'COMPLETE' ? '整刀更换' : row.replacement_type === 'REPAIR' ? '维修' : '-' }}</dd></div>
                    <div><dt>维修部位</dt><dd>{{ Array.isArray(row.repair_parts) && row.repair_parts.length ? row.repair_parts.join('、') : '-' }}</dd></div>
                  </dl>
                </section>
                <section class="detail-group" aria-label="采购信息">
                  <h3>采购信息</h3>
                  <dl class="detail-fields">
                    <div><dt>厂家</dt><dd>{{ row.manufacturer || '-' }}</dd></div>
                    <div><dt>品牌</dt><dd>{{ row.brand || '-' }}</dd></div>
                    <div><dt>价格</dt><dd>{{ row.price ?? '-' }}</dd></div>
                  </dl>
                </section>
              </div>
              <dl class="detail-attachments">
                <div class="attachment-field">
                  <dt>刀具磨损更换图</dt>
                  <dd>
                    <el-image v-if="row.wear_image" :src="row.wear_image" :preview-src-list="[row.wear_image]" preview-teleported class="wear-thumbnail" fit="cover" />
                    <span v-else>-</span>
                  </dd>
                </div>
                <div class="attachment-field">
                  <dt>旧刀照片</dt>
                  <dd>
                    <div v-if="row.old_photo_links?.length" class="photo-link-list">
                      <button v-for="(photo, index) in row.old_photo_links" :key="photo.id" type="button" class="photo-preview-button" aria-haspopup="dialog" @click="previewPhoto(photo.url, photo.name || `照片${index + 1}`)">{{ photo.name || `照片${index + 1}` }}</button>
                    </div>
                    <span v-else>-</span>
                  </dd>
                </div>
                <div class="attachment-field detail-remark"><dt>备注</dt><dd>{{ row.remark || '-' }}</dd></div>
              </dl>
            </div>
          </template>
        </el-table-column>
        <el-table-column type="index" label="序号" width="48" align="center" />
        <el-table-column label="刀具类型" min-width="240">
          <template #default="{ row }">
            <div class="tool-type-cell">
              <span>{{ row.tool_type_name }}</span>
              <span class="secondary-text">{{ row.tool_parent_type_display }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="刀具编号" min-width="140">
          <template #default="{ row }"><span class="tool-number">{{ row.tool_number || '-' }}</span></template>
        </el-table-column>
        <el-table-column label="检查状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="!row.is_checked ? 'info' : row.is_replaced ? 'danger' : 'success'" size="small">{{ checkStatus(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="wear_condition" label="磨损情况" width="88">
          <template #default="{ row }">{{ row.wear_condition || '-' }}</template>
        </el-table-column>
        <el-table-column label="刀刃磨损量" width="96" align="right">
          <template #default="{ row }">{{ row.blade_wear_amount ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="累计更换次数" width="104" align="right">
          <template #default="{ row }">{{ row.replacement_count }}</template>
        </el-table-column>
        <el-table-column label="采购厂家" min-width="120">
          <template #default="{ row }"><span class="table-text">{{ row.manufacturer || '-' }}</span></template>
        </el-table-column>
        <el-table-column label="返修状态" width="132">
          <template #default="{ row }">
            <el-tag :type="repairStatus(row) === 'CLOSED' ? 'success' : ['UNRECORDED', 'PENDING_VENDOR_FEEDBACK'].includes(repairStatus(row)) ? 'warning' : 'info'" size="small">{{ repairLabels[repairStatus(row)] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="旧刀返修" width="92" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.is_replaced && (isEditable || row.old_tool_record_data)"
              type="primary"
              link
              @click.stop="openOldToolRepair(row)"
            >
              {{ isEditable && row.old_tool_record_data?.inspection_status !== 'CLOSED' ? (row.old_tool_record_data ? '查看 / 补录' : '补录') : '查看' }}
            </el-button>
            <span v-else>-</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <OldToolRepairDialog v-if="pageActive" ref="repairDialogRef" @saved="getWarehouseInfo" />
    <el-dialog v-model="photoPreviewVisible" title="旧刀磨损照片" width="min(760px, calc(100vw - 32px))" top="5vh" class="detail-photo-dialog" :close-on-press-escape="true" destroy-on-close>
      <PhotoPreview :src="photoPreviewUrl" :name="photoPreviewName" :active="photoPreviewVisible" />
    </el-dialog>
  </fs-page>
</template>

<script lang="ts" setup name="ToolChangeDetail">
import { ref, onMounted, onActivated, onDeactivated, onUnmounted, computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { request } from '/@/utils/service';
import { ElMessage, type TableInstance } from 'element-plus';
import ExportDropdown from '/@/views/shield/components/ExportDropdown.vue';
import type { ExportColumn, ExportMetaItem } from '/@/views/shield/utils/export';
import OldToolRepairDialog from './OldToolRepairDialog.vue';
import PhotoPreview from './PhotoPreview.vue';
import { matchesDetailFilters, repairLabels, repairStatus, type CheckFilter, type RepairFilter } from './tablePresentation';

const route = useRoute();
const router = useRouter();

const warehouseId = ref<number>();
const warehouseInfo = ref<any>(null);
const dataLoaded = ref(false);
const loading = ref(false);
const loadError = ref('');
const pageActive = ref(true);
let loadGeneration = 0;
let detailGeneration = 0;
const tableData = ref<any[]>([]);
const detailTableRef = ref<TableInstance>();
const warehouseCollapsed = ref(false);
const searchText = ref('');
const checkFilter = ref<CheckFilter>('ALL');
const repairFilter = ref<RepairFilter>('ALL');
const hasActiveFilters = computed(() => Boolean(searchText.value.trim()) || checkFilter.value !== 'ALL' || repairFilter.value !== 'ALL');
const checkFilterLabel = computed(() => ({ UNCHECKED: '尚未检查', CHECKED_ONLY: '已检查未换', REPLACED: '已更换', ALL: '全部检查状态' })[checkFilter.value]);
const filteredTableData = computed(() => tableData.value.filter(row => matchesDetailFilters(row, checkFilter.value, repairFilter.value, searchText.value)));
const resetFilters = () => {
  searchText.value = '';
  checkFilter.value = 'ALL';
  repairFilter.value = 'ALL';
};
const repairDialogRef = ref();
const photoPreviewVisible = ref(false);
const photoPreviewUrl = ref('');
const photoPreviewName = ref('旧刀照片');
const isEditable = computed(() => pageActive.value && !loading.value && !loadError.value && route.query.mode === 'supplement' && warehouseInfo.value?.supplement_ready === true);

// 刀具父类型映射
const toolParentTypeMap: any = {
  'DISC': '滚刀',
  'RIPPER': '撕裂刀',
  'SCRAPER': '刮刀',
};

const checkStatus = (row: any) => {
  if (!row?.is_checked) return '尚未检查';
  return row.is_replaced ? '已换刀' : '已检查未换';
};

const newToolSummary = (row: any) => {
  const record = row?.new_tool_record_data;
  if (!record) return '-';
  if (row.tool_parent_type === 'SCRAPER') {
    return record.scraper_manufacturer ? `厂家：${record.scraper_manufacturer}` : '-';
  }
  return [
    record.ring_type_display || record.ring_type ? `刀圈：${record.ring_type_display || record.ring_type} / ${record.ring_manufacturer || '-'}` : '',
    record.shaft_condition_display || record.shaft_condition ? `刀轴：${record.shaft_condition_display || record.shaft_condition} / ${record.shaft_manufacturer || '-'}` : '',
    record.hub_condition_display || record.hub_condition ? `刀毂：${record.hub_condition_display || record.hub_condition} / ${record.hub_manufacturer || '-'}` : '',
  ].filter(Boolean).join('\n') || '-';
};

const exportColumns: ExportColumn[] = [
  { key: 'tool_parent_type_display', title: '刀具父类型', printWidth: 14 },
  { key: 'tool_type_name', title: '刀具类型名称', printWidth: 36 },
  { key: 'cutter_position_no', title: '刀位号', printWidth: 12 },
  { key: 'is_checked', title: '检查状态', printWidth: 18, formatter: (row) => checkStatus(row) },
  { key: 'tool_number', title: '刀具编号', printWidth: 23 },
  { key: 'wear_condition', title: '磨损情况', printWidth: 15 },
  { key: 'blade_wear_amount', title: '刀刃磨损量', printWidth: 16 },
  { key: 'trajectory', title: '刀位轨迹', printWidth: 18, formatter: (row) => row.trajectory?.display || '待按最终图纸核对' },
  { key: 'is_replaced', title: '是否更换', printWidth: 12, formatter: (row) => row.is_replaced ? '是' : '否' },
  { key: 'replacement_count', title: '累计更换次数', printWidth: 17 },
  { key: 'manufacturer', title: '厂家', printWidth: 26 },
  { key: 'new_tool_record_data', title: '新刀信息', printWidth: 48, formatter: (row) => newToolSummary(row) },
  { key: 'replacement_type', title: '更换类型', printWidth: 17, formatter: (row) => row.replacement_type === 'COMPLETE' ? '整刀更换' : row.replacement_type === 'REPAIR' ? '维修' : '' },
  { key: 'repair_parts', title: '维修部位', printWidth: 18 },
  { key: 'brand', title: '品牌', printWidth: 18 },
  { key: 'price', title: '价格', printWidth: 14 },
  { key: 'old_photo_links', title: '旧刀照片链接', printWidth: 32, formatter: (row) => (row.old_photo_links || []).map((item: any) => `${item.name || '照片'}：${item.url}`).join('\n') },
  { key: 'remark', title: '备注', printWidth: 32 },
];

const formatEmpty = (value: any) => value !== null && value !== undefined && value !== '' ? value : '-';

const exportFilename = computed(() => {
  const ringNo = warehouseInfo.value?.ring_no;
  return ringNo ? `换刀明细记录-第${ringNo}环` : '换刀明细记录';
});

const exportMeta = computed<ExportMetaItem[]>(() => {
  const info = warehouseInfo.value || {};
  return [
    { label: '换刀环号', value: formatEmpty(info.ring_no) },
    { label: '项目', value: formatEmpty(info.project_name) },
    { label: '开仓时间', value: formatEmpty(info.open_time) },
    { label: '区间', value: formatEmpty(info.section) },
    { label: '盾构机编号', value: formatEmpty(info.shield_model_name) },
    { label: '开仓编号', value: formatEmpty(info.warehouse_id) },
    { label: '换刀日期', value: formatEmpty(info.tool_change_date) },
    { label: '上次换刀环号', value: formatEmpty(info.last_ring_no) },
    { label: '期间掘进环数（环）', value: formatEmpty(info.rings_between_openings) },
    { label: '开仓持续时间（小时）', value: formatEmpty(info.opening_duration) },
    { label: '换刀总时长（小时）', value: formatEmpty(info.tool_change_duration) },
    { label: '检查刀具数量（把）', value: formatEmpty(info.checked_tool_count) },
    { label: '更换刀具数量（把）', value: formatEmpty(info.replaced_tool_count) },
    { label: '本次使用距离（m）', value: formatEmpty(info.usage_distance) },
    { label: '两次开仓间地层信息', value: stratumInfoDisplay.value, span: 3 },
    { label: '开仓位置地层信息', value: formatEmpty(info.geological_conditions), span: 3 },
  ];
});

// 计算属性：格式化地层信息
const stratumInfoDisplay = computed(() => {
  const list = warehouseInfo.value?.stratum_info_between_list;
  if (!list || !Array.isArray(list) || list.length === 0) {
    return '-';
  }

  try {
    // 检查是否是对象数组格式
    if (typeof list[0] === 'object' && list[0] !== null) {
      return list.map((item: any) => {
        const name = item.stratum_type_name || item.name || '未知地层';
        const count = item.ring_count || item.count || 0;
        return `${name}(${count}环)`;
      }).join('、');
    }
    // 如果是其他格式，直接返回
    return String(list);
  } catch (error) {
    console.error('格式化地层信息失败:', error);
    return '-';
  }
});

// 自然排序
const naturalSort = (a: string, b: string) => {
  const regex = /(\d+)|(\D+)/g;
  const aParts = a.match(regex) || [];
  const bParts = b.match(regex) || [];

  for (let i = 0; i < Math.max(aParts.length, bParts.length); i++) {
    const aPart = aParts[i] || '';
    const bPart = bParts[i] || '';
    const aNum = parseInt(aPart);
    const bNum = parseInt(bPart);

    if (!isNaN(aNum) && !isNaN(bNum)) {
      if (aNum !== bNum) return aNum - bNum;
    } else {
      if (aPart !== bPart) return aPart.localeCompare(bPart);
    }
  }
  return 0;
};

// 获取开仓信息
const getWarehouseInfo = async () => {
  if (!pageActive.value) return;
  const generation = ++loadGeneration;
  detailGeneration++;
  const id = route.query.warehouse_id;
  const path = route.path;
  const isCurrent = () => pageActive.value && generation === loadGeneration && route.query.warehouse_id === id && route.path === path;
  warehouseInfo.value = null;
  warehouseId.value = undefined;
  tableData.value = [];
  dataLoaded.value = false;
  loadError.value = '';
  loading.value = true;
  try {
    if (!id) {
      ElMessage.error('缺少开仓ID参数');
      router.back();
      return;
    }

    warehouseId.value = Number(id);

    const res = await request({
      url: `/api/shield/warehouse_opening/${id}/`,
      method: 'get',
    });
    if (!isCurrent()) return;
    warehouseInfo.value = res.data;

    if (route.query.mode === 'supplement' && !warehouseInfo.value?.supplement_ready) {
      ElMessage.warning('请先在开仓列表补全开仓持续时间、换刀总时长和刀具数量');
      await router.replace({
        path: route.path,
        query: { ...route.query, mode: 'view' },
      });
    }
    if (!isCurrent()) return;
    await loadData(generation);
  } catch (error: any) {
    if (isCurrent()) loadError.value = '开仓信息加载失败，请检查网络后重新加载。';
  } finally {
    if (isCurrent()) loading.value = false;
  }
};

// 加载数据
const loadData = async (generation = loadGeneration) => {
  if (!pageActive.value || !warehouseInfo.value || !warehouseId.value) return;
  const detailRequest = ++detailGeneration;
  const queryId = route.query.warehouse_id;
  const path = route.path;
  const isCurrent = () => pageActive.value && generation === loadGeneration && detailRequest === detailGeneration && route.query.warehouse_id === queryId && route.path === path;
  const openingId = warehouseId.value;
  const shieldId = warehouseInfo.value.shield_model;
  loading.value = true;
  loadError.value = '';
  dataLoaded.value = false;
  tableData.value = [];
  try {
    // 获取刀位信息
    const cutterRes = await request({
      url: '/api/shield/cutter_position_info/',
      method: 'get',
      params: {
        shield_machine: shieldId,
        limit: 1000,
      },
    });
    if (!isCurrent()) return;
    const cutterPositions = cutterRes.data || cutterRes.results || [];

    // 获取已有的换刀明细
    const detailRes = await request({
      url: '/api/shield/tool_change_detail/',
      method: 'get',
      params: {
        warehouse: openingId,
        limit: 1000,
      },
    });
    if (!isCurrent()) return;
    const existingDetails = detailRes.data || detailRes.results || [];
    const detailMap = new Map();
    existingDetails.forEach((d: any) => {
      detailMap.set(d.cutter_position_no, d);
    });

    // 构建表格数据
    tableData.value = cutterPositions.map((pos: any) => {
      const existingDetail = detailMap.get(pos.cutter_position_no);

      // 获取刀具类型名称（后端序列化器已经将 tool_info.tool_type_name 提升到顶层）
      const toolTypeName = pos.tool_type_name || '-';

      // 转换价格为数字类型
      let price = existingDetail?.price;
      if (price !== null && price !== undefined) {
        price = typeof price === 'string' ? parseFloat(price) : price;
      }

      // 只展示后端保存的编号，缺失时保留空值。
      const toolNumber = existingDetail?.tool_number || '';

      return {
        id: existingDetail?.id,
        cutter_position_id: pos.id,
        cutter_position_no: pos.cutter_position_no,
        tool_parent_type: pos.tool_type,
        tool_parent_type_display: toolParentTypeMap[pos.tool_type] || pos.tool_type,
        tool_type_name: toolTypeName,
        tool_number: toolNumber,
        is_checked: existingDetail?.is_checked || false,
        check_result: existingDetail?.check_result || 'PENDING',
        wear_condition: existingDetail?.wear_condition || '',
        blade_wear_amount: existingDetail?.blade_wear_amount ?? null,
        trajectory: existingDetail?.trajectory || null,
        is_replaced: existingDetail?.is_replaced || false,
        replacement_count: existingDetail?.replacement_count || 0,
        manufacturer: existingDetail?.manufacturer || '',
        new_tool_record_data: existingDetail?.new_tool_record_data || null,
        replacement_type: existingDetail?.replacement_type,
        repair_parts: existingDetail?.repair_parts || [],
        brand: existingDetail?.brand || '',
        price: price,
        wear_image: existingDetail?.wear_image_url || existingDetail?.wear_image || '',
        old_tool_record_data: existingDetail?.old_tool_record_data || null,
        old_photo_links: existingDetail?.old_photo_links || [],
        remark: existingDetail?.remark || '',
      };
    }).sort((a, b) => naturalSort(a.cutter_position_no, b.cutter_position_no));

    dataLoaded.value = true;
    ElMessage.success(`已加载 ${tableData.value.length} 条刀位数据`);
  } catch (error: any) {
    if (isCurrent()) loadError.value = '换刀明细加载失败，未展示旧数据，请重新加载后再查看或补录。';
  } finally {
    if (isCurrent()) loading.value = false;
  }
};

const openOldToolRepair = (row: any) => {
  if (!pageActive.value || loading.value || loadError.value) return;
  if (!row?.id) {
    ElMessage.warning('该刀位尚无现场记录，请先通过移动端录入');
    return;
  }
  if (!row.is_replaced) {
    ElMessage.warning('未更换刀具不能录入旧刀返修');
    return;
  }
  repairDialogRef.value?.open(row, { readOnly: !isEditable.value || row.old_tool_record_data?.inspection_status === 'CLOSED' });
};

const previewPhoto = (url: string, name = '旧刀照片') => {
  if (!url) return;
  photoPreviewUrl.value = url;
  photoPreviewName.value = name;
  photoPreviewVisible.value = true;
};

// 返回列表
const goBack = () => {
  router.back();
};

onMounted(() => {
  getWarehouseInfo();
});
onActivated(() => {
  if (!pageActive.value) {
    pageActive.value = true;
    getWarehouseInfo();
  }
});
const invalidateLoads = () => {
  pageActive.value = false;
  loadGeneration++;
  detailGeneration++;
  loading.value = false;
  dataLoaded.value = false;
  tableData.value = [];
  warehouseInfo.value = null;
  photoPreviewVisible.value = false;
};
onDeactivated(invalidateLoads);
onUnmounted(invalidateLoads);
</script>

<style>
.detail-photo-dialog { display: flex; flex-direction: column; max-height: 90dvh; margin-bottom: 0; }
.detail-photo-dialog .el-dialog__body { min-height: 0; overflow: auto; }
</style>

<style scoped>
.detail-loading { margin: 0 0 16px; padding: 12px 16px; border: 1px solid var(--el-border-color-lighter); border-radius: 4px; background: var(--el-fill-color-light); color: var(--el-text-color-regular); font-size: 14px; line-height: 22px; }
.detail-load-error { margin-bottom: 16px; }
.detail-load-error :deep(.el-alert__content) { min-width: 0; }
.detail-load-error :deep(.el-alert__title) { font-size: 14px; line-height: 22px; overflow-wrap: anywhere; }
.load-error-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.load-error-actions .el-button + .el-button { margin-left: 0; }

.warehouse-info-card {
  margin-bottom: 16px;
}

.warehouse-info-card :deep(.el-card__header) {
  padding: 12px 16px;
}

.warehouse-info-card :deep(.el-card__body) {
  padding: 16px;
}

.warehouse-information {
  border: 1px solid var(--el-border-color-lighter);
  border-bottom: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}

.warehouse-fields, .warehouse-geology {
  margin: 0;
}

.warehouse-fields {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.warehouse-fields > div, .warehouse-geology > div {
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr);
  min-width: 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.warehouse-fields > div:last-child {
  grid-column: span 2;
}

.warehouse-information dt, .warehouse-information dd {
  margin: 0;
  padding: 6px 10px;
  min-width: 0;
  overflow-wrap: anywhere;
}

.warehouse-information dt {
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
}

.warehouse-information dd {
  font-variant-numeric: tabular-nums;
}

.warehouse-geology dd {
  white-space: pre-wrap;
}

@media (max-width: 1100px) {
  .warehouse-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .warehouse-fields > div:last-child { grid-column: auto; }
}

@media (max-width: 640px) {
  .warehouse-info-card :deep(.el-card__header), .warehouse-info-card :deep(.el-card__body) { padding: 12px; }
  .warehouse-fields { grid-template-columns: minmax(0, 1fr); }
  .warehouse-fields > div, .warehouse-geology > div { grid-template-columns: 132px minmax(0, 1fr); }
  .warehouse-information dt, .warehouse-information dd { padding: 8px; }
  .warehouse-info-card .header-actions { width: 100%; justify-content: space-between; }
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.detail-filters { display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: center; }
.filter-field { display: flex; align-items: center; gap: 8px; min-width: 0; }
.filter-label { flex-shrink: 0; font-size: 13px; color: var(--el-text-color-regular); }
.active-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 10px; }
.active-filters .filter-chip { margin-left: 0; max-width: 100%; height: auto; min-height: 24px; }
.filter-chip :deep(span) { white-space: normal; overflow-wrap: anywhere; }
.detail-search { width: 332px; }
.detail-search :deep(.el-input) { flex: 1; min-width: 0; }
.detail-filters :deep(.el-select) { width: 160px; }
.detail-filters :deep(.el-input__wrapper:has(input:focus-visible)),
.detail-filters :deep(.el-select__wrapper:has(input:focus-visible)) { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
@media (max-width: 640px) {
  .detail-filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 12px; align-items: end; }
  .filter-field { flex-direction: column; align-items: stretch; gap: 4px; }
  .detail-search { grid-column: 1 / -1; }
  .detail-filters .filter-field, .detail-filters :deep(.el-select) { width: 100%; }
  .detail-filters > .el-button { justify-self: start; margin-left: 0; }
}
.table-scope { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 10px 0; font-size: 13px; color: var(--el-text-color-regular); }
.table-scope strong { font-weight: 600; color: var(--el-text-color-primary); }
.detail-hint, .export-scope { font-size: 12px; color: var(--el-text-color-regular); }
.tool-number { overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.detail-table { font-size: 13px; container: tool-detail-table / inline-size; }
.detail-table :deep(.cell) { padding: 0 8px; line-height: 20px; }
.detail-table :deep(.el-table__cell) { padding-top: 6px; padding-bottom: 6px; }
.detail-table :deep(.el-table__expanded-cell) { padding: 0; }
.position-detail-button { display: block; min-width: 24px; max-width: 100%; padding: 0 4px; border: 0; border-radius: 2px; background: transparent; color: color-mix(in srgb, var(--el-color-primary) 60%, var(--el-text-color-primary)); font: inherit; line-height: 20px; text-align: left; white-space: nowrap; font-variant-numeric: tabular-nums; cursor: pointer; }
.detail-table :deep(.el-tag--info) { --el-tag-text-color: var(--el-text-color-regular); }
.detail-table :deep(.el-tag--success) { --el-tag-text-color: color-mix(in srgb, var(--el-color-success) 50%, var(--el-text-color-primary)); }
.detail-table :deep(.el-tag--warning) { --el-tag-text-color: color-mix(in srgb, var(--el-color-warning) 50%, var(--el-text-color-primary)); }
.detail-table :deep(.el-tag--danger) { --el-tag-text-color: color-mix(in srgb, var(--el-color-danger) 50%, var(--el-text-color-primary)); }
.detail-table :deep(.el-table__empty-text) { width: 100%; line-height: 1.6; }
.detail-empty { padding: 24px 12px; }
.detail-empty :deep(.el-empty__description) { margin-top: 12px; }
.detail-empty :deep(.el-empty__description p) { color: var(--el-text-color-regular); line-height: 22px; }
.detail-empty :deep(.el-empty__bottom) { margin-top: 14px; }
.tool-type-cell { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0 8px; }
.tool-type-cell > span, .table-text { overflow-wrap: anywhere; }
.tool-type-cell .secondary-text { white-space: nowrap; }
.expanded-detail { position: sticky; left: 0; width: 100cqw; max-width: 100%; box-sizing: border-box; padding: 16px 20px; background: var(--el-fill-color-lighter); }
.detail-groups { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) minmax(0, 1fr); gap: 24px; }
.detail-group { min-width: 0; }
.detail-group + .detail-group { border-left: 1px solid var(--el-border-color-lighter); padding-left: 24px; }
.detail-group h3 { margin: 0 0 8px; font-size: 13px; font-weight: 600; color: var(--el-text-color-primary); }
.detail-fields, .detail-attachments { margin: 0; font-size: 13px; line-height: 1.65; }
.detail-fields > div { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 12px; margin-top: 6px; }
.expanded-detail dt { color: var(--el-text-color-secondary); font-weight: 400; }
.expanded-detail dd { margin: 0; min-width: 0; overflow-wrap: anywhere; color: var(--el-text-color-regular); }
.detail-attachments { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr); gap: 12px 24px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--el-border-color-lighter); }
.attachment-field { display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 12px; align-items: start; }
.detail-remark { grid-column: 1 / -1; }
.detail-remark dd { white-space: pre-wrap; }
.wear-thumbnail { width: 56px; height: 56px; border-radius: 4px; }
.photo-preview-button { max-width: 100%; min-height: 24px; padding: 1px 0; border: 0; border-radius: 2px; background: transparent; color: color-mix(in srgb, var(--el-color-primary) 60%, var(--el-text-color-primary)); font: inherit; line-height: 1.5; text-align: left; white-space: normal; overflow-wrap: anywhere; cursor: pointer; }
.photo-preview-button:hover, .position-detail-button:hover { text-decoration: underline; text-underline-offset: 3px; }
.photo-preview-button:focus-visible, .position-detail-button:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.position-detail-button:focus-visible { outline-offset: -2px; }
@media (max-width: 1200px) {
  .expanded-detail { padding: 16px; }
  .detail-groups { gap: 16px; }
  .detail-group + .detail-group { padding-left: 16px; }
  .detail-fields > div { grid-template-columns: 84px minmax(0, 1fr); gap: 8px; }
}
@container tool-detail-table (max-width: 760px) {
  .expanded-detail { padding: 12px; }
  .detail-groups { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .detail-group + .detail-group { border-left: 0; padding-left: 0; border-top: 1px solid var(--el-border-color-lighter); padding-top: 12px; }
  .detail-attachments { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .attachment-field { grid-template-columns: 96px minmax(0, 1fr); gap: 8px; }
}
.secondary-text { font-size: 12px; color: #606266; }
.warehouse-summary { font-size: 14px; color: var(--el-text-color-regular); overflow-wrap: anywhere; }

.title-with-mode {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.card-title {
  font-size: 16px;
  font-weight: bold;
}

.supplement-notice {
  margin-bottom: 12px;
}

.tool-change-detail-card {
  margin-bottom: 20px;
}

.tool-change-detail-card :deep(.el-card__header) { padding: 12px 16px; }
.tool-change-detail-card :deep(.el-card__body) { padding: 16px; }
@media (max-width: 640px) {
  .tool-change-detail-card :deep(.el-card__header), .tool-change-detail-card :deep(.el-card__body) { padding: 12px; }
}

.photo-link-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.trajectory-value {
  color: #a65c16;
  font-weight: 650;
}

.trajectory-pending {
  color: #909399;
}

.new-tool-summary {
  white-space: pre-line;
  overflow-wrap: anywhere;
  font-size: 13px;
  line-height: 1.6;
}

</style>
