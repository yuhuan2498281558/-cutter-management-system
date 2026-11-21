<template>
	<div v-if="pages.length" class="layout-aside-recent">
		<button type="button" class="layout-aside-recent-label" :aria-expanded="!collapsed" @click="onToggle">
			<span>最近打开</span>
			<el-icon class="layout-aside-recent-arrow" :class="{ 'is-open': !collapsed }" :size="12"><ele-ArrowDown /></el-icon>
		</button>
		<nav v-show="!collapsed" class="layout-aside-recent-list">
			<div
				v-for="page in pages"
				:key="page.route.url || page.route.path"
				class="layout-aside-recent-item"
				:class="{ 'is-current': page.isActive }"
				role="link"
				tabindex="0"
				:aria-current="page.isActive ? 'page' : undefined"
				@click="onOpen(page.route)"
				@keydown.enter="onOpen(page.route)"
			>
				<i class="layout-aside-recent-dot"></i>
				<span class="layout-aside-recent-text">
					<span class="layout-aside-recent-title">{{ other.setTagsViewNameI18n(page.route) }}</span>
					<span v-if="parentTitles[page.route.path]" class="layout-aside-recent-parent">{{ $t(parentTitles[page.route.path]) }}</span>
				</span>
			</div>
		</nav>
	</div>
</template>

<script setup lang="ts" name="layoutAsideRecent">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { storeToRefs } from 'pinia';
import other from '/@/utils/other';
import { Local } from '/@/utils/storage';
import { useRoutesList } from '/@/stores/routesList';
import { openedPages, recentOpenedPages } from '/@/layout/navBars/tagsView/openedPages';

// 侧栏"最近打开"（插在菜单的"首页"下面）：数据来自标签栏（tagsView.vue）维护的打开页面列表，
// 按最后访问从新到旧最多 5 个，不含首页等固定页；超出 5 个的页面由 tagsView.vue 关掉。
// 点小标题可以折叠，折叠状态记在浏览器里；二级菜单里的页面在名字下面用灰色小字标出所属的一级菜单

// 定义变量内容
const router = useRouter();
const { routesList } = storeToRefs(useRoutesList());
const pages = computed(() => recentOpenedPages(openedPages.list));
const collapsed = ref(Local.get('asideRecentCollapsed') === true);
// 页面路径 → 所属一级菜单的标题；一级菜单本身的页面（如掘进动态数据）不在表里
const parentTitles = computed(() => {
	const titles: Record<string, string> = {};
	const walk = (items: RouteItem[], topTitle: string) => {
		items.forEach((item) => {
			if (topTitle) titles[item.path] = topTitle;
			if (item.children?.length) walk(item.children, topTitle || item.meta?.title || '');
		});
	};
	walk(routesList.value as RouteItem[], '');
	return titles;
});

// 打开页面：与点击标签栏的标签相同
const onOpen = (route: RouteItem) => {
	router.push(route);
};
// 折叠/展开列表
const onToggle = () => {
	collapsed.value = !collapsed.value;
	Local.set('asideRecentCollapsed', collapsed.value);
};
</script>

<style scoped lang="scss">
// 小标题和圆点对齐菜单的图标列，页面名对齐菜单文字；和菜单一样不加选中竖线，当前页靠主题色圆点区分
.layout-aside-recent {
	margin-bottom: 8px;
	// 小标题整行可点；右边的箭头和菜单分组的箭头同一列，朝下是折叠、朝上是展开
	&-label {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: 6px 12px 4px;
		border: 0;
		border-radius: var(--dv-radius);
		background: transparent;
		font-family: inherit;
		font-size: 12px;
		line-height: 18px;
		color: var(--dv-text-muted);
		white-space: nowrap;
		cursor: pointer;
		&:hover {
			color: var(--dv-text-secondary);
		}
	}
	&-arrow.is-open {
		transform: rotate(180deg);
	}
	&-list {
		display: grid;
		gap: 2px;
	}
	// 只有页面名时 32px 高；带一级菜单名的两行项上下各留 4px（约 40px 高），圆点在两行中间
	&-item {
		display: flex;
		align-items: center;
		gap: 12px;
		min-height: 32px;
		padding: 4px 12px;
		box-sizing: border-box;
		border-radius: var(--dv-radius);
		font-size: 13px;
		color: var(--dv-text-secondary);
		white-space: nowrap;
		cursor: pointer;
		transition: background-color 0.15s, color 0.15s;
		&:hover {
			background: var(--dv-hover);
			color: var(--dv-text);
		}
		&.is-current {
			color: var(--dv-text);
			.layout-aside-recent-dot::before {
				background: var(--el-color-primary);
			}
		}
	}
	// 16px 宽的位置（与菜单图标同宽）里居中一个 6px 圆点
	&-dot {
		width: 16px;
		height: 16px;
		flex: none;
		display: flex;
		align-items: center;
		justify-content: center;
		&::before {
			content: '';
			width: 6px;
			height: 6px;
			border-radius: 50%;
			background: var(--dv-border-strong);
		}
	}
	&-text {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}
	&-title,
	&-parent {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	&-title {
		line-height: 18px;
	}
	&-parent {
		font-size: 11px;
		line-height: 14px;
		color: var(--dv-text-muted);
	}
}
</style>
