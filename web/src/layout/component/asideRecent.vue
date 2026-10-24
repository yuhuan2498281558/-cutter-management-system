<template>
	<div v-if="pages.length" class="layout-aside-recent">
		<div class="layout-aside-recent-label">最近打开</div>
		<nav class="layout-aside-recent-list">
			<div
				v-for="page in pages"
				:key="page.route.url || page.route.path"
				class="layout-aside-recent-item"
				:class="{ 'is-current': page.isActive }"
				role="link"
				tabindex="0"
				:aria-current="page.isActive ? 'page' : undefined"
				@click="onOpen(page.route)"
				@keydown.enter.self="onOpen(page.route)"
			>
				<i class="layout-aside-recent-dot"></i>
				<span class="layout-aside-recent-title">{{ other.setTagsViewNameI18n(page.route) }}</span>
				<button type="button" class="layout-aside-recent-close" @click.stop="onClose(page.route)">
					<el-icon :size="12"><ele-Close /></el-icon>
				</button>
			</div>
		</nav>
	</div>
</template>

<script setup lang="ts" name="layoutAsideRecent">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import other from '/@/utils/other';
import { openedPages, recentOpenedPages } from '/@/layout/navBars/tagsView/openedPages';

// 侧栏"最近打开"（插在菜单的"首页"下面）：数据来自标签栏（tagsView.vue）维护的打开页面列表，
// 按最后访问从新到旧最多 5 个，不含首页等固定页；超出 5 个的页面由 tagsView.vue 关掉

// 定义变量内容
const router = useRouter();
const pages = computed(() => recentOpenedPages(openedPages.list));

// 打开页面：与点击标签栏的标签相同
const onOpen = (route: RouteItem) => {
	router.push(route);
};
// 关闭页面：走标签栏的关闭逻辑（同时释放 keep-alive 缓存，关闭当前页时跳到相邻页面）
const onClose = (route: RouteItem) => {
	openedPages.close?.(route);
};
</script>

<style scoped lang="scss">
// 小标题和圆点对齐菜单的图标列，页面名对齐菜单文字；不加选中竖线，免得和菜单的竖线重复
.layout-aside-recent {
	margin-bottom: 8px;
	&-label {
		padding: 6px 12px 4px;
		font-size: 12px;
		line-height: 18px;
		color: var(--dv-text-muted);
		white-space: nowrap;
	}
	&-list {
		display: grid;
		gap: 2px;
	}
	&-item {
		display: flex;
		align-items: center;
		gap: 12px;
		height: 32px;
		padding: 0 4px 0 12px;
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
		&:hover,
		&:focus-within {
			.layout-aside-recent-close {
				visibility: visible;
			}
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
	&-title {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	&-close {
		width: 24px;
		height: 24px;
		flex: none;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0;
		border: 0;
		border-radius: var(--dv-radius-sm);
		background: transparent;
		color: var(--dv-text-muted);
		cursor: pointer;
		visibility: hidden;
		&:hover {
			background: var(--dv-selected);
			color: var(--dv-text);
		}
	}
}
</style>
