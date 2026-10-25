import type { QueryTrace } from '/@/api/ai-assistant';

export type { QueryTrace };

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  time: string;
  streaming?: boolean;
  rawError?: boolean;
  aborted?: boolean;
  // 模型路径回答用到的数据查询，显示在回答下方的"本次查询"
  queryTraces?: QueryTrace[];
}

export interface AnalysisSection {
  title: string;
  kind: 'conclusion' | 'evidence' | 'warning' | 'suggestion' | 'default';
  items: string[];
}

export interface ParsedAnalysisMessage {
  lead: string;
  sections: AnalysisSection[];
}

export interface QuickQuestionItem {
  label: string;
  query: string;
  numKey?: 'openingLimit' | 'ringWindow' | 'topN' | 'interval';
  min?: number;
  max?: number;
  step?: number;
  defaultValue?: number;
  textKey?: 'id';
}

export interface QuickQuestionGroup {
  title: string;
  desc: string;
  items: QuickQuestionItem[];
}

export type FocusSource =
  | 'tool_change'
  | 'opening'
  | 'inspection'
  | 'position'
  | 'stratum'
  | 'tunneling'
  | 'manufacturer'
  | 'cost'
  | 'repair'
  | 'lifecycle';

export interface ModelPromptTemplate {
  title: string;
  query: string;
  sources: FocusSource[];
  isDefault?: boolean;
  numKey?: QuickQuestionItem['numKey'];
  min?: number;
  max?: number;
  step?: number;
  defaultValue?: number;
  toolParam?: boolean;
  textKey?: 'id';
}

// 每条问题或模板各自的参数值：{n} 数字（清空时为 null）、{tool} 刀型、{id} 刀具编号
export interface QuestionParamValues {
  n: number | null;
  tool: string;
  id: string;
}

export interface MemoryMetadata {
  backend?: string;
  message_count?: number;
  summary_revision?: number;
  slots?: string[];
  scope?: string;
  activeSlots?: Partial<Record<QuerySlot, string | number | number[]>>;
  contextMode?: Exclude<ContextMode, 'auto'>;
}

// 后端发来的上下文用量：turn 是本轮最大一次模型调用，baseline 是下一问起步，rule 是直连查库。
// schema_version 2 起 used 可能是接口实测值（measurement），分项 parts 始终是估算。
export interface ContextInfo {
  kind: 'turn' | 'baseline' | 'rule';
  estimated: boolean;
  window: number;
  input_budget: number;
  output_reserve: number;
  safety_margin: number;
  used: number | null;
  exceeded: boolean;
  parts: { system: number; tools: number; memory: number; question: number; results: number; other: number } | null;
  results_raw: number | null;
  compacted_results: number;
  summarized_results: number;
  model_calls: number;
  // 长列表分页：该次调用里被切成一页的列表数、本轮模型自己要后面几页的次数（后端未提供时缺省）
  paged_lists?: number;
  page_requests?: number;
  thresholds: { compaction_min_tokens: number; evidence_soft_tokens?: number };
  memory: {
    backend: string;
    recent_turns: number | null;
    recent_budget: number | null;
    recent_tokens: number;
    included_turns: number;
    summary_tokens: number;
    summary_trigger_tokens: number | null;
    pending_tokens: number | null;
  };
  schema_version?: number;
  measurement?: 'actual' | 'estimated';
  last_prompt_tokens_actual?: number | null;
  trigger_tokens?: number;
  hard_input_limit?: number;
  provider_usage?: { prompt_tokens: number | null; completion_tokens: number | null; cache_hit_tokens: number | null } | null;
  history?: { turns: number; tool_results: number; legacy_qa_turns: number; other_project_turns: number; tokens: number };
  // auto 为 true 表示后端会在触发线自动压缩（B 阶段起提供）
  compaction?: {
    state: string;
    auto?: boolean;
    checkpoints: number;
    pruned_results: number;
    last_at: string | null;
    last_before: number | null;
    last_after: number | null;
  };
}

export type RouteMode = 'rule' | 'agent';
export type ContextMode = 'auto' | 'new' | 'continue';
export type QuerySlot = 'ring_range' | 'tool_type' | 'cutter_position_no';
