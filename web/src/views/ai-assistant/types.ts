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

export type RouteMode = 'rule' | 'agent';
export type ContextMode = 'auto' | 'new' | 'continue';
export type QuerySlot = 'ring_range' | 'tool_type' | 'cutter_position_no';
