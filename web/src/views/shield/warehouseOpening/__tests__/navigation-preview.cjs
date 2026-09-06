// node src/views/shield/warehouseOpening/__tests__/navigation-preview.cjs (from web)
// Real parent/dialog/Router/Element Plus. Synthetic CRUD, API and destination only.
// Memory-only, no business configuration or database; binds 127.0.0.1:5197.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const esbuild = require('esbuild');
const { parse, compileScript, compileStyle } = require('@vue/compiler-sfc');
const webRoot = path.resolve(__dirname, '../../../../..');
const parentFile = path.resolve(__dirname, '../index.vue');
const dialogFile = path.resolve(__dirname, '../OpeningCompletionDialog.vue');
const fixture = `
import {reactive,h} from 'vue';
export const fixture=reactive({mode:'success',refreshes:0,writes:0,pending:0,blockRoute:false});
export const rows=reactive([1,2].map(id=>({id,warehouse_id:'TEST-'+id,summary_status:'DRAFT',supplement_ready:false,opening_duration:4,tool_change_duration:2,checked_tool_count:10,replaced_tool_count:3,usage_distance:40})));
let options,finish;
export const settle=success=>{const fn=finish;finish=null;if(fn)fn(success);};
export async function CompleteSummary(id,payload){
  fixture.writes++;
  return {data:{...rows.find(row=>row.id===id),...payload,summary_status:'CONFIRMED',supplement_ready:true},msg:'模拟汇总已确认（未写业务库）'};
}
export const request=async()=>({data:[]});
export const createCrudOptions=opts=>{options=opts;return {crudOptions:{}};};
export const useCrud=()=>({resetCrudOptions(){}});
export const useExpose=()=>({crudExpose:{async doRefresh(){
  fixture.refreshes++;
  const mode=fixture.mode;
  if(mode==='pending'){
    fixture.pending++;
    const ok=await new Promise(resolve=>{finish=resolve;});
    fixture.pending--;
    if(!ok)throw new Error('Synthetic refresh failure');
  }else if(mode==='failure')throw new Error('Synthetic refresh failure');
}}});
export const Crud={setup(){return()=>h('section',rows.map(row=>h('p',[
  h('span',row.warehouse_id+' · '+row.summary_status+' '),
  h('button',{onClick:()=>options.onSupplement(row)},'确认 '+row.warehouse_id),
])));}};
`;
async function main() {
  const styles = [fs.readFileSync(require.resolve('element-plus/dist/index.css'), 'utf8')];
  const result = await esbuild.build({
    absWorkingDir: webRoot, bundle: true, write: false, format: 'iife', platform: 'browser',
    define: { 'process.env.NODE_ENV': '"development"', __VUE_OPTIONS_API__: 'true', __VUE_PROD_DEVTOOLS__: 'false' },
    stdin: { resolveDir: webRoot, loader: 'ts', contents: `
      import {createApp,h,KeepAlive} from 'vue';
      import {createRouter,createMemoryHistory,RouterView} from 'vue-router';
      import ElementPlus from 'element-plus';
      import Parent from './src/views/shield/warehouseOpening/index.vue';
      import {fixture,settle,Crud} from 'navigation-fixture';
      const router=createRouter({history:createMemoryHistory(),routes:[
        {path:'/',component:Parent},
        {path:'/other',component:{render:()=>h('h3','其他页面（模拟）')}},
        {path:'/shield/toolChangeDetail',component:{render:()=>h('h3','补录目标页（模拟；参数见上方）')}},
      ]});
      router.beforeEach(to=>!(fixture.blockRoute&&to.path==='/shield/toolChangeDetail'));
      const button=(text,fn)=>h('button',{onClick:fn},text);
      createApp({setup(){return()=>h('main',[
        h('h2','汇总跳转隔离验收 · 虚构数据 · 不写业务库'),
        h('div',{class:'controls'},[
          button('刷新成功',()=>fixture.mode='success'),button('刷新失败',()=>fixture.mode='failure'),
          button('刷新等待',()=>fixture.mode='pending'),button('释放成功',()=>settle(true)),button('释放失败',()=>settle(false)),
          button('离开列表',()=>router.push('/other')),button('返回列表',()=>router.push('/')),
          button('阻止跳转',()=>fixture.blockRoute=true),button('允许跳转',()=>fixture.blockRoute=false),
        ]),
        h('p',{id:'fixture-status'},'模拟确认数：'+fixture.writes+'；列表刷新数：'+fixture.refreshes+'；待刷新：'+fixture.pending+'；刷新模式：'+fixture.mode),
        h('p',{id:'route-status'},'当前路由：'+router.currentRoute.value.fullPath),
        h(RouterView,null,{default:({Component})=>h(KeepAlive,null,Component?h(Component):null)}),
      ]);}}).component('fs-page',{render(){return h('div',this.$slots.default?.());}})
        .component('fs-crud',Crud).use(ElementPlus).use(router).mount('#app');
    ` },
    plugins: [{ name: 'isolated-navigation', setup(build) {
      build.onResolve({ filter: /^navigation-fixture$|^@fast-crud\/fast-crud$|^\.\/api$|^\.\/crud$|^\/@\/utils\/service$/ }, () => ({ path: 'navigation-fixture', namespace: 'fixture' }));
      build.onLoad({ filter: /.*/, namespace: 'fixture' }, () => ({ contents: fixture, loader: 'js', resolveDir: webRoot }));
      build.onResolve({ filter: /^\/@\/views\/shield\/components\/ExportDropdown\.vue$/ }, () => ({ path: 'empty-export', namespace: 'empty' }));
      build.onLoad({ filter: /.*/, namespace: 'empty' }, () => ({ contents: 'export default {render(){return null;}}', loader: 'js' }));
      build.onLoad({ filter: /\.vue$/ }, args => {
        if (![parentFile, dialogFile].includes(args.path)) throw new Error('Unexpected component: ' + args.path);
        const { descriptor, errors } = parse(fs.readFileSync(args.path, 'utf8'), { filename: args.path });
        if (errors.length) throw errors[0];
        const id = args.path === parentFile ? 'data-v-navigation-parent' : 'data-v-navigation-dialog';
        const script = compileScript(descriptor, { id, inlineTemplate: true });
        for (const style of descriptor.styles) {
          const css = compileStyle({ source: style.content, filename: args.path, id, scoped: style.scoped });
          if (css.errors.length) throw css.errors[0];
          styles.push(css.code);
        }
        return { contents: script.content.replace('export default', 'const PreviewComponent =') + '\nPreviewComponent.__scopeId="' + id + '";export default PreviewComponent;', loader: 'ts', resolveDir: path.dirname(args.path) };
      });
    } }],
  });
  const assets = new Map([
    ['/', ['text/html; charset=utf-8', '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>汇总跳转隔离验收</title><link rel="stylesheet" href="/preview.css"><body><div id="app"></div><script src="/preview.js"></script></body></html>']],
    ['/favicon.ico', ['image/x-icon', Buffer.alloc(0)]],
    ['/preview.js', ['text/javascript; charset=utf-8', result.outputFiles[0].contents]],
    ['/preview.css', ['text/css; charset=utf-8', styles.join('\n') + '\nbody{margin:0;font-family:Arial,"Microsoft YaHei",sans-serif;background:#f5f7fa}main{padding:20px}.controls{display:flex;flex-wrap:wrap;gap:8px;position:relative;z-index:4000}button{padding:6px 10px}']],
  ]);
  const server = http.createServer((req, res) => {
    const asset = assets.get(req.url);
    if (req.method !== 'GET' || !asset) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'Content-Type': asset[0], 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'self';script-src 'self';style-src 'self' 'unsafe-inline';connect-src 'none';object-src 'none';base-uri 'none'" });
    res.end(asset[1]);
  });
  server.on('error', error => { console.error(error.message); process.exitCode = 1; });
  server.listen(5197, '127.0.0.1', () => console.log('Navigation fixture: http://127.0.0.1:5197/'));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
