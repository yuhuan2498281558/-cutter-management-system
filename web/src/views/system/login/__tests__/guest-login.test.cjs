// Run from web: node --test src/views/system/login/__tests__/guest-login.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { parse, compileScript } = require('@vue/compiler-sfc');
const ts = require('typescript');
const vue = require('vue');

const componentPath = path.resolve(__dirname, '../component/account.vue');
const apiPath = path.resolve(__dirname, '../api.ts');
const source = fs.readFileSync(componentPath, 'utf8');
const apiSource = fs.readFileSync(apiPath, 'utf8');
const { descriptor } = parse(source);
const script = compileScript(descriptor, { id: 'guest-login-test' });

function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

function setup(t, overrides = {}) {
  const calls = [];
  const notices = [];
  const mounted = [];
  const themeStore = vue.reactive({ themeConfig: { isRequestRoutes: true } });
  const systemConfigStore = vue.reactive({
    systemConfig: { 'base.captcha_state': true },
    getSystemConfigs() { calls.push(['settings']); },
  });
  const guestResult = overrides.guestResult || Promise.resolve({
    code: 2000,
    data: { access: 'guest-access-token', name: '游客' },
  });
  const context = {
    exports: {},
    setTimeout,
    localStorage: {
      getItem: () => '',
      setItem: (...args) => calls.push(['remember-set', ...args]),
      removeItem: (...args) => calls.push(['remember-remove', ...args]),
    },
    require: name => {
      if (name === 'vue') return { ...vue, onMounted: fn => mounted.push(fn) };
      if (name === 'vue-router') return {
        useRoute: () => ({ query: {} }),
        useRouter: () => ({ push: target => { calls.push(['route', target]); return Promise.resolve(); } }),
      };
      if (name === 'element-plus') return { ElMessage: { success: message => notices.push(message) } };
      if (name === 'vue-i18n') return { useI18n: () => ({ t: () => '登录成功' }) };
      if (name === 'js-cookie') return { set: (...args) => calls.push(['cookie', ...args]) };
      if (name === 'pinia') return { storeToRefs: vue.toRefs };
      if (name === '/@/stores/themeConfig') return { useThemeConfig: () => themeStore };
      if (name === '/@/router/frontEnd') return { initFrontEndControlRoutes: () => calls.push(['front-routes']) };
      if (name === '/@/utils/storage') return {
        Session: {
          set: (...args) => calls.push(['session', ...args]),
          remove: (...args) => calls.push(['session-remove', ...args]),
        },
      };
      if (name === '/@/utils/formatTime') return { formatAxis: () => '下午好' };
      if (name === '/@/utils/loading') return { NextLoading: { start: () => calls.push(['loading-start']) } };
      if (name === '/@/views/system/login/api') return {
        getCaptcha: () => Promise.resolve({ data: { image_base: 'captcha', key: 'key' } }),
        guestLogin: () => { calls.push(['guest-api']); return guestResult; },
        login: () => { calls.push(['account-api']); return Promise.resolve(); },
      };
      if (name === '/@/stores/userInfo') return { useUserInfo: () => ({ setUserInfos: () => calls.push(['user-info']) }) };
      if (name === '/@/stores/dictionary') return { DictionaryStore: () => ({ getSystemDictionarys: () => calls.push(['dictionary']) }) };
      if (name === '/@/stores/systemConfig') return { SystemConfigStore: () => systemConfigStore };
      if (name === 'ts-md5') return { Md5: { hashStr: value => value } };
      if (name === '/@/utils/message') return { errorMessage: message => notices.push(message) };
      throw new Error(`Unexpected import: ${name}`);
    },
  };
  const compiled = ts.transpileModule(script.content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true },
  }).outputText;
  vm.runInNewContext(compiled, context);
  const scope = vue.effectScope();
  const state = scope.run(() => context.exports.default.setup());
  t.after(() => scope.stop());
  return { state, calls, notices, mounted };
}

test('template exposes a clearly read-only guest entry without embedded credentials', () => {
  assert.match(descriptor.template.content, /游客登录/);
  assert.match(descriptor.template.content, /仅查看/);
  assert.match(descriptor.template.content, /无需账号和验证码/);
  assert.match(apiSource, /url:\s*['"]\/api\/guest-login\/['"]/);
  assert.doesNotMatch(source + apiSource, /guest.*password|password.*guest/i);
});

test('guest login reuses token, cookie, route and success handling without captcha', async t => {
  const { state, calls, notices } = setup(t);
  await state.guestLoginClick();
  assert.deepEqual(calls.filter(call => call[0] === 'guest-api').length, 1);
  assert.deepEqual(calls.filter(call => call[0] === 'account-api').length, 0);
  assert.deepEqual(calls.filter(call => call[0] === 'session-remove')[0], ['session-remove', 'mobileAccessVerified']);
  assert.deepEqual(calls.filter(call => call[0] === 'session')[0], ['session', 'token', 'guest-access-token']);
  assert.deepEqual(calls.filter(call => call[0] === 'cookie')[0], ['cookie', 'username', '游客']);
  assert.deepEqual(calls.filter(call => call[0] === 'route')[0], ['route', '/']);
  assert.equal(state.state.loading.guest, false);
  assert.equal(notices.length, 1);
});

test('repeated guest clicks are locked while the first request is pending', async t => {
  const wait = deferred();
  const { state, calls } = setup(t, { guestResult: wait.promise });
  const first = state.guestLoginClick();
  const second = state.guestLoginClick();
  assert.equal(calls.filter(call => call[0] === 'guest-api').length, 1);
  wait.resolve({ code: 2000, data: { access: 'token', name: '游客' } });
  await Promise.all([first, second]);
});

test('guest failure releases only the guest loading lock', async t => {
  const { state, calls } = setup(t, { guestResult: Promise.reject(new Error('offline')) });
  await assert.rejects(state.guestLoginClick(), /offline/);
  assert.equal(state.state.loading.guest, false);
  assert.equal(state.state.loading.signIn, false);
  assert.equal(calls.filter(call => call[0] === 'account-api').length, 0);
});
