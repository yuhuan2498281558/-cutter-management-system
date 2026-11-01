"""智能助手复用数据分析权限；只使用测试库和假模型。"""
import json
from contextlib import aclosing
from unittest.mock import Mock, patch

from asgiref.sync import async_to_sync
from django.conf import settings
from django.test import RequestFactory, TestCase
from django.utils import timezone
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from application.ai_assistant import llm_service as service, tools, views
from application.ai_assistant.memory_service import MemorySnapshot
from application.ai_assistant.models import AssistantMemoryMessage, AssistantMemoryScope
from application.ai_assistant.tools_lifecycle import trace_tool_lifecycle
from application.ai_assistant.tools_repairs import query_old_tool_repairs
from application.shield.analysis_metrics import ANALYSIS_REQUEST, scoped_queryset
from application.shield.analysis_views import AnalysisViewSet
from application.shield.models import (
    CutterPositionInfo, OldToolRecord, ProjectInfo, ShieldMachineBasicInfo,
    ShieldTunnelingData, StratumBasicInfo, ToolChangeDetail, WarehouseOpeningBasicInfo,
)
from dvadmin.system.models import Dept, Menu, MenuButton, Role, RoleMenuButtonPermission, Users
from dvadmin.utils.filters import DataLevelPermissionMargeFilter


class _ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class DataScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = Dept.objects.create(name="部门甲")
        cls.other_dept = Dept.objects.create(name="部门乙")
        cls.user = Users.objects.create(username="scope-user", dept=cls.dept)
        cls.admin = Users.objects.create(username="scope-admin", is_superuser=True)
        cls.guest = Users.objects.create(username=settings.WEB_GUEST_USERNAME)
        cls.role = Role.objects.create(name="本部门分析", key="scope-role", status=True)
        cls.user.role.add(cls.role)
        menu = Menu.objects.create(name="数据分析", web_path="/shield/analysis")
        cls.button = MenuButton.objects.create(
            menu=menu, name="总览", value="ScopeAnalysisOverview", method=0,
            api="/api/shield/analysis/overview/",
        )
        RoleMenuButtonPermission.objects.create(role=cls.role, menu_button=cls.button, data_range=2)
        cls.project = ProjectInfo.objects.create(
            project_id="SCOPE-A", project_name="项目甲", dept_belong_id=cls.dept.pk,
        )
        cls.other_project = ProjectInfo.objects.create(
            project_id="SCOPE-B", project_name="项目乙", dept_belong_id=cls.other_dept.pk,
        )
        cls.machine = ShieldMachineBasicInfo.objects.create(shield_model_id="SCOPE", shield_model="测试机")
        cls.openings = openings = WarehouseOpeningBasicInfo.objects.bulk_create([
            WarehouseOpeningBasicInfo(
                warehouse_id=f"SCOPE-{ring}", project=project, shield_model=cls.machine,
                ring_no=str(ring), open_time=timezone.now(), dept_belong_id=dept.pk,
            ) for project, dept, ring in (
                (cls.project, cls.dept, 9), (cls.project, cls.other_dept, 100),
                (cls.other_project, cls.other_dept, 200),
            )
        ])
        details = ToolChangeDetail.objects.bulk_create([
            ToolChangeDetail(
                warehouse=opening, cutter_position_no=str(index), tool_parent_type="DISC",
                is_checked=True, is_replaced=True, dept_belong_id=dept.pk,
            ) for index, (opening, dept) in enumerate((
                (openings[0], cls.dept), (openings[0], cls.dept),
                (openings[0], cls.other_dept), (openings[1], cls.other_dept),
                (openings[2], cls.other_dept),
            ), 1)
        ])
        OldToolRecord.objects.bulk_create([
            OldToolRecord(tool_change_detail=detail, old_tool_number=f"OLD-{index}", dept_belong_id=dept.pk)
            for index, (detail, dept) in enumerate(((details[0], cls.dept), (details[1], cls.other_dept)), 1)
        ])
        for dept, ring in ((cls.dept, 9), (cls.other_dept, 100)):
            StratumBasicInfo.objects.create(project=cls.project, ring_no=str(ring), dept_belong_id=dept.pk)
            ShieldTunnelingData.objects.create(
                project=cls.project, shield_machine=cls.machine, ring_no=str(ring),
                record_time=timezone.now(), dept_belong_id=dept.pk,
            )
            CutterPositionInfo.objects.create(
                shield_machine=cls.machine, cutter_position_no="9" if dept == cls.dept else "10",
                tool_type="DISC", dept_belong_id=dept.pk,
            )

    def setUp(self):
        self.enterContext(patch.dict("os.environ", {"AI_ABLATE_TEMPLATE": "0", "AI_ABLATE_MEMORY": "0"}))
        self.model_factory = self.enterContext(patch.object(service, "create_chat_model", side_effect=AssertionError("禁止真实模型")))

    def assistant(self):
        assistant = service.ToolAssistant()
        snapshot = MemorySnapshot(scope_key=f"user:{self.user.pk}", backend="legacy")
        assistant._load_memory = Mock(return_value=snapshot)
        assistant._store_turn_and_summarize = Mock(return_value=snapshot)
        assistant._should_polish_direct_answer = Mock(return_value=False)
        return assistant

    def response(self, user, body, *, streaming=False, token=None):
        if not streaming:
            request = APIRequestFactory().post("/api/ai/chat/", body, format="json")
            force_authenticate(request, user=user, token=token)
            return views.chat(request)
        request = RequestFactory().post("/api/ai/chat/stream/", body, content_type="application/json")
        request.ai_validated_token = token
        with patch.object(views, "_auth_user", return_value=user):
            return async_to_sync(views.chat_stream)(request)

    def test_inaccessible_and_missing_projects_are_rejected_before_model_or_memory(self):
        with patch.object(views, "get_assistant") as get_assistant:
            for project_id in (self.other_project.project_id, "MISSING"):
                for streaming in (False, True):
                    with self.subTest(project_id=project_id, streaming=streaming):
                        response = self.response(self.user, {"query": "换刀汇总", "project_id": project_id}, streaming=streaming)
                        self.assertEqual(response.status_code, 403)
                        expected = {"code": 4030, "msg": "无权查看该项目的数据"}
                        if not streaming:
                            expected["data"] = None
                        self.assertEqual(json.loads(response.content) if streaming else response.data, expected)
                        self.assertFalse(response.streaming)
                        self.assertIsNone(ANALYSIS_REQUEST.get())
            get_assistant.assert_not_called()
        self.model_factory.assert_not_called()
        self.assertFalse(AssistantMemoryScope.objects.exists())
        self.assertFalse(AssistantMemoryMessage.objects.exists())

    def test_rule_snapshot_and_coverage_only_include_visible_records(self):
        assistant = self.assistant()
        body = {"query": "当前项目换刀汇总", "project_id": self.project.project_id, "route_mode": "rule"}
        original = service.query_tool_change_data
        counts = []

        def capture(params):
            result = original(params)
            counts.append(json.loads(result)["total_records"])
            return result

        with patch.object(views, "get_assistant", return_value=assistant), patch.object(
            service, "query_tool_change_data", side_effect=capture,
        ) as query:
            response = self.response(self.user, body)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["data"]["success"], response.data)
        self.assertEqual(response.data["data"]["route_stage"], "rule")
        self.assertEqual(counts, [2])
        query.assert_called_once()
        context = views._context_for_user(self.user, body)
        self.assertEqual(context["snapshot_total_openings"], 1)
        self.assertEqual(context["snapshot_total_changes"], 2)
        self.assertEqual(context["snapshot_total_replaced"], 2)
        self.assertEqual(context["snapshot_total_positions"], 1)
        self.assertEqual(context["snapshot_latest_ring"], 9)
        for key in ("snapshot_tunneling_coverage", "snapshot_stratum_coverage"):
            self.assertEqual(context[key]["record_count"], 1)
            self.assertEqual(context[key]["ring_max"], 9)
        scope_token = ANALYSIS_REQUEST.set(context["data_scope"])
        try:
            result = json.loads(query_old_tool_repairs(json.dumps({"project_id": self.project.project_id})))
            self.assertEqual(result["scope"]["record_count"], 1)
            self.assertEqual(result["records"][0]["old_tool_number"], "OLD-1")
            self.assertEqual(service._data_coverage(self.project.project_id, "开仓")["record_count"], 1)
            self.assertEqual(json.loads(tools.query_tool_change_data(query.call_args.args[0]))["total_records"], 2)
        finally:
            ANALYSIS_REQUEST.reset(scope_token)
        self.assertIsNone(ANALYSIS_REQUEST.get())
        self.model_factory.assert_not_called()

    def test_superuser_and_analysis_guest_keep_full_read_access(self):
        for user in (self.admin, self.guest):
            with self.subTest(user=user.username):
                token = {settings.WEB_GUEST_SESSION_CLAIM: "scope-guest-session-123456"}
                context = views._context_for_user(user, {"project_id": self.project.project_id}, token)
                self.assertEqual(context["snapshot_total_openings"], 2)
                self.assertEqual(context["snapshot_total_changes"], 4)
                self.assertEqual(views._context_for_user(user, {"project_id": self.other_project.project_id}, token)["project_id"],
                                 self.other_project.project_id)
                scope_token = ANALYSIS_REQUEST.set(context["data_scope"])
                try:
                    self.assertEqual(scoped_queryset(ProjectInfo.objects.all()).count(), 2)
                    self.assertEqual(scoped_queryset(ToolChangeDetail.objects.all()).count(), 5)
                finally:
                    ANALYSIS_REQUEST.reset(scope_token)

    def test_sole_visible_project_is_inferred_among_two_projects(self):
        self.assertEqual(ProjectInfo.objects.count(), 2)
        for streaming in (False, True):
            assistant = self.assistant()
            assistant.chat = Mock(return_value={"success": True})
            with patch.object(views, "get_assistant", return_value=assistant):
                response = self.response(self.user, {"query": "换刀汇总"}, streaming=streaming)
            self.assertEqual(response.status_code, 200)
            if not streaming:
                self.assertEqual(assistant.chat.call_args.args[1]["project_id"], self.project.project_id)
            else:
                async def collect():
                    return b"".join([part async for part in response.streaming_content]).decode()
                content = async_to_sync(collect)()
                self.assertIn('"type": "done"', content)
                self.assertEqual(assistant._store_turn_and_summarize.call_args.kwargs["metadata"]["project_id"],
                                 self.project.project_id)
        self.assertIsNone(ANALYSIS_REQUEST.get())

    def test_no_data_scope_preserves_unfiltered_results_and_restores_outer_scope(self):
        params = json.dumps({"project_id": self.project.project_id})
        baseline = tools.query_tool_change_data(params)
        self.assertEqual(json.loads(baseline)["total_records"], 4)
        admin_token = ANALYSIS_REQUEST.set(views._analysis_scope_request(self.admin))
        try:
            self.assertEqual(tools.query_tool_change_data(params), baseline)
        finally:
            ANALYSIS_REQUEST.reset(admin_token)
        scope = views._analysis_scope_request(self.user)
        outer_token = ANALYSIS_REQUEST.set(scope)
        captured = []

        def query(value):
            captured.append(ANALYSIS_REQUEST.get())
            result = tools.query_tool_change_data(value)
            self.assertEqual(result, baseline)
            return result

        try:
            with patch.object(service, "query_tool_change_data", side_effect=query):
                result = self.assistant().chat("当前项目换刀汇总", {"project_id": self.project.project_id, "route_mode": "rule"})
            self.assertTrue(result["success"], result)
            self.assertEqual(captured, [None])
            self.assertIs(ANALYSIS_REQUEST.get(), scope)
        finally:
            ANALYSIS_REQUEST.reset(outer_token)

    def test_agent_tools_receive_scope_in_sync_and_stream_paths(self):
        # 流式工具使用独立线程；TestCase 未提交的数据在调用线程预取，工具桩核对范围传递。
        scope_token = ANALYSIS_REQUEST.set(views._analysis_scope_request(self.user))
        try:
            observation = tools.query_tool_change_data(json.dumps({"project_id": self.project.project_id}))
        finally:
            ANALYSIS_REQUEST.reset(scope_token)
        self.assertEqual(json.loads(observation)["total_records"], 2)
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                assistant = self.assistant()
                assistant._llm = _ToolModel(responses=[
                    AIMessage(content="", tool_calls=[{"name": "tool_query_tool_change_data", "args": {}, "id": "scope-call"}]),
                    AIMessage(content="查询到2条换刀记录。"),
                ])
                assistant._prompt = ChatPromptTemplate.from_messages([
                    ("system", "按查询结果回答。"), MessagesPlaceholder("chat_history"),
                    ("human", "{input}"), MessagesPlaceholder("agent_scratchpad"),
                ])
                assistant._get_tools_for_query = Mock(return_value=service._bind_tools_to_project(
                    [service.tool_query_tool_change_data], self.project.project_id,
                ))
                captured = []

                def query(params):
                    scope = ANALYSIS_REQUEST.get()
                    self.assertIsNotNone(scope)
                    self.assertEqual(scope.user.pk, self.user.pk)
                    self.assertEqual(scope.path, self.button.api)
                    self.assertEqual(scope.method, "GET")
                    self.assertEqual(json.loads(params)["project_id"], self.project.project_id)
                    captured.append(scope)
                    return observation

                with patch.object(views, "get_assistant", return_value=assistant), patch.object(service, "query_tool_change_data", side_effect=query):
                    response = self.response(self.user, {"query": "查询换刀记录", "project_id": self.project.project_id,
                                                         "route_mode": "agent"}, streaming=streaming)
                    self.assertEqual(response.status_code, 200)
                    if streaming:
                        async def collect():
                            content = b"".join([part async for part in response.streaming_content]).decode()
                            self.assertIsNone(ANALYSIS_REQUEST.get())
                            return content
                        self.assertIn('"type": "done"', async_to_sync(collect)())
                    else:
                        self.assertTrue(response.data["data"]["success"], response.data)
                self.assertEqual(len(captured), 1)
                assistant._store_turn_and_summarize.assert_called_once()
                self.assertIsNone(ANALYSIS_REQUEST.get())
        self.model_factory.assert_not_called()

    def test_scope_follows_real_overview_request_not_other_analysis_buttons(self):
        # 分析页其他按钮（如"查看"）配了全部数据，AI 仍只按总览接口的授权取范围
        view = MenuButton.objects.create(menu=self.button.menu, name="查看", value="ScopeAnalysisRetrieve",
                                         method=0, api="/api/shield/analysis/")
        RoleMenuButtonPermission.objects.create(role=self.role, menu_button=view, data_range=3)
        captured = []

        def overview(viewset, request, *args, **kwargs):
            captured.append(ANALYSIS_REQUEST.get())
            return Response({})

        request = APIRequestFactory().get("/api/shield/analysis/overview/")
        force_authenticate(request, user=self.user)
        with patch.object(AnalysisViewSet, "overview", overview):
            self.assertEqual(AnalysisViewSet.as_view({"get": "overview"})(request).status_code, 200)
        scope = views._analysis_scope_request(self.user)
        for model in (ProjectInfo, WarehouseOpeningBasicInfo, ToolChangeDetail, OldToolRecord):
            with self.subTest(model=model.__name__):
                real = DataLevelPermissionMargeFilter().filter_queryset(captured[0], model.objects.all(), None)
                ai = DataLevelPermissionMargeFilter().filter_queryset(scope, model.objects.all(), None)
                self.assertEqual(set(ai.values_list("pk", flat=True)), set(real.values_list("pk", flat=True)))
                self.assertLess(ai.count(), model.objects.count())
        # 总览收紧为仅本人：测试用户没创建过这些记录，项目就不可见
        RoleMenuButtonPermission.objects.filter(role=self.role, menu_button=self.button).update(data_range=0)
        with self.assertRaisesRegex(PermissionError, "无权查看该项目的数据"):
            views._context_for_user(self.user, {"project_id": self.project.project_id})
        self.assertNotIn("project_id", views._context_for_user(self.user, {}))
        RoleMenuButtonPermission.objects.filter(role=self.role, menu_button=self.button).update(data_range=2)
        self.user.dept = None
        self.user.save(update_fields=["dept"])
        with self.assertRaisesRegex(PermissionError, "无权查看该项目的数据"):
            views._context_for_user(self.user, {"project_id": self.project.project_id})

    def test_details_under_hidden_openings_are_not_counted(self):
        # 本部门的明细挂在另一部门的开仓下：数据分析页看不到，AI 也不计
        ToolChangeDetail.objects.bulk_create([ToolChangeDetail(
            warehouse=self.openings[1], cutter_position_no="6", tool_parent_type="DISC",
            is_checked=True, is_replaced=True, dept_belong_id=self.dept.pk,
        )])
        params = json.dumps({"project_id": self.project.project_id})
        self.assertEqual(json.loads(tools.query_tool_change_data(params))["total_records"], 5)
        context = views._context_for_user(self.user, {"project_id": self.project.project_id})
        self.assertEqual(context["snapshot_total_changes"], 2)
        scope_token = ANALYSIS_REQUEST.set(context["data_scope"])
        try:
            self.assertEqual(json.loads(tools.query_tool_change_data(params))["total_records"], 2)
        finally:
            ANALYSIS_REQUEST.reset(scope_token)

    def test_hidden_old_tool_record_is_not_reached_through_visible_detail(self):
        # 本部门明细上挂着另一部门的旧刀记录：看不到旧刀记录，就不给编号匹配和返修金额
        OldToolRecord.objects.filter(old_tool_number="OLD-2").update(repair_price=98765)
        params = json.dumps({"project_id": self.project.project_id, "tool_ids": ["OLD-2"]})
        self.assertIn("98765", trace_tool_lifecycle(params))
        scope_token = ANALYSIS_REQUEST.set(views._analysis_scope_request(self.user))
        try:
            result = trace_tool_lifecycle(params)
        finally:
            ANALYSIS_REQUEST.reset(scope_token)
        self.assertNotIn("98765", result)
        self.assertEqual(json.loads(result)["results"][0]["resolved_by"], "not_found")

    def test_scope_is_restored_after_failure_and_stream_close(self):
        context = views._context_for_user(self.user, {"project_id": self.project.project_id, "route_mode": "rule"})
        assistant = self.assistant()
        assistant._load_memory.side_effect = RuntimeError("测试失败")
        self.assertFalse(assistant.chat("换刀汇总", context)["success"])
        self.assertIsNone(ANALYSIS_REQUEST.get())

        async def close_stream():
            async with aclosing(self.assistant().chat_stream("当前项目换刀汇总", context)) as events:
                self.assertEqual((await anext(events))["type"], "meta")
                self.assertIs(ANALYSIS_REQUEST.get(), context["data_scope"])
            self.assertIsNone(ANALYSIS_REQUEST.get())

        async_to_sync(close_stream)()
        self.assertIsNone(ANALYSIS_REQUEST.get())
