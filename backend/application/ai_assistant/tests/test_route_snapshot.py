"""首问路由回归只运行判定条件；期望分支来自已签入的固定快照。"""
import json
from unittest.mock import patch

from django.test import SimpleTestCase

from application.ai_assistant.management.commands.update_route_snapshot import (
    SNAPSHOT, build_route_snapshot, snapshot_differences,
)


class RouteSnapshotTests(SimpleTestCase):
    def test_first_question_branches(self):
        expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        bank = [{"id": row["id"], "question": row["question"]} for row in expected if row["suite"] == "question_bank_v4"]
        with patch("application.ai_assistant.llm_provider.create_chat_model", side_effect=AssertionError("禁止创建模型")):
            actual = build_route_snapshot(bank)
        self.assertEqual(len(actual), len(expected), f"首问题数：实际 {len(actual)}，期望 {len(expected)}")
        differences = snapshot_differences(expected, actual)
        self.assertFalse(differences, "\n".join(
            f"{case_id} 首问分支：实际 {new}，期望 {old}（{question}）"
            for case_id, old, new, question in differences))
