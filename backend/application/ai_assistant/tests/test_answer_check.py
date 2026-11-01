import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from langchain_core.messages import AIMessage, AIMessageChunk

from application.ai_assistant.answer_check import answer_requirements, check_final_answer
from application.ai_assistant.context_budget import ContextBudgetExceeded, ContextBudgetPolicy, ContextUsage, GuardedChatModel, OutputLimitExceeded, context_usage
from application.ai_assistant.llm_service import TOOLS, ToolAssistant
from application.ai_assistant.memory_service import MemorySnapshot


PRICES = {"manufacturer_prices": [{"manufacturer": "甲厂"}, {"manufacturer": "乙厂"}]}
QUESTION = "逐家列出报价，按每环报价从低到高排列"
GOOD = "| 厂家 | 每环报价 |\n|---|---|\n| 甲厂 | 1 |\n| 乙厂 | 2 |"
BAD = "| 厂家 | 每环报价 |\n|---|---|\n| 甲厂 | 2 |\n| 甲厂 | 1 |"
RECOMMENDATIONS = {"recommendations": [{"tool_type_name": "型号A", "avg_service_rings": 10,
    "completed_service_count": 3, "manufacturer_prices": [
        {"manufacturer": "甲厂", "brand": "", "unit_price_yuan": 100, "price_per_ring_yuan": 10},
        {"manufacturer": "乙厂", "brand": "乙牌", "unit_price_yuan": 200, "price_per_ring_yuan": 20}]}],
    "insufficient_evidence": [{"tool_type_name": "型号B", "completed_service_count": 0,
        "manufacturer_prices": [{"manufacturer": "丙厂", "unit_price_yuan": 300, "price_per_ring_yuan": None}]},
        {"tool_type_name": "型号C", "completed_service_count": 2, "avg_service_rings": 20,
         "manufacturer_prices": [{"manufacturer": "丁厂", "unit_price_yuan": 400, "price_per_ring_yuan": 20}]}]}


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

    def assistant(self, answer=BAD, data=PRICES, tool="query", args=None):
        assistant = ToolAssistant()
        snapshot = MemorySnapshot(scope_key="user:1", backend="legacy")
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._store_turn_and_summarize = Mock(return_value=snapshot)
        assistant._llm = Mock()
        assistant._llm.invoke.return_value = AIMessage(content=GOOD)
        result = {"output": answer, "intermediate_steps": [(SimpleNamespace(tool=tool, tool_input=args or {}), json.dumps(data))]}
        self.enterContext(patch('application.ai_assistant.llm_service.invoke_agent', return_value=result))

        async def stream(*args, **kwargs):
            yield {"type": "tool_end", "call_id": "call-1", "name": "tool_query_tool_cost_catalog", "args": {}, "observation": json.dumps(data)}
            yield {"type": "model_text", "iteration": 2, "content": answer}
            yield {"type": "final", **result}

        assistant._get_tools_for_query = Mock(return_value=TOOLS)
        self.enterContext(patch('application.ai_assistant.llm_service.astream_agent', side_effect=stream))
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

    def test_review_cases_do_not_raise_false_issues(self):
        # 金额按表头或数字后的单位换算后再比
        amount = {"total_registered_cost_yuan": 100000}
        question = "统计登记金额，合计金额以万元展示"
        self.assertEqual(self.check(question, "| 项目 | 合计金额（万元） |\n|---|---|\n| 合计 | 10 |", amount), [])
        self.assertEqual(self.check(question, "| 项目 | 合计金额（万元） |\n|---|---|\n| 合计 | 12 |", amount), ["“合计金额（万元）”写的是 12，查询结果是 10。"])
        self.assertEqual(self.check(question, "总金额：10万元", amount), [])
        self.assertEqual(self.check(question, "总金额：12万元", amount), ["“总金额”写的是 12万，查询结果是 10万。"])
        self.assertEqual(self.check(question, "| 项目 | 合计金额（千元） |\n|---|---|\n| 合计 | 1 |", amount), [])
        # 要前 N 个时，只要求列出 N 个
        models = {"tool_model_count": 4, "service_by_model": [{"tool_type_name": name} for name in "ABCD"],
                  "recommendations": [{"tool_type_name": name} for name in "AB"]}
        self.assertEqual(self.check("从所有型号中推荐前2个型号", "| 型号 | 样本 |\n|---|---|\n| A | 3 |\n| B | 3 |", models), [])
        self.assertTrue(self.check("从所有型号中推荐前3个型号", "| 型号 | 样本 |\n|---|---|\n| A | 3 |\n| B | 3 |", models))
        # "更换过的刀位"是全集的子集，算不准就不查列全
        positions = {"matched_position_count": 2, "top_positions": [
            {"cutter_position_no": "S1L", "replacement_count": 1}, {"cutter_position_no": "S2L", "replacement_count": 0}]}
        self.assertEqual(self.check("列出全部更换过的刀位及更换数", "| 刀位 | 更换数 |\n|---|---|\n| S1L | 1 |", positions), [])
        # 逐家用文字写清楚也算逐家列出
        prices = {"manufacturer_prices": [{"manufacturer": "甲厂"}, {"manufacturer": "模拟厂家07·峻泽"}]}
        question = "请逐家用一句话说明新刀报价，不要表格"
        self.assertEqual(self.check(question, "甲厂新刀报价100元。模拟厂家07·峻泽新刀报价200元。", prices), [])
        self.assertEqual(self.check(question, "甲厂新刀报价100元。模拟厂家07·峻泽也有报价。", prices), ["没有逐家列出：模拟厂家07·峻泽。"])
        # 各组内分别排序时按组检查
        grouped = "| 型号 | 厂家 | 每环报价 |\n|---|---|---|\n| A | 甲 | 1 |\n| A | 乙 | 2 |\n| B | 甲 | 0.5 |\n| B | 乙 | 1.5 |"
        question = "各型号内的厂家分别按每环报价从低到高排序"
        self.assertEqual(self.check(question, grouped, PRICES), [])
        self.assertTrue(self.check(question, grouped.replace("| 0.5 |", "| 9 |"), PRICES))
        self.assertTrue(self.check("按每环报价从低到高排序", grouped, PRICES))

    def test_generated_table_only_covers_quote_sources(self):
        tools = [{"result": {**PRICES, "new_tool_quotes": [{"manufacturer": "丁厂"}],
                            "service_by_install_manufacturer": [{"manufacturer": "丙厂"}]}}]
        requirements = answer_requirements(QUESTION, {}, tools, ["manufacturer_prices"])
        self.assertEqual(check_final_answer(QUESTION, "", requirements, tools), ["没有逐家列出：丙厂。"])

    def test_generated_table_refetches_and_deduplicates_business_params_and_rows(self):
        assistant = self.assistant()
        params = {"project_id": "test-project", "tool_type": "DISC", "ring_range": [1, 100], "stratum_types": ["CLAY_SAND"],
                  "min_samples": 5, "max_unit_price": 500, "sort_by": "service", "top_n": 1}
        calls = [{"tool": "tool_recommend_tools", "args": {**params, "page": page, "page_size": 1},
                  "result": json.dumps({"recommendations": RECOMMENDATIONS["recommendations"][:1]})} for page in (1, 2)]
        calls.append({**calls[0], "args": {**params, "tool_type": "SCRAPER"}})
        with patch("application.ai_assistant.llm_service.recommend_tools", return_value=json.dumps(RECOMMENDATIONS)) as tool:
            events, trace = self.revise(assistant, "跨厂家价格区间", calls)
        self.assertEqual(tool.call_count, 2)
        self.assertEqual(json.loads(tool.call_args_list[0].args[0]), {**params, "top_n": 50})
        self.assertEqual([e["type"] for e in events], ["answer"])
        self.assertEqual(trace, {"generated_tables": ["manufacturer_prices"], "issues_before": [], "revised": False, "issues_after": []})
        self.assertEqual(events[0]["content"].count("| 型号A |"), 2)
        self.assertIn("| 型号B | 丙厂 | — | 300.00 | —（0） | — |", events[0]["content"])
        self.assertIn("| 型号C | 丁厂 | — | 400.00 | 20（2） | 20.00 |", events[0]["content"])
        assistant._llm.invoke.assert_not_called()
        with patch("application.ai_assistant.llm_service.recommend_tools") as tool:
            unbound = [{**calls[0], "args": {"tool_type": "DISC"}}]  # 拿不到项目时不附表，免得查成全部项目
            for question, tools in (("型号报价区间", calls), (QUESTION, [{**calls[0], "result": '{"error": "failed"}'}]), (QUESTION, []), (QUESTION, unbound)):
                self.assertEqual(assistant._manufacturer_price_table(question, {}, tools), "")
            tool.assert_not_called()

    async def test_generated_table_sync_stream_store_without_revision(self):
        for stream in (False, True):
            data = {**RECOMMENDATIONS, "criteria": {"project_id": "scoped-project"}}
            assistant = self.assistant("跨厂家区间100–200", data, "tool_recommend_tools")
            with patch("application.ai_assistant.llm_service.recommend_tools", return_value=json.dumps(data)) as fetch:
                if stream:
                    events = [e async for e in assistant.chat_stream(QUESTION, {"user_id": 1, "route_mode": "agent"})]
                    answers = [e["content"] for e in events if e["type"] == "answer"]
                    self.assertEqual(len(answers), 1)
                    self.assertNotIn("revising", [e.get("stage") for e in events])
                    answer, trace = answers[0], events[-1]["answer_check"]
                else:
                    result = assistant.chat(QUESTION, {"user_id": 1, "route_mode": "agent"})
                    self.assertTrue(result["success"], result)
                    answer, trace = result["answer"], result["answer_check"]
            self.assertEqual(json.loads(fetch.call_args.args[0])["project_id"], "scoped-project")
            self.assertIn("### 各厂家新刀报价（系统按查询结果生成）", answer)
            self.assertNotIn("回答核对", answer)
            self.assertEqual(trace["generated_tables"], ["manufacturer_prices"])
            self.assertEqual(assistant._store_turn_and_summarize.call_args.args[2], answer)
            assistant._llm.invoke.assert_not_called()

    def test_other_issue_revision_excludes_table_and_keeps_it_before_note(self):
        assistant = self.assistant()
        assistant._llm.invoke.return_value = AIMessage(content="更换数：9")
        tools = [{"tool": "tool_recommend_tools", "args": {}, "result": json.dumps(RECOMMENDATIONS)},
                 {"result": {"replaced_count": 4}}]
        trace = {}
        with patch("application.ai_assistant.llm_service.recommend_tools", return_value=json.dumps(RECOMMENDATIONS)):
            events = list(assistant._revise_agent_answer(QUESTION + "，更换数", "更换数：9", {}, tools, trace, project_id="p1"))
        self.assertEqual([e.get("stage", e["type"]) for e in events], ["revising", "answer", "done"])
        self.assertNotIn("没有逐家列出", str(trace))
        self.assertNotIn("系统按查询结果生成", str(assistant._llm.invoke.call_args.args[0]))
        self.assertLess(events[1]["content"].index("系统按查询结果生成"), events[1]["content"].index("### 回答核对"))

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
