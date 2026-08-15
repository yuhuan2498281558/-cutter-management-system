import { RouteRecordRaw } from 'vue-router';
import { storeToRefs } from 'pinia';
import pinia from '/@/stores/index';
import { useUserInfo } from '/@/stores/userInfo';
import { useRequestOldRoutes } from '/@/stores/requestOldRoutes';
import { Session } from '/@/utils/storage';
import { NextLoading } from '/@/utils/loading';
import { dynamicRoutes, notFoundAndNoPower } from '/@/router/route';
import { formatTwoStageRoutes, formatFlatteningRoutes, router } from '/@/router/index';
import { useRoutesList } from '/@/stores/routesList';
import { useTagsViewRoutes } from '/@/stores/tagsViewRoutes';
import { useMenuApi } from '/@/api/menu/index';
import { handleMenu } from '../utils/menu';
import { BtnPermissionStore } from '/@/plugin/permission/store.permission';
import {SystemConfigStore} from "/@/stores/systemConfig";
import {useDeptInfoStore} from "/@/stores/modules/dept";
import {DictionaryStore} from "/@/stores/dictionary";
import {useFrontendMenuStore} from "/@/stores/frontendMenu";
import {toRaw} from "vue";
const menuApi = useMenuApi();

const layouModules: any = import.meta.glob('../layout/routerView/*.{vue,tsx}');
const viewsModules: any = import.meta.glob('../views/**/*.{vue,tsx}');

/** 获取 layout 和 views 目录下可用于路由的 Vue/TSX 模块。 */
const dynamicViewsModules: Record<string, Function> = Object.assign({}, { ...layouModules }, { ...viewsModules });

// Reuse one initialization promise when login and the route guard run together.
let backendRoutesInitPromise: Promise<boolean> | null = null;

/** 初始化后端菜单路由，并同步用户、菜单和缓存状态。 */
async function initBackEndControlRoutesOnce() {
	// 启动页面加载状态。
	if (window.nextLoading === undefined) NextLoading.start();
	// 无 token 时停止初始化。
	if (!Session.get('token')) {
		console.warn('Token is missing, stop route loading.');
		return false;
	}
	// 初始化用户信息。
	// https://gitee.com/lyt-top/vue-next-admin/issues/I5F1HP
	await useUserInfo().setUserInfos();
	// 获取后端菜单数据。
	const res = await getBackEndControlRoutes();

	// 后端未返回菜单时保持空路由状态。
	// https://gitee.com/lyt-top/vue-next-admin/issues/I64HVO
	if (res.data.length <= 0) {
		console.warn('Backend menu data is empty.');
		return Promise.resolve(true);
	}

	// 转换菜单组件并写入动态路由。
	const {frameIn,frameOut} = handleMenu(res.data)

	dynamicRoutes[0].children = await backEndComponent(frameIn);

	// 注册动态路由。
	await setAddRoute();
	// 同步菜单路由与 tagsView 缓存。
	await setFilterMenuAndCacheTagsViewRoutes();
	return true;
}

export function initBackEndControlRoutes() {
	if (!backendRoutesInitPromise) {
		backendRoutesInitPromise = initBackEndControlRoutesOnce().catch((error) => {
			backendRoutesInitPromise = null;
			throw error;
		});
	}
	return backendRoutesInitPromise;
}

export async function setRouters(){
	const {frameInRoutes,frameOutRoutes} = await useFrontendMenuStore().getRouter()
	const frameInRouter = toRaw(frameInRoutes)
	const frameOutRouter = toRaw(frameOutRoutes)
	dynamicRoutes[0].children = frameInRouter
	dynamicRoutes.forEach((item:any)=>{
		router.addRoute(item)
	})
	frameOutRouter.forEach((item:any)=>{
		router.addRoute(item)
	})
	const storesRoutesList = useRoutesList(pinia);
	storesRoutesList.setRoutesList([...dynamicRoutes[0].children,...frameOutRouter]);
	const storesTagsView = useTagsViewRoutes(pinia);
	storesTagsView.setTagsViewRoutes([...dynamicRoutes[0].children,...frameOutRouter])

}

/** 同步侧边栏菜单路由并刷新 tagsView 缓存。 */
export function setFilterMenuAndCacheTagsViewRoutes() {
	const storesRoutesList = useRoutesList(pinia);
	storesRoutesList.setRoutesList(dynamicRoutes[0].children as any);
	setCacheTagsViewRoutes();
}

/** 缓存展开后的路由，供 tagsView 和菜单搜索使用。 */
export function setCacheTagsViewRoutes() {
	const storesTagsView = useTagsViewRoutes(pinia);
	storesTagsView.setTagsViewRoutes(formatTwoStageRoutes(formatFlatteningRoutes(dynamicRoutes))[0].children);
}

/** 整理动态路由结构并补充 404/401 路由。 */
export function setFilterRouteEnd() {
	let filterRouteEnd: any = formatTwoStageRoutes(formatFlatteningRoutes(dynamicRoutes));
	// 将 404/401 放入 layout，避免异常页脱离主布局。
	filterRouteEnd[0].children = [...filterRouteEnd[0].children, ...notFoundAndNoPower];
	return filterRouteEnd;
}

/** 注册整理后的动态路由。 */
export async function setAddRoute() {
	await setFilterRouteEnd().forEach((route: RouteRecordRaw) => {
		router.addRoute(route);
	});
}

function loadRouteSidecarData() {
	const tasks = [
		() => BtnPermissionStore().getBtnPermissionStore(),
		() => SystemConfigStore().getSystemConfigs(),
		() => useDeptInfoStore().requestDeptInfo(),
		() => DictionaryStore().getSystemDictionarys(),
	];
	window.setTimeout(() => {
		tasks.forEach((task) => {
			Promise.resolve()
				.then(task)
				.catch((error) => {
					if (import.meta.env.DEV) console.warn('route sidecar data load failed:', error);
				});
		});
	}, 0);
}

/** 请求后端菜单路由，并异步加载按钮权限等附属数据。 */
export function getBackEndControlRoutes() {
	loadRouteSidecarData();
	return menuApi.getSystemMenu();
}

/** 重新请求后端菜单，供菜单管理页面刷新使用。 */
export function setBackEndControlRefreshRoutes() {
	getBackEndControlRoutes();
}

/** 将后端路由中的 component 路径转换为可加载模块。 */
export function backEndComponent(routes: any) {
	if (!routes) return;
	return routes.map((item: any) => {
		if (item.component) item.component = dynamicImport(dynamicViewsModules, item.component as string);
		if(item.is_catalog){
			// 目录使用父级路由容器。
			item.component = dynamicImport(dynamicViewsModules, 'layout/routerView/parent')
		}
		if(item.is_link){
			// 外部链接按 iframe 或普通链接处理。
			if(item.is_iframe){
				item.component = dynamicImport(dynamicViewsModules, 'layout/routerView/iframes')
			}else {
				item.component = dynamicImport(dynamicViewsModules, 'layout/routerView/link')
			}
		}else{
			if(item.is_iframe){
				// const iframeRoute:RouteRecordRaw = {
				// 	...item
				// }
				// router.addRoute(iframeRoute)
				item.meta.isLink = item.link_url
				// item.path = `${item.path}Link`
				// item.name = `${item.name}Link`
				// item.meta.isIframe = item.is_iframe
				// item.meta.isKeepAlive = false
				// item.meta.isIframeOpen = true
				item.component = dynamicImport(dynamicViewsModules, 'layout/routerView/link.vue')
			}
		}
		item.children && backEndComponent(item.children);
		return item;
	});
}

/** 根据后端 component 路径匹配本地动态模块。 */
export function dynamicImport(dynamicViewsModules: Record<string, Function>, component: string) {
	const keys = Object.keys(dynamicViewsModules);
	const matchKeys = keys.filter((key) => {
		const k = key.replace(/..\/views|../, '');
		return k.startsWith(`${component}`) || k.startsWith(`/${component}`);
	});
	if (matchKeys?.length === 1) {
		const matchKey = matchKeys[0];
		return dynamicViewsModules[matchKey];
	}
	if (matchKeys?.length > 1) {
		return false;
	}
}
