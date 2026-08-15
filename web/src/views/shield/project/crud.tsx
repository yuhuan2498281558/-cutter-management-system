import * as api from './api';
import { UserPageQuery, AddReq, DelReq, EditReq, CreateCrudOptionsProps, CreateCrudOptionsRet } from '@fast-crud/fast-crud';
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
				project_id: {
					title: '项目编号',
					type: 'input',
					search: { show: true },
					column: { minWidth: 150 },
					form: {
						rules: [{ required: true, message: '请输入项目编号' }],
						component: { placeholder: '请输入项目编号' },
					},
				},
				project_name: {
					title: '项目名称',
					type: 'input',
					search: { show: true },
					column: { minWidth: 180 },
					form: {
						rules: [{ required: true, message: '请输入项目名称' }],
						component: { placeholder: '请输入项目名称' },
					},
				},
				location: {
					title: '所在地',
					type: 'input',
					column: { minWidth: 150 },
					form: {
						component: { placeholder: '请输入所在地' },
					},
				},
				excavation_diameter: {
					title: '开挖直径(m)',
					type: 'number',
					column: { minWidth: 120 },
					form: {
						component: { placeholder: '请输入开挖直径' },
					},
				},
				tunnel_length: {
					title: '隧洞长度(m)',
					type: 'number',
					column: { minWidth: 120 },
					form: {
						component: { placeholder: '请输入隧洞长度' },
					},
				},
				budget: {
					title: '预算金额(亿元)',
					type: 'number',
					column: { minWidth: 150 },
					form: {
						component: {
						placeholder: '请输入预算金额（单位：亿元）',
						step: 0.01,
					},
					},
				},
				estimated_time: {
					title: '预计完成时间',
					type: 'datetime',
					column: { minWidth: 160 },
					form: {
						component: {
							placeholder: '请选择预计完成时间',
							type: 'datetime',
							valueFormat: 'YYYY-MM-DD HH:mm:ss',
						},
					},
				},
				actual_time: {
					title: '实际完成时间',
					type: 'datetime',
					column: { minWidth: 160 },
					form: {
						component: {
							placeholder: '请选择实际完成时间',
							type: 'datetime',
							valueFormat: 'YYYY-MM-DD HH:mm:ss',
						},
					},
				},
				project_introduction: {
					title: '项目简介',
					type: 'textarea',
					column: {
						minWidth: 200,
						show: false,
					},
					form: {
						col: { span: 24 },
						component: {
							placeholder: '请输入项目简介',
							rows: 4,
						},
					},
				},
				create_datetime: {
					title: '创建时间',
					type: 'datetime',
					column: { minWidth: 160 },
					form: { show: false },
				},
			},
		},
	};
};
