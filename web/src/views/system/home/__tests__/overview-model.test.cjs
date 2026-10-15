const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');

function loadModel() {
  function compile(source) {
    const context = { exports: {}, require: requireModule };
    vm.runInNewContext(ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    }).outputText, context);
    return context.exports;
  }
  function requireModule(name) {
    if (name === '/@/constants/cutterPositions') {
      return compile(fs.readFileSync(path.resolve(__dirname, '../../../../constants/cutterPositions.ts'), 'utf8'));
    }
    throw new Error(`Unexpected import: ${name}`);
  }
  return compile(fs.readFileSync(path.resolve(__dirname, '../overviewModel.ts'), 'utf8'));
}

const model = loadModel();
const plain = value => JSON.parse(JSON.stringify(value));
const record = (ring, extra = {}) => ({
  cutter_position_no: '1', tool_parent_type: 'DISC', warehouse_ring_no: ring,
  is_replaced: true, manufacturer: 'A', ...extra,
});

test('filters active positions and normalizes tool types', () => {
  const discs = [...Array.from({ length: 79 }, (_, i) => String(i + 1)), '80A', '80B', 'Y1', 'Y3', 'Y5'];
  const scrapers = Array.from({ length: 19 }, (_, i) => [`S${i + 1}L`, `S${i + 1}R`]).flat();
  const records = [
    ...discs.map(position => record(10, { cutter_position_no: position })),
    ...scrapers.map(position => record(10, { cutter_position_no: position, tool_parent_type: 'SCRAPER' })),
    ...['0', '80', '81', 'Y2', 'Y4', 'Y6', 'G7L', 'H1', 'S20L', '', null]
      .map(position => record(10, { cutter_position_no: position })),
    record(20, { tool_parent_type: 'RIPPER' }),
  ];
  const discRows = plain(model.buildRows(records, 'DISC'));
  const scraperRows = plain(model.buildRows(records, 'SCRAPER'));
  assert.equal(discRows.length + scraperRows.length, 122);
  assert.deepEqual(discRows.map(row => row.position), ['Y1', 'Y3', 'Y5', ...discs.slice(0, 81)]);
  assert.deepEqual(scraperRows.map(row => row.position), scrapers);
  const aliases = [' disc ', 'CENTER_DISC', 'center', 'SCRAPER'].map((type, i) =>
    record(10, { cutter_position_no: String(i + 1), tool_parent_type: type }));
  assert.deepEqual(plain(model.buildRows(aliases, 'DISC')).map(row => row.position), ['1', '2', '3']);
});

test('keeps original position keys and trusts the record type', () => {
  const rows = model.buildRows(['y1', 'Y1', 'S1L', ' 1 '].map(position =>
    record(10, { cutter_position_no: position })), 'DISC');
  assert.deepEqual(plain(rows).map(row => row.position), ['y1', 'Y1', 'S1L']);
});

test('aggregates checks around the latest replacement', () => {
  const rows = model.buildRows([
    record('280', { is_replaced: false, manufacturer: 'B' }),
    record('100', { replacement_count: 7 }),
    record('250', { is_replaced: false }),
    record('200', { replacement_count: 9, replacement_type: 'REPAIR' }),
  ], 'DISC');
  assert.deepEqual(plain(rows), [{
    position: '1', previousRing: '200', previousReason: '维修', previousMileage: 80,
    averageLife: 100, total: '9/4', manufacturer: 'A', status: 'warning',
    lifeStatus: 'life-high', lifeRatio: 0.8,
  }]);
});

test('rounds displayed life after calculating the risk ratio', () => {
  const row = model.buildRow('2', [record(10), record(13), record(17), record(18, { is_replaced: false })]);
  assert.equal(row.previousRing, 17);
  assert.equal(row.previousReason, '更换');
  assert.equal(row.previousMileage, 1);
  assert.equal(row.averageLife, 4);
  assert.equal(row.lifeRatio, 1 / 3.5);
  assert.equal(row.lifeStatus, 'life-low');
  assert.equal(row.total, '3/4');
});

test('uses placeholders without a replacement history', () => {
  const empty = {
    position: '1', previousRing: '-', previousReason: '-', previousMileage: '-', averageLife: '-',
    total: '0/0', manufacturer: '-', status: 'normal', lifeStatus: 'life-unknown', lifeRatio: null,
  };
  assert.deepEqual(plain(model.buildRow('1', [])), empty);
  assert.deepEqual(plain(model.buildRow('1', [record('120', { is_replaced: false })])),
    { ...empty, total: '0/1', status: 'checked' });
});

test('prefers trimmed case-sensitive manufacturer samples', () => {
  const items = [record(10), record(30, { manufacturer: ' A ' }),
    record(70, { manufacturer: 'a' }), record(100)];
  assert.equal(model.getAverageLifeByItems(items), 30);
  assert.equal(model.getAverageLife(items, record(100)), 45);
});

test('falls back to all samples without a manufacturer lifespan', () => {
  const items = [record(10), record(30), record(100, { manufacturer: 'B' })];
  assert.equal(model.getAverageLife(items, items[2]), 45);
  assert.equal(model.getAverageLife(items, record(100, { manufacturer: ' ' })), 45);
  assert.equal(model.getAverageLife(items, undefined), 45);
});

test('averages positive adjacent replacement gaps only', () => {
  const items = [record(40), record(10), record(10), record(20),
    record(15, { is_replaced: false }), record('invalid')];
  assert.equal(model.getAverageLifeByItems(items), 15);
  for (const sample of [[], [record(10)], [record(10), record(10)],
    [record('bad'), record(10, { is_replaced: false })]]) {
    assert.equal(model.getAverageLifeByItems(sample), null);
  }
});

test('treats null and empty rings as zero in lifespan samples', () => {
  assert.equal(model.getAverageLifeByItems([record(null), record(''), record('10')]), 10);
});

test('includes both risk threshold boundaries', () => {
  const cases = [[null, 'life-unknown'], [0, 'life-low'], [0.33, 'life-low'],
    [0.330001, 'life-mid'], [0.66, 'life-mid'], [0.660001, 'life-high']];
  for (const [ratio, expected] of cases) assert.equal(model.getLifeStatus(ratio), expected);
});

test('prioritizes replacement status over the eighty-ring warning', () => {
  assert.equal(model.getStatus(record(100), 100, 0), 'changed');
  assert.equal(model.getStatus(record(100, { is_replaced: false }), 100, 20), 'warning');
  assert.equal(model.getStatus(record(99, { is_replaced: false }), 99, 20), 'checked');
  assert.equal(model.getStatus(record(100, { is_replaced: false }), null, null), 'checked');
  assert.equal(model.getStatus(undefined, null, null), 'normal');
});

test('sorts records by numeric ring then time then numeric id', () => {
  const items = [record('9', { id: 9 }),
    record('100', { id: 1, warehouse_open_time: '2026-01-01T00:00:00' }),
    record('100', { id: '4', warehouse_open_time: '2026-01-02T00:00:00' }),
    record('100', { id: 12, warehouse_open_time: '2026-01-02T00:00:00' }),
    record('20', { id: 2 }), record('bad', { id: 0 })];
  assert.deepEqual(items.sort(model.compareRecordDesc).map(item => item.id), [12, '4', 1, 2, 9, 0]);
});

test('sorts rows by risk before position', () => {
  const rows = [{ position: 'Y1', lifeStatus: 'life-unknown' },
    { position: '10', lifeStatus: 'life-high' }, { position: '2', lifeStatus: 'life-high' },
    { position: 'Y5', lifeStatus: 'life-low' }, { position: '1', lifeStatus: 'life-mid' },
    { position: 'Y3', lifeStatus: 'life-high' }];
  assert.deepEqual(rows.sort(model.compareLifeThenPosition).map(row => row.position),
    ['Y3', '2', '10', '1', 'Y5', 'Y1']);
});

test('sorts Y positions first then numbers and suffixes', () => {
  const positions = ['80B', '10', 'S19R', 'Y5', '2', 'Y1', '80A', 'S1R', 'S1L', 'Y3'];
  assert.deepEqual(positions.sort(model.comparePosition),
    ['Y1', 'Y3', 'Y5', 'S1L', 'S1R', '2', '10', 'S19R', '80A', '80B']);
});

test('formats local dates and preserves invalid text', () => {
  assert.equal(model.formatDateTime('2026-02-03T04:05:59'), '2026/02/03 04:05');
  assert.equal(model.formatDateTime('bad-date'), 'bad-date');
  for (const value of ['', null, undefined, 0]) assert.equal(model.formatDateTime(value), '');
});

test('overview Vue script and template compile', () => {
  const { compileTemplate } = require('@vue/compiler-sfc');
  const filename = path.resolve(__dirname, '../ToolChangeOverview.vue');
  const { descriptor, errors } = parse(fs.readFileSync(filename, 'utf8'), { filename });
  assert.deepEqual(errors, []);
  const script = compileScript(descriptor, { id: 'overview-model-test' });
  assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename, id: 'overview-model-test', compilerOptions: { bindingMetadata: script.bindings, expressionPlugins: ['typescript'] } }).errors, []);
});
