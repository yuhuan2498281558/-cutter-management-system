<template>
  <div class="cutter-position-detail">
    <!-- 左侧：刀盘展示 -->
    <div class="left-panel">
      <div class="panel-header">
        <div class="header-left">
          <h3>刀盘展示</h3>
        </div>
        <div class="header-info">
          <span>盾构机模型: {{ shieldMachine?.shield_model_id }}</span>
          <span>型号: {{ shieldMachine?.shield_model }}</span>
        </div>
      </div>
      <div class="cutterhead-container">
        <CutterheadDisplay
          @cutter-selected="handleCutterSelected"
          :selected-cutter-code="selectedCutterCode"
        />
      </div>
    </div>

    <!-- 右侧：刀位信息表单 -->
    <div class="right-panel">
      <div class="panel-header">
        <div class="header-left">
          <el-button @click="handleClose" type="default">
            <el-icon><ArrowLeft /></el-icon>
            返回
          </el-button>
          <h3>刀位信息管理</h3>
        </div>
      </div>
      <div class="cutter-position-table">
        <fs-crud ref="crudRef" v-bind="crudBinding"></fs-crud>
      </div>
    </div>
  </div>
</template>

<script lang="ts" setup>
import { ref, onMounted } from 'vue';
import { useExpose, useCrud, dict } from '@fast-crud/fast-crud';
import { request } from '/@/utils/service';
import { ElMessage } from 'element-plus';
import { ArrowLeft } from '@element-plus/icons-vue';
import CutterheadDisplay from './CutterheadDisplay.vue';
import type { ShieldMachine, CutterInfo, CrudQuery, CrudForm, CrudRow } from '/@/types/cutter.types';

const props = defineProps<{
  shieldMachine: ShieldMachine;
}>();

const emit = defineEmits<{
  (e: 'close'): void;
}>();

const crudRef = ref();
const crudBinding = ref();
const { crudExpose } = useExpose({ crudRef, crudBinding });
const selectedCutterCode = ref<string>('');
const editingCutterPositionNo = ref<string>(''); // 保存正在编辑的刀位号

// 处理关闭
const handleClose = () => {
  emit('close');
};

// 处理刀位选择
const handleCutterSelected = (cutterInfo: CutterInfo) => {
  selectedCutterCode.value = cutterInfo.code;
};

// 智能刀位号排序函数
const sortCutterPositionNo = (a: string, b: string): number => {
  if (!a) return 1;
  if (!b) return -1;

  // 提取数字和字母部分
  const extractParts = (str: string) => {
    const match = str.match(/^([a-zA-Z]*)(\d+)([a-zA-Z]*)$/);
    if (match) {
      return {
        prefix: match[1].toLowerCase(),
        number: parseInt(match[2], 10),
        suffix: match[3].toLowerCase(),
      };
    }
    // 如果不匹配数字模式，按字符串排序
    return { prefix: str.toLowerCase(), number: 0, suffix: '' };
  };

  const partsA = extractParts(a);
  const partsB = extractParts(b);

  // 先比较前缀
  if (partsA.prefix !== partsB.prefix) {
    return partsA.prefix.localeCompare(partsB.prefix);
  }

  // 再比较数字
  if (partsA.number !== partsB.number) {
    return partsA.number - partsB.number;
  }

  // 最后比较后缀
  return partsA.suffix.localeCompare(partsB.suffix);
};


// CRUD配置
const crudOptions = {
  table: {
    height: '100%',
    rowKey: 'id',  // 指定行的唯一标识
  },
  pagination: {
    pageSize: 1000,  // 设置足够大的数量，确保所有刀位数据在一页内显示
  },
  form: {
    onOpen: (ctx: any) => {
      // 不需要了
    },
    afterSubmit: (ctx: any) => {
      // 编辑模式下刷新后滚动到编辑的刀位
      if (ctx.mode === 'edit' && editingCutterPositionNo.value) {
        // 等待表格刷新完成
        setTimeout(() => {
          const tableWrapper = document.querySelector('.cutter-position-table .el-table__body-wrapper');
          if (tableWrapper) {
            // 查找包含刀位号的单元格
            const cells = tableWrapper.querySelectorAll('.el-table__body tbody td');
            for (const cell of cells) {
              if (cell.textContent?.trim() === editingCutterPositionNo.value) {
                const row = cell.closest('tr');
                if (row) {
                  // 计算行相对于表格容器的位置
                  const rowTop = (row as HTMLElement).offsetTop;
                  const wrapperHeight = (tableWrapper as HTMLElement).clientHeight;
                  const rowHeight = (row as HTMLElement).clientHeight;

                  // 滚动表格容器，让该行居中显示
                  (tableWrapper as HTMLElement).scrollTop = rowTop - (wrapperHeight / 2) + (rowHeight / 2);
                  break;
                }
              }
            }
          }
          editingCutterPositionNo.value = '';
        }, 500);
      }
    },
  },
  request: {
    pageRequest: async (query: CrudQuery) => {
      const res = await request({
        url: '/api/shield/cutter_position_info/',
        method: 'get',
        params: {
          ...query,
          shield_machine: props.shieldMachine.id,
          // 添加排序参数
          ordering: 'tool_type,cutter_position_no',
        },
      });

      // 前端二次排序，确保刀位号按数字大小排序
      // 支持 data 和 results 两种响应格式
      const dataArray = res.data || res.results;
      if (dataArray && Array.isArray(dataArray)) {
        dataArray.sort((a: any, b: any) => {
          // 首先按刀具类型排序
          const typeCompare = (a.tool_type || '').localeCompare(b.tool_type || '');
          if (typeCompare !== 0) return typeCompare;

          // 然后按刀位号排序（智能数字排序）
          return sortCutterPositionNo(a.cutter_position_no, b.cutter_position_no);
        });

        // 确保排序后的数据被正确赋值回响应对象
        if (res.data) {
          res.data = dataArray;
        } else if (res.results) {
          res.results = dataArray;
        }
      }

      return res;
    },
    addRequest: async ({ form }: { form: CrudForm }) => {
      form.shield_machine = props.shieldMachine.id;
      const res = await request({
        url: '/api/shield/cutter_position_info/',
        method: 'post',
        data: form,
      });
      ElMessage.success('添加成功');
      return res;
    },
    editRequest: async ({ form, row }: { form: CrudForm; row: CrudRow }) => {
      // 保存正在编辑的刀位号
      editingCutterPositionNo.value = form.cutter_position_no;

      const res = await request({
        url: `/api/shield/cutter_position_info/${form.id}/`,
        method: 'put',
        data: form,
      });

      ElMessage.success('修改成功');

      // 手动更新当前行数据
      const updatedData = res.data || res;
      Object.assign(row, updatedData);

      return res;
    },
    delRequest: async ({ row }: { row: CrudRow }) => {
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
    cutter_position_no: {
      title: '刀位号',
      type: 'input',
      search: { show: true },
      column: {
        minWidth: 120,
        sortable: false,
        order: 1,
      },
      form: {
        rules: [{ required: true, message: '请输入刀位号' }],
        component: {
          placeholder: '请输入刀位号（如：1、2、S1L等）',
        },
        order: 1,
      },
    },
    _tool_parent_type_select: {
      title: '刀具父类型',
      type: 'dict-select',
      dict: dict({
        data: [
          { label: '滚刀', value: 'DISC' },
          { label: '撕裂刀', value: 'RIPPER' },
          { label: '刮刀', value: 'SCRAPER' },
        ],
      }),
      column: {
        show: false,
      },
      form: {
        rules: [{ required: true, message: '请选择刀具父类型' }],
        component: {
          placeholder: '请先选择刀具父类型',
        },
        valueChange: async ({ value, form, getComponentRef }: any) => {
          // 清空刀具类型选择
          form.tool_info = undefined;
          form._tool_type_code_display = undefined;

          // 刷新刀具类型名称的选项
          const toolInfoRef = getComponentRef('tool_info');
          if (toolInfoRef) {
            await toolInfoRef.reloadDict();
          }
        },
        order: 2,
      },
    },
    tool_info: {
      title: '刀具类型名称',
      type: 'dict-select',
      dict: dict({
        getData: async ({ form }: any) => {
          if (!form?._tool_parent_type_select) {
            return [];
          }

          try {
            const res = await request({
              url: '/api/shield/tool_info/',
              method: 'get',
              params: {
                tool_parent_type: form._tool_parent_type_select,
                limit: 999,
              },
            });

            const data = res.data || res.results || [];

            // 去重：相同 tool_type_code 只保留一个（选第一个 id）
            const uniqueMap = new Map();
            for (const item of data) {
              if (!uniqueMap.has(item.tool_type_code)) {
                uniqueMap.set(item.tool_type_code, item);
              }
            }
            const uniqueData = Array.from(uniqueMap.values());

            return uniqueData;
          } catch (error) {
            console.error('获取刀具类型列表失败:', error);
            return [];
          }
        },
        label: 'tool_type_name',
        value: 'id',  // 使用 id 作为值
      }),
      column: {
        show: false,
      },
      form: {
        rules: [{ required: true, message: '请选择刀具类型名称' }],
        component: {
          placeholder: '请选择刀具类型名称',
          filterable: true,
        },
        valueChange: async ({ value, form }: any) => {
          if (value) {
            // 获取选中的刀具详情，显示编号
            try {
              const res = await request({
                url: `/api/shield/tool_info/${value}/`,
                method: 'get',
              });
              form._tool_type_code_display = res.tool_type_code;
            } catch (error) {
              console.error('获取刀具详情失败:', error);
            }
          } else {
            form._tool_type_code_display = undefined;
          }
        },
        wrapper: {
          onOpened: async ({ mode, form, row }: any) => {
            // 编辑模式下，回显父类型
            if (mode === 'edit' && row?.tool_parent_type) {
              setTimeout(() => {
                form._tool_parent_type_select = row.tool_parent_type;
                form._tool_type_code_display = row.tool_type_code;
              }, 100);
            }
          },
        },
        order: 3,
      },
    },
    _tool_type_code_display: {
      title: '刀具类型编号',
      type: 'input',
      column: {
        show: false,
      },
      form: {
        component: {
          placeholder: '自动显示',
          disabled: true,
        },
        order: 4,
      },
    },
    tool_parent_type: {
      title: '刀具父类型',
      type: 'text',
      column: {
        minWidth: 120,
        sortable: false,
        order: 2,
        formatter: (context: any) => {
          const typeMap: any = {
            'DISC': '滚刀',
            'RIPPER': '撕裂刀',
            'SCRAPER': '刮刀',
          };
          const value = context.row?.tool_parent_type;
          return typeMap[value] || value || '-';
        },
      },
      form: {
        show: false,
      },
    },
    tool_type_name: {
      title: '刀具类型名称',
      type: 'text',
      column: {
        minWidth: 150,
        sortable: false,
        order: 3,
      },
      form: {
        show: false,
      },
    },
    tool_type_code: {
      title: '刀具类型编号',
      type: 'text',
      column: {
        minWidth: 150,
        sortable: false,
        order: 4,
      },
      form: {
        show: false,
      },
    },
    create_datetime: {
      title: '创建时间',
      type: 'datetime',
      form: { show: false },
      column: {
        minWidth: 160,
        order: 5,
      },
    },
  },
};

const { resetCrudOptions } = useCrud({ crudExpose, crudOptions });

onMounted(() => {
  crudExpose.doRefresh();
});
</script>

<style scoped>
.cutter-position-detail {
  display: flex;
  height: 100vh;
  background: #f5f5f5;
}

.left-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-right: 1px solid #e0e0e0;
}

.right-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fff;
  padding: 20px;
}

.panel-header {
  padding: 20px;
  border-bottom: 1px solid #e0e0e0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-header .header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.panel-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  white-space: nowrap;
}

.header-info {
  display: flex;
  justify-content: flex-end;
  min-width: 0;
  gap: 20px;
  font-size: 12px;
  color: #666;
}

.header-info span {
  min-width: 0;
}

.cutterhead-container {
  flex: 1;
  overflow: hidden;
}

.cutter-position-table {
  flex: 1;
  margin-top: 20px;
  overflow: hidden;
}

.cutter-position-table :deep(.fs-crud) {
  height: 100%;
}

.cutter-position-table :deep(.el-table) {
  height: calc(100% - 100px) !important;
}
</style>
