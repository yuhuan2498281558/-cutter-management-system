import * as api from './api';
import { UserPageQuery, AddReq, DelReq, EditReq, CreateCrudOptionsProps, CreateCrudOptionsRet, dict, compute } from '@fast-crud/fast-crud';
import { request } from '/@/utils/service';
import { ElMessage } from 'element-plus';
import { getAuthHeader } from '/@/utils/storage';
import { createIndexFormatter } from '../crudUtils';

export const createCrudOptions = function ({ crudExpose, warehouseId, shieldMachineId }: any): CreateCrudOptionsRet {
	const normalizeToolParentType = (value: any) => {
		const map: Record<string, string> = {
			滚刀: 'DISC',
			撕裂刀: 'RIPPER',
			刮刀: 'SCRAPER',
			DISC: 'DISC',
			RIPPER: 'RIPPER',
			SCRAPER: 'SCRAPER',
		};
		return map[String(value || '').trim()] || value;
	};

	const buildCostQuery = (form: any = {}) => ({
		shield_machine: shieldMachineId,
		cutter_position_no: form.cutter_position_no,
		tool_parent_type: normalizeToolParentType(form.tool_parent_type),
		replacement_type: form.replacement_type,
		manufacturer: form.manufacturer,
		brand: form.brand,
		repair_parts: Array.isArray(form.repair_parts) ? form.repair_parts.join(',') : form.repair_parts,
	});

	const getCostOptions = async (form: any = {}) => {
		const res = await api.GetCostOptions(buildCostQuery(form));
		return Array.isArray(res.data) ? res.data : [];
	};

	const uniqueCostOptions = (options: any[], field: 'manufacturer' | 'brand') => {
		const seen = new Set<string>();
		return options
			.filter((item) => item?.[field])
			.filter((item) => {
				const value = String(item[field]);
				if (seen.has(value)) return false;
				seen.add(value);
				return true;
			})
			.map((item) => ({
				...item,
				value: item[field],
				label: field === 'manufacturer'
					? `${item.manufacturer} / ${item.brand || '-'} / ${item.unit_price || 0}元`
					: `${item.brand} / ${item.manufacturer || '-'} / ${item.unit_price || 0}元`,
			}));
	};

	const getManufacturerOptions = async (form: any = {}) => {
		const options = await getCostOptions({ ...form, manufacturer: undefined });
		return uniqueCostOptions(options, 'manufacturer');
	};

	const getBrandOptions = async (form: any = {}) => {
		const options = await getCostOptions({ ...form, brand: undefined });
		return uniqueCostOptions(options, 'brand');
	};

	const applyMatchedCost = async (form: any, flags: { keepManufacturer?: boolean; keepBrand?: boolean } = {}) => {
		if (!form?.is_replaced || !form?.replacement_type) return;
		const costOptions = await getCostOptions(form);
		if (costOptions.length === 0) {
			form.price = undefined;
			if (!flags.keepBrand) form.brand = undefined;
			return;
		}
		if (costOptions.length > 1) return;
		const matched = costOptions[0];
		if (!flags.keepManufacturer) {
			form.manufacturer = matched.manufacturer;
		}
		if (!flags.keepBrand) {
			form.brand = matched.brand;
		}
		form.price = matched.price ?? matched.unit_price;
	};

	const pageRequest = async (query: UserPageQuery) => {
		try {
			const res = await api.GetList({
				...query,
				warehouse: warehouseId,
			});

			return {
				records: Array.isArray(res.data) ? res.data : [],
				total: Number(res.total) || 0,
				currentPage: Number(res.page) || 1,
				pageSize: Number(res.limit) || 20,
			};
		} catch {
			return {
				records: [],
				total: 0,
				currentPage: 1,
				pageSize: 20,
			};
		}
	};

	const editRequest = async ({ form, row }: EditReq) => {
		form.id = row.id;
		form.warehouse = warehouseId;
		return await api.UpdateObj(form);
	};

	const delRequest = async ({ row }: DelReq) => {
		return await api.DelObj(row.id);
	};

	const addRequest = async ({ form }: AddReq) => {
		form.warehouse = warehouseId;
		return await api.AddObj(form);
	};

	return {
		crudOptions: {
			table: {
				height: 1200,
			},
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
						text: '新增换刀记录',
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
						type: 'primary',
						link: true,
					},
					remove: {
						show: true,
						text: '删除',
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
				warehouse_id_name: {
					title: '开仓编号',
					type: 'text',
					form: { show: false },
					column: { minWidth: 120, show: true },
				},
				tool_parent_type: {
					title: '刀具父类型',
					type: 'dict-select',
					dict: dict({
						data: [
							{ label: '滚刀', value: 'DISC' },
							{ label: '撕裂刀', value: 'RIPPER' },
							{ label: '刮刀', value: 'SCRAPER' },
						],
					}),
					column: { minWidth: 120 },
					form: {
						rules: [{ required: true, message: '请选择刀具父类型' }],
						component: {
							placeholder: '请选择刀具父类型',
						},
						valueChange: ({ form }: any) => {
							applyMatchedCost(form);
						},
						order: 1,
					},
				},
				cutter_position_no: {
					title: '刀位号',
					type: 'text',
					column: { minWidth: 100 },
					form: {
						rules: [{ required: true, message: '请输入刀位号' }],
						component: {
							placeholder: '请输入刀位号（如：1-1）',
						},
						order: 2,
					},
				},
				tool_number: {
					title: '刀具编号',
					type: 'input',
					column: { minWidth: 120 },
					form: {
						rules: [{ required: true, message: '请输入刀具编号' }],
						component: {
							placeholder: '请输入当前刀具编号',
						},
						order: 3,
					},
				},
				wear_condition: {
					title: '磨损情况',
					type: 'dict-select',
					dict: dict({
						data: [
							{ label: '良好', value: 'GOOD' },
							{ label: '正常磨损', value: 'NORMAL' },
							{ label: '中度磨损', value: 'MODERATE' },
							{ label: '严重磨损', value: 'SEVERE' },
							{ label: '异常磨损', value: 'ABNORMAL' },
						],
					}),
					column: { minWidth: 120 },
					form: {
						rules: [{ required: true, message: '请选择磨损情况' }],
						component: {
							placeholder: '请选择磨损情况',
						},
						order: 4,
					},
				},
				is_replaced: {
					title: '是否更换',
					type: 'dict-switch',
					dict: dict({
						data: [
							{ label: '是', value: true },
							{ label: '否', value: false },
						],
					}),
					column: {
						minWidth: 100,
						component: {
							name: 'el-switch',
							activeText: '是',
							inactiveText: '否',
							disabled: true,
						},
					},
					form: {
						value: false,
						rules: [{ required: true, message: '请选择是否更换' }],
						component: {
							activeText: '是',
							inactiveText: '否',
						},
						valueChange: ({ value, form }: any) => {
							// 如果不更换，清空更换相关字段
							if (!value) {
								form.replacement_type = undefined;
								form.repair_parts = undefined;
								form.manufacturer = undefined;
								form.brand = undefined;
								form.price = undefined;
							}
						},
						order: 5,
					},
				},
				replacement_count: {
					title: '累计更换次数',
					type: 'number',
					form: { show: false },
					column: {
						minWidth: 120,
						align: 'center',
					},
				},
				manufacturer: {
					title: '厂家',
					type: 'dict-select',
					dict: dict({
						value: 'value',
						label: 'label',
						getData: async ({ form }: any) => {
							return await getManufacturerOptions(form);
						},
					}),
					column: { minWidth: 120 },
					form: {
						rules: [
							{
								required: compute(({ form }) => form?.is_replaced === true),
								message: '请选择厂家'
							}
						],
						component: {
							placeholder: '请选择成本库中的厂家',
							filterable: true,
							allowCreate: false,
						},
						show: compute(({ form }) => form?.is_replaced === true),
						valueChange: ({ form }: any) => {
							form.brand = undefined;
							form.price = undefined;
							applyMatchedCost(form, { keepManufacturer: true });
						},
						order: 6,
					},
				},
				replacement_type: {
					title: '更换类型',
					type: 'dict-select',
					dict: dict({
						data: [
							{ label: '整刀更换', value: 'COMPLETE' },
							{ label: '维修', value: 'REPAIR' },
						],
					}),
					column: { minWidth: 120 },
					form: {
						rules: [
							{
								required: compute(({ form }) => form?.is_replaced === true),
								message: '请选择更换类型'
							}
						],
						component: {
							placeholder: '请选择更换类型',
						},
						show: compute(({ form }) => form?.is_replaced === true),
						valueChange: ({ value, form }: any) => {
							// 切换更换类型时清空对应字段
							if (value === 'COMPLETE') {
								form.repair_parts = undefined;
							}
							form.manufacturer = undefined;
							form.brand = undefined;
							form.price = undefined;
							applyMatchedCost(form);
						},
						order: 7,
					},
				},
				repair_parts: {
					title: '维修部位',
					type: 'dict-select',
					dict: dict({
						data: [
							{ label: '密封件', value: '密封件' },
							{ label: '轴承', value: '轴承' },
							{ label: '刀圈', value: '刀圈' },
						],
					}),
					column: {
						minWidth: 150,
						formatter: (context: any) => {
							const value = context.value;
							if (Array.isArray(value)) {
								return value.join('、');
							}
							return value || '-';
						},
					},
					form: {
						rules: [
							{
								required: compute(({ form }) => form?.is_replaced === true && form?.replacement_type === 'REPAIR'),
								message: '请选择维修部位'
							}
						],
						component: {
							placeholder: '请选择维修部位（可多选）',
							multiple: true,
						},
						show: compute(({ form }) => form?.is_replaced === true && form?.replacement_type === 'REPAIR'),
						valueChange: ({ form }: any) => {
							form.manufacturer = undefined;
							form.brand = undefined;
							form.price = undefined;
							applyMatchedCost(form);
						},
						order: 8,
					},
				},
				brand: {
					title: '品牌',
					type: 'dict-select',
					dict: dict({
						value: 'value',
						label: 'label',
						getData: async ({ form }: any) => {
							return await getBrandOptions(form);
						},
					}),
					column: { minWidth: 120 },
					form: {
						rules: [
							{
								required: compute(({ form }) => form?.is_replaced === true),
								message: '请选择品牌'
							}
						],
						component: {
							placeholder: '请选择成本库中的品牌',
							filterable: true,
							allowCreate: false,
						},
						show: compute(({ form }) => form?.is_replaced === true),
						valueChange: ({ form }: any) => {
							form.price = undefined;
							applyMatchedCost(form, { keepManufacturer: true, keepBrand: true });
						},
						order: 9,
					},
				},
				price: {
					title: '价格',
					type: 'number',
					column: {
						minWidth: 120,
						align: 'right',
						formatter: (context: any) => {
							const value = context.value;
							if (value !== null && value !== undefined) {
								return `¥${Number(value).toFixed(2)}`;
							}
							return '-';
						},
					},
					form: {
						rules: [
							{
								required: compute(({ form }) => form?.is_replaced === true),
								message: '请输入价格'
							}
						],
						component: {
							placeholder: '成本库自动带出价格',
							min: 0,
							precision: 2,
						},
						show: compute(({ form }) => form?.is_replaced === true),
						order: 10,
					},
				},
				wear_image: {
					title: '刀具磨损更换图',
					type: 'image-uploader',
					column: {
						minWidth: 150,
						component: {
							name: 'fs-images-format',
						},
					},
					form: {
						component: {
							uploader: {
								type: 'form',
								action: '/api/system/file/upload/',
								name: 'file',
								headers: {
									get Authorization() { return getAuthHeader().Authorization; },
								},
								data: {
									object_id: warehouseId,
								},
								buildUrl: (res: any) => {
									return res.data?.url || res.data?.file_url;
								},
							},
							placeholder: '点击上传图片',
						},
						order: 11,
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
						order: 12,
					},
				},
				create_datetime: {
					title: '创建时间',
					type: 'datetime',
					form: { show: false },
					column: { minWidth: 160 },
				},
			},
		},
	};
};
