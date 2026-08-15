/**
 * 换刀基本信息类型定义
 */
export interface WarehouseOpeningBasicInfoType {
  id?: number;
  warehouse_id: string;
  open_time: string;
  section?: string;
  ring_no: string;
  project: number;
  project_name?: string;
  shield_model?: number;
  shield_model_name?: string;
  opening_duration?: number;
  checked_tool_count?: number;
  replaced_tool_count?: number;
  last_ring_no?: string;
  rings_between_openings?: number;
  stratum_info_between?: Record<string, number>;
  stratum_info_between_list?: StratumInfoBetweenItem[];
  geological_conditions?: string;
  tool_change_date?: string;
  tool_change_duration?: number;
  usage_distance?: number;
  create_datetime?: string;
  update_datetime?: string;
  creator_name?: string;
  modifier_name?: string;
}

/**
 * 两次开仓间地层信息项
 */
export interface StratumInfoBetweenItem {
  stratum_type_code: string;
  stratum_type_name: string;
  ring_count: number;
}

/**
 * 地层信息数据项（用于表单提交）
 */
export interface APIResponseData {
  code?: number;
  data: any;
  msg?: string;
}
