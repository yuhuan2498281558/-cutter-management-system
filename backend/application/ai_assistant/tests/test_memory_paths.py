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
