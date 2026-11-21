// 固定样本按当前模板原文和显式替换值核对，不读取任何业务数据。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const cases = JSON.parse(fs.readFileSync(path.resolve(__dirname,
  '../../../../../backend/application/ai_assistant/evaluation/fixed_cases.json'), 'utf8'));
const source = fs.readFileSync(path.resolve(__dirname, '../constants.ts'), 'utf8');
const ts = require('typescript');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
const constants = { exports: {} };
new Function('exports', 'module', compiled)(constants.exports, constants);
const quick = constants.exports.quickQuestionGroups.flatMap(group => group.items);
const models = constants.exports.modelPromptTemplates;

// 前端新增快捷问题或模板而题单没有跟上时，下面两项会失败
test('全部快捷问题与固定题单逐条同步', () => {
  const fixed = cases.filter(item => item.kind === 'quick');
  assert.equal(fixed.length, quick.length, '快捷问题数量与固定题单不同，请同步 fixed_cases.json');
  fixed.forEach((item, index) => check(item, quick[index]));
});

test('每个模型模板都有固定变体且与当前原文同步', () => {
  const fixed = cases.filter(item => item.kind === 'model');
  for (const template of models) {
    assert.ok(fixed.some(item => item.source_title === template.title), `模板没有固定变体：${template.title}`);
  }
  for (const item of fixed) {
    const template = models.find(model => model.title === item.source_title);
    assert.ok(template, `${item.id} 模板不存在：${item.source_title}`);
    check(item, template);
    assert.deepEqual(item.focus_sources, template.sources, `${item.id} 关注数据源不同`);
  }
});

function check(item, template) {
  let question = template.query;
  assert.equal(item.source_question, question, `${item.id} 原文不同`);
  for (const [key, value] of Object.entries(item.substitutions || {})) {
    question = question.replaceAll(`{${key}}`, String(value));
    if (key === 'n') assert.equal(Number(value), template.defaultValue, `${item.id} 默认值不同`);
  }
  assert.equal(item.question, question, `${item.id} 问句不同`);
}
