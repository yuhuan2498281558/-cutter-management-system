import * as api from './api';
import { UserPageQuery, AddReq, DelReq, EditReq, CreateCrudOptionsProps, CreateCrudOptionsRet, dict, compute } from '@fast-crud/fast-crud';
import { createIndexFormatter } from '../crudUtils';
import { request } from '/@/utils/service';

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
					view: { show: false },
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
				tool_type: {
					title: '刀具类型',
					type: 'dict-select',
					search: { show: true },
					column: { minWidth: 120 },
					dict: dict({
						data: [
							{ label: '滚刀', value: 'DISC', color: 'primary' },
							{ label: '撕裂刀', value: 'RIPPER', color: 'success' },
							{ label: '刮刀', value: 'SCRAPER', color: 'warning' },
						],
					}),
					form: {
						rules: [{ required: true, message: '请选择刀具类型' }],
						component: {
							placeholder: '请选择刀具类型',
						},
					},
					component: { props: { color: 'auto' } },
				},
				tool_name: {
					title: '刀具名称',
					type: 'input',
					search: { show: true },
					column: { minWidth: 150 },
					form: {
						rules: [{ required: true, message: '请输入刀具名称' }],
						component: { placeholder: '请输入刀具名称' },
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
					},
				},
				tool_number: {
					title: '刀具编号',
					type: 'dict-select',
					search: { show: true },
					column: { minWidth: 120 },
					dict: dict({
						url: '/api/shield/tool_category/get_tool_numbers/',
						value: 'value',
						label: 'label',
						getData: async ({ url }: any) => {
							const res = await api.GetToolNumbers();
							// 将返回的数组转换为字典格式
							return res.data.map((item: any) => ({ value: item.value, label: item.label }));
						},
					}),
					form: {
						component: {
							placeholder: '请选择或输入刀具编号',
							filterable: true,
							allowCreate: true,
							defaultFirstOption: false,
						},
					},
				},
				cutter_position_no: {
					title: '刀位号',
					type: 'dict-select',
					search: { show: true },
					column: { minWidth: 120 },
					dict: dict({
						url: '/api/shield/tool_category/get_cutter_positions/',
						value: 'value',
						label: 'label',
						getData: async ({ url }: any) => {
							const res = await api.GetCutterPositions();
							// 后端已经返回了正确的格式 [{value, label}]
							return res.data;
						},
					}),
					form: {
						component: {
							placeholder: '请选择或输入刀位号',
							filterable: true,
							allowCreate: true,
							defaultFirstOption: false,
						},
					},
				},
				cost_records: {
					title: '刀具成本信息',
					type: 'table-select',
					column: { show: false },
					form: {
						title: '刀具成本信息',
						col: { span: 24 },
						component: {
							name: 'fs-table-select',
							vModel: 'modelValue',
							buildSelectRequest: ({ form }: any) => {
								return async () => {
									if (!form.id) return { data: [] };
									const res = await request({
										url: '/api/shield/tool_cost/',
										method: 'get',
										params: { tool_category: form.id, limit: 999 }
									});
									return res;
								};
							},
							createCrudOptions: () => {
								return {
									table: {
										border: true,
										stripe: true,
									},
									rowHandle: {
										width: 150,
										fixed: 'right',
										buttons: {
											view: { show: false },
											edit: { show: true, text: '编辑' },
											remove: { show: true, text: '删除' },
										},
									},
									columns: {
										cost_type: {
											title: '成本类型',
											type: 'dict-select',
											dict: dict({
												data: [
													{ label: '刀具换新', value: 'NEW_TOOL', color: 'primary' },
													{ label: '刀具维修', value: 'REPAIR', color: 'warning' },
												],
											}),
											form: {
												rules: [{ required: true, message: '请选择成本类型' }],
												component: { placeholder: '请选择成本类型' },
												valueChange: ({ value, form }: any) => {
													if (value === 'NEW_TOOL') {
														form.repair_parts = undefined;
													}
												},
											},
											component: { props: { color: 'auto' } },
										},
										repair_parts: {
											title: '维修部位',
											type: 'dict-select',
											dict: dict({
												data: [
													{ label: '刀圈', value: '刀圈' },
													{ label: '密封件', value: '密封件' },
													{ label: '轴承', value: '轴承' },
												],
											}),
											column: {
												formatter: ({ value }: any) => {
													if (!value || !Array.isArray(value) || value.length === 0) return '-';
													return value.join(', ');
												},
											},
											form: {
												rules: [
													{
														required: compute(({ form }) => form?.cost_type === 'REPAIR'),
														message: '请选择维修部位'
													}
												],
												component: {
													placeholder: '请先选择维修部位（可多选）',
													multiple: true,
												},
												show: compute(({ form }) => form?.cost_type === 'REPAIR'),
												order: 1,
											},
										},
										brand: {
											title: '刀具品牌',
											type: 'input',
											form: {
												component: { placeholder: '请输入刀具品牌' },
												order: 2,
											},
										},
										manufacturer: {
											title: '刀具厂商',
											type: 'input',
											form: {
												component: { placeholder: '请输入刀具厂商' },
												order: 3,
											},
										},
										unit_price: {
											title: '单价(元)',
											type: 'number',
											column: {
												formatter: ({ value }: any) => {
													if (value === null || value === undefined) return '-';
													return `¥${Number(value).toFixed(2)}`;
												},
											},
											form: {
												component: {
													placeholder: '请输入单价',
													min: 0,
													precision: 2,
												},
												order: 4,
											},
										},
										remark: {
											title: '备注',
											type: 'textarea',
											column: { show: false },
											form: {
												component: {
													placeholder: '请输入备注信息',
													rows: 2,
												},
												order: 5,
											},
										},
										create_datetime: {
											title: '创建时间',
											type: 'datetime',
											column: { width: 160 },
											form: { show: false },
										},
									},
								};
							},
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
