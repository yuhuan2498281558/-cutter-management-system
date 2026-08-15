import { request } from '/@/utils/service';
import { UserPageQuery, AddReq, EditReq, InfoReq } from '@fast-crud/fast-crud';

export const apiPrefix = '/api/shield/stratum_basic_info/';

export function GetList(query: UserPageQuery) {
	return request({
		url: apiPrefix,
		method: 'get',
		params: query,
	});
}

export function GetObj(id: InfoReq) {
	return request({
		url: apiPrefix + id + '/',
		method: 'get',
	});
}

export function AddObj(obj: AddReq) {
	return request({
		url: apiPrefix,
		method: 'post',
		data: obj,
	});
}

export function UpdateObj(obj: EditReq) {
	return request({
		url: apiPrefix + obj.id + '/',
		method: 'put',
		data: obj,
	});
}

export function DelObj(id: string) {
	return request({
		url: apiPrefix + id + '/',
		method: 'delete'
	});
}

export function BatchDel(ids: string[]) {
	return request({
		url: apiPrefix + 'multiple_delete/',
		method: 'delete',
		data: { ids }
	});
}

export function exportData(params: any) {
	return request({
		url: apiPrefix + 'export_data/',
		method: 'get',
		params: params,
	});
}

export function importData(data: any) {
	return request({
		url: apiPrefix + 'import_data/',
		method: 'post',
		data: data,
	});
}

export function downloadTemplate() {
	return request({
		url: apiPrefix + 'import_data/',
		method: 'get',
		responseType: 'blob',
	});
}

export function importFromPdf(params: { project: number; dry_run?: boolean }) {
	return request({
		url: apiPrefix + 'import_from_pdf/',
		method: 'post',
		data: params,
	});
}
