/**
 * 项目信息类型定义
 */
export interface ProjectInfoType {
  id?: number;
  project_id: string;
  project_name: string;
  location?: string;
  excavation_diameter?: number;
  tunnel_length?: number;
  budget?: number | string;
  estimated_time?: string;
  actual_time?: string;
  project_introduction?: string;
  create_datetime?: string;
  update_datetime?: string;
  creator_name?: string;
  modifier_name?: string;
}

export interface APIResponseData<T = any> {
  code?: number;
  data: T;
  msg?: string;
}
