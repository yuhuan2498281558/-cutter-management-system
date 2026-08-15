/**
 * 磨损明细类型定义
 */
export interface WearDetailType {
  id?: number;
  warehouse: number;
  warehouse_id_name?: string;
  cutter_position_no: string;
  tool: number;
  tool_id_name?: string;
  wear_type?: number;
  wear_type_name?: string;
  wear_degree?: string;
  is_abnormal: boolean;
  abnormal_cause?: number;
  abnormal_cause_name?: string;
  photo_url?: string;
  inspect_time?: string;
  remark?: string;
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
