import { request } from '/@/utils/service';
import { UserPageQuery, AddReq, EditReq, InfoReq } from '@fast-crud/fast-crud';

export const apiPrefix = '/api/shield/warehouse_opening/';

export interface OpeningStratumPreview {
	last_ring_no: string | null;
	rings_between_openings: number | null;
	stratum_info_between: Record<string, number>;
	stratum_info_between_list: Array<{
		stratum_type_code: string;
		stratum_type_name: string;
		ring_count: number;
	}>;
	geological_conditions: string;
}

/**
 * 获取项目基本信息列表
 */
export function GetList(query: UserPageQuery) {
	return request({
		url: apiPrefix,
		method: 'get',
		params: query,
	});
}

/**
 * 获取项目基本信息详情
 */
export function GetObj(id: InfoReq) {
	return request({
		url: apiPrefix + id + '/',
		method: 'get',
	});
}

/**
 * 新增项目基本信息
 */
export function AddObj(obj: AddReq) {
	return request({
		url: apiPrefix,
		method: 'post',
		data: obj,
	});
}

/**
 * 修改换刀基本信息
 */
export function UpdateObj(obj: EditReq) {
	return request({
		url: apiPrefix + obj.id + '/',
		method: 'put',
		data: obj,
	});
}

/**
 * 删除换刀基本信息
 */
export function DelObj(id: string) {
	return request({
		url: apiPrefix + id + '/',
		method: 'delete'
	});
}

/**
 * 批量删除换刀基本信息
 */
export function BatchDel(ids: string[]) {
	return request({
		url: apiPrefix + 'multiple_delete/',
		method: 'delete',
		data: { ids }
	});
}

/** 根据项目、盾构机和换刀环号预览自动地层信息。 */
export function GetAutoStratumPreview(params: {
	project: number | string;
	ring_no: number | string;
	shield_model?: number | string;
	opening_id?: number | string;
}) {
	return request({
		url: apiPrefix + 'auto_stratum_preview/',
		method: 'get',
		params,
	});
}
