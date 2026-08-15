export type ExportFormat = 'excel' | 'csv' | 'pdf';

export interface ExportColumn {
  key: string;
  title: string;
  formatter?: (row: any, index: number) => any;
}

export interface ExportMetaItem {
  label: string;
  value: any;
  span?: number;
}

interface ExportOptions {
  title: string;
  filename: string;
  columns: ExportColumn[];
  rows: any[];
  format: ExportFormat;
  meta?: ExportMetaItem[];
}

function normalizeValue(value: any) {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.join('、');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function getCell(row: any, column: ExportColumn, index: number) {
  const value = column.formatter ? column.formatter(row, index) : row?.[column.key];
  return normalizeValue(value);
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function download(content: BlobPart, filename: string, type: string) {
  const blob = new Blob([content], { type });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  URL.revokeObjectURL(link.href);
  document.body.removeChild(link);
}

function buildMetaRows(meta: ExportMetaItem[] = [], columnCount: number) {
  if (!meta.length) return '';
  const rows: string[] = [];
  const pending: ExportMetaItem[] = [];
  const labelSpan = columnCount >= 12 ? 2 : 1;

  const flushPending = () => {
    if (!pending.length) return;
    const valueTotal = Math.max(columnCount - pending.length * labelSpan, pending.length);
    const baseValueSpan = Math.floor(valueTotal / pending.length);
    let remainder = valueTotal - baseValueSpan * pending.length;
    const cells = pending.map((item) => {
      const valueSpan = baseValueSpan + (remainder > 0 ? 1 : 0);
      remainder -= 1;
      return `
        <th class="meta-label" colspan="${labelSpan}">${escapeHtml(item.label)}</th>
        <td class="meta-value" colspan="${valueSpan}">${escapeHtml(normalizeValue(item.value))}</td>
      `;
    }).join('');
    rows.push(`<tr class="meta-row">${cells}</tr>`);
    pending.length = 0;
  };

  meta.forEach((item) => {
    if (item.span === 3) {
      flushPending();
      rows.push(`
        <tr class="meta-row">
          <th class="meta-label" colspan="${labelSpan}">${escapeHtml(item.label)}</th>
          <td class="meta-value" colspan="${Math.max(columnCount - labelSpan, 1)}">${escapeHtml(normalizeValue(item.value))}</td>
        </tr>
      `);
      return;
    }
    pending.push(item);
    if (pending.length === 3) {
      flushPending();
    }
  });
  flushPending();

  return `
    <tr class="meta-title"><th colspan="${columnCount}">开仓基本信息</th></tr>
    ${rows}
    <tr class="table-spacer"><td colspan="${columnCount}"></td></tr>
  `;
}

function buildHtmlTable(options: ExportOptions) {
  const columnCount = Math.max(options.columns.length, 1);
  const metaRows = buildMetaRows(options.meta || [], columnCount);
  const headers = options.columns.map(column => `<th>${escapeHtml(column.title)}</th>`).join('');
  const rows = options.rows.map((row, index) => {
    const cells = options.columns
      .map(column => `<td>${escapeHtml(getCell(row, column, index))}</td>`)
      .join('');
    return `<tr>${cells}</tr>`;
  }).join('');
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>${escapeHtml(options.title)}</title>
<style>
body{font-family:Arial,"Microsoft YaHei",sans-serif;color:#1f2937;}
h1{font-size:18px;margin:0 0 12px;}
table{border-collapse:collapse;width:100%;font-size:12px;}
th,td{border:1px solid #d9d9d9;padding:6px 8px;text-align:left;vertical-align:top;}
th{background:#f2f3f5;font-weight:600;}
.export-table{table-layout:auto;}
.meta-title th{font-size:14px;background:#fff;border:none;padding:0 0 10px 0;text-align:left;}
.meta-row .meta-label{background:#f2f3f5;white-space:nowrap;color:#606266;font-weight:600;}
.meta-row .meta-value{background:#fff;}
.table-spacer td{height:12px;border-left:none;border-right:none;background:#fff;padding:0;}
.detail-header th{background:#f2f3f5;white-space:nowrap;}
</style>
</head>
<body>
<h1>${escapeHtml(options.title)}</h1>
<table class="export-table"><tbody>${metaRows}<tr class="detail-header">${headers}</tr>${rows}</tbody></table>
</body>
</html>`;
}

function exportExcel(options: ExportOptions) {
  const html = '\ufeff' + buildHtmlTable(options);
  download(html, `${options.filename}.xls`, 'application/vnd.ms-excel;charset=utf-8');
}

function exportCsv(options: ExportOptions) {
  const metaRows = (options.meta || []).map(item => (
    `"${item.label.replace(/"/g, '""')}","${normalizeValue(item.value).replace(/"/g, '""')}"`
  ));
  const header = options.columns.map(column => `"${column.title.replace(/"/g, '""')}"`).join(',');
  const rows = options.rows.map((row, index) => options.columns
    .map(column => `"${getCell(row, column, index).replace(/"/g, '""')}"`)
    .join(','));
  const content = metaRows.length
    ? [...metaRows, '', header, ...rows].join('\n')
    : [header, ...rows].join('\n');
  download(`\ufeff${content}`, `${options.filename}.csv`, 'text/csv;charset=utf-8');
}

function exportPdf(options: ExportOptions) {
  const win = window.open('', '_blank');
  if (!win) return;
  win.document.write(buildHtmlTable(options));
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 100);
}

export function exportTableData(options: ExportOptions) {
  if (options.format === 'excel') exportExcel(options);
  if (options.format === 'csv') exportCsv(options);
  if (options.format === 'pdf') exportPdf(options);
}
