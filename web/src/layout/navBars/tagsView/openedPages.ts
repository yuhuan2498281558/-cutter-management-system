import { reactive } from 'vue';

/**
 * 标签栏里已打开页面的只读镜像，给侧栏"最近打开"用
 * 打开页面的记录、关闭页面和 keep-alive 缓存仍然全部由 tagsView.vue 维护（标签栏横条在侧边栏布局里只是隐藏，组件照常挂载），
 * 这里只同步一份列表；侧栏关闭页面时调用 tagsView.vue 登记的 close，走和标签栏关闭按钮相同的逻辑。
 * tagsView.vue 卸载（例如在布局设置里关掉标签栏）时清空，侧栏随之不显示这一块。
 */
export interface OpenedPage {
	// 打开的页面（tagsView 列表里的路由项）
	route: RouteItem;
	// 是否当前页
	isActive: boolean;
}

export const openedPages = reactive<{ list: OpenedPage[]; close: ((route: RouteItem) => void) | null }>({
	list: [],
	close: null,
});

/**
 * 侧栏"最近打开"显示的页面：当前页在前，其余按打开时间从新到旧，最多 limit 个
 */
export function recentOpenedPages(list: OpenedPage[], limit = 6): OpenedPage[] {
	const active = list.filter((page) => page.isActive);
	const others = list.filter((page) => !page.isActive).reverse();
	return [...active, ...others].slice(0, limit);
}
