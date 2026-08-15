/**
 * 刀具相关类型定义
 */

// 刀具类型枚举
export enum ToolType {
  DISC = 'DISC',
  RIPPER = 'RIPPER',
  SCRAPER = 'SCRAPER'
}

// 刀位信息接口
export interface CutterPosition {
  code: string;
  type: '滚刀' | '刮刀';
  x: number;
  y: number;
}

// 刀具信息接口
export interface CutterInfo {
  code: string;
  type: '滚刀' | '刮刀';
  x?: number;
  y?: number;
}

// 盾构机信息接口
export interface ShieldMachine {
  id: number | string;
  shield_model_id: string;
  shield_model: string;
}

// CRUD 请求参数接口
export interface CrudQuery {
  page?: number;
  limit?: number;
  shield_machine?: number | string;
  [key: string]: any;
}

export interface CrudForm {
  id?: number | string;
  shield_machine?: number | string;
  cutter_position_no?: string;
  tool_type?: string;
  [key: string]: any;
}

export interface CrudRow {
  id: number | string;
  [key: string]: any;
}
