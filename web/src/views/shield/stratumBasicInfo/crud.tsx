import * as api from './api';
import { UserPageQuery, AddReq, DelReq, EditReq, CreateCrudOptionsProps, CreateCrudOptionsRet, dict } from '@fast-crud/fast-crud';
import { createIndexFormatter } from '../crudUtils';
import { request } from '/@/utils/service';
import { h } from 'vue';

export const longitudinalRatioEntries = (value?: Record<string, number>, notes: string[] = []) => {
  if (!value || !Object.keys(value).length) return ['未提取', ...notes];
  // Also guard rows cached before the API correction; never display a condition
  // label as an area measurement merely because the label exists on this ring.
  const ratios = { ...value };
  for (const code of ['CLAY_SAND', 'SOFT_HARD', 'SOFT_SOIL', 'WEAK_GRANITE',
    'ZONE_CLAY_SAND', 'ZONE_SOFT_HARD', 'ZONE_WEAK_GRANITE', 'ZONE_BEDROCK_PROTRUSION', 'ZONE_SOFT_SOIL']) {
    if (ratios[code] > 0) ratios.OTHER_IDENTIFIED = (ratios.OTHER_IDENTIFIED || 0) + ratios[code];
    delete ratios[code];
  }
  const labels: Record<string, string> = {
    AREA_CLAY_SAND: '黏土夹砂地层', AREA_SOFT_HARD: '上软下硬地层',
    AREA_WEAK_GRANITE: '全断面弱风化花岗岩', AREA_BEDROCK_PROTRUSION: '基岩凸起地层',
    AREA_SOFT_SOIL: '软土地基', AREA_BOULDER: '孤石',
    OTHER_IDENTIFIED: '已识别区域（分类面积待核定）', UNRESOLVED: '未识别区域',
  };
  return [...Object.entries(labels).filter(([code]) => ratios[code] > 0)
    .map(([code, label]) => {
      const percent = ratios[code];
      return `${label} ${percent > 0 && percent < 0.01 ? '<0.01' : Number(percent.toFixed(2))}%`;
    }), ...notes];
};

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
        engineering_zones_list: {
          title: '地层类型',
          type: 'text',
          column: {
            show: true,
            minWidth: 200,
            formatter: (context) => {
              const list = context.value || [];
              if (list.length === 0) return '分类待核定';
              return list.map((item: any) => item.name).join('、');
            },
          },
          form: {
            show: false,
          },
        },
        rock_types_list: {
          title: '岩层类型',
          type: 'text',
          form: { show: false },
          column: { minWidth: 200, formatter: ({ value }) =>
            (value || []).map((item: any) => item.name).join('、') || '占比未提取，岩层类型未知' },
        },
        longitudinal_type_ratios: {
          title: '地层占比（每环子地层面积归并）',
          type: 'text',
          form: { show: false },
          column: {
            minWidth: 240,
            showOverflowTooltip: false,
            formatter: ({ value, row }) => longitudinalRatioEntries(value, row?.longitudinal_area_notes).join('；'),
            conditionalRender: { match: () => true, render: ({ value, row }) => {
              const entries = longitudinalRatioEntries(value, row?.longitudinal_area_notes);
              return h('div', { style: { whiteSpace: 'normal', lineHeight: '20px', padding: '2px 0' } },
                entries.length ? entries.map(text => h('div', { key: text }, text)) : '未提取');
            } },
          },
        },
        stratum_types_data: {
          title: '工程地质条件',
          type: 'dict-select',
          column: { show: false },
          dict: dict({
            url: '/api/init/dictionary/?dictionary_key=stratum_type',
            label: 'label',
            value: 'value',
            getData: async ({ url }: any) => {
              const response = await request({ url, method: 'get' });
              return (response.data || []).map((item: any) => item.value === 'WEAK_GRANITE'
                ? { ...item, label: '弱风化花岗岩段（含局部侵入）' } : item);
            },
          }),
          form: {
            show: true,
            component: {
              multiple: true,
              filterable: true,
              placeholder: '请选择工程地质条件（可多选）',
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
