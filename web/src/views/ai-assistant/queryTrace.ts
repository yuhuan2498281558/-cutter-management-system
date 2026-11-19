import type { QueryTrace } from './types';

// 环号和记录数可能是数字，也可能是数字字符串
const toNumber = (value: unknown) => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && /^\d+$/.test(value.trim())) return Number(value);
  return undefined;
};

const ringText = (start: unknown, end: unknown) => {
  const from = toNumber(start);
  const to = toNumber(end);
  if (from === undefined || to === undefined) return '';
  return from === to ? `第${from}环` : `第${from}–${to}环`;
};

// 环段按 ring_range、effective_ring_range、ring_min/ring_max 的顺序取第一个能用的
const describeRings = (scope: Record<string, unknown>) => {
  for (const key of ['ring_range', 'effective_ring_range']) {
    const range = scope[key];
    const text = Array.isArray(range) && range.length === 2 ? ringText(range[0], range[1]) : '';
    if (text) return text;
  }
  return ringText(scope.ring_min, scope.ring_max);
};

const describeCount = (scope: Record<string, unknown>) => {
  const count = toNumber(scope.record_count) ?? toNumber(scope.observation_count);
  return count === undefined ? '' : `${count}条`;
};

// 一次查询的文字，例如"换刀与磨损 · 第388–487环 · 359条"；取不到范围时只有类别名
export const describeQueryTrace = (trace: QueryTrace) => {
  const scope = trace.scope || {};
  return [trace.sourceLabel, describeRings(scope), describeCount(scope)].filter(Boolean).join(' · ');
};

// 按类别去重，每类一个标签；同一类查了多次时，用第一条带范围的
export const queryTraceTags = (traces: QueryTrace[]) => {
  const tags = new Map<string, string>();
  for (const trace of traces) {
    if (tags.get(trace.sourceLabel) === undefined || tags.get(trace.sourceLabel) === trace.sourceLabel) {
      tags.set(trace.sourceLabel, describeQueryTrace(trace));
    }
  }
  return [...tags.values()];
};
