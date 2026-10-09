import os
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from application.ai_assistant.memory_service import MemoryService


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks and independent connections")
class DjangoMemoryConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"AI_MEMORY_DUAL_WRITE": "0"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_parallel_turns_keep_unique_sequence_and_adjacent_pairs(self):
        service = MemoryService(backend="django")
        snapshot = service.load("experiment:concurrent")
        barrier = threading.Barrier(4)

        def append(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return MemoryService(backend="django").append_turn(
                    snapshot.scope_key, f"q{index}", f"a{index}",
                    expected_generation=snapshot.generation,
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(append, range(4)))
        messages = service.history_page(snapshot.scope_key)["messages"]
        self.assertEqual([item.sequence for item in messages], list(range(1, 9)))
        self.assertEqual([item.role for item in messages], ["human", "ai"] * 4)
        for question, answer in zip(messages[::2], messages[1::2]):
            self.assertEqual(question.content[1:], answer.content[1:])

    def test_reset_completed_on_other_connection_rejects_waiting_response(self):
        service = MemoryService(backend="django")
        snapshot = service.load("experiment:reset-concurrent")
        loaded = threading.Event()
        reset_done = threading.Event()

        def answer():
            close_old_connections()
            try:
                worker = MemoryService(backend="django")
                old = worker.load(snapshot.scope_key)
                loaded.set()
                if not reset_done.wait(timeout=10):
                    raise AssertionError("reset did not complete")
                return worker.append_turn(old.scope_key, "late", "answer", expected_generation=old.generation)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(answer)
            self.assertTrue(loaded.wait(timeout=10))
            service.reset(snapshot.scope_key)
            reset_done.set()
            result = pending.result(timeout=10)
        self.assertEqual(result.message_count, 0)
        self.assertGreater(result.generation, snapshot.generation)
