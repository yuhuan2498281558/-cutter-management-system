import * as api from './api';
import { apiPrefix } from './api';
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
				warehouse: {
					title: '开仓编号',
					type: 'dict-select',
					column: { show: false },
					dict: dict({
						url: '/api/shield/warehouse_opening/',
						label: 'warehouse_id',
						value: 'id',
					}),
					form: {
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
				replace_part: {
					title: '更换部位',
					type: 'dict-select',
					search: { show: true },
					column: { minWidth: 120 },
					dict: dict({
						data: [
							{ label: '密封件', value: 'SEAL' },
							{ label: '轴承', value: 'BEARING' },
							{ label: '刀具', value: 'TOOL' },
						],
					}),
					form: {
						order: 1,
						rules: [{ required: true, message: '请选择更换部位' }],
						component: {
							placeholder: '请选择更换部位',
						},
					},
					valueChange({ value, form }: any) {
						// 当选择密封件或轴承时，清空刀具相关字段
						if (value !== 'TOOL') {
							form.is_replaced = false;
							form.old_tool = null;
							form.old_tool_number = '';
							form.new_tool = null;
						}
					},
				},
				is_replaced: {
					title: '是否换刀',
					type: 'dict-switch',
					column: { minWidth: 100, show: true },
					dict: dict({
						data: [
							{ label: '是', value: true },
							{ label: '否', value: false },
						],
					}),
					form: {
						order: 2,
						value: false,
						show: ({ form }: any) => {
							// 只有选择"刀具"时才显示
							return form.replace_part === 'TOOL';
						},
						component: {
							activeText: '是',
							inactiveText: '否',
						},
					},
				},
				old_tool: {
					title: '旧刀具',
					type: 'dict-select',
					column: { show: false },
					dict: dict({
						url: '/api/shield/tool_info/',
						label: 'tool_name',
						value: 'id',
					}),
					form: {
						order: 3,
						show: ({ form }: any) => {
							// 只有选择"刀具"时才显示
							return form.replace_part === 'TOOL';
						},
						component: {
							placeholder: '请选择旧刀具',
							filterable: true,
						},
					},
				},
				old_tool_name: {
					title: '旧刀具名称',
					type: 'text',
					form: { show: false },
					column: { show: true, minWidth: 150 },
				},
				old_tool_number: {
					title: '旧刀具编号',
					type: 'dict-select',
					search: { show: true },
					column: { minWidth: 120, show: true },
					dict: dict({
						url: apiPrefix + 'get_tool_numbers/',
						value: 'label',  // 使用刀具编号作为值
						label: 'label',  // 使用刀具编号作为显示标签
					}),
					form: {
						order: 4,
						show: ({ form }: any) => {
							// 只有选择"刀具"时才显示
							return form.replace_part === 'TOOL';
						},
						component: {
							placeholder: '请选择或输入刀具编号',
							filterable: true,      // 支持搜索过滤
							allowCreate: true,     // 支持手动输入新值
							defaultFirstOption: false,  // 不默认选择第一项
						},
					},
				},
				new_tool: {
					title: '新刀具',
					type: 'dict-select',
					column: { show: false },
					dict: dict({
						url: '/api/shield/tool_info/',
						label: 'tool_name',
						value: 'id',
					}),
					form: {
						order: 5,
						show: ({ form }: any) => {
							// 只有选择"刀具"时才显示
							return form.replace_part === 'TOOL';
						},
						component: {
							placeholder: '请选择新刀具',
							filterable: true,
						},
					},
				},
				new_tool_name: {
					title: '新刀具名称',
					type: 'text',
					form: { show: false },
					column: { show: true, minWidth: 150 },
				},
				new_tool_number: {
					title: '新刀具编号',
					type: 'dict-select',
					search: { show: true },
					column: { minWidth: 120, show: true },
					dict: dict({
						url: apiPrefix + 'get_tool_numbers/',
						value: 'label',  // 使用刀具编号作为值
						label: 'label',  // 使用刀具编号作为显示标签
					}),
					form: {
						order: 6,
						show: ({ form }: any) => {
							// 只有选择"刀具"时才显示
							return form.replace_part === 'TOOL';
						},
						component: {
							placeholder: '请选择或输入刀具编号',
							filterable: true,      // 支持搜索过滤
							allowCreate: true,     // 支持手动输入新值
							defaultFirstOption: false,  // 不默认选择第一项
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
