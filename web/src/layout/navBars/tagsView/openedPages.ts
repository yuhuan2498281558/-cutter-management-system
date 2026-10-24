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
	// 最后访问的时间戳（毫秒）；0 表示没有记录（例如刷新前打开、之后没再访问过）
	lastVisit: number;
}

// 侧栏"最近打开"最多列几个页面
export const RECENT_PAGES_LIMIT = 5;

export const openedPages = reactive<{ list: OpenedPage[]; close: ((route: RouteItem) => void) | null }>({
	list: [],
	close: null,
});

// 可以列进"最近打开"的页面，按最后访问从新到旧：当前页在前，没有访问记录的排在后面、按打开先后倒序。
// 固定页（首页等 isAffix）不列：首页就在菜单最上面，而且固定页关不掉
function sortRecent(list: OpenedPage[]): OpenedPage[] {
	return list
		.map((page, index) => ({ page, index }))
		.filter(({ page }) => !page.route.meta?.isAffix)
		.sort((a, b) => Number(b.page.isActive) - Number(a.page.isActive) || b.page.lastVisit - a.page.lastVisit || b.index - a.index)
		.map(({ page }) => page);
}

/**
 * 侧栏"最近打开"显示的页面：最近访问的 limit 个，从新到旧，当前页在第一个
 */
export function recentOpenedPages(list: OpenedPage[], limit = RECENT_PAGES_LIMIT): OpenedPage[] {
	return sortRecent(list).slice(0, limit);
}

/**
 * 挤出"最近打开"、要关掉的页面：排在第 limit 个之后的。当前页总在第一个，不会被挤出
 */
export function overflowOpenedPages(list: OpenedPage[], limit = RECENT_PAGES_LIMIT): OpenedPage[] {
	return sortRecent(list).slice(limit);
}
