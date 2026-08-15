<template>
  <fs-page>
    <!-- 开仓信息卡片 -->
    <el-card class="warehouse-info-card" shadow="never" style="margin-bottom: 20px;" v-if="warehouseInfo">
      <template #header>
        <div class="card-header">
          <span class="card-title">开仓基本信息</span>
          <el-button type="primary" size="small" @click="goBack">返回列表</el-button>
        </div>
      </template>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="换刀环号">{{ warehouseInfo.ring_no }}</el-descriptions-item>
        <el-descriptions-item label="项目">{{ warehouseInfo.project_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="开仓时间">{{ warehouseInfo.open_time }}</el-descriptions-item>
        <el-descriptions-item label="区间">{{ warehouseInfo.section || '-' }}</el-descriptions-item>
        <el-descriptions-item label="盾构机编号">{{ warehouseInfo.shield_model_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="开仓编号">{{ warehouseInfo.warehouse_id }}</el-descriptions-item>
        <el-descriptions-item label="换刀日期">{{ warehouseInfo.tool_change_date || '-' }}</el-descriptions-item>
        <el-descriptions-item label="上次换刀环号">{{ warehouseInfo.last_ring_no || '-' }}</el-descriptions-item>
        <el-descriptions-item label="期间掘进环数（环）">{{ warehouseInfo.rings_between_openings !== null && warehouseInfo.rings_between_openings !== undefined ? warehouseInfo.rings_between_openings : '-' }}</el-descriptions-item>
        <el-descriptions-item label="换刀总时长（小时）">{{ warehouseInfo.tool_change_duration ?? warehouseInfo.opening_duration ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="本次使用距离（m）">{{ warehouseInfo.usage_distance ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="两次开仓间地层信息" :span="3">
          {{ stratumInfoDisplay }}
        </el-descriptions-item>
        <el-descriptions-item label="开仓位置地层信息" :span="3">
          {{ warehouseInfo.geological_conditions || '-' }}
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 换刀明细表格 -->
    <el-card shadow="never" v-if="dataLoaded" class="tool-change-detail-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">换刀明细记录</span>
          <div class="header-actions">
            <ExportDropdown title="换刀明细记录" :filename="exportFilename" :rows="tableData" :columns="exportColumns" :meta="exportMeta" />
            <el-button type="success" @click="batchSave" :loading="saving">批量保存</el-button>
          </div>
        </div>
      </template>

      <el-table
        :data="tableData"
        border
        stripe
        height="calc(100vh - 280px)"
        style="width: 100%"
        :row-key="(row: any) => row.cutter_position_no"
        table-layout="fixed"
        @row-click="(row: any) => activeRowKey = row.cutter_position_no"
      >
        <el-table-column type="index" label="序号" width="60" align="center" fixed />

        <el-table-column label="刀具父类型" width="120" fixed>
          <template #default="{ row }">
            <span>{{ row.tool_parent_type_display }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="tool_type_name" label="刀具类型名称" width="200" fixed />

        <el-table-column prop="cutter_position_no" label="刀位号" width="100" fixed />

        <el-table-column label="检查状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag v-if="!row.is_checked" type="info" size="small">尚未检查</el-tag>
            <el-tag v-else-if="row.is_replaced" type="danger" size="small">已换刀</el-tag>
            <el-tag v-else type="success" size="small">已检查未换</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="刀具编号" width="150">
          <template #default="{ row }">
            <span>{{ row.tool_number || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="磨损情况" width="180">
          <template #default="{ row }">
            <template v-if="activeRowKey === row.cutter_position_no">
              <el-select
                v-model="row.wear_condition"
                placeholder="请选择或输入"
                size="small"
                filterable
                allow-create
              >
                <el-option label="正常" value="正常" />
                <el-option label="偏磨" value="偏磨" />
                <el-option label="刀圈崩刃" value="刀圈崩刃" />
                <el-option label="刀圈脱落" value="刀圈脱落" />
                <el-option label="无刀圈" value="无刀圈" />
                <el-option label="刀圈裂" value="刀圈裂" />
                <el-option label="漏油" value="漏油" />
                <el-option label="轴承损坏" value="轴承损坏" />
                <el-option label="轴承断裂" value="轴承断裂" />
                <el-option label="轴承变形" value="轴承变形" />
              </el-select>
            </template>
            <span v-else>{{ row.wear_condition || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="是否更换" width="100" align="center">
          <template #default="{ row }">
            <el-checkbox v-model="row.is_replaced" @change="handleReplaceChange(row)" />
          </template>
        </el-table-column>

        <el-table-column label="刀刃磨损量" width="120">
          <template #default="{ row }">
            <el-input-number
              v-if="activeRowKey === row.cutter_position_no"
              v-model="row.blade_wear_amount"
              :min="0"
              :precision="2"
              controls-position="right"
              size="small"
            />
            <span v-else>{{ row.blade_wear_amount ?? '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="刀位轨迹" width="150">
          <template #default="{ row }">
            <el-tooltip :content="row.trajectory?.source || '图纸依据'" placement="top">
              <span :class="row.trajectory?.status === 'CONFIRMED' ? 'trajectory-value' : 'trajectory-pending'">
                {{ row.trajectory?.display || '待按最终图纸核对' }}
              </span>
            </el-tooltip>
          </template>
        </el-table-column>

        <el-table-column prop="replacement_count" label="累计更换次数" width="120" align="center" />

        <el-table-column label="厂家" width="150">
          <template #default="{ row }">
            <el-select
              v-if="activeRowKey === row.cutter_position_no"
              v-model="row.manufacturer"
              placeholder="请选择厂家"
              size="small"
              filterable
              clearable
              :disabled="!row.is_replaced"
              @change="handleManufacturerChange(row)"
              @visible-change="(visible) => visible && refreshCostOptions(row, ['manufacturer'])"
            >
              <el-option
                v-for="item in getManufacturerOptions(row)"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              >
                <div class="cost-option">
                  <span>{{ item.label }}</span>
                  <small>{{ item.description }}</small>
                </div>
              </el-option>
            </el-select>
            <span v-else>{{ row.manufacturer || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="新刀信息" min-width="220">
          <template #default="{ row }">
            <div class="new-tool-summary">{{ newToolSummary(row) }}</div>
          </template>
        </el-table-column>

        <el-table-column label="更换类型" width="150">
          <template #default="{ row }">
            <template v-if="activeRowKey === row.cutter_position_no">
              <el-select v-model="row.replacement_type" placeholder="请选择" size="small" :disabled="!row.is_replaced" @change="handleReplacementTypeChange(row)">
                <el-option label="整刀更换" value="COMPLETE" />
                <el-option label="维修" value="REPAIR" />
              </el-select>
            </template>
            <span v-else>{{ row.replacement_type === 'COMPLETE' ? '整刀更换' : row.replacement_type === 'REPAIR' ? '维修' : '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="维修部位" width="180">
          <template #default="{ row }">
            <template v-if="activeRowKey === row.cutter_position_no">
              <el-select
                v-model="row.repair_parts"
                placeholder="请选择"
                size="small"
                multiple
                :disabled="!row.is_replaced || row.replacement_type !== 'REPAIR'"
                @change="handleRepairPartsChange(row)"
              >
                <el-option label="密封件" value="密封件" />
                <el-option label="轴承" value="轴承" />
                <el-option label="刀圈" value="刀圈" />
              </el-select>
            </template>
            <span v-else>{{ Array.isArray(row.repair_parts) && row.repair_parts.length ? row.repair_parts.join('、') : '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="品牌" width="150">
          <template #default="{ row }">
            <el-select
              v-if="activeRowKey === row.cutter_position_no"
              v-model="row.brand"
              placeholder="请选择品牌"
              size="small"
              filterable
              clearable
              :disabled="!row.is_replaced"
              @change="handleBrandChange(row)"
              @visible-change="(visible) => visible && refreshCostOptions(row, ['brand'])"
            >
              <el-option
                v-for="item in getBrandOptions(row)"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              >
                <div class="cost-option">
                  <span>{{ item.label }}</span>
                  <small>{{ item.description }}</small>
                </div>
              </el-option>
            </el-select>
            <span v-else>{{ row.brand || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="价格" width="120">
          <template #default="{ row }">
            <el-select
              v-if="activeRowKey === row.cutter_position_no"
              v-model="row.price"
              placeholder="请选择价格"
              size="small"
              :disabled="!row.is_replaced"
              filterable
              clearable
              style="width: 100%"
              @change="handlePriceChange(row)"
              @visible-change="(visible) => visible && refreshCostOptions(row)"
            >
              <el-option
                v-for="item in getPriceOptions(row)"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              >
                <div class="cost-option">
                  <span>{{ item.label }}</span>
                  <small>{{ item.description }}</small>
                </div>
              </el-option>
            </el-select>
            <span v-else>{{ row.price != null ? row.price : '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="刀具磨损更换图" width="150">
          <template #default="{ row }">
            <el-upload
              :action="uploadAction"
              :headers="uploadHeaders"
              :data="{ object_id: warehouseId }"
              :on-success="(res: any) => handleUploadSuccess(res, row)"
              :show-file-list="false"
              accept="image/*"
            >
              <el-button size="small" type="primary">上传图片</el-button>
            </el-upload>
            <div v-if="row.wear_image" style="margin-top: 5px;">
              <el-image
                :src="row.wear_image"
                :preview-src-list="[row.wear_image]"
                style="width: 50px; height: 50px;"
                fit="cover"
              />
            </div>
          </template>
        </el-table-column>

        <el-table-column label="旧刀照片" width="150">
          <template #default="{ row }">
            <div v-if="row.old_photo_links?.length" class="photo-link-list">
              <el-link
                v-for="(photo, index) in row.old_photo_links"
                :key="photo.id"
                type="primary"
                @click="previewPhoto(photo.url, photo.name || `照片${index + 1}`)"
              >{{ photo.name || `照片${index + 1}` }}</el-link>
            </div>
            <span v-else>-</span>
          </template>
        </el-table-column>

        <el-table-column label="旧刀返修" width="120" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.is_replaced" type="primary" link @click.stop="openOldToolRepair(row)">
              {{ row.old_tool_record_data ? '查看 / 补录' : '补录' }}
            </el-button>
            <span v-else>-</span>
          </template>
        </el-table-column>

        <el-table-column label="备注" min-width="160">
          <template #default="{ row }">
            <el-input
              v-if="activeRowKey === row.cutter_position_no"
              v-model="row.remark"
              type="textarea"
              placeholder="请输入备注"
              size="small"
              :rows="2"
            />
            <span v-else>{{ row.remark || '-' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <OldToolRepairDialog ref="repairDialogRef" @saved="loadData" />
    <el-dialog v-model="photoPreviewVisible" title="旧刀磨损照片" width="760px" destroy-on-close>
      <div class="photo-preview">
        <img v-if="photoPreviewUrl" :src="photoPreviewUrl" :alt="photoPreviewName" />
      </div>
    </el-dialog>
  </fs-page>
</template>

<script lang="ts" setup name="ToolChangeDetail">
import { ref, onMounted, computed, shallowRef } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { request } from '/@/utils/service';
import { ElMessage } from 'element-plus';
import { getAuthHeader } from '/@/utils/storage';
import ExportDropdown from '/@/views/shield/components/ExportDropdown.vue';
import type { ExportColumn, ExportMetaItem } from '/@/views/shield/utils/export';
import OldToolRepairDialog from './OldToolRepairDialog.vue';

const route = useRoute();
const router = useRouter();

const warehouseId = ref<number>();
const warehouseInfo = ref<any>(null);
const dataLoaded = ref(false);
const tableData = ref<any[]>([]);
const saving = ref(false);
const toolNumberCounters = ref<Map<string, number>>(new Map());
const activeRowKey = ref<string | null>(null); // 当前激活编辑的行
const costOptionsMap = ref<Record<string, any[]>>({});
const repairDialogRef = ref();
const photoPreviewVisible = ref(false);
const photoPreviewUrl = ref('');
const photoPreviewName = ref('旧刀照片');

const uploadAction = '/api/system/file/upload/';
const uploadHeaders = {
  get Authorization() { return getAuthHeader().Authorization; },
};

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
  { key: 'tool_parent_type_display', title: '刀具父类型' },
  { key: 'tool_type_name', title: '刀具类型名称' },
  { key: 'cutter_position_no', title: '刀位号' },
  { key: 'is_checked', title: '检查状态', formatter: (row) => checkStatus(row) },
  { key: 'tool_number', title: '刀具编号' },
  { key: 'wear_condition', title: '磨损情况' },
  { key: 'blade_wear_amount', title: '刀刃磨损量' },
  { key: 'trajectory', title: '刀位轨迹', formatter: (row) => row.trajectory?.display || '待按最终图纸核对' },
  { key: 'is_replaced', title: '是否更换', formatter: (row) => row.is_replaced ? '是' : '否' },
  { key: 'replacement_count', title: '累计更换次数' },
  { key: 'manufacturer', title: '厂家' },
  { key: 'new_tool_record_data', title: '新刀信息', formatter: (row) => newToolSummary(row) },
  { key: 'replacement_type', title: '更换类型', formatter: (row) => row.replacement_type === 'COMPLETE' ? '整刀更换' : row.replacement_type === 'REPAIR' ? '维修' : '' },
  { key: 'repair_parts', title: '维修部位' },
  { key: 'brand', title: '品牌' },
  { key: 'price', title: '价格' },
  { key: 'old_photo_links', title: '旧刀照片链接', formatter: (row) => (row.old_photo_links || []).map((item: any) => `${item.name || '照片'}：${item.url}`).join('\n') },
  { key: 'remark', title: '备注' },
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
    { label: '换刀总时长（小时）', value: formatEmpty(info.tool_change_duration ?? info.opening_duration) },
    { label: '本次使用距离（m）', value: formatEmpty(info.usage_distance) },
    { label: '两次开仓间地层信息', value: stratumInfoDisplay.value, span: 3 },
    { label: '开仓位置地层信息', value: formatEmpty(info.geological_conditions), span: 3 },
  ];
});

const getCostOptionKey = (row: any = {}) => row.cutter_position_no || '__default__';

const getRowCostOptions = (row: any = {}) => costOptionsMap.value[getCostOptionKey(row)] || [];

const buildCostQuery = (row: any = {}, ignoreFields: string[] = []) => ({
  shield_machine: warehouseInfo.value?.shield_model,
  cutter_position_no: row.cutter_position_no,
  tool_parent_type: row.tool_parent_type,
  replacement_type: row.replacement_type,
  manufacturer: ignoreFields.includes('manufacturer') ? undefined : row.manufacturer,
  brand: ignoreFields.includes('brand') ? undefined : row.brand,
  repair_parts: Array.isArray(row.repair_parts) ? row.repair_parts.join(',') : row.repair_parts,
});

const refreshCostOptions = async (row: any = {}, ignoreFields: string[] = []) => {
  const key = getCostOptionKey(row);
  try {
    const res = await request({
      url: '/api/shield/tool_change_detail/cost_options/',
      method: 'get',
      params: buildCostQuery(row, ignoreFields),
    });
    costOptionsMap.value[key] = Array.isArray(res.data) ? res.data : [];
  } catch (error) {
    console.error('获取成本库候选失败:', error);
    costOptionsMap.value[key] = [];
  }
};

const uniqueOptions = (options: any[], field: 'manufacturer' | 'brand') => {
  const seen = new Set<string>();
  return options
    .filter((item) => item?.[field])
    .filter((item) => {
      const value = String(item[field]);
      if (seen.has(value)) return false;
      seen.add(value);
      return true;
    })
    .map((item) => ({
      value: item[field],
      label: item[field],
      description: field === 'manufacturer'
        ? `${item.brand || '-'} / ${item.unit_price || 0}元`
        : `${item.manufacturer || '-'} / ${item.unit_price || 0}元`,
    }));
};

const getManufacturerOptions = (row: any) => {
  return uniqueOptions(
    getRowCostOptions(row).filter((item) => {
      if (row.replacement_type === 'COMPLETE' && item.cost_type !== 'NEW_TOOL') return false;
      if (row.replacement_type === 'REPAIR' && item.cost_type !== 'REPAIR') return false;
      if (row.brand && item.brand !== row.brand) return false;
      return true;
    }),
    'manufacturer'
  );
};

const getBrandOptions = (row: any) => {
  return uniqueOptions(
    getRowCostOptions(row).filter((item) => {
      if (row.replacement_type === 'COMPLETE' && item.cost_type !== 'NEW_TOOL') return false;
      if (row.replacement_type === 'REPAIR' && item.cost_type !== 'REPAIR') return false;
      if (row.manufacturer && item.manufacturer !== row.manufacturer) return false;
      return true;
    }),
    'brand'
  );
};

const getPriceOptions = (row: any) => {
  const seen = new Set<string>();
  return getRowCostOptions(row)
    .filter((item) => {
      if (row.replacement_type === 'COMPLETE' && item.cost_type !== 'NEW_TOOL') return false;
      if (row.replacement_type === 'REPAIR' && item.cost_type !== 'REPAIR') return false;
      if (row.manufacturer && item.manufacturer !== row.manufacturer) return false;
      if (row.brand && item.brand !== row.brand) return false;
      return item.price != null || item.unit_price != null;
    })
    .filter((item) => {
      const value = String(item.price ?? item.unit_price);
      const key = `${value}|${item.manufacturer || ''}|${item.brand || ''}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .map((item) => {
      const value = Number(item.price ?? item.unit_price);
      return {
        value,
        label: `${value.toFixed(2)}元`,
        manufacturer: item.manufacturer,
        brand: item.brand,
        description: `${item.manufacturer || '-'} / ${item.brand || '-'}`,
      };
    });
};

const applyMatchedCost = async (row: any) => {
  await refreshCostOptions(row);
  const matched = getRowCostOptions(row).filter((item) => {
    if (row.manufacturer && item.manufacturer !== row.manufacturer) return false;
    if (row.brand && item.brand !== row.brand) return false;
    if (row.replacement_type === 'COMPLETE' && item.cost_type !== 'NEW_TOOL') return false;
    if (row.replacement_type === 'REPAIR' && item.cost_type !== 'REPAIR') return false;
    return true;
  });
  if (matched.length === 1) {
    row.manufacturer = matched[0].manufacturer || row.manufacturer;
    row.brand = matched[0].brand || row.brand;
    row.price = matched[0].price ?? matched[0].unit_price;
  } else if (matched.length === 0) {
    row.price = undefined;
  }
};

const handleManufacturerChange = async (row: any) => {
  row.brand = '';
  row.price = undefined;
  await refreshCostOptions(row);
};

const handleBrandChange = async (row: any) => {
  row.price = undefined;
  await refreshCostOptions(row);
};

const handlePriceChange = async (row: any) => {
  const selectedPrice = Number(row.price);
  const matched = getRowCostOptions(row).filter((item) => {
    const itemPrice = Number(item.price ?? item.unit_price);
    if (Number.isNaN(itemPrice) || itemPrice !== selectedPrice) return false;
    if (row.replacement_type === 'COMPLETE' && item.cost_type !== 'NEW_TOOL') return false;
    if (row.replacement_type === 'REPAIR' && item.cost_type !== 'REPAIR') return false;
    if (row.manufacturer && item.manufacturer !== row.manufacturer) return false;
    if (row.brand && item.brand !== row.brand) return false;
    return true;
  });
  if (matched.length === 1) {
    row.manufacturer = matched[0].manufacturer || row.manufacturer;
    row.brand = matched[0].brand || row.brand;
  }
};

const handleReplacementTypeChange = async (row: any) => {
  if (row.replacement_type === 'COMPLETE') {
    row.repair_parts = [];
  }
  row.manufacturer = '';
  row.brand = '';
  row.price = undefined;
  await refreshCostOptions(row);
};

const handleRepairPartsChange = async (row: any) => {
  row.manufacturer = '';
  row.brand = '';
  row.price = undefined;
  await refreshCostOptions(row);
};

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

// 生成刀具编号
const generateToolNumber = (cutterPositionNo: string) => {
  const ringNo = warehouseInfo.value?.ring_no || '0000';

  // 获取该刀位的当前计数器
  const key = cutterPositionNo;
  let counter = toolNumberCounters.value.get(key) || 0;
  counter += 1;
  toolNumberCounters.value.set(key, counter);

  // 格式：R环号-刀位号-序号
  return `R${ringNo}-${cutterPositionNo}-${counter}`;
};

// 初始化刀具编号计数器
const initToolNumberCounters = async () => {
  try {
    const res = await request({
      url: '/api/shield/tool_change_detail/get_tool_number_counters/',
      method: 'get',
      params: {
        project_id: warehouseInfo.value.project,
      },
    });

    const counters = res.data || {};
    Object.entries(counters).forEach(([posNo, maxSeq]) => {
      toolNumberCounters.value.set(posNo, maxSeq as number);
    });
  } catch (error) {
    console.error('初始化刀具编号计数器失败:', error);
  }
};

// 获取开仓信息
const getWarehouseInfo = async () => {
  try {
    const id = route.query.warehouse_id;
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

    warehouseInfo.value = res.data;

    // 初始化刀具编号计数器
    await initToolNumberCounters();

    await loadData();
  } catch (error: any) {
    console.error('获取开仓信息失败:', error);
    ElMessage.error('获取开仓信息失败');
  }
};

// 加载数据
const loadData = async () => {
  try {
    // 获取刀位信息
    const cutterRes = await request({
      url: '/api/shield/cutter_position_info/',
      method: 'get',
      params: {
        shield_machine: warehouseInfo.value.shield_model,
        limit: 1000,
      },
    });

    const cutterPositions = cutterRes.data || cutterRes.results || [];

    // 获取已有的换刀明细
    const detailRes = await request({
      url: '/api/shield/tool_change_detail/',
      method: 'get',
      params: {
        warehouse: warehouseId.value,
        limit: 1000,
      },
    });

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

      // 刀具编号：如果已有记录则使用已有的，否则生成初始编号
      let toolNumber = existingDetail?.tool_number || '';
      if (!toolNumber) {
        // 第一次创建时自动生成初始编号
        toolNumber = generateToolNumber(pos.cutter_position_no);
      }

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
    console.error('加载数据失败:', error);
    ElMessage.error('加载数据失败');
  }
};

// 处理更换变化
const handleReplaceChange = (row: any) => {
  // 勾选更换时不做任何操作，只是标记
  // 刀具编号在保存时生成
};

const openOldToolRepair = (row: any) => {
  if (!row?.id) {
    ElMessage.warning('请先保存刀位记录');
    return;
  }
  if (!row.is_replaced) {
    ElMessage.warning('未更换刀具不能录入旧刀返修');
    return;
  }
  repairDialogRef.value?.open(row);
};

// 处理图片上传成功
const handleUploadSuccess = (res: any, row: any) => {
  if (res.code === 2000) {
    let url = res.data?.url || res.data?.file_url || '';
    // 将相对路径转为以 / 开头的绝对路径，方便 el-image 加载
    if (url && !url.startsWith('http')) {
      url = '/' + url.replace(/^\/+/, '');
    }
    row.wear_image = url;
    ElMessage.success('图片上传成功');
  } else {
    ElMessage.error('图片上传失败');
  }
};

const previewPhoto = (url: string, name = '旧刀照片') => {
  if (!url) return;
  photoPreviewUrl.value = url;
  photoPreviewName.value = name;
  photoPreviewVisible.value = true;
};

// 批量保存
const batchSave = async () => {
  saving.value = true;

  try {
    const updates = tableData.value.map(row => {
      const data: any = {
        wear_condition: row.wear_condition,
        blade_wear_amount: row.blade_wear_amount,
        is_replaced: row.is_replaced,
        manufacturer: row.manufacturer,
        replacement_type: row.replacement_type,
        repair_parts: row.repair_parts,
        brand: row.brand,
        price: row.price,
        remark: row.remark,
      };

      // 如果勾选了更换，生成新的刀具编号
      if (row.is_replaced) {
        data.tool_number = generateToolNumber(row.cutter_position_no);
      } else if (row.tool_number) {
        // 未更换则保持原编号
        data.tool_number = row.tool_number;
      }

      if (row.wear_image) {
        data.wear_image = row.wear_image;
      }

      if (row.id) {
        data.id = row.id;
      } else {
        // 新记录需要关联信息
        data.warehouse = warehouseId.value;
        data.cutter_position = row.cutter_position_id;
        data.cutter_position_no = row.cutter_position_no;
        data.tool_parent_type = row.tool_parent_type;
      }

      return data;
    });

    // 分离新增和更新
    const toCreate = updates.filter(u => !u.id);
    const toUpdate = updates.filter(u => u.id);

    // 批量更新
    if (toUpdate.length > 0) {
      await request({
        url: '/api/shield/tool_change_detail/batch_update/',
        method: 'post',
        data: { updates: toUpdate },
      });
    }

    // 批量创建
    if (toCreate.length > 0) {
      await request({
        url: '/api/shield/tool_change_detail/batch_create/',
        method: 'post',
        data: {
          warehouse_id: warehouseId.value,
          details: toCreate
        },
      });
    }

    ElMessage.success('保存成功');
    router.back();
  } catch (error: any) {
    console.error('保存失败:', error);
    ElMessage.error('保存失败');
  } finally {
    saving.value = false;
  }
};

// 返回列表
const goBack = () => {
  router.back();
};

onMounted(() => {
  getWarehouseInfo();
});
</script>

<style scoped>
.warehouse-info-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-title {
  font-size: 16px;
  font-weight: bold;
}

.tool-change-detail-card {
  margin-bottom: 20px;
}

.cost-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.cost-option small {
  color: #909399;
  font-size: 12px;
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
  line-height: 1.6;
}

.photo-preview {
  display: flex;
  justify-content: center;
  min-height: 180px;
  background: #f4f6f8;
}

.photo-preview img {
  display: block;
  max-width: 100%;
  max-height: 70vh;
  object-fit: contain;
}
</style>
