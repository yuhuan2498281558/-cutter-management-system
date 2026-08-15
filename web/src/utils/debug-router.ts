/**
 * 路由调试工具
 * 用于排查路由显示问题
 */

export function debugRouter() {
  console.group('🔍 路由调试信息');

  // 1. 检查是否有token
  const token = sessionStorage.getItem('token');
  console.log('1. Token状态:', token ? '✅ 已登录' : '❌ 未登录');

  // 2. 检查路由列表
  const routesListStr = sessionStorage.getItem('routesList');
  if (routesListStr) {
    try {
      const routesList = JSON.parse(routesListStr);
      console.log('2. 路由列表数量:', routesList.length);
      console.log('路由列表详情:', routesList);
    } catch (e) {
      console.error('2. 路由列表解析失败:', e);
    }
  } else {
    console.warn('2. ⚠️ 路由列表为空');
  }

  // 3. 检查菜单数据
  const menuDataStr = sessionStorage.getItem('menuData');
  if (menuDataStr) {
    try {
      const menuData = JSON.parse(menuDataStr);
      console.log('3. 菜单数据:', menuData);
    } catch (e) {
      console.error('3. 菜单数据解析失败:', e);
    }
  } else {
    console.warn('3. ⚠️ 菜单数据为空');
  }

  // 4. 检查当前路由实例
  const router = (window as any).__VUE_ROUTER__;
  if (router) {
    const routes = router.getRoutes();
    console.log('4. 当前注册的路由数量:', routes.length);
    console.log('所有路由:', routes.map((r: any) => ({
      path: r.path,
      name: r.name,
      component: r.component?.name || 'anonymous'
    })));
  } else {
    console.warn('4. ⚠️ 无法获取路由实例');
  }

  // 5. 检查用户信息
  const userInfoStr = sessionStorage.getItem('userInfo');
  if (userInfoStr) {
    try {
      const userInfo = JSON.parse(userInfoStr);
      console.log('5. 用户信息:', {
        username: userInfo.username,
        roles: userInfo.roles
      });
    } catch (e) {
      console.error('5. 用户信息解析失败:', e);
    }
  } else {
    console.warn('5. ⚠️ 用户信息为空');
  }

  console.groupEnd();
}

// 自动在开发环境执行
if (import.meta.env.DEV) {
  (window as any).debugRouter = debugRouter;
}
