import io
import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class EvaluationCommandTests(SimpleTestCase):
    def test_commands_require_project_before_any_assistant_call(self):
        for command in ("benchmark_ai_assistant", "regression_ai_assistant"):
            with self.subTest(command=command), patch(
                f"application.ai_assistant.management.commands.{command}.get_assistant"
            ) as assistant:
                with self.assertRaisesMessage(CommandError, "--project-id is required"):
                    call_command(command, stdout=io.StringIO())
                assistant.assert_not_called()

    def test_benchmark_isolates_each_case_and_run_and_passes_project(self):
        module = "application.ai_assistant.management.commands.benchmark_ai_assistant"
        assistant = Mock()
        assistant.chat.return_value = {"success": True, "type": "analysis", "answer": "answer"}
        with tempfile.TemporaryDirectory(prefix="ai-eval-test-") as directory:
            output = os.path.join(directory, "result.json")
            with patch(f"{module}.get_assistant", return_value=assistant), patch(
                f"{module}.get_llm_config", return_value=SimpleNamespace(provider="test", model="test", base_url="")
            ), patch(f"{module}._build_project_snapshot", return_value={"latest_ring_no": 487}):
                for _ in range(2):
                    call_command("benchmark_ai_assistant", project_id="PROJECT-A", route_mode="rule",
                                 questions=["q1", "q2"], user_id="123", output=output, stdout=io.StringIO())
            with open(output, encoding="utf-8") as source:
                result = json.load(source)
        contexts = [call.args[1] for call in assistant.chat.call_args_list]
        self.assertEqual(len({context["user_id"] for context in contexts}), 4)
        self.assertTrue(all(context["project_id"] == "PROJECT-A" for context in contexts))
        self.assertTrue(all(context["route_mode"] == "rule" for context in contexts))
        self.assertTrue(all(context["latest_ring_no"] == 487 for context in contexts))
        self.assertTrue(all(not context["user_id"].isdigit() for context in contexts))
        self.assertEqual(result["summary"]["scope_policy"], "isolated_per_case")

    def test_regression_uses_bound_project_and_separate_case_scopes(self):
        module = "application.ai_assistant.management.commands.regression_ai_assistant"
        assistant = Mock()
        assistant.chat.return_value = {"success": True, "type": "analysis", "answer": "expected"}
        cases = [{"id": str(i), "question": "question", "must_contain": ["expected"]} for i in range(2)]
        with patch(f"{module}.get_assistant", return_value=assistant), patch(
            f"{module}._build_project_snapshot", return_value={}
        ), patch(f"{module}.Command._load_cases", return_value=cases):
            call_command("regression_ai_assistant", project_id="PROJECT-B", stdout=io.StringIO())
        first, second = [call.args[1] for call in assistant.chat.call_args_list]
        self.assertNotEqual(first["user_id"], second["user_id"])
        self.assertEqual(first["project_id"], "PROJECT-B")
        self.assertEqual(second["project_id"], "PROJECT-B")
