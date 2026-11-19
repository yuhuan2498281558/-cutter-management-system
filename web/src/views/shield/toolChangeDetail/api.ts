import { request } from '/@/utils/service';

const apiPrefix = '/api/shield/tool_change_detail';

export function GetToolChangeOptions() {
  return request({
    url: apiPrefix + '/field_options/',
    method: 'get',
  });
}

export function GetOldToolRecord(id: string | number) {
  return request({
    url: apiPrefix + `/${id}/old_tool_record/`,
    method: 'get',
  });
}

export function UpdateOldToolRecord(id: string | number, data: FormData) {
  return request({
    url: apiPrefix + `/${id}/old_tool_record/`,
    method: 'put',
    data,
    timeout: 60000,
  });
}
