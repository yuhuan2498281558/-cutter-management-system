import asyncio
import json
import os
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from application.ai_assistant.context_budget import (
    ContextBudgetExceeded, ContextBudgetPolicy, GuardedChatModel,
    OutputLimitExceeded, prepare_messages, estimate_request_tokens,
)
from application.ai_assistant.context_compaction import unpack_columnar
from application.ai_assistant.llm_provider import create_chat_model, get_context_policy, LLMProviderError
from application.ai_assistant.llm_service import ToolAssistant
from application.ai_assistant.memory_service import MemorySnapshot


class RecordingModel(Runnable):
    def __init__(self, finish=None):
        self.calls = []
        self.closed = []
        self.finish = finish

    def invoke(self, input, config=None, **kwargs):
        self.calls.append((input, config, kwargs))
        return AIMessage(content="answer", response_metadata=self.finish or {})

    async def ainvoke(self, input, config=None, **kwargs):
        return self.invoke(input, config, **kwargs)

    def stream(self, input, config=None, **kwargs):
        self.calls.append((input, config, kwargs))
        try:
            yield AIMessageChunk(content="partial")
            yield AIMessageChunk(content="", response_metadata=self.finish or {})
        finally:
            self.closed.append("sync")

    async def astream(self, input, config=None, **kwargs):
        self.calls.append((input, config, kwargs))
        try:
            yield AIMessageChunk(content="partial")
            await asyncio.sleep(0)
            yield AIMessageChunk(content="", response_metadata=self.finish or {})
        finally:
            self.closed.append("async")


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class ContextBudgetTests(SimpleTestCase):
    def test_local_metadata_and_duplicate_calls_do_not_consume_budget(self):
        call = {"name": "query", "args": {"filter": "中文范围"}, "id": "one"}
        plain = AIMessage(content="", tool_calls=[call])
        annotated = plain.model_copy(deep=True)
        annotated.id = "local" * 1000
        annotated.response_metadata = {"audit": "x" * 10000}
        annotated.additional_kwargs["tool_calls"] = [{
            "id": "one", "type": "function", "function": {
                "name": "query", "arguments": json.dumps(call["args"]),
            },
        }]
        self.assertEqual(estimate_request_tokens([plain]), estimate_request_tokens([annotated]))
        base = ToolMessage(content="data", tool_call_id="one")
        local = base.model_copy(update={"artifact": "x" * 10000, "status": "error", "id": "x" * 1000})
        self.assertEqual(estimate_request_tokens([base]), estimate_request_tokens([local]))

    def test_transport_escaping_does_not_inflate_text_cost(self):
        # These contain equal numbers of non-CJK characters. JSON quoting
        # would double the backslashes, although the model receives them once.
        normal = HumanMessage(content="a" * 2000)
        escaped = HumanMessage(content="\\" * 2000)
        self.assertEqual(estimate_request_tokens([normal]), estimate_request_tokens([escaped]))
        policy = ContextBudgetPolicy(1024, 128, 128)
        self.assertEqual(prepare_messages([escaped], policy)[0].content, escaped.content)

    def test_raw_and_invalid_function_arguments_still_count_without_mutation(self):
        raw = {"name": "query", "arguments": "x" * 5000}
        messages = [
            AIMessage(content="", additional_kwargs={"function_call": raw}),
            AIMessage(content="", invalid_tool_calls=[{"name": "query", "args": "x" * 5000, "id": "bad", "error": "invalid"}]),
        ]
        for message in messages:
            before = message.model_dump()
            with self.assertRaises(ContextBudgetExceeded):
                prepare_messages([message], ContextBudgetPolicy(1024, 128, 128))
            self.assertEqual(message.model_dump(), before)
        self.assertEqual(raw["arguments"], "x" * 5000)

    def test_schemas_remain_counted_when_tool_choice_is_none(self):
        options = {"tool_choice": "none", "tools": [{"description": "x" * 5000}]}
        with self.assertRaises(ContextBudgetExceeded):
            prepare_messages([HumanMessage(content="small")], ContextBudgetPolicy(1024, 128, 128), options)

    def test_tool_protocol_reserve_counts_once_and_blocks_at_boundary(self):
        messages = [HumanMessage(content="hello")]
        for options in ({"tools": [{"name": "one"}]},
                        {"tools": [{"name": "one"}, {"name": "two"}], "tool_choice": "none"},
                        {"functions": [{"name": "legacy"}]}):
            base = estimate_request_tokens(messages, options, tool_protocol_tokens=1)
            with_reserve = estimate_request_tokens(messages, options, tool_protocol_tokens=1024)
            self.assertEqual(with_reserve - base, 1023)
            policy = ContextBudgetPolicy(with_reserve + 256 - 1, 128, 128)
            with self.assertRaises(ContextBudgetExceeded):
                prepare_messages(messages, policy, options)
        for options in ({}, {"tools": []}):
            self.assertEqual(estimate_request_tokens(messages, options, 1),
                             estimate_request_tokens(messages, options, 1024))

    def test_audio_metadata_rejected(self):
        with self.assertRaisesRegex(ValueError, "仅支持文本"):
            prepare_messages([AIMessage(content="", additional_kwargs={"audio": {"id": "audio1"}})], ContextBudgetPolicy())

    def test_all_input_components_count_before_provider(self):
        policy = ContextBudgetPolicy(1024, 128, 128)
        huge = "x" * 5000
        cases = [
            ([SystemMessage(content=huge), HumanMessage(content="small")], {}),
            ([HumanMessage(content=huge)], {}),
            ([AIMessage(content=huge), HumanMessage(content="small")], {}),
            ([ToolMessage(content=huge, tool_call_id="one")], {}),
            ([AIMessage(content="", tool_calls=[{"name": "query", "args": {"filter": huge}, "id": "one"}])], {}),
            ([HumanMessage(content="small")], {"tools": [{"description": huge}]}),
            ([HumanMessage(content="small")], {"response_format": {"description": huge}}),
        ]
        for messages, kwargs in cases:
            with self.subTest(kind=messages[0].type, options=list(kwargs)):
                model = RecordingModel()
                with self.assertRaises(ContextBudgetExceeded):
                    GuardedChatModel(model, policy).invoke(messages, **kwargs)
                self.assertEqual(model.calls, [])

    def test_compaction_preserves_messages_and_statistics(self):
        raw = json.dumps({"unit": "mm", "denominator": "known only", "rows": [
            {"normal_count": 10, "abnormal_count": 2, "unknown_count": 7,
             "wear": None, "ring": i} for i in range(150)
        ]})
        tool = ToolMessage(content=raw, tool_call_id="one", name="query", artifact={"audit": raw})
        result = prepare_messages([tool], ContextBudgetPolicy())
        self.assertEqual(unpack_columnar(result[0].content), json.loads(raw))
        self.assertEqual(tool.content, raw)
        self.assertIsNot(result[0], tool)
        self.assertEqual(result[0].tool_call_id, "one")
        self.assertEqual(result[0].artifact, tool.artifact)
        error = tool.model_copy(update={"status": "error"})
        self.assertEqual(prepare_messages([error], ContextBudgetPolicy())[0].content, raw)

    def test_non_text_inputs_fail_without_guessing_media_cost(self):
        with self.assertRaisesRegex(ValueError, "仅支持文本"):
            prepare_messages([HumanMessage(content=[{"type": "image_url", "image_url": {"url": "https://invalid"}}])], ContextBudgetPolicy())

    def test_binding_options_and_config_reach_actual_model(self):
        model = RecordingModel()
        guard = GuardedChatModel(model, ContextBudgetPolicy()).bind(stop=["END"], max_tokens=128)
        config = {"tags": ["budget-test"], "metadata": {"request": "one"}}
        guard.invoke("hello", config=config, temperature=0)
        self.assertEqual(model.calls[0][1], config)
        self.assertEqual(model.calls[0][2], {"stop": ["END"], "max_tokens": 128, "temperature": 0})

    async def test_async_options_and_streams_reach_model(self):
        model = RecordingModel()
        guard = GuardedChatModel(model, ContextBudgetPolicy())
        await guard.ainvoke("hello", stop=["END"], max_tokens=128)
        list(guard.stream("hello", stop=["END"], max_tokens=128))
        _ = [chunk async for chunk in guard.astream("hello", stop=["END"], max_tokens=128)]
        for _, _, kwargs in model.calls:
            self.assertEqual(kwargs, {"stop": ["END"], "max_tokens": 128})

    def test_output_overrides_cannot_exceed_reserve(self):
        model = RecordingModel()
        guard = GuardedChatModel(model, ContextBudgetPolicy())
        for value in (0, -1, None, True, 2049):
            for name in ("max_tokens", "max_completion_tokens", "num_predict"):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    guard.bind(**{name: value}).invoke("hello")
        for kwargs in ({"options": {"num_predict": -1}}, {"model_kwargs": {"max_tokens": 9000}}, {"num_ctx": 1}, {"extra_body": {"max_tokens": 99999}}, {"model": "another"}):
            with self.assertRaises(ValueError):
                guard.invoke("hello", **kwargs)
        self.assertEqual(model.calls, [])

    def test_completion_tokens_alias_is_capped_without_duplicate(self):
        model = RecordingModel()
        GuardedChatModel(model, ContextBudgetPolicy()).invoke("hello", max_completion_tokens=100)
        self.assertEqual(model.calls[0][2], {"max_completion_tokens": 100})

    async def test_closing_stream_propagates_immediately(self):
        model = RecordingModel()
        guard = GuardedChatModel(model, ContextBudgetPolicy())
        stream = guard.stream("hello")
        next(stream)
        stream.close()
        self.assertEqual(model.closed, ["sync"])
        stream = guard.astream("hello")
        await anext(stream)
        await stream.aclose()
        self.assertEqual(model.closed, ["sync", "async"])

    async def test_length_stop_never_returns_success(self):
        for finish in ({"finish_reason": "length"}, {"done_reason": "length"}):
            guard = GuardedChatModel(RecordingModel(finish), ContextBudgetPolicy())
            with self.assertRaises(OutputLimitExceeded):
                guard.invoke("hello")
            with self.assertRaises(OutputLimitExceeded):
                await guard.ainvoke("hello")
            with self.assertRaises(OutputLimitExceeded):
                list(guard.stream("hello"))
            with self.assertRaises(OutputLimitExceeded):
                _ = [chunk async for chunk in guard.astream("hello")]

    async def test_budget_failure_does_not_persist_or_emit_done(self):
        assistant = ToolAssistant()
        assistant._llm = GuardedChatModel(RecordingModel(), ContextBudgetPolicy(1024, 128, 128))
        snapshot = MemorySnapshot(scope_key="user:1", backend="legacy")
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._store_turn_and_summarize = Mock(return_value=snapshot)
        assistant._model_needs_tools = Mock(return_value=False)
        query = "解释概念" + "x" * 5000
        context = {"user_id": 1, "project_id": "TEST", "route_mode": "agent"}
        result = assistant.chat(query, context)
        self.assertFalse(result["success"])
        self.assertIn("上下文超过配置预算", result["error"])
        events = [event async for event in assistant.chat_stream(query, context)]
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("上下文超过配置预算", events[-1]["content"])
        self.assertNotIn("done", [event["type"] for event in events])
        assistant._store_turn_and_summarize.assert_not_called()

    async def test_truncated_answer_does_not_persist_or_emit_done(self):
        assistant = ToolAssistant()
        assistant._llm = GuardedChatModel(RecordingModel({"finish_reason": "length"}), ContextBudgetPolicy())
        snapshot = MemorySnapshot(scope_key="user:1", backend="legacy")
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._store_turn_and_summarize = Mock(return_value=snapshot)
        assistant._model_needs_tools = Mock(return_value=False)
        context = {"user_id": 1, "project_id": "TEST", "route_mode": "agent"}
        result = assistant.chat("你好", context)
        self.assertFalse(result["success"])
        self.assertIn("达到输出上限", result["error"])
        events = [event async for event in assistant.chat_stream("你好", context)]
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("达到输出上限", events[-1]["content"])
        self.assertNotIn("done", [event["type"] for event in events])
        assistant._store_turn_and_summarize.assert_not_called()

    async def test_guarded_agent_preserves_argument_recovery(self):
        assistant = ToolAssistant()
        assistant._llm = GuardedChatModel(ToolModel(responses=[
            AIMessage(content="", tool_calls=[{"name": "tool_query_tool_change_data", "args": {"ring_range": [200, 100]}, "id": "bad"}]),
            AIMessage(content="", tool_calls=[{"name": "tool_query_tool_change_data", "args": {"ring_range": [100, 200]}, "id": "fixed"}]),
            AIMessage(content="100至200环共3条记录。"),
        ]), ContextBudgetPolicy())
        snapshot = MemorySnapshot(scope_key="user:1", backend="legacy")
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._store_turn_and_summarize = Mock(return_value=snapshot)
        with patch("application.ai_assistant.llm_service.query_tool_change_data", return_value=json.dumps({"total_records": 3})) as query:
            events = [event async for event in assistant.chat_stream(
                "查询100至200环换刀记录", {"user_id": 1, "project_id": "TEST", "route_mode": "agent"},
            )]
        self.assertEqual(events[-1]["type"], "done", events)
        self.assertEqual(query.call_count, 1)
        self.assertEqual(json.loads(query.call_args.args[0])["ring_range"], [100, 200])
        assistant._store_turn_and_summarize.assert_called_once()

    async def test_guarded_agent_truncation_cannot_be_saved(self):
        assistant = ToolAssistant()
        assistant._llm = GuardedChatModel(ToolModel(responses=[
            AIMessage(content="", tool_calls=[{"name": "tool_query_tool_change_data", "args": {}, "id": "one"}]),
            AIMessage(content="部分答案", response_metadata={"finish_reason": "length"}),
        ]), ContextBudgetPolicy())
        snapshot = MemorySnapshot(scope_key="user:1", backend="legacy")
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._store_turn_and_summarize = Mock(return_value=snapshot)
        with patch("application.ai_assistant.llm_service.query_tool_change_data", return_value=json.dumps({"total_records": 3})):
            events = [event async for event in assistant.chat_stream(
                "查询换刀记录", {"user_id": 1, "project_id": "TEST", "route_mode": "agent"},
            )]
        self.assertEqual(events[-1]["type"], "error", events)
        self.assertIn("达到输出上限", events[-1]["content"])
        self.assertNotIn("done", [event["type"] for event in events])
        assistant._store_turn_and_summarize.assert_not_called()


class ContextPolicyTests(SimpleTestCase):
    def test_invalid_policy_rejected(self):
        for kwargs in ({"context_tokens": 100}, {"output_tokens": 0}, {"safety_margin_tokens": -1}, {"compaction_min_tokens": True}):
            with self.assertRaises(ValueError):
                ContextBudgetPolicy(**kwargs)

    @override_settings(AI_LLM_PROVIDER="deepseek", AI_CONTEXT_WINDOW_TOKENS=8192)
    def test_environment_overrides_django_settings(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_context_policy().context_tokens, 8192)
            with patch.dict(os.environ, {"AI_CONTEXT_WINDOW_TOKENS": "4096"}):
                self.assertEqual(get_context_policy().context_tokens, 4096)

    def test_tool_protocol_reserve_configuration(self):
        with patch.dict(os.environ, {"AI_CONTEXT_TOOL_PROTOCOL_TOKENS": "2048"}, clear=True):
            self.assertEqual(get_context_policy().tool_protocol_tokens, 2048)
            for value in ("0", "-1", "invalid"):
                with patch.dict(os.environ, {"AI_CONTEXT_TOOL_PROTOCOL_TOKENS": value}):
                    with self.assertRaises(LLMProviderError):
                        get_context_policy()

    def test_ollama_limits_and_invalid_configuration(self):
        with patch.dict(os.environ, {"AI_LLM_PROVIDER": "ollama", "OLLAMA_NUM_CTX": "8192"}, clear=True):
            self.assertEqual(get_context_policy().context_tokens, 8192)
            self.assertEqual(get_context_policy().output_tokens, 1024)
            for value in ("abc", "99999", "100"):
                with patch.dict(os.environ, {"AI_CONTEXT_WINDOW_TOKENS": value}):
                    with self.assertRaises(LLMProviderError):
                        get_context_policy()

    def test_openai_factory_enforces_output_cap(self):
        with patch.dict(os.environ, {"AI_LLM_PROVIDER": "openai", "AI_LLM_API_KEY": "test-not-a-secret", "AI_CONTEXT_OUTPUT_TOKENS": "512"}, clear=True):
            with patch("langchain_openai.ChatOpenAI", return_value=RecordingModel()) as factory:
                guard = create_chat_model()
            self.assertIsInstance(guard, GuardedChatModel)
            self.assertEqual(factory.call_args.kwargs["max_tokens"], 512)
            guard.invoke("hello")
            self.assertEqual(guard.model.calls[0][2]["max_tokens"], 512)

    def test_ollama_actual_request_shape_no_top_level_num_predict(self):
        with patch.dict(os.environ, {"AI_LLM_PROVIDER": "ollama"}, clear=True):
            guard = create_chat_model()
        prepared, options = guard._prepare_call("hello", {})
        params = guard.model._chat_params(prepared, **options)
        self.assertNotIn("num_predict", params)
        self.assertEqual(params["options"].num_predict, guard.policy.output_tokens)
        self.assertEqual(params["options"].num_ctx, 4096)
        with self.assertRaises(ValueError):
            guard.invoke("hello", num_predict=128)

    def test_actual_openai_and_compatible_payload_caps(self):
        for provider in ("openai", "deepseek", "api", "openai-compatible"):
            with self.subTest(provider=provider), patch.dict(os.environ, {
                "AI_LLM_PROVIDER": provider, "AI_LLM_API_KEY": "test-not-a-secret",
                "AI_LLM_BASE_URL": "http://test.invalid/v1",
            }, clear=True):
                guard = create_chat_model()
                prepared, options = guard._prepare_call("hello", {})
                payload = guard.model._get_request_payload(prepared, **options)
            key = "max_completion_tokens" if provider == "openai" else "max_tokens"
            other = "max_tokens" if provider == "openai" else "max_completion_tokens"
            self.assertEqual(payload[key], guard.policy.output_tokens)
            self.assertNotIn(other, payload)
