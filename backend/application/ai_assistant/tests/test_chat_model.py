import asyncio
import json
from unittest.mock import patch

import httpx
import openai
from asgiref.sync import async_to_sync
from django.test import SimpleTestCase
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from application.ai_assistant.chat_model import ChatCompletionsModel
from application.ai_assistant.context_budget import (
    ContextBudgetPolicy, ContextUsage, GuardedChatModel, OutputLimitExceeded, context_usage,
)
from application.ai_assistant.llm_service import _context_overflow, ToolAssistant


_DEEPSEEK_USAGE = {
    "prompt_tokens": 30, "completion_tokens": 7, "total_tokens": 37,
    "prompt_cache_hit_tokens": 24, "prompt_cache_miss_tokens": 6,
}
_OPENAI_USAGE = {
    "prompt_tokens": 30, "completion_tokens": 7, "total_tokens": 37,
    "prompt_tokens_details": {"cached_tokens": 24},
    "completion_tokens_details": {"reasoning_tokens": 3},
}
_NORMALIZED = {
    "input_tokens": 30, "output_tokens": 7, "total_tokens": 37,
    "input_token_details": {}, "output_token_details": {},
}
_TOOLS = [{"type": "function", "function": {"name": "query", "description": "查询", "parameters": {
    "type": "object", "properties": {"city": {"type": "string"}},
}}}]
_CALLS = [
    {"id": "one", "type": "function", "function": {"name": "query", "arguments": '{"city": "北京"}'}},
    {"id": "two", "type": "function", "function": {"name": "query", "arguments": '{"city": "上海"}'}},
]


def _completion(usage, calls=None, finish="stop"):
    return {
        "id": "answer-1", "object": "chat.completion", "created": 1, "model": "actual-model",
        "system_fingerprint": "fp-test", "usage": usage,
        "choices": [{"index": 0, "finish_reason": finish, "message": {
            "role": "assistant", "content": None if calls else "答案", "tool_calls": calls,
        }}],
    }


def _stream_body(usage, deltas=None, finish="stop"):
    if deltas is None:
        deltas = [{"role": "assistant", "content": ""}, {"content": "答"}, {"content": "案"}]
    base = {"id": "answer-1", "object": "chat.completion.chunk", "created": 1,
            "model": "actual-model", "system_fingerprint": "fp-test"}
    chunks = [{**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]} for delta in deltas]
    chunks.append({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
    chunks.append({**base, "choices": [], "usage": usage})
    return ("".join("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n" for chunk in chunks)
            + "data: [DONE]\n\n").encode("utf-8")


def _merge(chunks):
    result = chunks[0]
    for chunk in chunks[1:]:
        result += chunk
    return result


class ChatModelTests(SimpleTestCase):
    def _model(self, usage=_DEEPSEEK_USAGE, calls=None, deltas=None, finish="stop", **kwargs):
        requests = []

        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            if body["stream"]:
                return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                      content=_stream_body(usage, deltas, finish))
            return httpx.Response(200, json=_completion(usage, calls, finish))

        sync_client = httpx.Client(transport=httpx.MockTransport(respond))
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        self.addCleanup(sync_client.close)
        self.addCleanup(async_to_sync(async_client.aclose))
        model = ChatCompletionsModel(
            model="test-model", base_url="http://test.invalid/v1", api_key="test-not-a-secret",
            temperature=0.1, timeout=60, max_tokens=8192,
            http_client=sync_client, http_async_client=async_client, **kwargs,
        )
        return model, requests

    async def test_nonstream_text_usage_and_callbacks(self):
        for usage, details in ((_DEEPSEEK_USAGE, ({}, {})), (_OPENAI_USAGE, ({"cache_read": 24}, {"reasoning": 3})),
                               ({**_OPENAI_USAGE, "total_tokens": 0, "prompt_tokens_details": {"cached_tokens": 0},
                                 "completion_tokens_details": {"reasoning_tokens": 0}}, ({"cache_read": 0}, {"reasoning": 0}))):
            model, requests = self._model(usage)
            expected = {**_NORMALIZED, "input_token_details": details[0], "output_token_details": details[1]}
            handler = UsageMetadataCallbackHandler()
            config = {"callbacks": [handler], "tags": ["offline"], "metadata": {"turn": "test"}}
            messages = [model.invoke("问题", config=config), await model.ainvoke("问题", config=config)]
            for message in messages:
                self.assertEqual(message.content, "答案")
                self.assertEqual(message.tool_calls, [])
                self.assertEqual(message.invalid_tool_calls, [])
                self.assertEqual(message.additional_kwargs, {"refusal": None})
                self.assertEqual(message.usage_metadata, expected)
                raw = message.response_metadata["token_usage"]
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    self.assertEqual(raw[key], usage[key])
                if usage is _DEEPSEEK_USAGE:
                    self.assertEqual(raw, {**usage, "prompt_tokens_details": None, "completion_tokens_details": None})
                self.assertEqual(message.response_metadata["model_name"], "actual-model")
                self.assertEqual(message.response_metadata["finish_reason"], "stop")
            self.assertEqual(handler.usage_metadata["actual-model"], {
                "input_tokens": 60, "output_tokens": 14, "total_tokens": 74,
                "input_token_details": {k: v * 2 for k, v in details[0].items()},
                "output_token_details": {k: v * 2 for k, v in details[1].items()},
            })
            self.assertEqual(requests, [{"model": "test-model", "temperature": 0.1, "stream": False,
                                         "max_tokens": 8192, "messages": [{"role": "user", "content": "问题"}]}] * 2)
            self.assertIs(model._get_client(), model._get_client())
            self.assertEqual(model._get_client().max_retries, 2)
            self.assertEqual(model._get_client().timeout, 60)

    async def test_stream_text_usage_tail_and_callbacks(self):
        for usage, details in ((_DEEPSEEK_USAGE, ({}, {})), (_OPENAI_USAGE, ({"cache_read": 24}, {"reasoning": 3}))):
            model, requests = self._model(usage)
            handler = UsageMetadataCallbackHandler()
            config = {"callbacks": [handler]}
            streams = [list(model.stream("问题", config=config)),
                       [chunk async for chunk in model.astream("问题", config=config)]]
            for chunks in streams:
                self.assertEqual([chunk.content for chunk in chunks], ["", "答", "案", "", ""])
                self.assertEqual([chunk.response_metadata for chunk in chunks[:3]], [{}, {}, {}])
                self.assertEqual(chunks[-2].response_metadata, {
                    "finish_reason": "stop", "model_name": "actual-model", "system_fingerprint": "fp-test",
                })
                self.assertEqual(chunks[-1].usage_metadata, {
                    **_NORMALIZED, "input_token_details": details[0], "output_token_details": details[1],
                })
                raw = chunks[-1].response_metadata["token_usage"]
                self.assertEqual(raw["prompt_tokens"], 30)
                if usage is _DEEPSEEK_USAGE:
                    self.assertEqual(raw, {**usage, "prompt_tokens_details": None, "completion_tokens_details": None})
                self.assertEqual(_merge(chunks).content, "答案")
            self.assertEqual(handler.usage_metadata["actual-model"]["total_tokens"], 74)
            for request in requests:
                self.assertTrue(request["stream"])
                self.assertEqual(request["stream_options"], {"include_usage": True})

    async def test_two_tools_with_fragmented_names_and_arguments(self):
        deltas = [
            {"role": "assistant", "tool_calls": [{"index": i, "id": call["id"], "type": "function",
                "function": {"name": "que", "arguments": '{"ci'}} for i, call in enumerate(_CALLS)]},
            {"tool_calls": [{"index": i, "function": {"name": "ry", "arguments": 'ty": "'}} for i in range(2)]},
            {"tool_calls": [{"index": i, "function": {"arguments": city + '"}'}} for i, city in enumerate(("北京", "上海"))]},
        ]
        model, _ = self._model(calls=_CALLS, deltas=deltas, finish="tool_calls")
        expected = [{"name": "query", "args": {"city": city}, "id": call_id, "type": "tool_call"}
                    for city, call_id in (("北京", "one"), ("上海", "two"))]
        response = model.invoke("问题")
        self.assertEqual(response.tool_calls, expected)
        self.assertEqual(response.additional_kwargs, {"tool_calls": _CALLS, "refusal": None})
        for chunks in (list(model.stream("问题")), [chunk async for chunk in model.astream("问题")]):
            self.assertEqual(chunks[0].tool_call_chunks, [
                {"index": i, "id": call_id, "name": "que", "args": '{"ci', "type": "tool_call_chunk"}
                for i, call_id in enumerate(("one", "two"))
            ])
            self.assertEqual(chunks[1].tool_call_chunks, [
                {"index": i, "id": None, "name": "ry", "args": 'ty": "', "type": "tool_call_chunk"} for i in range(2)
            ])
            combined = _merge(chunks)
            self.assertEqual(combined.tool_calls, expected)
            self.assertEqual(combined.invalid_tool_calls, [])
            self.assertEqual(combined.additional_kwargs["tool_calls"], [{**call, "index": i} for i, call in enumerate(_CALLS)])

    async def test_invalid_tool_arguments_preserve_raw_response(self):
        calls = [{"id": "bad", "type": "function", "function": {"name": "query", "arguments": "not-json"}}]
        model, _ = self._model(calls=calls, deltas=[{"tool_calls": [{**calls[0], "index": 0}]}], finish="tool_calls")
        error = ("Function query arguments:\n\nnot-json\n\nare not valid JSON. Received JSONDecodeError "
                 "Expecting value: line 1 column 1 (char 0)\nFor troubleshooting, visit: "
                 "https://python.langchain.com/docs/troubleshooting/errors/OUTPUT_PARSING_FAILURE ")
        for response in (model.invoke("问题"), await model.ainvoke("问题")):
            self.assertEqual(response.content, "")
            self.assertEqual(response.tool_calls, [])
            self.assertEqual(response.invalid_tool_calls, [
                {"name": "query", "args": "not-json", "id": "bad", "error": error, "type": "invalid_tool_call"},
            ])
            self.assertEqual(response.additional_kwargs, {"tool_calls": calls, "refusal": None})
        combined = _merge([chunk async for chunk in model.astream("问题")])
        self.assertEqual(combined.invalid_tool_calls, [
            {"name": "query", "args": "not-json", "id": "bad", "error": None, "type": "invalid_tool_call"},
        ])

    def test_multiturn_request_tools_and_output_parameters(self):
        messages = [SystemMessage(content="系统", name="system-name"), HumanMessage(content="问题", name="user-name"),
                    AIMessage(content="", tool_calls=[{"id": "one", "name": "query", "args": {"city": "北京"}}]),
                    ToolMessage(content='{"count": 3}', tool_call_id="one", name="ignored")]
        for parameter in ("max_tokens", "max_completion_tokens"):
            model, requests = self._model(output_parameter=parameter)
            guard = GuardedChatModel(model, ContextBudgetPolicy()).bind_tools(_TOOLS, tool_choice="auto")
            self.assertIs(guard.model, model)
            self.assertEqual(guard.request_options, {"tools": _TOOLS, "tool_choice": "auto"})
            guard.invoke(messages, max_tokens=128, stop=["END"])
            guard.invoke(messages, max_completion_tokens=128, stop=["END"])
            self.assertEqual(requests, [{
                "model": "test-model", "temperature": 0.1, "stream": False, parameter: 128,
                "tools": _TOOLS, "tool_choice": "auto", "stop": ["END"], "messages": [
                    {"role": "system", "content": "系统", "name": "system-name"},
                    {"role": "user", "content": "问题", "name": "user-name"},
                    {"role": "assistant", "content": None, "tool_calls": [{"id": "one", "type": "function",
                     "function": {"name": "query", "arguments": '{"city": "\\u5317\\u4eac"}'}}]},
                    {"role": "tool", "content": '{"count": 3}', "tool_call_id": "one"},
                ],
            }] * 2)

    async def test_length_stop_is_rejected_after_usage_recording(self):
        model, _ = self._model(finish="length")
        guard = GuardedChatModel(model, ContextBudgetPolicy(), provider="deepseek")
        usage = ContextUsage()
        token = context_usage.set(usage)
        try:
            with self.assertRaises(OutputLimitExceeded):
                guard.invoke("问题")
            with self.assertRaises(OutputLimitExceeded):
                await guard.ainvoke("问题")
            with self.assertRaises(OutputLimitExceeded):
                list(guard.stream("问题"))
            with self.assertRaises(OutputLimitExceeded):
                _ = [chunk async for chunk in guard.astream("问题")]
        finally:
            context_usage.reset(token)
        self.assertEqual(len(usage.calls), 4)
        self.assertEqual(usage.provider_usage, {"prompt_tokens": 120, "completion_tokens": 28, "cache_hit_tokens": 96})
        self.assertTrue(all(call["model"] == "actual-model" for call in usage.calls))

    def test_repeated_async_to_sync_caches_clients_per_loop(self):
        model, requests = self._model()
        clients, loops = [], []

        async def consume_twice():
            loops.append(asyncio.get_running_loop())
            for _ in range(2):
                chunks = [chunk async for chunk in model.astream("问题")]
                self.assertEqual(_merge(chunks).content, "答案")
                clients.append(model._get_async_client())

        async_to_sync(consume_twice)()
        async_to_sync(consume_twice)()
        self.assertIs(clients[0], clients[1])
        self.assertIs(clients[2], clients[3])
        self.assertIsNot(clients[0], clients[2])
        self.assertIsNot(loops[0], loops[1])
        self.assertTrue(all(loop.is_closed() for loop in loops))
        self.assertEqual(len(requests), 4)
        # 第二个临时循环开始用时，第一个已关闭循环的客户端已丢掉，缓存里只剩最近一个
        self.assertEqual(list(model._async_clients), [loops[1]])

    def test_sdk_errors_retries_and_httpx_timeout(self):
        for kind, expected, count in (("context", openai.BadRequestError, 1), ("connection", openai.APIConnectionError, 3),
                                     ("timeout", openai.APITimeoutError, 3), ("rate", openai.RateLimitError, 3)):
            attempts = []

            def fail(request):
                attempts.append(request)
                if kind == "connection":
                    raise httpx.ConnectError("offline", request=request)
                if kind == "timeout":
                    raise httpx.ReadTimeout("offline", request=request)
                return httpx.Response(400 if kind == "context" else 429, json={"error": {
                    "message": "maximum context length exceeded" if kind == "context" else "rate limit exceeded",
                    "type": "invalid_request_error", "code": "context_length_exceeded" if kind == "context" else "rate_limit_exceeded",
                }})

            with httpx.Client(transport=httpx.MockTransport(fail)) as client, patch("openai._base_client.time.sleep"):
                model = ChatCompletionsModel(model="test-model", base_url="http://test.invalid/v1", api_key="test-key",
                                             temperature=0.1, timeout=60, max_tokens=8192, http_client=client)
                with self.assertRaises(expected) as caught:
                    model.invoke("问题")
            self.assertEqual(len(attempts), count)
            self.assertEqual(attempts[0].extensions["timeout"], dict.fromkeys(("connect", "read", "write", "pool"), 60))
            if kind == "context":
                self.assertTrue(_context_overflow(caught.exception))
            if kind == "connection":
                self.assertEqual(ToolAssistant._friendly_error(None, str(caught.exception)), "无法连接到模型服务，请稍后重试。")
            if kind == "timeout":
                self.assertEqual(ToolAssistant._friendly_error(None, str(caught.exception)), "处理超时，请稍后重试或简化问题。")
