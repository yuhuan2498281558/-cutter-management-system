import * as api from './api';
import { UserPageQuery, AddReq, DelReq, EditReq, CreateCrudOptionsProps, CreateCrudOptionsRet, dict } from '@fast-crud/fast-crud';
import { createIndexFormatter } from '../crudUtils';
import { request } from '/@/utils/service';
import { useRouter } from 'vue-router';

export const createCrudOptions = function ({ crudExpose }: CreateCrudOptionsProps): CreateCrudOptionsRet {
	const router = useRouter();
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
				width: 280,
				buttons: {
					view: { show: false },
					edit: {
						show: true,
						text: '编辑',
						iconRight: 'Edit',
						type: 'primary',
						link: true,
					},
					costInfo: {
						text: '成本信息',
						type: 'success',
						link: true,
						iconRight: 'Money',
						click: ({ row }: any) => {
							router.push({
								path: '/shield/toolCost',
								query: {
									tool_info_id: row.id,
									tool_info_name: row.tool_type_name,
									tool_number: row.tool_number,
								},
							});
						},
					},
					remove: {
						show: true,
						text: '删除',
						iconRight: 'Delete',
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
						formatter: createIndexFormatter(crudExpose),
					},
				},
				tool_parent_type: {
					title: '刀具父类型',
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
							// 显示时转换为中文
							const typeMap: any = {
								'DISC': '滚刀',
								'RIPPER': '撕裂刀',
								'SCRAPER': '刮刀',
							};
							const value = context.row?.tool_parent_type;
							return typeMap[value] || value;
						},
					},
					form: {
						rules: [{ required: true, message: '请选择刀具父类型' }],
						component: {
							placeholder: '请选择刀具父类型',
						},
						order: 1,
					},
				},
				tool_type_name: {
					title: '刀具类型名称',
					type: 'input',
					search: { show: true },
					column: { show: true, minWidth: 120 },
					form: {
						rules: [{ required: true, message: '请输入刀具类型名称' }],
						component: {
							placeholder: '请输入刀具类型名称（如：型号、规格等）',
						},
						order: 2,
					},
				},
				tool_type_code: {
					title: '刀具类型编号',
					type: 'text',
					search: { show: true },
					form: { show: false },
					column: {
						show: true,
						minWidth: 120,
						formatter: (context: any) => {
							const value = context.row?.tool_type_code;
							if (value) {
								return value;
							}
							return '自动生成';
						},
					},
				},
				shield_machine: {
					title: '所属盾构机',
					type: 'dict-select',
					column: { minWidth: 150 },
					dict: dict({
						url: '/api/shield/shield_machine_basic_info/',
						label: 'shield_model',
						value: 'id',
					}),
					form: {
						component: {
							placeholder: '请选择所属盾构机',
							filterable: true,
						},
						wrapper: {
							onOpened: async ({ mode, form }: any) => {
								if (mode === 'add') {
									try {
										const res = await request({
											url: '/api/shield/shield_machine_basic_info/',
											method: 'get',
											params: { page: 1, limit: 1, ordering: '-id' }
										});
										if (res.data && res.data.length > 0) {
											setTimeout(() => {
												form.shield_machine = res.data[0].id;
											}, 100);
										}
									} catch (error) {
										console.error('获取默认盾构机失败:', error);
									}
								}
							},
						},
						order: 3,
					},
				},
				remark: {
					title: '备注',
					type: 'textarea',
					column: { show: false },
					form: {
						col: { span: 24 },
						component: {
							placeholder: '请输入备注信息',
							rows: 3,
						},
						order: 4,
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
