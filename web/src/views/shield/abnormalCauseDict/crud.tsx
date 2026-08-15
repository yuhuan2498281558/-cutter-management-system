import * as api from './api';
import { AddReq, DelReq, EditReq, UserPageQuery, UserPageRes } from '@fast-crud/fast-crud';

export const createCrudOptions = function ({ crudExpose }: { crudExpose: any }) {
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
        id: {
          title: 'ID',
          type: 'number',
          form: { show: false },
          column: { width: 80 },
        },
        cause_name: {
          title: '异常原因名称',
          type: 'input',
          form: { rules: [{ required: true, message: '请输入异常原因名称' }] },
        },
        cause_code: {
          title: '异常原因编码',
          type: 'input',
          form: { rules: [{ required: true, message: '请输入异常原因编码' }] },
        },
        description: {
          title: '原因描述',
          type: 'textarea',
          column: { show: false },
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
