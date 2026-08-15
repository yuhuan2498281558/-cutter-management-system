import { request } from '/@/utils/service';
import { UserPageQuery, AddReq, DelReq, EditReq, UserPageRes } from '@fast-crud/fast-crud';
import { BatchCreateRequest } from './types';

const apiPrefix = '/api/shield/tool_change_detail';

export function GetList(query: UserPageQuery): Promise<UserPageRes> {
  return request({
    url: apiPrefix + '/',
    method: 'get',
    params: query,
  });
}

export function AddObj(obj: AddReq) {
  return request({
    url: apiPrefix + '/',
    method: 'post',
    data: obj,
  });
}

export function UpdateObj(obj: EditReq) {
  return request({
    url: apiPrefix + `/${obj.id}/`,
    method: 'put',
    data: obj,
  });
}

export function DelObj(id: string) {
  return request({
    url: apiPrefix + `/${id}/`,
    method: 'delete',
  });
}

export function GetObj(id: string) {
  return request({
    url: apiPrefix + `/${id}/`,
    method: 'get',
  });
}

export function GetCostOptions(query: Record<string, any>) {
  return request({
    url: apiPrefix + '/cost_options/',
    method: 'get',
    params: query,
  });
}

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

// 批量创建换刀明细记录
export function BatchCreate(data: BatchCreateRequest) {
  return request({
    url: apiPrefix + '/batch_create/',
    method: 'post',
    data: data,
  });
}

// 获取指定盾构机的刀位列表
export function GetCutterPositions(shieldMachineId: number) {
  return request({
    url: apiPrefix + '/get_cutter_positions/',
    method: 'get',
    params: { shield_machine: shieldMachineId },
  });
}

// 批量更新换刀明细记录
export function BatchUpdate(details: any[]) {
  const promises = details.map(detail => {
    if (detail.id) {
      return UpdateObj(detail);
    } else {
      return AddObj(detail);
    }
  });
  return Promise.all(promises);
}
