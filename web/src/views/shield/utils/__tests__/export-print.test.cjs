const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function exportHtml(format, columnCount = 18, printWidths = []) {
  const documents = [], blobs = [];
  const source = fs.readFileSync(process.env.EXPORT_PRINT_TEST_FILE || path.resolve(__dirname, '../export.ts'), 'utf8');
  const context = {
    exports: {}, Blob,
    URL: { createObjectURL(blob) { blobs.push(blob); return 'blob:export'; }, revokeObjectURL() {} },
    document: { createElement: () => ({ style: {}, click() {} }), body: { appendChild() {}, removeChild() {} } },
    window: { open: () => ({ document: { write: html => documents.push(html), close() {} }, focus() {}, print() {} }) },
    setTimeout: fn => fn(),
  };
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, context);
  const options = {
    format, title: '换刀明细 <验收>', filename: 'print-test',
    columns: Array.from({ length: columnCount }, (_, i) => ({ key: `column${i}`, title: `字段${i}`, printWidth: printWidths[i] })),
    meta: Array.from({ length: 16 }, (_, i) => ({ label: `开仓字段${i}`, value: i === 0 ? 0 : `开仓值${i}`, span: i >= 14 ? 3 : undefined })),
    rows: Array.from({ length: 122 }, (_, row) => Object.fromEntries(Array.from({ length: columnCount }, (_, col) => [`column${col}`, col === 0 ? `POS-${row}` : col === 1 ? '第一行\n第二行 <b>文字</b>' : 0]))),
  };
  const before = JSON.stringify(options);
  context.exports.exportTableData(options);
  assert.equal(JSON.stringify(options), before);
  return { html: documents[0], blobs };
}

test('opening metadata rows contain no array separator text in PDF or Excel', async () => {
  for (const format of ['pdf', 'excel']) {
    const result = exportHtml(format);
    const html = result.html || await result.blobs[0].text();
    assert.doesNotMatch(html, /<\/tr>\s*,\s*<tr/);
    for (let i = 0; i < 16; i++) assert.ok(html.includes(`开仓字段${i}`));
  }
});

test('PDF repeats only detail headers and keeps metadata outside the repeating table', () => {
  const { html } = exportHtml('pdf');
  const header = html.match(/<thead>([\s\S]*?)<\/thead>/)?.[1];
  assert.ok(header);
  assert.equal((header.match(/<th>/g) || []).length, 18);
  assert.doesNotMatch(header, /开仓字段/);
  assert.ok(html.indexOf('开仓基本信息') < html.indexOf('<thead>'));
  assert.match(html, /thead\{[^}]*display:table-header-group/);
  assert.equal((html.match(/<td>/g) || []).length, 122 * 18);
  for (let i = 0; i < 122; i++) assert.ok(html.includes(`<td>POS-${i}</td>`));
  assert.ok(html.includes('第一行\n第二行 &lt;b&gt;文字&lt;/b&gt;'));
  assert.ok(html.includes('换刀明细 &lt;验收&gt;'));
});

test('print layout selects wide paper only for wide tables and allows long values to wrap', () => {
  assert.match(exportHtml('pdf', 18).html, /@page\{size:A3 landscape/);
  assert.match(exportHtml('pdf', 8).html, /@page\{size:A4 landscape/);
  assert.match(exportHtml('pdf', 4).html, /@page\{size:A4 portrait/);
  assert.match(exportHtml('pdf').html, /overflow-wrap:anywhere/);
  assert.match(exportHtml('pdf').html, /white-space:pre-line/);
});

test('Excel keeps its single-table layout without PDF page settings', async () => {
  const { blobs } = exportHtml('excel');
  const html = await blobs[0].text();
  assert.equal((html.match(/<table\b/g) || []).length, 1);
  assert.doesNotMatch(html, /@page|<thead>/);
  assert.equal((html.match(/<td>/g) || []).length, 122 * 18);
});

test('relative print widths allocate more room to long fields without changing cell values', () => {
  const { html } = exportHtml('pdf', 3, [1, 3, 1]);
  const widths = Array.from(html.matchAll(/<col style="width:([\d.]+)%">/g), match => Number(match[1]));
  assert.deepEqual(widths, [20, 60, 20]);
  assert.ok(html.includes('<td>POS-121</td>'));
  assert.ok(html.includes('第一行\n第二行 &lt;b&gt;文字&lt;/b&gt;'));
});
