const test = require('node:test');
const assert = require('node:assert/strict');
const { setup, settle, plain, deferred } = require('./helpers.cjs');
const meta = { schema_version: 2, generated_at: '2026-09-11T00:00:00Z', summary_status: 'CONFIRMED', scope: { project_name: 'P' } };
const fields = { dimensions: ['ring_no', 'manufacturer', 'tool_parent_type'].map(value => ({value, label:value, chart_types:['line','matrix']})), metrics: [{ value:'replacement_count',label:'更换数',unit:'把' }, {value:'total_cost',label:'登记费用',unit:'元'}] };
function result(params) { return { meta, chart_type: params.chart_type, x_field: {value:params.x_field,label:params.x_field}, y_field:{value:'tool_parent_type',label:'刀型'}, metrics:[{value:'replacement_count',label:'更换数',unit:'把'}], categories:['A'], x_categories:['<img>'], y_categories:['滚刀'], series:[{metric:'replacement_count',name:'更换数',unit:'把',data:params.chart_type === 'matrix' ? [[0,0,0],[1,0,null]] : [0]}], rows:[{x:'A',replacement_count:0}], record_count:1 }; }
function harness(t, request) { const h=setup(t,'pages/CustomAnalysis.vue',{request:request || (async c=>({data:c.url.includes('custom_fields')?fields:result(c.params)}))}); h.state.chartRef.value={}; return h; }
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
test('configuration stays disabled until field choices load', async t => {
  const fieldsPending = deferred();
  const h = harness(t, async c => ({ data: c.url.includes('custom_fields') ? await fieldsPending.promise : result(c.params) }));
  const pending = h.mount(); await settle();
  assert.equal(h.nodes().find(node => node.type?.name === 'el-form').props.disabled, true);
  fieldsPending.resolve(fields); await pending;
  assert.equal(h.nodes().find(node => node.type?.name === 'el-form').props.disabled, false);
});
