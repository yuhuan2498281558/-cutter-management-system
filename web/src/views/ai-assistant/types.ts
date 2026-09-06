export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  time: string;
  streaming?: boolean;
  rawError?: boolean;
  aborted?: boolean;
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
}

export interface QuickQuestionGroup {
  title: string;
  desc: string;
  items: QuickQuestionItem[];
}

export interface QuickParams {
  openingLimit: number;
  ringWindow: number;
  topN: number;
  interval: number;
}

export interface MemoryMetadata {
  backend?: string;
  message_count?: number;
  summary_revision?: number;
  slots?: string[];
  scope?: string;
}

export type RouteMode = 'rule' | 'agent';
