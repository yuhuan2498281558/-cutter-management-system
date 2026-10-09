/**
 * 地层基本信息类型定义
 */
export interface StratumBasicInfoType {
  id?: number;
  project: number;
  ring_no: string;
  stratum_type_ratios?: Record<string, number>;
  /** 每环纵断面面积业务分类；原岩性数据单独保留。 */
  longitudinal_type_ratios?: Partial<Record<'AREA_CLAY_SAND' | 'AREA_SOFT_HARD' | 'AREA_SOFT_SOIL' | 'AREA_WEAK_GRANITE' | 'AREA_BEDROCK_PROTRUSION' | 'AREA_BOULDER' | 'OTHER_IDENTIFIED' | 'UNRESOLVED', number>>;
  engineering_zones_list?: Array<{ code: string; name: string }>;
  longitudinal_area_notes?: string[];
  rock_types_list?: Array<{ code: string; name: string; percent: number }>;
  /** Historical engineering conditions; not cross-section rock types. */
  stratum_types_list?: Array<{ code: string; name: string; description?: string }>;
  stratum_info: string;
  burial_depth?: number;
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
