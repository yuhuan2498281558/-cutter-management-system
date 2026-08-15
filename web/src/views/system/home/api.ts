import { request } from '/@/utils/service';
import { PageQuery, AddReq, DelReq, EditReq, InfoReq } from '@fast-crud/fast-crud';

const debugLog = (...args: any[]) => {
  if (import.meta.env.DEV) console.log(...args);
};

// api.ts
export function GetProjectInfo(query: PageQuery) {
  return request({
    url: '/api/system/project/1/project_info/',
    method: 'get'
  });
}

export function GetHomeProjectInfo() {
  return request({
    url: '/api/shield/project/1/',
    method: 'get'
  });
}

export function UpdateProjectInfo(data: any) {
  return request({
    url: '/api/system/project/1/update_project_info/',
    method: 'put',
    data
  });
}
// 获取设备类型选项。
export const getDeviceTypes = () => {
  return request({
    url: '/api/system/sensortype/',
    method: 'get'
  });
};

// 获取监测点选项。
export const getMonitoringPoints = () => {
  return request({
    url: '/api/system/sensor/',
    method: 'get'
  });
};

// 根据传感器类型获取监测点。
export const getMonitoringPointsBySensorType = (sensorTypeId: number | string) => {
  return request({
    url: `/api/system/Statisticalreport/get_monitoring_points_by_sensortype/`,
    method: 'get',
    params: {
      sensortype_id: sensorTypeId
    }
  });
};

// 获取统计时间选项。
export const getStatisticalTimes = () => {
  return request({
    url: '/api/system/Statisticalreport/',
    method: 'get',
    params: {
      limit: 100, // 限制返回数量。
      ordering: '-statistical_time' // 按统计时间倒序排列。
    }
  });
};

// 获取统计报表数据。
export const getStatisticalReportData = (params: {
  device_type?: number | string;
  monitoring_point?: number | string;
  statistical_time?: string;
  start_date?: string;
  end_date?: string;
  [key: string]: any;
}) => {
  // 创建独立参数对象，避免修改调用方数据。
  const apiParams = { ...params };
  // 起止日期齐全时转换为后端范围查询格式。
  if (params.start_date && params.end_date) {
    apiParams.statistical_time__range = `${params.start_date},${params.end_date}`;
    // 删除原始日期参数，避免重复传递。
    delete apiParams.start_date;
    delete apiParams.end_date;
    debugLog('转换后的日期范围：', apiParams.statistical_time__range);
  }
  debugLog('请求统计报表数据，参数：', apiParams);
  return request({
    url: '/api/system/Statisticalreport/',
    method: 'get',
    params: apiParams
  }).then((response: any) => {
    debugLog('API 响应：', response);
    return response;
  }).catch((error: any) => {
    console.error('API 请求失败：', error);
    throw error;
  });
};
/** 获取图片。 */
export function getimage() {
	return request<string>({
		url: 'api/system/file/1/',
		method: 'get',
	});
}
