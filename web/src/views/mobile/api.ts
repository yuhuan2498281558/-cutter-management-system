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

/** 开仓时刀盘右转、左转累计读数；空字符串表示没读到 */
export function saveMobileReadings(taskId: string | number, data: { right_revolution_reading: string; left_revolution_reading: string }) {
  return request({ url: `/api/shield/mobile/tasks/${taskId}/save_readings/`, method: 'post', data });
}

export function submitMobileTask(taskId: string | number) {
  return request({ url: `/api/shield/mobile/tasks/${taskId}/submit/`, method: 'post' });
}
