import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from application.ai_assistant import llm_service
from application.ai_assistant.llm_service import ToolAssistant
from application.ai_assistant.memory_service import MemorySnapshot


def _config():
    return SimpleNamespace(
        provider="test",
        model="test-model",
        base_url="http://test.invalid",
    )


class LazyInitializationTests(SimpleTestCase):
    def test_constructor_only_builds_rule_runtime(self):
        with (
            patch("application.ai_assistant.llm_service.get_llm_config") as get_config,
            patch("application.ai_assistant.llm_service.create_chat_model") as create_model,
            patch("application.ai_assistant.llm_service.create_tool_calling_agent") as create_agent,
        ):
            assistant = ToolAssistant()

        self.assertFalse(assistant.llm_runtime_ready)
        self.assertFalse(assistant.agent_runtime_ready)
        get_config.assert_not_called()
        create_model.assert_not_called()
        create_agent.assert_not_called()

    async def test_rule_stream_keeps_llm_and_agent_cold(self):
        snapshot = MemorySnapshot(scope_key="user:1", backend="legacy")
        with (
            patch("application.ai_assistant.llm_service.create_chat_model") as create_model,
            patch("application.ai_assistant.llm_service.create_tool_calling_agent") as create_agent,
        ):
            assistant = ToolAssistant()
            assistant._load_memory = Mock(return_value=snapshot)
            assistant._resolve_memory_slots = Mock(return_value={})
            assistant._direct_route = Mock(return_value={
                "rule_branch": "tool_change_summary",
                "type": "analysis",
                "answer": "规则答案",
            })
            assistant._store_turn_and_summarize = Mock(return_value=snapshot)

            events = [
                event
                async for event in assistant.chat_stream(
                    "统计当前项目换刀情况",
                    {"user_id": 1, "route_mode": "rule"},
                )
            ]

        self.assertEqual(
            [event["type"] for event in events],
            ["meta", "chunk", "memory", "done"],
        )
        self.assertEqual(events[0]["route_stage"], "rule")
        self.assertEqual(events[1]["content"], "规则答案")
        self.assertFalse(assistant.llm_runtime_ready)
        self.assertFalse(assistant.agent_runtime_ready)
        create_model.assert_not_called()
        create_agent.assert_not_called()

    def test_llm_runtime_does_not_build_agent(self):
        model = object()
        with (
            patch("application.ai_assistant.llm_service.get_llm_config", return_value=_config()) as get_config,
            patch("application.ai_assistant.llm_service.create_chat_model", return_value=model) as create_model,
        ):
            assistant = ToolAssistant()
            self.assertIs(assistant.llm, model)
            self.assertIs(assistant.llm, model)

        self.assertTrue(assistant.llm_runtime_ready)
        self.assertFalse(assistant.agent_runtime_ready)
        get_config.assert_called_once_with(None)
        create_model.assert_called_once_with(None)

    def test_agent_runtime_and_group_executor_are_cached(self):
        all_executor = object()
        group_executor = object()
        with (
            patch("application.ai_assistant.llm_service.get_llm_config", return_value=_config()),
            patch("application.ai_assistant.llm_service.create_chat_model", return_value=object()) as create_model,
        ):
            assistant = ToolAssistant()
            assistant._create_executor = Mock(side_effect=[all_executor, group_executor])

            first = assistant._get_executor_for_query("分析掘进趋势")
            second = assistant._get_executor_for_query("分析掘进趋势")

        self.assertIs(first, group_executor)
        self.assertIs(second, group_executor)
        self.assertTrue(assistant.llm_runtime_ready)
        self.assertTrue(assistant.agent_runtime_ready)
        create_model.assert_called_once_with(None)
        self.assertEqual(assistant._create_executor.call_count, 2)

    def test_concurrent_llm_initialization_runs_once(self):
        model = object()

        def create_model_once(_model_name=None):
            time.sleep(0.05)
            return model

        with (
            patch("application.ai_assistant.llm_service.get_llm_config", return_value=_config()),
            patch(
                "application.ai_assistant.llm_service.create_chat_model",
                side_effect=create_model_once,
            ) as create_model,
        ):
            assistant = ToolAssistant()
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: assistant.llm, range(16)))

        self.assertTrue(all(result is model for result in results))
        create_model.assert_called_once_with(None)

    def test_global_assistant_singleton_is_thread_safe(self):
        original = llm_service._assistant
        sentinel = object()

        def build_once():
            time.sleep(0.05)
            return sentinel

        try:
            llm_service._assistant = None
            with patch(
                "application.ai_assistant.llm_service.ToolAssistant",
                side_effect=build_once,
            ) as assistant_class:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(lambda _: llm_service.get_assistant(), range(16)))
        finally:
            llm_service._assistant = original

        self.assertTrue(all(result is sentinel for result in results))
        assistant_class.assert_called_once_with()

    def test_reset_does_not_initialize_llm_or_agent(self):
        assistant = ToolAssistant()
        assistant._reset_memory_scope = Mock()

        assistant.reset_memory("1")

        assistant._reset_memory_scope.assert_called_once_with("1")
        self.assertFalse(assistant.llm_runtime_ready)
        self.assertFalse(assistant.agent_runtime_ready)
