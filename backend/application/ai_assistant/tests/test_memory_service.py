import json
import os
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from application.ai_assistant.memory_service import (
    MemoryService, MemorySnapshot, StoredMessage, estimate_tokens,
    serialize_messages,
)


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
        self.assertEqual([item.content for item in messages], ["新问题", "新回答"])

    def test_django_metadata_round_trip_keeps_content_and_public_history_unchanged(self):
        metadata = {"query_intent": {"intent": "change_trend", "interval": 100}}
        snapshot = self.service.append_turn("experiment:metadata", "那全部刀具呢", "查询结果", metadata=metadata)
        self.assertEqual([item.metadata for item in snapshot.messages], [metadata, metadata])
        history = self.service.history_page(snapshot.scope_key)["messages"]
        self.assertEqual([item.metadata for item in history], [metadata, metadata])
        self.assertEqual([item.content for item in self.service.context_messages(snapshot)], ["那全部刀具呢", "查询结果"])
        self.assertTrue(all(set(item) == {"sequence", "role", "content", "token_count"}
                            for item in serialize_messages(history)))
        old = self.service.append_turn("experiment:old-metadata", "旧问题", "旧回答")
        self.assertEqual([item.metadata for item in old.messages], [{}, {}])

    def test_legacy_metadata_round_trip_and_absent_metadata(self):
        with tempfile.TemporaryDirectory(prefix="ai-memory-metadata-") as directory:
            legacy = MemoryService(backend="legacy")
            legacy.history_db_url = "sqlite:///" + os.path.join(directory, "history.sqlite3")
            try:
                metadata = {"query_intent": {"intent": "change_trend", "interval": 100}}
                snapshot = legacy.append_turn("experiment:metadata", "那全部刀具呢", "查询结果", metadata=metadata)
                self.assertEqual([item.metadata for item in snapshot.messages], [metadata, metadata])
                history = legacy.history_page(snapshot.scope_key)["messages"]
                self.assertEqual([item.metadata for item in history], [metadata, metadata])
                self.assertEqual([item.content for item in history], ["那全部刀具呢", "查询结果"])
                old = legacy.append_turn("experiment:no-metadata", "旧问题", "旧回答")
                self.assertEqual([item.metadata for item in old.messages], [{}, {}])
            finally:
                legacy.close()

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
            source = self.service.summary_source(snapshot)
            self.assertEqual([item.role for item in source], ["human", "ai"])
            self.assertEqual(source[-1].sequence, 2)
            self.assertLessEqual(sum(item.token_count for item in source), 40)
            self.assertTrue(snapshot.summary_source_truncated)
            self.assertTrue(self.service.summary_due(snapshot))
        self.assertEqual(self.service.load(snapshot.scope_key).summary_through_sequence, 0)

    def test_oversized_turn_summary_advances_without_changing_original_history(self):
        original = "完整历史" * 10000
        snapshot = self.service.append_turn("experiment:huge-source", original, original)
        for index in range(5):
            snapshot = self.service.append_turn(snapshot.scope_key, f"question{index}", f"answer{index}")
        source = self.service.summary_source(snapshot)
        self.assertEqual([item.sequence for item in source], [1, 2])
        self.assertTrue(all("[不完整摘录]" in item.content for item in source))
        self.assertLessEqual(sum(estimate_tokens(item.content) for item in source), 6000)
        self.assertTrue(self.service.save_summary(snapshot.scope_key, "有界摘要", 2, snapshot.revision))
        updated = self.service.load(snapshot.scope_key)
        self.assertEqual([item.sequence for item in self.service.summary_source(updated)], [3, 4, 5, 6])
        history = self.service.history_page(snapshot.scope_key)["messages"]
        self.assertEqual([item.content for item in history[:2]], [original, original])

    def test_summary_after_reset_cannot_read_new_generation(self):
        for index in range(5):
            old = self.service.append_turn("experiment:summary-reset", "question", "answer")
        self.service.reset(old.scope_key)
        for index in range(5):
            self.service.append_turn(old.scope_key, "new question", "new answer")
        self.assertEqual(self.service.summary_source(old), [])
        self.assertFalse(self.service.save_summary(old.scope_key, "old summary", 4, old.revision))

    def test_reset_rejects_already_cached_summary_source(self):
        for index in range(5):
            old = self.service.append_turn("experiment:cached-reset", "question", "answer")
        source = self.service.summary_source(old)
        self.assertTrue(source)
        self.service.reset(old.scope_key)
        self.assertFalse(self.service.save_summary(
            old.scope_key, "late summary", source[-1].sequence, old.revision,
        ))
        self.assertEqual(self.service.load(old.scope_key).summary, "")

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


class MemoryBudgetTests(SimpleTestCase):
    def setUp(self):
        self.service = MemoryService(backend="django")

    @staticmethod
    def snapshot(contents):
        return MemorySnapshot(scope_key="experiment:budget-unit", messages=[
            StoredMessage(index, role, content, estimate_tokens(content))
            for index, (role, content) in enumerate(contents, start=1)
        ])

    def test_context_never_leaves_answer_when_question_exceeds_budget(self):
        snapshot = self.snapshot([("human", "问" * 100), ("ai", "短答")])
        self.assertEqual(self.service.context_messages(snapshot, budget=20), [])

    def test_legacy_records_without_new_metadata_remain_readable(self):
        rows = [{"id": index, "message": json.dumps({"type": role, "data": {
            "content": content, "additional_kwargs": additional_kwargs,
        }})} for index, role, content, additional_kwargs in [
            (1, "human", "旧问题", {"memory_slots": {"tool_type": "DISC"}}),
            (2, "ai", "旧回答", {}),
            (3, "human", "坏元数据不影响正文", {"memory_metadata": ["invalid"]}),
        ]]
        messages, slots = self.service._decode_legacy_rows(rows)
        self.assertEqual(len(messages), 3)
        self.assertEqual([item.metadata for item in messages], [{}, {}, {}])
        self.assertEqual(slots, {"tool_type": "DISC"})
        self.assertEqual(messages[0].content, "旧问题")

    def test_stored_message_metadata_default_is_not_shared(self):
        first = StoredMessage(1, "human", "one", 1)
        second = StoredMessage(2, "ai", "two", 1)
        first.metadata["query_intent"] = {"intent": "change_trend"}
        self.assertEqual(second.metadata, {})

    def test_context_discards_orphans_and_keeps_recent_complete_turn(self):
        snapshot = self.snapshot([
            ("ai", "孤立回答"), ("human", "未完成问题"), ("human", "完整问题"),
            ("ai", "完整回答"), ("human", "末尾未完成"),
        ])
        messages = self.service.context_messages(snapshot, budget=100)
        self.assertEqual([item.content for item in messages], ["完整问题", "完整回答"])
        snapshot.summary_through_sequence = 3
        self.assertEqual(self.service.context_messages(snapshot, budget=100), [])

    def test_context_zero_token_metadata_still_honors_budget(self):
        snapshot = MemorySnapshot(scope_key="experiment:no-token", messages=[
            StoredMessage(1, "human", "问" * 100), StoredMessage(2, "ai", "回答"),
        ])
        self.assertEqual(self.service.context_messages(snapshot, budget=20), [])

    def test_summary_caps_200_messages_even_for_in_memory_snapshot(self):
        snapshot = self.snapshot([("human", "q"), ("ai", "a")] * 110)
        source = self.service.summary_source(snapshot)
        self.assertEqual(len(source), 200)
        self.assertEqual(source[-1].sequence, 200)

    def test_default_summary_budget_stops_at_complete_turn(self):
        snapshot = self.snapshot([("human", "问" * 100), ("ai", "答" * 100)] * 110)
        with patch.dict(os.environ, {"AI_MEMORY_SUMMARY_SOURCE_TOKEN_BUDGET": "6000"}):
            source = self.service.summary_source(snapshot)
        self.assertEqual(len(source), 40)
        self.assertEqual(sum(item.token_count for item in source), 6000)
        self.assertEqual([item.role for item in source], ["human", "ai"] * 20)

    def test_oversized_question_or_answer_remains_paired_and_bounded(self):
        for question, answer in [("问" * 20000, "短答"), ("短问", "答" * 20000)]:
            with self.subTest(question_size=len(question)):
                snapshot = self.snapshot([("human", question), ("ai", answer)] + [
                    ("human", "q"), ("ai", "a"),
                ] * 3)
                source = self.service.summary_source(snapshot)
                self.assertEqual([item.sequence for item in source], [1, 2])
                self.assertLessEqual(sum(estimate_tokens(item.content) for item in source), 6000)
                self.assertTrue(any("[不完整摘录]" in item.content for item in source))
                self.assertEqual(snapshot.messages[0].content, question)
                self.assertEqual(snapshot.messages[1].content, answer)

    def test_impossibly_small_budget_does_not_emit_unmarked_partial_source(self):
        snapshot = self.snapshot([("human", "问" * 100), ("ai", "答" * 100)] * 4)
        with patch.dict(os.environ, {"AI_MEMORY_SUMMARY_SOURCE_TOKEN_BUDGET": "1"}):
            self.assertEqual(self.service.summary_source(snapshot), [])
