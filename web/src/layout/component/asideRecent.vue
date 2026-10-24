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
				@keydown.enter="onOpen(page.route)"
			>
				<i class="layout-aside-recent-dot"></i>
				<span class="layout-aside-recent-title">{{ other.setTagsViewNameI18n(page.route) }}</span>
				<button v-if="!page.route.meta?.isAffix" type="button" class="layout-aside-recent-close" @click.stop="onClose(page.route)">
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

// 侧栏"最近打开"：数据来自标签栏（tagsView.vue）维护的打开页面列表，当前页在前，其余按打开时间从新到旧，最多 6 个

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
.layout-aside-recent {
	&-label {
		padding: 18px 10px 6px;
		font-size: 11.5px;
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
		gap: 10px;
		height: 32px;
		padding: 0 4px 0 10px;
		border-radius: var(--dv-radius);
		color: var(--dv-text-secondary);
		white-space: nowrap;
		cursor: pointer;
		transition: background-color 0.15s, color 0.15s;
		&:hover {
			background: var(--dv-fill);
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
			.layout-aside-recent-dot {
				background: var(--dv-accent);
				box-shadow: 0 0 0 3px var(--dv-accent-soft);
			}
		}
	}
	&-dot {
		width: 6px;
		height: 6px;
		margin: 0 5px;
		flex: none;
		border-radius: 2px;
		background: var(--dv-border-strong);
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
			background: var(--dv-fill);
			color: var(--dv-text);
		}
	}
}
</style>
