<template>
  <div class="cutter-position-manager">
    <div class="header-info">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="盾构机模型编号">{{ shieldMachine.shield_model_id }}</el-descriptions-item>
        <el-descriptions-item label="盾构机型号">{{ shieldMachine.shield_model }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <div class="cutter-position-table" style="margin-top: 20px; height: 1000px;">
      <fs-crud ref="crudRef" v-bind="crudBinding" style="height: 100%;"></fs-crud>
    </div>
  </div>
</template>

<script lang="ts" setup>
import { ref, onMounted, defineProps } from 'vue';
import { useExpose, useCrud, dict } from '@fast-crud/fast-crud';
import { request } from '/@/utils/service';
import { ElMessage } from 'element-plus';
import { isActiveCutterPosition } from '/@/constants/cutterPositions';

const props = defineProps<{
  shieldMachine: any;
}>();

const crudRef = ref();
const crudBinding = ref();
const { crudExpose } = useExpose({ crudRef, crudBinding });

// CRUD配置
const crudOptions = {
  table: {
    height: 1000, // 设置表格高度
  },
  form: {
    afterSubmit: async (ctx: any) => {
      // 编辑成功后不刷新整个表格，只更新当前行
      if (ctx.mode === 'edit') {
        return false; // 返回 false 阻止默认的刷新行为
      }
    },
  },
  request: {
    pageRequest: async (query: any) => {
      const res = await request({
        url: '/api/shield/cutter_position_info/',
        method: 'get',
        params: {
          ...query,
          shield_machine: props.shieldMachine.id,
        },
      });
      const dataArray = res.data || res.results;
      if (Array.isArray(dataArray)) {
        const activeData = dataArray.filter((item: any) =>
          isActiveCutterPosition(item.cutter_position_no)
        );
        dataArray.splice(0, dataArray.length, ...activeData);
      }
      return res;
    },
    addRequest: async ({ form }: any) => {
      form.shield_machine = props.shieldMachine.id;
      const res = await request({
        url: '/api/shield/cutter_position_info/',
        method: 'post',
        data: form,
      });
      ElMessage.success('添加成功');
      return res;
    },
    editRequest: async ({ form, row }: any) => {
      const res = await request({
        url: `/api/shield/cutter_position_info/${form.id}/`,
        method: 'put',
        data: form,
      });
      ElMessage.success('修改成功');
      // 返回更新后的数据，fast-crud会自动更新当前行而不刷新整个表格
      return res.data || res;
    },
    delRequest: async ({ row }: any) => {
      const res = await request({
        url: `/api/shield/cutter_position_info/${row.id}/`,
        method: 'delete',
      });
      ElMessage.success('删除成功');
      return res;
    },
  },
  actionbar: {
    buttons: {
      add: {
        show: true,
        text: '新增刀位',
        type: 'primary',
      },
    },
  },
  rowHandle: {
    fixed: 'right',
    width: 200,
    buttons: {
      view: { show: false },
      edit: {
        show: true,
        text: '编辑',
        type: 'primary',
        link: true,
      },
      remove: {
        show: true,
        text: '删除',
        type: 'danger',
        link: true,
      },
    },
  },
  columns: {
    _index: {
      title: '序号',
      form: { show: false },
      column: {
        align: 'center',
        width: '70px',
        formatter: (context: any) => {
          let index = context.index ?? 1;
          let pagination = crudExpose!.crudBinding.value.pagination;
          return ((pagination!.currentPage ?? 1) - 1) * pagination!.pageSize + index + 1;
        },
      },
    },
    cutter_position_no: {
      title: '刀位号',
      type: 'input',
      search: { show: true },
      column: { minWidth: 120 },
      form: {
        rules: [{ required: true, message: '请输入刀位号' }],
        component: {
          placeholder: '请输入刀位号（如：A1、B2等）',
        },
        order: 1,
      },
    },
    tool_type: {
      title: '刀具类型',
      type: 'dict-select',
      dict: dict({
        url: '/api/system/dictionary/?parent=50',
        label: 'label',
        value: 'value',
      }),
      column: {
        show: true,
        minWidth: 100,
        formatter: (context: any) => {
          const typeMap: any = {
            'DISC': '滚刀',
            'RIPPER': '撕裂刀',
            'SCRAPER': '刮刀',
          };
          const value = context.row?.tool_type;
          return typeMap[value] || value;
        },
      },
      form: {
        rules: [{ required: true, message: '请选择刀具类型' }],
        component: {
          placeholder: '请选择刀具类型',
        },
        order: 2,
      },
    },
    create_datetime: {
      title: '创建时间',
      type: 'datetime',
      form: { show: false },
      column: { minWidth: 160 },
    },
  },
};

const { resetCrudOptions } = useCrud({ crudExpose, crudOptions });

onMounted(() => {
  crudExpose.doRefresh();
});
</script>

<style scoped>
.cutter-position-manager {
  padding: 10px;
}

.header-info {
  margin-bottom: 20px;
}

.cutter-position-table {
  height: 1000px;
}

.cutter-position-table :deep(.fs-crud) {
  height: 100%;
}

.cutter-position-table :deep(.el-table) {
  height: calc(100% - 100px) !important;
}
</style>
