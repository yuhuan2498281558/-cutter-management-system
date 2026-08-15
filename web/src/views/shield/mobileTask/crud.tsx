import * as api from './api';
import { AddReq, DelReq, EditReq, UserPageQuery, UserPageRes, dict } from '@fast-crud/fast-crud';

const statusMap: Record<string, string> = {
  UNASSIGNED: '待分配',
  PENDING: '待处理',
  IN_PROGRESS: '录入中',
  SUBMITTED: '已提交',
  RETURNED: '已退回',
  COMPLETED: '已完成',
  CANCELLED: '已取消',
};

const scopeMap: Record<string, string> = {
  ALL: '全部刀位',
  TOOL_TYPE: '按刀具类型',
  POSITION_LIST: '按刀位清单',
};

const listText = (value: unknown) => Array.isArray(value) ? value.join('、') : (value || '');
const toolTypeOptions = [
  { label: '滚刀', value: 'DISC' },
  { label: '撕裂刀', value: 'RIPPER' },
  { label: '刮刀', value: 'SCRAPER' },
];

export const createCrudOptions = function ({ crudExpose, openApproval }: { crudExpose: any; openApproval?: (row: any) => void }) {
  return {
    crudOptions: {
      request: {
        pageRequest: async (query: UserPageQuery): Promise<UserPageRes> => await api.GetList(query),
        addRequest: async (req: { form: AddReq }) => await api.AddObj(req.form),
        editRequest: async (req: { form: EditReq }) => await api.UpdateObj(req.form),
        delRequest: async (req: { row: DelReq }) => await api.DelObj(req.row.id),
      },
      actionbar: {
        buttons: {
          add: { show: false },
        },
      },
      rowHandle: {
        fixed: 'right',
        width: 120,
        buttons: {
          view: { show: false },
          edit: { show: false },
          remove: { show: false },
          approvalTask: {
            text: '查看录入',
            type: 'text',
            show: ({ row }: any) => ['SUBMITTED', 'RETURNED', 'COMPLETED'].includes(row.status),
            click: ({ row }: any) => {
              openApproval?.(row);
            },
          },
        },
      },
      columns: {
        id: {
          title: 'ID',
          type: 'number',
          form: { show: false },
          column: { width: 80 },
        },
        warehouse: {
          title: '开仓记录',
          type: 'dict-select',
          dict: dict({ url: '/api/shield/warehouse_opening/', label: 'warehouse_id', value: 'id' }),
          form: {
            show: false,
            rules: [{ required: true, message: '请选择开仓记录' }],
            component: { placeholder: '请选择开仓记录', filterable: true },
          },
          column: { width: 110 },
        },
        warehouse_id_name: {
          title: '开仓编号',
          type: 'text',
          form: { show: false },
          column: { width: 140 },
        },
        project_name: {
          title: '项目',
          type: 'text',
          form: { show: false },
          column: { minWidth: 160 },
        },
        ring_no: {
          title: '环号',
          type: 'text',
          form: { show: false },
          column: { width: 100 },
        },
        recorder: {
          title: '录入员',
          type: 'text',
          form: { show: false },
          column: { show: false, width: 110 },
        },
        recorder_name: {
          title: '录入员',
          type: 'text',
          form: { show: false },
          column: { width: 120 },
        },
        scope_type: {
          title: '任务范围',
          type: 'dict-select',
          dict: { data: Object.entries(scopeMap).map(([value, label]) => ({ value, label })) },
          form: { show: false, value: 'ALL' },
          column: { show: false, formatter: ({ value }: any) => scopeMap[value] || value },
        },
        tool_types: {
          title: '刀具类型',
          type: 'dict-select',
          dict: { data: toolTypeOptions },
          form: {
            show: false,
            helper: '范围分配建议从开仓记录行的分配录入进入',
            component: { multiple: true, clearable: true },
          },
          column: { show: false, width: 160, formatter: ({ value }: any) => listText(value) },
        },
        position_nos: {
          title: '刀位清单',
          type: 'textarea',
          column: { show: false, width: 180, formatter: ({ value }: any) => listText(value) },
          form: { show: false, helper: '按刀位清单分配时填写，多个用逗号或换行分隔' },
        },
        status: {
          title: '状态',
          type: 'dict-select',
          dict: { data: Object.entries(statusMap).map(([value, label]) => ({ value, label })) },
          form: { show: false, value: 'UNASSIGNED' },
          column: { width: 100, formatter: ({ value }: any) => statusMap[value] || value },
        },
        progress: {
          title: '进度',
          type: 'text',
          form: { show: false },
          column: {
            width: 170,
            formatter: ({ value }: any) => value ? `${value.saved || 0}/${value.total || 0}，换刀 ${value.replaced || 0}，缺照片 ${value.missing_photo || 0}` : '',
          },
        },
        returned_reason: {
          title: '退回原因',
          type: 'textarea',
          column: { show: false },
        },
        submitted_at: {
          title: '提交时间',
          type: 'datetime',
          form: { show: false },
          column: { width: 160 },
        },
        create_datetime: {
          title: '创建时间',
          type: 'datetime',
          form: { show: false },
          column: { width: 160 },
        },
      },
    },
  };
};
