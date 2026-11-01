"""用内存会话回放固定规则题；工具及回答均与直接 ORM 计算的独立真值核对。"""
import copy
import json
import os
import time
from contextlib import ExitStack
from unittest import expectedFailure, skip
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from application.ai_assistant import llm_service
from application.ai_assistant.evaluation.demo_dataset import build_demo_dataset
from application.ai_assistant.evaluation.fixed_suite import collect_gold, load_fixed_cases, score_answer, verify_tool
from application.ai_assistant.memory_service import MemorySnapshot, StoredMessage


class _EphemeralPersistence:
    def __init__(self):
        self.snapshots = {}

    def load(self, scope_key, **kwargs):
        return copy.deepcopy(self.snapshots.get(scope_key) or MemorySnapshot(
            scope_key=scope_key, backend="legacy", message_count=0))

    def append_turn(self, scope_key, question, answer, slots=None, metadata=None, **kwargs):
        current = self.load(scope_key)
        sequence = current.last_sequence
        current.messages.extend([StoredMessage(sequence + 1, "human", question, 0, metadata or {}),
                                 StoredMessage(sequence + 2, "ai", answer, 0, metadata or {})])
        current.slots = dict(slots or {})
        current.message_count = len(current.messages)
        current.latest_sequence = sequence + 2
        current.revision += 1
        self.snapshots[scope_key] = current
        return copy.deepcopy(current)


class FixedQuestionReplayTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        started = time.perf_counter()
        cls.project_id = build_demo_dataset()
        assert build_demo_dataset() == cls.project_id
        cls.dataset_seconds = time.perf_counter() - started
        started = time.perf_counter()
        cls.gold = collect_gold(cls.project_id)
        cls.gold_seconds = time.perf_counter() - started
        cls.replay_seconds = 0
        print(f"\n固定题单：建数 {cls.dataset_seconds:.3f} 秒，独立真值 {cls.gold_seconds:.3f} 秒。", flush=True)

    @classmethod
    def tearDownClass(cls):
        print(f"\n固定题单：回放 {cls.replay_seconds:.3f} 秒。", flush=True)
        super().tearDownClass()

    def _replay(self, case):
        started = time.perf_counter()
        memory = _EphemeralPersistence()
        evidence = self.gold[case["id"]]["evidence"]
        calls = []
        def capture(name, original):
            def invoke(raw):
                traced = llm_service._TRACE.get() is not None
                result = original(raw)
                if traced:
                    calls.append({"name": name, "params": json.loads(raw), "data": json.loads(result)})
                return result
            return invoke
        snapshot = {"snapshot_latest_ring": max(int(row["ring_no"]) for row in evidence["openings"]),
                    "snapshot_total_openings": len(evidence["openings"]),
                    "snapshot_tunneling_coverage": {"ring_min": 1, "ring_max": max(int(row["ring_no"]) for row in evidence["tunnel"])}}
        try:
            with ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {"AI_TRACE_TOOL_RESULTS": "1", "AI_ABLATE_TEMPLATE": "0",
                    "AI_ASSISTANT_POLISH_DIRECT": "0", "AI_ABLATE_MEMORY": "0"}))
                model = stack.enter_context(patch("application.ai_assistant.llm_service.create_chat_model", side_effect=AssertionError("禁止创建模型")))
                stack.enter_context(patch("application.ai_assistant.llm_provider.create_chat_model", side_effect=AssertionError("禁止创建模型")))
                runtime = stack.enter_context(patch.object(llm_service.ToolAssistant, "_ensure_llm_runtime", side_effect=AssertionError("禁止初始化模型")))
                assistant = llm_service.ToolAssistant()
                original_route = assistant._direct_route

                def _route(*args, **kwargs):
                    # 从规则路由起采集证据，范围准备查询不计入规则工具集合。
                    calls.clear()
                    return original_route(*args, **kwargs)

                stack.enter_context(patch.object(assistant, "_direct_route", side_effect=_route))
                stack.enter_context(patch.object(assistant.memory, "load", side_effect=memory.load))
                stack.enter_context(patch.object(assistant.memory, "append_turn", side_effect=memory.append_turn))
                for name in [*llm_service._TOOL_SOURCES, "query_data_catalog"]:
                    stack.enter_context(patch.object(llm_service, name, side_effect=capture(name, getattr(llm_service, name))))
                questions = case.get("turns") or [case["question"]]
                for turn, question in enumerate(questions):
                    calls.clear()
                    result = assistant.chat(question, {**snapshot, "project_id": self.project_id, "require_project": True,
                        "user_id": "fixed-" + case["id"], "route_mode": "rule", "context_mode": "auto", "focus_sources": []})
                    prefix = f"{case['id']} 第 {turn + 1} 轮"
                    self.assertTrue(result["success"], f"{prefix} 回放：实际 {result}，期望成功")
                    self.assertEqual(result["route"], "rule", f"{prefix} 路由：实际 {result.get('route')}，期望 rule")
                    target = self.gold[case["id"]]["turns"][turn]["expect"]
                    for marker in target.get("required_sections", []):
                        self.assertIn(marker, result["answer"], f"{prefix} 输出章节：实际缺少 {marker}，期望出现")
                    self.assertEqual(result["rule_branch"], target["branch"], f"{prefix} 分支：实际 {result['rule_branch']}，期望 {target['branch']}")
                    self.assertEqual([call["name"] for call in calls], [call["name"] for call in target["tools"]],
                                     f"{prefix} 工具集合：实际 {[c['name'] for c in calls]}，期望 {[c['name'] for c in target['tools']]}")
                    for actual, expected in zip(calls, target["tools"]):
                        self.assertEqual(actual["params"], {"project_id": self.project_id, **expected["params"]},
                                         f"{prefix} 工具参数：实际 {actual['params']}，期望 {expected['params']}")
                        self.assertNotIn("error", actual["data"], f"{prefix} 工具结果：实际 {actual['data']}，期望无查询错误")
                        checks = verify_tool(actual["name"], actual["params"], actual["data"], self.gold[case["id"]])
                        self.assertFalse([item for item in checks if not item["passed"]], "\n".join(
                            f"{prefix} {item['check']}：实际 {item['actual']}，期望 {item['expected']}" for item in checks if not item["passed"]))
                    if "memory_slots" in target:
                        stored = next(iter(memory.snapshots.values()))
                        self.assertEqual(stored.slots, target["memory_slots"], f"{prefix} 追问条件：实际 {stored.slots}，期望 {target['memory_slots']}")
                    score = score_answer(case, result["answer"], self.gold, turn)
                    self.assertTrue(score["passed"], "\n".join(issue["detail"] for issue in score["issues"] if issue["kind"] != "format_only"))
                model.assert_not_called()
                runtime.assert_not_called()
        finally:
            type(self).replay_seconds += time.perf_counter() - started


for _case in load_fixed_cases():
    if _case["expected_path"] != "rule":
        continue
    def _test(self, case=_case):
        self._replay(case)
    if _case.get("skip_in_ci"):
        _test = skip(_case["skip_in_ci"])(_test)
    elif _case.get("known_failure"):
        _test = expectedFailure(_test)
    setattr(FixedQuestionReplayTests, "test_" + _case["id"].replace("-", "_"), _test)


class ScoreAnswerTests(SimpleTestCase):
    def _score(self, answer, numbers=(), objects=None, sort=None):
        return score_answer({"id": "q04"}, answer, {"q04": {"turns": [{"numbers": list(numbers),
            "objects": objects, "sort": sort, "expect": {}}]}})

    def test_number_normalization(self):
        for answer, value, unit in (("登记金额 １，２３４．５０ 元", 1234.5, "元"),
                                    ("登记金额 1.2345 万元", 12345, "元"),
                                    ("里程 1,250 米", 1.25, "km"), ("已分类数 3 / 5", 5, "")):
            with self.subTest(answer=answer):
                result = self._score(answer, [{"label": "数值", "value": value, "unit": unit}])
                self.assertTrue(result["passed"], result)
                self.assertGreater(result["numbers"]["format_only"], 0, result)

    def test_empty_record_means_zero_only(self):
        for answer in ("未找到记录", "该范围没有掘进数据"):
            for value, passed in ((0, True), (2, False)):
                result = self._score(answer, [{"label": "记录数", "value": value, "empty": True}])
                self.assertEqual(result["passed"], passed)

    def test_wrong_and_missing_numbers(self):
        fact = {"label": "更换率", "value": 50}
        self.assertEqual(self._score("更换率 49.8%", [fact])["issues"][0]["kind"], "wrong_number")
        self.assertEqual(self._score("没有说明", [fact])["issues"][0]["kind"], "missing_number")

    def test_missing_objects(self):
        result = self._score("| S1L | 8 |", objects=[["S1L"], ["S1R"]])
        self.assertEqual(result["objects"], {"expected": 2, "listed": 1})
        self.assertEqual(result["issues"][0]["kind"], "missing_objects")
        for answer in ("刀位57更换8次，59号刀位更换2次", "| 排名 | 刀位 |\n| --- | --- |\n| 1 | 57 |\n| 2 | 59 |"):
            self.assertTrue(self._score(answer, objects=[["57"], ["59"]])["passed"])

    def test_reversed_sort(self):
        for answer in ("| S1R | 2 |\n| S1L | 8 |", "刀位 S1R 更换2次，刀位 S1L 更换8次"):
            result = self._score(answer, objects=[["S1L"], ["S1R"]], sort=[("S1L", 8), ("S1R", 2)])
            self.assertFalse(result["sort_ok"])
            self.assertEqual(result["issues"][0]["kind"], "bad_sort")
