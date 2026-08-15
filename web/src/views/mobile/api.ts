import { request } from '/@/utils/service';

export function mobileLogin(data: Record<string, any>) {
  return request({ url: '/api/login/', method: 'post', data });
}

export function getCaptcha() {
  return request({ url: '/api/captcha/', method: 'get' });
}

export function getMobileMe() {
  return request({ url: '/api/shield/mobile/me/', method: 'get' });
}

export function getMobileTasks(status = 'active') {
  return request({ url: '/api/shield/mobile/tasks/', method: 'get', params: { status } });
}

export function getMobileTask(id: string | number) {
  return request({ url: `/api/shield/mobile/tasks/${id}/`, method: 'get' });
}

export function saveMobileDetail(taskId: string | number, data: FormData) {
  return request({
    url: `/api/shield/mobile/tasks/${taskId}/save_detail/`,
    method: 'post',
    data,
    timeout: 60000,
  });
}

export function submitMobileTask(taskId: string | number) {
  return request({ url: `/api/shield/mobile/tasks/${taskId}/submit/`, method: 'post' });
}
