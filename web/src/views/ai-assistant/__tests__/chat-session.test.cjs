// Run from web: node --test src/views/ai-assistant/__tests__/chat-session.test.cjs
// Run the actual page setup with Vue reactivity; isolate API and animation frames.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const vue = require('vue');

function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
function setup() {
  const history = deferred(), reset = deferred(), streams = [], notices = [], frames = new Map();
  let mounted, unmounted, nextFrame = 0, clock = 0;
  const api = { history: () => history.promise, reset: () => reset.promise, chatStream: (data, callbacks, signal) => { streams.push({ data, callbacks, signal }); return Promise.resolve(); } };
  const context = { exports: {}, AbortController, window: { requestAnimationFrame(callback) { const id = ++nextFrame; frames.set(id, callback); return id; }, cancelAnimationFrame(id) { frames.delete(id); } } };
  context.require = name => {
    if (name === 'vue') return { ...vue, onMounted: callback => { mounted = callback; }, onUnmounted: callback => { unmounted = callback; } };
    if (name === 'element-plus') return { ElMessage: { success: value => notices.push(['success', value]), error: value => notices.push(['error', value]), info: value => notices.push(['info', value]) } };
    if (name === '/@/api/ai-assistant') return { useAiAssistantApi: () => api };
    if (name.endsWith('.vue') || name === '@element-plus/icons-vue') return {};
    throw new Error(`Unexpected import: ${name}`);
  };
  const source = fs.readFileSync(path.resolve(__dirname, '../index.vue'), 'utf8').match(/<script[^>]*>([\s\S]*?)<\/script>/)[1] + '\nexports.page = { loadHistory, sendQuery, handleRegenerate, handleReset, handleAbort, messages, memoryInfo, loading, resetting, historyLoading, hasMoreHistory, nextHistoryCursor, chatListRef };';
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText, context);
  return { ...context.exports.page, api, history, reset, streams, notices, frames, mount: () => mounted(), unmount: () => unmounted(), frame() { const callbacks = [...frames.values()]; frames.clear(); clock += 16; callbacks.forEach(callback => callback(clock)); } };
}
const historyResponse = { data: { messages: [{ role: 'user', content: '旧问题' }, { role: 'assistant', content: '旧回答' }], memory: { message_count: 2, slot_names: ['ring_range'] } } };

test('late initial history cannot overwrite a new question or mix old and new answers', async () => {
  const h = setup(), pending = h.mount(); h.sendQuery('新的问题');
  h.history.resolve(historyResponse); await pending;
  h.streams[0].callbacks.onChunk('新的回答'); h.streams[0].callbacks.onDone();
  assert.deepEqual(Array.from(h.messages.value, message => message.content), ['新的问题', '新的回答']);
  assert.equal(h.memoryInfo.value, undefined);
  assert.equal(h.loading.value, false);
});

test('reset blocks send/retry, discards old history/stream callbacks and releases loading', async () => {
  const h = setup(), history = h.mount(); h.sendQuery('问题'); const old = h.streams[0];
  const reset = h.handleReset(); h.sendQuery('重置中的问题'); h.handleRegenerate();
  assert.equal(h.streams.length, 1); assert.equal(old.signal.aborted, true);
  h.reset.resolve({ data: { message: '对话已重置' } }); await reset;
  old.callbacks.onChunk('过期内容'); old.callbacks.onMemory({ message_count: 8 }); old.callbacks.onDone(); old.callbacks.onError('过期错误');
  h.history.resolve(historyResponse); await history;
  assert.equal(h.messages.value.length, 0); assert.equal(h.memoryInfo.value, undefined);
  assert.equal(h.loading.value, false); assert.equal(h.resetting.value, false);
  h.sendQuery('重置后的问题'); assert.equal(h.streams.length, 2);
});

test('failed reset preserves messages and memory and shows no success notice', async () => {
  const h = setup(), initial = h.mount(); h.history.resolve(historyResponse); await initial;
  const reset = h.handleReset(); h.reset.reject(new Error('数据库异常')); await reset;
  assert.deepEqual(Array.from(h.messages.value, message => message.content), ['旧问题', '旧回答']);
  assert.equal(h.memoryInfo.value.message_count, 2);
  assert.deepEqual(h.notices, [['error', '重置失败：数据库异常']]);
  assert.equal(h.resetting.value, false);
});

test('first content is immediate, later frames grow it, and done waits for presentation queue', () => {
  const h = setup(); h.sendQuery('问题'); const callbacks = h.streams[0].callbacks;
  const answer = '工程管理数据'.repeat(60); callbacks.onChunk(answer); callbacks.onDone();
  const first = h.messages.value[1].content.length; assert.ok(first > 0 && first < answer.length); assert.equal(h.loading.value, true);
  h.frame(); const second = h.messages.value[1].content.length; h.frame(); const third = h.messages.value[1].content.length;
  assert.ok(first < second && second < third);
  for (let i = 0; i < 1000 && h.frames.size; i++) h.frame();
  assert.equal(h.messages.value[1].content, answer); assert.equal(h.loading.value, false); assert.equal(h.messages.value[1].streaming, false);
});

test('stop cancels visual queue; old terminal callbacks cannot unlock or modify next stream', () => {
  const h = setup(); h.sendQuery('问题1'); const old = h.streams[0]; old.callbacks.onChunk('第一条长回答'.repeat(50));
  h.handleAbort(); assert.equal(h.frames.size, 0); assert.equal(h.messages.value[1].aborted, true); assert.equal(h.messages.value[1].streaming, false);
  const stopped = h.messages.value[1].content; h.sendQuery('问题2');
  old.callbacks.onChunk('过期'); old.callbacks.onError('过期错误'); old.callbacks.onDone(); old.callbacks.onMemory({ message_count: 99 });
  assert.equal(h.loading.value, true); assert.equal(h.messages.value[1].content, stopped); assert.equal(h.memoryInfo.value, undefined);
  h.streams[1].callbacks.onChunk('新回答'); h.streams[1].callbacks.onDone(); assert.equal(h.messages.value[3].content, '新回答');
});

test('stream error preserves received text, exits loading and permits another question', () => {
  const h = setup(); h.sendQuery('问题'); const callbacks = h.streams[0].callbacks; callbacks.onChunk('已收到的长内容'.repeat(20)); callbacks.onError('连接提前结束');
  assert.equal(h.frames.size, 0); assert.equal(h.loading.value, false); assert.equal(h.messages.value[1].rawError, true);
  assert.match(h.messages.value[1].content, /已收到的长内容/); assert.match(h.messages.value[1].content, /连接提前结束/);
  h.sendQuery('再试'); assert.equal(h.streams.length, 2);
});

test('unmount invalidates delayed history/reset and cancels animation frames', async () => {
  const h = setup(), history = h.mount(); h.sendQuery('问题'); h.streams[0].callbacks.onChunk('长内容'.repeat(30));
  const reset = h.handleReset(); h.unmount(); h.reset.resolve({ data: {} }); h.history.resolve(historyResponse); await Promise.all([reset, history]);
  assert.equal(h.frames.size, 0); assert.equal(h.streams[0].signal.aborted, true); assert.equal(h.notices.length, 0);
  h.sendQuery('卸载后不得发送'); assert.equal(h.streams.length, 1);
});

test('authoritative answer replaces draft text, drains progressively, and matches refreshed history', async () => {
  const h = setup(); h.sendQuery('分析磨损'); const callbacks = h.streams[0].callbacks;
  callbacks.onChunk('正在查询临时工具信息'.repeat(10)); h.frame();
  const answer = '最终确认的工程结论。'.repeat(25);
  callbacks.onAnswer(answer); callbacks.onChunk('忽略迟到的临时文本'); callbacks.onDone();
  assert.ok(h.messages.value[1].content.length < answer.length);
  assert.equal(h.messages.value[1].content.includes('临时'), false);
  for (let i = 0; i < 1000 && h.frames.size; i++) h.frame();
  assert.equal(h.messages.value[1].content, answer); assert.equal(h.loading.value, false);
  const refreshed = setup(), restored = refreshed.mount();
  refreshed.history.resolve({ data: { messages: [{ role: 'user', content: '分析磨损', sequence: 1 }, { role: 'assistant', content: answer, sequence: 2 }] } }); await restored;
  assert.deepEqual(Array.from(refreshed.messages.value, message => message.content), Array.from(h.messages.value, message => message.content));
});

test('ask again appends a complete new turn, keeping the same history after refresh', async () => {
  const h = setup(); h.sendQuery('换刀情况'); h.streams[0].callbacks.onChunk('原回答'); h.streams[0].callbacks.onDone();
  h.handleRegenerate(); h.streams[1].callbacks.onChunk('新回答'); h.streams[1].callbacks.onDone();
  assert.deepEqual(Array.from(h.messages.value, message => message.content), ['换刀情况', '原回答', '换刀情况', '新回答']);
  assert.equal(new Set(h.messages.value.map(message => message.id)).size, 4);
  const restored = setup(), loaded = restored.mount();
  restored.history.resolve({ data: { messages: h.messages.value.map((message, index) => ({ role: message.role, content: message.content, sequence: index + 1 })) } }); await loaded;
  assert.deepEqual(Array.from(restored.messages.value, message => message.content), Array.from(h.messages.value, message => message.content));
});

test('final answer retains its common visible prefix while replacing the divergent suffix', () => {
  const h = setup(); h.sendQuery('问题'); const callbacks = h.streams[0].callbacks;
  callbacks.onChunk('相同前缀但这是临时结论');
  callbacks.onAnswer('相同前缀最终依据完整');
  assert.equal(h.messages.value[1].content, '相同前缀');
  callbacks.onDone();
  for (let i = 0; i < 100 && h.frames.size; i++) h.frame();
  assert.equal(h.messages.value[1].content, '相同前缀最终依据完整'); assert.equal(h.loading.value, false);
});

test('history pagination sends cursor/limit, prepends chronologically without duplication, and restores scroll', async () => {
  const h = setup(); const requests = [], restored = [];
  h.api.history = async params => { requests.push(params); return { data: requests.length === 1 ? {
    messages: [{ role: 'user', content: '较新问题', sequence: 3 }, { role: 'assistant', content: '较新回答', sequence: 4 }], has_more: true, next_before_sequence: 3,
  } : { messages: [{ role: 'user', content: '较早问题', sequence: 1 }, { role: 'assistant', content: '较早回答', sequence: 2 }, { role: 'user', content: '较新问题', sequence: 3 }], has_more: false, next_before_sequence: null } }; };
  h.chatListRef.value = { scrollToBottom() {}, captureScrollPosition: () => ({ top: 22, height: 100 }), restoreScrollPosition: position => restored.push(position) };
  await h.mount(); assert.equal(h.hasMoreHistory.value, true); await h.loadHistory(true);
  assert.deepEqual(JSON.parse(JSON.stringify(requests)), [{ limit: 50 }, { limit: 50, before_sequence: 3 }]);
  assert.deepEqual(Array.from(h.messages.value, message => message.content), ['较早问题', '较早回答', '较新问题', '较新回答']);
  assert.deepEqual(restored, [{ top: 22, height: 100 }]);
  assert.equal(h.hasMoreHistory.value, false); assert.equal(h.historyLoading.value, false);
});

for (const action of ['send', 'reset']) {
  test(`late history page cannot modify the conversation after ${action}`, async () => {
    const h = setup(); const initial = h.mount(); h.history.resolve({ data: { ...historyResponse.data, has_more: true, next_before_sequence: 3 } }); await initial;
    const page = deferred(); let calls = 0; h.api.history = () => { calls++; return page.promise; };
    const paging = h.loadHistory(true); h.loadHistory(true); assert.equal(calls, 1);
    if (action === 'send') h.sendQuery('分页期间新问题');
    else { const reset = h.handleReset(); h.reset.resolve({ data: {} }); await reset; }
    page.resolve({ data: { messages: [{ role: 'assistant', content: '过期历史', sequence: 1 }], has_more: true, next_before_sequence: 1 } }); await paging;
    assert.equal(h.messages.value.some(message => message.content === '过期历史'), false);
    assert.equal(h.historyLoading.value, false);
    if (action === 'reset') assert.equal(h.hasMoreHistory.value, false);
    else assert.equal(h.loading.value, true);
  });
}
