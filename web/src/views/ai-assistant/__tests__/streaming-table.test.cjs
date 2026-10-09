// Mount the actual SFC in Vue's renderer. Track host node identity, not just parser output.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');

const sourcePath = process.env.ANALYSIS_MESSAGE_TEST_SOURCE || path.resolve(__dirname, '../components/AnalysisMessage.vue');
const { descriptor } = parse(fs.readFileSync(sourcePath, 'utf8'), { filename: sourcePath });
const compiled = compileScript(descriptor, { id: 'streaming-table-test', inlineTemplate: true });
const context = { exports: {}, require: name => {
  if (name === 'vue') return vue;
  if (name === '../constants') return { SECTION_TITLES: ['结论', '关键依据', '注意事项'] };
  throw new Error(`Unexpected import: ${name}`);
} };
vm.runInNewContext(ts.transpileModule(compiled.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, context);
const AnalysisMessage = context.exports.default;

function mountMessage(content, streaming = true) {
  const node = (tag, text = '') => ({ tag, text, props: {}, children: [], parent: null });
  const mutations = [];
  const detach = child => {
    if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1);
    child.parent = null;
  };
  const renderer = vue.createRenderer({
    createElement: tag => node(tag), createText: text => node('#text', text), createComment: text => node('#comment', text),
    setText: (element, text) => { element.text = text; },
    setElementText: (element, text) => { element.text = text; element.children = []; },
    parentNode: element => element.parent,
    nextSibling: element => element.parent?.children[element.parent.children.indexOf(element) + 1] || null,
    insert(element, parent, anchor = null) {
      detach(element);
      parent.children.splice(anchor ? parent.children.indexOf(anchor) : parent.children.length, 0, element);
      element.parent = parent;
    },
    remove(element) { mutations.push({ type: 'remove', element }); detach(element); },
    patchProp(element, key, previous, next) { mutations.push({ type: key, element, previous, next }); element.props[key] = next; },
    setScopeId() {},
  });
  const root = node('root');
  const props = vue.reactive({ content, streaming });
  const app = renderer.createApp({ setup: () => () => vue.h(AnalysisMessage, props) });
  app.mount(root);
  const find = (tag, parent = root) => parent.children.flatMap(child => [...(child.tag === tag ? [child] : []), ...find(tag, child)]);
  return { props, find, mutations, unmount: () => app.unmount(), async append(text) { props.content += text; await vue.nextTick(); } };
}

const header = '## 刀位与地层\n\n| 刀位 | 地层标签关联次数 | 各地层关联次数 |\n| --- | --- | --- |\n';
const row = '| 17 | 9 | 黏土夹砂地层 4次、上软下硬地层 3次、全断面弱风化花岗岩 1次、孤石 1次 |\n';

test('streaming from the first character commits the separator once and never remounts a valid table', async () => {
  const h = mountMessage('');
  try {
    let table;
    for (const char of header + row) {
      await h.append(char);
      const current = h.find('table')[0];
      if (table) assert.equal(current, table, 'table must remain mounted while delimiter and body arrive');
      else if (current) table = current;
    }
    assert.ok(table);
    assert.equal(h.find('td').length, 3);
  } finally { h.unmount(); }
});

test('every streamed character preserves the table, header and completed cells; only complete rows append', async () => {
  const h = mountMessage(header + row);
  try {
    const table = h.find('table')[0], head = h.find('thead')[0], body = h.find('tbody')[0];
    const firstRow = h.find('tr', body)[0];
    const originalCells = h.find('td');
    const originalValues = originalCells.map(cell => cell.props.innerHTML);
    const remaining = row.replace('| 17 |', '| 19 |') + row.replace('| 17 |', '| S19R |');
    let completeRows = 1;
    for (const char of remaining) {
      const mutationStart = h.mutations.length;
      await h.append(char);
      if (char === '\n') completeRows += 1;
      assert.equal(h.find('table')[0], table, `table replaced after ${JSON.stringify(char)}`);
      assert.equal(h.find('thead')[0], head);
      assert.equal(h.find('tbody')[0], body);
      assert.equal(h.find('tr', body)[0], firstRow);
      assert.equal(h.find('td').length, completeRows * 3);
      originalCells.forEach((cell, index) => {
        assert.equal(h.find('td')[index], cell);
        assert.equal(cell.props.innerHTML, originalValues[index]);
        assert.equal(h.mutations.slice(mutationStart).some(mutation => mutation.element === cell), false, 'completed cells must not be rewritten');
      });
      assert.equal(h.find('pre').length, 0, 'valid streaming table must never fall back to source');
    }
    h.props.streaming = false;
    await vue.nextTick();
    assert.equal(h.find('table')[0], table);
    assert.equal(h.find('thead')[0], head);
    assert.equal(h.find('tr', body)[0], firstRow);
  } finally { h.unmount(); }
});

test('a final row without newline flushes on completion without replacing the table', async () => {
  const h = mountMessage(header + row);
  try {
    const table = h.find('table')[0];
    await h.append('| S19R | 0 | A\\|B地层、暂无 |');
    assert.equal(h.find('td').length, 3);
    h.props.streaming = false;
    await vue.nextTick();
    assert.equal(h.find('table')[0], table);
    assert.deepEqual(h.find('td').slice(-3).map(cell => cell.props.innerHTML), ['S19R', '0', 'A|B地层、暂无']);
  } finally { h.unmount(); }
});

test('borderless rows and CRLF streams stay inside the same table while their next line is incomplete', async () => {
  const h = mountMessage('刀位 | 数量\r\n--- | ---\r\n17 | 9\r\n');
  try {
    const table = h.find('table')[0];
    for (const char of 'S19R | 10') {
      await h.append(char);
      assert.equal(h.find('table')[0], table);
      assert.equal(h.find('p').length, 0);
      assert.equal(h.find('td').length, 2);
    }
    await h.append('\r\n');
    assert.equal(h.find('td').length, 4);
  } finally { h.unmount(); }
});

test('long later values do not change header-based column sizing', async () => {
  const h = mountMessage(header + row);
  try {
    const table = h.find('table')[0];
    const sizes = JSON.stringify(h.find('col').map(col => col.props.style));
    assert.equal(h.find('col').length, 3);
    assert.ok(table.props.style.minWidth);
    await h.append(`| 999 | 10000 | ${'很长的地层说明'.repeat(25)} |\n`);
    assert.equal(JSON.stringify(h.find('col').map(col => col.props.style)), sizes);
  } finally { h.unmount(); }
});

test('final malformed source and unsafe cells are retained as text without creating HTML elements', async () => {
  const h = mountMessage(header + row);
  try {
    await h.append('| <img src=x onerror=alert(1)> | 0 | 地层 | 不得丢失的多余列 |');
    assert.equal(h.find('table').length, 1);
    assert.equal(h.find('img').length, 0);
    h.props.streaming = false;
    await vue.nextTick();
    assert.equal(h.find('pre')[0].text, h.props.content.slice(h.props.content.indexOf('| 刀位')));
    assert.equal(h.find('img').length, 0);
    assert.match(h.find('p')[0].text, /已保留原文/);
  } finally { h.unmount(); }
});

test('replacing an answer discards its old table and partial tail', async () => {
  const h = mountMessage(header + row + '| 未完成');
  try {
    h.props.content = '## 新回答\n\n**结论**\n\n1. 复核数据\n2. 查看 `S1L`';
    h.props.streaming = false;
    await vue.nextTick();
    assert.equal(h.find('table').length, 0);
    assert.equal(h.find('h2')[0].props.innerHTML, '新回答');
    assert.equal(h.find('p')[0].props.innerHTML, '<strong>结论</strong>');
    assert.equal(h.find('li').length, 2);
    assert.equal(h.find('li')[1].props.innerHTML, '查看 <code>S1L</code>');
  } finally { h.unmount(); }
});
