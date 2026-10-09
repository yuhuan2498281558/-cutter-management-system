import { request } from '/@/utils/service';

export const apiPrefix = '/api/shield/mobile/tool_lifecycle/';

export function getLifecycleScopes() {
  return request({ url: `${apiPrefix}scopes/`, method: 'get' });
}

export function getPositionHistory(params: Record<string, any>) {
  return request({ url: `${apiPrefix}position_history/`, method: 'get', params });
}

export function getToolLifecycleList(params: Record<string, any>) {
  return request({ url: apiPrefix, method: 'get', params });
}

export function getToolLifecycleDetail(id: string | number) {
  return request({ url: `${apiPrefix}${encodeURIComponent(String(id))}/`, method: 'get' });
}
