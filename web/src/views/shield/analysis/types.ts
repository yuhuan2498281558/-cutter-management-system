// ─────────────────────────────────────────────────────────────
// 全局筛选参数
// ─────────────────────────────────────────────────────────────
export interface AnalysisFilter {
  summary_status?: 'CONFIRMED' | 'DRAFT' | 'ALL';
  project?: number | string;
  shield_machine?: number | string;
  start_ring?: string;
  end_ring?: string;
  blade_track_min?: string;
  blade_track_max?: string;
  stratum_type?: string;
  stratum_types?: string | string[];
  tool_parent_type?: string;
  tool_type_name?: string;
  tool_type_names?: string | string[];
  cost_type?: string;
  cost_types?: string | string[];
  manufacturer?: string;
  manufacturers?: string | string[];
}

export interface AnalysisMeta {
  schema_version: number;
  generated_at: string;
  summary_status: string;
  opening_count: number;
  draft_opening_count: number;
  excluded_inactive_count: number;
  unobserved_count: number;
  warnings: string[];
  scope: AnalysisFilter & { project_name?: string; shield_machine_name?: string };
  wear_basis?: string;
  observed_count?: number;
  observed_basis?: string;
  legacy_observed_count?: number;
  cost_source_count?: number;
  service_sample_count?: number;
  pairing_unresolved_count?: number;
  excluded_invalid_ring_opening_count?: number;
  filter_capabilities?: string[];
  blade_track_basis?: string;
}

export interface CostSources {
  installation: number;
  confirmed_repair: number;
  legacy: number;
  unresolved: number;
  total: number;
  missing_price_count: number;
  pending_repair_count: number;
  repair_missing_price_count: number;
  unresolved_count: number;
  priced_count: number;
}

export interface CostSourceRow {
  id: string | number;
  detail_id: number;
  opening_id: number;
  warehouse_id: string;
  ring_no: string;
  tool_parent_type: string;
  cutter_position_no: string;
  manufacturer: string;
  source: 'installation' | 'confirmed_repair' | 'legacy_complete' | 'legacy_repair' | 'legacy_untyped' | 'unresolved';
  amount: number | null;
  included: boolean;
  reason: string;
  old_tool_number: string;
  new_tool_number: string;
  inspection_status?: string;
}

// ─────────────────────────────────────────────────────────────
// 概览仪表盘
// ─────────────────────────────────────────────────────────────
export interface OverviewKpi {
  total_openings: number;
  total_replacements: number;
  total_repairs: number;
  total_cost: number;
  avg_rings_between_openings: number;
  abnormal_wear_rate: number | null;
  healthy_rate: number | null;
  total_completes?: number;
  total_untyped?: number;
  detail_checked_count?: number;
  summary_checked_count?: number;
  summary_replaced_count?: number;
  replacement_gap?: number;
  summary_detail_replaced_count?: number;
  cost_sources?: CostSources;
}

export interface MonthlyTrendItem {
  month: string;          // 'YYYY-MM'
  replacements: number;
  repairs: number;
  cost: number;
  untyped?: number;
  total_replacements?: number;
}

export interface TypeTrendItem {
  ring_no: string;
  DISC: number;
  RIPPER: number;
  SCRAPER: number;
}

export interface RecentOpeningItem {
  id: number;
  warehouse_id: string;
  ring_no: string;
  open_time: string;
  replaced_count: number;
  cost: number;
  geological_conditions: string;
  abnormal_count: number;
  summary_status?: string;
  summary_replaced_count?: number;
  replacement_gap?: number;
  cost_sources?: CostSources;
}

export interface OverviewData {
  meta?: AnalysisMeta;
  kpi: OverviewKpi;
  monthly_trend: MonthlyTrendItem[];
  type_trend: TypeTrendItem[];
  recent_openings: RecentOpeningItem[];
}

// ─────────────────────────────────────────────────────────────
// 成本分析
// ─────────────────────────────────────────────────────────────
export interface CostTypeBreakdownItem {
  tool_type: string;
  complete_cost: number;
  repair_cost: number;
  total: number;
  cost_sources?: CostSources;
}

export interface CostOverviewData {
  meta?: AnalysisMeta;
  cost_sources?: CostSources;
  source_rows?: CostSourceRow[];
  source_rows_total?: number;
  source_rows_truncated?: boolean;
  replacement_vs_repair: {
    complete: number;
    repair: number;
    total: number;
  };
  cost_per_ring?: {
    ring_count: number;
    complete: number | null;
    repair: number | null;
    total: number | null;
    available?: boolean;
    reason?: string;
  };
  type_breakdown: CostTypeBreakdownItem[];
}

export interface CostTrendItem {
  ring_no: string;
  open_time: string;
  complete_cost: number;
  repair_cost: number;
  cumulative_cost: number;
  installation_cost?: number;
  confirmed_repair_cost?: number;
  legacy_cost?: number;
  unresolved_cost?: number;
  total_cost?: number;
  replacement_count?: number;
}

export interface BrandCostItem {
  manufacturer: string;
  total_cost: number;
  count: number;
  opening_count?: number;
  abnormal_count?: number;
  normal_count?: number;
  avg_cost: number | null;
  cost_per_ring?: number | null;
  abnormal_rate?: number | null;
  normal_rate?: number | null;
  avg_lifespan?: number | null;
  lifespan_count?: number;
  priced_count?: number;
  missing_price_count?: number;
  wear_recorded_count?: number;
  unrecorded_wear_count?: number;
  paired_count?: number;
  pairing_unresolved_count?: number;
  cost_sources?: CostSources;
}

export interface BrandPriceTrendSeries {
  manufacturer: string;
  data: (number | null)[];
  count_data?: number[];
}

export interface BrandPriceTrendData {
  meta?: AnalysisMeta;
  manufacturers: string[];
  time_axis: { ring_no: string; open_time: string }[];
  series: BrandPriceTrendSeries[];
}

export interface BrandPerfTrendSeries {
  manufacturer: string;
  data: (number | null)[];
  count_data?: number[];
  abnormal_count_data?: number[];
}

export interface BrandPerformanceTrendData {
  meta?: AnalysisMeta;
  manufacturers: string[];
  time_axis: { ring_no: string; open_time: string }[];
  abnormal_rate_series: BrandPerfTrendSeries[];
  normal_rate_series: BrandPerfTrendSeries[];
  lifespan_series: BrandPerfTrendSeries[];
}

// ─────────────────────────────────────────────────────────────
// 磨损分析
// ─────────────────────────────────────────────────────────────
export interface WearDistributionItem {
  wear_condition: string;
  count: number;
  percentage: number;
}

export interface WearTrendItem {
  id?: number;
  warehouse_id?: string;
  ring_no: string;
  open_time: string;
  total: number;
  abnormal: number;
  abnormal_rate: number | null;
  checked_count?: number;
  replacement_count?: number;
  unrecorded_count?: number;
  geological_conditions: string;
  stratum_types: string;
}

// ─────────────────────────────────────────────────────────────
// 自定义分析
// ─────────────────────────────────────────────────────────────
export interface CustomFieldOption {
  value: string;
  label: string;
  type?: string;
  unit?: string;
  chart_types?: string[];
  fields?: CustomFieldOption[];
}

export interface CustomFieldsData {
  dimensions: CustomFieldOption[];
  metrics: CustomFieldOption[];
  defaults?: {
    line?: { x_field: string; metrics: string[] };
    matrix?: { x_field: string; y_field: string; metrics: string[] };
  };
}

export interface CustomLineSeries {
  metric: string;
  name: string;
  unit: string;
  data: (number | null)[];
}

export interface CustomMatrixSeries {
  metric: string;
  name: string;
  unit: string;
  data: [number, number, number | null][];
}

export interface CustomChartData {
  meta?: AnalysisMeta;
  chart_type: 'line' | 'matrix';
  x_field: CustomFieldOption;
  y_field?: CustomFieldOption;
  x_fields?: CustomFieldOption[];
  y_fields?: CustomFieldOption[];
  metrics: CustomFieldOption[];
  categories?: string[];
  x_categories?: string[];
  y_categories?: string[];
  series: CustomLineSeries[] | CustomMatrixSeries[];
  rows?: Record<string, any>[];
  record_count: number;
}
