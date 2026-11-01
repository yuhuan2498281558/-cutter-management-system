"""同一脚本化假模型核对双入口的事件、用量、落库与调用线程。"""

import os
import threading
from contextlib import aclosing
from contextvars import ContextVar
from copy import deepcopy
from unittest.mock import Mock, patch
from uuid import uuid4

from asgiref.sync import async_to_sync
from django.db import connection
from django.test import TestCase
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import StructuredTool

from application.ai_assistant import llm_service as service
from application.ai_assistant.context_budget import ContextBudgetPolicy, GuardedChatModel, context_usage
from application.ai_assistant.memory_service import MemorySnapshot


_USAGE = {"input_tokens": 17, "output_tokens": 3, "total_tokens": 20}
_REQUEST = ContextVar("turn_kernel_request", default=None)
_QUERY = "查询换刀记录"
_CONTEXT = {"user_id": "turn", "project_id": "P", "route_mode": "agent"}


def _calls(*values):
    return AIMessageChunk(content="", tool_calls=[
        {"name": "lookup", "args": {"value": value}, "id": f"call-{value}"} for value in values
    ])


class _ScriptedModel(Runnable):
    def __init__(self, script, sync_only=False):
        self.script, self.sync_only = script, sync_only
        self.calls, self.closed = [], []

    def bind_tools(self, tools):
        return self

    def _reply(self, messages, config, method):
        if self.sync_only and method.startswith("a"):
            raise AssertionError("同步入口不能触碰异步客户端")
        index = len(self.calls)
        self.calls.append((deepcopy(messages), config, method, threading.get_ident()))
        response = None
        try:
            for position, item in enumerate(self.script[index]):
                if isinstance(item, Exception):
                    raise item
                chunk = deepcopy(item)
                if position == len(self.script[index]) - 1:
                    chunk.usage_metadata = {**_USAGE, "input_token_details": {"cache_read": 5}}
                    chunk.response_metadata = {"model_name": "scripted"}
                response = chunk if response is None else response + chunk
                yield chunk
            for callback in config.get("callbacks", []):
                callback.on_llm_end(LLMResult(generations=[[ChatGeneration(message=response)]]), run_id=uuid4())
        finally:
            self.closed.append(index)

    def invoke(self, input, config=None, **kwargs):
        return sum(self._reply(input, config, "invoke"), AIMessageChunk(content=""))

    async def ainvoke(self, input, config=None, **kwargs):
        return sum(self._reply(input, config, "ainvoke"), AIMessageChunk(content=""))

    def stream(self, input, config=None, **kwargs):
        yield from self._reply(input, config, "stream")

    async def astream(self, input, config=None, **kwargs):
        for chunk in self._reply(input, config, "astream"):
            yield chunk


class TurnKernelTests(TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {
            "AI_ABLATE_TEMPLATE": "0", "AI_ABLATE_ANSWER_CHECK": "0", "AI_ABLATE_MEMORY": "0",
        }))

    def _assistant(self, script, rule=None, lookup=None):
        assistant = service.ToolAssistant()
        model = _ScriptedModel(script)
        assistant._llm = GuardedChatModel(model, ContextBudgetPolicy())
        assistant._prompt = ChatPromptTemplate.from_messages([
            ("system", "按查询结果回答。"), MessagesPlaceholder("chat_history"),
            ("human", "{input}"), MessagesPlaceholder("agent_scratchpad"),
        ])
        snapshot = MemorySnapshot(scope_key="user:turn", backend="legacy", generation=3)
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._store_turn_and_summarize = Mock(return_value=snapshot)
        assistant._should_polish_direct_answer = Mock(return_value=False)
        executed = []

        def _lookup(value: int, config: RunnableConfig):
            executed.append((value, config))
            return lookup(value) if lookup else {"total_records": 2}

        tool = StructuredTool.from_function(_lookup, name="lookup", description="查询记录。")
        assistant._get_tools_for_query = Mock(return_value=[tool])

        def _direct(*args):
            if rule:
                service._TRACE.get().append({"tool": "lookup", "args": {}, "result": '{"total_records": 2}'})
            return deepcopy(rule)

        assistant._direct_route = Mock(side_effect=_direct)
        return assistant, model, executed

    def _pair(self, script, *, rule=None, query=_QUERY, lookup=None, setup=None):
        runs = []
        for streaming in (False, True):
            assistant, model, executed = self._assistant(script, rule, lookup)
            model.sync_only = not streaming
            if setup:
                setup(assistant)
            recorded = []
            original = assistant._turn_events

            async def _observe(*args, **kwargs):
                async with aclosing(original(*args, **kwargs)) as events:
                    async for event in events:
                        recorded.append((event, len(model.calls)))
                        yield event

            assistant._turn_events = _observe
            context = {**_CONTEXT, "route_mode": "rule" if rule else "agent"}

            async def _collect():
                return [event async for event in assistant.chat_stream(query, context)]

            if streaming:
                events = async_to_sync(_collect)()
                self.assertEqual(events, [event for event, _ in recorded if event["type"] != "result"])
                result = recorded[-1][0]["payload"]
            else:
                result = assistant.chat(query, context)
                self.assertEqual(result, recorded[-1][0]["payload"])
            self.assertEqual(sum(event["type"] == "result" for event, _ in recorded), 1)
            self.assertIsNone(context_usage.get())
            self.assertIsNone(service._TRACE.get())
            self.assertGreaterEqual(result["latency_ms"], 0)
            for _, config, _, _ in model.calls:
                self.assertEqual(config["configurable"], {"session_id": "turn"})
                self.assertEqual(len(config["callbacks"]), 1)
                self.assertIs(config, model.calls[0][1])
            for _, config in executed:
                self.assertEqual(config["configurable"], {"session_id": "turn"})
            runs.append((result, recorded, assistant, model, executed))

        left, right = runs
        self.assertEqual({key: value for key, value in left[0].items() if key != "latency_ms"},
                         {key: value for key, value in right[0].items() if key != "latency_ms"})
        self.assertEqual([item[0] for item in left[3].calls], [item[0] for item in right[3].calls])
        for run in runs:
            if run[0]["success"]:
                run[2]._store_turn_and_summarize.assert_called_once()
            else:
                run[2]._store_turn_and_summarize.assert_not_called()
        if left[0]["success"]:
            saved = [run[2]._store_turn_and_summarize.call_args for run in runs]
            self.assertEqual(saved[0].args, saved[1].args)
            for field in ("metadata", "enriched_input", "expected_generation", "usage"):
                self.assertEqual(saved[0].kwargs[field], saved[1].kwargs[field], field)
            self.assertEqual([action.tool for action, _ in saved[0].kwargs["intermediate_steps"]],
                             [action.tool for action, _ in saved[1].kwargs["intermediate_steps"]])
            self.assertEqual(saved[0].args[1:3], (query, left[0]["answer"]))
        else:
            self.assertEqual(right[1][-2][0], {"type": "error", "content": left[0]["error"]})
            self.assertEqual(left[0]["route_stage"], "error")
        return runs

    def _usage(self, result, calls):
        expected = {**{key: value * calls for key, value in _USAGE.items()}, "input_token_details": {"cache_read": 5 * calls}}
        self.assertEqual(result["usage"], {"scripted": expected})
        self.assertEqual(result["context"]["model_calls"], calls)

    def test_rule_answer_polish_and_template_ablation(self):
        rule = {"answer": "规则回答", "type": "analysis", "rule_branch": "tool_change_summary"}
        for polish, ablate in ((False, False), (True, False), (True, True)):
            with self.subTest(polish=polish, ablate=ablate), patch.dict(os.environ, {"AI_ABLATE_TEMPLATE": str(int(ablate))}):
                script = [[AIMessageChunk(content="复述结果")]] if ablate else []
                if polish:
                    script.append([AIMessageChunk(content="润色结果")])

                def _setup(assistant):
                    assistant._should_polish_direct_answer = Mock(return_value=polish)
                    prepare = assistant._prepare_query_context

                    def _prepare(*args):
                        service._TRACE.get().append({"tool": "query_opening_records", "args": {}, "result": "准备查询"})
                        return prepare(*args)

                    assistant._prepare_query_context = _prepare

                runs = self._pair(script, rule=rule, setup=_setup)
                for result, events, assistant, model, _ in runs:
                    self.assertEqual(result["answer"], "润色结果" if polish else "规则回答")
                    self.assertEqual([event["type"] for event, _ in events], ["meta", "chunk", "memory", "context", "done", "result"])
                    saved = assistant._store_turn_and_summarize.call_args.kwargs
                    self.assertEqual(saved["metadata"]["rule_branch"], "tool_change_summary")
                    self.assertIsNone(saved["enriched_input"])
                    self.assertEqual(saved["intermediate_steps"], [])
                    self.assertEqual([call["tool"] for call in result["tool_calls"]], ["lookup"])
                    self.assertEqual([call["tool"] for call in events[-2][0]["tool_calls"]], ["query_opening_records", "lookup"])
                    self.assertEqual(len(model.calls), int(polish) + int(ablate))
                    if ablate:
                        self.assertNotIn("准备查询", model.calls[0][0][-1].content)
                    if polish:
                        self._usage(result, len(script))
                    else:
                        self.assertEqual(result["usage"], {})

    def test_direct_chat_preserves_text_and_stream_chunks(self):
        runs = self._pair([[AIMessageChunk(content="你好"), AIMessageChunk(content="。")]], query="你好")
        for result, _, assistant, _, _ in runs:
            self.assertEqual((result["answer"], result["route_stage"]), ("你好。", "llm_direct"))
            self._usage(result, 1)
            self.assertTrue(assistant._store_turn_and_summarize.call_args.kwargs["enriched_input"].endswith("你好"))
        self.assertEqual([event["content"] for event, _ in runs[1][1] if event["type"] == "chunk"], ["你好", "。"])

    def test_agent_success_and_revision_share_config_usage_and_evidence(self):
        good = "| 厂家 | 每环报价 |\n|---|---|\n| 甲厂 | 1 |\n| 乙厂 | 2 |"
        for revision in (False, True):
            with self.subTest(revision=revision):
                answer = "共2条。" if not revision else "| 厂家 | 每环报价 |\n|---|---|\n| 甲厂 | 2 |\n| 甲厂 | 1 |"
                script = [[_calls(1)], [AIMessageChunk(content=answer)]]
                if revision:
                    script.append([AIMessageChunk(content=good)])
                runs = self._pair(script, query="逐家列出报价，按每环报价从低到高排列" if revision else _QUERY,
                                  lookup=(lambda value: {"manufacturer_prices": [{"manufacturer": "甲厂"}, {"manufacturer": "乙厂"}]}) if revision else None)
                for result, events, assistant, _, _ in runs:
                    self.assertEqual(result["answer"], good if revision else answer)
                    self.assertEqual(result["retry_count"], 0)
                    self._usage(result, 3 if revision else 2)
                    saved = assistant._store_turn_and_summarize.call_args.kwargs
                    self.assertEqual(saved["metadata"]["tool_group"], "all")
                    self.assertEqual([action.tool for action, _ in saved["intermediate_steps"]], ["lookup"])
                    if revision:
                        self.assertTrue(result["answer_check"]["revised"])
                        self.assertEqual(result["answer_check"]["issues_after"], [])
                        self.assertEqual([event.get("stage", event["type"]) for event, _ in events],
                                         ["meta", "chunk", "revising", "answer", "done", "memory", "context", "done", "result"])

    def test_missing_tool_retries_before_any_chunk_and_saves_retry_input(self):
        runs = self._pair([[AIMessageChunk(content="没有依据的回答")], [_calls(1)], [AIMessageChunk(content="共2条。")]])
        for result, events, assistant, model, _ in runs:
            self.assertEqual((result["answer"], result["retry_count"]), ("共2条。", 1))
            self.assertEqual([(event["content"], calls) for event, calls in events if event["type"] == "chunk"], [("共2条。", 3)])
            saved = assistant._store_turn_and_summarize.call_args.kwargs
            self.assertIn("【系统提示】你上一次回答没有调用任何工具", saved["enriched_input"])
            self.assertEqual(saved["enriched_input"], next(message.content for message in reversed(model.calls[1][0]) if isinstance(message, HumanMessage)))
            self._usage(result, 3)

        failed = self._pair([[AIMessageChunk(content="仍未查数据")]] * 2)
        for result, events, _, model, _ in failed:
            self.assertEqual(result["error"], "处理出错：未取得完整的工具查询结果，请重试")
            self.assertEqual(len(model.calls), 2)
            self.assertFalse(any(event["type"] == "chunk" for event, _ in events))

    def test_hard_tool_failure_stops_before_next_tool_or_model(self):
        runs = self._pair([[_calls(1, 2)], [AIMessageChunk(content="不应调用")]], lookup=lambda value: {"error": "query failed"})
        for result, events, _, model, executed in runs:
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "处理出错：数据查询失败，无法给出完整分析，请稍后重试")
            self.assertEqual([value for value, _ in executed], [1])
            self.assertEqual(len(model.calls), 1)
            self.assertEqual(model.closed, [0])
            self.assertEqual([event["type"] for event, _ in events], ["meta", "error", "result"])

    def test_overflow_compacts_once_and_replays_without_early_text(self):
        def _setup(assistant):
            snapshot = assistant._load_memory.return_value
            assistant._compaction_check = Mock(return_value=(True, [], 100))
            assistant._compact_history = Mock(return_value=(snapshot, []))
            assistant._compact_after_overflow = Mock(return_value=(snapshot, [HumanMessage(content="已整理历史")]))

        runs = self._pair([[RuntimeError("context length exceeded")], [_calls(1)], [AIMessageChunk(content="共2条。")]], setup=_setup)
        for result, events, assistant, model, _ in runs:
            self.assertTrue(result["success"], result)
            self.assertEqual(result["answer"], "共2条。")
            self.assertEqual([event.get("stage", event["type"]) for event, _ in events],
                             ["compacting", "done", "meta", "compacting", "done", "chunk", "memory", "context", "done", "result"])
            assistant._compact_history.assert_called_once()
            assistant._compact_after_overflow.assert_called_once()
            for compaction in (assistant._compact_history, assistant._compact_after_overflow):
                self.assertEqual(compaction.call_args.kwargs["config"]["configurable"], {"session_id": "turn"})
            self.assertIn("已整理历史", [message.content for message in model.calls[1][0]])
            self.assertEqual(result["retry_count"], 0)

        partial = _calls(2)
        partial.content = "继续检查。"
        for script, compactions in (
            ([[RuntimeError("invalid request")]], 0),
            ([[RuntimeError("context length exceeded")]] * 2, 1),
            ([[_calls(1)], [partial], [RuntimeError("context length exceeded")]], 0),
        ):
            with self.subTest(script=script):
                for result, _, assistant, model, _ in self._pair(script, setup=_setup):
                    self.assertFalse(result["success"])
                    self.assertEqual(assistant._compact_after_overflow.call_count, compactions)
                    self.assertEqual(len(model.calls), len(script))

    def test_preparation_failure_and_empty_answers_return_errors_without_saving(self):
        for method in ("_load_memory", "_prepare_query_context"):
            with self.subTest(method=method):
                runs = self._pair([], setup=lambda assistant: setattr(assistant, method, Mock(side_effect=RuntimeError("offline failure"))))
                self.assertEqual(runs[0][0]["error"], runs[0][2]._friendly_error("offline failure"))
                self.assertEqual(runs[0][3].calls, [])
        for route in ("rule", "llm_direct", "agent"):
            with self.subTest(route=route):
                script = [[AIMessageChunk(content="")]] if route != "rule" else []
                if route == "agent":
                    script.insert(0, [_calls(1)])
                runs = self._pair(script, rule={"answer": "", "type": "analysis"} if route == "rule" else None,
                                  query="你好" if route == "llm_direct" else _QUERY)
                self.assertEqual(runs[0][0]["error"], "处理出错：未生成完整回答，请重试")
                if route == "rule":
                    self.assertEqual([event["type"] for event, _ in runs[1][1]], ["error", "result"])

    def test_chat_uses_sync_clients_and_calling_transaction_on_consecutive_turns(self):
        seen = []

        def _lookup(value):
            seen.append((threading.get_ident(), connection.in_atomic_block, _REQUEST.get()))
            return {"total_records": 2}

        assistant, model, _ = self._assistant([[_calls(1)], [AIMessageChunk(content="第一次")],
                                                [_calls(2)], [AIMessageChunk(content="第二次")]], lookup=_lookup)
        model.sync_only = True
        token = _REQUEST.set("项目 P")
        try:
            results = [assistant.chat(_QUERY, _CONTEXT) for _ in range(2)]
        finally:
            _REQUEST.reset(token)
        self.assertEqual([result["answer"] for result in results], ["第一次", "第二次"])
        self.assertEqual(seen, [(threading.get_ident(), True, "项目 P")] * 2)
        self.assertTrue(all(method == "stream" and thread == threading.get_ident() for _, _, method, thread in model.calls))
        self.assertEqual(assistant._store_turn_and_summarize.call_count, 2)
