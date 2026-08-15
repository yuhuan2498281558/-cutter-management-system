<template>
  <section class="tool-change-overview">
    <header class="overview-header">
      <div class="title-block">
        <h2>盾构机换刀情况表</h2>
        <div class="meta-row">
          <span>当前环号：{{ latestRingNo || '暂无' }}</span>
          <span>更新时间：{{ latestOpenTime || '暂无开仓记录' }}</span>
        </div>
      </div>
      <div class="header-actions">
        <button class="back-button" type="button" @click="goHome">返回首页</button>
        <div class="tool-tabs" role="tablist" aria-label="刀具类型">
          <button
            v-for="item in toolTypes"
            :key="item.value"
            type="button"
            :class="{ active: activeType === item.value }"
            @click="activeType = item.value; selectedPosition = ''"
          >
            {{ item.label }}
          </button>
        </div>
      </div>
    </header>

    <div class="overview-body">
      <div class="drawing-panel">
        <div class="drawing-title">
          <span>{{ currentTool.label }}分布示意</span>
          <span>{{ loading ? '加载中' : `共 ${currentRows.length} 个刀位` }}</span>
        </div>
        <div class="cutter-map">
          <div class="map-figure">
            <img src="/cutterhead-placeholder.svg" alt="刀盘示意图" />
            <svg
              class="marker-layer"
              viewBox="0 0 1900 2100"
              aria-label="刀位轮廓图层"
            >
              <g
                v-for="row in currentRows"
                :key="row.position"
                class="marker-group"
                :class="{ selected: isSelected(row.position) }"
                role="button"
                tabindex="0"
                @click="selectPosition(row.position)"
                @keydown.enter="selectPosition(row.position)"
              >
                <title>{{ '刀位 ' + row.position }}</title>
                <circle :cx="getMarker(row).x" :cy="getMarker(row).y" :r="isSelected(row.position) ? 28 : 18" :class="['marker-dot', row.lifeStatus, { selected: isSelected(row.position) }]" />
                <text :x="getMarker(row).x" :y="getMarker(row).y - 28" class="marker-label">{{ row.position }}</text>
              </g>
            </svg>
          </div>
          <div v-if="!loading && currentRows.length === 0" class="empty-map">
            暂无{{ currentTool.label }}换刀数据
          </div>
        </div>
        <div class="drawing-note">
          <span class="legend life-low"></span><span>{{ '\u5bff\u547d\u4f59\u91cf\u5145\u8db3' }}</span>
          <span class="legend life-mid"></span><span>{{ '\u5bff\u547d\u8fdb\u5165\u5173\u6ce8\u533a' }}</span>
          <span class="legend life-high"></span><span>{{ '\u63a5\u8fd1\u6216\u8d85\u8fc7\u5e73\u5747\u5bff\u547d' }}</span>
        </div>
        <div class="position-tags" aria-label="刀位状态">
          <button
            v-for="row in positionTagRows"
            :key="row.position"
            type="button"
            :class="['position-tag', row.lifeStatus, { selected: isSelected(row.position) }]"
            @click="selectPosition(row.position)"
          >
            <span class="tag-code">{{ row.position }}</span>
            <span class="tag-count">{{ row.total }}</span>
          </button>
          <span v-if="!loading && currentRows.length === 0" class="position-tag empty">暂无刀位数据</span>
        </div>
      </div>

      <div class="table-panel">
        <div class="table-meta">
          <strong>{{ currentTool.label }}换刀明细</strong>
          <span v-if="loading">正在加载接口数据</span>
          <span v-else-if="loadError">{{ loadError }}</span>
          <span v-else>累计换刀 {{ totalChanged }} 次</span>
        </div>

        <div class="table-grid">
          <div class="table-scroll">
            <tool-change-table
              :rows="splitRows.left"
              :selected-position="selectedPosition"
              @select="selectPosition"
            />
          </div>
          <div class="table-scroll">
            <tool-change-table
              :rows="splitRows.right"
              :selected-position="selectedPosition"
              @select="selectPosition"
            />
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed, defineComponent, h, onMounted, ref } from 'vue';
import { ACTIVE_CUTTER_POSITIONS, isActiveCutterPosition } from '/@/constants/cutterPositions';
import { request } from '/@/utils/service';

type ToolType = 'roller' | 'scraper' | 'ripper';
type ToolParentType = 'DISC' | 'SCRAPER' | 'RIPPER';
type RowStatus = 'changed' | 'checked' | 'warning' | 'normal';
type LifeStatus = 'life-low' | 'life-mid' | 'life-high' | 'life-unknown';

interface ToolChangeApiItem {
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

interface ToolChangeRow {
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

const ToolChangeTable = defineComponent({
  name: 'ToolChangeTable',
  props: {
    rows: {
      type: Array as () => ToolChangeRow[],
      required: true,
    },
    selectedPosition: {
      type: String,
      default: '',
    },
  },
  emits: ['select'],
  setup(props, { emit }) {
    return () =>
      h('table', { class: 'change-table' }, [
        h('colgroup', [
          h('col', { class: 'col-position' }),
          h('col', { class: 'col-ring' }),
          h('col', { class: 'col-reason' }),
          h('col', { class: 'col-mileage' }),
          h('col', { class: 'col-life' }),
          h('col', { class: 'col-total' }),
        ]),
        h('thead', [
          h('tr', [
            h('th', '\u5200\u4f4d\u53f7'),
            h('th', '\u4e0a\u6b21\u6362\u5200(\u73af)'),
            h('th', '\u4e0a\u6b21\u66f4\u6362\u539f\u56e0'),
            h('th', '\u7d2f\u8ba1\u63a8\u8fdb(\u73af)'),
            h('th', '\u5e73\u5747\u5bff\u547d(\u73af)'),
            h('th', '\u7d2f\u8ba1\u6362\u5200/\u68c0\u67e5'),
          ]),
        ]),
        h(
          'tbody',
          props.rows.length > 0
            ? props.rows.map((row) =>
                h(
                  'tr',
                  {
                    key: row.position,
                    class: [row.lifeStatus, { selected: row.position === props.selectedPosition }],
                    tabindex: 0,
                    onClick: () => emit('select', row.position),
                    onKeydown: (event: KeyboardEvent) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        emit('select', row.position);
                      }
                    },
                  },
                  [
                    h('td', { class: ['position-cell', row.lifeStatus] }, row.position),
                    h('td', row.previousRing),
                    h('td', row.previousReason),
                    h('td', { class: ['mileage-cell', row.lifeStatus] }, row.previousMileage),
                    h('td', row.averageLife),
                    h('td', row.total),
                  ],
                ),
              )
            : [h('tr', [h('td', { class: 'empty-cell', colspan: 6 }, '暂无数据')])],
        ),
      ]);
  },
});

const toolTypes: Array<{ value: ToolType; label: string; apiType: ToolParentType }> = [
  { value: 'roller', label: '滚刀', apiType: 'DISC' },
  { value: 'scraper', label: '刮刀', apiType: 'SCRAPER' },
  { value: 'ripper', label: '撕裂刀', apiType: 'RIPPER' },
];

const activeType = ref<ToolType>('roller');
const loading = ref(false);
const loadError = ref('');
const apiRows = ref<ToolChangeApiItem[]>([]);
const selectedPosition = ref('');
const emit = defineEmits<{ (e: 'back'): void }>();

const currentTool = computed(() => toolTypes.find((item) => item.value === activeType.value) ?? toolTypes[0]);
const latestRecord = computed(() => [...apiRows.value].sort(compareRecordDesc)[0]);
const latestRingNo = computed(() => latestRecord.value?.warehouse_ring_no ? String(latestRecord.value.warehouse_ring_no) : '');
const latestOpenTime = computed(() => formatDateTime(latestRecord.value?.warehouse_open_time));
const currentRows = computed(() => buildRows(apiRows.value, currentTool.value.apiType));
const positionTagRows = computed(() => [...currentRows.value].sort(compareLifeThenPosition));
const splitRows = computed(() => {
  const midpoint = Math.ceil(currentRows.value.length / 2);
  return {
    left: currentRows.value.slice(0, midpoint),
    right: currentRows.value.slice(midpoint),
  };
});
const totalChanged = computed(() => currentRows.value.reduce((sum, item) => sum + Number(item.total.split('/')[0] || 0), 0));

const positionMap = computed(() => {
  const result: Record<string, { x: number; y: number }> = {};
  for (const item of ACTIVE_CUTTER_POSITIONS) {
    result[item.code.toUpperCase()] = { x: item.x, y: item.y };
  }
  return result;
});

async function loadToolChangeData() {
  loading.value = true;
  loadError.value = '';
  try {
    const res = await request({
      url: '/api/shield/tool_change_detail/overview/',
      method: 'get',
    });
    apiRows.value = extractList<ToolChangeApiItem>(res);
  } catch {
    apiRows.value = [];
    loadError.value = '接口加载失败';
  } finally {
    loading.value = false;
  }
}

function extractList<T>(res: any): T[] {
  let payload = res?.data ?? res ?? [];
  if (payload && !Array.isArray(payload) && payload.code !== undefined && payload.data !== undefined) {
    payload = payload.data;
  }
  if (payload && !Array.isArray(payload) && Array.isArray(payload.results)) {
    return payload.results;
  }
  return Array.isArray(payload) ? payload : [];
}

async function fetchPagedList<T>(url: string) {
  const result: T[] = [];
  let page = 1;
  let hasNext = true;

  while (hasNext) {
    const res = await request({
      url,
      method: 'get',
      params: { page, limit: 999 },
    });
    result.push(...extractList<T>(res));
    hasNext = Boolean(res?.is_next);
    page += 1;
  }

  return result;
}

function buildRows(records: ToolChangeApiItem[], apiType: ToolParentType): ToolChangeRow[] {
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
    .sort((left, right) => comparePosition(left.position, right.position));
}

function buildRow(position: string, items: ToolChangeApiItem[]): ToolChangeRow {
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

function getAverageLife(items: ToolChangeApiItem[], latestReplaced: ToolChangeApiItem | undefined) {
  const manufacturer = normalizeManufacturer(latestReplaced?.manufacturer);
  const sameManufacturerLife = manufacturer
    ? getAverageLifeByItems(items.filter((item) => normalizeManufacturer(item.manufacturer) === manufacturer))
    : null;

  if (sameManufacturerLife != null) return sameManufacturerLife;
  return getAverageLifeByItems(items);
}

function getAverageLifeByItems(items: ToolChangeApiItem[]) {
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

function getLifeStatus(ratio: number | null): LifeStatus {
  if (ratio == null) return 'life-unknown';
  if (ratio <= 0.33) return 'life-low';
  if (ratio <= 0.66) return 'life-mid';
  return 'life-high';
}

function getMarker(row: ToolChangeRow) {
  const code = row.position.split('-')[0].toUpperCase();
  const matched = positionMap.value[code];
  if (matched) return matched;

  const index = currentRows.value.findIndex((item) => item.position === row.position);
  const angle = (Math.PI * 2 * index) / Math.max(currentRows.value.length, 1) - Math.PI / 2;
  const radius = activeType.value === 'ripper' ? 760 : 620;
  return {
    x: 1137 + Math.cos(angle) * radius,
    y: 1049 + Math.sin(angle) * radius,
  };
}

function goHome() {
  emit('back');
}

function isYPosition(position: string) {
  return /^Y/i.test(position);
}

function getStatus(latest: ToolChangeApiItem | undefined, latestRing: number | null, previousRing: number | null): RowStatus {
  if (latest?.is_replaced) return 'changed';
  if (latestRing != null && previousRing != null && latestRing - previousRing >= 80) return 'warning';
  if (latest) return 'checked';
  return 'normal';
}

function getReasonLabel(item: ToolChangeApiItem | undefined) {
  if (!item) return '-';
  const raw = item.replacement_type_display || item.replacement_type || item.wear_condition_display || item.wear_condition;
  return translateDictionary(raw, item.is_replaced ? '更换' : '检查');
}

function selectPosition(position: string) {
  selectedPosition.value = selectedPosition.value === position ? '' : position;
}

function isSelected(position: string) {
  return selectedPosition.value === position;
}

function translateDictionary(value: unknown, fallback: string) {
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

function normalizeToolType(value: unknown): string {
  const text = String(value || '').trim().toUpperCase();
  if (text === 'CENTER_DISC' || text === 'CENTER') return 'DISC';
  if (text === 'TEAR') return 'RIPPER';
  return text;
}

function normalizeManufacturer(value: unknown): string {
  return String(value || '').trim();
}

function compareRecordDesc(left: ToolChangeApiItem, right: ToolChangeApiItem) {
  const ringDiff = (toNumber(right.warehouse_ring_no) ?? -1) - (toNumber(left.warehouse_ring_no) ?? -1);
  if (ringDiff !== 0) return ringDiff;
  const timeDiff = new Date(right.warehouse_open_time || 0).getTime() - new Date(left.warehouse_open_time || 0).getTime();
  if (timeDiff !== 0) return timeDiff;
  return Number(right.id ?? 0) - Number(left.id ?? 0);
}


function compareLifeThenPosition(left: ToolChangeRow, right: ToolChangeRow) {
  const leftLife = getLifeSortWeight(left.lifeStatus);
  const rightLife = getLifeSortWeight(right.lifeStatus);
  if (leftLife !== rightLife) return leftLife - rightLife;
  return comparePosition(left.position, right.position);
}

function getLifeSortWeight(status: LifeStatus) {
  const weights: Record<LifeStatus, number> = {
    'life-low': 0,
    'life-mid': 1,
    'life-high': 2,
    'life-unknown': 3,
  };
  return weights[status];
}

function comparePosition(left: string, right: string) {
  const leftIsY = isYPosition(left);
  const rightIsY = isYPosition(right);
  if (leftIsY !== rightIsY) return leftIsY ? -1 : 1;

  const leftNumber = Number(left.match(/\d+/)?.[0] ?? Number.MAX_SAFE_INTEGER);
  const rightNumber = Number(right.match(/\d+/)?.[0] ?? Number.MAX_SAFE_INTEGER);
  if (leftNumber !== rightNumber) return leftNumber - rightNumber;
  return left.localeCompare(right);
}

function toNumber(value: unknown) {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function formatDateTime(value: unknown) {
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

onMounted(() => {
  loadToolChangeData();
});
</script>

<style scoped>
.tool-change-overview {
  height: 100%;
  min-height: 0;
  background: #f4f6f8;
  color: #172033;
  display: flex;
  flex-direction: column;
  padding: 14px;
  box-sizing: border-box;
}

.overview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
}

.title-block {
  display: flex;
  align-items: baseline;
  gap: 18px;
  min-width: 0;
}

.title-block h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0;
  flex-shrink: 0;
}

.meta-row {
  display: flex;
  gap: 16px;
  margin-top: 0;
  color: #475569;
  font-size: 16px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.back-button {
  height: 34px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #fff;
  color: #1e293b;
  padding: 0 12px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}

.back-button:hover {
  background: #f1f5f9;
}

.tool-tabs {
  display: inline-flex;
  border: 1px solid #cbd5e1;
  background: #fff;
  border-radius: 6px;
  overflow: hidden;
  flex-shrink: 0;
}

.tool-tabs button {
  min-width: 76px;
  height: 34px;
  border: 0;
  border-right: 1px solid #cbd5e1;
  background: #fff;
  color: #475569;
  cursor: pointer;
  font-size: 13px;
}

.tool-tabs button:last-child {
  border-right: 0;
}

.tool-tabs button.active {
  background: #145da0;
  color: #fff;
  font-weight: 600;
}

.overview-body {
  min-height: 0;
  flex: 1;
  display: grid;
  grid-template-columns: minmax(500px, 0.64fr) minmax(620px, 1fr);
  gap: 8px;
}

.drawing-panel,
.table-panel {
  min-height: 0;
  background: #fff;
  border: 1px solid #d7dde5;
  border-radius: 4px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.drawing-title,
.table-meta {
  height: 36px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #d7dde5;
  font-size: 13px;
}

.cutter-map {
  flex: 0 1 auto;
  width: 100%;
  aspect-ratio: 1 / 1;
  max-height: calc(100% - 154px);
  min-height: 0;
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  background: #f8fafc;
  overflow: hidden;
  padding: 0;
  box-sizing: border-box;
}

.map-figure {
  width: 100%;
  height: 100%;
  position: relative;
  line-height: 0;
}

.map-figure img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.marker-layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: auto;
}

.marker-group {
  cursor: pointer;
  outline: none;
}

.marker-dot {
  stroke: #111827;
  stroke-width: 3;
  transition: r 0.16s ease, fill 0.16s ease, stroke 0.16s ease, stroke-width 0.16s ease, filter 0.16s ease;
}

.marker-dot.life-low {
  fill: #22c55ed1;
}

.marker-dot.life-mid {
  fill: #f59e0bdb;
}

.marker-dot.life-high {
  fill: #dc2626e6;
}

.marker-dot.life-unknown {
  fill: #94a3b8c7;
}

.marker-dot.selected {
  fill: #2563eb;
  stroke: #f8fafc;
  stroke-width: 8;
  filter: drop-shadow(0 0 10px rgba(37, 99, 235, 0.75));
}

.marker-label {
  fill: #0f172a;
  font-size: 34px;
  font-weight: 700;
  text-anchor: middle;
  paint-order: stroke;
  stroke: #fff;
  stroke-width: 8px;
}

.empty-map {
  position: absolute;
  left: 50%;
  bottom: 18px;
  transform: translateX(-50%);
  color: #64748b;
  font-size: 13px;
}

.drawing-note {
  height: 32px;
  border-top: 1px solid #d7dde5;
  border-bottom: 1px solid #d7dde5;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
}

.legend {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  margin-right: -6px;
}

.legend.life-low {
  background: linear-gradient(135deg, #dcfce7 0%, #22c55e 100%);
}

.legend.life-mid {
  background: linear-gradient(135deg, #fef3c7 0%, #f59e0b 100%);
}

.legend.life-high {
  background: linear-gradient(135deg, #fecaca 0%, #dc2626 100%);
}

.position-tags {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(48px, 1fr));
  gap: 2px;
  flex: 1;
  min-height: 118px;
  padding: 5px;
  overflow: auto;
  border-top: 0;
  background: #fff;
  align-content: start;
}

.position-tag {
  height: 20px;
  min-width: 52px;
  border: 1px solid #cbd5e1;
  border-left-width: 3px;
  border-radius: 3px;
  background: #f8fafc;
  color: #1f2937;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  padding: 0 4px;
  cursor: pointer;
  font-size: 11px;
  line-height: 1;
}

.position-tag.life-low {
  border-left-color: #16a34a;
  background: linear-gradient(90deg, #dcfce7 0%, #f8fafc 88%);
}

.position-tag.life-mid {
  border-left-color: #f59e0b;
  background: linear-gradient(90deg, #fef3c7 0%, #fffbeb 88%);
}

.position-tag.life-high {
  border-left-color: #dc2626;
  background: linear-gradient(90deg, #fecaca 0%, #fef2f2 88%);
}

.position-tag.life-unknown {
  border-left-color: #94a3b8;
}

.position-tag.selected {
  border-color: #1d4ed8;
  background: #eff6ff;
  color: #0f172a;
  box-shadow: inset 0 0 0 1px #1d4ed8;
}

.position-tag.empty {
  grid-column: 1 / -1;
  justify-content: center;
  color: #64748b;
  cursor: default;
}

.tag-code {
  min-width: max-content;
  overflow: visible;
  text-overflow: clip;
  white-space: nowrap;
  font-weight: 700;
}

.tag-count {
  display: none;
  color: #64748b;
  font-size: 11px;
  flex-shrink: 0;
}

.table-meta strong {
  font-size: 14px;
}

.table-meta span {
  color: #64748b;
  font-size: 12px;
}

.table-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 5px;
  padding: 5px;
  background: #f8fafc;
}

.table-scroll {
  min-height: 0;
  overflow: auto;
  border: 1px solid #d7dde5;
  background: #fff;
}

:deep(.change-table) {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 11px;
  color: #1f2937;
}

:deep(.change-table th),
:deep(.change-table td) {
  border: 1px solid #d8dee8;
  padding: 4px 4px;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  box-sizing: border-box;
}

:deep(.change-table th) {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f1f5f9;
  color: #1e293b;
  font-weight: 600;
  line-height: 16px;
}

:deep(.change-table tbody tr.life-low td) {
  background: #fff;
}

:deep(.change-table tbody tr.life-mid td) {
  background: #fff;
}

:deep(.change-table tbody tr.life-high td) {
  background: #fff;
}

:deep(.change-table tbody tr) {
  cursor: pointer;
  outline: none;
}

:deep(.change-table tbody tr:hover td) {
  background: #f8fafc;
}

:deep(.change-table tbody tr td:first-child) {
  border-left-width: 3px;
}

:deep(.change-table tbody tr.life-low td:first-child) {
  border-left-color: #16a34a;
}

:deep(.change-table tbody tr.life-mid td:first-child) {
  border-left-color: #f59e0b;
}

:deep(.change-table tbody tr.life-high td:first-child) {
  border-left-color: #dc2626;
}

:deep(.change-table tbody tr.life-unknown td:first-child) {
  border-left-color: #94a3b8;
}

:deep(.change-table tbody tr.selected td) {
  background: #eff6ff;
  border-top-color: #2563eb;
  border-bottom-color: #2563eb;
  color: #0f172a;
  font-weight: 700;
}

:deep(.change-table tbody tr.selected td:first-child) {
  border-left-color: #2563eb;
}

:deep(.change-table tbody tr.selected td:last-child) {
  border-right-color: #2563eb;
}

:deep(.change-table .col-position) { width: 11%; }
:deep(.change-table .col-ring) { width: 16%; }
:deep(.change-table .col-reason) { width: 21%; }
:deep(.change-table .col-mileage) { width: 17%; }
:deep(.change-table .col-life) { width: 17%; }
:deep(.change-table .col-total) { width: 18%; }


:deep(.change-table tbody tr.life-low .position-cell) {
  background: linear-gradient(90deg, #dcfce7 0%, #f8fafc 88%);
  color: #14532d;
}

:deep(.change-table tbody tr.life-mid .position-cell) {
  background: linear-gradient(90deg, #fef3c7 0%, #fffbeb 88%);
  color: #78350f;
}

:deep(.change-table tbody tr.life-high .position-cell) {
  background: linear-gradient(90deg, #fecaca 0%, #fef2f2 88%);
  color: #7f1d1d;
}

:deep(.position-cell) {
  color: #111827;
  font-weight: 700;
}


:deep(.position-cell.life-low) {
  background: linear-gradient(90deg, #dcfce7 0%, #f8fafc 88%);
  color: #14532d;
}

:deep(.position-cell.life-mid) {
  background: linear-gradient(90deg, #fef3c7 0%, #fffbeb 88%);
  color: #78350f;
}

:deep(.position-cell.life-high) {
  background: linear-gradient(90deg, #fecaca 0%, #fef2f2 88%);
  color: #7f1d1d;
}

:deep(.mileage-cell) {
  font-weight: 700;
}

:deep(.mileage-cell.life-low) {
  background: linear-gradient(90deg, #dcfce7 0%, #f0fdf4 100%);
  color: #166534;
}

:deep(.mileage-cell.life-mid) {
  background: linear-gradient(90deg, #fef3c7 0%, #fffbeb 100%);
  color: #92400e;
}

:deep(.mileage-cell.life-high) {
  background: linear-gradient(90deg, #fecaca 0%, #fef2f2 100%);
  color: #7f1d1d;
}

:deep(.empty-cell) {
  height: 96px;
  color: #94a3b8;
}

@media (max-width: 1280px) {
  .overview-body {
    grid-template-columns: 1fr;
  }

  .drawing-panel {
    min-height: 420px;
  }

  .table-grid {
    grid-template-columns: 1fr;
  }
}
</style>
