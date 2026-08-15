/**
 * 磨损类型字典类型定义
 */
export interface WearTypeDictType {
  id?: number;
  wear_type_name: string;
  wear_type_code: string;
  description?: string;
  create_datetime?: string;
  update_datetime?: string;
}

export interface APIResponseData {
  code?: number;
  data: any;
  msg?: string;
}
