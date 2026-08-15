/**
 * 盾构机基本信息类型定义
 */
export interface ShieldMachineBasicInfoType {
  id?: number;
  shield_model_id: string;
  shield_model: string;
  cutter_position_no: string;
  create_datetime?: string;
  update_datetime?: string;
}

export interface APIResponseData {
  code?: number;
  data: any;
  msg?: string;
}
