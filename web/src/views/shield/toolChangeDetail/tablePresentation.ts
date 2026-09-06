export interface DetailStatusRow {
  cutter_position_no?: string;
  tool_number?: string;
  is_checked?: boolean;
  is_replaced?: boolean;
  old_tool_record_data?: { inspection_status?: string } | null;
}

export type CheckFilter = 'ALL' | 'UNCHECKED' | 'CHECKED_ONLY' | 'REPLACED';
export const repairLabels = {
  NOT_REPLACED: '无需返修补录',
  UNRECORDED: '待补录',
  PENDING_VENDOR_FEEDBACK: '待厂家反馈',
  CONFIRMED: '厂家反馈已确认',
  CLOSED: '已归档',
  UNKNOWN: '状态待核实',
} as const;
export type RepairStatus = keyof typeof repairLabels;
export type RepairFilter = 'ALL' | RepairStatus;

export function repairStatus(row: DetailStatusRow): RepairStatus {
  if (!row.is_replaced) return 'NOT_REPLACED';
  if (!row.old_tool_record_data) return 'UNRECORDED';
  const status = row.old_tool_record_data.inspection_status;
  return status === 'PENDING_VENDOR_FEEDBACK' || status === 'CONFIRMED' || status === 'CLOSED' ? status : 'UNKNOWN';
}

export function matchesDetailFilters(row: DetailStatusRow, check: CheckFilter, repair: RepairFilter, query: string): boolean {
  if (check === 'UNCHECKED' && row.is_checked) return false;
  if (check === 'CHECKED_ONLY' && (!row.is_checked || row.is_replaced)) return false;
  if (check === 'REPLACED' && !row.is_replaced) return false;
  if (repair !== 'ALL' && repairStatus(row) !== repair) return false;
  const search = query.trim().toLocaleLowerCase();
  return !search || [row.cutter_position_no, row.tool_number].some(value => String(value ?? '').toLocaleLowerCase().includes(search));
}
