const { test } = require('node:test');
const assert = require('node:assert/strict');
const vue = require('vue');
const { setup, plain, descendants } = require('./helpers.cjs');

const text = node => descendants(node).map(item => typeof item.children === 'string' ? item.children : '').join('');

test('amount shares divide by the total and show — when the total is zero or missing', t => {
  const parts = [
    { label: '新装刀具登记', amount: 75, color: '#3f5f7a', tip: '装入刀具登记，可能包含维修件' },
    { label: '已确认返修', amount: 25, color: '#6f8f6a' },
    { label: '历史登记', amount: 0, color: '#c2b8a3' },
  ];
  const h = setup(t, 'components/AmountShare.vue', { props: { parts, total: 100 } });
  const cells = name => h.nodes().filter(node => node.props?.class === name).map(node => node.children);
  const bar = () => h.nodes().find(node => node.props?.class === 'share-bar');
  const segments = () => plain(descendants(bar()).filter(node => node.type === 'span').map(node => node.props.style));
  assert.deepEqual(cells('share-amount'), ['¥75', '¥25', '¥0']);
  assert.deepEqual(cells('share-percent'), ['75.0%', '25.0%', '0.0%']);
  assert.deepEqual(segments(), [{ width: '75%', background: '#3f5f7a' }, { width: '25%', background: '#6f8f6a' }, { width: '0%', background: '#c2b8a3' }]);
  assert.equal(bar().props['aria-label'], '新装刀具登记 75.0%，已确认返修 25.0%，历史登记 0.0%');
  assert.deepEqual(plain(descendants(h.nodes()[0]).filter(node => node.props?.class === 'share-swatch').map(node => node.props.style.background)), ['#3f5f7a', '#6f8f6a', '#c2b8a3']);
  assert.deepEqual(h.nodes().filter(node => node.type?.name === 'InfoTip').map(node => node.props.content), ['装入刀具登记，可能包含维修件']);

  for (const total of [0, null, undefined, NaN]) {
    h.props.total = total;
    assert.deepEqual(cells('share-percent'), ['—', '—', '—'], String(total));
    assert.deepEqual(segments().map(item => item.width), ['0%', '0%', '0%']);
    assert.deepEqual(cells('share-amount'), ['¥75', '¥25', '¥0'], 'amounts stay visible');
  }
  h.props.total = 100;
  h.props.parts = [{ ...parts[0], amount: null }, parts[1], parts[2]];
  assert.deepEqual(cells('share-amount'), ['未记录', '¥25', '¥0']);
  assert.deepEqual(cells('share-percent'), ['—', '25.0%', '0.0%']);
});

test('review list shows only non-zero items, folds zero items into one line, and says so when nothing needs review', t => {
  const items = [
    { name: '缺登记价格', pending: false, lead: '0 条缺登记价格', detail: '没有计入金额，合计偏小' },
    { name: '返修待确认', pending: true, lead: '274 条返修待确认', detail: '确认后，返修金额和合计还会增加' },
    { name: '已确认返修缺价', pending: false, lead: '0 条已确认返修缺价', detail: '未计入返修金额' },
    { name: '金额归属待核对', pending: false, lead: '0 条金额归属待核对（¥0）', detail: '未计入合计' },
  ];
  const h = setup(t, 'components/ReviewList.vue', { props: { items } });
  const lines = () => h.nodes().filter(node => node.type === 'p').map(node => [node.props.class, text(node)]);
  assert.deepEqual(lines(), [
    ['review-item', '274 条返修待确认：确认后，返修金额和合计还会增加'],
    ['review-quiet', '缺登记价格、已确认返修缺价、金额归属待核对：均为 0'],
  ]);
  assert.equal(h.nodes().find(node => node.type === 'b').children, '274 条返修待确认');

  h.props.items = items.map(item => ({ ...item, pending: true }));
  assert.equal(lines().length, 4); assert.ok(lines().every(([name]) => name === 'review-item'), 'no zero line when every item is pending');
  h.props.items = items.map(item => ({ ...item, pending: false }));
  assert.deepEqual(lines(), [['review-quiet', '没有需要核对的记录']]);
});

test('a chart card heading slot replaces the title, keeping toolbar and body states', t => {
  const h = setup(t, 'components/ChartCard.vue', {
    props: { title: undefined, description: '不显示', loading: false, height: undefined, chartHeight: undefined, isEmpty: false, error: '', emptyDescription: '' },
    slots: { heading: () => [vue.h('span', { class: 'heading-probe' }, '页签')], default: () => [] },
  });
  const heading = h.nodes().find(node => node.props?.class === 'chart-heading');
  assert.equal(text(heading), '页签');
  assert.equal(descendants(heading).some(node => node.type === 'h3' || node.type?.name === 'InfoTip'), false);
});
