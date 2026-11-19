<template>
	<div v-show="!showCount" ref="deptInfoRef" class="dept-user-com-box dept-info">
		<div class="di-left">
			<h3>{{ deptInfo.dept_name || '' }}</h3>
			<div class="di-cell">
				<p>部门负责人：</p>
				<p class="content">{{ deptInfo.owner || '无' }}</p>
			</div>
			<div class="di-cell">
				<p>部门人数：</p>
				<p class="content">{{ deptInfo.dept_user || 0 }}人</p>
			</div>
			<div class="di-cell">
				<p>部门简介：</p>
				<p class="content">{{ deptInfo.description || '无' }}</p>
			</div>
			<div class="di-cell">
				<p>显示子级：</p>
				<el-switch
					v-model="isShowChildFlag"
					inline-prompt
					active-text="是"
					inactive-text="否"
					:disabled="!currentDeptId"
					@change="handleSwitchChange"
					style="--el-switch-on-color: var(--el-color-primary)"
				/>
			</div>
		</div>
		<div v-show="infoWidth >= BAR_MIN_WIDTH" ref="deptCountBar" class="di-chart di-chart--bar"></div>
		<div v-show="infoWidth >= PIE_MIN_WIDTH" ref="deptSexPie" class="di-chart di-chart--pie"></div>
	</div>

	<fs-crud
		ref="crudRef"
		v-bind="crudBinding"
		:customClass="!showCount ? 'dept-user-com-box dept-user-com-table' : 'dept-user-com-box dept-user-com-table-cover'"
	>
		<template #toolbar-left>
			<el-button :icon="!showCount ? 'Hide' : 'View'" circle @click="showCount = !showCount"></el-button>
		</template>
		<template #actionbar-right>
			<importExcel api="api/system/user/" v-auth="'user:Import'">导入 </importExcel>
		</template>
	</fs-crud>

	<el-dialog v-model="resetPwdVisible" title="重设密码" width="400px" draggable :before-close="handleResetPwdClose">
		<div>
			<el-input v-model="resetPwdFormState.newPassword" type="password" placeholder="请输入密码" show-password style="margin-bottom: 20px" />
			<el-input v-model="resetPwdFormState.newPassword2" type="password" placeholder="请再次输入密码" show-password />
		</div>
		<template #footer>
			<span class="dialog-footer">
				<el-button @click="handleResetPwdClose">取消</el-button>
				<el-button type="primary" @click="handleResetPwdSubmit"> 保存 </el-button>
			</span>
		</template>
	</el-dialog>
</template>

<script lang="ts" setup name="user">
import { ref, reactive, onMounted, onBeforeUnmount, nextTick } from 'vue';
import { useExpose, useCrud } from '@fast-crud/fast-crud';
import { Md5 } from 'ts-md5';
import { createCrudOptions } from './crud';
import importExcel from '/@/components/importExcel/index.vue';
import { ECharts, EChartsOption, init } from 'echarts';
import { CHART_COLORS, DV_PALETTE } from '/@/views/shield/analysis/utils/chartTheme';
import { getDeptInfoById, resetPwd } from './api';
import { warningNotification, successNotification } from '/@/utils/message';
import { HeadDeptInfoType } from '../../types';

let deptCountChart: ECharts;
let deptSexChart: ECharts;
let chartResizeObserver: ResizeObserver | null = null;

// 部门信息区放不下时先收起柱状图，再窄就只留文字（柱状图至少约 260px 宽，饼图 200px）
const BAR_MIN_WIDTH = 720;
const PIE_MIN_WIDTH = 440;
const deptInfoRef = ref<HTMLElement>();
const infoWidth = ref(0);

// crud组件的ref
const crudRef = ref();
// crud 配置的ref
const crudBinding = ref();
// 暴露的方法
const { crudExpose } = useExpose({ crudRef, crudBinding });

let currentDeptId = ref('');
let deptCountBar = ref();
let deptSexPie = ref();
let isShowChildFlag = ref(false);
let deptInfo = ref<Partial<HeadDeptInfoType>>({});
let showCount = ref(false);

let resetPwdVisible = ref(false);
let resetPwdFormState = reactive({
	id: 0,
	newPassword: '',
	newPassword2: '',
});

/**
 * 初始化顶部部门折线图
 */
const initDeptCountBarChart = () => {
	const xAxisData = deptInfo.value.sub_dept_map?.map((item) => item.name) || [];
	const yAxisData = deptInfo.value.sub_dept_map?.map((item) => item.count) || [];

	const option: EChartsOption = {
		tooltip: {
			trigger: 'axis',
			axisPointer: {
				type: 'shadow',
			},
		},
		xAxis: {
			type: 'category',
			data: xAxisData,
			axisTick: {
				alignWithLabel: true,
			},
		},
		yAxis: {
			type: 'value',
		},
		dataZoom: [
			{
				type: 'inside',
			},
		],
		grid: {
			top: 12,
			right: 8,
			bottom: 4,
			left: 4,
			containLabel: true,
		},
		series: [
			{
				data: yAxisData,
				type: 'bar',
				barWidth: '60%',
				barMaxWidth: 32,
				itemStyle: {
					color: CHART_COLORS.primary,
					borderRadius: [3, 3, 0, 0],
				},
			},
		],
	};

	deptCountChart.setOption(option);
};

/**
 * 初始化顶部性别统计
 */
const initDeptSexPieChart = () => {
	const option: EChartsOption = {
		tooltip: {
			trigger: 'item',
		},
		legend: {
			orient: 'vertical',
			right: '0%',
			left: '65%',
			top: 'center',
			itemWidth: 12,
			itemHeight: 12,
		},
		series: [
			{
				type: 'pie',
				radius: '65%',
				center: ['32%', '50%'],
				label: {
					show: false,
					position: 'center',
				},
				color: [CHART_COLORS.primary, DV_PALETTE[6], CHART_COLORS.neutral],
				data: [
					{ value: deptInfo.value.gender?.male || 0, name: '男' },
					{ value: deptInfo.value.gender?.female || 0, name: '女' },
					{ value: deptInfo.value.gender?.unknown || 0, name: '未知' },
				],
			},
		],
	};
	deptSexChart.setOption(option);
};

/**
 * 获取顶部部门信息
 */
const getDeptInfo = async () => {
	const res = await getDeptInfoById(currentDeptId.value, isShowChildFlag.value ? '1' : '0');
	if (res?.code === 2000) {
		deptInfo.value = res.data;
		initDeptCountBarChart();
		initDeptSexPieChart();
	}
};

/**
 * 部门切换刷新用户列表
 */
const handleDoRefreshUser = (id: string) => {
	currentDeptId.value = id;
	crudExpose.doSearch({ form: { dept: id } });
	getDeptInfo();
};

const handleSwitchChange = () => {
	handleDoRefreshUser(currentDeptId.value);
};

const handleResetPwdOpen = ({ id }: { id: number }) => {
	resetPwdFormState.id = id;
	resetPwdVisible.value = true;
};
const handleResetPwdClose = () => {
	resetPwdVisible.value = false;
	resetPwdFormState.id = 0;
	resetPwdFormState.newPassword = '';
	resetPwdFormState.newPassword2 = '';
};
const handleResetPwdSubmit = async () => {
	if (!resetPwdFormState.id) {
		warningNotification('请选择用户！');
		return;
	}
	if (!resetPwdFormState.newPassword || !resetPwdFormState.newPassword2) {
		warningNotification('请输入密码！');
		return;
	}
	if (resetPwdFormState.newPassword !== resetPwdFormState.newPassword2) {
		warningNotification('两次输入密码不一致');
		return;
	}
	const pwdRegex = new RegExp('(?=.*[0-9])(?=.*[a-zA-Z]).{8,30}');
	if (!pwdRegex.test(resetPwdFormState.newPassword) || !pwdRegex.test(resetPwdFormState.newPassword2)) {
		warningNotification('您的密码复杂度太低(密码中必须包含字母、数字)');
		return;
	}
	const res = await resetPwd(resetPwdFormState.id, {
		newPassword: Md5.hashStr(resetPwdFormState.newPassword),
		newPassword2: Md5.hashStr(resetPwdFormState.newPassword2),
	});

	if (res?.code === 2000) {
		successNotification(res.msg || '修改成功！');
		handleResetPwdClose();
	}
};

onMounted(async () => {
	// 先按当前宽度定好显示哪些图，再初始化，免得在隐藏的元素上建图
	infoWidth.value = deptInfoRef.value?.clientWidth || 0;
	await nextTick();
	deptCountChart = init(deptCountBar.value as HTMLElement, 'dv');
	deptSexChart = init(deptSexPie.value as HTMLElement, 'dv');
	// 信息区变宽变窄（窗口缩放、侧栏收起、隐藏后再显示）时，按新宽度决定显示哪些图并重排；隐藏着的图不重排
	chartResizeObserver = new ResizeObserver(() => {
		infoWidth.value = deptInfoRef.value?.clientWidth || 0;
		[deptCountChart, deptSexChart].forEach((chart) => {
			if (chart.getDom().clientWidth) chart.resize();
		});
	});
	[deptInfoRef.value, deptCountBar.value, deptSexPie.value].forEach((el) => el && chartResizeObserver?.observe(el));
	getDeptInfo();
	crudExpose.doRefresh();
});

onBeforeUnmount(() => {
	chartResizeObserver?.disconnect();
	deptCountChart?.dispose();
	deptSexChart?.dispose();
});

defineExpose({
	handleDoRefreshUser,
});

// 你的crud配置
const { crudOptions } = createCrudOptions({ crudExpose, context: { getDeptInfo, isShowChildFlag, handleResetPwdOpen } });

// 初始化crud配置
const { resetCrudOptions } = useCrud({
	crudExpose,
	crudOptions,
	context: {},
});
</script>

<style lang="scss" scoped>
.dept-user-com-box {
	padding: 0 10px;
	border-radius: 8px 0 0 8px;
	box-sizing: border-box;
	background-color: #fff;
}
.dept-user-com-table {
	height: calc(100% - 200px);
}
.dept-user-com-table-cover {
	height: 100%;
}
// 左边文字固定宽，柱状图占剩下的宽度，饼图（带右侧图例）固定 200px
.dept-info {
	width: 100%;
	height: 200px;
	display: flex;
	align-items: center;
	gap: 16px;
	margin-bottom: 10px;

	.di-chart {
		height: 180px;
		min-width: 0;
	}

	.di-chart--bar {
		flex: 1 1 0;
	}

	.di-chart--pie {
		flex: 0 0 200px;
	}

	.di-left {
		flex: 0 0 210px;
		min-width: 0;

		h3 {
			font-size: 18px;
			font-weight: 900;
		}
		.di-cell {
			margin-top: 6px;
			display: flex;
			align-items: center;

			p:nth-child(1) {
				display: block;
				width: 85px;
				text-align: left;
			}
			.content {
				max-width: 120px;
				overflow: hidden;
				white-space: nowrap;
				text-overflow: ellipsis;
			}
		}
	}
}
</style>
