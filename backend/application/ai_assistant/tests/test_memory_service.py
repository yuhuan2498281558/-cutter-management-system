import os
import tempfile
from unittest.mock import patch

from django.test import TestCase

from application.ai_assistant.memory_service import MemoryService, estimate_tokens


class MemoryServiceTests(TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"AI_MEMORY_DUAL_WRITE": "0", "AI_MEMORY_RECENT_TURNS": "3"})
        self.env.start()
        self.addCleanup(self.env.stop)
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

    def test_token_estimator_is_provider_independent(self):
        self.assertGreater(estimate_tokens("中文"), 0)

    def test_reset_rejects_loaded_generation_and_accepts_new_generation(self):
        snapshot = self.service.append_turn("experiment:generation", "question", "answer")
        self.service.reset(snapshot.scope_key)
        result = self.service.append_turn(snapshot.scope_key, "late", "late answer",
                                          expected_generation=snapshot.generation)
        self.assertEqual(result.message_count, 0)
        self.assertGreater(result.generation, snapshot.generation)
        current = self.service.append_turn(snapshot.scope_key, "fresh", "answer",
                                           expected_generation=result.generation)
        self.assertEqual(current.message_count, 2)

    def test_bounded_context_and_history_pages(self):
        for index in range(10):
            snapshot = self.service.append_turn("experiment:pages", f"q{index}", f"a{index}")
        self.assertEqual(snapshot.message_count, 20)
        self.assertEqual(len(snapshot.messages), 6)
        page = self.service.history_page(snapshot.scope_key, limit=7)
        self.assertEqual([item.sequence for item in page["messages"]], list(range(14, 21)))
        self.assertEqual(page["message_count"], 20)
        previous = self.service.history_page(snapshot.scope_key, limit=7,
                                             before_sequence=page["next_before_sequence"])
        self.assertEqual([item.sequence for item in previous["messages"]], list(range(7, 14)))

    def test_summary_reads_bounded_incremental_history_outside_context(self):
        for index in range(10):
            snapshot = self.service.append_turn("experiment:source", f"q{index}", f"a{index}")
        with patch.dict(os.environ, {"AI_MEMORY_SUMMARY_TRIGGER_TOKENS": "1"}):
            self.assertTrue(self.service.summary_due(snapshot))
        source = self.service.summary_source(snapshot)
        self.assertEqual([item.sequence for item in source], list(range(1, 15)))
        self.assertTrue(self.service.save_summary(snapshot.scope_key, "summary", 14, snapshot.revision))
        updated = self.service.append_turn(snapshot.scope_key, "new", "answer")
        self.assertEqual([item.sequence for item in self.service.summary_source(updated)], [15, 16])

    def test_summary_budget_does_not_advance_through_partial_turn(self):
        for index in range(5):
            snapshot = self.service.append_turn("experiment:budget-source", "问题" * 10, "回答" * 10)
        with patch.dict(os.environ, {"AI_MEMORY_SUMMARY_SOURCE_TOKEN_BUDGET": "40"}):
            self.assertEqual(self.service.summary_source(snapshot), [])
        self.assertEqual(self.service.load(snapshot.scope_key).summary_through_sequence, 0)

    def test_summary_after_reset_cannot_read_new_generation(self):
        for index in range(5):
            old = self.service.append_turn("experiment:summary-reset", "question", "answer")
        self.service.reset(old.scope_key)
        for index in range(5):
            self.service.append_turn(old.scope_key, "new question", "new answer")
        self.assertEqual(self.service.summary_source(old), [])
        self.assertFalse(self.service.save_summary(old.scope_key, "old summary", 4, old.revision))

    def test_dual_write_preserves_slots_in_both_directions_and_reset(self):
        with tempfile.TemporaryDirectory(prefix="ai-dual-write-") as directory:
            database_url = "sqlite:///" + os.path.join(directory, "history.sqlite3")
            legacy = MemoryService(backend="legacy")
            legacy.history_db_url = database_url
            self.service.history_db_url = database_url
            try:
                with patch.dict(os.environ, {"AI_MEMORY_DUAL_WRITE": "1"}):
                    self.service.append_turn("experiment:dual", "question", "answer", slots={"tool_type": "DISC"})
                    self.assertEqual(legacy.load("experiment:dual").slots, {"tool_type": "DISC"})
                    legacy.append_turn("experiment:dual", "next", "answer", slots={"ring_range": [1, 2]})
                    self.assertEqual(self.service.load("experiment:dual").slots, {"ring_range": [1, 2]})
                    self.assertEqual(self.service.load("experiment:dual").message_count, 4)
                    self.assertEqual(legacy.load("experiment:dual").message_count, 4)
                    self.service.reset("experiment:dual")
                    self.assertEqual(legacy.load("experiment:dual").message_count, 0)
                    self.assertEqual(legacy.load("experiment:dual").slots, {})
            finally:
                legacy.close()

    def test_reset_all_invalidates_empty_scope(self):
        snapshot = self.service.load("experiment:empty")
        self.service.reset()
        result = self.service.append_turn(snapshot.scope_key, "late", "answer",
                                          expected_generation=snapshot.generation)
        self.assertEqual(result.message_count, 0)
        self.assertGreater(result.generation, snapshot.generation)
