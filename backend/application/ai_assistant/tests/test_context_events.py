import copy
from hashlib import sha256
import json
import os
import sqlite3
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from django.test import SimpleTestCase
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage, convert_to_openai_messages
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool
from sqlalchemy import func, select

from application.ai_assistant.context_budget import ContextBudgetPolicy, ContextUsage, GuardedChatModel, context_usage
from application.ai_assistant.context_events import ContextEventStore
from application.ai_assistant.llm_provider import create_chat_model
from application.ai_assistant.llm_service import SYSTEM_PROMPT, ToolAssistant
from application.ai_assistant.memory_service import MemoryService
from application.ai_assistant.tests.test_context_budget_agent import RecordingToolModel, trend_payload


RAW = ' { "summary": "原始结果", "count": 3, "missing": null }\n'
ARGUMENTS = '{ "label": "中文", "page": 1 }'
PROVIDER_USAGE = {"prompt_tokens": 15000, "completion_tokens": 24, "prompt_cache_hit_tokens": 12000}


class ConversationModel(RecordingToolModel):
    mode: str = "tools"
    with_usage: bool = True
    output_limited: bool = False
    arguments: str = ARGUMENTS

    def _response(self, messages):
        self.seen.append(copy.deepcopy(messages))
        current = messages[max(i for i, message in enumerate(messages) if isinstance(message, HumanMessage)) + 1:]
        if self.mode == "fail":
            raise RuntimeError("offline model failure")
        if self.mode == "tools" and not any(isinstance(message, ToolMessage) for message in current):
            calls = [{"id": f"call-{len(self.seen)}-{i}", "type": "function", "function": {
                "name": "tool_query_tool_change_trend", "arguments": self.arguments,
            }} for i in range(2)]
            response = AIMessage(content="", additional_kwargs={"tool_calls": calls})
        else:
            response = AIMessage(content="根据已有结果，共3条，缺失值未知。")
        response.response_metadata = {"model_name": "offline-actual", "finish_reason": "length" if self.output_limited else "stop"}
        if self.with_usage:
            response.response_metadata["token_usage"] = dict(PROVIDER_USAGE)
            response.usage_metadata = {"input_tokens": 15000, "output_tokens": 24, "total_tokens": 15024}
        return response

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        response = self._response(messages)
        metadata = dict(response.response_metadata)
        raw_usage = metadata.pop("token_usage", None)
        yield ChatGenerationChunk(message=AIMessageChunk(
            content=response.content, additional_kwargs=response.additional_kwargs,
            tool_calls=response.tool_calls, response_metadata=metadata,
        ))
        if raw_usage:
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="", usage_metadata=response.usage_metadata,
                response_metadata={"token_usage": raw_usage},
            ))


class ContextEventTests(SimpleTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.env = patch.dict(os.environ, {"AI_MEMORY_DUAL_WRITE": "0", "AI_ABLATE_MEMORY": "0"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.memory = MemoryService(backend="legacy")
        self.memory.history_db_url = "sqlite:///" + (Path(temporary.name) / "history.sqlite").as_posix()
        self.addCleanup(self.memory.close)
        self.model = ConversationModel()
        self.guard = GuardedChatModel(self.model, ContextBudgetPolicy(), provider="deepseek", model_name="offline-requested")
        self.tool = StructuredTool.from_function(
            lambda label="", page=1, ring_range=None, tool_type="": RAW,
            name="tool_query_tool_change_trend", description="Read exact statistics.",
        )
        self.options = {"user_id": "event-test", "project_id": "P1", "route_mode": "agent"}
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT), MessagesPlaceholder("chat_history"),
            ("human", "{input}"), MessagesPlaceholder("agent_scratchpad"),
        ])
        executor = AgentExecutor(agent=create_tool_calling_agent(self.guard, [self.tool], prompt),
                                 tools=[self.tool], return_intermediate_steps=True, max_iterations=3)
        self.assistant = ToolAssistant()
        self.assistant.memory = self.memory
        self.assistant._llm = self.guard
        self.assistant._get_executor_for_query = Mock(return_value=executor)
        self.assistant._model_needs_tools = Mock(return_value=True)

    def snapshot(self):
        return self.memory.load(self.memory.scope_key("event-test"))

    def ask(self, query="查询100到200环滚刀", **context):
        result = self.assistant.chat(query, {**self.options, **context})
        self.assertTrue(result["success"], result)
        return result

    def test_all_turns_replay_raw_protocol_and_keep_prefix_after_three_turns(self):
        for index in range(5):
            self.ask(f"查询第{index + 1}项")
        snapshot = self.snapshot()
        history, stats, _ = self.memory.protocol_history(snapshot, "P1")
        self.assertEqual(stats["turns"], 5)
        self.assertEqual(stats["tool_results"], 10)
        self.assertEqual(len(history), 25)
        self.assertEqual(len(snapshot.messages), 10)
        for turn in snapshot.context_events:
            payloads = [json.loads(event["payload"]) for event in turn["events"] if event["kind"] == "message"]
            self.assertEqual(len(payloads), 5)
            self.assertEqual(payloads[1]["message"]["data"]["additional_kwargs"]["tool_calls"][0]["function"]["arguments"], ARGUMENTS)
            for payload in payloads[2:4]:
                self.assertEqual(payload["message"]["data"]["content"], RAW)
                self.assertEqual(payload["sha256"], sha256(RAW.encode("utf-8")).hexdigest())
        for index in range(4):
            previous = self.model.seen[index * 2 + 1]
            following = self.model.seen[(index + 1) * 2]
            self.assertEqual(convert_to_openai_messages(following[:len(previous)]), convert_to_openai_messages(previous))
        self.model.mode = "answer"
        result = self.ask("请解释它的含义")
        self.assertEqual(result["memory"]["context_mode"], "new")
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["context"]["history"]["turns"], 5)
        self.assertEqual(result["context"]["model_calls"], 1)
        self.assertEqual(sum(isinstance(message, ToolMessage) for message in self.model.seen[-1]), 10)

    def test_cleared_slots_remain_cleared_with_full_history(self):
        self.ask()
        self.assertEqual(self.snapshot().slots["tool_type"], "DISC")
        self.ask("取消刀型限制")
        self.assertNotIn("tool_type", self.snapshot().slots)
        self.ask("同样范围继续解释")
        self.assertNotIn("tool_type", self.snapshot().slots)
        current = next(message.content for message in reversed(self.model.seen[-1]) if isinstance(message, HumanMessage))
        self.assertNotIn("刀具类型：DISC", current)
        self.assertIn("不得从历史恢复已清除", current)

    def test_large_tool_results_are_saved_before_lossless_encoding(self):
        raw = " \n" + trend_payload() + "\n"
        with patch(__name__ + ".RAW", raw):
            self.ask()
        prepared = [message for message in self.model.seen[-1] if isinstance(message, ToolMessage)]
        self.assertTrue(all(message.content != raw for message in prepared))
        history, _, _ = self.memory.protocol_history(self.snapshot(), "P1")
        self.assertEqual([message.content for message in history if isinstance(message, ToolMessage)], [raw, raw])

    async def test_direct_chat_also_commits_enriched_input_and_usage(self):
        self.assistant._model_needs_tools = Mock(return_value=False)
        self.model.mode = "answer"
        self.ask("什么是滚刀")
        events = [event async for event in self.assistant.chat_stream("谢谢", self.options)]
        self.assertEqual(events[-1]["type"], "done", events)
        history, stats, anchor = self.memory.protocol_history(self.snapshot(), "P1")
        self.assertEqual(stats["turns"], 2)
        self.assertEqual(stats["tool_results"], 0)
        self.assertTrue(history[0].content.startswith("【当前上下文】当前项目ID：P1"))
        self.assertTrue(history[0].content.endswith("什么是滚刀"))
        self.assertEqual(anchor["prompt_tokens"], 15000)

    def test_other_project_gets_qa_warning_without_tool_evidence(self):
        self.ask()
        history, stats, _ = self.memory.protocol_history(self.snapshot(), "P2")
        self.assertEqual(len(history), 2)
        self.assertTrue(history[0].content.startswith("（以下为项目 P1 的对话，结果不能作为当前项目的证据）\n"))
        self.assertEqual(history[0].content.split("\n")[-1], "查询100到200环滚刀")
        self.assertEqual(stats["other_project_turns"], 1)
        self.assertEqual(stats["tool_results"], 0)
        self.model.mode = "answer"
        result = self.assistant.chat("解释结果", {**self.options, "project_id": "P2"})
        self.assertFalse(result["success"])
        self.assertEqual(self.snapshot().message_count, 2)

    def test_legacy_qa_and_rule_turns_do_not_invent_evidence(self):
        self.memory.append_turn(self.memory.scope_key("event-test"), "旧问题", "旧回答")
        self.assistant._direct_route = Mock(return_value={"answer": "规则回答", "type": "analysis"})
        self.assistant._should_polish_direct_answer = Mock(return_value=False)
        self.ask("规则问题", route_mode="rule")
        snapshot = self.snapshot()
        self.assertEqual(snapshot.context_events, [])
        history, stats, anchor = self.memory.protocol_history(snapshot, "P1")
        self.assertEqual([message.content for message in history], ["旧问题", "旧回答", "规则问题", "规则回答"])
        self.assertEqual(stats["legacy_qa_turns"], 2)
        self.assertIsNone(anchor)

    def test_broken_pairs_or_hash_fall_back_to_qa(self):
        self.ask()
        for damage in ("missing", "duplicate", "hash"):
            snapshot = self.snapshot()
            events = snapshot.context_events[0]["events"]
            if damage == "missing":
                events.pop(2)
            elif damage == "duplicate":
                payload = json.loads(events[1]["payload"])
                calls = payload["message"]["data"]["additional_kwargs"]["tool_calls"]
                calls[1]["id"] = calls[0]["id"]
                events[1]["payload"] = json.dumps(payload)
            else:
                payload = json.loads(events[2]["payload"])
                payload["sha256"] = "bad"
                events[2]["payload"] = json.dumps(payload)
            with self.assertLogs("application.ai_assistant.context_events", "WARNING"):
                history, stats, anchor = self.memory.protocol_history(snapshot, "P1")
            self.assertEqual([message.content for message in history], [snapshot.messages[0].content, snapshot.messages[1].content])
            self.assertEqual(stats["tool_results"], 0)
            self.assertIsNone(anchor)

    def test_commit_failure_rolls_back_messages_events_and_slots(self):
        self.snapshot()
        with self.memory._get_legacy_engine().begin() as connection:
            connection.exec_driver_sql("""CREATE TRIGGER reject_commit BEFORE INSERT ON ai_context_events
                WHEN NEW.kind = 'turn_commit' BEGIN SELECT RAISE(FAIL, 'reject commit'); END""")
        result = self.assistant.chat("查询100到200环滚刀", self.options)
        self.assertFalse(result["success"])
        snapshot = self.snapshot()
        self.assertEqual((snapshot.message_count, snapshot.slots, snapshot.context_events), (0, {}, []))

    def test_reset_deletes_events_and_rejects_stale_generation(self):
        self.ask()
        old = self.snapshot()
        self.memory.append_turn("experiment:other", "其他", "回答", context_messages=ContextEventStore.turn_messages("其他", "回答"))
        self.assistant.reset_memory("event-test")
        stale = self.memory.append_turn(old.scope_key, "迟到", "回答", expected_generation=old.generation,
                                        context_messages=ContextEventStore.turn_messages("迟到", "回答"))
        self.assertEqual((stale.message_count, stale.context_events), (0, []))
        self.assertGreater(stale.generation, old.generation)
        self.assertTrue(self.memory.load("experiment:other").context_events)
        self.memory.reset()
        with self.memory._get_legacy_engine().connect() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(ContextEventStore.table)), 0)

    async def test_failed_interrupted_and_length_limited_turns_never_commit(self):
        self.model.mode = "fail"
        self.assertFalse(self.assistant.chat("查询", self.options)["success"])
        events = [event async for event in self.assistant.chat_stream("查询", self.options)]
        self.assertEqual(events[-1]["type"], "error")
        self.model.mode = "tools"
        stream = self.assistant.chat_stream("查询", self.options)
        while (await anext(stream))["type"] != "chunk":
            pass
        await stream.aclose()
        self.model.output_limited = True
        events = [event async for event in self.assistant.chat_stream("查询", self.options)]
        self.assertEqual(events[-1]["type"], "error")
        self.assistant._model_needs_tools = Mock(return_value=False)
        self.guard.policy = ContextBudgetPolicy(1024, 128, 128)
        events = [event async for event in self.assistant.chat_stream("查询", self.options)]
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("上下文超过配置预算", events[-1]["content"])
        self.assertEqual(self.snapshot().context_events, [])
        self.assertEqual(self.snapshot().message_count, 0)

    async def test_usage_tail_counted_once_and_history_allows_tool_free_stream(self):
        events = [event async for event in self.assistant.chat_stream("查询", self.options)]
        self.assertEqual(events[-1]["type"], "done", events)
        info = events[-2]["context"]
        self.assertEqual(info["measurement"], "actual")
        self.assertEqual(info["used"], 15000)
        self.assertEqual(info["last_prompt_tokens_actual"], 15000)
        self.assertEqual(info["provider_usage"], {"prompt_tokens": 30000, "completion_tokens": 48, "cache_hit_tokens": 24000})
        _, _, anchor = self.memory.protocol_history(self.snapshot(), "P1")
        self.assertEqual(anchor["prompt_tokens"], 15000)
        self.assertEqual(anchor["model"], "offline-actual")
        self.assertEqual(len(anchor["calls"]), 2)
        self.model.mode = "answer"
        events = [event async for event in self.assistant.chat_stream("请解释它", self.options)]
        self.assertEqual(events[-1]["type"], "done", events)
        self.assertTrue(any(event["type"] == "chunk" for event in events))
        self.assertEqual(events[-2]["context"]["model_calls"], 1)
        self.assistant.reset_memory("event-test")
        events = [event async for event in self.assistant.chat_stream("请解释它", self.options)]
        self.assertEqual(events[-1]["type"], "error")
        self.assertFalse(any(event["type"] == "chunk" for event in events))

    def test_baseline_uses_anchor_and_invalidates_changed_fingerprints(self):
        result = self.ask()
        with patch("application.ai_assistant.llm_service.TOOLS", [self.tool]):
            baseline = self.assistant.get_history("event-test", project_id="P1")["context"]
            _, _, anchor = self.memory.protocol_history(self.snapshot(), "P1")
            self.assertEqual(baseline["used"], 15000 + sum(baseline["parts"].values()) - anchor["request_estimate"])
            self.assertEqual(baseline["measurement"], "estimated")
            self.assertEqual(baseline["last_prompt_tokens_actual"], 15000)
            self.assertIsNone(baseline["provider_usage"])
            for field, value in (("model_name", "changed-model"), ("provider", "changed-provider")):
                with patch.object(self.guard, field, value):
                    changed = self.assistant.get_history("event-test", project_id="P1")["context"]
                self.assertEqual(changed["used"], sum(changed["parts"].values()))
            with patch("application.ai_assistant.llm_service.SYSTEM_PROMPT", "changed-system"):
                changed = self.assistant.get_history("event-test", project_id="P1")["context"]
                self.assertEqual(changed["used"], sum(changed["parts"].values()))
        changed = self.assistant.get_history("event-test", project_id="P1")["context"]
        self.assertEqual(changed["used"], sum(changed["parts"].values()))
        self.assertEqual(result["context"]["schema_version"], 2)

    def test_absent_usage_stays_unknown(self):
        self.model.with_usage = False
        result = self.ask()
        self.assertIsNone(result["context"]["provider_usage"])
        self.assertIsNone(result["context"]["last_prompt_tokens_actual"])
        self.assertEqual(result["context"]["measurement"], "estimated")
        _, _, anchor = self.memory.protocol_history(self.snapshot(), "P1")
        self.assertIsNone(anchor["prompt_tokens"])

    async def test_compatible_provider_preserves_deepseek_usage_tail(self):
        with patch.dict(os.environ, {"AI_LLM_PROVIDER": "deepseek", "AI_LLM_MODEL": "offline-requested",
                                    "AI_LLM_API_KEY": "offline-test", "AI_LLM_BASE_URL": "http://test.invalid/v1"}, clear=True):
            guard = create_chat_model()
        self.assertTrue(guard.model.stream_usage)
        chunk = guard.model._convert_chunk_to_generation_chunk(
            {"choices": [], "usage": dict(PROVIDER_USAGE)}, AIMessageChunk, None,
        )
        self.assertEqual(chunk.message.response_metadata["token_usage"], PROVIDER_USAGE)
        self.assertEqual(chunk.message.usage_metadata["input_tokens"], 15000)
        chunks = [
            {"choices": [{"delta": {"role": "assistant", "content": "回答"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}], "model": "offline-actual"},
            {"choices": [], "usage": dict(PROVIDER_USAGE)},
        ]
        for asynchronous in (False, True):
            response = MagicMock()
            response.__enter__.return_value = response
            response.__aenter__.return_value = response
            response.__iter__.return_value = iter(chunks)
            response.__aiter__.return_value = chunks
            usage = ContextUsage()
            token = context_usage.set(usage)
            try:
                if asynchronous:
                    with patch.object(guard.model.async_client, "create", AsyncMock(return_value=response)) as create:
                        _ = [item async for item in guard.astream("问题")]
                else:
                    with patch.object(guard.model.client, "create", return_value=response) as create:
                        list(guard.stream("问题"))
                self.assertEqual(create.call_args.kwargs["stream_options"], {"include_usage": True})
                self.assertEqual(create.call_args.kwargs["max_tokens"], 8192)
                self.assertEqual(usage.provider_usage, {"prompt_tokens": 15000, "completion_tokens": 24, "cache_hit_tokens": 12000})
                self.assertEqual(len(usage.calls), 1)
                self.assertEqual(usage.event()["model"], "offline-actual")
            finally:
                context_usage.reset(token)

    def queried(self, query, **arguments):
        self.model.mode = "tools"
        self.model.arguments = json.dumps(arguments)
        self.ask(query)
        self.model.mode = "answer"

    def test_history_answers_only_what_an_earlier_query_covers(self):
        self.queried("查询100到200环换刀情况", ring_range=[100, 200])
        for query in ("查询120到150环换刀情况", "为什么换得这么多", "查询100到200环刮刀换刀情况"):
            result = self.assistant.chat(query, self.options)
            self.assertTrue(result["success"], (query, result))
            self.assertEqual(result["context"]["model_calls"], 1, query)
        turns = self.snapshot().message_count
        for query in ("查询300到400环换刀情况", "全部环段的换刀情况", "最新的换刀情况"):
            result = self.assistant.chat(query, self.options)
            self.assertFalse(result["success"], query)
        self.assertEqual(self.snapshot().message_count, turns)

    def test_history_with_another_tool_type_does_not_cover(self):
        self.queried("查询100到200环滚刀换刀情况", ring_range=[100, 200], tool_type="DISC")
        self.assertFalse(self.assistant.chat("查询100到200环刮刀换刀情况", self.options)["success"])
        self.assertTrue(self.assistant.chat("查询100到200环滚刀换刀情况", self.options)["success"])

    async def test_stream_requires_a_query_for_a_new_range(self):
        self.queried("查询100到200环换刀情况", ring_range=[100, 200])
        events = [event async for event in self.assistant.chat_stream("查询300到400环换刀情况", self.options)]
        self.assertEqual(events[-1]["type"], "error", events)
        self.assertFalse(any(event["type"] == "chunk" for event in events))
        events = [event async for event in self.assistant.chat_stream("查询120到150环换刀情况", self.options)]
        self.assertEqual(events[-1]["type"], "done", events)
        memory = next(event for event in events if event["type"] == "memory")
        self.assertEqual(memory["turn_sequences"], [item.sequence for item in self.snapshot().messages[-2:]])

    def test_load_reads_without_holding_the_write_lock(self):
        self.ask()
        database = self.memory._get_legacy_engine().url.database
        original = ContextEventStore.load
        acquired = []

        def load_while_another_writer_starts(connection, scope_key, generation):
            other = sqlite3.connect(database, timeout=0)
            try:
                other.execute("BEGIN IMMEDIATE")
                acquired.append(True)
                other.rollback()
            finally:
                other.close()
            return original(connection, scope_key, generation)

        with patch.object(ContextEventStore, "load", side_effect=load_while_another_writer_starts):
            snapshot = self.snapshot()
        self.assertEqual(acquired, [True])
        self.assertEqual(snapshot.message_count, 2)

    def test_full_history_asks_for_a_reset_instead_of_a_smaller_range(self):
        self.memory.append_turn(self.memory.scope_key("event-test"), "旧问题", "长" * 300000)
        self.model.mode = "answer"
        for context_mode in ("auto", "new"):
            result = self.assistant.chat("你好", {**self.options, "context_mode": context_mode})
            self.assertFalse(result["success"])
            self.assertIn("对话历史已超过模型上下文上限，本次未生成回答。请点「重置对话」清空历史后再问。", result["error"])
        self.assistant.reset_memory("event-test")
        self.assistant._model_needs_tools = Mock(return_value=False)
        self.assertTrue(self.assistant.chat("你好", self.options)["success"])
