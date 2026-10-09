import type { AnalysisMeta } from '../types';

export const STATUS_LABELS: Record<string, string> = { CONFIRMED: '已确认开仓', DRAFT: '草稿开仓', ALL: '全部开仓状态' };
export const SOURCE_LABELS: Record<string, string> = {
  installation: '新装刀具登记', confirmed_repair: '已确认返修', legacy_complete: '历史整刀',
  legacy_repair: '历史维修', legacy_untyped: '历史未分类', unresolved: '归属待核对',
};
export function formatNumber(value: unknown, digits = 0): string {
  if (value === null || value === undefined || value === '') return '未记录';
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString('zh-CN', { maximumFractionDigits: digits }) : '未记录';
}
export function formatCurrency(value: unknown): string {
  const text = formatNumber(value, 2);
  return text === '未记录' ? text : `¥${text}`;
}
export function formatPercent(value: unknown): string {
  if (value === null || value === undefined || value === '') return '无有效样本';
  return Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : '无有效样本';
}
export function escapeHtml(value: unknown): string {
  return String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]!));
}
export function requireAnalysisV2<T extends { meta?: AnalysisMeta }>(data: T): T {
  if (data?.meta?.schema_version !== 2) throw new Error('分析服务尚未更新，当前结果未展示。请更新服务后重新加载。');
  return data;
}
function uniqueScopeNames(value?: string): string {
  return [...new Set(String(value || '').split('、').map(name => name.trim()).filter(Boolean))].join('、');
}
export function scopeSummary(meta?: AnalysisMeta): string {
  if (!meta) return '';
  const scope = meta.scope || {};
  return [uniqueScopeNames(scope.project_name) || (scope.project ? `项目 ${scope.project}` : '全部项目'), uniqueScopeNames(scope.shield_machine_name) || (scope.shield_machine ? `盾构机 ${scope.shield_machine}` : '全部盾构机'),
    STATUS_LABELS[meta.summary_status] || meta.summary_status,
    scope.start_ring || scope.end_ring ? `${scope.start_ring || '起点'} 至 ${scope.end_ring || '终点'} 环` : '全部环号',
    scope.blade_track_min || scope.blade_track_max ? `刀刃轨迹 ${scope.blade_track_min || '不限下界'} 至 ${scope.blade_track_max || '不限上界'} mm` : '',
    scope.tool_parent_type ? ({ DISC: '滚刀', SCRAPER: '刮刀' }[scope.tool_parent_type] || scope.tool_parent_type) : '全部刀型',
    scope.tool_type_name || scope.tool_type_names, scope.manufacturer || scope.manufacturers,
    scope.stratum_type || scope.stratum_types,
    scope.cost_type || scope.cost_types ? String(scope.cost_type || scope.cost_types).split(',').map(value => ({ COMPLETE: '新装/历史整刀', REPAIR: '返修/历史维修' }[value] || value)).join('、') : '',
  ].filter(Boolean).map(value => Array.isArray(value) ? value.join('、') : value).join(' · ');
}
export function analysisExportMeta(meta?: AnalysisMeta) {
  if (!meta) return [];
  return [
    { label: '统计范围', value: scopeSummary(meta) },
    { label: '生成时间', value: new Date(meta.generated_at).toLocaleString('zh-CN') },
    { label: '开仓数', value: String(meta.opening_count) },
    { label: '范围内草稿', value: String(meta.draft_opening_count) },
    { label: '观察样本', value: `${meta.observed_count ?? '未记录'} 条；${meta.observed_basis || '有效观察明细'}` },
    { label: '排除记录', value: `无效刀位 ${meta.excluded_inactive_count ?? 0} 条，未观察 ${meta.unobserved_count ?? 0} 条，环号不可用 ${meta.excluded_invalid_ring_opening_count ?? 0} 次开仓` },
    { label: '范围说明', value: (meta.warnings || []).join('；') },
    { label: '磨损口径', value: meta.wear_basis || '有现场磨损记录的样本' },
    { label: '磨损归类', value: '轻微/中度磨损计入非正常描述；比例只评价有记录样本，不是故障率。' },
    ...(meta.scope?.blade_track_min || meta.scope?.blade_track_max ? [{ label: '轨迹口径', value: meta.blade_track_basis || '当前刀位中心轨迹半径，单位 mm，含上下限。' }] : []),
    { label: '金额口径', value: '新装登记 + 已确认返修 + 历史登记；待核对金额不计入明确合计，非财务结算额。' },
  ];
}
