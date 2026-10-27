import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from langchain_core.messages import AIMessage, AIMessageChunk

from application.ai_assistant.answer_check import answer_requirements, check_final_answer
from application.ai_assistant.context_budget import ContextBudgetExceeded, ContextBudgetPolicy, ContextUsage, GuardedChatModel, OutputLimitExceeded, context_usage
from application.ai_assistant.llm_service import ToolAssistant
from application.ai_assistant.memory_service import MemorySnapshot


PRICES = {"manufacturer_prices": [{"manufacturer": "甲厂"}, {"manufacturer": "乙厂"}]}
QUESTION = "逐家列出报价，按每环报价从低到高排列"
GOOD = "| 厂家 | 每环报价 |\n|---|---|\n| 甲厂 | 1 |\n| 乙厂 | 2 |"
BAD = "| 厂家 | 每环报价 |\n|---|---|\n| 甲厂 | 2 |\n| 甲厂 | 1 |"


class AnswerCheckTests(SimpleTestCase):
    def check(self, question, answer, data, spec=None):
        tools = [{"result": data}]
        return check_final_answer(question, answer, answer_requirements(question, spec, tools), tools)

    def test_manufacturers_requested_and_unrequested(self):
        self.assertEqual(self.check("逐家列出", GOOD, PRICES), [])
        self.assertEqual(self.check("各厂家报价", "跨厂家区间1–2", PRICES), ["没有逐家列出：甲厂、乙厂。"])
        self.assertEqual(self.check("报价区间", "跨厂家区间1–2", PRICES), [])
        scoped = {"recommendations": [{"tool_parent_type": "DISC", "manufacturer_prices": [{"manufacturer": "甲厂"}]},
                                       {"tool_parent_type": "SCRAPER", "manufacturer_prices": [{"manufacturer": "乙厂"}]}]}
        self.assertEqual(self.check("逐家列出滚刀报价", GOOD.replace("乙厂", "甲厂"), scoped), [])

    def test_sort_directions_and_empty_last(self):
        for direction, rows in (("从低到高", "| A | 1 |\n| B | 2 |"), ("降序", "| A | 2 |\n| B | 1 |")):
            with self.subTest(direction=direction):
                header = "| 厂家 | 每环报价 |\n|---|---|\n"
                query = "按每环报价" + direction
                self.assertEqual(self.check(query, header + rows + "\n| C | — |", PRICES), [])
                self.assertEqual(len(self.check(query, header + "\n".join(reversed(rows.splitlines())), PRICES)), 1)
                self.assertEqual(len(self.check(query, header + "| C | 暂无 |\n" + rows, PRICES)), 1)
        self.assertEqual(self.check("列出报价", BAD, PRICES), [])
        self.assertTrue(self.check("按每环报价排序", BAD, PRICES, {"sort_by": "price_per_ring"}))

    def test_all_objects_and_scoped_truncation_notice(self):
        data = {"position_counts": [{"cutter_position_no": str(n)} for n in range(3)]}
        answer = "| 刀位 | 次数 |\n|---|---|\n| 0 | 1 |"
        self.assertEqual(self.check("按刀位列出", answer, data), ["刀位只列出 1 个，查询结果共有 3 个。"])
        self.assertEqual(self.check("按刀位列出", answer + "\n只列出前1个刀位。", data), [])
        self.assertTrue(self.check("按刀位列出", answer + "\n只逐条查看了前100条旧刀。", data))
        notice = "下表按页内顺序**逐一列出第 1 页全部 1 个出现 2 次及以上的刀位**，其余未展开。\n"
        self.assertEqual(self.check("按刀位列出", notice + answer, data), [])
        self.assertTrue(self.check("按刀位列出", "接口返回第 1 页全部 1 个刀位。\n" + answer, data))
        self.assertEqual(self.check("按刀位列出", answer + "\n| 1 | 1 |\n| 2 | 1 |", data), [])
        self.assertEqual(self.check("概括异常", answer, data), [])
        self.assertTrue(self.check("全部型号", "| 型号 | 次数 |\n|---|---|\n| A | 1 |",
                                   {"recommendations": [{"tool_type_name": "A"}], "tool_model_count": 3}))
        self.assertTrue(self.check("逐把列出旧刀", "| 旧刀 | 次数 |\n|---|---|\n| A | 1 |",
                                   {"records": [{"old_tool_number": "A"}], "scope": {"record_count": 3}}))

    def test_summary_numbers_and_mixed_columns(self):
        data = {"total_records": 10, "replaced_count": 4, "segment_count": 2, "total_registered_cost_yuan": 100}
        for label, wrong, correct in (("观测数", 9, 10), ("更换数", 3, 4), ("段数", 3, 2), ("合计金额", 99, 100)):
            with self.subTest(label=label):
                self.assertEqual(self.check(label, f"{label}：{correct}", data), [])
                self.assertEqual(self.check(label, f"{label}：{wrong}", data), [f"“{label}”写的是 {wrong}，查询结果是 {correct}。"])
        header = "| 观测数 | 更换数 |\n|---|---|\n"
        self.assertEqual(self.check("更换统计", header + "| 10 | 10 |", data), ["“更换数”列填的是观测数，不是更换数。"])
        self.assertEqual(self.check("更换统计", header + "| 10 | 4 |", data), [])
        self.assertEqual(self.check("更换统计", "其中滚刀更换数3，刮刀更换数1。", data), [])

    def test_universal_observation_claim_and_followup(self):
        data = {"matched_position_count": 10, "total_records": 10,
                "replacement_by_type": [{"count": 4}], "scope": {"ring_range": [1, 50]}}
        self.assertEqual(self.check("更换次数", "每个刀位只被观测/更换1次。", data),
                         ["“1–50环更换数”写的是 10，查询结果是 4。"])
        self.assertEqual(self.check("更换次数", "每个刀位只被观测1次，其中4次更换。", data), [])
        self.assertTrue(self.check("继续", "区间1–2", PRICES, {"effective_query": "逐家列出报价"}))

    def assistant(self, answer=BAD, data=PRICES):
        assistant = ToolAssistant()
        snapshot = MemorySnapshot(scope_key="user:1", backend="legacy")
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._store_turn_and_summarize = Mock(return_value=snapshot)
        assistant._llm = Mock()
        assistant._llm.invoke.return_value = AIMessage(content=GOOD)
        result = {"output": answer, "intermediate_steps": [(SimpleNamespace(tool="query", tool_input={}), json.dumps(data))]}
        assistant._invoke_with_retry = Mock(return_value=result)

        async def stream(*args, **kwargs):
            yield {"event": "on_chain_start", "run_id": "root", "parent_ids": []}
            yield {"event": "on_tool_end", "name": "tool_query_tool_cost_catalog", "data": {"output": json.dumps(data)}}
            yield {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content=answer)}}
            yield {"event": "on_chain_end", "run_id": "root", "data": {"output": result}}

        assistant._get_executor_for_query = Mock(return_value=SimpleNamespace(astream_events=stream))
        return assistant

    def revise(self, assistant, answer=BAD, tools=None):
        trace = {}
        events = list(assistant._revise_agent_answer(QUESTION, answer, {}, tools or [{"result": PRICES}], trace))
        return events, trace

    def test_clean_answer_does_not_invoke_or_emit(self):
        assistant = self.assistant()
        events, trace = self.revise(assistant, GOOD)
        self.assertEqual(events, [])
        self.assertEqual(trace, {"issues_before": [], "revised": False, "issues_after": []})
        assistant._llm.invoke.assert_not_called()

    def test_remaining_issues_keep_better_version_and_annotate(self):
        partial = GOOD.replace("乙厂", "甲厂")
        for original, candidate, chosen in ((partial, BAD, partial), (BAD, partial, partial)):
            with self.subTest(original=original):
                assistant = self.assistant()
                assistant._llm.invoke.return_value = AIMessage(content=candidate)
                events, trace = self.revise(assistant, original)
                answer = events[1]["content"]
                self.assertTrue(answer.startswith(chosen))
                self.assertIn("### 回答核对\n\n以下几处没有答全或与查询结果不一致，以查询结果为准：", answer)
                self.assertTrue(trace["revised"])
                assistant._llm.invoke.assert_called_once()

    def test_budget_skip_preserves_turn_usage(self):
        assistant = self.assistant()
        raw_model = assistant._llm
        assistant._llm = GuardedChatModel(raw_model, ContextBudgetPolicy(context_tokens=300, output_tokens=50, safety_margin_tokens=50))
        usage = ContextUsage()
        token = context_usage.set(usage)
        try:
            events, trace = self.revise(assistant, tools=[{"result": {**PRICES, "detail": "查询结果" * 500}}])
        finally:
            context_usage.reset(token)
        self.assertIn("### 回答核对", events[1]["content"])
        self.assertFalse(trace["revised"])
        self.assertFalse(usage.exceeded)
        self.assertEqual(usage.model_calls, 0)
        raw_model.invoke.assert_not_called()

    def test_sync_stores_final_answer_and_accounts_for_revision(self):
        assistant = self.assistant()
        raw_model = assistant._llm
        raw_model.invoke.return_value = AIMessage(content=GOOD, usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
        assistant._llm = GuardedChatModel(raw_model, ContextBudgetPolicy())
        result = assistant.chat(QUESTION, {"user_id": 1, "route_mode": "agent"})
        self.assertTrue(result["success"], result)
        self.assertEqual(result["answer"], GOOD)
        self.assertEqual(result["answer_check"]["issues_after"], [])
        self.assertEqual(result["context"]["provider_usage"]["prompt_tokens"], 100)
        self.assertEqual(assistant._store_turn_and_summarize.call_args.args[2], GOOD)
        messages = raw_model.invoke.call_args.args[0]
        self.assertIn("上一版回答有以下问题，请只改这些地方，其余内容保持不变，数字一律以查询结果为准：\n- ", messages[-1].content)
        self.assertNotIn("tools", raw_model.invoke.call_args.kwargs)

    async def test_stream_revision_sequence_and_clean_no_extra_events(self):
        for original in (BAD, GOOD):
            with self.subTest(original=original):
                assistant = self.assistant(original)
                events = [e async for e in assistant.chat_stream(QUESTION, {"user_id": 1, "route_mode": "agent"})]
                revision = [e for e in events if e["type"] in ("status", "answer")]
                self.assertEqual(revision, ([{"type": "status", "stage": "revising"}, {"type": "answer", "content": GOOD},
                                             {"type": "status", "stage": "done"}] if original == BAD else []))
                self.assertEqual(events[-1]["type"], "done", events)
                self.assertEqual(assistant._store_turn_and_summarize.call_args.args[2], GOOD)
                self.assertEqual(assistant._llm.invoke.call_count, int(original == BAD))

    def test_ablation_skips_check_entirely(self):
        assistant = self.assistant()
        with patch.dict(os.environ, {"AI_ABLATE_ANSWER_CHECK": "1"}), patch(
            "application.ai_assistant.llm_service.answer_requirements", side_effect=AssertionError("check called"),
        ):
            result = assistant.chat(QUESTION, {"user_id": 1, "route_mode": "agent"})
        self.assertTrue(result["success"], result)
        self.assertEqual(result["answer"], BAD)
        self.assertNotIn("answer_check", result)
        assistant._llm.invoke.assert_not_called()

    def revision_failure(self, error):
        def fail(*args, **kwargs):
            if isinstance(error, ContextBudgetExceeded):
                usage = context_usage.get()
                usage.record([], ContextBudgetPolicy(), {}, 999999, 0, 0)
            raise error
        return fail

    def test_sync_revision_exception_returns_original_with_note(self):
        for error in (OutputLimitExceeded("truncated"), RuntimeError("provider"), ContextBudgetExceeded(999999, 100)):
            with self.subTest(error=type(error).__name__):
                assistant = self.assistant()
                assistant._llm.invoke.side_effect = self.revision_failure(error)
                result = assistant.chat(QUESTION, {"user_id": 1, "route_mode": "agent"})
                self.assertTrue(result["success"], result)
                self.assertFalse(result["context"]["exceeded"])
                self.assertTrue(result["answer"].startswith(BAD + "\n\n### 回答核对"))
                self.assertFalse(result["answer_check"]["revised"])
                self.assertEqual(result["answer_check"]["revision_error"], type(error).__name__)
                self.assertEqual(assistant._store_turn_and_summarize.call_args.args[2], result["answer"])

    async def test_stream_revision_exception_still_replaces_and_finishes(self):
        for error in (OutputLimitExceeded("truncated"), RuntimeError("provider"), ContextBudgetExceeded(999999, 100)):
            with self.subTest(error=type(error).__name__):
                assistant = self.assistant()
                assistant._llm.invoke.side_effect = self.revision_failure(error)
                events = [e async for e in assistant.chat_stream(QUESTION, {"user_id": 1, "route_mode": "agent"})]
                revision = [e for e in events if e["type"] in ("status", "answer")]
                self.assertEqual([e.get("stage", e["type"]) for e in revision], ["revising", "answer", "done"])
                self.assertTrue(revision[1]["content"].startswith(BAD + "\n\n### 回答核对"))
                self.assertNotIn("error", [e["type"] for e in events])
                self.assertFalse(next(e["context"] for e in events if e["type"] == "context")["exceeded"])
                self.assertEqual(events[-1]["answer_check"]["revision_error"], type(error).__name__)
                self.assertEqual(assistant._store_turn_and_summarize.call_args.args[2], revision[1]["content"])

    def test_revision_hints_are_model_only_and_cancellation_propagates(self):
        assistant = self.assistant()
        tools = [{"result": {**PRICES, "position_counts": [{"cutter_position_no": "1"}]}}]
        assistant._llm.invoke.return_value = AIMessage(content=BAD)
        trace = {}
        events = list(assistant._revise_agent_answer("各厂家报价，按刀位列出", BAD, {}, tools, trace))
        prompt = assistant._llm.invoke.call_args.args[0][-1].content
        for hint in ("逐家的内容请用带“厂家”列的表格列出，每个厂家一行。", "请列全，或在表前写明只列出了前几个。"):
            self.assertIn(hint, prompt)
            self.assertNotIn(hint, events[1]["content"])
        assistant._llm.invoke.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            self.revise(assistant)
