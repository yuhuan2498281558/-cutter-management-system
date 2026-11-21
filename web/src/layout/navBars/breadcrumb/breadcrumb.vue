<template>
	<div v-if="isShowBreadcrumb" class="layout-navbars-breadcrumb">
		<button type="button" class="layout-navbars-breadcrumb-icon" @click="onThemeConfigChange">
			<SvgIcon :name="themeConfig.isCollapse ? 'ele-Expand' : 'ele-Fold'" :size="16" />
		</button>
		<el-breadcrumb class="layout-navbars-breadcrumb-hide" :separator-icon="ArrowRight">
			<el-breadcrumb-item v-for="(v, k) in state.breadcrumbList" :key="!v.meta.tagsViewName ? v.meta.title : v.meta.tagsViewName">
				<span v-if="k === state.breadcrumbList.length - 1" class="layout-navbars-breadcrumb-span">
					<SvgIcon :name="v.meta.icon" :size="16" class="layout-navbars-breadcrumb-iconfont" v-if="themeConfig.isBreadcrumbIcon" />
					<div v-if="!v.meta.tagsViewName">{{ $t(v.meta.title) }}</div>
					<div v-else>{{ v.meta.tagsViewName }}</div>
				</span>
				<a v-else @click.prevent="onBreadcrumbClick(v)">
					<SvgIcon :name="v.meta.icon" :size="16" class="layout-navbars-breadcrumb-iconfont" v-if="themeConfig.isBreadcrumbIcon" />{{ $t(v.meta.title) }}
				</a>
			</el-breadcrumb-item>
		</el-breadcrumb>
	</div>
</template>

<script setup lang="ts" name="layoutBreadcrumb">
import { reactive, computed, onMounted } from 'vue';
import { onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router';
import { ArrowRight } from '@element-plus/icons-vue';
import { Local } from '/@/utils/storage';
import other from '/@/utils/other';
import { storeToRefs } from 'pinia';
import { useThemeConfig } from '/@/stores/themeConfig';
import { useRoutesList } from '/@/stores/routesList';

// 定义变量内容
const stores = useRoutesList();
const storesThemeConfig = useThemeConfig();
const { themeConfig } = storeToRefs(storesThemeConfig);
const { routesList } = storeToRefs(stores);
const route = useRoute();
const router = useRouter();
const state = reactive<BreadcrumbState>({
	breadcrumbList: [],
	routeSplit: [],
	routeSplitFirst: '',
	routeSplitIndex: 1,
});

// 动态设置经典、横向布局不显示
const isShowBreadcrumb = computed(() => {
	initRouteSplit(route.path);
	const { layout, isBreadcrumb } = themeConfig.value;
	if (layout === 'classic' || layout === 'transverse') return false;
	else return isBreadcrumb ? true : false;
});
// 面包屑点击时
const onBreadcrumbClick = (v: RouteItem) => {
	const { redirect, path } = v;
	if (redirect) router.push(redirect);
	else router.push(path);
};
// 展开/收起左侧菜单点击
const onThemeConfigChange = () => {
	themeConfig.value.isCollapse = !themeConfig.value.isCollapse;
	setLocalThemeConfig();
};
// 存储布局配置
const setLocalThemeConfig = () => {
	Local.remove('themeConfig');
	Local.set('themeConfig', themeConfig.value);
};
// 处理面包屑数据
const getBreadcrumbList = (arr: RouteItems) => {
	arr.forEach((item: RouteItem) => {
		state.routeSplit.forEach((v: string, k: number, arrs: string[]) => {
			if (state.routeSplitFirst === item.path) {
				state.routeSplitFirst += `/${arrs[state.routeSplitIndex]}`;
				state.breadcrumbList.push(item);
				state.routeSplitIndex++;
				if (item.children) getBreadcrumbList(item.children);
			}
		});
	});
};
// 当前路由字符串切割成数组，并删除第一项空内容
const initRouteSplit = (path: string) => {
	if (!themeConfig.value.isBreadcrumb) return false;
	state.breadcrumbList = [routesList.value[0]];
	state.routeSplit = path.split('/');
	state.routeSplit.shift();
	state.routeSplitFirst = `/${state.routeSplit[0]}`;
	state.routeSplitIndex = 1;
	getBreadcrumbList(routesList.value);
	if (route.name === 'home' || (route.name === 'notFound' && state.breadcrumbList.length > 1)) state.breadcrumbList.shift();
	if (state.breadcrumbList.length > 0)
		state.breadcrumbList[state.breadcrumbList.length - 1].meta.tagsViewName = other.setTagsViewNameI18n(<RouteToFrom>route);
};
// 页面加载时
onMounted(() => {
	initRouteSplit(route.path);
});
// 路由更新时
onBeforeRouteUpdate((to) => {
	initRouteSplit(to.path);
});
</script>

<style scoped lang="scss">
.layout-navbars-breadcrumb {
	flex: 1;
	min-width: 0;
	height: inherit;
	display: flex;
	align-items: center;
	gap: 6px;
	// 收起/展开菜单：34px 圆角图标按钮，与顶栏右侧工具图标同样式
	.layout-navbars-breadcrumb-icon {
		width: 34px;
		height: 34px;
		flex: none;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0;
		border: 0;
		border-radius: var(--dv-radius);
		background: transparent;
		color: var(--next-bg-topBarColor);
		cursor: pointer;
		transition: background-color 0.15s, color 0.15s;
		&:hover {
			background: var(--dv-hover);
			color: var(--dv-text);
		}
	}
	// 图标和文字的大小与侧栏菜单一致（图标 16px、文字 14px），整行 20px 行高、上下居中：
	// 原来文字 13px、行高也压到 13px，图标 14px，几样东西各自的中线对不齐
	:deep(.el-breadcrumb) {
		display: flex;
		align-items: center;
		font-size: 14px;
		line-height: 20px;
		white-space: nowrap;
	}
	:deep(.el-breadcrumb__item),
	:deep(.el-breadcrumb__inner) {
		display: inline-flex;
		align-items: center;
	}
	// 当前页用正文色，前面的层级用顶栏文字色（默认是次要文字色）
	.layout-navbars-breadcrumb-span {
		display: flex;
		align-items: center;
		color: var(--el-text-color-primary);
		font-weight: 500;
	}
	.layout-navbars-breadcrumb-iconfont {
		flex: none;
		width: 16px;
		margin-right: 6px;
		line-height: 1;
		text-align: center;
	}
	// 分隔：14px 右箭头
	:deep(.el-breadcrumb__separator) {
		margin: 0 6px;
		font-size: 14px;
		color: var(--dv-text-muted);
	}
	:deep(.el-breadcrumb__inner a, .el-breadcrumb__inner.is-link) {
		font-weight: unset !important;
		color: var(--next-bg-topBarColor);
		&:hover {
			color: var(--el-text-color-primary) !important;
		}
	}
}
</style>
