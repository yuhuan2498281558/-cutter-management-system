<template>
	<div class="h100" v-show="!isTagsViewCurrenFull">
		<el-aside class="layout-aside" :class="[setCollapseStyle, { 'layout-aside-panel': isPanel, 'is-collapse': isPanelCollapse }]">
			<Logo v-if="setShowLogo" />
			<!-- 侧边栏布局：侧栏依次是 Logo、菜单搜索、菜单、最近打开、用户 -->
			<button v-if="isPanel" type="button" class="layout-aside-search" @click="onSearchClick">
				<el-icon :size="16"><ele-Search /></el-icon>
				<span>搜索菜单</span>
			</button>
			<el-scrollbar class="flex-auto" ref="layoutAsideScrollbarRef" @mouseenter="onAsideEnterLeave(true)" @mouseleave="onAsideEnterLeave(false)">
				<Vertical :menuList="state.menuList" />
				<AsideRecent v-if="isPanel && !isPanelCollapse" />
			</el-scrollbar>
			<AsideUser v-if="isPanel" />
			<Search v-if="isPanel" ref="searchRef" />
		</el-aside>
	</div>
</template>

<script setup lang="ts" name="layoutAside">
import { defineAsyncComponent, reactive, computed, watch, onBeforeMount, ref } from 'vue';
import { storeToRefs } from 'pinia';
import pinia from '/@/stores/index';
import { useRoutesList } from '/@/stores/routesList';
import { useThemeConfig } from '/@/stores/themeConfig';
import { useTagsViewRoutes } from '/@/stores/tagsViewRoutes';
import mittBus from '/@/utils/mitt';

// 引入组件
const Logo = defineAsyncComponent(() => import('/@/layout/logo/index.vue'));
const Vertical = defineAsyncComponent(() => import('/@/layout/navMenu/vertical.vue'));
const AsideRecent = defineAsyncComponent(() => import('/@/layout/component/asideRecent.vue'));
const AsideUser = defineAsyncComponent(() => import('/@/layout/component/asideUser.vue'));
const Search = defineAsyncComponent(() => import('/@/layout/navBars/breadcrumb/search.vue'));

// 定义变量内容
const layoutAsideScrollbarRef = ref();
const searchRef = ref();
const stores = useRoutesList();
const storesThemeConfig = useThemeConfig();
const storesTagsViewRoutes = useTagsViewRoutes();
const { routesList } = storeToRefs(stores);
const { themeConfig } = storeToRefs(storesThemeConfig);
const { isTagsViewCurrenFull } = storeToRefs(storesTagsViewRoutes);
const state = reactive<AsideState>({
	menuList: [],
	clientWidth: 0,
});

// 设置菜单展开/收起时的宽度
const setCollapseStyle = computed(() => {
	const { layout, isCollapse, menuBar } = themeConfig.value;
	const asideBrTheme = ['#FFFFFF', '#FFF', '#fff', '#ffffff'];
	const asideBrColor = asideBrTheme.includes(menuBar) ? 'layout-el-aside-br-color' : '';
	// 判断是否是手机端
	if (state.clientWidth <= 1000) {
		if (isCollapse) {
			document.body.setAttribute('class', 'el-popup-parent--hidden');
			const asideEle = document.querySelector('.layout-container') as HTMLElement;
			const modeDivs = document.createElement('div');
			modeDivs.setAttribute('class', 'layout-aside-mobile-mode');
			asideEle.appendChild(modeDivs);
			modeDivs.addEventListener('click', closeLayoutAsideMobileMode);
			return [asideBrColor, 'layout-aside-mobile', 'layout-aside-mobile-open'];
		} else {
			// 关闭弹窗
			closeLayoutAsideMobileMode();
			return [asideBrColor, 'layout-aside-mobile', 'layout-aside-mobile-close'];
		}
	} else {
		if (layout === 'columns') {
			// 分栏布局，菜单收起时宽度给 1px
			if (isCollapse) return [asideBrColor, 'layout-aside-pc-1'];
			else return [asideBrColor, 'layout-aside-pc-220'];
		} else {
			// 其它布局给 64px；侧边栏布局展开时是 256px
			if (isCollapse) return [asideBrColor, 'layout-aside-pc-64'];
			else return [asideBrColor, layout === 'defaults' ? 'layout-aside-pc-256' : 'layout-aside-pc-220'];
		}
	}
});
// 侧边栏布局：侧栏带菜单搜索、最近打开和用户区（窄屏时变成抽屉）
const isPanel = computed(() => themeConfig.value.layout === 'defaults');
// 侧栏收起成 64px（窄屏时 isCollapse 表示抽屉打开，不算收起）
const isPanelCollapse = computed(() => isPanel.value && themeConfig.value.isCollapse && state.clientWidth > 1000);
// 菜单搜索：打开与顶栏搜索图标相同的菜单搜索弹窗
const onSearchClick = () => {
	searchRef.value.openSearch();
};
// 设置显示/隐藏 logo
const setShowLogo = computed(() => {
	let { layout, isShowLogo } = themeConfig.value;
	return (isShowLogo && layout === 'defaults') || (isShowLogo && layout === 'columns');
});
// 关闭移动端蒙版
const closeLayoutAsideMobileMode = () => {
	const el = document.querySelector('.layout-aside-mobile-mode');
	el?.setAttribute('style', 'animation: error-img-two 0.3s');
	setTimeout(() => {
		el?.parentNode?.removeChild(el);
	}, 300);
	const clientWidth = document.body.clientWidth;
	if (clientWidth < 1000) themeConfig.value.isCollapse = false;
	document.body.setAttribute('class', '');
};
// 设置/过滤路由（非静态路由/是否显示在菜单中）
const setFilterRoutes = () => {
	if (themeConfig.value.layout === 'columns') return false;
	state.menuList = filterRoutesFun(routesList.value);
};
// 路由过滤递归函数
const filterRoutesFun = <T extends RouteItem>(arr: T[]): T[] => {
	return arr
		.filter((item: T) => !item.meta?.isHide)
		.map((item: T) => {
			item = Object.assign({}, item);
			if (item.children) item.children = filterRoutesFun(item.children);
			return item;
		});
};
// 设置菜单导航是否固定（移动端）
const initMenuFixed = (clientWidth: number) => {
	state.clientWidth = clientWidth;
};
// 鼠标移入、移出
const onAsideEnterLeave = (bool: Boolean) => {
	let { layout } = themeConfig.value;
	if (layout !== 'columns') return false;
	if (!bool) mittBus.emit('restoreDefault');
	stores.setColumnsMenuHover(bool);
};
// 页面加载前
onBeforeMount(() => {
	initMenuFixed(document.body.clientWidth);
	setFilterRoutes();
	// 此界面不需要取消监听(mittBus.off('setSendColumnsChildren))
	// 因为切换布局时有的监听需要使用，取消了监听，某些操作将不生效
	mittBus.on('setSendColumnsChildren', (res: MittMenu) => {
		state.menuList = res.children;
	});
	mittBus.on('setSendClassicChildren', (res: MittMenu) => {
		let { layout, isClassicSplitMenu } = themeConfig.value;
		if (layout === 'classic' && isClassicSplitMenu) {
			state.menuList = [];
			state.menuList = res.children;
		}
	});
	mittBus.on('getBreadcrumbIndexSetFilterRoutes', () => {
		setFilterRoutes();
	});
	mittBus.on('layoutMobileResize', (res: LayoutMobileResize) => {
		initMenuFixed(res.clientWidth);
		closeLayoutAsideMobileMode();
	});
});
// 监听 themeConfig 配置文件的变化，更新菜单 el-scrollbar 的高度
watch(themeConfig.value, (val) => {
	if (val.isShowLogoChange !== val.isShowLogo) {
		if (layoutAsideScrollbarRef.value) layoutAsideScrollbarRef.value.update();
	}
});
// 监听 pinia 值的变化，动态赋值给菜单中
watch(
	pinia.state,
	(val) => {
		let { layout, isClassicSplitMenu } = val.themeConfig.themeConfig;
		if (layout === 'classic' && isClassicSplitMenu) return false;
		setFilterRoutes();
	},
	{
		deep: true,
	}
);
</script>

<style scoped lang="scss">
// 侧边栏布局的侧栏（底色、分割线、左右 8px 内边距和宽度见 theme/app.scss 的 .layout-shell）
// 图标列：搜索图标、菜单图标、最近打开的圆点都从侧栏左边 20px 起（8px 内边距 + 12px），Logo 方块和头像与图标列同一条中线
.layout-aside-panel {
	// 菜单搜索：轻微凹进去的按钮，点开菜单搜索弹窗
	.layout-aside-search {
		height: var(--dv-control-height);
		flex: none;
		display: flex;
		align-items: center;
		gap: 12px;
		margin-bottom: 8px;
		padding: 0 12px;
		border: 0;
		border-radius: var(--dv-radius);
		background: var(--dv-side-inset);
		box-shadow: var(--dv-shadow-inset);
		color: var(--dv-text-secondary);
		font: inherit;
		white-space: nowrap;
		cursor: pointer;
		&:hover {
			color: var(--dv-text-regular);
		}
		span {
			flex: 1;
			min-width: 0;
			overflow: hidden;
			text-overflow: ellipsis;
			text-align: left;
		}
	}
	// 菜单滚动区左右伸到侧栏边上，再用内边距收回 8px：滚动条贴着分割线，菜单项的键盘焦点框不被滚动区裁掉
	> .el-scrollbar {
		width: auto;
		margin: 0 -8px;
		:deep(.el-scrollbar__view) {
			padding: 0 8px;
		}
	}
	// 收起成 64px：只留图标，搜索按钮、头像、"更多"按钮都在 64px 的中线上
	&.is-collapse {
		.layout-aside-search {
			justify-content: center;
			padding: 0;
			span {
				display: none;
			}
		}
		:deep(.layout-aside-user) {
			flex-direction: column;
			gap: 6px;
			padding: 8px 0 0;
			.layout-aside-user-who {
				display: none;
			}
		}
	}
}
</style>
