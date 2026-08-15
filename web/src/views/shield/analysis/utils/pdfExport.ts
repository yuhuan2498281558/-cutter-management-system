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
      const canvas = chartRoot.querySelector('canvas');
      const clonedChartRoot = targetChartRoots[index];
      if (!canvas || !clonedChartRoot) return;

      const imageWrap = document.createElement('div');
      imageWrap.className = 'chart-export-box';
      imageWrap.appendChild(createChartImage(canvas));
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
  target.querySelectorAll('.analysis-export-bar').forEach(el => el.remove());
}

export interface AnalysisPdfSection {
  title: string;
  selector: string;
}

export interface AnalysisPdfMetaItem {
  label: string;
  value: string;
}

function cloneSection(selector: string) {
  const source = document.querySelector(selector) as HTMLElement | null;
  if (!source) return '';
  const cloned = source.cloneNode(true) as HTMLElement;
  copyCanvasToImages(source, cloned);
  removeExportBars(cloned);
  return cloned.outerHTML;
}

function buildMetaHtml(meta: AnalysisPdfMetaItem[] = []) {
  if (!meta.length) return '';
  const rows: string[] = [];
  for (let i = 0; i < meta.length; i += 3) {
    const group = meta.slice(i, i + 3);
    const cells = group.map(item => `
      <th>${item.label}</th>
      <td>${item.value || '全部'}</td>
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
) {
  const sections = typeof selectorOrSections === 'string'
    ? [{ title: '', selector: selectorOrSections }]
    : selectorOrSections;

  const content = sections.map(section => {
    const html = cloneSection(section.selector);
    if (!html) return '';
    return `<section class="pdf-section">
      ${section.title ? `<h2>${section.title}</h2>` : ''}
      ${html}
    </section>`;
  }).join('');

  const win = window.open('', '_blank');
  if (!win) return;

  win.document.write(`<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>${title}</title>
<style>
@page{size:A4 landscape;margin:5mm;}
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
table{border-collapse:collapse;width:100%;font-size:10px;}
th,td{border:1px solid #d9d9d9;padding:3px 5px;text-align:left;}
.chart-export-box{width:100%!important;line-height:0;overflow:visible!important;text-align:center;}
img,.chart-export-image{display:block;width:auto!important;height:auto!important;max-width:100%;max-height:58mm;object-fit:contain;margin:0 auto;}
.cost-brand-section .el-table{height:auto!important;}
.cost-brand-section .el-table__body-wrapper{height:auto!important;max-height:none!important;overflow:visible!important;}
.cost-brand-section .el-table__inner-wrapper{height:auto!important;}
.el-empty,.empty-tip{display:none!important;}
@media print {
  body{padding:0;}
  .el-card{break-inside:avoid;}
}
</style>
</head>
<body>
<h1>${title}</h1>
${buildMetaHtml(meta)}
${content}
</body>
</html>`);
  win.document.close();
  win.focus();
  const printWhenReady = () => {
    const images = Array.from(win.document.images);
    if (!images.length || images.every(image => image.complete)) {
      win.print();
      return;
    }
    setTimeout(printWhenReady, 100);
  };
  setTimeout(printWhenReady, 300);
}
