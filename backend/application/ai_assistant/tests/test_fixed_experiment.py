"""只用假 chat、假评分器及内存数据库边界，禁止模型网络请求。"""

import csv
import io
import json
import os
import tempfile
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from application.ai_assistant.management.commands import analyze_fixed_experiment as analyze
from application.ai_assistant.management.commands import run_fixed_experiment as run


CASES = [{"id": f"q{i}", "kind": "quick", "question": f"问题{i}", "focus_sources": [], "expected_path": "rule" if i < 3 else "agent"} for i in range(4)]
FINGERPRINT = {"sha256": "stable", "tables": {}}


class FixedExperimentTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.suite = ModuleType("application.ai_assistant.evaluation.fixed_suite")
        self.suite.load_fixed_cases = Mock(return_value=CASES)
        self.suite.collect_gold = Mock(return_value={c["id"]: {"value": 42} for c in CASES})
        self.suite.score_answer = Mock(side_effect=lambda case, answer, gold, turn=0: {
            "passed": answer == "42", "numbers": {"checked": 1, "correct": int(answer == "42"), "format_only": 0, "wrong": 0, "missing": int(answer != "42")},
            "objects": None, "sort_ok": None, "issues": [] if answer == "42" else [{"kind": "missing_number", "detail": "缺少42"}]})
        self.stack = self.enterContext(ExitStack())
        self.stack.enter_context(patch.dict("sys.modules", {self.suite.__name__: self.suite}))
        self.stack.enter_context(patch.object(run, "readonly", side_effect=lambda: nullcontext()))
        self.stack.enter_context(patch.object(analyze, "readonly", side_effect=lambda: nullcontext()))
        self.stack.enter_context(patch.object(run, "data_fingerprint", return_value=FINGERPRINT))
        self.stack.enter_context(patch.object(analyze, "data_fingerprint", return_value=FINGERPRINT))
        self.stack.enter_context(patch.object(run, "git_info", return_value={"commit": "abc", "dirty": False}))
        self.stack.enter_context(patch.object(run, "project_id", return_value="project"))
        self.stack.enter_context(patch("application.ai_assistant.llm_provider.get_llm_config", return_value=SimpleNamespace(model="fake")))
        self.stack.enter_context(patch("application.ai_assistant.views._build_project_snapshot", return_value={}))
        self.transport = self.stack.enter_context(patch.object(httpx.Client, "_send_single_request", return_value=httpx.Response(200)))
        self.stack.enter_context(patch.object(httpx.AsyncClient, "_send_single_request", side_effect=AssertionError("禁止真实异步网络")))
        self.seen = []
        self.chat = self.stack.enter_context(patch("application.ai_assistant.llm_service.ToolAssistant.chat", autospec=True, side_effect=self.fake_chat))

    def fake_chat(self, assistant, question, context=None):
        from application.ai_assistant.context_budget import ContextUsage
        from application.ai_assistant.messages import AIMessage, HumanMessage, ToolMessage
        signature = {key: os.environ.get(key) for key in run.arm_environment("hybrid")}
        snapshot = assistant.memory.load(assistant.memory.scope_key(context["user_id"]))
        if snapshot.messages:
            _, stats, _ = assistant.memory.protocol_history(snapshot, context["project_id"])
            self.assertEqual(stats["tool_results"], len(snapshot.messages) // 2)
        self.seen.append((question, context.copy(), signature, len(snapshot.messages)))
        # 每轮模拟两次 HTTP：首次生成与核对补全，均穿过真实计数包装。
        for _ in range(2):
            httpx.Client._send_single_request(None, httpx.Request("POST", "https://fake.invalid/chat"))
            message = SimpleNamespace(response_metadata={"model_name": "fake-actual", "token_usage": {
                "prompt_tokens": 10, "completion_tokens": 4, "prompt_cache_hit_tokens": 3}}, usage_metadata=None, tool_calls=[])
            ContextUsage().record_response(message, [], {}, "fake", "fake")
        call_id = f"call-{len(snapshot.messages)}"
        messages = [HumanMessage(content=question), AIMessage(content="", tool_calls=[{"name": "query", "args": {"n": 1}, "id": call_id}]),
                    ToolMessage(content="42", tool_call_id=call_id), AIMessage(content="42")]
        assistant.memory.append_turn(assistant.memory.scope_key(context["user_id"]), question, "42", slots={"ring_range": [1, 10]},
                                     metadata={"project_id": context["project_id"]}, context_messages=messages)
        return {"success": True, "answer": "42", "route": "rule", "route_stage": "rule", "rule_branch": "fake",
                "tool_calls": [{"tool": "query", "args": {"n": 1}}], "answer_check": {"issues_before": []}}

    def execute(self, maximum=100, **options):
        output = io.StringIO()
        call_command("run_fixed_experiment", output_dir=str(self.path), max_model_calls=maximum,
                     arm=options.pop("arm", ["agent"]), repeat=options.pop("repeat", 1), stdout=output, **options)
        return output.getvalue()

    def test_budget_mid_answer_and_resume(self):
        text = self.execute(3)
        self.assertIn("已达到模型请求上限 3", text)
        self.assertEqual(len(run.read_records(self.path)), 1)
        self.assertEqual(len(json.loads((self.path / "model_requests.json").read_text(encoding="utf-8"))), 3)
        self.execute(20, resume=True)
        rows = run.read_records(self.path)
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({(r["case_id"], r["rep"], r["turn"]) for r in rows}), 4)
        self.assertEqual(self.transport.call_count, 9)
        self.assertEqual(rows[0]["provider_usage"], dict(prompt_tokens=20, completion_tokens=8, cache_hit_tokens=6))
        self.assertEqual(rows[0]["actual_models"], ["fake-actual"])
        self.suite.score_answer.assert_not_called()
        before = self.chat.call_count
        self.execute(20, resume=True)
        self.assertEqual(self.chat.call_count, before)

    def test_seeded_order_and_scoped_environment(self):
        external = {key: "external" for key in run.arm_environment("hybrid")}
        with patch.dict(os.environ, external):
            self.execute(200, arm=list(run.ARMS), seed=17)
            self.assertEqual({key: os.environ[key] for key in external}, external)
        rows = run.read_records(self.path)
        self.assertFalse(any(r["arm"] == "hybrid_no_template" and r["case_id"] == "q3" for r in rows))
        expected = [(c["id"], arm, rep) for c, arm, rep in run.make_schedule(CASES, list(run.ARMS), 1, 17)]
        self.assertEqual([(r["case_id"], r["arm"], r["rep"]) for r in rows], expected)
        self.assertNotEqual(expected, [(c["id"], arm, rep) for c, arm, rep in run.make_schedule(CASES, list(run.ARMS), 1, 18)])
        self.assertEqual(expected, [(c["id"], arm, rep) for c, arm, rep in run.make_schedule(CASES, list(run.ARMS), 1, 17)])
        self.assertEqual(len({context["user_id"] for _, context, _, _ in self.seen}), len(rows))
        for row, (_, context, environment, history) in zip(rows, self.seen):
            self.assertEqual(environment, run.arm_environment(row["arm"]))
            self.assertEqual(context["route_mode"], row["config"]["route_mode"])
            self.assertEqual(history, 0)

    def test_chain_resume_restores_history_and_switches_on_exception(self):
        case = {**CASES[0], "turns": ["第一轮", "第二轮"]}
        self.suite.load_fixed_cases.return_value = [case]
        with patch.dict(os.environ, {"AI_ABLATE_ANSWER_CHECK": "original"}):
            self.execute(3, arm=["agent_no_check"])
            self.assertEqual(os.environ["AI_ABLATE_ANSWER_CHECK"], "original")
            self.execute(10, arm=["agent_no_check"], resume=True)
            self.assertEqual(os.environ["AI_ABLATE_ANSWER_CHECK"], "original")
        self.assertEqual([r["turn"] for r in run.read_records(self.path)], [0, 1])
        self.assertEqual([entry[3] for entry in self.seen], [0, 2, 2])

    def test_changed_fingerprint_aborts(self):
        changed = {"sha256": "changed", "tables": {}}
        with patch.object(run, "data_fingerprint", side_effect=[FINGERPRINT, changed]):
            with self.assertRaisesMessage(CommandError, "数据指纹与开始时不同，已中止"):
                self.execute()
        meta = json.loads((self.path / "run_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["data_fingerprint_end"], changed)
        before = self.chat.call_count
        with patch.object(run, "data_fingerprint", return_value=changed):
            with self.assertRaises(CommandError):
                self.execute(resume=True)
        self.assertEqual(self.chat.call_count, before)

    def test_bootstrap_direction_and_report_evidence(self):
        delta = analyze.paired_bootstrap([(.8, .2), (1., .3), (.9, .1)], 1000, 7)
        self.assertGreater(delta["low"], 0)
        self.assertEqual(delta, analyze.paired_bootstrap([(.8, .2), (1., .3), (.9, .1)], 1000, 7))
        ratio = analyze.paired_bootstrap([(1, 20), (2, 40), (3, 60)], 1000, 7, ratio=True)
        self.assertAlmostEqual(ratio["high"], .05)
        self.execute(200, repeat=5, arm=["hybrid", "agent"])
        rows = run.read_records(self.path)
        for row in rows:
            row["latency_ms"] = 1 if row["arm"] == "hybrid" else 20
            if row["arm"] == "agent":
                row["answer"] = "x" * 50 + "42" + "y" * 50
        (self.path / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        with patch.object(analyze, "data_fingerprint", return_value={"sha256": "changed"}):
            call_command("analyze_fixed_experiment", input_dir=str(self.path), bootstrap=1000, stdout=io.StringIO())
        report = (self.path / "analysis.md").read_text(encoding="utf-8")
        self.assertIn("数据已变化，评分可能不准", report)
        self.assertIn("支持。回答中位延迟比", report)
        self.assertIn("多项比较未做校正，结论以区间和题数为准", report)
        with (self.path / "per_case.csv").open(encoding="utf-8-sig", newline="") as source:
            csv_rows = list(csv.DictReader(source))
        self.assertEqual(len(csv_rows), 8)
        failure = json.loads(next(r for r in csv_rows if r["arm"] == "agent")["failures"])[0]
        match = failure["review_contexts"][0]["matches"][0]
        self.assertEqual(match, {"start": 50, "end": 52, "context": "x" * 40 + "42" + "y" * 40})
        self.assertEqual(self.suite.score_answer.call_count, 40)
        self.suite.collect_gold.assert_called_once_with("project")
        self.assertNotIn("score", run.read_records(self.path)[0])

    def test_estimate_uses_five_repeats_without_model(self):
        self.execute(100)
        before = self.chat.call_count
        text = self.execute(0, estimate=True)
        self.assertEqual(self.chat.call_count, before)
        self.assertIn("组 | 题型 | 试跑条数 | 每条请求", text)
        self.assertIn("agent | quick | 4 | 2.00 | 20.00 | 8.00 | 40.00 | 560.00", text)
        self.assertIn("合计完整实验请求数：40.0；完整实验 token：560.0", text)
