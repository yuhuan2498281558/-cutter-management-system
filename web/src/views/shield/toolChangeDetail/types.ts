/**
 * 换刀明细类型定义（表格式）
 */
export interface ToolChangeDetail {
  id?: number;
  warehouse: number;
  warehouse_id_name?: string;

  // 刀位信息
  cutter_position?: number;
  cutter_position_no?: string;
  tool_parent_type?: string;

  // 刀具信息
  tool_number?: string;

  // 磨损情况
  wear_condition?: string;
  wear_condition_display?: string;

  // 是否更换
  is_replaced: boolean;

  // 累计更换次数（自动计算）
  replacement_count?: number;

  // 厂家
  manufacturer?: string;

  // 更换类型（仅当is_replaced=true时有效）
  replacement_type?: string;
  replacement_type_display?: string;

  // 维修部位（仅当replacement_type='REPAIR'时有效）
  repair_parts?: string[];

  // 品牌（仅当replacement_type='REPAIR'时有效）
  brand?: string;

  // 价格（仅当replacement_type='REPAIR'时有效）
  price?: number;

  // 刀具磨损更换图
  wear_image?: string;
  wear_image_url?: string;

  // 备注
  remark?: string;

  // 时间戳
  create_datetime?: string;
  update_datetime?: string;
}

/**
 * 批量创建请求
 */
export interface BatchCreateRequest {
  warehouse_id: number;
  details: ToolChangeDetail[];
}

/**
 * 刀位信息
 */
export interface CutterPosition {
  id: number;
  cutter_position_no: string;
  tool_type: string;
  tool_type_display?: string;
}
