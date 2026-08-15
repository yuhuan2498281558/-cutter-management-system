import * as api from './api';
import { UserPageQuery, AddReq, DelReq, EditReq, CreateCrudOptionsProps, CreateCrudOptionsRet, dict } from '@fast-crud/fast-crud';
import { createIndexFormatter } from '../crudUtils';

export const createCrudOptions = function ({ crudExpose }: CreateCrudOptionsProps): CreateCrudOptionsRet {
	const pageRequest = async (query: UserPageQuery) => await api.GetList(query);
	const editRequest = async ({ form, row }: EditReq) => {
		form.id = row.id;
		return await api.UpdateObj(form);
	};
	const delRequest = async ({ row }: DelReq) => await api.DelObj(row.id);
	const addRequest = async ({ form }: AddReq) => await api.AddObj(form);

	return {
		crudOptions: {
			request: { pageRequest, addRequest, editRequest, delRequest },
			actionbar: { buttons: { add: { show: true, text: '新增', type: 'primary' } } },
			rowHandle: {
				fixed: 'right',
				width: 180,
				buttons: {
					view: { show: false },
					edit: { show: true, text: '编辑', iconRight: 'Edit', type: 'text' },
					remove: { show: true, text: '删除', iconRight: 'Delete', type: 'text' },
				},
			},
			columns: {
				_index: {
					title: '序号',
					form: { show: false },
					column: { align: 'center', width: '70px', formatter: createIndexFormatter(crudExpose) },
				},
				tool_info: {
					title: '刀具类型',
					type: 'dict-select',
					dict: dict({ url: '/api/shield/tool_info/', value: 'id', label: 'tool_type_name' }),
					search: { show: true },
					column: { minWidth: 180, formatter: ({ row }: any) => row.tool_type_name || row.tool_info },
					form: { rules: [{ required: true, message: '请选择刀具类型' }] },
				},
				tool_type_code: { title: '刀具类型编号', type: 'input', column: { minWidth: 150 }, form: { show: false } },
				tool_number: { title: '刀具编号', type: 'input', search: { show: true }, column: { minWidth: 150 }, form: { show: false } },
				usage_time: { title: '使用时间', type: 'number', column: { minWidth: 110 } },
				usage_rings: { title: '使用环数', type: 'number', column: { minWidth: 110 } },
				remaining_life: { title: '剩余寿命预测', type: 'number', column: { minWidth: 140 } },
				future_stratum_type: {
					title: '未来地层类型',
					type: 'input',
					search: { show: true },
					column: { minWidth: 140 },
				},
				prediction_time: {
					title: '预测时间',
					type: 'datetime',
					column: { minWidth: 160 },
					form: { component: { type: 'datetime', valueFormat: 'YYYY-MM-DD HH:mm:ss' } },
				},
				remark: { title: '备注', type: 'textarea', column: { minWidth: 180 }, form: { component: { rows: 3 } } },
			},
		},
	};
};
