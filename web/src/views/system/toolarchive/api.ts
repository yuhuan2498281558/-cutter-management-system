import { request } from '/@/utils/service';
import { UserPageQuery, AddReq, EditReq, InfoReq } from '@fast-crud/fast-crud';

export const apiPrefix = '/api/system/toolarchive/';


// 项目列表
export function getToolList(query: UserPageQuery) {
  return request({
    url: apiPrefix ,
    method: 'get',
    params: query,
  });
}

// 新增项目
export function addTool(obj: AddReq) {
  return request({
    url: apiPrefix ,
    method: 'post',
    data: obj,
  });
}

// 删除项目
export function deleteTool(id: string | number) {
  return request({
    url: apiPrefix + id + '/' ,
    method: 'delete',
    params: {
      id,
    },
    data: {
      id,
    },
  });
}

// 导出项目
export function exportTool(query: UserPageQuery) {
  return request({
    url: apiPrefix + 'export',
    method: 'get',
    params: query,
    responseType: 'blob',
  });
}

// 修改项目
export function updateTool(obj: EditReq) {

  if (!obj.id) {
    throw new Error('未传入id，无法修改');
  }
  return request({
    url: apiPrefix + obj.id + '/',
    method: 'put',
    data: obj,
  });
}