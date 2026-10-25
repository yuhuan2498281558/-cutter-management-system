import asyncio
import copy
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from rest_framework.test import force_authenticate

from application.ai_assistant import views
from application.ai_assistant.agent_views import agent_view
from application.ai_assistant.context_budget import (
    ContextBudgetPolicy, ContextUsage, GuardedChatModel, context_usage,
    estimate_request_tokens, mark_context_message,
)
from application.ai_assistant.context_compaction import COLUMNAR_FORMAT
from application.ai_assistant.llm_provider import LLMProviderError
from application.ai_assistant.llm_service import ToolAssistant
from application.ai_assistant.memory_service import MemoryService, MemorySnapshot, StoredMessage
from application.ai_assistant.tests.test_context_budget import RecordingModel
from application.ai_assistant.tests.test_context_budget_agent import RecordingToolModel, trend_payload
from application.ai_assistant.token_estimation import estimate_tokens


class MultiRoundModel(RecordingToolModel):
    def _response(self, messages):
        self.seen.append(copy.deepcopy(messages))
        round_no = sum(isinstance(message, ToolMessage) for message in messages)
        if round_no < 2:
            return AIMessage(content="", tool_calls=[{
                "name": "tool_query_tool_change_trend", "args": {}, "id": f"call-{round_no}",
            }])
        return AIMessage(content="已按原始统计口径返回。")


class PagingModel(MultiRoundModel):
    def _response(self, messages):
        response = super()._response(messages)
        if response.tool_calls:
            response.tool_calls[0]["args"] = {"page": len(self.seen)}
        return response

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        response = self._response(messages)
        if response.tool_calls:
            call = response.tool_calls[0]
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[{
                "name": call["name"], "id": call["id"], "args": '{"page":', "index": 0,
            }]))
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[{
                "args": str(call["args"]["page"]) + "}", "index": 0,
            }]))
        else:
            yield ChatGenerationChunk(message=AIMessageChunk(content=response.content))


def make_agent():
    model = MultiRoundModel()
    policy = ContextBudgetPolicy(context_tokens=32768)
    guard = GuardedChatModel(model, policy)
    payloads = iter([trend_payload(), '{"summary":"小结果"}'])

    def query_trend():
        return next(payloads)

    tool = StructuredTool.from_function(query_trend, name="tool_query_tool_change_trend",
                                        description="Return exact per-ring statistics.")
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Preserve scope and denominator."), MessagesPlaceholder("chat_history"),
        ("human", "{input}"), MessagesPlaceholder("agent_scratchpad"),
    ])
    executor = AgentExecutor(agent=create_tool_calling_agent(guard, [tool], prompt),
                             tools=[tool], return_intermediate_steps=True, max_iterations=3)
    options = {"tools": [convert_to_openai_tool(tool)], "max_tokens": policy.output_tokens}
    return model, guard, executor, options


class ContextUsageTests(SimpleTestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"AI_MEMORY_RECENT_TURNS": "3",
                                     "AI_MEMORY_CONTEXT_TOKEN_BUDGET": "1200",
                                     "AI_MEMORY_SUMMARY_TRIGGER_TOKENS": "1800",
                                     "AI_ABLATE_MEMORY": "0"})
        env.start()
        self.addCleanup(env.stop)

    def make_assistant(self, guard=None, snapshot=None):
        assistant = ToolAssistant()
        assistant.memory = MemoryService(backend="legacy")
        assistant._llm = guard
        snapshot = snapshot or MemorySnapshot(scope_key="user:1", backend="legacy")
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._store_turn_and_summarize = Mock(return_value=snapshot)
        assistant._direct_route = Mock(return_value=None)
        assistant._model_needs_tools = Mock(return_value=False)
        return assistant

    def assert_parts(self, info):
        self.assertEqual(set(info["parts"]), {"system", "tools", "memory", "question", "results", "other"})
        self.assertTrue(all(type(value) is int and value >= 0 for value in info["parts"].values()))
        self.assertEqual(sum(info["parts"].values()), info["used"])

    def test_agent_peak_keeps_all_results_and_compaction_stats(self):
        model, guard, executor, options = make_agent()
        assistant = self.make_assistant(guard)
        assistant._model_needs_tools = Mock(return_value=True)
        assistant._get_executor_for_query = Mock(return_value=executor)
        result = assistant.chat("查询换刀趋势", {"user_id": 1, "route_mode": "agent"})
        self.assertTrue(result["success"], result)
        info = result["context"]
        counts = [estimate_request_tokens(messages, options, guard.policy.tool_protocol_tokens)
                  for messages in model.seen]
        self.assertEqual(info["model_calls"], 3)
        self.assertEqual(info["used"], max(counts))
        self.assertEqual(info["used"], counts[-1])
        self.assertEqual(info["kind"], "turn")
        self.assert_parts(info)
        self.assertEqual(info["results_raw"], estimate_tokens(trend_payload()) + estimate_tokens('{"summary":"小结果"}'))
        self.assertGreater(info["results_raw"], info["parts"]["results"])
        self.assertEqual(info["compacted_results"], 1)
        self.assertEqual(info["summarized_results"], 0)
        self.assertIsNone(context_usage.get())

    async def test_paged_tool_lists_and_model_page_requests(self):
        for streaming in (False, True):
            model = PagingModel()
            guard = GuardedChatModel(model, ContextBudgetPolicy(context_tokens=32768))
            payload = json.loads(trend_payload())
            payload["data"] = payload["data"][:51]
            for index, row in enumerate(payload["data"]):
                row["observation"] = f"record-{index}:" + ("x" * 200 if index < 50 else "short")

            def query_trend(page: int = 1):
                return agent_view(json.dumps(payload), page=page)

            tool = StructuredTool.from_function(query_trend, name="tool_query_tool_change_trend",
                                                description="Read one page of per-ring statistics.")
            prompt = ChatPromptTemplate.from_messages([
                ("system", "Read later pages when necessary."), ("human", "{input}"),
                MessagesPlaceholder("agent_scratchpad"),
            ])
            executor = AgentExecutor(agent=create_tool_calling_agent(guard, [tool], prompt),
                                     tools=[tool], return_intermediate_steps=True, max_iterations=3)
            assistant = self.make_assistant(guard)
            assistant._model_needs_tools = Mock(return_value=True)
            assistant._get_executor_for_query = Mock(return_value=executor)
            request_context = {"user_id": 1, "route_mode": "agent"}
            if streaming:
                events = [event async for event in assistant.chat_stream("查看换刀明细", request_context)]
                self.assertEqual(events[-1]["type"], "done", events)
                info = events[-2]["context"]
            else:
                result = assistant.chat("查看换刀明细", request_context)
                self.assertTrue(result["success"], result)
                info = result["context"]
            self.assertGreaterEqual(info["paged_lists"], 1)
            self.assertEqual(info["page_requests"], 1)
            self.assertEqual(info["model_calls"], 3)
            self.assertEqual(info["paged_lists"], 2)
            self.assertTrue(any(json.loads(message.content).get("format") == COLUMNAR_FORMAT
                                for message in model.seen[1] if isinstance(message, ToolMessage)))
            self.assertEqual(estimate_request_tokens(model.seen[-1], {
                "tools": [convert_to_openai_tool(tool)], "max_tokens": guard.policy.output_tokens,
            }), info["used"])
            self.assert_parts(info)

    def test_internal_markers_do_not_change_estimates_or_reach_model(self):
        model = RecordingModel()
        guard = GuardedChatModel(model, ContextBudgetPolicy(context_tokens=32768))
        memory = mark_context_message(HumanMessage(content="旧问题"), memory="旧问题")
        messages = [SystemMessage(content="规则"), memory,
                    AIMessage(content="", tool_calls=[{"id": "old", "name": "query", "args": {"n": 2}}]),
                    ToolMessage(content='{"summary":"旧结果"}', tool_call_id="old"),
                    AIMessage(content="", tool_calls=[{"id": "new", "name": "query", "args": {}}]),
                    ToolMessage(content="{}", tool_call_id="new")]
        plain = copy.deepcopy(messages)
        plain[1].response_metadata.clear()
        self.assertEqual(estimate_request_tokens(messages), estimate_request_tokens(plain))
        usage = ContextUsage()
        token = context_usage.set(usage)
        try:
            guard.invoke(messages)
        finally:
            context_usage.reset(token)
        self.assertEqual(usage.peak["summarized_results"], 0)
        self.assertEqual(usage.peak["parts"]["memory"], estimate_request_tokens([memory]) - estimate_request_tokens([]))
        self.assertTrue(all("_context_parts" not in message.response_metadata for message in model.calls[0][0]))
        self.assertIn("_context_parts", memory.response_metadata)
        self.assert_parts(usage.peak)

    async def test_turn_stream_order_and_over_budget_context_precedes_error(self):
        for policy, failed in [(ContextBudgetPolicy(), False), (ContextBudgetPolicy(1024, 128, 128), True)]:
            assistant = self.make_assistant(GuardedChatModel(RecordingModel(), policy))
            request_context = {"user_id": 1, "route_mode": "agent"}
            events = [event async for event in assistant.chat_stream("解释磨损机理", request_context)]
            self.assertEqual([event["type"] for event in events[-2:]],
                             ["context", "error" if failed else "done"])
            info = events[-2]["context"]
            self.assertEqual(info["exceeded"], failed)
            self.assertEqual(info["model_calls"], 1)
            self.assert_parts(info)
            self.assertEqual(info["window"], policy.context_tokens)
            if failed:
                self.assertGreater(info["used"], info["input_budget"])
                assistant._store_turn_and_summarize.assert_not_called()
                sync_result = assistant.chat("解释磨损机理", request_context)
                self.assertEqual(sync_result["context"], info)

    async def test_rule_stream_has_null_usage_and_no_model_initialization(self):
        assistant = self.make_assistant()
        assistant._direct_route = Mock(return_value={"answer": "规则答案", "type": "analysis"})
        with patch.object(assistant, "_should_polish_direct_answer", return_value=False):
            events = [event async for event in assistant.chat_stream("统计换刀", {"user_id": 1})]
        self.assertEqual([event["type"] for event in events], ["meta", "chunk", "memory", "context", "done"])
        info = events[-2]["context"]
        self.assertEqual(info["kind"], "rule")
        for field in ("used", "parts", "results_raw"):
            self.assertIsNone(info[field])
        self.assertEqual(info["model_calls"], 0)
        self.assertEqual(info["paged_lists"], 0)
        self.assertEqual(info["page_requests"], 0)
        self.assertFalse(assistant.llm_runtime_ready)

    def test_history_baseline_reports_selected_memory_for_both_backends(self):
        for backend in ("legacy", "django"):
            snapshot = MemorySnapshot(scope_key="user:1", backend=backend, summary="已有摘要", messages=[
                StoredMessage(index, "human" if index % 2 else "ai", "历史内容", 12) for index in range(1, 9)
            ])
            model = RecordingToolModel(use_tool=False)
            assistant = self.make_assistant(GuardedChatModel(model, ContextBudgetPolicy(32768)), snapshot)
            assistant.memory = MemoryService(backend=backend)
            assistant.memory.history_page = Mock(return_value={"messages": snapshot.messages,
                                                              "has_more": False, "next_before_sequence": None})
            request = RequestFactory().get("/api/ai/history/")
            force_authenticate(request, user=SimpleNamespace(id=1, username="test-user", is_authenticated=True))
            with patch.object(views, "get_assistant", return_value=assistant):
                response = views.conversation_history(request)
            self.assertEqual(response.data["code"], 2000)
            info = response.data["data"]["context"]
            self.assertEqual(info["kind"], "baseline")
            self.assertEqual(info["model_calls"], 0)
            self.assertEqual(info["paged_lists"], 0)
            self.assertEqual(info["page_requests"], 0)
            self.assertEqual(info["parts"]["question"], 0)
            self.assertEqual(info["parts"]["results"], 0)
            self.assert_parts(info)
            memory = info["memory"]
            self.assertEqual(memory["included_turns"], 4)
            self.assertEqual(memory["recent_tokens"], 96)
            self.assertEqual(memory["summary_tokens"], estimate_tokens(snapshot.summary))
            self.assertEqual(memory["summary_trigger_tokens"], 1800 if backend == "django" else None)
            self.assertEqual(memory["pending_tokens"], 24 if backend == "django" else None)
            self.assertFalse(model.seen)

    def test_baseline_missing_or_invalid_model_configuration_is_null(self):
        assistant = self.make_assistant()
        assistant.memory.history_page = Mock(return_value={"messages": [], "has_more": False, "next_before_sequence": None})
        with patch("application.ai_assistant.llm_service.get_llm_config", return_value=SimpleNamespace(
            provider="deepseek", api_key="",
        )):
            self.assertIsNone(assistant.get_history("1")["context"])
        with (
            patch("application.ai_assistant.llm_service.get_llm_config", return_value=SimpleNamespace(provider="ollama")),
            patch("application.ai_assistant.llm_service.get_context_policy", side_effect=LLMProviderError("invalid budget")),
        ):
            self.assertIsNone(assistant.get_history("1")["context"])

    async def test_concurrent_requests_keep_their_own_collector(self):
        model = RecordingModel()
        assistant = self.make_assistant(GuardedChatModel(model, ContextBudgetPolicy()))

        async def request(query):
            events = [event async for event in assistant.chat_stream(query, {"user_id": 1, "route_mode": "agent"})]
            return events[-2]["context"]

        short, long = await asyncio.gather(request("解释磨损"), request("解释磨损" + "x" * 400))
        self.assertEqual(short["model_calls"], 1)
        self.assertEqual(long["model_calls"], 1)
        self.assertGreater(long["used"], short["used"])
        self.assertGreater(long["parts"]["question"], short["parts"]["question"])
        self.assertEqual(len(model.calls), 2)
        self.assertIsNone(context_usage.get())
