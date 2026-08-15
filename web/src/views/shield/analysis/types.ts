// ─────────────────────────────────────────────────────────────
// 全局筛选参数
// ─────────────────────────────────────────────────────────────
export interface AnalysisFilter {
  project?: number | string;
  shield_machine?: number | string;
  start_ring?: string;
  end_ring?: string;
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

// ─────────────────────────────────────────────────────────────
// 概览仪表盘
// ─────────────────────────────────────────────────────────────
export interface OverviewKpi {
  total_openings: number;
  total_replacements: number;
  total_repairs: number;
  total_cost: number;
  avg_rings_between_openings: number;
  abnormal_wear_rate: number;   // 0~1
  healthy_rate: number;          // 0~1
}

export interface MonthlyTrendItem {
  month: string;          // 'YYYY-MM'
  replacements: number;
  repairs: number;
  cost: number;
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
}

export interface OverviewData {
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
}

export interface CostOverviewData {
  replacement_vs_repair: {
    complete: number;
    repair: number;
    total: number;
  };
  cost_per_ring?: {
    ring_count: number;
    complete: number;
    repair: number;
    total: number;
  };
  type_breakdown: CostTypeBreakdownItem[];
}

export interface CostTrendItem {
  ring_no: string;
  open_time: string;
  complete_cost: number;
  repair_cost: number;
  cumulative_cost: number;
}

export interface BrandCostItem {
  manufacturer: string;
  total_cost: number;
  count: number;
  opening_count?: number;
  abnormal_count?: number;
  normal_count?: number;
  avg_cost: number;
  cost_per_ring?: number;
  abnormal_rate?: number;
  normal_rate?: number;
  avg_lifespan?: number | null;
  lifespan_count?: number;
}

export interface BrandPriceTrendSeries {
  manufacturer: string;
  data: (number | null)[];
  count_data?: number[];
}

export interface BrandPriceTrendData {
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
  ring_no: string;
  open_time: string;
  total: number;
  abnormal: number;
  abnormal_rate: number;
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
  data: number[];
}

export interface CustomMatrixSeries {
  metric: string;
  name: string;
  unit: string;
  data: [number, number, number][];
}

export interface CustomChartData {
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
