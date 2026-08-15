/**
 * 异常原因字典类型定义
 */
export interface AbnormalCauseDictType {
  id?: number;
  cause_name: string;
  cause_code: string;
  description?: string;
  create_datetime?: string;
  update_datetime?: string;
}

export interface APIResponseData {
  code?: number;
  data: any;
  msg?: string;
}
