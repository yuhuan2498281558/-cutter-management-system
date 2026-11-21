import copy
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
import sqlite3
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

import httpx
from asgiref.sync import sync_to_async
from django.test import SimpleTestCase, TestCase, RequestFactory
from rest_framework.test import force_authenticate
from application.ai_assistant.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage, convert_to_openai_messages
from application.ai_assistant.agent_loop import AgentPrompt
from application.ai_assistant.tests.test_tooling import make_tool
from sqlalchemy import func, select

from application.ai_assistant.context_budget import ContextBudgetPolicy, ContextUsage, GuardedChatModel, context_usage
from application.ai_assistant.context_events import ContextEventStore
from application.ai_assistant.history_access import access_stamp, authorized_snapshot
from application.ai_assistant import views
from application.ai_assistant.llm_provider import create_chat_model
from application.ai_assistant.llm_service import SYSTEM_PROMPT, ToolAssistant
from application.ai_assistant.memory_service import MemoryService, MemorySnapshot, StoredMessage
from application.shield.analysis_metrics import ANALYSIS_REQUEST
from application.shield.models import ProjectInfo
from dvadmin.system.models import Dept, Menu, MenuButton, Role, RoleMenuButtonPermission, Users
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
        yield AIMessageChunk(
            content=response.content, additional_kwargs=response.additional_kwargs,
            tool_calls=response.tool_calls, response_metadata=metadata,
        )
        if raw_usage:
            yield AIMessageChunk(
                content="", usage_metadata=response.usage_metadata,
                response_metadata={"token_usage": raw_usage},
            )


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
        self.tool = make_tool(
            lambda label="", page=1, ring_range=None, tool_type="": RAW,
            name="tool_query_tool_change_trend", description="Read exact statistics.",
        )
        self.options = {"user_id": "event-test", "project_id": "P1", "route_mode": "agent"}
        prompt = AgentPrompt(SYSTEM_PROMPT)
        self.assistant = ToolAssistant()
        self.assistant.memory = self.memory
        self.assistant._llm = self.guard
        self.assistant._prompt = prompt
        self.assistant._get_tools_for_query = Mock(return_value=[self.tool])
        self.assistant._model_needs_tools = Mock(return_value=True)

    def snapshot(self):
        return self.memory.load(self.memory.scope_key("event-test"))

    def ask(self, query="查询100到200环滚刀", **context):
        # 派生的异步测试也复用此夹具，同步入口在没有事件循环的线程中运行。
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(self.assistant.chat, query, {**self.options, **context}).result()
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

    def test_other_project_is_not_replayed_or_used_as_evidence(self):
        self.ask()
        history, stats, _ = self.memory.protocol_history(self.snapshot(), "P2")
        self.assertEqual(history, [])
        self.assertEqual(stats["other_project_turns"], 1)
        self.assertEqual(stats["tool_results"], 0)
        self.model.mode = "answer"
        result = self.assistant.chat("解释结果", {**self.options, "project_id": "P2"})
        self.assertFalse(result["success"])
        self.assertEqual(self.snapshot().message_count, 2)
        self.assertNotIn("P1", str(convert_to_openai_messages(self.model.seen[-1])))

    def test_project_switch_filters_model_history_and_history_pages(self):
        self.ask("P1的独有问题")
        self.ask("P2的独有问题", project_id="P2")
        self.assertNotIn("P1", str(convert_to_openai_messages(self.model.seen[-1])))
        for project in ("P2", "P1"):
            page = self.assistant.get_history("event-test", project_id=project)
            self.assertEqual([item["content"] for item in page["messages"] if item["role"] == "user"],
                             [f"{project}的独有问题"])
            self.assertEqual(page["context"]["history"]["other_project_turns"], 1)
        self.ask("P1的第二问")
        self.assertNotIn("P2", str(convert_to_openai_messages(self.model.seen[-1])))
        page = self.assistant.get_history("event-test", project_id="P1", limit=2)
        earlier = self.assistant.get_history("event-test", project_id="P1", limit=2,
                                             before_sequence=page["next_before_sequence"])
        self.assertTrue(page["has_more"])
        self.assertFalse(earlier["has_more"])
        self.assertIsNone(earlier["next_before_sequence"])
        self.assertEqual([item["sequence"] for item in earlier["messages"] + page["messages"]],
                         [item.sequence for item in self.snapshot().messages if item.sequence not in (3, 4)])

    def test_changed_scope_withholds_history_slots_and_evidence(self):
        self.ask("旧范围100到200环滚刀换刀情况")
        self.assertTrue(self.snapshot().slots)
        self.assertEqual(authorized_snapshot(self.snapshot(), "P1", "narrower-scope").slots, {})
        with patch("application.ai_assistant.llm_service.access_stamp", return_value="narrower-scope"):
            page = self.assistant.get_history("event-test", project_id="P1")
            self.assertEqual(page["messages"], [])
            self.assertEqual(page["memory"]["active_slots"], {})
            self.assertEqual(page["context"]["history"]["other_project_turns"], 1)
            self.model.mode = "answer"
            result = self.assistant.chat("为什么换得这么多", self.options)
            self.assertFalse(result["success"])
            request = str(convert_to_openai_messages(self.model.seen[-1][1:]))
            for forbidden in ("旧范围", "100", "DISC", "原始结果"):
                self.assertNotIn(forbidden, request)
            self.model.mode = "tools"
            self.ask("新范围问题")
            self.assertEqual(len(self.assistant.get_history("event-test", project_id="P1")["messages"]), 2)

    def test_unstamped_or_unidentified_turns_never_reach_model_or_page(self):
        for metadata in ({}, {"project_id": "P1"}, {"access_stamp": access_stamp("P1")}):
            self.memory.append_turn(self.snapshot().scope_key, "未标记旧问题", "未标记旧答案", metadata=metadata,
                                    slots={"ring_range": [100, 200], "tool_type": "DISC"})
        page = self.assistant.get_history("event-test", project_id="P1")
        self.assertEqual(page["messages"], [])
        self.assertEqual(page["memory"]["active_slots"], {})
        self.assertEqual(page["context"]["history"]["other_project_turns"], 3)
        self.ask("新问题", context_mode="continue")
        self.assertNotIn("未标记", str(convert_to_openai_messages(self.model.seen[-1])))
        self.assertEqual(self.snapshot().slots, {})

    def test_foreign_checkpoints_do_not_hide_authorized_turns(self):
        self.ask()
        for project, stamp in (("P2", access_stamp("P2")), ("P1", "old-scope")):
            self.memory.append_compaction(self.snapshot(), project, {
                "mode": "checkpoint", "through_sequence": self.snapshot().last_sequence,
                "summary": "不应出现的摘要", "access_stamp": stamp,
            })
        full = self.snapshot()
        filtered = authorized_snapshot(full, "P1", access_stamp("P1"))
        self.assertEqual((filtered.message_count, filtered.latest_sequence, filtered.generation),
                         (full.message_count, full.latest_sequence, full.generation))
        history, stats, _ = self.memory.protocol_history(filtered, "P1")
        self.assertEqual((stats["turns"], stats["summarized_turns"], stats["tool_results"]), (1, 0, 2))
        self.assertNotIn("不应出现的摘要", str(convert_to_openai_messages(history)))
        self.assertEqual(ContextEventStore.compactions(filtered.context_events), [])
        self.model.mode = "answer"
        self.ask("为什么换得这么多")
        self.assertNotIn("不应出现的摘要", str(convert_to_openai_messages(self.model.seen[-1])))

    def test_legacy_qa_and_rule_turns_do_not_invent_evidence(self):
        self.memory.append_turn(self.memory.scope_key("event-test"), "旧问题", "旧回答")
        self.assistant._direct_route = Mock(return_value={"answer": "规则回答", "type": "analysis"})
        self.assistant._should_polish_direct_answer = Mock(return_value=False)
        self.ask("规则问题", route_mode="rule")
        snapshot = self.snapshot()
        self.assertEqual(snapshot.context_events, [])
        history, stats, anchor = self.memory.protocol_history(authorized_snapshot(snapshot, "P1", access_stamp("P1")), "P1")
        self.assertEqual([message.content for message in history], ["规则问题", "规则回答"])
        self.assertEqual(stats["legacy_qa_turns"], 1)
        self.assertEqual(stats["other_project_turns"], 1)
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
        self.assertFalse((await sync_to_async(self.assistant.chat)("查询", self.options))["success"])
        self.assertEqual(len(self.model.seen), 1)
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
        chunks = [
            {"choices": [{"delta": {"role": "assistant", "content": "回答"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}], "model": "offline-actual"},
            {"choices": [], "usage": dict(PROVIDER_USAGE)},
        ]
        requests = []

        def respond(request):
            requests.append(json.loads(request.content))
            body = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode("utf-8"))

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as async_client:
                guard.model.http_client, guard.model.http_async_client = client, async_client
                for asynchronous in (False, True):
                    usage = ContextUsage()
                    token = context_usage.set(usage)
                    try:
                        if asynchronous:
                            received = [item async for item in guard.astream("问题")]
                        else:
                            received = list(guard.stream("问题"))
                        self.assertEqual(received[-1].response_metadata["token_usage"], {
                            **PROVIDER_USAGE, "total_tokens": None,
                            "prompt_tokens_details": None, "completion_tokens_details": None,
                        })
                        self.assertEqual(received[-1].usage_metadata["input_tokens"], 15000)
                        self.assertEqual(requests[-1]["stream_options"], {"include_usage": True})
                        self.assertEqual(requests[-1]["max_tokens"], 8192)
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
        for query in ("查询100到200环换刀情况", "为什么换得这么多"):
            result = self.assistant.chat(query, self.options)
            self.assertTrue(result["success"], (query, result))
            self.assertEqual(result["context"]["model_calls"], 1, query)
        turns = self.snapshot().message_count
        for query in ("查询120到150环换刀情况", "查询100到200环刮刀换刀情况", "查询100到200环换刀趋势",
                      "查询300到400环换刀情况", "全部环段的换刀情况", "最新的换刀情况"):
            result = self.assistant.chat(query, self.options)
            self.assertFalse(result["success"], query)
        self.assertEqual(self.snapshot().message_count, turns)

    def test_history_with_another_tool_type_does_not_cover(self):
        self.queried("查询100到200环滚刀换刀情况", ring_range=[100, 200], tool_type="DISC")
        self.assertFalse(self.assistant.chat("查询100到200环刮刀换刀情况", self.options)["success"])
        self.assertTrue(self.assistant.chat("查询100到200环滚刀换刀情况", self.options)["success"])

    def test_history_requires_matching_intent_and_controls_from_the_calling_turn(self):
        question = "查询100到200环换刀趋势，按50环分段"
        self.queried(question, ring_range=[200, 100])
        snapshot = authorized_snapshot(self.snapshot(), "P1", access_stamp("P1"))
        history = self.assistant._memory_messages(snapshot, self.options)
        spec = snapshot.messages[0].metadata["query_intent"]
        context = {**self.options, "memory_snapshot": snapshot, "memory_slots": {"ring_range": [100, 200]},
                   "query_spec": spec}
        self.assertTrue(self.assistant._history_evidence_covers(history, context, question))
        self.assertTrue(self.assistant._history_evidence_covers(history, context, " 查询100到200环换刀趋势 按50环分段？"))
        self.assertFalse(self.assistant._history_evidence_covers(history, context, "查询100到200环草稿换刀趋势，按50环分段"))
        self.assertFalse(self.assistant._history_evidence_covers(history, context, "查询100到200环换刀趋势，按5.0环分段"))
        self.assertFalse(self.assistant._history_evidence_covers(history, context, "查询100到200环换刀趋势，按5，0环分段"))
        for change in ({"interval": 100}, {"details": True}, {"concentrated": True}, {"intent": "tool_change_summary"}):
            self.assertFalse(self.assistant._history_evidence_covers(history, {**context, "query_spec": {**spec, **change}},
                                                                   question))
        self.assertFalse(self.assistant._history_evidence_covers(history, {**context, "query_spec": {}}, question))
        snapshot.messages[0].metadata.pop("query_intent")
        self.assertFalse(self.assistant._history_evidence_covers(history, context, question))

    def test_history_does_not_cover_a_question_with_an_unscoped_condition(self):
        # 草稿/已确认这类条件不在范围槽位和意图里，问句不同就要重查
        self.queried("查询100到200环已确认开仓记录", ring_range=[100, 200])
        self.assertFalse(self.assistant.chat("查询100到200环草稿开仓记录", self.options)["success"])
        self.assertTrue(self.assistant.chat("查询100到200环已确认开仓记录", self.options)["success"])

    def test_slots_need_the_last_stored_turn_to_be_authorized(self):
        messages = [StoredMessage(1, "human", "P1问题", metadata={"project_id": "P1", "access_stamp": "s1"}),
                    StoredMessage(2, "ai", "P1回答"),
                    StoredMessage(3, "human", "P2问题", metadata={"project_id": "P2", "access_stamp": "s2"})]
        slots = {"ring_range": [300, 400]}
        # P2 的回答行损坏未解码：存储里最后一条是序号 4，槽位由 P2 那一轮写入
        tail_damaged = MemorySnapshot(scope_key="user:1", backend="legacy", slots=slots, messages=messages, latest_sequence=4)
        self.assertEqual(authorized_snapshot(tail_damaged, "P1", "s1").slots, {})
        complete = MemorySnapshot(scope_key="user:1", backend="legacy", slots=slots, messages=messages[:2], latest_sequence=2)
        self.assertEqual(authorized_snapshot(complete, "P1", "s1").slots, slots)

    async def test_stream_requires_a_query_for_a_new_range(self):
        self.queried("查询100到200环换刀情况", ring_range=[100, 200])
        events = [event async for event in self.assistant.chat_stream("查询300到400环换刀情况", self.options)]
        self.assertEqual(events[-1]["type"], "error", events)
        self.assertFalse(any(event["type"] == "chunk" for event in events))
        events = [event async for event in self.assistant.chat_stream("查询120到150环换刀情况", self.options)]
        self.assertEqual(events[-1]["type"], "error", events)
        self.assertFalse(any(event["type"] == "chunk" for event in events))
        events = [event async for event in self.assistant.chat_stream("查询100到200环换刀情况", self.options)]
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
        self.memory.append_turn(self.memory.scope_key("event-test"), "旧问题", "长" * 300000,
                                metadata={"project_id": "P1", "access_stamp": access_stamp("P1")})
        self.model.mode = "answer"
        # 整理不出空间时（如 Django 后端）才走到这条提示；能整理的情况见 test_history_compaction
        self.assistant._compaction_check = lambda snapshot, context, text: (
            False, self.assistant._memory_messages(snapshot, context), None,
        )
        for context_mode in ("auto", "new"):
            result = self.assistant.chat("你好", {**self.options, "context_mode": context_mode})
            self.assertFalse(result["success"])
            self.assertIn("对话历史已超过模型上下文上限，本次未生成回答。请点「重置对话」清空历史后再问。", result["error"])
        self.assistant.reset_memory("event-test")
        self.assistant._model_needs_tools = Mock(return_value=False)
        self.assertTrue(self.assistant.chat("你好", self.options)["success"])


class HistoryAccessTests(TestCase):
    def setUp(self):
        self.dept = Dept.objects.create(name="历史授权部门")
        self.user = Users.objects.create(username="history-user", dept=self.dept)
        role = Role.objects.create(name="历史授权角色", key="history-role", status=True)
        self.user.role.add(role)
        menu = Menu.objects.create(name="历史授权测试")
        button = MenuButton.objects.create(menu=menu, name="总览", value="HistoryOverview", method=0,
                                           api="/api/shield/analysis/overview/")
        self.permission = RoleMenuButtonPermission.objects.create(role=role, menu_button=button, data_range=2)
        ProjectInfo.objects.create(project_id="P1", project_name="项目一", dept_belong_id=self.dept.pk, creator=self.user)
        token = ANALYSIS_REQUEST.set(views._analysis_scope_request(self.user))
        self.addCleanup(ANALYSIS_REQUEST.reset, token)

    def test_stamp_tracks_filter_sql_and_empty_scope(self):
        original = access_stamp("P1")
        self.assertEqual(original, access_stamp("P1"))
        self.assertNotEqual(original, access_stamp("P2"))
        self.permission.data_range = 0
        self.permission.save()
        own = access_stamp("P1")
        self.assertNotEqual(original, own)
        self.user.dept = Dept.objects.create(name="新部门")
        self.assertNotEqual(own, access_stamp("P1"))
        self.user.is_superuser = True
        unrestricted = access_stamp("P1")
        self.assertNotEqual(original, unrestricted)
        token = ANALYSIS_REQUEST.set(None)
        try:
            self.assertEqual(unrestricted, access_stamp("P1"))
        finally:
            ANALYSIS_REQUEST.reset(token)
        self.user.is_superuser = False
        self.permission.delete()
        empty = access_stamp("P1")
        self.assertEqual(empty, access_stamp("P1"))
        self.assertNotEqual(empty, original)

    def test_history_endpoint_resolves_project_and_rechecks_permissions(self):
        snapshot = MemorySnapshot(scope_key=f"user:{self.user.pk}", slots={"ring_range": [100, 200]}, messages=[
            StoredMessage(1, "human", "授权问题", metadata={"project_id": "P1", "access_stamp": access_stamp("P1")}),
            StoredMessage(2, "ai", "授权答案"),
        ])
        assistant = ToolAssistant()
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._baseline_context = Mock(return_value=None)
        request = RequestFactory().get("/api/ai/history/")
        force_authenticate(request, user=self.user)
        with patch.object(views, "get_assistant", return_value=assistant):
            response = views.conversation_history(request)
            self.assertEqual(response.data["code"], 2000)
            self.assertEqual(len(response.data["data"]["messages"]), 2)
            self.assertEqual(assistant._baseline_context.call_args.args[1], "P1")
            self.permission.data_range = 0
            self.permission.save()
            response = views.conversation_history(request)
            self.assertEqual(response.data["code"], 2000)
            self.assertEqual(response.data["data"]["messages"], [])
            self.assertEqual(response.data["data"]["memory"]["active_slots"], {})
            denied = RequestFactory().get("/api/ai/history/", {"project_id": "P2"})
            force_authenticate(denied, user=self.user)
            self.assertEqual(views.conversation_history(denied).status_code, 403)
            with self.assertRaisesMessage(PermissionError, "无权查看该项目的数据"):
                views._context_for_user(self.user, {"project_id": "P2"})
