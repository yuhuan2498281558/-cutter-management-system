import { request } from '/@/utils/service';
import { UserPageQuery, AddReq, EditReq, InfoReq } from '@fast-crud/fast-crud';

export const apiPrefix = '/api/shield/mobile/task_manage/';

export function GetList(query: UserPageQuery) {
  return request({ url: apiPrefix, method: 'get', params: query });
}

export function GetObj(id: InfoReq) {
  return request({ url: apiPrefix + id + '/', method: 'get' });
}

export function AddObj(obj: AddReq) {
  return request({ url: apiPrefix, method: 'post', data: normalizeTask(obj) });
}

export function UpdateObj(obj: EditReq) {
  return request({ url: apiPrefix + obj.id + '/', method: 'put', data: normalizeTask(obj) });
}

export function DelObj(id: string) {
  return request({ url: apiPrefix + id + '/', method: 'delete' });
}

export function ReturnTask(id: string | number, reason = '') {
  return request({ url: `${apiPrefix}${id}/return_task/`, method: 'post', data: { reason } });
}

export function CompleteTask(id: string | number) {
  return request({ url: `${apiPrefix}${id}/complete_task/`, method: 'post' });
}

function splitList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  if (typeof value !== 'string') return [];
  return value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean);
}

function normalizeTask(obj: any) {
  return {
    ...obj,
    tool_types: splitList(obj.tool_types),
    position_nos: splitList(obj.position_nos),
  };
}


export function GetAssignOptions(warehouse?: string | number) {
  return request({ url: apiPrefix + 'assign_options/', method: 'get', params: { warehouse } });
}

export function GetRecorderOptions() {
  return request({ url: apiPrefix + 'recorder_options/', method: 'get' });
}


export function ApprovalDetail(id: string | number) {
  return request({ url: apiPrefix + id + '/approval_detail/', method: 'get' });
}
