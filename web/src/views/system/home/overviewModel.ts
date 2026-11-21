import { isActiveCutterPosition } from '/@/constants/cutterPositions';

export type ToolType = 'roller' | 'scraper';
export type ToolParentType = 'DISC' | 'SCRAPER';
export type RowStatus = 'changed' | 'checked' | 'warning' | 'normal';
export type LifeStatus = 'life-low' | 'life-mid' | 'life-high' | 'life-unknown';

export interface ToolChangeApiItem {
  id?: number | string;
  cutter_position_no?: string;
  tool_parent_type?: string;
  tool_number?: string;
  warehouse_ring_no?: string | number;
  warehouse_open_time?: string;
  wear_condition?: string;
  wear_condition_display?: string;
  replacement_type?: string;
  replacement_type_display?: string;
  replacement_count?: number;
  is_replaced?: boolean;
  manufacturer?: string;
}

export interface ToolChangeRow {
  position: string;
  previousRing: number | string;
  previousReason: string;
  previousMileage: number | string;
  averageLife: number | string;
  total: string;
  manufacturer: string;
  status: RowStatus;
  lifeStatus: LifeStatus;
  lifeRatio: number | null;
}

// 按刀具类型筛选并汇总刀位行。
export function buildRows(records: ToolChangeApiItem[], apiType: ToolParentType): ToolChangeRow[] {
  const filtered = records.filter((item) =>
    normalizeToolType(item.tool_parent_type) === apiType
    && isActiveCutterPosition(item.cutter_position_no),
  );
  const grouped = filtered.reduce<Record<string, ToolChangeApiItem[]>>((result, item) => {
    const position = String(item.cutter_position_no);
    return { ...result, [position]: [...(result[position] ?? []), item] };
  }, {});

  return Object.entries(grouped)
    .map(([position, items]) => buildRow(position, items))
    .sort(compareLifeThenPosition);
}

// 汇总单个刀位的换刀记录与寿命状态。
export function buildRow(position: string, items: ToolChangeApiItem[]): ToolChangeRow {
  const sorted = [...items].sort(compareRecordDesc);
  const latest = sorted[0];
  const replaced = sorted.filter((item) => item.is_replaced);
  const latestReplaced = replaced[0];
  const prevReplaced = replaced[1];
  const latestRing = toNumber(latest?.warehouse_ring_no);
  const latestReplacedRing = toNumber(latestReplaced?.warehouse_ring_no);
  const prevReplacedRing = toNumber(prevReplaced?.warehouse_ring_no);
  const checkCount = sorted.length;
  const replacementCount = Number(latestReplaced?.replacement_count ?? replaced.length);
  const previousMileage = latestRing != null && latestReplacedRing != null ? latestRing - latestReplacedRing : '-';
  const averageLife = getAverageLife(items, latestReplaced);
  const lifeRatio = typeof previousMileage === 'number' && typeof averageLife === 'number' && averageLife > 0
    ? previousMileage / averageLife
    : null;
  const lifeStatus = getLifeStatus(lifeRatio);

  return {
    position,
    previousRing: latestReplaced?.warehouse_ring_no ?? '-',
    previousReason: getReasonLabel(latestReplaced),
    previousMileage,
    averageLife: typeof averageLife === 'number' ? Math.round(averageLife) : '-',
    total: `${replacementCount}/${checkCount}`,
    manufacturer: latestReplaced?.manufacturer || '-',
    status: getStatus(latest, latestRing, latestReplacedRing),
    lifeStatus,
    lifeRatio,
  };
}

// 优先使用同厂家样本计算平均寿命。
export function getAverageLife(items: ToolChangeApiItem[], latestReplaced: ToolChangeApiItem | undefined) {
  const manufacturer = normalizeManufacturer(latestReplaced?.manufacturer);
  const sameManufacturerLife = manufacturer
    ? getAverageLifeByItems(items.filter((item) => normalizeManufacturer(item.manufacturer) === manufacturer))
    : null;

  if (sameManufacturerLife != null) return sameManufacturerLife;
  return getAverageLifeByItems(items);
}

// 计算相邻换刀记录正环差的平均值。
export function getAverageLifeByItems(items: ToolChangeApiItem[]) {
  const replaced = items
    .filter((item) => item.is_replaced)
    .map((item) => ({ item, ring: toNumber(item.warehouse_ring_no) }))
    .filter((entry): entry is { item: ToolChangeApiItem; ring: number } => entry.ring != null)
    .sort((left, right) => left.ring - right.ring);

  const lifespans: number[] = [];
  for (let index = 1; index < replaced.length; index += 1) {
    const lifespan = replaced[index].ring - replaced[index - 1].ring;
    if (lifespan > 0) lifespans.push(lifespan);
  }

  if (lifespans.length === 0) return null;
  return lifespans.reduce((sum, item) => sum + item, 0) / lifespans.length;
}

// 根据寿命使用比例确定风险等级。
export function getLifeStatus(ratio: number | null): LifeStatus {
  if (ratio == null) return 'life-unknown';
  if (ratio <= 0.33) return 'life-low';
  if (ratio <= 0.66) return 'life-mid';
  return 'life-high';
}

// 判断刀位是否属于 Y 系列。
export function isYPosition(position: string) {
  return /^Y/i.test(position);
}

// 根据最新记录和环差确定换刀状态。
export function getStatus(latest: ToolChangeApiItem | undefined, latestRing: number | null, previousRing: number | null): RowStatus {
  if (latest?.is_replaced) return 'changed';
  if (latestRing != null && previousRing != null && latestRing - previousRing >= 80) return 'warning';
  if (latest) return 'checked';
  return 'normal';
}

// 获取换刀或检查原因的显示文案。
export function getReasonLabel(item: ToolChangeApiItem | undefined) {
  if (!item) return '-';
  const raw = item.replacement_type_display || item.replacement_type || item.wear_condition_display || item.wear_condition;
  return translateDictionary(raw, item.is_replaced ? '更换' : '检查');
}

// 将字典编码转换为显示文案。
export function translateDictionary(value: unknown, fallback: string) {
  const text = String(value || '').trim();
  if (!text) return fallback;
  const key = text.toUpperCase();
  const map: Record<string, string> = {
    COMPLETE: '整刀更换',
    REPAIR: '维修',
    GOOD: '良好',
    NORMAL: '正常磨损',
    MODERATE: '中度磨损',
    SEVERE: '严重磨损',
    ABNORMAL: '异常磨损',
    UNKNOWN: '未知',
    COMPLETE_REPLACEMENT: '整刀更换',
    TOOL_CHANGE: '更换',
    REPLACE: '更换',
    CHECK: '检查',
    INSPECTION: '检查',
  };
  return map[key] ?? text;
}

// 统一刀具类型编码及中心滚刀别名。
export function normalizeToolType(value: unknown): string {
  const text = String(value || '').trim().toUpperCase();
  if (text === 'CENTER_DISC' || text === 'CENTER') return 'DISC';
  return text;
}

// 去除厂家名称两端空白。
export function normalizeManufacturer(value: unknown): string {
  return String(value || '').trim();
}

// 按环号、开仓时间和编号降序比较记录。
export function compareRecordDesc(left: ToolChangeApiItem, right: ToolChangeApiItem) {
  const ringDiff = (toNumber(right.warehouse_ring_no) ?? -1) - (toNumber(left.warehouse_ring_no) ?? -1);
  if (ringDiff !== 0) return ringDiff;
  const timeDiff = new Date(right.warehouse_open_time || 0).getTime() - new Date(left.warehouse_open_time || 0).getTime();
  if (timeDiff !== 0) return timeDiff;
  return Number(right.id ?? 0) - Number(left.id ?? 0);
}


// 优先按寿命风险等级再按刀位比较行。
export function compareLifeThenPosition(left: ToolChangeRow, right: ToolChangeRow) {
  const leftLife = getLifeSortWeight(left.lifeStatus);
  const rightLife = getLifeSortWeight(right.lifeStatus);
  if (leftLife !== rightLife) return leftLife - rightLife;
  return comparePosition(left.position, right.position);
}

// 获取寿命风险等级的排序权重。
export function getLifeSortWeight(status: LifeStatus) {
  const weights: Record<LifeStatus, number> = {
    // 红色最紧急，其次黄色，绿色最后；无有效寿命数据排在末尾。
    'life-high': 0,
    'life-mid': 1,
    'life-low': 2,
    'life-unknown': 3,
  };
  return weights[status];
}

// 按 Y 系列优先、数字和后缀比较刀位。
export function comparePosition(left: string, right: string) {
  const leftIsY = isYPosition(left);
  const rightIsY = isYPosition(right);
  if (leftIsY !== rightIsY) return leftIsY ? -1 : 1;

  const leftNumber = Number(left.match(/\d+/)?.[0] ?? Number.MAX_SAFE_INTEGER);
  const rightNumber = Number(right.match(/\d+/)?.[0] ?? Number.MAX_SAFE_INTEGER);
  if (leftNumber !== rightNumber) return leftNumber - rightNumber;
  return left.localeCompare(right);
}

// 将输入转换为有限数值或空值。
export function toNumber(value: unknown) {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

// 格式化本地日期时间并保留无效日期文本。
export function formatDateTime(value: unknown) {
  if (!value) return '';
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hour = String(date.getHours()).padStart(2, '0');
  const minute = String(date.getMinutes()).padStart(2, '0');
  return `${year}/${month}/${day} ${hour}:${minute}`;
}
