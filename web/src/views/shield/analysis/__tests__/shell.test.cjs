const { test } = require('node:test');
const assert = require('node:assert/strict');
const vue = require('vue');
const { setup, plain, descendants } = require('./helpers.cjs');

const text = node => descendants(node).map(item => typeof item.children === 'string' ? item.children : '').join('');
const byClass = (nodes, name) => nodes.find(node => node.props?.class === name);

test('shell puts tabs under the title, filters above the page and hands the action area to the active page', t => {
  const h = setup(t, 'index.vue');
  const nodes = h.nodes();
  const heading = byClass(nodes, 'analysis-heading');
  assert.equal(text(heading), '数据分析', 'no subtitle under the title');
  const actions = descendants(heading).find(node => node.props?.class === 'analysis-actions');
  assert.equal(actions.ref.r, 'actionsRef');

  const tabs = nodes.find(node => node.type?.name === 'el-tabs');
  const panes = descendants(tabs).filter(node => node.type?.name === 'el-tab-pane');
  assert.deepEqual(panes.map(node => node.props.label), ['概览', '成本', '磨损', '自定义']);
  assert.ok(panes.every(node => node.children == null), 'tabs only navigate');
  const order = ['el-tabs', 'FilterPanel', 'Overview'].map(name => nodes.findIndex(node => node.type?.name === name));
  assert.deepEqual(order, [...order].sort((a, b) => a - b));
  assert.equal(descendants(tabs).some(node => node.type?.name === 'Overview'), false);

  const page = name => h.nodes().filter(node => ['Overview', 'CostAnalysis', 'WearAnalysis', 'CustomAnalysis'].includes(node.type?.name)).map(node => [node.type.name, node.props['actions-target']]);
  assert.deepEqual(page(), [['Overview', null]]);
  const target = { nodeType: 1 };
  h.state.actionsRef.value = target;
  for (const [tab, name] of [['cost', 'CostAnalysis'], ['wear', 'WearAnalysis'], ['custom', 'CustomAnalysis']]) {
    h.state.activeTab.value = tab;
    const [[rendered, passed], ...others] = page();
    assert.equal(rendered, name); assert.equal(vue.toRaw(passed), target); assert.equal(others.length, 0);
  }
});

test('page actions appear only with a target and show generated time, refresh and exports', t => {
  const runs = [];
  const item = (label, disabled = false) => ({ label, disabled, run: () => runs.push(label) });
  const h = setup(t, 'components/AnalysisActions.vue', { props: { target: null, generatedAt: '', refresh: undefined, refreshing: false, exports: [item('导出 PDF')] } });
  assert.equal(h.nodes().some(node => node.type === vue.Teleport), false);

  const target = { nodeType: 1 };
  h.props.target = target;
  let nodes = h.nodes();
  const teleport = nodes.find(node => node.type === vue.Teleport);
  assert.equal(vue.toRaw(teleport.props.to), target);
  assert.equal(byClass(nodes, 'analysis-generated'), undefined, 'no time before data arrives');
  assert.equal(nodes.some(node => node.type?.name === 'el-dropdown'), false);
  let buttons = nodes.filter(node => node.type?.name === 'el-button');
  assert.deepEqual(buttons.map(text), ['导出 PDF'], 'no refresh unless the page provides one');
  buttons[0].props.onClick(); assert.deepEqual(runs, ['导出 PDF']);

  let refreshed = 0;
  Object.assign(h.props, { generatedAt: '2026-09-01T08:05:00', refresh: () => refreshed++, refreshing: true, exports: [item('导出 PDF', true)] });
  nodes = h.nodes();
  assert.equal(text(byClass(nodes, 'analysis-generated')), '生成于 09-01 08:05');
  buttons = nodes.filter(node => node.type?.name === 'el-button');
  assert.deepEqual(plain(buttons.map(node => [text(node), node.props.disabled])), [['刷新', true], ['导出 PDF', true]]);
  buttons[0].props.onClick(); assert.equal(refreshed, 1);
  buttons[1].props.onClick(); assert.deepEqual(runs, ['导出 PDF'], 'a disabled export never runs');

  h.props.exports = [item('费用来源 PDF'), item('厂家表现 PDF', true)];
  nodes = h.nodes();
  const dropdown = nodes.find(node => node.type?.name === 'el-dropdown');
  const trigger = descendants(dropdown).find(node => node.type?.name === 'el-button');
  assert.equal(text(trigger), '导出'); assert.equal(trigger.props.disabled, false);
  const entries = descendants(dropdown).filter(node => node.type?.name === 'el-dropdown-item');
  assert.deepEqual(plain(entries.map(node => [text(node), node.props.command, node.props.disabled])), [['费用来源 PDF', 0, false], ['厂家表现 PDF', 1, true]]);
  dropdown.props.onCommand(1); dropdown.props.onCommand(0);
  assert.deepEqual(runs, ['导出 PDF', '费用来源 PDF']);
  h.props.generatedAt = 'not a date';
  assert.equal(byClass(h.nodes(), 'analysis-generated'), undefined);
});

test('scope line shows openings and observations; exclusions and basis stay in the expandable part', t => {
  const meta = {
    opening_count: 1234, observed_count: 0, draft_opening_count: 2, summary_status: 'CONFIRMED', unobserved_count: 0,
    excluded_inactive_count: 3, excluded_invalid_ring_opening_count: 0, warnings: ['范围提示'], wear_basis: '磨损口径',
    observed_basis: '观察口径', blade_track_basis: '轨迹口径', scope: {}, generated_at: '2026-09-01T08:05:00',
  };
  const h = setup(t, 'components/ScopeSummary.vue', { props: { meta }, slots: { default: () => [vue.h('p', { class: 'page-basis' }, '页面口径')] } });
  let nodes = h.nodes();
  const summary = nodes.find(node => node.type === 'summary');
  assert.equal(text(summary), '1,234 次开仓 · 0 条有效观察统计口径与已排除记录');
  const details = byClass(nodes, 'scope-details');
  const lines = descendants(details).filter(node => node.type === 'p').map(text);
  assert.deepEqual(lines.slice(0, 4), ['工程范围草稿 2 次（未纳入）', '3 条历史无效刀位已排除', '范围提示', '磨损口径']);
  assert.ok(lines.includes('观察口径')); assert.ok(lines.includes('页面口径'));
  assert.equal(lines.some(line => /预建未观察|环号不可用|轨迹口径/.test(line)), false, 'zero counts and unused bounds stay hidden');
  assert.equal(nodes.some(node => /生成于/.test(text(node))), false, 'generated time moved to the title row');

  h.props.meta = { ...meta, observed_count: undefined, unobserved_count: 5, excluded_invalid_ring_opening_count: 1, scope: { blade_track_max: '3000' } };
  nodes = h.nodes();
  assert.equal(text(nodes.find(node => node.type === 'summary').children[0]), '1,234 次开仓');
  const more = descendants(byClass(nodes, 'scope-details')).filter(node => node.type === 'p').map(text);
  assert.ok(more.includes('5 条预建未观察记录未纳入')); assert.ok(more.includes('1 次开仓环号不可用，已排除')); assert.ok(more.includes('轨迹口径'));
  h.props.meta = undefined;
  assert.equal(h.nodes().some(node => node.type === 'details'), false);
});

test('chart description sits in an ⓘ beside the title instead of a line under it', t => {
  const h = setup(t, 'components/ChartCard.vue', {
    props: { title: '刀具类型的费用贡献', description: '待核对金额不进入堆叠。', loading: false, height: undefined, chartHeight: undefined, isEmpty: false, error: '', emptyDescription: '' },
    slots: { toolbar: () => [vue.h('span', { class: 'toolbar-probe' })], default: () => [] },
  });
  const heading = byClass(h.nodes(), 'chart-heading');
  const elements = node => descendants(node).slice(1).filter(item => typeof item.type !== 'symbol').map(item => item.type?.name || item.type);
  assert.deepEqual(elements(heading), ['h3', 'InfoTip']);
  assert.equal(descendants(heading).find(node => node.type?.name === 'InfoTip').props.content, '待核对金额不进入堆叠。');
  assert.equal(h.nodes().some(node => node.props?.class === 'chart-description'), false);
  assert.ok(h.nodes().some(node => node.props?.class === 'toolbar-probe'));
  assert.equal(descendants(heading).some(node => node.props?.class === 'toolbar-probe'), false, 'toolbar stays outside the heading');
  h.props.description = '';
  assert.equal(descendants(byClass(h.nodes(), 'chart-heading')).some(node => node.type?.name === 'InfoTip'), false);
});

test('InfoTip keeps the full wording in the tooltip, the accessible name and the PDF data attribute', t => {
  const content = '新装登记、已确认返修、历史登记三类之和，不是财务结算额';
  const h = setup(t, '../../../components/InfoTip.vue', { props: { content } });
  const tooltip = h.nodes().find(node => node.type?.name === 'el-tooltip');
  assert.equal(tooltip.props.content, content);
  assert.deepEqual(plain(tooltip.props['popper-style']), { maxWidth: '320px' });
  const button = descendants(tooltip).find(node => node.type === 'button');
  assert.deepEqual(plain({ type: button.props.type, label: button.props['aria-label'], data: button.props['data-info-tip'], text: button.children }),
    { type: 'button', label: content, data: content, text: 'i' });
});
