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
				project: {
					title: '所属项目',
					type: 'dict-select',
					dict: dict({ url: '/api/shield/project/', value: 'id', label: 'project_name' }),
					search: { show: true },
					column: { minWidth: 160, formatter: ({ row }: any) => row.project_name || row.project },
					form: { rules: [{ required: true, message: '请选择所属项目' }] },
				},
				shield_machine: {
					title: '盾构机',
					type: 'dict-select',
					dict: dict({ url: '/api/shield/shield_machine_basic_info/', value: 'id', label: 'shield_model' }),
					search: { show: true },
					column: { minWidth: 160, formatter: ({ row }: any) => row.shield_machine_name || row.shield_machine },
					form: { rules: [{ required: true, message: '请选择盾构机' }] },
				},
				ring_no: {
					title: '所属环号',
					type: 'input',
					search: { show: true },
					column: { minWidth: 100 },
					form: { rules: [{ required: true, message: '请输入所属环号' }] },
				},
				thrust: { title: '推力', type: 'number', column: { minWidth: 100 } },
				torque: { title: '扭矩', type: 'number', column: { minWidth: 100 } },
				cutterhead_speed: { title: '刀盘转速', type: 'number', column: { minWidth: 120 } },
				penetration: { title: '贯入力', type: 'number', column: { minWidth: 100 } },
				point_count: {
					title: '采样点数',
					type: 'number',
					column: { show: false },
					form: { show: false },
				},
				raw_parameters: {
					title: 'XML平均参数',
					type: 'textarea',
					column: {
						show: false,
						minWidth: 240,
						formatter: ({ row }: any) => {
							const value = row.raw_parameters;
							if (!value || Object.keys(value).length === 0) {
								return '';
							}
							return JSON.stringify(value);
						},
					},
					form: {
						show: false,
						component: { rows: 4 },
					},
				},
				import_source: {
					title: '导入来源',
					type: 'input',
					column: { minWidth: 220, show: false },
					form: { show: false },
				},
				record_time: {
					title: '记录时间',
					type: 'datetime',
					column: { minWidth: 160 },
					form: { component: { type: 'datetime', valueFormat: 'YYYY-MM-DD HH:mm:ss' } },
				},
				remark: { title: '备注', type: 'textarea', column: { minWidth: 180 }, form: { component: { rows: 3 } } },
			},
		},
	};
};
