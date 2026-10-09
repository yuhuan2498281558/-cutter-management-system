const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vue = require('vue');
const { compile } = require('../../analysis/__tests__/helpers.cjs');
const source = fs.readFileSync(path.resolve(__dirname, '../crud.tsx'), 'utf8');
const moduleUnderTest = compile(source, name => {
  if (name === 'vue') return vue;
  if (name === '@fast-crud/fast-crud') return { dict: value => value };
  if (name === '../crudUtils') return { createIndexFormatter: () => () => 1 };
  if (name === './api' || name === '/@/utils/service') return {};
  throw new Error(`Unexpected import ${name}`);
});
const columns = moduleUnderTest.createCrudOptions({ crudExpose: {} }).crudOptions.columns;

test('table uses longitudinal field while retaining rock names', () => {
  assert.equal(columns.stratum_type_ratios, undefined);
  assert.equal(columns.rock_types_list.column.formatter({ value: [{ name: '黏土' }] }), '黏土');
  const column = columns.longitudinal_type_ratios.column;
  const value = { AREA_SOFT_HARD: 70, AREA_WEAK_GRANITE: 20, UNRESOLVED: 10 };
  assert.equal(column.formatter({ value }), '上软下硬地层 70%；全断面弱风化花岗岩 20%；未识别区域 10%');
  assert.equal(column.conditionalRender.match({ value }), true);
  assert.equal(column.conditionalRender.render({ value }).children.length, 3);
  assert.equal(column.showOverflowTooltip, false);
});

test('partition labels and percentages use the same reviewed classes, including bedrock', () => {
  assert.equal(columns.stratum_types_list, undefined);
  const zones = [{ code: 'AREA_BEDROCK_PROTRUSION', name: '基岩凸起地层' }];
  assert.equal(columns.engineering_zones_list.column.formatter({ value: zones }), '基岩凸起地层');
  assert.equal(columns.engineering_zones_list.column.formatter({ value: [] }), '分类待核定');
  assert.equal(columns.longitudinal_type_ratios.column.formatter({ value: { AREA_BEDROCK_PROTRUSION: 90,AREA_BOULDER:10 } }), '基岩凸起地层 90%；孤石 10%');
  assert.equal(columns.longitudinal_type_ratios.column.formatter({ value: { ZONE_CLAY_SAND:100 } }), '已识别区域（分类面积待核定） 100%');
  assert.equal(columns.longitudinal_type_ratios.column.formatter({ value: { WEAK_GRANITE: 100 } }), '已识别区域（分类面积待核定） 100%');
});

test('missing data is distinct from zero and small unknown areas stay visible', () => {
  const format = columns.longitudinal_type_ratios.column.formatter;
  assert.equal(format({ value: {} }), '未提取');
  assert.equal(format({}), '未提取');
  assert.equal(format({ value: { SOFT_HARD: 100 } }), '已识别区域（分类面积待核定） 100%');
  assert.equal(format({ value: { SOFT_HARD: 99.995, UNRESOLVED: 0.005 } }).includes('未识别区域 <0.01%'), true);
});

test('cached tag-derived ratios are withheld and explicit boulder note is retained', () => {
  const column = columns.longitudinal_type_ratios.column;
  const value = { CLAY_SAND: 98.880005, SOFT_HARD: 0, WEAK_GRANITE: 0, UNRESOLVED: 1.119995 };
  assert.equal(column.formatter({ value }), '已识别区域（分类面积待核定） 98.88%；未识别区域 1.12%');
  assert.equal(column.conditionalRender.render({ value }).children.length, 2);
  assert.equal(column.formatter({ value: { SOFT_SOIL: 95, UNRESOLVED: 5 } }), '已识别区域（分类面积待核定） 95%；未识别区域 5%');
  assert.equal(column.formatter({ value: { OTHER_IDENTIFIED: 100 } }), '已识别区域（分类面积待核定） 100%');
  const row = { longitudinal_area_notes: ['孤石：有区段记录，面积尚未核定'] };
  assert.ok(column.formatter({ value: { SOFT_HARD: 96.67, UNRESOLVED: 3.33 }, row }).includes(row.longitudinal_area_notes[0]));
  assert.equal(column.conditionalRender.render({ value, row }).children.length, 3);
});
