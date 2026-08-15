import { request } from '/@/utils/service';
import { UserPageQuery, AddReq, EditReq, InfoReq } from '@fast-crud/fast-crud';

export const apiPrefix = '/api/shield/tool_category/';

/**
 * 获取刀具类型字典列表
 */
export function GetList(query: UserPageQuery) {
	return request({
		url: apiPrefix,
		method: 'get',
		params: query,
	});
}

/**
 * 获取单个刀具类型详情
 */
export function GetObj(id: InfoReq) {
	return request({
		url: apiPrefix + id + '/',
		method: 'get',
	});
}

/**
 * 新增刀具类型
 */
export function AddObj(obj: AddReq) {
	return request({
		url: apiPrefix,
		method: 'post',
		data: obj,
	});
}

/**
 * 修改刀具类型
 */
export function UpdateObj(obj: EditReq) {
	return request({
		url: apiPrefix + obj.id + '/',
		method: 'put',
		data: obj,
	});
}

/**
 * 删除刀具类型
 */
export function DelObj(id: string) {
	return request({
		url: apiPrefix + id + '/',
		method: 'delete'
	});
}

/**
 * 批量删除刀具类型
 */
export function BatchDel(ids: string[]) {
	return request({
		url: apiPrefix + 'multiple_delete/',
		method: 'delete',
		data: { ids }
	});
}

/**
 * 获取所有已录入的刀位号列表
 */
export function GetCutterPositions() {
	return request({
		url: apiPrefix + 'get_cutter_positions/',
		method: 'get',
	});
}

/**
 * 获取所有已录入的刀具编号列表
 */
export function GetToolNumbers() {
	return request({
		url: apiPrefix + 'get_tool_numbers/',
		method: 'get',
	});
}
