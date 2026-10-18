export const TOOL_TYPE_COLORS: Record<string, string> = {
  DISC: '#e84749',
  RIPPER: '#fa8c16',
  SCRAPER: '#1677ff',
};

export const TOOL_TYPE_LABELS: Record<string, string> = {
  DISC: '滚刀',
  RIPPER: '撕裂刀',
  SCRAPER: '刮刀',
};

export const TOOLTIP_STYLE = {
  backgroundColor: 'rgba(255,255,255,0.95)',
  borderColor: '#e8e8e8',
  borderWidth: 1,
  textStyle: { color: '#333', fontSize: 12 },
  extraCssText: 'box-shadow: 0 2px 8px rgba(0,0,0,0.12); border-radius:4px;',
};

export const DEFAULT_GRID = {
  top: 40,
  right: 24,
  bottom: 60,
  left: 60,
  containLabel: true,
};
