import * as echarts from 'echarts';
import { ElMessage } from 'element-plus';
import { escapeHtml } from './presentation';

function createChartImage(canvas: HTMLCanvasElement) {
  const image = document.createElement('img');
  const canvasWidth = canvas.width || canvas.clientWidth || 1;
  const canvasHeight = canvas.height || canvas.clientHeight || 1;
  image.src = canvas.toDataURL('image/png');
  image.className = 'chart-export-image';
  image.width = canvasWidth;
  image.height = canvasHeight;
  image.style.aspectRatio = `${canvasWidth} / ${canvasHeight}`;
  return image;
}

function copyCanvasToImages(source: HTMLElement, target: HTMLElement) {
  const sourceChartRoots = Array.from(source.querySelectorAll('div[_echarts_instance_]'));
  const targetChartRoots = Array.from(target.querySelectorAll('div[_echarts_instance_]'));

  if (sourceChartRoots.length && targetChartRoots.length) {
    sourceChartRoots.forEach((chartRoot, index) => {
      const clonedChartRoot = targetChartRoots[index];
      if (!clonedChartRoot || (chartRoot as HTMLElement).closest('.chart-content')?.getAttribute('style')?.includes('display: none')) return;
      const chart = echarts.getInstanceByDom(chartRoot as HTMLElement);
      const canvases = chartRoot.querySelectorAll('canvas');
      if (!chart && canvases.length !== 1) throw new Error('图表尚未就绪，请等待图表加载完成后重试');
      let image: HTMLImageElement;
      if (chart) {
        image = document.createElement('img');
        image.src = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' });
        image.width = chart.getWidth(); image.height = chart.getHeight();
        image.className = 'chart-export-image';
        image.style.aspectRatio = `${image.width} / ${image.height}`;
      } else image = createChartImage(canvases[0]);
      const imageWrap = document.createElement('div');
      imageWrap.className = 'chart-export-box';
      imageWrap.appendChild(image);
      if (chart) {
        const option = chart.getOption() as any;
        const note = document.createElement('p'); note.className = 'chart-snapshot-note';
        const names = (option.series || []).map((series: any) => series.name).filter(Boolean);
        const hidden = (option.legend || []).flatMap((legend: any) => Object.entries(legend.selected || {}).filter(([, selected]) => !selected).map(([name]) => name));
        const zoom = (option.dataZoom || []).map((item: any) => item.startValue != null || item.endValue != null ? `${item.startValue ?? '起点'} 至 ${item.endValue ?? '终点'}（轴索引/值）` : `${item.start ?? 0}% 至 ${item.end ?? 100}%`);
        note.textContent = ['图形按当前视窗导出', names.length ? `系列：${names.join('、')}` : '', hidden.length ? `未选中：${hidden.join('、')}` : '', zoom.length ? `缩放：${zoom.join('；')}` : ''].filter(Boolean).join('；');
        imageWrap.appendChild(note);
      }
      clonedChartRoot.replaceWith(imageWrap);
    });
    return;
  }

  const sourceCanvases = Array.from(source.querySelectorAll('canvas'));
  const targetCanvases = Array.from(target.querySelectorAll('canvas'));
  sourceCanvases.forEach((canvas, index) => {
    const clonedCanvas = targetCanvases[index];
    if (!clonedCanvas) return;
    clonedCanvas.replaceWith(createChartImage(canvas));
  });
}

function removeExportBars(target: HTMLElement) {
  target.querySelectorAll('.analysis-export-bar, .analysis-no-export, .el-form, .el-pagination, .el-loading-mask, .caret-wrapper, .el-table__column-resize-proxy').forEach(el => el.remove());
  target.querySelectorAll('.chart-card-header').forEach(header => Array.from(header.children).filter(child => !child.classList.contains('chart-heading')).forEach(child => child.remove()));
  target.querySelectorAll('details').forEach(details => details.setAttribute('open', ''));
  target.querySelectorAll('button, a').forEach(button => {
    const label = document.createElement('span'); label.textContent = button.textContent; button.replaceWith(label);
  });
  target.querySelectorAll('script, iframe, object, embed').forEach(element => element.remove());
  target.querySelectorAll('*').forEach(element => Array.from(element.attributes).forEach(attribute => {
    if (/^on/i.test(attribute.name)) element.removeAttribute(attribute.name);
  }));
}

/** Element Plus renders the fixed header and scrollable body as separate tables. */
function flattenTables(target: HTMLElement) {
  target.querySelectorAll('.el-table').forEach(wrapper => {
    const own = (selector: string) => Array.from(wrapper.querySelectorAll(selector)).find(element => element.closest('.el-table') === wrapper);
    const body = own('table.el-table__body');
    if (!body) return;
    const head = own('table.el-table__header')?.querySelector('thead') || body.querySelector('thead');
    const table = document.createElement('table'); table.className = 'analysis-print-table';
    if (head) table.appendChild(head.cloneNode(true));
    const tbody = body.querySelector('tbody'); if (tbody) table.appendChild(tbody.cloneNode(true));
    const footer = own('table.el-table__footer')?.querySelector('tbody');
    if (footer) { const foot = document.createElement('tfoot'); Array.from(footer.children).forEach(row => foot.appendChild(row.cloneNode(true))); table.appendChild(foot); }
    table.querySelectorAll('.gutter, col[name="gutter"]').forEach(element => element.remove());
    table.querySelectorAll('*').forEach(element => { element.removeAttribute('style'); element.removeAttribute('width'); element.removeAttribute('height'); });
    wrapper.closest('.el-card')?.classList.add('analysis-print-table-card');
    wrapper.replaceWith(table);
  });
}

export interface AnalysisPdfSection {
  title: string;
  selector: string;
}

export interface AnalysisPdfMetaItem {
  label: string;
  value: string;
}

export interface AnalysisPdfTable {
  id: string;
  headers: string[];
  rows: string[][];
}

/** Build full detail tables only for export, independently of the visible page. */
function replaceSnapshotTables(target: HTMLElement, tables: AnalysisPdfTable[]) {
  if (!tables.length) return target;
  const snapshots = new Map(tables.map(table => [table.id, table]));
  const wrappers = [target, ...Array.from(target.querySelectorAll<HTMLElement>('[data-analysis-table]'))];
  wrappers.forEach(wrapper => {
    const snapshot = snapshots.get(wrapper.getAttribute('data-analysis-table') || '');
    if (!snapshot) return;
    const table = document.createElement('table');
    table.className = 'analysis-print-table';
    table.setAttribute('data-analysis-table', snapshot.id);
    const head = document.createElement('thead');
    const headerRow = document.createElement('tr');
    snapshot.headers.forEach(value => {
      const cell = document.createElement('th'); cell.textContent = value; headerRow.appendChild(cell);
    });
    head.appendChild(headerRow); table.appendChild(head);
    const body = document.createElement('tbody');
    snapshot.rows.forEach(values => {
      const row = document.createElement('tr');
      values.forEach(value => {
        const cell = document.createElement('td'); cell.textContent = value ?? ''; row.appendChild(cell);
      });
      body.appendChild(row);
    });
    table.appendChild(body);
    wrapper.closest('.el-card')?.classList.add('analysis-print-table-card');
    if (wrapper === target) target = table;
    else wrapper.replaceWith(table);
  });
  return target;
}

function cloneSection(selector: string, tables: AnalysisPdfTable[]) {
  const source = document.querySelector(selector) as HTMLElement | null;
  if (!source) throw new Error('未找到需要导出的内容，请重新加载当前分析页');
  let cloned = source.cloneNode(true) as HTMLElement;
  copyCanvasToImages(source, cloned);
  cloned = replaceSnapshotTables(cloned, tables);
  flattenTables(cloned);
  removeExportBars(cloned);
  return cloned.outerHTML;
}

function buildMetaHtml(meta: AnalysisPdfMetaItem[] = []) {
  if (!meta.length) return '';
  const rows: string[] = [];
  for (let i = 0; i < meta.length; i += 3) {
    const group = meta.slice(i, i + 3);
    const cells = group.map(item => `
      <th>${escapeHtml(item.label)}</th>
      <td>${escapeHtml(item.value || '未记录')}</td>
    `).join('');
    rows.push(`<tr>${cells}${'<th></th><td></td>'.repeat(3 - group.length)}</tr>`);
  }
  return `<section class="filter-summary">
    <h2>筛选条件</h2>
    <table>${rows.join('')}</table>
  </section>`;
}

export function exportAnalysisPdf(
  title: string,
  selectorOrSections: string | AnalysisPdfSection[],
  meta: AnalysisPdfMetaItem[] = [],
  tables: AnalysisPdfTable[] = [],
) {
  const sections = typeof selectorOrSections === 'string'
    ? [{ title: '', selector: selectorOrSections }]
    : selectorOrSections;

  let content: string;
  try { content = sections.map(section => {
    const html = cloneSection(section.selector, tables);
    if (!html) return '';
    return `<section class="pdf-section">
      ${section.title ? `<h2>${escapeHtml(section.title)}</h2>` : ''}
      ${html}
    </section>`;
  }).join(''); } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : '导出内容读取失败，请重新加载'); return false; }
  if (!content) { ElMessage.warning('没有可导出的分析内容'); return false; }

  const win = window.open('', '_blank');
  if (!win) { ElMessage.warning('打印窗口被浏览器拦截，请允许弹出窗口后重试'); return false; }

  win.document.write(`<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>${escapeHtml(title)}</title>
<style>
@page{size:A4 landscape;margin:9mm;}
body{margin:0;padding:8px;font-family:Arial,"Microsoft YaHei",sans-serif;color:#1f2937;background:#fff;}
h1{font-size:15px;margin:0 0 6px;line-height:1.25;}
h2{font-size:12px;margin:0 0 4px;color:#111827;line-height:1.25;}
.filter-summary{margin-bottom:8px;page-break-inside:avoid;break-inside:avoid;}
.filter-summary h2{margin-bottom:4px;}
.filter-summary table{width:100%;border-collapse:collapse;font-size:9px;line-height:1.2;}
.filter-summary th{width:12%;background:#f2f3f5;text-align:left;font-weight:600;white-space:nowrap;}
.filter-summary td{width:21%;}
.filter-summary th,.filter-summary td{border:1px solid #d9d9d9;padding:2px 4px;}
.pdf-section{margin-bottom:6px;}
.pdf-section + .pdf-section{break-before:auto;page-break-before:auto;}
.el-row{display:flex;flex-wrap:wrap;margin-left:0!important;margin-right:0!important;}
.el-row .el-col{padding-left:3px!important;padding-right:3px!important;}
.el-col{box-sizing:border-box;max-width:100%;}
.el-col-8{flex:0 0 33.333333%;max-width:33.333333%;}
.el-col-12{flex:0 0 50%;max-width:50%;}
.el-col-16{flex:0 0 66.666667%;max-width:66.666667%;}
.el-col-24{flex:0 0 100%;max-width:100%;}
.el-card{border:1px solid #d9d9d9;border-radius:4px;margin-bottom:6px;background:#fff;page-break-inside:avoid;break-inside:avoid;overflow:visible!important;}
.el-card__header{padding:4px 6px;border-bottom:1px solid #e5e7eb;}
.el-card__body{padding:5px;overflow:visible!important;}
.chart-card-body{height:auto!important;min-height:0!important;overflow:visible!important;}
.chart-card-body > div,.chart-card-body div[_echarts_instance_]{width:100%!important;height:auto!important;min-height:0!important;overflow:visible!important;position:static!important;}
.chart-card-header{display:flex;align-items:center;justify-content:space-between;}
.chart-title{font-size:10px;font-weight:600;color:#111827;line-height:1.2;}
.chart-description,.analysis-note,.analysis-scope,.reconciliation,.cost-quality,.graph-scope{font-size:9px;line-height:1.5;margin:4px 0 8px;}
.analysis-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;}
.analysis-grid>section{min-width:0;}
.analysis-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border:1px solid #ddd;margin-bottom:6px;}
.analysis-metric{padding:6px;border-right:1px solid #ddd;font-size:9px;}
.analysis-metric span,.analysis-metric strong,.analysis-metric small{display:block;}
.analysis-metric strong{font-size:14px;margin:4px 0;}
.analysis-print-table{table-layout:fixed;width:100%;}
.analysis-print-table thead{display:table-header-group;}
.analysis-print-table tr{break-inside:avoid;page-break-inside:avoid;}
.analysis-print-table th,.analysis-print-table td{position:static!important;white-space:normal!important;overflow-wrap:anywhere;vertical-align:top;font-size:9px;}
.cell-detail{display:block;font-size:8px;color:#555;}
.analysis-print-table-card{break-inside:auto!important;page-break-inside:auto!important;}
.chart-snapshot-note{font-size:8px;line-height:1.5;color:#555;margin:4px 0;text-align:left;}
table{border-collapse:collapse;width:100%;font-size:10px;}
th,td{border:1px solid #d9d9d9;padding:3px 5px;text-align:left;}
.chart-export-box{width:100%!important;line-height:0;overflow:visible!important;text-align:center;}
img,.chart-export-image{display:block;width:auto!important;height:auto!important;max-width:100%;max-height:58mm;object-fit:contain;margin:0 auto;}
.cost-brand-section .el-table{height:auto!important;}
.cost-brand-section .el-table__body-wrapper{height:auto!important;max-height:none!important;overflow:visible!important;}
.cost-brand-section .el-table__inner-wrapper{height:auto!important;}
.state-tip,.el-empty,.empty-tip{font-size:10px;padding:12px;text-align:center;}
@media print {
  body{padding:0;}
  .el-card{break-inside:avoid;}
}
</style>
</head>
<body>
<h1>${escapeHtml(title)}</h1>
${buildMetaHtml(meta)}
${content}
</body>
</html>`);
  win.document.close();
  const started = Date.now();
  let fontsReady = !win.document.fonts;
  win.document.fonts?.ready.then(() => { fontsReady = true; }, () => { fontsReady = true; });
  const printWhenReady = () => {
    if (win.closed) return;
    const images = Array.from(win.document.images);
    const failed = images.some(image => image.complete && image.naturalWidth === 0);
    if (failed || Date.now() - started >= 10000) {
      ElMessage.error(failed ? '报告图片加载失败，请重新导出' : '报告加载超时，未自动打印，请重新导出');
      return;
    }
    if (fontsReady && images.every(image => image.complete && image.naturalWidth > 0)) {
      win.focus(); win.print(); return;
    }
    setTimeout(printWhenReady, 100);
  };
  setTimeout(printWhenReady, 100);
  return true;
}
