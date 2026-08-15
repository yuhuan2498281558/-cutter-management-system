import { request } from '/@/utils/service';

const API_PREFIX = '/api/shield/analysis/';

export interface AnalysisFilterParams {
  project?: number | string;
  shield_machine?: number | string;
  start_ring?: string;
  end_ring?: string;
  stratum_type?: string;
  stratum_types?: string | string[];
  tool_parent_type?: string;
  tool_type_name?: string;
  tool_type_names?: string | string[];
  cost_type?: string;
  cost_types?: string | string[];
  manufacturer?: string;
  manufacturers?: string | string[];
}

/** 分析筛选项 */
export function getFilterOptions(params: AnalysisFilterParams = {}) {
  return request({ url: API_PREFIX + 'filter_options/', method: 'get', params });
}

/** 概览仪表盘数据 */
export function getOverview(params: AnalysisFilterParams = {}) {
  return request({ url: API_PREFIX + 'overview/', method: 'get', params });
}

/** 成本构成概览 */
export function getCostOverview(params: AnalysisFilterParams = {}) {
  return request({ url: API_PREFIX + 'cost_overview/', method: 'get', params });
}

/** 成本时序趋势 */
export function getCostTrend(params: AnalysisFilterParams = {}) {
  return request({ url: API_PREFIX + 'cost_trend/', method: 'get', params });
}

/** 各厂家成本对比 */
export function getBrandCost(params: AnalysisFilterParams = {}) {
  return request({ url: API_PREFIX + 'brand_cost/', method: 'get', params });
}

/** 各厂家平均单价时序趋势 */
export function getBrandPriceTrend(params: AnalysisFilterParams = {}) {
  return request({ url: API_PREFIX + 'brand_price_trend/', method: 'get', params });
}

/** 各厂家刀具性能时序趋势（异常率 / 正常磨损率） */
export function getBrandPerformanceTrend(params: AnalysisFilterParams = {}) {
  return request({ url: API_PREFIX + 'brand_performance_trend/', method: 'get', params });
}

/** 磨损等级分布 */
export function getWearDistribution(params: AnalysisFilterParams = {}) {
  return request({ url: API_PREFIX + 'wear_distribution/', method: 'get', params });
}

/** 磨损率时序趋势 */
export function getWearTrend(params: AnalysisFilterParams = {}) {
  return request({ url: API_PREFIX + 'wear_trend/', method: 'get', params });
}

/** 自定义分析字段 */
export function getCustomFields() {
  return request({ url: API_PREFIX + 'custom_fields/', method: 'get' });
}

/** 自定义分析图表 */
export function getCustomChart(params: AnalysisFilterParams & {
  chart_type?: 'line' | 'matrix';
  x_field?: string;
  y_field?: string;
  x_fields?: string | string[];
  y_fields?: string | string[];
  metrics?: string | string[];
} = {}) {
  return request({ url: API_PREFIX + 'custom_chart/', method: 'get', params });
}
