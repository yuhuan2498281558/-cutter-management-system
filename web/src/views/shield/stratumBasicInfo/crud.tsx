import * as api from './api';
import { UserPageQuery, AddReq, DelReq, EditReq, CreateCrudOptionsProps, CreateCrudOptionsRet, dict } from '@fast-crud/fast-crud';
import { createIndexFormatter } from '../crudUtils';

export const createCrudOptions = function ({ crudExpose }: CreateCrudOptionsProps): CreateCrudOptionsRet {
  const pageRequest = async (query: UserPageQuery) => {
    return await api.GetList(query);
  };
  const editRequest = async ({ form, row }: EditReq) => {
    form.id = row.id;
    return await api.UpdateObj(form);
  };
  const delRequest = async ({ row }: DelReq) => {
    return await api.DelObj(row.id);
  };
  const addRequest = async ({ form }: AddReq) => {
    return await api.AddObj(form);
  };

  const exportRequest = async (query: UserPageQuery) => {
    return await api.exportData(query);
  };

  return {
    crudOptions: {
      request: {
        pageRequest,
        addRequest,
        editRequest,
        delRequest,
      },
      actionbar: {
        buttons: {
          add: {
            show: true,
            text: '新增',
            type: 'primary',
          },
          export: {
            show: true,
            text: '导出',
            title: '导出数据',
            click() {
              return exportRequest(crudExpose.getSearchFormData());
            }
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
        id: {
          title: 'ID',
          type: 'number',
          form: { show: false },
          column: { width: 80 },
        },
        project: {
          title: '项目编号',
          type: 'dict-select',
          column: { show: false },
          dict: dict({
            url: '/api/shield/project/',
            label: 'project_id',
            value: 'id',
          }),
          form: {
            rules: [{ required: true, message: '请选择项目编号' }],
            component: {
              placeholder: '请选择项目编号',
              filterable: true,
            },
          },
        },
        project_name: {
          title: '项目名称',
          type: 'text',
          form: { show: false },
          column: { show: true, minWidth: 150 },
        },
        ring_no: {
          title: '环号',
          type: 'input',
          form: { rules: [{ required: true, message: '请输入环号' }] },
        },
        stratum_types_list: {
          title: '地层类型',
          type: 'text',
          column: {
            show: true,
            minWidth: 200,
            formatter: (context) => {
              const list = context.value || [];
              if (list.length === 0) return '-';
              return list.map((item: any) => item.name).join('、');
            },
          },
          form: {
            show: false,
          },
        },
        stratum_types_data: {
          title: '地层类型',
          type: 'dict-select',
          column: { show: false },
          dict: dict({
            url: '/api/init/dictionary/?dictionary_key=stratum_type',
            label: 'label',
            value: 'value',
          }),
          form: {
            show: true,
            component: {
              multiple: true,
              filterable: true,
              placeholder: '请选择地层类型（可多选）',
            },
            valueBuilder: (context) => {
              // 从后端获取的数据转换为表单数据
              if (context.row && context.row.stratum_types_list) {
                return context.row.stratum_types_list.map((item: any) => item.code);
              }
              return [];
            },
            valueResolve: (context) => {
              // 表单数据已经是编码数组，无需转换
              // 后端期望格式: ['CLAY_SAND', 'SOFT_HARD']
            },
          },
        },
        stratum_info: {
          title: '地层信息（备注）',
          type: 'textarea',
          column: { show: false },
          form: {
            show: true,
            component: {
              placeholder: '可选填，用于补充说明地层信息',
            },
          },
        },
        burial_depth: {
          title: '埋深(m)',
          type: 'number',
          column: { minWidth: 120 },
          form: {
            component: {
              placeholder: '请输入埋深',
              min: 0,
              precision: 2,
            },
          },
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
