"""离线验证工具循环保留预算检查、用量回调和原始工具证据。"""

import copy
import json
import unittest

from application.ai_assistant.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from application.ai_assistant.agent_loop import AgentPrompt
from application.ai_assistant.tests.test_tooling import make_tool

from application.ai_assistant.agent_loop import astream_agent, invoke_agent
from application.ai_assistant.context_budget import (
    ContextBudgetExceeded, ContextBudgetPolicy, GuardedChatModel,
)
from application.ai_assistant.context_compaction import COLUMNAR_FORMAT, unpack_columnar
from application.ai_assistant.token_estimation import estimate_tokens


USAGE = {"input_tokens": 17, "output_tokens": 3, "total_tokens": 20}


class FakeMessagesListChatModel:
    """按顺序循环返回预设消息的测试假模型。"""
    def __init__(self, responses):
        self.responses, self.index = responses, 0

    def invoke(self, input, config=None, **kwargs):
        response = self.responses[self.index]
        self.index = (self.index + 1) % len(self.responses)
        return response

    async def ainvoke(self, input, config=None, **kwargs):
        return self.invoke(input, config, **kwargs)

    def stream(self, input, config=None, **kwargs):
        yield self.invoke(input, config, **kwargs)

    async def astream(self, input, config=None, **kwargs):
        yield self.invoke(input, config, **kwargs)


class RecordingToolModel:
    """记录输入、片段和用量的离线模型。"""
    def __init__(self, use_tool=True, **kwargs):
        self.seen, self.bound_names, self.use_tool = [], [], use_tool
        self.__dict__.update(kwargs)

    def bind_tools(self, tools, **kwargs):
        self.bound_names.extend(getattr(tool, "name", "unknown") for tool in tools)
        return self

    def _response(self, messages):
        self.seen.append(copy.deepcopy(messages))
        if self.use_tool and not any(isinstance(message, ToolMessage) for message in messages):
            return AIMessage(
                content="", tool_calls=[{"name": "query_trend", "args": {}, "id": "call-1"}],
                usage_metadata=USAGE.copy(), response_metadata={"offline": True},
            )
        return AIMessage(
            content="已按原始统计口径返回。", usage_metadata=USAGE.copy(),
            response_metadata={"offline": True},
        )

    def invoke(self, messages, config=None, **kwargs):
        response = self._response(messages)
        if collector := (config or {}).get("usage"):
            collector.record(response)
        return response

    async def ainvoke(self, messages, config=None, **kwargs):
        return self.invoke(messages, config, **kwargs)

    def stream(self, messages, config=None, **kwargs):
        observe = (config or {}).get("observe", lambda kind, value: None)
        observe("start", messages)
        response = None
        for chunk in self._stream(messages, **kwargs):
            observe("chunk", chunk)
            response = chunk if response is None else response + chunk
            yield chunk
        if collector := (config or {}).get("usage"):
            collector.record(response)

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._response(messages)
        yield AIMessageChunk(
            content=message.content, tool_calls=message.tool_calls,
            usage_metadata=message.usage_metadata,
            response_metadata=message.response_metadata,
        )

    async def astream(self, messages, config=None, **kwargs):
        for chunk in self.stream(messages, config, **kwargs):
            yield chunk


def trend_payload():
    return json.dumps({
        "project_id": 42, "ring_range": [1, 160], "unit": "mm",
        "denominator": "normal_count + abnormal_count; excludes unknown_count",
        "data": [
            {"ring_no": index + 1, "normal_count": 5, "abnormal_count": 5,
             "unknown_count": 90, "abnormal_rate": 50.0, "wear_mm": None}
            for index in range(160)
        ],
    }, ensure_ascii=False)


def make_agent(payload, policy=None):
    model = RecordingToolModel()
    guard = GuardedChatModel(model, policy or ContextBudgetPolicy(
        context_tokens=4096, output_tokens=512, safety_margin_tokens=512,
    ))
    tool = make_tool(
        func=lambda: payload, name="query_trend",
        description="Return exact per-ring counts, unknown values and the denominator.",
    )
    prompt = AgentPrompt("Use query_trend for statistics. Preserve scope, null and denominator.")
    return model, guard, prompt, [tool]


class ContextBudgetAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_agent_compacts_second_round_only_and_preserves_evidence(self):
        payload = trend_payload()
        model, guard, prompt, tools = make_agent(payload)
        # The raw observation alone is too large; only lossless compaction
        # allows this second model round to proceed under the selected budget.
        self.assertGreater(estimate_tokens(payload), guard.policy.input_budget)
        result = invoke_agent(guard, prompt, tools, {"input": "查询1至160环异常率"})
        self.assertEqual(len(model.seen), 2)
        self.assertEqual(model.bound_names, ["query_trend", "query_trend"])
        self.assertFalse(any(isinstance(message, ToolMessage) for message in model.seen[0]))
        observation = next(message for message in model.seen[1] if isinstance(message, ToolMessage))
        self.assertEqual(json.loads(observation.content)["format"], COLUMNAR_FORMAT)
        self.assertEqual(unpack_columnar(observation.content), json.loads(payload))
        self.assertEqual(observation.tool_call_id, "call-1")
        self.assertEqual(result["intermediate_steps"][0][1], payload)
        self.assertEqual(result["output"], "已按原始统计口径返回。")

    async def test_async_agent_also_guards_each_round(self):
        payload = trend_payload()
        model, guard, prompt, tools = make_agent(payload)
        events = [event async for event in astream_agent(guard, prompt, tools, {"input": "查询1至160环异常率"})]
        result = events[-1]
        self.assertEqual(len(model.seen), 2)
        observation = next(message for message in model.seen[1] if isinstance(message, ToolMessage))
        self.assertEqual(unpack_columnar(observation.content), json.loads(payload))
        self.assertEqual(result["intermediate_steps"][0][1], payload)

    async def test_event_stream_retains_model_events_usage_and_original_tool_output(self):
        payload = trend_payload()
        model, guard, prompt, tools = make_agent(payload)
        starts, streams = [], []

        def observe(kind, value):
            (starts if kind == "start" else streams).append(value)

        events = [event async for event in astream_agent(
            guard, prompt, tools, {"input": "查询1至160环异常率"}, config={"observe": observe},
        )]
        self.assertEqual(len(model.seen), 2)
        self.assertGreaterEqual(len(starts), 2)
        self.assertTrue(streams)
        self.assertTrue(any(chunk.content == "已按原始统计口径返回。" for chunk in streams))
        self.assertTrue(any(chunk.usage_metadata == USAGE for chunk in streams))
        self.assertTrue(any(event["type"] == "model_text" and event["content"] == "已按原始统计口径返回。"
                            for event in events))
        tool_ends = [event for event in events if event["type"] == "tool_end"]
        self.assertEqual(len(tool_ends), 1)
        self.assertEqual(tool_ends[0]["observation"], payload)

    def test_oversized_second_round_is_blocked_before_another_model_call(self):
        payload = json.dumps({"narrative": "无法结构压缩的长结果" * 5000}, ensure_ascii=False)
        model, guard, prompt, tools = make_agent(payload, ContextBudgetPolicy(
            context_tokens=4096, output_tokens=256, safety_margin_tokens=256,
        ))
        with self.assertRaises(ContextBudgetExceeded):
            invoke_agent(guard, prompt, tools, {"input": "查询1至160环异常率"})
        self.assertEqual(len(model.seen), 1)

    async def test_async_event_second_round_is_blocked_after_original_tool_event(self):
        payload = json.dumps({"narrative": "巨大工具输出" * 5000}, ensure_ascii=False)
        model, guard, prompt, tools = make_agent(payload, ContextBudgetPolicy(
            context_tokens=4096, output_tokens=256, safety_margin_tokens=256,
        ))
        events = []
        with self.assertRaises(ContextBudgetExceeded):
            async for event in astream_agent(guard, prompt, tools, {"input": "查询"}):
                events.append(event)
        self.assertEqual(len(model.seen), 1)
        self.assertTrue(any(event["type"] == "tool_end"
                            and event["observation"] == payload for event in events))

    def test_error_observation_is_never_reformatted(self):
        payload = json.dumps({"error": "invalid ring range", "details": [1, 160]}, indent=4)
        model, guard, prompt, tools = make_agent(payload)
        result = invoke_agent(guard, prompt, tools, {"input": "查询"})
        observation = next(message for message in model.seen[1] if isinstance(message, ToolMessage))
        self.assertEqual(observation.content, payload)
        self.assertEqual(result["intermediate_steps"][0][1], payload)

    async def test_direct_model_methods_preserve_usage_and_response_metadata(self):
        model = RecordingToolModel(use_tool=False)
        guard = GuardedChatModel(model, ContextBudgetPolicy())
        messages = [HumanMessage(content="hello")]
        responses = [guard.invoke(messages), await guard.ainvoke(messages)]
        responses.extend(guard.stream(messages))
        responses.extend([chunk async for chunk in guard.astream(messages)])
        self.assertEqual(len(responses), 4)
        for response in responses:
            self.assertEqual(response.usage_metadata, USAGE)
            self.assertTrue(response.response_metadata["offline"])
        self.assertEqual(messages, [HumanMessage(content="hello")])


if __name__ == "__main__":
    unittest.main()
