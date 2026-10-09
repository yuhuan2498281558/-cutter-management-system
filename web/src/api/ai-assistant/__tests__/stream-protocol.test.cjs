// Run from web: node --test src/api/ai-assistant/__tests__/stream-protocol.test.cjs
// Execute the real API client with deterministic HTTP/stream boundaries.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function setup({ payload = '', contentType = 'text/event-stream; charset=utf-8', status = 200, fetchImpl, response } = {}) {
  const requests = [];
  const context = { exports: {}, TextDecoder, fetch: async (url, options) => {
    requests.push({ url, options });
    return fetchImpl ? fetchImpl(url, options) : new Response(payload, { status, headers: { 'Content-Type': contentType } });
  }};
  context.require = name => {
    if (name === 'axios') return { create: () => ({
      interceptors: { request: { use() {} } },
      get: async () => ({ data: response || { code: 2000, data: {} } }),
      post: async () => ({ data: response || { code: 2000, data: {} } }),
    }) };
    if (name === '/@/utils/storage') return { Session: { get: () => 'test-token' } };
    throw new Error(`Unexpected import: ${name}`);
  };
  const source = fs.readFileSync(path.resolve(__dirname, '../index.ts'), 'utf8').replaceAll('import.meta.env.VITE_API_URL', "''");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText, context);
  const api = context.exports.useAiAssistantApi();
  const events = [];
  const callbacks = { onChunk: value => events.push(['chunk', value]), onDone: () => events.push(['done']), onError: value => events.push(['error', value]), onMemory: value => events.push(['memory', value]) };
  return { api, requests, events, callbacks, run: signal => api.chatStream({ query: '当前项目换刀汇总', route_mode: 'rule' }, callbacks, signal) };
}

test('preserves POST/JWT/query/mode and parses split UTF-8, CRLF, comments, memory and an unterminated final done event', async () => {
  const payload = ': connected\r\n\r\ndata: {"type":"chunk","content":"刀具"}\r\n\r\ndata: {"type":"memory","backend":"django","message_count":2,"slot_names":["ring_range"]}\n\ndata: {"type":"done"}';
  const bytes = new TextEncoder().encode(payload);
  const h = setup({ fetchImpl: async () => new Response(new ReadableStream({ start(controller) { for (const byte of bytes) controller.enqueue(Uint8Array.of(byte)); controller.close(); } }), { headers: { 'Content-Type': 'text/event-stream' } }) });
  await h.run();
  assert.deepEqual(h.events.map(event => event[0]), ['chunk', 'memory', 'done']);
  assert.equal(h.events[0][1], '刀具');
  assert.deepEqual(Array.from(h.events[1][1].slots), ['ring_range']);
  assert.equal(h.requests[0].url, '/api/ai/chat/stream/');
  assert.equal(h.requests[0].options.method, 'POST');
  assert.equal(h.requests[0].options.headers.Authorization, 'JWT test-token');
  assert.deepEqual(JSON.parse(h.requests[0].options.body), { query: '当前项目换刀汇总', route_mode: 'rule' });
});

for (const [label, options, pattern] of [
  ['malformed JSON', { payload: 'data: {broken}\n\n' }, /解析失败/],
  ['premature EOF', { payload: 'data: {"type":"chunk","content":"未完成"}\n\n' }, /回答不完整/],
  ['HTML response', { payload: '<html>proxy error</html>', contentType: 'text/html' }, /未返回流式响应/],
  ['HTTP error', { status: 401 }, /401/],
  ['invalid chunk shape', { payload: 'data: {"type":"chunk","content":{}}\n\n' }, /文本格式无效/],
]) {
  test(`${label} is one visible error, never a successful done`, async () => {
    const h = setup(options); await h.run();
    assert.equal(h.events.filter(event => event[0] === 'done').length, 0);
    assert.equal(h.events.filter(event => event[0] === 'error').length, 1);
    assert.match(h.events.at(-1)[1], pattern);
  });
}

test('sends explicit context controls and preserves an empty effective scope', async () => {
  const h = setup({ payload: 'data: {"type":"memory","slot_names":["tool_type"],"active_slots":{},"context_mode":"new"}\n\ndata: {"type":"done"}\n\n' });
  await h.api.chatStream({ query: '换刀统计', context_mode: 'new', clear_slots: ['tool_type'] }, h.callbacks);
  assert.deepEqual(JSON.parse(h.requests[0].options.body), { query: '换刀统计', context_mode: 'new', clear_slots: ['tool_type'] });
  assert.deepEqual(Object.keys(h.events[0][1].activeSlots), []);
  assert.equal(h.events[0][1].contextMode, 'new');
});

test('terminal event stops callbacks and cancels/releases an open reader', async () => {
  let cancelled = 0;
  const stream = new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode('data: {"type":"done"}\n\ndata: {"type":"chunk","content":"late"}\n\n')); }, cancel() { cancelled++; } });
  const h = setup({ fetchImpl: async () => new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } }) });
  await h.run();
  assert.deepEqual(h.events, [['done']]);
  assert.equal(cancelled, 1);
  assert.equal(stream.locked, false);
});

test('server error is terminal even if followed by done', async () => {
  const h = setup({ payload: 'data: {"type":"error","content":"服务暂不可用"}\n\ndata: {"type":"done"}\n\n' });
  await h.run(); assert.deepEqual(h.events, [['error', '服务暂不可用']]);
});

test('abort suppresses queued callbacks and releases the reader', async () => {
  const controller = new AbortController();
  const stream = new ReadableStream({ start(source) { source.enqueue(new TextEncoder().encode('data: {"type":"chunk","content":"first"}\n\ndata: {"type":"done"}\n\n')); } });
  const h = setup({ fetchImpl: async () => new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } }) });
  h.callbacks.onChunk = value => { h.events.push(['chunk', value]); controller.abort(); };
  await h.run(controller.signal);
  assert.deepEqual(h.events, [['chunk', 'first']]);
  assert.equal(stream.locked, false);
});

test('business failures in HTTP 200 reject history/reset/chat and do not masquerade as success', async () => {
  const h = setup({ response: { code: 4000, data: null, msg: '数据库操作失败' } });
  await assert.rejects(h.api.reset(), /数据库操作失败/);
  await assert.rejects(h.api.history(), /数据库操作失败/);
  await assert.rejects(h.api.chat({ query: 'test' }), /数据库操作失败/);
});

test('authoritative answer is delivered separately from transient chunks before done', async () => {
  const h = setup({ payload: 'data: {"type":"chunk","content":"临时分析"}\n\ndata: {"type":"answer","content":"最终结论"}\n\ndata: {"type":"done"}\n\n' });
  h.callbacks.onAnswer = value => h.events.push(['answer', value]);
  await h.run(); assert.deepEqual(h.events, [['chunk', '临时分析'], ['answer', '最终结论'], ['done']]);
});
