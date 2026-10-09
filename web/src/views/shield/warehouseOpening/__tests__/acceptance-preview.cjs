// Run from web with Node; binds only 127.0.0.1:5193. Ctrl+C to stop.
// Real SFC + Element Plus, synthetic data and memory-only responses. No real API/config/DB access.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const esbuild = require('esbuild');
const { parse, compileScript, compileStyle } = require('@vue/compiler-sfc');
const webRoot = path.resolve(__dirname, '../../../../..');
const dialogFile = path.resolve(__dirname, '../OpeningCompletionDialog.vue');
const fixture = `
import {reactive} from 'vue';
export const fixture = reactive({mode:'pending',requests:0,saved:0,pending:false});
let finish;
export function settle(success) { if (finish) { finish(success); finish=null; } }
export async function CompleteSummary(id,payload) {
  fixture.requests++; fixture.pending=true;
  const mode=fixture.mode;
  const success = mode==='pending' ? await new Promise(resolve=>{finish=resolve;}) : mode==='success';
  fixture.pending=false;
  if (!success) throw new Error('Synthetic network failure');
  return {data:{id,warehouse_id:'TEST-'+id,...payload},msg:'模拟确认成功（未写业务库）'};
}`;
async function main() {
  const styles = [fs.readFileSync(require.resolve('element-plus/dist/index.css'), 'utf8')];
  const result = await esbuild.build({
    absWorkingDir: webRoot, bundle: true, write: false, format: 'iife', platform: 'browser',
    define: { 'process.env.NODE_ENV': '"development"', __VUE_OPTIONS_API__: 'true', __VUE_PROD_DEVTOOLS__: 'false' },
    stdin: { resolveDir: webRoot, loader: 'ts', contents: `
      import {createApp,h,ref} from 'vue';
      import ElementPlus from 'element-plus';
      import Dialog from './src/views/shield/warehouseOpening/OpeningCompletionDialog.vue';
      import {fixture,settle} from 'summary-fixture';
      const row=id=>({id,warehouse_id:'TEST-'+id,ring_no:487,opening_duration:4,tool_change_duration:2,checked_tool_count:10,replaced_tool_count:3,usage_distance:40});
      createApp({setup(){
        const visible=ref(true),opening=ref(row(1));
        const button=(label,fn)=>h('button',{onClick:fn},label);
        return ()=>h('main',[
          h('h2','开仓汇总隔离验收 · 虚构数据 · 不写业务库'),
          h('div',{class:'controls'},[
            button('打开 A',()=>{opening.value=row(1);visible.value=true;}),
            button('打开 B',()=>{opening.value=row(2);visible.value=true;}),
            button('缺失时长',()=>{opening.value={...row(3),opening_duration:null,tool_change_duration:null};visible.value=true;}),
            button('等待响应',()=>fixture.mode='pending'),button('立即失败',()=>fixture.mode='failure'),
            button('立即成功',()=>fixture.mode='success'),
            button('返回成功',()=>settle(true)),button('返回失败',()=>settle(false)),
          ]),
          h('p',{id:'fixture-status'},'请求数：'+fixture.requests+'；成功事件：'+fixture.saved+'；待响应：'+fixture.pending+'；模式：'+fixture.mode),
          h(Dialog,{modelValue:visible.value,opening:opening.value,'onUpdate:modelValue':v=>visible.value=v,onSaved:()=>fixture.saved++}),
        ]);
      }}).use(ElementPlus).mount('#app');
    ` },
    plugins: [{ name: 'isolated-summary', setup(build) {
      build.onResolve({ filter: /^summary-fixture$|^\.\/api$/ }, args => {
        if (args.path === 'summary-fixture' || args.importer === dialogFile) return { path:'summary-fixture',namespace:'fixture' };
      });
      build.onLoad({ filter: /.*/, namespace:'fixture' }, () => ({ contents:fixture, loader:'js', resolveDir:webRoot }));
      build.onLoad({ filter: /\.vue$/ }, args => {
        if (args.path !== dialogFile) throw new Error('Unexpected component: '+args.path);
        const {descriptor,errors}=parse(fs.readFileSync(args.path,'utf8'),{filename:args.path});
        if(errors.length) throw errors[0];
        const id='data-v-summary-preview';
        const script=compileScript(descriptor,{id,inlineTemplate:true});
        for(const style of descriptor.styles){
          const css=compileStyle({source:style.content,filename:args.path,id,scoped:style.scoped});
          if(css.errors.length) throw css.errors[0];
          styles.push(css.code);
        }
        return {contents:script.content.replace('export default','const PreviewComponent =')+'\nPreviewComponent.__scopeId="'+id+'";export default PreviewComponent;',loader:'ts',resolveDir:path.dirname(args.path)};
      });
    }}],
  });
  const assets=new Map([
    ['/', ['text/html; charset=utf-8','<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>汇总弹窗隔离验收</title><link rel="stylesheet" href="/preview.css"><body><div id="app"></div><script src="/preview.js"></script></body></html>']],
    ['/preview.js',['text/javascript; charset=utf-8',result.outputFiles[0].contents]],
    ['/preview.css',['text/css; charset=utf-8',styles.join('\n')+'\nbody{margin:0;font-family:Arial,"Microsoft YaHei",sans-serif;background:#f5f7fa}main{padding:20px}.controls{display:flex;gap:8px;position:fixed;bottom:0;left:0;right:0;overflow-x:auto;background:white;z-index:4000}.controls button{padding:6px 10px;flex-shrink:0}']],
  ]);
  const server=http.createServer((req,res)=>{
    const asset=assets.get(req.url);
    if(req.method!=='GET'||!asset){res.writeHead(404);res.end();return;}
    res.writeHead(200,{'Content-Type':asset[0],'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self';script-src 'self';style-src 'self' 'unsafe-inline';connect-src 'none';object-src 'none';base-uri 'none'"});
    res.end(asset[1]);
  });
  server.on('error',error=>{console.error(error.message);process.exitCode=1;});
  server.listen(5193,'127.0.0.1',()=>console.log('Summary fixture: http://127.0.0.1:5193/'));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
