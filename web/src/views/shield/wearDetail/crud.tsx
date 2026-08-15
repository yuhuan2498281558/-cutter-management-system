import * as api from './api';
import { apiPrefix } from './api';
import { AddReq, DelReq, EditReq, UserPageQuery, UserPageRes, compute, dict } from '@fast-crud/fast-crud';
import { createIndexFormatter } from '../crudUtils';

export const createCrudOptions = function ({ crudExpose }: { crudExpose: any }) {
  return {
    crudOptions: {
      request: {
        pageRequest: async (query: UserPageQuery): Promise<UserPageRes> => {
          return await api.GetList(query);
        },
        addRequest: async (req: { form: AddReq }) => {
          return await api.AddObj(req.form);
        },
        editRequest: async (req: { form: EditReq }) => {
          return await api.UpdateObj(req.form);
        },
        delRequest: async (req: { row: DelReq }) => {
          return await api.DelObj(req.row.id);
        },
      },
      actionbar: {
        buttons: {
          add: {
            show: true,
            text: '新增',
            type: 'primary',
          },
        },
      },
      rowHandle: {
        fixed: 'right',
        width: 200,
        buttons: {
          view: {
            show: false
          },
          edit: {
            show: true,
            text: '编辑',
            iconRight: 'Edit',
            type: 'text',
          },
          remove: {
            show: true,
            text: '删除',
            iconRight: 'Delete',
            type: 'text',
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
            formatter: createIndexFormatter(crudExpose),
          },
        },
        warehouse: {
          title: '开仓编号',
          type: 'dict-select',
          column: { show: false },
          dict: dict({
            url: '/api/shield/warehouse_opening/',
            value: 'id',
            label: 'warehouse_id',
          }),
          form: {
            order: 1,
            rules: [{ required: true, message: '请选择开仓编号' }],
            component: {
              placeholder: '请选择开仓编号',
              filterable: true,
            },
          },
        },
        warehouse_id_name: {
          title: '开仓编号',
          type: 'text',
          form: { show: false },
          column: { show: true, minWidth: 150 },
        },
        cutter_position_no: {
          title: '刀位号',
          type: 'dict-select',
          search: { show: true },
          column: { minWidth: 120 },
          dict: dict({
            url: apiPrefix + 'get_cutter_positions/',
            value: 'value',
            label: 'label',
            getData: async ({ url }: any) => {
              const res = await api.GetCutterPositions();
              return res.data;
            },
          }),
          form: {
            order: 2,
            rules: [{ required: true, message: '请选择或输入刀位号' }],
            component: {
              placeholder: '请选择或输入刀位号',
              filterable: true,
              allowCreate: true,
              defaultFirstOption: false,
            },
          },
        },
        tool_type: {
          title: '刀具类型',
          type: 'dict-select',
          search: { show: true },
          column: { minWidth: 120 },
          dict: dict({
            data: [
              { label: '滚刀', value: '滚刀', color: 'primary' },
              { label: '撕裂刀', value: '撕裂刀', color: 'success' },
              { label: '刮刀', value: '刮刀', color: 'warning' },
            ],
          }),
          form: {
            order: 3,
            component: {
              placeholder: '请选择刀具类型',
            },
          },
          component: { props: { color: 'auto' } },
        },
        tool_number: {
          title: '刀具编号',
          type: 'dict-select',
          search: { show: true },
          column: { minWidth: 120 },
          dict: dict({
            url: apiPrefix + 'get_tool_numbers/',
            value: 'value',
            label: 'label',
            getData: async ({ url }: any) => {
              const res = await api.GetToolNumbers();
              return res.data;
            },
          }),
          form: {
            order: 4,
            component: {
              placeholder: '请选择或输入刀具编号',
              filterable: true,
              allowCreate: true,
              defaultFirstOption: false,
            },
          },
        },
        wear_type: {
          title: '磨损类型',
          type: 'dict-select',
          search: { show: true },
          column: { minWidth: 120 },
          dict: dict({
            data: [
              { label: '正常磨损', value: 'NORMAL', color: 'success' },
              { label: '异常磨损', value: 'ABNORMAL', color: 'danger' },
            ],
          }),
          form: {
            order: 5,
            value: 'NORMAL',
            rules: [{ required: true, message: '请选择磨损类型' }],
            component: {
              placeholder: '请选择磨损类型',
            },
          },
          component: { props: { color: 'auto' } },
        },
        wear_degree: {
          title: '磨损程度',
          type: 'input',
          search: { show: true },
          column: { minWidth: 120 },
          form: {
            order: 6,
            show: compute(({ form }) => {
              return form.wear_type === 'NORMAL';
            }),
            component: {
              placeholder: '如：轻度、中度、严重等'
            },
          },
        },
        abnormal_cause: {
          title: '异常磨损原因',
          type: 'textarea',
          search: { show: true },
          column: { minWidth: 150 },
          form: {
            order: 7,
            show: compute(({ form }) => {
              return form.wear_type === 'ABNORMAL';
            }),
            component: {
              placeholder: '请输入异常磨损原因',
              rows: 3,
            },
          },
        },
        create_datetime: {
          title: '创建时间',
          type: 'datetime',
          form: { show: false },
          column: { minWidth: 160 },
        },
      },
    },
  };
};
