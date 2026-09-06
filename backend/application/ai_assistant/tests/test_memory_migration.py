import json
import os
import tempfile

from django.core.management import call_command
from django.test import TestCase

from sqlalchemy import create_engine, text

from application.ai_assistant.models import AssistantMemoryMessage


class MemoryMigrationTests(TestCase):
    def test_migrate_legacy_history_is_idempotent_and_skips_experiments(self):
        handle, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        try:
            engine = create_engine(f"sqlite:///{path}")
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE TABLE message_store (id INTEGER PRIMARY KEY, "
                    "session_id VARCHAR(255), message TEXT)"
                ))
                conn.execute(text(
                    "INSERT INTO message_store (id, session_id, message) VALUES "
                    "(1, '7', :human), (2, '7', :ai), (3, 'exp-1', :exp), "
                    "(4, '7', :broken)"
                ), {
                    "human": json.dumps({"type": "human", "data": {"content": "问题"}}),
                    "ai": json.dumps({"type": "ai", "data": {"content": "回答"}}),
                    "exp": json.dumps({"type": "human", "data": {"content": "实验"}}),
                    "broken": "not-json",
                })

            call_command("migrate_ai_history", database_url=f"sqlite:///{path}")
            self.assertEqual(
                AssistantMemoryMessage.objects.filter(scope__scope_key="user:7").count(),
                2,
            )
            call_command("migrate_ai_history", database_url=f"sqlite:///{path}")
            self.assertEqual(
                AssistantMemoryMessage.objects.filter(scope__scope_key="user:7").count(),
                2,
            )
        finally:
            if "engine" in locals():
                engine.dispose()
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
