import json
from contextlib import ExitStack
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from application.ai_assistant.llm_service import ToolAssistant
from application.ai_assistant.memory_service import MemoryService, MemorySnapshot, StoredMessage


class MemoryPathTests(SimpleTestCase):
    def setUp(self):
        self.assistant = ToolAssistant.__new__(ToolAssistant)
        self.assistant.memory = MemoryService(backend="django")

    def test_explicit_slot_overrides_and_clear(self):
        snapshot = MemorySnapshot(
            scope_key="user:1",
            slots={"ring_range": [100, 300], "tool_type": "DISC", "cutter_position_no": "S14R"},
        )
        resolved = self.assistant._resolve_memory_slots("那 S15R 呢", snapshot)
        self.assertEqual(resolved["cutter_position_no"], "S15R")
        self.assertEqual(resolved["ring_range"], [100, 300])

        cleared = self.assistant._resolve_memory_slots("取消范围的换刀情况", snapshot)
        self.assertNotIn("ring_range", cleared)

    def test_intent_policy_does_not_leak_detail_filters_to_opening(self):
        context = {
            "memory_slots": {
                "ring_range": [100, 300],
                "tool_type": "DISC",
                "cutter_position_no": "S14R",
            }
        }
        params = self.assistant._context_params("同样范围，开仓情况呢", context)
        self.assertEqual(params["ring_range"], [100, 300])
        self.assertIsNone(params["tool_type"])
        self.assertNotIn("cutter_position_no", params)

    def test_independent_all_tool_queries_do_not_inherit_ring_scope(self):
        snapshot = MemorySnapshot(scope_key='user:1', slots={'tool_type': 'DISC', 'ring_range': [100, 300]})
        for query in ['统计全部刀具的换刀次数和频率', '统计所有刀具换刀情况', '不分刀型统计换刀次数',
                      '统计当前项目全部刀具换刀情况，列出检查数、更换数、更换率和主要磨损类型']:
            with self.subTest(query=query):
                slots = self.assistant._resolve_memory_slots(query, snapshot)
                params = self.assistant._context_params(query, {'project_id': 'test', 'memory_slots': slots})
                self.assertNotIn('tool_type', slots)
                self.assertIsNone(params['tool_type'])
                self.assertIsNone(params['ring_range'])

    def test_all_disc_records_still_filters_disc_and_followup_keeps_type(self):
        snapshot = MemorySnapshot(scope_key='user:1', slots={'tool_type': 'SCRAPER'})
        for query in ['统计全部滚刀换刀情况', '统计所有刀具中的滚刀换刀情况']:
            slots = self.assistant._resolve_memory_slots(query, snapshot)
            self.assertEqual(slots['tool_type'], 'DISC')
        self.assertEqual(self.assistant._resolve_memory_slots('同样范围的换刀频率呢', snapshot)['tool_type'], 'SCRAPER')

    def test_memory_messages_use_summary_and_bounded_recent_history(self):
        snapshot = MemorySnapshot(
            scope_key="user:1",
            summary="已确认关注换刀范围",
            slots={"ring_range": [100, 300]},
            messages=[
                StoredMessage(1, "human", "旧问题", 2),
                StoredMessage(2, "ai", "旧回答", 2),
                StoredMessage(3, "human", "新问题", 2),
                StoredMessage(4, "ai", "新回答", 2),
            ],
            summary_through_sequence=2,
        )
        messages = self.assistant._memory_messages(snapshot, {"memory_slots": snapshot.slots})
        self.assertIn("当前工作状态", messages[0].content)
        self.assertIn("历史摘要", messages[1].content)
        self.assertEqual([item.content for item in messages[-2:]], ["新问题", "新回答"])

    def test_ablation_drops_persisted_slots(self):
        snapshot = MemorySnapshot(scope_key="user:1", backend="ablate", slots={"ring_range": [1, 2]})
        self.assertEqual(self.assistant._resolve_memory_slots("滚刀换刀情况", snapshot), {})

    def test_relative_window_and_segment_interval_are_not_absolute_rings(self):
        self.assertEqual(
            self.assistant._extract_ring_range("统计最近100环的换刀情况"),
            [],
        )
        self.assertEqual(
            self.assistant._extract_ring_range("按50环为一段统计换刀趋势"),
            [],
        )
        self.assertEqual(
            self.assistant._extract_ring_range("统计100环到300环的换刀趋势"),
            [100, 300],
        )

    def test_interval_extraction_and_corrupted_slot_cleanup(self):
        self.assertEqual(
            self.assistant._extract_interval("按60环为一段统计换刀趋势"),
            60,
        )
        snapshot = MemorySnapshot(
            scope_key="user:1",
            slots={"ring_range": [50, 50]},
        )
        resolved = self.assistant._resolve_memory_slots(
            "按50环为一段统计换刀趋势",
            snapshot,
        )
        self.assertNotIn("ring_range", resolved)

    def test_recent_window_drops_stale_absolute_range(self):
        snapshot = MemorySnapshot(
            scope_key="user:1",
            slots={"ring_range": [50, 50]},
        )
        resolved = self.assistant._resolve_memory_slots(
            "统计最近100环的换刀情况",
            snapshot,
        )
        self.assertNotIn("ring_range", resolved)

    def test_scope_transitions(self):
        snapshot = MemorySnapshot(scope_key="user:1", slots={
            "ring_range": [100, 300], "tool_type": "DISC", "cutter_position_no": "30",
        })
        cases = [
            ("取消滚刀限制", {}, {"ring_range": [100, 300]}),
            ("清除刀型限制", {}, {"ring_range": [100, 300]}),
            ("取消滚刀限制，改查刮刀换刀情况", {}, {"ring_range": [100, 300], "tool_type": "SCRAPER"}),
            ("取消范围的换刀情况", {}, {"tool_type": "DISC", "cutter_position_no": "30"}),
            ("取消刀位限制", {}, {"ring_range": [100, 300], "tool_type": "DISC"}),
            ("那刮刀呢", {}, {"ring_range": [100, 300], "tool_type": "SCRAPER"}),
            ("同样范围统计全部刀具换刀情况", {}, {"ring_range": [100, 300]}),
            ("统计刮刀换刀情况", {}, {"tool_type": "SCRAPER"}),
            ("统计全部刀具换刀情况", {}, {}),
            ("统计400环到500环滚刀换刀情况", {}, {"ring_range": [400, 500], "tool_type": "DISC"}),
            ("同样范围统计换刀情况", {"context_mode": "new"}, {}),
            ("统计换刀情况", {"context_mode": "continue"}, dict(snapshot.slots)),
            ("统计换刀情况", {"context_mode": "continue", "clear_slots": ["tool_type"]}, {"ring_range": [100, 300]}),
            ("统计换刀情况", {"clear_slots": ["ring_range"]}, {"tool_type": "DISC", "cutter_position_no": "30"}),
            ("统计滚刀换刀情况", {"context_mode": "new", "clear_slots": ["tool_type"]}, {}),
            ("那S15R呢", {}, {"ring_range": [100, 300], "cutter_position_no": "S15R"}),
            ("同样范围看刮刀S15R刀位换刀情况", {}, {"ring_range": [100, 300], "tool_type": "SCRAPER", "cutter_position_no": "S15R"}),
        ]
        for query, context, expected in cases:
            with self.subTest(query=query, context=context):
                working = self.assistant._prepare_query_context(query, snapshot, context)
                self.assertEqual(working["memory_slots"], expected)
                params = self.assistant._context_params(working["effective_query"], working)
                for field in ("ring_range", "tool_type", "cutter_position_no"):
                    self.assertEqual(params.get(field), expected.get(field))

    def test_intent_filters_apply_before_model_context_and_metadata(self):
        snapshot = MemorySnapshot(scope_key="user:1", slots={
            "ring_range": [100, 300], "tool_type": "DISC", "cutter_position_no": "30",
        })
        for query, expected in [
            ("同样范围查询开仓记录情况", {"ring_range": [100, 300]}),
            ("同样范围查询地层分布", {"ring_range": [100, 300]}),
            ("同样范围查询刀位更换排行", {"ring_range": [100, 300], "tool_type": "DISC"}),
            ("同样范围统计换刀趋势", {"ring_range": [100, 300], "tool_type": "DISC"}),
        ]:
            with self.subTest(query=query):
                working = self.assistant._prepare_query_context(query, snapshot)
                self.assertEqual(working["memory_slots"], expected)
                self.assertEqual(self.assistant._memory_diagnostics(snapshot, working)["active_slots"], expected)
                if "tool_type" not in expected:
                    self.assertNotIn("DISC", self.assistant._build_context_message(working))

    def test_new_query_omits_old_summary_and_raw_history(self):
        snapshot = MemorySnapshot(scope_key="user:1", summary="旧范围滚刀", slots={"tool_type": "DISC"}, messages=[
            StoredMessage(1, "human", "统计滚刀换刀情况", 5), StoredMessage(2, "ai", "旧答案", 5),
        ])
        new = self.assistant._prepare_query_context("统计全部刀具换刀情况", snapshot)
        self.assertEqual(self.assistant._memory_messages(snapshot, new), [])
        self.assertEqual(self.assistant._memory_diagnostics(snapshot, new)["active_slots"], {})
        continued = self.assistant._prepare_query_context("同样范围统计换刀情况", snapshot)
        self.assertTrue(self.assistant._memory_messages(snapshot, continued))

    def test_short_followup_carries_intent_without_reintroducing_old_filters(self):
        snapshot = MemorySnapshot(scope_key="user:1", slots={"tool_type": "DISC", "ring_range": [100, 300]}, messages=[
            StoredMessage(1, "human", "统计100环到300环滚刀换刀情况", 5),
            StoredMessage(2, "ai", "旧答案", 5),
        ])
        working = self.assistant._prepare_query_context("那刮刀呢", snapshot)
        self.assertTrue(self.assistant._needs_tool_call(working["effective_query"]))
        self.assertNotIn("滚刀", working["effective_query"])
        with patch("application.ai_assistant.llm_service.query_tool_change_data", return_value=json.dumps({
            "total_records": 3, "replaced_count": 2, "replacement_rate": 66.7, "wear_distribution": [],
        })) as tool:
            result = self.assistant._direct_route(working["effective_query"], working)
        self.assertEqual(result["rule_branch"], "tool_change_summary")
        self.assertEqual(json.loads(tool.call_args.args[0])["tool_type"], "SCRAPER")

    def test_recent_range_is_actual_scope_and_recomputed_for_new_window(self):
        snapshot = MemorySnapshot(scope_key="user:1", slots={"ring_range": [1, 2], "tool_type": "DISC"})
        with patch.object(self.assistant, "_recent_ring_range", return_value=[388, 487]):
            working = self.assistant._prepare_query_context("统计最近100环换刀情况", snapshot, {"project_id": "TEST"})
        self.assertEqual(working["memory_slots"], {"ring_range": [388, 487]})
        self.assertEqual(self.assistant._memory_diagnostics(snapshot, working)["active_slots"], {"ring_range": [388, 487]})

    async def test_sync_and_stream_save_same_effective_slots_and_original_question(self):
        snapshot = MemorySnapshot(scope_key="user:1", slots={"ring_range": [100, 300], "tool_type": "DISC", "cutter_position_no": "30"})
        snapshot.messages = [StoredMessage(1, "human", "统计100环到300环滚刀换刀情况", 5), StoredMessage(2, "ai", "旧回答", 5)]
        assistant = ToolAssistant()
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._direct_route = Mock(return_value={"answer": "已查询", "type": "analysis", "rule_branch": "tool_change_summary"})
        assistant._store_turn_and_summarize = Mock(return_value=snapshot)
        assistant._polish_direct_answer = Mock(return_value=("已查询", {}))
        query = "取消滚刀限制"
        sync_result = assistant.chat(query, {"user_id": 1, "project_id": "TEST"})
        stream = [event async for event in assistant.chat_stream(query, {"user_id": 1, "project_id": "TEST"})]
        for call in assistant._store_turn_and_summarize.call_args_list:
            self.assertEqual(call.args[1], query)
            self.assertEqual(call.args[3], {"ring_range": [100, 300]})
            self.assertEqual(call.kwargs["metadata"]["query_intent"]["intent"], "tool_change_summary")
        self.assertEqual(sync_result["memory"]["active_slots"], {"ring_range": [100, 300]})
        memory = next(event for event in stream if event["type"] == "memory")
        self.assertEqual(memory["active_slots"], sync_result["memory"]["active_slots"])
        self.assertEqual(memory["context_mode"], "continue")

    def test_short_followups_keep_branch_and_query_controls(self):
        cases = [
            ("统计100环到300环滚刀换刀次数频率", "那全部刀具呢", "change_trend", "query_tool_change_trend", {"ring_range": [100, 300], "tool_type": None, "interval": 50}),
            ("按100环为一段统计滚刀换刀趋势", "全部刀具呢", "change_trend", "query_tool_change_trend", {"tool_type": None, "interval": 100}),
            ("查询100环到300环掘进异常", "那400环到500环呢", "tunneling_anomaly", "query_tunneling_anomaly", {"ring_range": [400, 500]}),
            ("查询最近3次开仓记录", "那100环到300环呢", "opening", "query_opening_records", {"ring_range": [100, 300], "limit": 3}),
            ("统计前5个刀位更换排行", "那滚刀呢", "cutter_position", "query_cutter_position_stats", {"tool_type": "DISC", "top_n": 5}),
        ]
        for first, followup, branch, tool_name, expected in cases:
            with self.subTest(first=first):
                initial = self.assistant._prepare_query_context(first, MemorySnapshot(scope_key="user:1"))
                snapshot = MemorySnapshot(scope_key="user:1", slots=initial["memory_slots"], messages=[
                    StoredMessage(1, "human", first, 5), StoredMessage(2, "ai", "前一回答", 5),
                ])
                context = self.assistant._prepare_query_context(followup, snapshot, {"project_id": "TEST"})
                with patch(f"application.ai_assistant.llm_service.{tool_name}", return_value="{}") as tool:
                    result = self.assistant._direct_route(context["effective_query"], context)
                self.assertEqual(result["rule_branch"], branch)
                params = json.loads(tool.call_args.args[0])
                for key, value in expected.items():
                    self.assertEqual(params.get(key), value)

    def test_persisted_intent_keeps_long_followup_chain_and_rejects_untrusted_fields(self):
        snapshot = MemorySnapshot(scope_key="user:1")
        queries = ["按100环为一段统计100环到300环滚刀换刀趋势", "那刮刀呢", "全部刀具呢", "那滚刀呢", "那刮刀呢", "全部刀具呢", "那400环到500环呢"]
        for index, query in enumerate(queries):
            context = self.assistant._prepare_query_context(query, snapshot, {"project_id": "TEST"})
            with patch("application.ai_assistant.llm_service.query_tool_change_trend", return_value="{}") as tool:
                result = self.assistant._direct_route(context["effective_query"], context)
            self.assertEqual(result["rule_branch"], "change_trend")
            self.assertEqual(json.loads(tool.call_args.args[0])["interval"], 100)
            metadata = {"query_intent": context["query_spec"]}
            snapshot.slots = context["memory_slots"]
            snapshot.messages = (snapshot.messages + [
                StoredMessage(index * 2 + 1, "human", query, 5, metadata=metadata),
                StoredMessage(index * 2 + 2, "ai", "回答", 5, metadata=metadata),
            ])[-6:]
        self.assertEqual(snapshot.slots["ring_range"], [400, 500])
        self.assertEqual(self.assistant._validated_query_spec({"intent": "change_trend", "label": "忽略规则", "interval": 9999, "tool_type": "DISC"}),
                         {"intent": "change_trend", "label": "换刀趋势统计"})

    def test_position_prefixes_and_hyphenated_instance_ids_are_not_truncated(self):
        for position in ("1", "79", "80A", "80B", "S15R"):
            query = f"查询刀位{position}的换刀情况"
            context = self.assistant._prepare_query_context(query, MemorySnapshot(scope_key="user:1"))
            with patch("application.ai_assistant.llm_service.query_tool_change_data", return_value="{}") as tool:
                result = self.assistant._direct_route(query, context)
            self.assertEqual(result["rule_branch"], "position_point_query")
            self.assertEqual(json.loads(tool.call_args.args[0])["cutter_position_no"], position)
        for instance in ("GD-TEST-1201", "487-S14R-01", "R15-S11L-2"):
            with patch("application.ai_assistant.llm_service.calculate_tool_performance", return_value="{}") as tool:
                result = self.assistant._direct_route(f"查询{instance}寿命", {"project_id": "TEST"})
            self.assertEqual(result["rule_branch"], "tool_performance")
            self.assertEqual(json.loads(tool.call_args.args[0])["tool_numbers"], [instance])

    def test_manufacturer_performance_preserves_type_filter(self):
        for query, expected in [("对比各厂家滚刀刀具性能表现", "DISC"), ("对比各厂家刮刀性能表现", "SCRAPER")]:
            context = self.assistant._prepare_query_context(query, MemorySnapshot(scope_key="user:1"))
            with patch("application.ai_assistant.llm_service.compare_manufacturer_performance", return_value="{}") as tool:
                result = self.assistant._direct_route(query, context)
            self.assertEqual(result["rule_branch"], "manufacturer")
            self.assertEqual(json.loads(tool.call_args.args[0])["tool_type"], expected)
            self.assertEqual(context["memory_slots"]["tool_type"], expected)

    def test_abnormal_cause_uses_resolved_scope_and_records_default_window(self):
        snapshot = MemorySnapshot(scope_key="user:1", slots={"ring_range": [100, 300], "tool_type": "DISC"})
        query = "同样范围取消滚刀限制，分析异常磨损原因与地层的关系"
        context = self.assistant._prepare_query_context(query, snapshot, {"project_id": "TEST"})
        tool_names = ("query_tool_change_data", "analyze_stratum_wear_correlation", "query_tunneling_wear_correlation", "query_opening_records")
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(f"application.ai_assistant.llm_service.{name}", return_value="{}")) for name in tool_names]
            recent = stack.enter_context(patch.object(self.assistant, "_recent_ring_range", return_value=[388, 487]))
            result = self.assistant._direct_route(query, context)
            recent.assert_not_called()
        self.assertEqual(result["rule_branch"], "recent_abnormal_wear_cause")
        for tool in mocks:
            params = json.loads(tool.call_args.args[0])
            self.assertEqual(params["ring_range"], [100, 300])
            self.assertFalse(params.get("tool_type"))
        context = self.assistant._prepare_query_context("分析近期异常磨损原因", MemorySnapshot(scope_key="user:1"), {"project_id": "TEST"})
        with ExitStack() as stack:
            for name in tool_names:
                stack.enter_context(patch(f"application.ai_assistant.llm_service.{name}", return_value="{}"))
            stack.enter_context(patch.object(self.assistant, "_recent_ring_range", return_value=[388, 487]))
            self.assistant._direct_route("分析近期异常磨损原因", context)
        self.assertEqual(context["memory_slots"], {"ring_range": [388, 487]})

    def test_actual_total_cost_does_not_become_model_cost_recommendation(self):
        query = "当前项目实际刀具采购加返修总成本是多少"
        with patch("application.ai_assistant.llm_service.recommend_tools") as recommend:
            result = self.assistant._direct_route(query, {"project_id": "TEST"})
        self.assertEqual(result["rule_branch"], "unsupported_actual_total_cost")
        self.assertIn("无法给出实际总成本", result["answer"])
        self.assertIn("不能替代", result["answer"])
        recommend.assert_not_called()

    def test_explicit_range_clear_cannot_be_replaced_by_recent_defaults(self):
        snapshot = MemorySnapshot(scope_key="user:1", slots={"ring_range": [100, 300]})
        cases = [
            ("分析近期异常磨损原因", {"clear_slots": ["ring_range"]}, "recent_abnormal_wear_cause"),
            ("取消范围限制，分析近期异常磨损原因", {}, "recent_abnormal_wear_cause"),
            ("统计近期换刀情况", {"clear_slots": ["ring_range"]}, "tool_change_summary"),
            ("统计最近100环换刀情况", {"clear_slots": ["ring_range"]}, "recent_ring_tool_change"),
        ]
        for query, options, branch in cases:
            with self.subTest(query=query):
                with ExitStack() as stack:
                    recent = stack.enter_context(patch.object(self.assistant, "_recent_ring_range", return_value=[388, 487]))
                    tool_names = ("query_tool_change_data", "analyze_stratum_wear_correlation", "query_tunneling_wear_correlation", "query_opening_records")
                    mocks = [stack.enter_context(patch(f"application.ai_assistant.llm_service.{name}", return_value="{}")) for name in tool_names]
                    context = self.assistant._prepare_query_context(query, snapshot, {"project_id": "TEST", **options})
                    result = self.assistant._direct_route(context["effective_query"], context)
                self.assertEqual(result["rule_branch"], branch)
                recent.assert_not_called()
                self.assertNotIn("ring_range", context["memory_slots"])
                for tool in mocks:
                    for call in tool.call_args_list:
                        self.assertFalse(json.loads(call.args[0]).get("ring_range"))
                if branch == "recent_abnormal_wear_cause":
                    self.assertIn("全项目范围", result["answer"])
