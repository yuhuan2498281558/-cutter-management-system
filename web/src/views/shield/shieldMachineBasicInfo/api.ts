import { request } from '/@/utils/service';
import { UserPageQuery, AddReq, EditReq, InfoReq } from '@fast-crud/fast-crud';

export const apiPrefix = '/api/shield/shield_machine_basic_info/';

export function GetList(query: UserPageQuery) {
	return request({ url: apiPrefix, method: 'get', params: query });
}

export function GetObj(id: InfoReq) {
	return request({ url: apiPrefix + id + '/', method: 'get' });
}

export function AddObj(obj: AddReq) {
	return request({ url: apiPrefix, method: 'post', data: obj });
}

export function UpdateObj(obj: EditReq) {
	return request({ url: apiPrefix + obj.id + '/', method: 'put', data: obj });
}

export function DelObj(id: string) {
	return request({ url: apiPrefix + id + '/', method: 'delete' });
}

export function BatchDel(ids: string[]) {
	return request({ url: apiPrefix + 'multiple_delete/', method: 'delete', data: { ids } });
}
