const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vue = require('vue');
const { setup, descendants, textOf } = require('../../views/shield/analysis/__tests__/helpers.cjs');

const src = path.resolve(__dirname, '../..');
const read = file => fs.readFileSync(path.resolve(src, file), 'utf8');
const modules = {
  '@element-plus/icons-vue': { Search: { name: 'Search' } },
  'element-tree-line': { getElementLabelLine: () => ({ name: 'ElementTreeLine' }) },
};
const mount = (t, options = {}) => setup(t, '../../../components/TreePanel.vue', { modules, ...options });
const byName = (nodes, name) => nodes.filter(node => node.type?.name === name);
const byClass = (nodes, name) => nodes.find(node => node.props?.class === name);

test('search box sits on top with a search icon; the title row only appears with a title', t => {
  const h = mount(t, { props: { placeholder: '请输入部门名称' } });
  const nodes = h.nodes();
  const [input] = byName(nodes, 'el-input');
  assert.equal(input.props['prefix-icon'].name, 'Search');
  assert.equal(input.props.placeholder, '请输入部门名称');
  assert.ok(nodes.indexOf(input) < nodes.indexOf(byName(nodes, 'el-tree')[0]));
  assert.equal(byClass(nodes, 'tree-panel__head'), undefined);
  assert.equal(byClass(nodes, 'tree-panel__footer'), undefined);
});

test('title row shows icon, title, info tip and the page actions; footer holds the page tools', t => {
  const icon = vue.markRaw({ name: 'HomeFilled' });
  const h = mount(t, {
    props: { title: '部门架构', icon, tip: '1.部门信息;' },
    slots: { actions: () => [vue.h('i', { class: 'eye' })], footer: () => [vue.h('i', { class: 'add' })] },
  });
  const nodes = h.nodes();
  const head = byClass(nodes, 'tree-panel__head');
  const inHead = descendants(head);
  assert.ok(inHead.some(node => node.type === icon), 'icon rendered in the title row');
  assert.equal(textOf(byClass(inHead, 'tree-panel__title')), '部门架构');
  assert.equal(byName(inHead, 'InfoTip')[0].props.content, '1.部门信息;');
  assert.ok(descendants(byClass(inHead, 'tree-panel__actions')).some(node => node.props?.class === 'eye'));
  assert.ok(descendants(byClass(nodes, 'tree-panel__footer')).some(node => node.props?.class === 'add'));
});

test('tree props and events written on the panel reach el-tree; indent matches the guide lines', t => {
  const load = () => {}, onNodeClick = () => {};
  const h = mount(t, { props: { $attrs: { data: [{ name: 'A' }], lazy: '', load, onNodeClick } } });
  const [tree] = byName(h.nodes(), 'el-tree');
  assert.deepEqual(tree.props.data, [{ name: 'A' }]);
  assert.equal(tree.props.load, load);
  assert.equal(tree.props.onNodeClick, onNodeClick);
  assert.equal(tree.props['highlight-current'], '');

  const rows = tree.children.default({ node: { label: '技术部' }, data: {} });
  const [line] = byName(descendants(rows), 'ElementTreeLine');
  assert.equal(line.props.indent, tree.props.indent);
  assert.equal(line.props.showLabelLine, false);
  assert.equal(textOf(rows), '技术部', 'falls back to the node label');
});

test('a node slot replaces the label and receives node and data', t => {
  const h = mount(t, { slots: { node: ({ node, data }) => [vue.h('span', `${node.label}（${data.count}人）`)] } });
  const [tree] = byName(h.nodes(), 'el-tree');
  assert.equal(textOf(tree.children.default({ node: { label: '运营部' }, data: { count: 3 } })), '运营部（3人）');
});

test('typing in the search box filters the tree', async t => {
  const h = mount(t);
  const calls = [];
  h.state.treeRef.value = { filter: value => calls.push(value) };
  byName(h.nodes(), 'el-input')[0].props['onUpdate:modelValue']('运营');
  await vue.nextTick();
  assert.deepEqual(calls, ['运营']);
});

test('search box and the tree keep a 10px gap', () => {
  assert.match(read('components/TreePanel.vue'), /\.tree-panel \{[^}]*gap: 10px;/);
});

test('every left-tree page uses TreePanel instead of its own el-tree', () => {
  for (const file of ['views/system/user/index.vue', 'views/system/dept/components/DeptTreeCom/index.vue', 'views/system/menu/components/MenuTreeCom/index.vue']) {
    const source = read(file);
    assert.match(source, /import TreePanel from '\/@\/components\/TreePanel\.vue'/, file);
    assert.match(source, /<TreePanel\b/, file);
    assert.doesNotMatch(source, /<el-tree\b/, file);
  }
});

test('user import buttons are real components', () => {
  for (const file of ['views/system/user/index.vue', 'views/system/dept/components/DeptUserCom/index.vue']) {
    assert.match(read(file), /import importExcel from '\/@\/components\/importExcel\/index\.vue'/, file);
  }
});
