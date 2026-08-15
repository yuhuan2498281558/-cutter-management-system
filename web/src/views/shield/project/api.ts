import { request } from '/@/utils/service';
import { UserPageQuery, AddReq, EditReq, InfoReq } from '@fast-crud/fast-crud';

export const apiPrefix = '/api/shield/project/';

/**
 * 获取项目列表
 */
export function GetList(query: UserPageQuery) {
	return request({
		url: apiPrefix,
		method: 'get',
		params: query,
	});
}

/**
 * 获取单个项目详情
 */
export function GetObj(id: InfoReq) {
	return request({
		url: apiPrefix + id + '/',
		method: 'get',
	});
}

/**
 * 新增项目
 */
export function AddObj(obj: AddReq) {
	return request({
		url: apiPrefix,
		method: 'post',
		data: obj,
	});
}

/**
 * 修改项目
 */
export function UpdateObj(obj: EditReq) {
	return request({
		url: apiPrefix + obj.id + '/',
		method: 'put',
		data: obj,
	});
}

/**
 * 删除项目
 */
export function DelObj(id: string) {
	return request({
		url: apiPrefix + id + '/',
		method: 'delete'
	});
}

/**
 * 批量删除项目
 */
export function BatchDel(ids: string[]) {
	return request({
		url: apiPrefix + 'multiple_delete/',
		method: 'delete',
		data: { ids }
	});
}

export function ImportTunnelingXml(projectId: number | string, data: any) {
	return request({
		url: apiPrefix + projectId + '/import_tunneling_xml/',
		method: 'post',
		data,
	});
}
