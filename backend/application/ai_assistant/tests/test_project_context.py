import asyncio
import json
from unittest.mock import patch

from django.test import SimpleTestCase

from application.ai_assistant.views import _resolve_request_project_id
from application.ai_assistant.llm_service import (
    _bind_tools_to_project,
    tool_query_tool_change_data,
)


class ProjectContextTests(SimpleTestCase):
    def test_explicit_project_is_preserved(self):
        with patch("application.shield.models.ProjectInfo.objects") as manager:
            self.assertEqual(_resolve_request_project_id("P-001"), "P-001")
            manager.values_list.assert_not_called()

    def test_sole_project_is_inferred(self):
        with patch("application.shield.models.ProjectInfo.objects") as manager:
            manager.values_list.return_value.__getitem__.return_value = ["P-ONLY"]
            self.assertEqual(_resolve_request_project_id(), "P-ONLY")

    def test_multiple_projects_are_not_implicitly_aggregated(self):
        with patch("application.shield.models.ProjectInfo.objects") as manager:
            manager.values_list.return_value.__getitem__.return_value = ["P-1", "P-2"]
            self.assertEqual(_resolve_request_project_id(), "")

    def test_agent_tool_uses_request_project_without_exposing_project_argument(self):
        bound_tool = _bind_tools_to_project(
            [tool_query_tool_change_data],
            "P-REQUEST",
        )[0]

        self.assertNotIn("project_id", bound_tool.args)
        with patch(
            "application.ai_assistant.llm_service.query_tool_change_data",
            return_value=json.dumps({"total_records": 0}),
        ) as query:
            bound_tool.invoke({})

        params = json.loads(query.call_args.args[0])
        self.assertEqual(params["project_id"], "P-REQUEST")

    def test_agent_tool_project_binding_is_isolated_per_tool_set(self):
        project_a_tool = _bind_tools_to_project(
            [tool_query_tool_change_data],
            "P-A",
        )[0]
        project_b_tool = _bind_tools_to_project(
            [tool_query_tool_change_data],
            "P-B",
        )[0]

        captured = []

        def capture(params_str):
            captured.append(json.loads(params_str)["project_id"])
            return json.dumps({"total_records": 0})

        with patch(
            "application.ai_assistant.llm_service.query_tool_change_data",
            side_effect=capture,
        ):
            project_a_tool.invoke({})
            project_b_tool.invoke({})
            project_a_tool.invoke({})

        self.assertEqual(captured, ["P-A", "P-B", "P-A"])

    async def test_async_agent_tools_keep_concurrent_project_bindings_isolated(self):
        project_a_tool = _bind_tools_to_project(
            [tool_query_tool_change_data],
            "P-A",
        )[0]
        project_b_tool = _bind_tools_to_project(
            [tool_query_tool_change_data],
            "P-B",
        )[0]
        captured = []

        def capture(params_str):
            captured.append(json.loads(params_str)["project_id"])
            return json.dumps({"total_records": 0})

        with patch(
            "application.ai_assistant.llm_service.query_tool_change_data",
            side_effect=capture,
        ):
            await asyncio.gather(
                project_a_tool.ainvoke({}),
                project_b_tool.ainvoke({}),
            )

        self.assertCountEqual(captured, ["P-A", "P-B"])
