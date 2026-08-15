/**
 * 刀位信息API接口
 */
import { request } from '/@/utils/service';

const BIMFACE_VIEW_TOKEN_CACHE_KEY = 'bimface:viewToken';
const BIMFACE_VIEW_TOKEN_CACHE_MS = 11 * 60 * 60 * 1000;

export type WearCondition = 'GOOD' | 'NORMAL' | 'MODERATE' | 'SEVERE' | 'ABNORMAL' | 'UNKNOWN' | null;

export interface CutterStatus {
  tool_type: string;
  wear_condition: WearCondition;
  is_replaced: boolean | null;
}

export interface CutterModelMapping {
  id: number | string;
  model_point_code: string;
  component_id?: string | null;
  cutter_position_no: string;
  tool_type?: string;
  tool_type_display?: string;
  tool_name?: string;
  screen_x?: number | null;
  screen_y?: number | null;
  sort_no?: number;
}

export async function getBimfaceViewToken(forceRefresh = false): Promise<string> {
  if (!forceRefresh) {
    try {
      const cached = JSON.parse(localStorage.getItem(BIMFACE_VIEW_TOKEN_CACHE_KEY) || 'null');
      if (cached?.token && cached?.expiresAt > Date.now()) return cached.token;
    } catch {
      localStorage.removeItem(BIMFACE_VIEW_TOKEN_CACHE_KEY);
    }
  } else {
    localStorage.removeItem(BIMFACE_VIEW_TOKEN_CACHE_KEY);
  }

  const res = await request({ url: '/api/bimface/view-token/', method: 'get' });
  const token = res?.viewToken ?? res?.data?.viewToken;
  if (!token) throw new Error('未获取到 viewToken');

  localStorage.setItem(
    BIMFACE_VIEW_TOKEN_CACHE_KEY,
    JSON.stringify({ token, expiresAt: Date.now() + BIMFACE_VIEW_TOKEN_CACHE_MS }),
  );
  return token;
}

export async function getAllCutterStatus(): Promise<Record<string, CutterStatus>> {
  try {
    const res = await request({
      url: '/api/bimface/cutter-status/',
      method: 'get',
    });
    return res?.data ?? res ?? {};
  } catch {
    return {};
  }
}

export async function getActiveCutterModelMappings(): Promise<CutterModelMapping[]> {
  try {
    const res = await request({
      url: '/api/bimface/cutter-model-mapping/',
      method: 'get',
    });
    return res?.data ?? res ?? [];
  } catch {
    return [];
  }
}

export interface CutterModelMappingSaveItem {
  cutter_position_no: string;
  model_point_code?: string;
  component_id?: string | null;
  screen_x?: number | null;
  screen_y?: number | null;
  sort_no?: number;
  is_active?: boolean;
}

export async function saveCutterModelMappings(items: CutterModelMappingSaveItem[]) {
  const res = await request({
    url: '/api/shield/cutter_model_mapping/bulk_upsert/',
    method: 'post',
    data: { items },
  });
  return res?.data ?? res;
}

export interface CurrentCutterInfo {
  name: string;
  serialNumber: string;
  manufacturer?: string;
  brand?: string;
  price?: number;
  startRing: number;
  installDate?: string;
}

export interface CutterHistoryInfo {
  toolTypeName?: string;
  serialNumber: string;
  startRing: number | string;
  endRing: number | string;
  usageDuration: number;
  drivingDistance: number;
  price: number;
  manufacturer: string;
  replaceDate: string;
  replaceReason?: string;
  ringsUsed?: number | null;
  wearType?: string;
  wearDegree?: string;
  replacementTypeDisplay?: string;
  brand?: string;
  replacePart?: string;
  remark?: string;
}

export interface CutterPositionInfo {
  code: string;
  type: string;
  latestWearType?: string;
  current?: CurrentCutterInfo;
  history?: CutterHistoryInfo[];
}

const WEAR_LABELS: Record<string, string> = {
  GOOD: '良好',
  NORMAL: '正常磨损',
  MODERATE: '中度磨损',
  SEVERE: '严重磨损',
  ABNORMAL: '异常磨损',
  UNKNOWN: '未知',
};

const REPLACEMENT_LABELS: Record<string, string> = {
  COMPLETE: '整刀更换',
  REPAIR: '维修',
};

const TOOL_PARENT_LABELS: Record<string, string> = {
  DISC: '滚刀',
  RIPPER: '撕裂刀',
  SCRAPER: '刮刀',
  CENTER_DISC: '中心滚刀',
  CENTER: '中心滚刀',
};

function labelFromMap(value: unknown, map: Record<string, string>) {
  if (!value) return '';
  const key = String(value).trim().toUpperCase();
  return map[key] ?? String(value);
}

function toolTypeLabel(value: unknown, fallback?: unknown) {
  const raw = value || fallback;
  if (!raw) return '-';
  const text = String(raw).trim();
  return TOOL_PARENT_LABELS[text.toUpperCase()] ?? text;
}

export async function getCutterInfo(code: string): Promise<CutterPositionInfo> {
  try {
    const res = await request({
      url: '/api/shield/tool_change_detail/get_cutter_position_history/',
      method: 'get',
      params: { cutter_position_no: code },
    });

    const data = res?.data ?? res;
    const rawHistory: any[] = data?.history ?? [];
    const positionType = toolTypeLabel(data.tool_parent_type, data.tool_parent_type_display);
    data.tool_parent_type_display = positionType;

    const history: CutterHistoryInfo[] = rawHistory.map((h: any) => ({
      toolTypeName: toolTypeLabel(h.tool_type_name ?? h.tool_parent_type_display, h.tool_parent_type),
      serialNumber: h.tool_number ?? h.serialNumber ?? '-',
      startRing: h.start_ring ?? h.startRing ?? 0,
      endRing: h.end_ring ?? h.endRing ?? '-',
      usageDuration: h.usage_duration ?? h.usageDuration ?? 0,
      drivingDistance: h.driving_distance ?? h.drivingDistance ?? 0,
      price: h.price ?? 0,
      manufacturer: h.manufacturer ?? '-',
      brand: h.brand ?? '',
      replaceDate: h.open_time ?? h.replaceDate ?? '-',
      replaceReason: h.wear_type_display ?? labelFromMap(h.wear_type, WEAR_LABELS) ?? h.replaceReason,
      ringsUsed: h.rings_used ?? null,
      wearType: h.wear_type_display ?? labelFromMap(h.wear_type, WEAR_LABELS),
      wearDegree: h.wear_degree_display ?? labelFromMap(h.wear_degree, REPLACEMENT_LABELS),
      replacementTypeDisplay: h.replacement_type_display ?? labelFromMap(h.replacement_type, REPLACEMENT_LABELS),
      replacePart: h.replace_part,
      remark: h.remark,
    }));

    // 最新一条换刀记录作为"当前刀具"
    const latest = rawHistory[0];
    const latestWearType = latest?.wear_type_display ?? labelFromMap(latest?.wear_type, WEAR_LABELS) ?? '-';
    const current: CurrentCutterInfo | undefined = latest
      ? {
          name: toolTypeLabel(latest.tool_type_name ?? latest.tool_parent_type_display, latest.tool_parent_type ?? data.tool_parent_type_display),
          serialNumber: latest.tool_number || '-',
          manufacturer: latest.manufacturer || '-',
          brand: latest.brand ?? '',
          price: latest.price ?? 0,
          startRing: latest.start_ring ?? 0,
          installDate: latest.open_time,
        }
      : undefined;

    return {
      code,
      type: data.tool_parent_type_display ?? (code.match(/[SGH]/) ? '刮刀' : '滚刀'),
      normalizedType: positionType,
      latestWearType,
      current,
      history,
    };
  } catch {
    // 接口失败时降级返回基本信息
    return {
      code,
      type: code.match(/[SGH]/) ? '刮刀' : '滚刀',
    };
  }
}
