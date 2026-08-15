/**
 * 换刀明细类型定义
 */
export interface WarehouseOpeningDetailType {
  id?: number;
  warehouse: number;
  warehouse_id_name?: string;
  replace_part: string;  // 更换部位：SEAL-密封件, BEARING-轴承, TOOL-刀具
  is_replaced: boolean;
  old_tool?: number;
  old_tool_name?: string;
  old_tool_number?: string;  // 旧刀具编号（可手动输入）
  new_tool?: number;
  new_tool_name?: string;
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
