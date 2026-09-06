// Isolated real-component preview. Run from web: node src/views/shield/toolChangeDetail/__tests__/acceptance-preview.cjs
// Binds ONLY 127.0.0.1:5189. All API reads use synthetic fixtures; every write is rejected.
// Does not load Vite config, credentials, real APIs or business data. Ctrl+C stops the server.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const esbuild = require('esbuild');
const { parse, compileScript, compileStyle } = require('@vue/compiler-sfc');
const webRoot = path.resolve(__dirname, '../../../../..');
const fixtureService = `
import {reactive} from 'vue';
export const fixtureState=reactive({failure:new URLSearchParams(location.search).get('failure')||'',pending:false,reads:0});
let finish;
export const release=()=>{const fn=finish;finish=null;fn?.();};
const positions = ['1','2','17','19','21','80A','80B','S1L'];
const statuses = [null,null,'PENDING_VENDOR_FEEDBACK','CONFIRMED','CLOSED',null,null,null];
const photo = '/fixture-photo.svg';
const rows = positions.map((position,i) => ({
  id:i+1, cutter_position_no:position, tool_number:i===1?'':'TEST-'+position,
  is_checked:i>0, is_replaced:i>1, wear_condition:i>1?'偏磨':'', blade_wear_amount: i===2?0:2.1,
  replacement_count:i>1?1:0, manufacturer:'测试厂家（虚构）', brand:'测试品牌', price:'0',
  replacement_type:'REPAIR', repair_parts:['刀圈','轴承'], trajectory:{display:'R1955 mm',source:'验收测试值'},
  new_tool_record_data:position==='S1L'?{scraper_manufacturer:'测试厂家'}:{ring_type_display:'光面',ring_manufacturer:'测试厂家',shaft_condition_display:'全新',shaft_manufacturer:'测试厂家',hub_condition_display:'维修',hub_manufacturer:'测试厂家'},
  old_tool_record_data:statuses[i]?{inspection_status:statuses[i],old_tool_number:'OLD-'+position,disposition:'REPAIRABLE',remark:'虚构旧刀说明',photos:[]} : null,
  wear_image_url:i===2?photo:'', old_photo_links:i===2?[{id:1,name:'测试照片-长文件名称-用于检查换行.svg',url:photo}]:[],
  remark:i===2?'测试备注：这是虚构数据，不关联任何真实项目。\\n第二行验证换行。':'',
}));
export async function request(config) {
  if (config.method?.toLowerCase()!=='get') throw new Error('隔离验收禁止业务写入');
  const url=config.url;
  fixtureState.reads++;
  if(fixtureState.failure==='opening'&&url.includes('warehouse_opening')) throw new Error('Synthetic opening read failure');
  if(fixtureState.failure==='detail'&&url==='/api/shield/tool_change_detail/') throw new Error('Synthetic detail read failure');
  if(fixtureState.failure==='pending'&&url==='/api/shield/tool_change_detail/'){
    fixtureState.pending=true;await new Promise(resolve=>{finish=resolve;});fixtureState.pending=false;
  }
  if (url.startsWith('/api/shield/warehouse_opening/')) return {data:{id:1,ring_no:'100',warehouse_id:'TEST-OPENING',project_name:'隔离验收项目（虚构）',shield_model:1,section:'测试区间',shield_model_name:'测试机型',open_time:'2026-01-01 08:00',tool_change_date:'2026-01-01',opening_duration:6,tool_change_duration:3,checked_tool_count:7,replaced_tool_count:6,usage_distance:40,last_ring_no:'80',rings_between_openings:20,supplement_ready:!location.hash.includes('ready=0')}};
  if (url==='/api/shield/cutter_position_info/') return {data:positions.map((p,i)=>({id:i+1,cutter_position_no:p,tool_type:p==='S1L'?'SCRAPER':'DISC',tool_type_name:p==='S1L'?'常压刮刀':'19寸双联常压正滚刀180（转角）'}))};
  if (url==='/api/shield/tool_change_detail/') return {data:rows};
  if (url.endsWith('/field_options/')) return {data:{ring_damage:[{label:'崩口',value:'CHIPPED'}],bearing_failure_reasons:[],hub_failure_reasons:[],old_tool_dispositions:[{label:'可维修',value:'REPAIRABLE'}]}};
  const match=url.match(/tool_change_detail\\/(\\d+)\\/old_tool_record/);
  if (match) return {data:{old_tool_record_data:rows[Number(match[1])-1].old_tool_record_data}};
  throw new Error('Unexpected fixture request: '+url);
}`;

async function main() {
  const styles = [fs.readFileSync(require.resolve('element-plus/dist/index.css'), 'utf8')];
  const result = await esbuild.build({
    absWorkingDir: webRoot, bundle: true, write: false, format: 'iife', platform: 'browser',
    define: { 'process.env.NODE_ENV': '"development"', __VUE_OPTIONS_API__: 'true', __VUE_PROD_DEVTOOLS__: 'false' },
    stdin: { contents: `
      import {createApp,h,KeepAlive} from 'vue';
      import ElementPlus from 'element-plus';
      import {createRouter,createWebHashHistory,RouterView} from 'vue-router';
      import Detail from './src/views/shield/toolChangeDetail/index.vue';
      import {fixtureState,release} from '/@/utils/service';
      const router=createRouter({history:createWebHashHistory(),routes:[{path:'/detail',component:Detail},{path:'/other',component:{render:()=>h('p','其他页面（模拟）')}}]});
      if (!location.hash) location.hash='/detail?warehouse_id=1&mode=view';
      const button=(text,click)=>h('button',{onClick:click},text);
      const app=createApp({render:()=>h('div',[
        h('nav',{class:'fixture-controls'},[
          button('请求正常',()=>fixtureState.failure=''),button('开仓读取失败',()=>fixtureState.failure='opening'),
          button('明细读取失败',()=>fixtureState.failure='detail'),button('挂起明细',()=>fixtureState.failure='pending'),
          button('释放明细',release),button('离开明细',()=>router.push('/other')),
          button('返回明细',()=>router.push('/detail?warehouse_id=1&mode=view')),
        ]),h('p',{class:'fixture-status'},'模拟读取：'+fixtureState.reads+'；挂起：'+fixtureState.pending+'；故障：'+(fixtureState.failure||'无')),
        h(RouterView,null,{default:({Component,route})=>h(KeepAlive,null,Component?h(Component,{key:route.fullPath}):null)}),
      ])});
      app.component('FsPage',{setup:(_, {slots})=>()=>h('main',{class:'fixture-page'},slots.default?.())});
      app.use(ElementPlus);app.use(router);router.isReady().then(()=>app.mount('#app'));
    `, resolveDir: webRoot, loader: 'ts' },
    plugins: [{ name: 'isolated-sfc', setup(build) {
      build.onResolve({ filter: /^\/@\// }, args => args.path === '/@/utils/service'
        ? { path: 'fixture-service', namespace: 'fixture' }
        : { path: path.join(webRoot, 'src', args.path.slice(3)) });
      build.onLoad({ filter: /.*/, namespace: 'fixture' }, () => ({ contents: fixtureService, loader: 'js', resolveDir: webRoot }));
      build.onLoad({ filter: /\.vue$/ }, args => {
        const { descriptor, errors } = parse(fs.readFileSync(args.path, 'utf8'), { filename: args.path });
        if (errors.length) throw errors[0];
        const id = 'data-v-' + crypto.createHash('sha256').update(args.path).digest('hex').slice(0, 8);
        const script = compileScript(descriptor, { id, inlineTemplate: true });
        for (const style of descriptor.styles) {
          const css = compileStyle({ source: style.content, filename: args.path, id, scoped: style.scoped });
          if (css.errors.length) throw css.errors[0];
          styles.push(css.code);
        }
        const component = script.content.replace('export default', 'const PreviewComponent =');
        return { contents: component + `\nPreviewComponent.__scopeId=${JSON.stringify(id)}; export default PreviewComponent;`, loader: 'ts', resolveDir: path.dirname(args.path) };
      });
    } }],
  });
  const html = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>换刀明细隔离验收</title><link rel="stylesheet" href="/preview.css"><body><aside>隔离验收 · 虚构数据 · 所有写入已阻断</aside><div id="app"></div><script src="/preview.js"></script></body></html>';
  const css = styles.join('\n') + '\nbody{margin:0;background:#f5f7fa;font-family:Arial,"Microsoft YaHei",sans-serif}aside{padding:8px 20px;background:#fff7e6;color:#7a4d00;font-size:13px}.fixture-page{padding:16px;box-sizing:border-box}.fixture-controls{display:flex;flex-wrap:wrap;gap:8px;padding:8px 16px}.fixture-status{padding:0 16px}';
  const assets = new Map([
    ['/', ['text/html; charset=utf-8', html]],
    ['/favicon.ico', ['image/x-icon', Buffer.alloc(0)]],
    ['/preview.css', ['text/css; charset=utf-8', css]],
    ['/preview.js', ['text/javascript; charset=utf-8', result.outputFiles[0].contents]],
    ['/fixture-photo.svg', ['image/svg+xml', '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200"><rect width="320" height="200" fill="#e8eef5"/><text x="50" y="105" font-size="22">Synthetic test image</text></svg>']],
  ]);
  const server = http.createServer((req, res) => {
    const asset = assets.get(new URL(req.url, 'http://127.0.0.1:5189').pathname);
    if (req.method !== 'GET' || !asset) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'Content-Type': asset[0], 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'none'; object-src 'none'; base-uri 'none'" });
    res.end(asset[1]);
  });
  server.on('error', error => { console.error(error.message); process.exitCode = 1; });
  server.listen(5189, '127.0.0.1', () => console.log('Isolated detail acceptance: http://127.0.0.1:5189/#/detail?warehouse_id=1&mode=view'));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
