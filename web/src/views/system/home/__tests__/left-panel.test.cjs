const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');
const { parse, compileScript } = require('@vue/compiler-sfc');
const { renderToString } = require('@vue/server-renderer');

const filename = path.join(__dirname, '../LeftPanel.vue');
const { descriptor } = parse(fs.readFileSync(filename, 'utf8'), { filename });
const settle = () => new Promise(resolve => setImmediate(resolve));

// responders: { project, machine, openings, warnings }，每项返回响应或抛错。
function harness(responders) {
  const bindings = Object.keys(compileScript(descriptor, { id: 'left-panel-test' }).bindings);
  const script = descriptor.scriptSetup.content.replace(/^import .*$/gm, '');
  const requests = [];
  let mount;
  const context = {
    ...vue,
    console: { error() {} },
    onMounted: fn => { mount = fn; },
    useRouter: () => ({ push() {} }),
    request: async ({ url, params }) => {
      const key = url.includes('home_warnings') ? 'warnings'
        : url.includes('warehouse_opening') ? 'openings'
          : url.includes('shield_machine') ? 'machine' : 'project';
      requests.push({ key, params });
      return responders[key](params);
    },
  };
  vm.createContext(context);
  vm.runInContext(ts.transpileModule(script, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText
    + `\nglobalThis.api={${bindings.filter(name => name !== 'ProjectRouteMap').join(',')}};`, context);
  const api = context.api;
  return {
    api, requests,
    mount: async () => { mount(); await settle(); await settle(); },
    async text() {
      const app = vue.createSSRApp({ template: descriptor.template.content, setup: () => api });
      app.component('ProjectRouteMap', { render: () => null });
      const html = await renderToString(app);
      return html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    },
    // 按模板里刷新按钮实际绑定的处理函数点一次。
    clickRefresh() {
      const match = descriptor.template.content.match(/class="refresh-btn" @click="(\w+)"/);
      assert.ok(match, 'refresh button binds a handler');
      return api[match[1]]();
    },
  };
}

const ok = data => () => ({ code: 2000, data });
const fail = () => { throw new Error('network unavailable'); };
const project = { project_name: '福州滨海快线', location: '福州', excavation_diameter: 6.8, tunnel_length: 5600 };
const responders = (overrides = {}) => ({
  project: ok([project]),
  machine: ok([{ shield_model: 'ZTE6880' }]),
  openings: ok([]),
  warnings: ok({ warnings: [{ position: '12', type: 'DISC', lastRing: 90, ringsSince: 397 }] }),
  ...overrides,
});

test('recent openings are requested by numeric ring order and re-sorted as a fallback', async () => {
  const h = harness(responders({
    openings: ok([
      { id: 3, ring_no: '67', open_time: '2026-03-01T08:00:00' },
      { id: 5, ring_no: '487', open_time: '2026-05-01T08:00:00' },
      { id: 4, ring_no: '443', open_time: '2026-04-01T08:00:00' },
    ]),
  }));
  await h.mount();
  const opening = h.requests.find(r => r.key === 'openings');
  assert.deepEqual({ ...opening.params }, { limit: 5, ordering: '-ring_int,-open_time' });
  assert.deepEqual([...h.api.recentChanges.value].map(item => item.ring_no), ['487', '443', '67']);
  assert.equal(h.api.latestRingNo.value, '487');
});

test('project request failure asks the user to refresh instead of loading forever', async () => {
  const h = harness(responders({ project: fail }));
  await h.mount();
  const text = await h.text();
  assert.ok(text.includes('加载失败，请点刷新重试'), text);
  assert.ok(!text.includes('加载中...'), text);
});

test('an empty project list shows that there is no project', async () => {
  const h = harness(responders({ project: ok([]) }));
  await h.mount();
  const text = await h.text();
  assert.ok(text.includes('暂无项目信息'), text);
  assert.ok(!text.includes('加载中...'), text);
});

test('a loaded project shows its details', async () => {
  const h = harness(responders());
  await h.mount();
  const text = await h.text();
  assert.ok(text.includes('福州滨海快线'), text);
  assert.ok(text.includes('ZTE6880'), text);
  assert.ok(!text.includes('加载失败'), text);
});

test('opening request failure keeps project details and is not shown as having no records', async () => {
  const h = harness(responders({ openings: fail }));
  await h.mount();
  const text = await h.text();
  assert.ok(text.includes('福州滨海快线'), text);
  assert.ok(text.includes('换刀记录加载失败'), text);
  assert.ok(!text.includes('暂无换刀记录'), text);
});

test('warning request failure is not shown as having no warnings', async () => {
  const h = harness(responders({ warnings: fail }));
  await h.mount();
  const text = await h.text();
  assert.ok(text.includes('预警加载失败'), text);
  assert.ok(!text.includes('暂无预警'), text);
});

test('an empty warning response still shows no warnings', async () => {
  const h = harness(responders({ warnings: ok({ warnings: [] }) }));
  await h.mount();
  const text = await h.text();
  assert.ok(text.includes('暂无预警'), text);
  assert.ok(!text.includes('预警加载失败'), text);
});

test('the refresh button reloads both the project data and the warnings', async () => {
  let warningsFail = true;
  const h = harness(responders({
    warnings: params => (warningsFail ? fail() : ok({ warnings: [] })(params)),
  }));
  await h.mount();
  assert.ok((await h.text()).includes('预警加载失败'));
  warningsFail = false;
  await h.clickRefresh();
  await settle(); await settle();
  const count = key => h.requests.filter(r => r.key === key).length;
  assert.equal(count('project'), 2);
  assert.equal(count('openings'), 2);
  assert.equal(count('warnings'), 2);
  const text = await h.text();
  assert.ok(text.includes('暂无预警'), text);
  assert.ok(!text.includes('预警加载失败'), text);
});
