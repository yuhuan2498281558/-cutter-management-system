import * as api from './api';
import { UserPageQuery, AddReq, EditReq, CreateCrudOptionsRet, dict } from '@fast-crud/fast-crud';
import { useRouter } from 'vue-router';
import AutoStratumDisplay from './AutoStratumDisplay.vue';
import { createIndexFormatter } from '../crudUtils';

export const createCrudOptions = function ({ crudExpose }: any): CreateCrudOptionsRet {
	const router = useRouter();

	const pageRequest = async (query: UserPageQuery) => {
		return await api.GetList(query);
	};
	const editRequest = async ({ form, row }: EditReq) => {
		form.id = row.id;
		return await api.UpdateObj(form);
	};
	const delRequest = async ({ row }: any) => {
		return await api.DelObj(row.id);
	};
	const addRequest = async ({ form }: AddReq) => {
		return await api.AddObj(form);
	};

	let previewTimer: ReturnType<typeof setTimeout> | undefined;
	let previewRequestId = 0;
	const clearAutoStratum = (form: any) => {
		form.last_ring_no = undefined;
		form.rings_between_openings = undefined;
		form.stratum_info_between_list = [];
		form.geological_conditions = '';
	};
	const queueAutoStratumPreview = (form: any) => {
		if (previewTimer) clearTimeout(previewTimer);
		const project = form?.project;
		const ringNo = form?.ring_no;
		if (!project || ringNo === undefined || ringNo === null || String(ringNo).trim() === '') {
			previewRequestId += 1;
			clearAutoStratum(form);
			return;
		}
		const requestId = ++previewRequestId;
		previewTimer = setTimeout(async () => {
			try {
				const response = await api.GetAutoStratumPreview({
					project,
					ring_no: ringNo,
					shield_model: form.shield_model || undefined,
					opening_id: form.id || undefined,
				});
				if (requestId !== previewRequestId) return;
				const data = response.data as api.OpeningStratumPreview;
				form.last_ring_no = data.last_ring_no || undefined;
				form.rings_between_openings = data.rings_between_openings;
				form.stratum_info_between_list = data.stratum_info_between_list || [];
				form.geological_conditions = data.geological_conditions || '';
			} catch {
				if (requestId === previewRequestId) clearAutoStratum(form);
			}
		}, 280);
	};

	// 跳转到换刀明细页面
	const goToToolChangeDetail = (row: any) => {
		router.push({
			path: '/shield/toolChangeDetail',
			query: {
				warehouse_id: row.id,
				warehouse_code: row.warehouse_id,
			},
		});
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
				width: 360,
				buttons: {
					view: { show: false },
					edit: {
						show: true,
						text: '编辑',
						iconRight: 'Edit',
						type: 'primary',
						link: true,
					},
					remove: {
						show: true,
						text: '删除',
						iconRight: 'Delete',
						type: 'danger',
						link: true,
					},
					toolChangeDetail: {
						text: '换刀明细',
						type: 'success',
						link: true,
						iconRight: 'List',
						click: ({ row }: any) => {
							goToToolChangeDetail(row);
						},
					},
				},
			},
			form: {
				col: { span: 12 },
				labelWidth: '156px',
				row: { gutter: 20 },
				wrapper: {
					is: 'el-dialog',
					width: '980px',
					onOpened: ({ form }: any) => queueAutoStratumPreview(form),
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
				ring_no: {
					title: '换刀环号',
					type: 'input',
					search: { show: true },
					column: { minWidth: 120, sortable: true },
					form: {
						rules: [{ required: true, message: '请输入换刀环号' }],
						component: { placeholder: '请输入换刀环号' },
						valueChange: ({ form }: any) => queueAutoStratumPreview(form),
						order: 2,
					},
				},
				project: {
					title: '项目',
					type: 'dict-select',
					column: { show: false },
					dict: dict({
						url: '/api/shield/project/',
						label: 'project_id',
						value: 'id',
					}),
					form: {
						rules: [{ required: true, message: '请选择项目' }],
						value: undefined,
						component: {
							placeholder: '请选择项目',
							filterable: true,
						},
						valueChange: ({ form }: any) => queueAutoStratumPreview(form),
						order: 0,
					},
				},
				project_name: {
					title: '项目名称',
					type: 'text',
					form: { show: false },
					column: { show: true, minWidth: 150 },
				},
				open_time: {
					title: '开仓时间',
					type: 'datetime',
					column: { minWidth: 160, sortable: true },
					form: {
						rules: [{ required: true, message: '请选择开仓日期' }],
						component: {
							placeholder: '请选择开仓日期',
							type: 'datetime',
							valueFormat: 'YYYY-MM-DD HH:mm:ss',
						},
						order: 3,
					},
				},
				section: {
					title: '区间',
					type: 'input',
					column: { minWidth: 120 },
					form: {
						component: { placeholder: '请输入区间' },
						order: 4,
					},
				},
				tool_change_date: {
					title: '换刀日期',
					type: 'date',
					column: { minWidth: 130 },
					form: {
						component: { placeholder: '请选择换刀日期', valueFormat: 'YYYY-MM-DD' },
						order: 5,
					},
				},
				shield_model: {
					title: '盾构机编号',
					type: 'dict-select',
					column: { show: false },
					dict: dict({
						url: '/api/shield/shield_machine_basic_info/',
						label: 'shield_model',
						value: 'id',
					}),
					form: {
						value: undefined,
						component: {
							placeholder: '请选择盾构机编号（可选）',
							filterable: true,
						},
						valueChange: ({ form }: any) => queueAutoStratumPreview(form),
						order: 1,
					},
				},
				shield_model_name: {
					title: '盾构机型号',
					type: 'text',
					form: { show: false },
					column: { show: true, minWidth: 150 },
				},
				opening_duration: {
					title: '持续开仓时间（小时）',
					type: 'number',
					column: { minWidth: 140 },
					form: {
						component: {
							placeholder: '请输入持续开仓时间（小时）',
							min: 0,
							precision: 2,
						},
						order: 6,
					},
				},
				tool_change_duration: {
					title: '换刀总时长（小时）',
					type: 'number',
					column: { minWidth: 140 },
					form: {
						component: { placeholder: '请输入换刀总时长（小时）', min: 0, precision: 2 },
						order: 7,
					},
				},
				usage_distance: {
					title: '本次使用距离（m）',
					type: 'number',
					column: { minWidth: 130 },
					form: {
						component: { placeholder: '请输入本次使用距离（m）', min: 0, precision: 2 },
						order: 8,
					},
				},
				checked_tool_count: {
					title: '检查刀具数量（把）',
					type: 'number',
					column: { minWidth: 130 },
					form: {
						component: {
							placeholder: '请输入检查刀具数量（把）',
							min: 0,
							precision: 0,
						},
						order: 9,
					},
				},
				replaced_tool_count: {
					title: '更换刀具数量（把）',
					type: 'number',
					column: { minWidth: 130 },
					form: {
						component: {
							placeholder: '请输入更换刀具数量（把）',
							min: 0,
							precision: 0,
						},
						order: 10,
					},
				},
				last_ring_no: {
					title: '上次换刀环号',
					type: 'text',
					column: { minWidth: 120 },
					form: {
						show: true,
						component: {
							disabled: true,
							placeholder: '自动获取（第一次开仓为空）',
						},
						order: 11,
					},
				},
				rings_between_openings: {
					title: '期间掘进环数（环）',
					type: 'number',
					column: { minWidth: 120 },
					form: {
						show: true,
						component: {
							disabled: true,
							placeholder: '自动计算',
						},
						order: 12,
					},
				},
				stratum_info_between_list: {
					title: '两次开仓间地层信息',
					type: 'text',
					column: {
						show: true,
						minWidth: 200,
						formatter: (context) => {
							const list = context.value || [];
							if (list.length === 0) return '-';
							return list.map((item: any) => `${item.stratum_type_name}(${item.ring_count}环)`).join('、');
						},
					},
					form: {
						show: true,
						order: 13,
						component: {
							name: AutoStratumDisplay,
							kind: 'between',
						},
					},
				},
				geological_conditions: {
					title: '开仓位置地层信息',
					type: 'text',
					column: {
						show: true,
						minWidth: 200,
					},
					form: {
						show: true,
						component: {
							name: AutoStratumDisplay,
							kind: 'position',
						},
						order: 14,
					},
				},
				warehouse_id: {
					title: '开仓编号',
					type: 'input',
					search: { show: true },
					column: { minWidth: 150, sortable: true },
					form: {
						show: true,
						component: {
							disabled: true,
							placeholder: '系统自动生成',
						},
						order: 15,
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
