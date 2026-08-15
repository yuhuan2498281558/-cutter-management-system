import * as api from './api';
import { UserPageQuery, AddReq, DelReq, EditReq, CreateCrudOptionsProps, CreateCrudOptionsRet, dict, compute } from '@fast-crud/fast-crud';
import { createIndexFormatter } from '../crudUtils';
import { useRoute } from 'vue-router';

export const createCrudOptions = function ({ crudExpose }: CreateCrudOptionsProps): CreateCrudOptionsRet {
	const route = useRoute();
	const toolInfoId = route.query.tool_info_id as string;

	const pageRequest = async (query: UserPageQuery) => {
		query.tool_info = toolInfoId;
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
		form.tool_info = toolInfoId;
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
						text: '新增成本记录',
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
				cost_type: {
					title: '成本类型',
					type: 'dict-select',
					dict: dict({
						data: [
							{ label: '刀具换新', value: 'NEW_TOOL', color: 'primary' },
							{ label: '刀具维修', value: 'REPAIR', color: 'warning' },
						],
					}),
					column: { minWidth: 120 },
					form: {
						rules: [{ required: true, message: '请选择成本类型' }],
						component: {
							placeholder: '请选择成本类型',
						},
						valueChange: ({ value, form }: any) => {
							if (value === 'NEW_TOOL') {
								form.repair_parts = undefined;
							}
						},
						order: 0,
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
						minWidth: 150,
						formatter: ({ value }: any) => {
							if (!value || !Array.isArray(value) || value.length === 0) return '-';
							return value.join(', ');
						},
					},
					form: {
						rules: [
							{
								required: compute(({ form }) => form?.cost_type === 'REPAIR'),
								message: '请先选择维修部位'
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
					column: { minWidth: 120 },
					form: {
						component: {
							placeholder: '请输入刀具品牌',
						},
						order: 2,
					},
				},
				manufacturer: {
					title: '刀具厂商',
					type: 'input',
					column: { minWidth: 120 },
					form: {
						component: {
							placeholder: '请输入刀具厂商',
						},
						order: 3,
					},
				},
				unit_price: {
					title: '单价(元)',
					type: 'number',
					column: {
						minWidth: 120,
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
					column: { minWidth: 200 },
					form: {
						component: {
							placeholder: '请输入备注信息',
							rows: 3,
						},
						order: 5,
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
