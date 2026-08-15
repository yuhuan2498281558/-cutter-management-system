/**
 * 刀具类型类型定义
 */
export interface ToolTypeType {
  id?: number;
  tool_category: string;
  tool_name: string;
  tool_number?: string;
  cutter_position_no?: string;
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
