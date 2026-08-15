/**
 * 刀具信息类型定义
 */
export interface ToolInfoType {
  id?: number;
  tool_id: string;
  tool_name: string;
  tool_category: number;
  tool_category_name?: string;
  manufacturer: string;
  production_date: string;
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
