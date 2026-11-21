const test = require('node:test');
const assert = require('node:assert/strict');
const { setup, settle, plain, deferred } = require('./helpers.cjs');
const meta = { schema_version: 2, generated_at: '2026-09-11T00:00:00Z', summary_status: 'CONFIRMED', scope: { project_name: 'P' } };
const fields = { dimensions: ['ring_no', 'manufacturer', 'tool_parent_type'].map(value => ({value, label:value, chart_types:['line','matrix']})), metrics: [{ value:'replacement_count',label:'更换数',unit:'把' }, {value:'total_cost',label:'登记费用',unit:'元'}] };
function result(params) { return { meta, chart_type: params.chart_type, x_field: {value:params.x_field,label:params.x_field}, y_field:{value:'tool_parent_type',label:'刀型'}, metrics:[{value:'replacement_count',label:'更换数',unit:'把'}], categories:['A'], x_categories:['<img>'], y_categories:['滚刀'], series:[{metric:'replacement_count',name:'更换数',unit:'把',data:params.chart_type === 'matrix' ? [[0,0,0],[1,0,null]] : [0]}], rows:[{x:'A',replacement_count:0}], record_count:1 }; }
function harness(t, request, options = {}) { const h=setup(t,'pages/CustomAnalysis.vue',{request:request || (async c=>({data:c.url.includes('custom_fields')?fields:result(c.params)})), ...options}); h.state.chartRef.value={}; return h; }
test('custom uses categorical bars, time lines and success labels',async t=>{
  const h=harness(t); await h.mount(); assert.equal(h.charts[0].options.at(-1).series[0].type,'line');
  h.state.form.metrics=['replacement_count']; h.state.form.x_field='manufacturer'; await settle();
  assert.equal(h.charts[0].options.at(-1).series[0].type,'bar');
  assert.match(h.state.chartTitle.value,/manufacturer.*比较/);
  assert.equal(h.state.selectedMetricMeta.value[0].label,'更换数');
});
test('clearing metrics immediately removes results and prevents old export',async t=>{
  const h=harness(t); await h.mount(); h.state.exportPdf(); assert.equal(h.exports.length,1);
  h.state.form.metrics=[]; h.state.exportPdf(); assert.equal(h.exports.length,1); await settle();
  assert.equal(h.state.chartData.value,null); assert.deepEqual(plain(h.state.tableRows.value),[]);
});
test('late chart cannot override latest configuration',async t=>{
  const old=deferred(); const h=harness(t, async c=>({data:c.url.includes('custom_fields')?fields:c.params.x_field==='ring_no'?await old.promise:result(c.params)}));
  const pending=h.mount(); await settle(); h.state.form.metrics=['replacement_count']; h.state.form.x_field='manufacturer'; await settle();
  old.resolve(result({chart_type:'line',x_field:'ring_no'})); await pending;
  assert.equal(h.state.chartData.value.x_field.value,'manufacturer');
});
test('matrix keeps null distinct from zero, escapes names and sizes by current width',async t=>{
  const h=harness(t); await h.mount(); h.state.form.metrics=['replacement_count']; h.state.form.chart_type='matrix'; await settle();
  let option=h.charts[0].options.at(-1); assert.equal(option.series[0].data.length,1); assert.equal(option.series[0].data[0].value[2],0);
  assert.match(option.tooltip.formatter({value:[0,0,0,0]}),/&lt;img&gt;/);
  h.charts[0].width=320; h.state.renderChart(); option=h.charts[0].options.at(-1); assert.ok(option.grid.left<=100);
});
test('unsupported manufacturer wear warns and never leaves a previous result',async t=>{
  const h=harness(t); await h.mount(); h.state.form.x_field='manufacturer'; await settle();
  assert.match(h.state.validationError.value,/厂家磨损/); assert.equal(h.state.ready.value,false);
  const calls=h.requests.filter(r=>r.url.includes('custom_chart')); assert.equal(calls.length,1);
});
test('field failure can be retried and unmount disposes chart',async t=>{
  let fail=true; const h=harness(t,async c=>{if(fail&&c.url.includes('custom_fields')) throw new Error('失败');return {data:c.url.includes('custom_fields')?fields:result(c.params)};});
  await h.mount(); assert.ok(h.state.fieldsError.value); fail=false; await h.state.loadChart(); await settle();
  assert.equal(h.state.ready.value,true); h.unmount(); assert.equal(h.charts[0].disposed,true);
});
test('a successful field retry loads the chart without another click', async t => {
  let fail = true; const h = harness(t, async c => { if (fail && c.url.includes('custom_fields')) throw new Error('失败'); return { data: c.url.includes('custom_fields') ? fields : result(c.params) }; });
  await h.mount(); assert.ok(h.state.fieldsError.value); assert.ok(h.state.error.value); assert.equal(h.state.ready.value, false);
  const retry = h.nodes().find(node => node.type?.name === 'el-button' && node.children?.default?.().some(child => String(child.children).includes('重新读取字段')));
  fail = false; await retry.props.onClick(); await settle(); await settle();
  assert.equal(h.state.fieldsError.value, ''); assert.equal(h.state.error.value, ''); assert.equal(h.state.ready.value, true);
  assert.equal(h.requests.filter(r => r.url.includes('custom_chart')).length, 1);
});
test('chart size changes keep line options but rebuild width-dependent matrices', async t => {
  const observers = [];
  class RecordingResizeObserver { constructor(callback) { this.callback = callback; observers.push(this); } observe() {} disconnect() {} }
  const h = harness(t, undefined, { globals: { ResizeObserver: RecordingResizeObserver } }); await h.mount();
  const resizeChart = async () => { observers.at(-1).callback([]); await new Promise(resolve => setTimeout(resolve, 120)); };
  const chart = h.charts[0]; chart.resizeCount = 0; chart.resize = function () { this.resizeCount += 1; };
  assert.equal(chart.options.at(-1).series[0].type, 'line'); const lineOptions = chart.options.length;
  await resizeChart(); assert.equal(chart.options.length, lineOptions); assert.equal(chart.resizeCount, 1);
  h.state.form.metrics = ['replacement_count']; h.state.form.chart_type = 'matrix'; await settle();
  const matrixOptions = chart.options.length; chart.width = 320;
  await resizeChart(); assert.equal(chart.options.length, matrixOptions + 1); assert.ok(chart.options.at(-1).grid.left <= 100);
});
test('configuration stays disabled until field choices load', async t => {
  const fieldsPending = deferred();
  const h = harness(t, async c => ({ data: c.url.includes('custom_fields') ? await fieldsPending.promise : result(c.params) }));
  const pending = h.mount(); await settle();
  assert.equal(h.nodes().find(node => node.type?.name === 'el-form').props.disabled, true);
  fieldsPending.resolve(fields); await pending;
  assert.equal(h.nodes().find(node => node.type?.name === 'el-form').props.disabled, false);
});

const fs = require('node:fs');
const path = require('node:path');
const { compile, root, echartsStub } = require('./helpers.cjs');
function loadChartOptionsModule(file) {
  return compile(fs.readFileSync(file, 'utf8'), name => name === 'echarts' ? echartsStub : loadChartOptionsModule(path.resolve(path.dirname(file), `${name}.ts`)));
}
const { buildLineChartOption, buildMatrixChartOption } = loadChartOptionsModule(path.resolve(root, 'utils/customChartOptions.ts'));

test('option builders preserve line gaps and matrix null versus zero', () => {
  const line = result({ chart_type: 'line', x_field: 'ring_no' });
  line.series[0].data = [0, null];
  assert.equal(buildLineChartOption(line).series[0].type, 'line');
  assert.deepEqual(plain(buildLineChartOption(line).series[0].data), [0, null]);
  line.x_field.value = 'manufacturer';
  assert.equal(buildLineChartOption(line).series[0].type, 'bar');

  const matrix = result({ chart_type: 'matrix', x_field: 'ring_no' });
  matrix.series[0].data = [[0, 0, 0], [1, 0, null], [2, 0, 5]];
  matrix.series.push({ metric: 'total_cost', name: '登记费用', unit: '元', data: [[0, 0, 0], [2, 0, null]] });
  const option = buildMatrixChartOption(matrix, { width: 900, height: '380px' });
  assert.deepEqual(plain(option.series[0].data.map(item => item.value)), [[0, 0, 0, 0], [2, 0, 5, null]]);
  assert.equal(option.series[0].symbolSize([0, 0, 0, 0]), 5);
  assert.equal(option.series[0].data[1].itemStyle.color, '#9a978e');
});

test('matrix option tooltip escapes categories, dimensions, metrics and units', () => {
  const data = result({ chart_type: 'matrix', x_field: 'ring_no' });
  data.x_categories = ['<img>'];
  data.y_categories = ['滚刀&刮刀'];
  data.x_field.label = 'X<轴>';
  data.y_field.label = 'Y"轴';
  data.series[0].name = '更换<数>';
  data.series[0].unit = '把&';
  data.series.push({ metric: 'total_cost', name: '费用\'额', unit: '<元>', data: [[0, 0, null]] });
  const option = buildMatrixChartOption(data, { width: 900, height: '380px' });
  assert.equal(option.tooltip.formatter({ value: [0, 0, 0, null] }),
    '<b>X&lt;轴&gt;：&lt;img&gt;</b><br/>Y&quot;轴：滚刀&amp;刮刀<br/>更换&lt;数&gt;：0 把&amp;<br/>费用&#39;额：- &lt;元&gt;');
});

test('matrix option narrows grid left to the existing width limit', () => {
  const data = result({ chart_type: 'matrix', x_field: 'ring_no' });
  data.y_categories = ['这是一个超过十四个字符的刀具类型名称'];
  assert.equal(buildMatrixChartOption(data, { width: 900, height: '380px' }).grid.left, 180);
  assert.equal(buildMatrixChartOption(data, { width: 320, height: '380px' }).grid.left, 100);
});

const { descendants, textOf } = require('./helpers.cjs');
test('config sits on one row with labels inside the controls; the aggregate line keeps its basis in an info tip', async t => {
  const h = harness(t); await h.mount();
  const nodes = () => h.nodes();
  const page = nodes();
  const order = ['ScopeSummary', 'el-card'].map(name => page.findIndex(node => node.type?.name === name));
  assert.ok(order[0] >= 0 && order[0] < order[1], 'the scope line comes right under the filters');
  const actions = page.find(node => node.type?.name === 'AnalysisActions');
  assert.equal(actions.props.refresh, undefined);
  assert.deepEqual(plain(actions.props.exports.map(item => [item.label, item.disabled])), [['导出 PDF', false]]);
  const form = () => nodes().find(node => node.type?.name === 'el-form');
  assert.equal(form().props['label-position'], undefined);
  assert.equal(descendants(form()).some(node => node.type?.name === 'el-form-item'), false);
  const selects = () => descendants(form()).filter(node => node.type?.name === 'el-select').map(node => [node.props['aria-label'], textOf(descendants(node).find(item => item.props?.class === 'config-label'))]);
  assert.deepEqual(selects(), [['X轴', 'X轴'], ['指标', '指标']]);
  assert.equal(textOf(descendants(form()).find(node => node.props?.class === 'config-label')), '图表类型');
  assert.ok(descendants(form()).some(node => node.type?.name === 'el-radio-group'));
  assert.ok(descendants(form()).some(node => node.type?.name === 'el-button' && textOf(node) === '生成图表'));
  h.state.form.chart_type = 'matrix';
  assert.deepEqual(selects().map(([label]) => label), ['X轴', 'Y轴', '指标']);
  h.state.form.chart_type = 'line'; await settle();

  const line = nodes().find(node => node.props?.class === 'aggregate-line');
  assert.equal(textOf(line), '本次聚合 1 条记录，展示 1 个分组');
  assert.equal(descendants(line).find(node => node.type?.name === 'InfoTip').props.content, '未记录与零值分别显示；地层分组可能重叠，不能直接加总。');
});
test('an invalid configuration warns in the warning style and keeps its alert role', async t => {
  const h = harness(t); await h.mount();
  h.state.form.x_field = 'manufacturer'; await settle();
  const warning = h.nodes().find(node => node.props?.role === 'alert' && node.props.class === 'config-warning');
  assert.match(textOf(warning), /厂家磨损请在成本分析的厂家表现中查看/);
});
