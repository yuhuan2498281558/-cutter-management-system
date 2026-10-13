"""Offline integration with the real LangChain 0.3 agent/executor protocol."""

import copy
import json
import unittest

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool
from pydantic import Field

from application.ai_assistant.context_budget import (
    ContextBudgetExceeded, ContextBudgetPolicy, GuardedChatModel,
)
from application.ai_assistant.context_compaction import COLUMNAR_FORMAT, unpack_columnar
from application.ai_assistant.token_estimation import estimate_tokens


USAGE = {"input_tokens": 17, "output_tokens": 3, "total_tokens": 20}


class RecordingToolModel(BaseChatModel):
    """Local deterministic model; no provider, tokenization download or DB."""

    seen: list = Field(default_factory=list)
    bound_names: list = Field(default_factory=list)
    use_tool: bool = True

    @property
    def _llm_type(self):
        return "offline-context-budget-integration"

    def bind_tools(self, tools, **kwargs):
        self.bound_names.extend(getattr(tool, "name", "unknown") for tool in tools)
        return self

    def get_num_tokens(self, text):
        # Defensive offline fallback only. Production guard uses estimate_tokens,
        # so this fake tokenizer does not establish real provider token counts.
        return len(text)

    def get_num_tokens_from_messages(self, messages, tools=None):
        return sum(len(str(message.content)) + 12 for message in messages)

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

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._response(messages))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._response(messages)
        yield ChatGenerationChunk(message=AIMessageChunk(
            content=message.content, tool_calls=message.tool_calls,
            usage_metadata=message.usage_metadata,
            response_metadata=message.response_metadata,
        ))

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        for chunk in self._stream(messages, stop=stop, **kwargs):
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


def make_executor(payload, policy=None):
    model = RecordingToolModel()
    guard = GuardedChatModel(model, policy or ContextBudgetPolicy(
        context_tokens=4096, output_tokens=512, safety_margin_tokens=512,
    ))
    tool = StructuredTool.from_function(
        func=lambda: payload, name="query_trend",
        description="Return exact per-ring counts, unknown values and the denominator.",
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Use query_trend for statistics. Preserve scope, null and denominator."),
        ("human", "{input}"), MessagesPlaceholder("agent_scratchpad"),
    ])
    agent = create_tool_calling_agent(guard, [tool], prompt)
    executor = AgentExecutor(
        agent=agent, tools=[tool], return_intermediate_steps=True, max_iterations=3,
    )
    return model, guard, executor


class ContextBudgetAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_real_executor_compacts_second_round_only_and_preserves_evidence(self):
        payload = trend_payload()
        model, guard, executor = make_executor(payload)
        # The raw observation alone is too large; only lossless compaction
        # allows this second model round to proceed under the selected budget.
        self.assertGreater(estimate_tokens(payload), guard.policy.input_budget)
        result = executor.invoke({"input": "查询1至160环异常率"})
        self.assertEqual(len(model.seen), 2)
        self.assertEqual(model.bound_names, ["query_trend"])
        self.assertFalse(any(isinstance(message, ToolMessage) for message in model.seen[0]))
        observation = next(message for message in model.seen[1] if isinstance(message, ToolMessage))
        self.assertEqual(json.loads(observation.content)["format"], COLUMNAR_FORMAT)
        self.assertEqual(unpack_columnar(observation.content), json.loads(payload))
        self.assertEqual(observation.tool_call_id, "call-1")
        self.assertEqual(result["intermediate_steps"][0][1], payload)
        self.assertEqual(result["output"], "已按原始统计口径返回。")

    async def test_async_executor_also_guards_each_round(self):
        payload = trend_payload()
        model, _, executor = make_executor(payload)
        result = await executor.ainvoke({"input": "查询1至160环异常率"})
        self.assertEqual(len(model.seen), 2)
        observation = next(message for message in model.seen[1] if isinstance(message, ToolMessage))
        self.assertEqual(unpack_columnar(observation.content), json.loads(payload))
        self.assertEqual(result["intermediate_steps"][0][1], payload)

    async def test_event_stream_retains_model_events_usage_and_original_tool_output(self):
        payload = trend_payload()
        model, _, executor = make_executor(payload)
        events = [event async for event in executor.astream_events(
            {"input": "查询1至160环异常率"}, version="v2",
        )]
        starts = [event for event in events if event["event"] == "on_chat_model_start"]
        streams = [event for event in events if event["event"] == "on_chat_model_stream"]
        self.assertEqual(len(model.seen), 2)
        self.assertGreaterEqual(len(starts), 2)
        self.assertTrue(streams)
        self.assertTrue(any(event["data"]["chunk"].content == "已按原始统计口径返回。"
                            for event in streams))
        self.assertTrue(any(event["data"]["chunk"].usage_metadata == USAGE for event in streams))
        tool_ends = [event for event in events if event["event"] == "on_tool_end"]
        self.assertEqual(len(tool_ends), 1)
        self.assertEqual(tool_ends[0]["data"]["output"], payload)

    def test_oversized_second_round_is_blocked_before_another_model_call(self):
        payload = json.dumps({"narrative": "无法结构压缩的长结果" * 5000}, ensure_ascii=False)
        model, _, executor = make_executor(payload, ContextBudgetPolicy(
            context_tokens=4096, output_tokens=256, safety_margin_tokens=256,
        ))
        with self.assertRaises(ContextBudgetExceeded):
            executor.invoke({"input": "查询1至160环异常率"})
        self.assertEqual(len(model.seen), 1)

    async def test_async_event_second_round_is_blocked_after_original_tool_event(self):
        payload = json.dumps({"narrative": "巨大工具输出" * 5000}, ensure_ascii=False)
        model, _, executor = make_executor(payload, ContextBudgetPolicy(
            context_tokens=4096, output_tokens=256, safety_margin_tokens=256,
        ))
        events = []
        with self.assertRaises(ContextBudgetExceeded):
            async for event in executor.astream_events({"input": "查询"}, version="v2"):
                events.append(event)
        self.assertEqual(len(model.seen), 1)
        self.assertTrue(any(event["event"] == "on_tool_end"
                            and event["data"]["output"] == payload for event in events))

    def test_error_observation_is_never_reformatted(self):
        payload = json.dumps({"error": "invalid ring range", "details": [1, 160]}, indent=4)
        model, _, executor = make_executor(payload)
        result = executor.invoke({"input": "查询"})
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
