import {createRouter, createWebHashHistory} from 'vue-router';
import NProgress from 'nprogress';
import 'nprogress/nprogress.css';
import pinia from '/@/stores/index';
import {storeToRefs} from 'pinia';
import {useKeepALiveNames} from '/@/stores/keepAliveNames';
import {useRoutesList} from '/@/stores/routesList';
import {useThemeConfig} from '/@/stores/themeConfig';
import {Session} from '/@/utils/storage';
import {dynamicRoutes, notFoundAndNoPower, staticRoutes} from '/@/router/route';
import {initFrontEndControlRoutes} from '/@/router/frontEnd';
import {initBackEndControlRoutes, setRouters} from '/@/router/backEnd';
import {useFrontendMenuStore} from "/@/stores/frontendMenu";
import {useTagsViewRoutes} from "/@/stores/tagsViewRoutes";
import {toRaw} from "vue";

/**
 * isRequestRoutes=false 时使用前端路由，并通过 roles 进行权限过滤。
 * isRequestRoutes=true 时使用后端返回的菜单路由。
 * 两种模式的实现分别位于 frontEnd.ts 和 backEnd.ts。
 */

// 读取主题配置中的路由控制模式。
const storesThemeConfig = useThemeConfig(pinia);
const {themeConfig} = storeToRefs(storesThemeConfig);
const {isRequestRoutes} = themeConfig.value;

const debugLog = (...args: any[]) => {
    if (import.meta.env.DEV) console.log(...args);
};

// Hash 路由在实例创建前先接管直接打开的移动端地址，避免初始路径被判成 `/`。
const directHashRoute = window.location.pathname.match(/(\/(?:login|mobile\/login|mobile\/tasks(?:\/[^/]+)?))\/?$/);
if (directHashRoute && (!window.location.hash || window.location.hash === '#/' || window.location.hash === '#')) {
    const routePath = directHashRoute[1];
    const basePath = window.location.pathname.slice(0, -routePath.length).replace(/\/?$/, '/');
    window.history.replaceState(window.history.state, '', `${basePath || '/'}#${routePath}${window.location.search}`);
}

/** 创建 Vue Router 实例。 */
export const router = createRouter({
    history: createWebHashHistory(),
    // 预先注册 404/401 与静态路由，动态路由加载后会继续补充。
    routes: [...notFoundAndNoPower, ...staticRoutes]
});

/** 将多级嵌套路由展开为一维数组。 */
export function formatFlatteningRoutes(arr: any) {
    if (arr.length <= 0) return false;
    for (let i = 0; i < arr.length; i++) {
        if (arr[i].children) {
            arr = arr.slice(0, i + 1).concat(arr[i].children, arr.slice(i + 1));
        }
    }
    return arr;
}

/** 将一维路由恢复为最多两级的结构，并同步 keep-alive 缓存名称。 */
export function formatTwoStageRoutes(arr: any) {
    if (arr.length <= 0) return false;
    const newArr: any = [];
    const cacheList: Array<string> = [];
    arr.forEach((v: any) => {
        if (v.path === '/') {
            newArr.push({component: v.component,name: v.name,path: v.path,redirect: v.redirect,meta: v.meta,children: []});
        } else {
            // 标记包含参数的动态路由，供 tagsView 等模块使用。
            if (v.path.indexOf('/:') > -1) {
                v.meta['isDynamic'] = true;
                v.meta['isDynamicPath'] = v.path;
            }
            newArr[0].children.push({...v});
            // 保存组件名称，供 keep-alive 的 include 使用。
            if (newArr[0].meta.isKeepAlive && v.meta.isKeepAlive && v.component_name != "") {
                cacheList.push(v.name);
                const stores = useKeepALiveNames(pinia);
                stores.setCacheKeepAlive(cacheList);
            }
        }
    });
    return newArr;
}

// 无需 token 即可访问的路由。
const whiteList = ['/login', '/mobile/login', '/404', '/401'];

// 路由前置守卫。
router.beforeEach(async (to, from, next) => {
    NProgress.configure({showSpinner: false});
    if (to.meta.title) NProgress.start();

    const token = Session.get('token');
    const isMobileRoute = to.path.startsWith('/mobile');

    if (isMobileRoute && !token && to.path !== '/mobile/login') {
        next({path: '/mobile/login', query: {redirect: to.fullPath}, replace: true});
        NProgress.done();
        return;
    }

    if (isMobileRoute && token && to.path === '/mobile/login') {
        next({path: '/mobile/tasks', replace: true});
        NProgress.done();
        return;
    }

    if (isMobileRoute && token) {
        next();
        NProgress.done();
        return;
    }

    // 白名单路由直接放行。
    if (whiteList.includes(to.path)) {
        next();
        NProgress.done();
        return;
    }

    // 未登录时重定向到登录页。
    if (!token) {
        // 避免重复跳转登录页造成死循环。
        if (to.path !== '/login') {
            next(`/login?redirect=${to.path}&params=${JSON.stringify(to.query ? to.query : to.params)}`);
            Session.clear();
            NProgress.done();
        } else {
            next();
            NProgress.done();
        }
        return;
    }

    // 已登录用户访问登录页时跳转首页。
    if (token && to.path === '/login') {
        next('/home');
        NProgress.done();
        return;
    }

    // 已登录时检查动态路由是否加载。
    const storesRoutesList = useRoutesList(pinia);
    const {routesList} = storeToRefs(storesRoutesList);

    if (routesList.value.length === 0) {
        try {
            debugLog('开始加载路由，当前路径：', to.path);
            if (isRequestRoutes) {
                // 初始化后端菜单路由。
                const result = await initBackEndControlRoutes();
                debugLog('路由加载结果：', result);

                if (result === false) {
                    // 路由获取失败时清除登录状态并返回登录页。
                    console.warn('Route loading failed, redirecting to login.');
                    Session.clear();
                    next({ path: '/login', replace: true });
                    NProgress.done();
                    return;
                }

                // 检查路由是否成功写入状态。
                const {routesList: newRoutesList} = storeToRefs(storesRoutesList);
                debugLog('加载后的路由数量：', newRoutesList.value.length);
                debugLog('路由列表内容：', JSON.stringify(newRoutesList.value, null, 2));

                if (newRoutesList.value.length === 0) {
                    console.warn('Route list is empty, redirecting to login.');
                    Session.clear();
                    next({ path: '/login', replace: true });
                    NProgress.done();
                    return;
                }
            } else {
                // 初始化前端配置路由。
                await initFrontEndControlRoutes();
            }
            // 路由加载成功后重新解析目标地址。
            debugLog('路由加载成功，导航到：', to.path);
            debugLog('已注册路由：', router.getRoutes().map(r => ({ path: r.path, name: r.name })));
            // The initial match may be the static notFound route. Re-resolve by
            // path only so its stale `name`/`matched` fields cannot win.
            next({ path: to.fullPath, replace: true });
        } catch (error) {
            // 初始化失败时清除登录状态并返回登录页。
            console.error('路由初始化失败：', error);
            Session.clear();
            next({ path: '/login', replace: true });
            NProgress.done();
        }
    } else {
        // 路由已加载，直接放行。
        debugLog('路由已存在，直接放行：', to.path);
        next();
    }
});

// 路由后置守卫。
router.afterEach(() => {
    NProgress.done();
});

// 导出路由实例。
export default router;
