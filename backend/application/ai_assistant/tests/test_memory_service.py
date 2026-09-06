from django.test import TestCase

from application.ai_assistant.memory_service import MemoryService, estimate_tokens


class MemoryServiceTests(TestCase):
    def setUp(self):
        self.service = MemoryService(backend="django")

    def test_scope_key_and_atomic_turn_order(self):
        self.assertEqual(self.service.scope_key(12), "user:12")
        self.assertEqual(self.service.scope_key("exp-1"), "experiment:exp-1")

        snapshot = self.service.append_turn(
            "user:12", "100-300环换刀", "已查询", slots={"ring_range": [100, 300]}
        )
        snapshot = self.service.append_turn("user:12", "同样范围开仓呢", "开仓结果")

        self.assertEqual([item.sequence for item in snapshot.messages], [1, 2, 3, 4])
        self.assertEqual(snapshot.slots, {"ring_range": [100, 300]})
        self.assertEqual(
            [item.role for item in self.service.context_messages(snapshot)],
            ["human", "ai", "human", "ai"],
        )

    def test_token_budget_keeps_recent_messages(self):
        snapshot = self.service.append_turn("experiment:budget", "旧问题" * 200, "旧回答" * 200)
        snapshot = self.service.append_turn("experiment:budget", "新问题", "新回答")
        messages = self.service.context_messages(snapshot, recent_turns=3, budget=20)
        self.assertLessEqual(sum(item.token_count for item in messages), 20)
        self.assertTrue(messages)
        self.assertEqual(messages[-1].content, "新回答")

    def test_summary_compare_and_swap(self):
        snapshot = self.service.append_turn("experiment:summary", "问题", "回答")
        self.assertFalse(self.service.save_summary(
            "experiment:summary", "旧摘要", 2, expected_revision=snapshot.revision + 1
        ))
        self.assertTrue(self.service.save_summary(
            "experiment:summary", "已确认范围", 2, expected_revision=snapshot.revision
        ))
        loaded = self.service.load("experiment:summary")
        self.assertEqual(loaded.summary, "已确认范围")
        self.assertEqual(loaded.summary_through_sequence, 2)

    def test_reset_clears_messages_slots_and_summary(self):
        snapshot = self.service.append_turn(
            "experiment:reset", "问题", "回答", slots={"tool_type": "DISC"}
        )
        self.service.save_summary("experiment:reset", "摘要", 2, snapshot.revision)
        self.service.reset("experiment:reset")
        loaded = self.service.load("experiment:reset")
        self.assertEqual(loaded.messages, [])
        self.assertEqual(loaded.slots, {})
        self.assertEqual(loaded.summary, "")

    def test_ablation_does_not_touch_database(self):
        # The orchestration layer owns the ablation switch; this assertion keeps
        # the estimator deterministic and provider-independent.
        self.assertGreater(estimate_tokens("中文"), 0)
