import { request } from '/@/utils/service';

export function GetHomeProjectInfo() {
  return request({
    url: '/api/shield/project/1/',
    method: 'get'
  });
}
