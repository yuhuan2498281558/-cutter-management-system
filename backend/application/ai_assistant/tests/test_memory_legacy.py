import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from langchain_community.chat_message_histories import SQLChatMessageHistory
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from application.ai_assistant.memory_service import MemoryService


class LegacyMemoryTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="ai-memory-test-")
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {"AI_MEMORY_DUAL_WRITE": "0", "AI_MEMORY_RECENT_TURNS": "3"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.service = self.new_service()

    def new_service(self):
        service = MemoryService(backend="legacy")
        service.history_db_url = "sqlite:///" + os.path.join(self.directory.name, "history.sqlite3")
        self.addCleanup(service.close)
        return service

    def test_concurrent_connections_keep_whole_turns_adjacent(self):
        services = [self.new_service() for _ in range(4)]
        for service in services:
            service.load("experiment:concurrent")
        barrier = threading.Barrier(4)

        def append(index):
            barrier.wait(timeout=5)
            return services[index].append_turn("experiment:concurrent", f"q{index}", f"a{index}")

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(append, range(4)))
        page = self.service.history_page("experiment:concurrent")
        self.assertEqual(page["message_count"], 8)
        self.assertEqual([item.role for item in page["messages"]], ["human", "ai"] * 4)
        for question, answer in zip(page["messages"][::2], page["messages"][1::2]):
            self.assertEqual(question.content[1:], answer.content[1:])

    def test_second_insert_failure_rolls_back_question_and_slots(self):
        self.service.load("experiment:failure")
        with self.service._get_legacy_engine().begin() as connection:
            connection.exec_driver_sql("""
                CREATE TRIGGER reject_ai BEFORE INSERT ON message_store
                WHEN NEW.message LIKE '%"type": "ai"%'
                BEGIN SELECT RAISE(FAIL, 'test: reject ai'); END
            """)
        with self.assertRaises(IntegrityError):
            self.service.append_turn("experiment:failure", "question", "answer", slots={"tool_type": "DISC"})
        snapshot = self.service.load("experiment:failure")
        self.assertEqual(snapshot.message_count, 0)
        self.assertEqual(snapshot.slots, {})

    def test_reset_from_other_connection_rejects_inflight_response(self):
        snapshot = self.service.append_turn("experiment:reset", "old", "old answer")
        self.new_service().reset("experiment:reset")
        result = self.service.append_turn(
            "experiment:reset", "late", "late answer", slots={"ring_range": [1, 2]},
            expected_generation=snapshot.generation,
        )
        self.assertGreater(result.generation, snapshot.generation)
        self.assertEqual(result.message_count, 0)
        self.assertEqual(result.slots, {})
        accepted = self.service.append_turn("experiment:reset", "fresh", "fresh answer",
                                            expected_generation=result.generation)
        self.assertEqual(accepted.message_count, 2)

    def test_reset_all_invalidates_even_empty_loaded_scopes(self):
        empty = self.service.load("experiment:empty")
        other = self.service.append_turn("experiment:other", "question", "answer")
        self.new_service().reset()
        for old in (empty, other):
            result = self.service.append_turn(old.scope_key, "late", "answer", expected_generation=old.generation)
            self.assertEqual(result.message_count, 0)
            self.assertGreater(result.generation, old.generation)

    def test_bounded_load_and_cursor_pages_preserve_exact_count(self):
        for index in range(10):
            self.service.append_turn("experiment:pages", f"q{index}", f"a{index}")
            self.service.append_turn("experiment:unrelated", "other", "other answer")
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        engine = self.service._get_legacy_engine()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            snapshot = self.service.load("experiment:pages")
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        self.assertEqual(snapshot.message_count, 20)
        self.assertEqual(len(snapshot.messages), 6)
        content_selects = [sql for sql in statements if "message_store.message" in sql]
        self.assertTrue(content_selects)
        self.assertTrue(all("LIMIT" in sql for sql in content_selects))
        page = self.service.history_page("experiment:pages", limit=7)
        sequences = [item.sequence for item in page["messages"]]
        while page["has_more"]:
            page = self.service.history_page("experiment:pages", limit=7,
                                            before_sequence=page["next_before_sequence"])
            sequences = [item.sequence for item in page["messages"]] + sequences
        self.assertEqual(len(sequences), 20)
        self.assertEqual(sequences, sorted(set(sequences)))

    def test_legacy_format_remains_readable_by_langchain(self):
        self.service.append_turn("experiment:compatibility", "question", "answer", slots={"tool_type": "DISC"})
        history = SQLChatMessageHistory(session_id="compatibility", connection=self.service._get_legacy_engine())
        self.assertEqual([item.content for item in history.messages], ["question", "answer"])
        self.assertEqual(history.messages[0].additional_kwargs["memory_slots"], {"tool_type": "DISC"})

    def test_reads_existing_langchain_history_with_slots(self):
        from langchain_core.messages import AIMessage, HumanMessage
        history = SQLChatMessageHistory(session_id="old", connection=self.service._get_legacy_engine())
        history.add_messages([HumanMessage(content="question", additional_kwargs={
            "memory_slots": {"ring_range": [10, 20]},
        }), AIMessage(content="answer")])
        snapshot = self.service.load("experiment:old")
        self.assertEqual(snapshot.message_count, 2)
        self.assertEqual(snapshot.slots, {"ring_range": [10, 20]})
        updated = self.service.append_turn("experiment:old", "next", "next answer")
        self.assertEqual(updated.slots, {"ring_range": [10, 20]})

    def test_mirror_failure_keeps_committed_primary_turn_without_retry(self):
        mirror = Mock()
        mirror._generation.return_value = 0
        mirror._append_backend_turn.side_effect = RuntimeError("simulated mirror outage")
        with patch.dict(os.environ, {"AI_MEMORY_DUAL_WRITE": "1"}), patch(
            "application.ai_assistant.memory_service.MemoryService", return_value=mirror,
        ), self.assertLogs("application.ai_assistant.memory_service", level="ERROR"):
            snapshot = self.service.append_turn("experiment:mirror-failure", "question", "answer",
                                                 slots={"tool_type": "DISC"})
        self.assertEqual(snapshot.message_count, 2)
        self.assertEqual(snapshot.slots, {"tool_type": "DISC"})
        mirror._append_backend_turn.assert_called_once()
        mirror.close.assert_called_once()

    def test_mirror_receives_generation_captured_before_primary_commit(self):
        mirror = Mock()
        mirror._generation.return_value = 7
        mirror._append_backend_turn.return_value = False
        with patch.dict(os.environ, {"AI_MEMORY_DUAL_WRITE": "1"}), patch(
            "application.ai_assistant.memory_service.MemoryService", return_value=mirror,
        ):
            snapshot = self.service.append_turn("experiment:mirror-reset", "question", "answer")
        self.assertEqual(snapshot.message_count, 2)
        self.assertEqual(mirror._append_backend_turn.call_args.kwargs["expected_generation"], 7)
