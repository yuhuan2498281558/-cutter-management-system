<template>
  <div class="batch-tool-change">
    <el-card shadow="never">
      <template #header>
        <div class="header">
          <span>批量录入换刀明细</span>
          <div>
            <el-button @click="loadCutterPositions" type="primary">加载刀位信息</el-button>
            <el-button @click="batchSave" type="success" :loading="saving">批量保存</el-button>
          </div>
        </div>
      </template>

      <el-table
        :data="tableData"
        border
        stripe
        height="600"
        style="width: 100%"
      >
        <el-table-column type="index" label="序号" width="60" align="center" fixed />

        <el-table-column prop="tool_parent_type" label="刀具父类型" width="120" fixed>
          <template #default="{ row }">
            {{ formatToolParentType(row.tool_parent_type) }}
          </template>
        </el-table-column>

        <el-table-column prop="tool_type_name" label="刀具类型名称" width="180" fixed />

        <el-table-column prop="cutter_position_no" label="刀位号" width="100" fixed />

        <el-table-column label="刀具编号" width="150">
          <template #default="{ row }">
            <el-input v-model="row.tool_number" placeholder="请输入刀具编号" size="small" />
          </template>
        </el-table-column>

        <el-table-column label="磨损情况" width="150">
          <template #default="{ row }">
            <el-select v-model="row.wear_condition" placeholder="请选择" size="small">
              <el-option label="良好" value="GOOD" />
              <el-option label="正常磨损" value="NORMAL" />
              <el-option label="中度磨损" value="MODERATE" />
              <el-option label="严重磨损" value="SEVERE" />
              <el-option label="异常磨损" value="ABNORMAL" />
            </el-select>
          </template>
        </el-table-column>

        <el-table-column label="是否更换" width="100" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.is_replaced" />
          </template>
        </el-table-column>

        <el-table-column prop="replacement_count" label="累计更换次数" width="120" align="center" />

        <el-table-column label="厂家" width="150">
          <template #default="{ row }">
            <el-input v-model="row.manufacturer" placeholder="请输入厂家" size="small" />
          </template>
        </el-table-column>

        <el-table-column label="更换类型" width="150">
          <template #default="{ row }">
            <el-select v-model="row.replacement_type" placeholder="请选择" size="small" :disabled="!row.is_replaced">
              <el-option label="整刀更换" value="COMPLETE" />
              <el-option label="维修" value="REPAIR" />
            </el-select>
          </template>
        </el-table-column>

        <el-table-column label="维修部位" width="180">
          <template #default="{ row }">
            <el-select
              v-model="row.repair_parts"
              placeholder="请选择"
              size="small"
              multiple
              :disabled="!row.is_replaced || row.replacement_type !== 'REPAIR'"
            >
              <el-option label="密封件" value="密封件" />
              <el-option label="轴承" value="轴承" />
              <el-option label="刀圈" value="刀圈" />
            </el-select>
          </template>
        </el-table-column>

        <el-table-column label="品牌" width="150">
          <template #default="{ row }">
            <el-input
              v-model="row.brand"
              placeholder="请输入品牌"
              size="small"
              :disabled="!row.is_replaced || row.replacement_type !== 'REPAIR'"
            />
          </template>
        </el-table-column>

        <el-table-column label="价格" width="120">
          <template #default="{ row }">
            <el-input-number
              v-model="row.price"
              placeholder="价格"
              size="small"
              :min="0"
              :precision="2"
              :disabled="!row.is_replaced || row.replacement_type !== 'REPAIR'"
              style="width: 100%"
            />
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

        <el-table-column label="备注" width="200">
          <template #default="{ row }">
            <el-input
              v-model="row.remark"
              type="textarea"
              placeholder="请输入备注"
              size="small"
              :rows="2"
            />
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script lang="ts" setup>
import { ref } from 'vue';
import { request } from '/@/utils/service';
import { ElMessage } from 'element-plus';
import { Session } from '/@/utils/storage';

const props = defineProps<{
  warehouseId: number;
  shieldMachineId: number;
}>();

const tableData = ref<any[]>([]);
const saving = ref(false);

const uploadAction = '/api/system/file/upload/';
const uploadHeaders = {
  // 全站统一用 JWT 前缀（request.ts / service.ts 均如此），此处原为 Bearer，
  // DRF 期望 JWT 关键字，会导致上传 401。
  get Authorization() { return 'JWT ' + Session.get('token'); },
};

// 格式化刀具父类型
const formatToolParentType = (type: string) => {
  const map: any = {
    'DISC': '滚刀',
    'RIPPER': '撕裂刀',
    'SCRAPER': '刮刀',
  };
  return map[type] || type;
};

// 加载刀位信息
const loadCutterPositions = async () => {
  try {
    const res = await request({
      url: '/api/shield/cutter_position_info/',
      method: 'get',
      params: {
        shield_machine: props.shieldMachineId,
        limit: 1000,
      },
    });

    const positions = res.data || res.results || [];

    // 转换为表格数据
    tableData.value = positions.map((pos: any) => ({
      cutter_position_id: pos.id,
      tool_parent_type: pos.tool_type || pos.tool_parent_type,
      tool_type_name: pos.tool_type_name || '-',
      cutter_position_no: pos.cutter_position_no,
      tool_number: '',
      wear_condition: 'GOOD',
      is_replaced: false,
      replacement_count: 0,
      manufacturer: '',
      replacement_type: undefined,
      repair_parts: [],
      brand: '',
      price: undefined,
      wear_image: '',
      remark: '',
    }));

    ElMessage.success(`已加载 ${tableData.value.length} 个刀位信息`);
  } catch (error: any) {
    console.error('加载刀位信息失败:', error);
    ElMessage.error('加载刀位信息失败: ' + (error.message || '未知错误'));
  }
};

// 处理图片上传成功
const handleUploadSuccess = (res: any, row: any) => {
  if (res.code === 2000) {
    row.wear_image = res.data?.url || res.data?.file_url;
    ElMessage.success('图片上传成功');
  } else {
    ElMessage.error('图片上传失败');
  }
};

// 批量保存
const batchSave = async () => {
  // 验证必填字段
  const invalidRows = tableData.value.filter(row => {
    if (!row.tool_number || !row.wear_condition) {
      return true;
    }
    if (row.is_replaced && !row.replacement_type) {
      return true;
    }
    if (row.is_replaced && row.replacement_type === 'REPAIR') {
      if (!row.repair_parts || row.repair_parts.length === 0 || !row.brand || !row.price) {
        return true;
      }
    }
    return false;
  });

  if (invalidRows.length > 0) {
    ElMessage.error(`有 ${invalidRows.length} 行数据填写不完整，请检查`);
    return;
  }

  saving.value = true;

  try {
    // 批量创建换刀记录
    const promises = tableData.value.map(row => {
      return request({
        url: '/api/shield/tool_change_detail/',
        method: 'post',
        data: {
          warehouse: props.warehouseId,
          tool_parent_type: formatToolParentType(row.tool_parent_type),
          cutter_position_no: row.cutter_position_no,
          tool_number: row.tool_number,
          wear_condition: row.wear_condition,
          is_replaced: row.is_replaced,
          manufacturer: row.manufacturer,
          replacement_type: row.replacement_type,
          repair_parts: row.repair_parts,
          brand: row.brand,
          price: row.price,
          wear_image: row.wear_image,
          remark: row.remark,
        },
      });
    });

    await Promise.all(promises);

    ElMessage.success('批量保存成功');
    tableData.value = [];
  } catch (error: any) {
    console.error('批量保存失败:', error);
    ElMessage.error('批量保存失败: ' + (error.message || '未知错误'));
  } finally {
    saving.value = false;
  }
};

defineExpose({
  loadCutterPositions,
});
</script>

<style scoped>
.batch-tool-change {
  padding: 20px;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
