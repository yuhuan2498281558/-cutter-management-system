/**
 * 地层基本信息类型定义
 */
export interface StratumBasicInfoType {
  id?: number;
  project: number;
  ring_no: string;
  stratum_info: string;
  burial_depth?: number;
  create_datetime?: string;
  update_datetime?: string;
  creator_name?: string;
  modifier_name?: string;
}

export interface APIResponseData {
  code?: number;
  data: any;
  msg?: string;
}
