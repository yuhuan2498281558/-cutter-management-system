import json
import shutil
import tempfile
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient, APIRequestFactory

from dvadmin.system.models import Role, Users
from application.shield.models import (
    CutterImageAnnotation,
    CutterPositionInfo,
    MobileToolChangeTask,
    ProjectInfo,
    ShieldMachineBasicInfo,
    StratumBasicInfo,
    ToolCost,
    ToolChangeDetail,
    ToolInfo,
    ToolInstance,
    NewToolRecord,
    OldToolRecord,
    WarehouseOpeningBasicInfo,
)
from application.shield.mobile_views import (
    AdminMobileTaskViewSet,
    MobileTaskViewSet,
    ToolLifecycleViewSet,
    mobile_field_options,
    old_tool_inspection_payload,
    resolve_task_positions,
    scoped_details,
)
from application.shield.mobile_views import MobileToolChangeDetailSerializer
from application.shield.views import (
    CutterImageAnnotationViewSet,
    ToolChangeDetailCreateUpdateSerializer,
    ToolChangeDetailViewSet,
    WarehouseOpeningCompletionSerializer,
    WarehouseOpeningBasicInfoCreateUpdateSerializer,
    _build_opening_stratum_context,
)
from application.shield.trajectory import get_tool_trajectory
from application.shield.cutter_position_scope import (
    ACTIVE_CUTTER_POSITION_CODES,
    is_active_cutter_position,
)


class ToolChangeFlowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._test_media_root = tempfile.mkdtemp(prefix="shield-test-media-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._test_media_root)
        cls._media_override.enable()
        try:
            super().setUpClass()
        except Exception:
            cls._media_override.disable()
            shutil.rmtree(cls._test_media_root, ignore_errors=True)
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            cls._media_override.disable()
            shutil.rmtree(cls._test_media_root, ignore_errors=True)

    def setUp(self):
        recorder_role = Role.objects.create(name="录入员", key="mobile_recorder")
        self.first_operator = Users.objects.create(
            username="tool-flow-first",
            name="第一录入员",
            is_active=True,
            is_staff=True,
            is_superuser=False,
        )
        self.second_operator = Users.objects.create(
            username="tool-flow-second",
            name="第二录入员",
            is_active=True,
            is_staff=True,
            is_superuser=False,
        )
        self.first_operator.role.add(recorder_role)
        self.second_operator.role.add(recorder_role)
        project = ProjectInfo.objects.create(project_id="TEST-PROJECT", project_name="测试项目")
        shield = ShieldMachineBasicInfo.objects.create(shield_model_id="TEST-SHIELD", shield_model="测试盾构机")
        tool_info = ToolInfo.objects.create(tool_parent_type="DISC", tool_type_name="测试滚刀")
        CutterPositionInfo.objects.create(
            shield_machine=shield,
            cutter_position_no="1",
            tool_type="DISC",
            tool_info=tool_info,
        )
        CutterPositionInfo.objects.create(
            shield_machine=shield,
            cutter_position_no="2",
            tool_type="DISC",
            tool_info=tool_info,
        )
        self.opening = WarehouseOpeningBasicInfo.objects.create(
            project=project,
            shield_model=shield,
            ring_no="100",
            open_time=timezone.now(),
            blade_track="测试轨迹",
            opening_duration=3.0,
            tool_change_duration=2.5,
            checked_tool_count=0,
            replaced_tool_count=0,
        )
        self.task = MobileToolChangeTask.objects.get(warehouse=self.opening)

    @staticmethod
    def request_for(user, method="get", data=None):
        factory = APIRequestFactory()
        request = getattr(factory, method)("/", data=data or {})
        request.user = user
        return request

    def update_old_tool_record(self, detail, data):
        self.first_operator.is_superuser = True
        self.first_operator.save(update_fields=["is_superuser"])
        opening = detail.warehouse
        if opening.summary_status != WarehouseOpeningBasicInfo.SUMMARY_STATUS_CONFIRMED:
            opening.summary_status = WarehouseOpeningBasicInfo.SUMMARY_STATUS_CONFIRMED
            opening.summary_confirmed_at = timezone.now()
            opening.summary_confirmed_by = self.first_operator
            opening.save(update_fields=[
                "summary_status", "summary_confirmed_at", "summary_confirmed_by",
                "update_datetime",
            ])
        view = ToolChangeDetailViewSet()
        view.action_map = {}
        request = view.initialize_request(
            self.request_for(self.first_operator, method="put", data=data)
        )
        request.user = self.first_operator
        view.request = request
        view.kwargs = {"pk": detail.id}
        return view.old_tool_record(request, pk=detail.id)

    def test_first_detail_open_claims_task_and_second_operator_is_rejected(self):
        view = MobileTaskViewSet()
        first = view._get_task(
            self.request_for(self.first_operator), self.task.id, claim=True
        )
        self.assertEqual(first.recorder_id, self.first_operator.id)
        self.assertEqual(first.status, "PENDING")

        second = view._get_task(
            self.request_for(self.second_operator), self.task.id, claim=True
        )
        self.assertIsNone(second)
        self.task.refresh_from_db()
        self.assertEqual(self.task.recorder_id, self.first_operator.id)

    def test_field_options_are_served_by_backend(self):
        request = self.request_for(self.first_operator)
        response = ToolChangeDetailViewSet().field_options(request)
        options = response.data["data"]
        self.assertIn({"value": "SMOOTH", "label": "光面"}, options["ring_types"])
        self.assertIn({"value": "REPAIRABLE", "label": "可维修"}, options["old_tool_dispositions"])
        self.assertIn({"value": "C_BLOCK_LOSS", "label": "C 块掉落"}, options["ring_damage"])

    def test_opening_create_mobile_summary_and_desktop_supplement_end_to_end(self):
        """完整覆盖电脑建仓、移动录入、汇总校正和桌面补录。"""
        self.first_operator.is_superuser = True
        self.first_operator.save(update_fields=["is_superuser"])
        client = APIClient()
        client.force_authenticate(user=self.first_operator)

        create_response = client.post(
            "/api/shield/warehouse_opening/",
            {
                "project": self.opening.project_id,
                "shield_model": self.opening.shield_model_id,
                "ring_no": "110",
                "open_time": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
                "opening_duration": 99,
                "tool_change_duration": 99,
                "checked_tool_count": 99,
                "replaced_tool_count": 99,
                "usage_distance": 999,
            },
            format="json",
            HTTP_USER_AGENT="shield-e2e-test-client",
        )
        self.assertEqual(create_response.data["code"], 2000)
        opening = WarehouseOpeningBasicInfo.objects.get(
            id=create_response.data["data"]["id"]
        )
        self.assertEqual(opening.rings_between_openings, 10)
        self.assertEqual(opening.usage_distance, 20.0)
        self.assertIsNone(opening.opening_duration)
        self.assertIsNone(opening.tool_change_duration)
        self.assertIsNone(opening.checked_tool_count)
        self.assertIsNone(opening.replaced_tool_count)

        details = list(opening.tool_change_details.order_by("cutter_position_no"))
        self.assertEqual(len(details), 2)
        blocked = ToolChangeDetailCreateUpdateSerializer(
            details[0], data={"remark": "桌面提前补录"}, partial=True
        )
        self.assertFalse(blocked.is_valid())

        task = MobileToolChangeTask.objects.get(warehouse=opening)
        mobile_view = MobileTaskViewSet()
        mobile_view.action_map = {}
        replaced_request = mobile_view.initialize_request(
            self.request_for(self.first_operator, method="post", data={
                "detail_id": details[0].id,
                "is_replaced": "true",
                "ring_type": "INSERTED",
                "shaft_condition": "NEW",
                "hub_condition": "REPAIRED",
                "old_photos": SimpleUploadedFile(
                    "e2e-old.png", b"old", content_type="image/png"
                ),
            })
        )
        replaced_request.user = self.first_operator
        self.assertEqual(
            mobile_view.save_detail(replaced_request, pk=task.id).data["code"],
            2000,
        )

        checked_request = mobile_view.initialize_request(
            self.request_for(self.first_operator, method="post", data={
                "detail_id": details[1].id,
                "is_replaced": "false",
            })
        )
        checked_request.user = self.first_operator
        self.assertEqual(
            mobile_view.save_detail(checked_request, pk=task.id).data["code"],
            2000,
        )

        opening.refresh_from_db()
        self.assertEqual(opening.checked_tool_count, 2)
        self.assertEqual(opening.replaced_tool_count, 1)

        summary_response = client.post(
            f"/api/shield/warehouse_opening/{opening.id}/complete_summary/",
            {
                "opening_duration": 4.5,
                "tool_change_duration": 2.25,
                "checked_tool_count": 3,
                "replaced_tool_count": 1,
            },
            format="json",
            HTTP_USER_AGENT="shield-e2e-test-client",
        )
        self.assertEqual(summary_response.data["code"], 2000)
        self.assertTrue(summary_response.data["data"]["supplement_ready"])
        self.assertEqual(summary_response.data["data"]["checked_tool_count"], 3)
        self.assertEqual(
            summary_response.data["data"]["summary_status"],
            WarehouseOpeningBasicInfo.SUMMARY_STATUS_CONFIRMED,
        )
        self.assertEqual(
            summary_response.data["data"]["summary_confirmed_by"],
            self.first_operator.id,
        )

        details[0].refresh_from_db()
        desktop_write = ToolChangeDetailCreateUpdateSerializer(
            details[0], data={"remark": "桌面补录已完成"}, partial=True
        )
        self.assertFalse(desktop_write.is_valid())
        repair_response = self.update_old_tool_record(details[0], {
            "workflow_action": "SAVE_DRAFT",
            "remark": "已送厂家检测",
        })
        self.assertEqual(repair_response.data["code"], 2000)
        self.assertEqual(OldToolRecord.objects.get(tool_change_detail=details[0]).remark, "已送厂家检测")

    def test_confirmed_summary_blocks_mobile_save_until_desktop_withdraws(self):
        """确认后锁定移动端；撤回后重算数量、重开任务并恢复录入。"""
        self.first_operator.is_superuser = True
        self.first_operator.save(update_fields=["is_superuser"])
        client = APIClient()
        client.force_authenticate(user=self.first_operator)
        details = list(self.opening.tool_change_details.order_by("cutter_position_no"))
        mobile_view = MobileTaskViewSet()
        mobile_view.action_map = {}

        replaced_request = mobile_view.initialize_request(
            self.request_for(self.first_operator, method="post", data={
                "detail_id": details[0].id,
                "is_replaced": "true",
                "ring_type": "INSERTED",
                "shaft_condition": "NEW",
                "hub_condition": "REPAIRED",
                "old_photos": SimpleUploadedFile(
                    "summary-lock-old.png", b"old", content_type="image/png"
                ),
            })
        )
        replaced_request.user = self.first_operator
        self.assertEqual(
            mobile_view.save_detail(replaced_request, pk=self.task.id).data["code"],
            2000,
        )
        checked_request = mobile_view.initialize_request(
            self.request_for(self.first_operator, method="post", data={
                "detail_id": details[1].id,
                "is_replaced": "false",
            })
        )
        checked_request.user = self.first_operator
        self.assertEqual(
            mobile_view.save_detail(checked_request, pk=self.task.id).data["code"],
            2000,
        )

        summary_response = client.post(
            f"/api/shield/warehouse_opening/{self.opening.id}/complete_summary/",
            {
                "opening_duration": 4.5,
                "tool_change_duration": 2.25,
                "checked_tool_count": 3,
                "replaced_tool_count": 2,
            },
            format="json",
            HTTP_USER_AGENT="shield-summary-lock-test-client",
        )
        self.assertEqual(summary_response.data["code"], 2000)
        self.task.refresh_from_db()
        self.task.status = "COMPLETED"
        self.task.submitted_at = timezone.now()
        self.task.save(update_fields=["status", "submitted_at", "update_datetime"])

        late_request = mobile_view.initialize_request(
            self.request_for(self.first_operator, method="post", data={
                "detail_id": details[1].id,
                "is_replaced": "false",
            })
        )
        late_request.user = self.first_operator
        locked_response = mobile_view.save_detail(late_request, pk=self.task.id)
        self.assertNotEqual(locked_response.data["code"], 2000)
        self.assertIn("汇总已确认", locked_response.data["msg"])
        self.opening.refresh_from_db()
        self.assertEqual(self.opening.checked_tool_count, 3)
        self.assertEqual(self.opening.replaced_tool_count, 2)

        withdraw_response = client.post(
            f"/api/shield/warehouse_opening/{self.opening.id}/withdraw_summary/",
            {},
            format="json",
            HTTP_USER_AGENT="shield-summary-lock-test-client",
        )
        self.assertEqual(withdraw_response.data["code"], 2000)
        self.assertFalse(withdraw_response.data["data"]["supplement_ready"])
        self.assertEqual(
            withdraw_response.data["data"]["summary_status"],
            WarehouseOpeningBasicInfo.SUMMARY_STATUS_DRAFT,
        )
        self.assertEqual(withdraw_response.data["data"]["checked_tool_count"], 2)
        self.assertEqual(withdraw_response.data["data"]["replaced_tool_count"], 1)
        self.assertEqual(
            withdraw_response.data["data"]["summary_withdrawn_by"],
            self.first_operator.id,
        )
        self.assertIsNotNone(withdraw_response.data["data"]["summary_withdrawn_at"])
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "RETURNED")
        self.assertIsNone(self.task.submitted_at)

        details[0].refresh_from_db()
        blocked = ToolChangeDetailCreateUpdateSerializer(
            details[0], data={"remark": "撤回后桌面不可补录"}, partial=True
        )
        self.assertFalse(blocked.is_valid())
        resumed_request = mobile_view.initialize_request(
            self.request_for(self.first_operator, method="post", data={
                "detail_id": details[1].id,
                "is_replaced": "false",
            })
        )
        resumed_request.user = self.first_operator
        self.assertEqual(
            mobile_view.save_detail(resumed_request, pk=self.task.id).data["code"],
            2000,
        )

    def test_desktop_write_routes_preserve_tool_identity_and_archive(self):
        """旧客户端的单条/批量/删除入口不能改号或撤销已归档换刀。"""
        self.first_operator.is_superuser = True
        self.first_operator.save(update_fields=["is_superuser"])
        client = APIClient()
        client.force_authenticate(self.first_operator)
        headers = {"HTTP_USER_AGENT": "shield-desktop-write-guard-test"}
        detail = self.opening.tool_change_details.get(cutter_position_no="1")
        saved = client.post(
            f"/api/shield/mobile/tasks/{self.task.pk}/save_detail/",
            {
                "detail_id": detail.pk,
                "is_replaced": "true",
                "old_photos": SimpleUploadedFile("identity-guard.png", b"old", content_type="image/png"),
            },
            format="multipart", **headers,
        )
        self.assertEqual(saved.data["code"], 2000, saved.data)
        detail.refresh_from_db()
        number = detail.tool_number
        instance_id = detail.new_tool_record.tool_instance_id
        summary = client.post(
            f"/api/shield/warehouse_opening/{self.opening.pk}/complete_summary/",
            {"opening_duration": 3, "tool_change_duration": 2, "checked_tool_count": 2, "replaced_tool_count": 1},
            format="json", **headers,
        )
        self.assertEqual(summary.data["code"], 2000, summary.data)
        for note in ("已送厂家", "厂家反馈待核实"):
            response = client.put(
                f"/api/shield/tool_change_detail/{detail.pk}/old_tool_record/",
                {"workflow_action": "SAVE_DRAFT", "remark": note},
                format="json", **headers,
            )
            self.assertEqual(response.data["code"], 2000, response.data)
            detail.refresh_from_db()
            self.assertEqual(detail.tool_number, number)
            self.assertEqual(detail.new_tool_record.tool_instance.display_tool_no, number)
            self.assertEqual(detail.old_tool_record.remark, note)
        for workflow_action in ("CONFIRM", "CLOSE"):
            response = client.put(
                f"/api/shield/tool_change_detail/{detail.pk}/old_tool_record/",
                {"workflow_action": workflow_action, "disposition": "SCRAP"},
                format="json", **headers,
            )
            self.assertEqual(response.data["code"], 2000, response.data)

        prefix = "/api/shield/tool_change_detail/"
        requests = [
            ("put", f"{prefix}{detail.pk}/", {"is_replaced": False, "tool_number": "R100-1-999"}),
            ("patch", f"{prefix}{detail.pk}/", {"is_checked": False, "tool_number": "FORGED"}),
            ("delete", f"{prefix}{detail.pk}/", {}),
            ("post", prefix, {"warehouse": self.opening.pk, "cutter_position_no": "3", "is_replaced": True}),
            ("post", f"{prefix}batch_update/", {"updates": [{"id": detail.pk, "is_replaced": False, "tool_number": "FORGED"}]}),
            ("post", f"{prefix}batch_create/", {"warehouse_id": self.opening.pk, "details": [{"cutter_position_no": "3"}]}),
            ("delete", f"{prefix}multiple_delete/", {"keys": [detail.pk]}),
            ("post", f"{prefix}import_data/", {}),
        ]
        for method, path, payload in requests:
            with self.subTest(method=method, path=path):
                response = getattr(client, method)(path, payload, format="json", **headers)
                self.assertNotEqual(response.data["code"], 2000, response.data)
                self.assertIn("现场明细不可", str(response.data))
                detail.refresh_from_db()
                self.assertTrue(detail.is_replaced)
                self.assertTrue(detail.is_checked)
                self.assertEqual(detail.tool_number, number)
                self.assertEqual(detail.new_tool_record.tool_instance_id, instance_id)
                self.assertEqual(detail.new_tool_record.tool_instance.display_tool_no, number)
                self.assertEqual(detail.old_tool_record.inspection_status, "CLOSED")
                self.assertEqual(detail.old_tool_record.photos.count(), 1)
                self.assertEqual(self.opening.tool_change_details.count(), 2)
        self.opening.refresh_from_db()
        self.assertEqual(self.opening.replaced_tool_count, 1)
        self.assertEqual(self.opening.summary_status, "CONFIRMED")
        self.assertEqual(client.get(f"{prefix}{detail.pk}/", **headers).data["code"], 2000)

    def test_desktop_cannot_mark_unchecked_position_replaced(self):
        """汇总确认前后，桌面都不能凭空制造新刀或检查事实。"""
        self.first_operator.is_superuser = True
        self.first_operator.save(update_fields=["is_superuser"])
        client = APIClient()
        client.force_authenticate(self.first_operator)
        detail = self.opening.tool_change_details.first()
        for summary_status in ("DRAFT", "CONFIRMED"):
            self.opening.summary_status = summary_status
            self.opening.save(update_fields=["summary_status"])
            response = client.post(
                "/api/shield/tool_change_detail/batch_update/",
                {"updates": [{"id": detail.pk, "is_checked": True, "is_replaced": True, "tool_number": "FAKE"}]},
                format="json", HTTP_USER_AGENT="shield-desktop-write-guard-test",
            )
            self.assertNotEqual(response.data["code"], 2000)
            detail.refresh_from_db()
            self.assertFalse(detail.is_checked)
            self.assertFalse(detail.is_replaced)
            self.assertFalse(NewToolRecord.objects.filter(tool_change_detail=detail).exists())
            self.assertFalse(OldToolRecord.objects.filter(tool_change_detail=detail).exists())

    def test_mobile_detail_exposes_costs_for_its_fixed_tool_type(self):
        tool_info = self.opening.tool_change_details.get(cutter_position_no="1").cutter_position.tool_info
        cost = ToolCost.objects.create(
            tool_info=tool_info,
            cost_type="NEW_TOOL",
            manufacturer="测试成本厂家",
            brand="测试成本品牌",
            unit_price="6200.00",
        )
        payload = MobileToolChangeDetailSerializer(
            self.opening.tool_change_details.get(cutter_position_no="1")
        ).data
        self.assertEqual(payload["tool_info_id"], tool_info.id)
        self.assertEqual([item["id"] for item in payload["tool_cost_options"]], [cost.id])
        self.assertEqual(payload["tool_cost_options"][0]["brand"], "测试成本品牌")
        self.assertIn({"value": "偏磨", "label": "偏磨"}, mobile_field_options()["wear_descriptions"])

    def test_mobile_save_rejects_cross_type_cost_and_persists_selected_cost(self):
        detail = self.opening.tool_change_details.get(cutter_position_no="1")
        fixed_cost = ToolCost.objects.create(
            tool_info=detail.cutter_position.tool_info,
            cost_type="NEW_TOOL",
            manufacturer="固定类型厂家",
            brand="固定类型品牌",
            unit_price="6300.00",
        )
        other_tool = ToolInfo.objects.create(tool_parent_type="SCRAPER", tool_type_name="其他类型")
        other_cost = ToolCost.objects.create(
            tool_info=other_tool,
            cost_type="NEW_TOOL",
            manufacturer="其他厂家",
            brand="其他品牌",
            unit_price="1200.00",
        )
        view = MobileTaskViewSet()
        view.action_map = {}
        invalid_request = self.request_for(self.first_operator, method="post", data={
            "detail_id": detail.id,
            "is_replaced": "true",
            "tool_cost_id": other_cost.id,
            "old_photos": SimpleUploadedFile("cross-type.png", b"image", content_type="image/png"),
        })
        invalid_request = view.initialize_request(invalid_request)
        invalid_request.user = self.first_operator
        self.assertNotEqual(view.save_detail(invalid_request, pk=self.task.id).data["code"], 2000)

        valid_request = self.request_for(self.first_operator, method="post", data={
            "detail_id": detail.id,
            "is_replaced": "true",
            "tool_cost_id": fixed_cost.id,
            "ring_type": "INSERTED",
            "shaft_condition": "NEW",
            "hub_condition": "REPAIRED",
            "wear_condition": "偏磨",
            "old_photos": SimpleUploadedFile("fixed-cost.png", b"image", content_type="image/png"),
        })
        valid_request = view.initialize_request(valid_request)
        valid_request.user = self.first_operator
        self.assertEqual(view.save_detail(valid_request, pk=self.task.id).data["code"], 2000)
        detail.refresh_from_db()
        self.assertEqual(detail.manufacturer, "固定类型厂家")
        self.assertEqual(detail.brand, "固定类型品牌")
        self.assertEqual(str(detail.price), "6300.00")
        self.assertEqual(detail.wear_condition, "偏磨")

    def test_trajectory_uses_radial_distance_for_rollers_and_scrapers(self):
        self.assertEqual(get_tool_trajectory("1", "DISC")["radius_mm"], 135)
        self.assertEqual(get_tool_trajectory("13", "DISC")["radius_mm"], 1555)
        self.assertEqual(get_tool_trajectory("18", "DISC")["radius_mm"], 2035)
        self.assertEqual(get_tool_trajectory("80-A", "DISC")["radius_mm"], 6809.8)
        self.assertEqual(get_tool_trajectory("y1", "DISC")["radius_mm"], 6605)
        self.assertEqual(get_tool_trajectory("Y3", "DISC")["radius_mm"], 6650)
        self.assertEqual(get_tool_trajectory("y5", "DISC")["radius_mm"], 6670)
        self.assertEqual(get_tool_trajectory("y2", "DISC")["status"], "PENDING_REVIEW")
        scraper = get_tool_trajectory("S14R", "SCRAPER")
        self.assertEqual(scraper["status"], "CONFIRMED")
        self.assertEqual(scraper["radius_mm"], 5910)

        detail = self.opening.tool_change_details.get(cutter_position_no="1")
        payload = MobileToolChangeDetailSerializer(detail).data
        self.assertEqual(payload["trajectory"]["display"], "R135 mm")

    def test_recordable_position_scope_matches_confirmed_trajectory_map(self):
        expected_codes = {
            *{str(number) for number in range(1, 80)},
            "80A", "80B", "Y1", "Y3", "Y5",
            *{f"S{number}{side}" for number in range(1, 20) for side in ("L", "R")},
        }
        self.assertEqual(ACTIVE_CUTTER_POSITION_CODES, expected_codes)
        for code in expected_codes:
            tool_parent_type = "SCRAPER" if code.startswith("S") else "DISC"
            self.assertTrue(is_active_cutter_position(code, tool_parent_type))
            self.assertEqual(
                get_tool_trajectory(code, tool_parent_type)["status"],
                "CONFIRMED",
            )

        for code in ("Y2", "Y4", "Y6", "G1L", "H1R"):
            self.assertFalse(is_active_cutter_position(code))
        self.assertFalse(is_active_cutter_position("3", "RIPPER"))
        self.assertFalse(is_active_cutter_position("S1L", "DISC"))

    def test_new_opening_and_mobile_scope_exclude_unrecorded_positions(self):
        shield = self.opening.shield_model
        disc = self.opening.tool_change_details.get(cutter_position_no="1").cutter_position.tool_info
        scraper = ToolInfo.objects.create(tool_parent_type="SCRAPER", tool_type_name="测试刮刀")
        ripper = ToolInfo.objects.create(tool_parent_type="RIPPER", tool_type_name="测试先行刀")
        for code, tool_type, tool_info in (
            ("Y1", "DISC", disc),
            ("Y2", "DISC", disc),
            ("S1L", "SCRAPER", scraper),
            ("G1L", "SCRAPER", scraper),
            ("3", "RIPPER", ripper),
        ):
            CutterPositionInfo.objects.create(
                shield_machine=shield,
                cutter_position_no=code,
                tool_type=tool_type,
                tool_info=tool_info,
            )

        opening = WarehouseOpeningBasicInfo.objects.create(
            project=self.opening.project,
            shield_model=shield,
            ring_no="101",
            open_time=self.opening.open_time + timedelta(hours=1),
        )
        expected_codes = {"1", "2", "Y1", "S1L"}
        self.assertEqual(
            set(opening.tool_change_details.values_list("cutter_position_no", flat=True)),
            expected_codes,
        )

        task = MobileToolChangeTask.objects.get(warehouse=opening)
        self.assertEqual(resolve_task_positions(opening, "ALL"), expected_codes)
        self.assertEqual(
            set(scoped_details(task).values_list("cutter_position_no", flat=True)),
            expected_codes,
        )

        view = AdminMobileTaskViewSet()
        view.action_map = {}
        request = view.initialize_request(
            self.request_for(
                self.first_operator,
                method="get",
                data={"warehouse": opening.id},
            )
        )
        request.user = self.first_operator
        response = view.assign_options(request)
        self.assertEqual(response.data["code"], 2000)
        self.assertEqual(
            {item["value"] for item in response.data["data"]["tool_types"]},
            {"DISC", "SCRAPER"},
        )
        self.assertEqual(
            {item["value"] for item in response.data["data"]["positions"]},
            expected_codes,
        )

    def test_mobile_save_and_submit_keep_uninspected_positions_pending(self):
        view = MobileTaskViewSet()
        detail = self.opening.tool_change_details.get(cutter_position_no="1")
        detail.tool_number = "LEGACY-OLD-001"
        detail.save(update_fields=["tool_number"])
        request = self.request_for(self.first_operator, method="post", data={
            "detail_id": detail.id,
            "is_replaced": "true",
            "ring_type": "INSERTED",
            "ring_manufacturer": "测试刀圈厂家",
            "shaft_condition": "NEW",
            "shaft_manufacturer": "测试刀轴厂家",
            "hub_condition": "REPAIRED",
            "hub_manufacturer": "测试刀毂厂家",
            "blade_wear_amount": "1.2",
            "old_photos": SimpleUploadedFile("old.png", b"test-image", content_type="image/png"),
        })
        view.action_map = {}
        request = view.initialize_request(request)
        request.user = self.first_operator
        response = view.save_detail(request, pk=self.task.id)
        self.assertEqual(response.data["code"], 2000)

        detail.refresh_from_db()
        self.assertTrue(detail.is_checked)
        self.assertTrue(detail.is_replaced)
        self.assertEqual(detail.blade_wear_amount, 1.2)
        self.assertEqual(detail.new_tool_record.ring_type, "INSERTED")
        self.assertEqual(detail.new_tool_record.hub_condition, "REPAIRED")
        self.assertEqual(detail.tool_number, detail.new_tool_record.tool_instance.display_tool_no)
        self.assertNotEqual(detail.tool_number, "LEGACY-OLD-001")
        self.assertEqual(detail.old_tool_record.old_tool_number, "LEGACY-OLD-001")
        self.assertEqual(detail.old_tool_record.photos.count(), 1)

        submit_request = view.initialize_request(self.request_for(self.first_operator, method="post"))
        submit_request.user = self.first_operator
        submit_response = view.submit(submit_request, pk=self.task.id)
        self.assertEqual(submit_response.data["code"], 2000)
        self.assertEqual(submit_response.data["data"]["progress"]["saved"], 1)
        untouched = self.opening.tool_change_details.get(cutter_position_no="2")
        self.assertFalse(untouched.is_checked)
        self.assertEqual(untouched.mobile_status, "SUBMITTED")
        self.assertEqual(untouched.check_result, "PENDING")

        self.first_operator.is_superuser = True
        self.first_operator.save(update_fields=["is_superuser"])
        self.opening.summary_status = WarehouseOpeningBasicInfo.SUMMARY_STATUS_CONFIRMED
        self.opening.summary_confirmed_at = timezone.now()
        self.opening.summary_confirmed_by = self.first_operator
        self.opening.save(update_fields=[
            "summary_status", "summary_confirmed_at", "summary_confirmed_by",
            "update_datetime",
        ])
        repair_view = ToolChangeDetailViewSet()
        repair_view.action_map = {}
        repair_request = repair_view.initialize_request(self.request_for(
            self.first_operator,
            method="put",
            data={
                "ring_wear_amount": "2.5",
                "bias_wear_amount": "0.4",
                "ring_damage": '["CHIP", "BOLT_LOSS"]',
                "ring_tooth_loss_count": "3",
                "bearing_failed": "true",
                "bearing_failure_reasons": '["SEAL_FAILURE"]',
                "disposition": "REPAIRABLE",
                "repair_result": "更换轴承后可维修",
            },
        ))
        repair_request.user = self.first_operator
        repair_view.request = repair_request
        repair_view.kwargs = {"pk": detail.id}
        repair_response = repair_view.old_tool_record(repair_request, pk=detail.id)
        self.assertEqual(repair_response.data["code"], 2000)
        self.assertEqual(
            repair_response.data["data"]["old_tool_record_data"]["old_tool_number_display"],
            "LEGACY-OLD-001",
        )
        detail.old_tool_record.refresh_from_db()
        self.assertEqual(detail.old_tool_record.ring_tooth_loss_count, 3)
        self.assertEqual(detail.old_tool_record.ring_damage, ["CHIP", "BOLT_LOSS"])
        self.assertEqual(detail.old_tool_record.disposition, "REPAIRABLE")
        self.assertEqual(detail.old_tool_record.old_tool_number, "LEGACY-OLD-001")

    def test_reverting_replacement_restores_removed_tool_number(self):
        view = MobileTaskViewSet()
        view.action_map = {}
        detail = self.opening.tool_change_details.get(cutter_position_no="1")
        detail.tool_number = "LEGACY-OLD-RESTORE"
        detail.save(update_fields=["tool_number"])

        replace_request = self.request_for(self.first_operator, method="post", data={
            "detail_id": detail.id,
            "is_replaced": "true",
            "ring_type": "INSERTED",
            "shaft_condition": "NEW",
            "hub_condition": "REPAIRED",
            "old_photos": SimpleUploadedFile("old.png", b"old", content_type="image/png"),
        })
        replace_request = view.initialize_request(replace_request)
        replace_request.user = self.first_operator
        self.assertEqual(view.save_detail(replace_request, pk=self.task.id).data["code"], 2000)

        detail.refresh_from_db()
        self.assertNotEqual(detail.tool_number, "LEGACY-OLD-RESTORE")
        self.assertEqual(detail.old_tool_record.old_tool_number, "LEGACY-OLD-RESTORE")

        revert_request = self.request_for(self.first_operator, method="post", data={
            "detail_id": detail.id,
            "is_replaced": "false",
        })
        revert_request = view.initialize_request(revert_request)
        revert_request.user = self.first_operator
        self.assertEqual(view.save_detail(revert_request, pk=self.task.id).data["code"], 2000)

        detail.refresh_from_db()
        self.assertEqual(detail.tool_number, "LEGACY-OLD-RESTORE")
        self.assertFalse(NewToolRecord.objects.filter(tool_change_detail=detail).exists())
        self.assertFalse(OldToolRecord.objects.filter(tool_change_detail=detail).exists())

    def test_mobile_save_recovers_old_number_from_previous_installed_instance(self):
        previous_opening = WarehouseOpeningBasicInfo.objects.create(
            project=self.opening.project,
            shield_model=self.opening.shield_model,
            ring_no="90",
            open_time=self.opening.open_time - timedelta(days=1),
        )
        previous_detail = previous_opening.tool_change_details.get(cutter_position_no="1")
        tool_info = previous_detail.cutter_position.tool_info
        previous_instance = ToolInstance.objects.create(
            tool_uid="TEST-PREVIOUS-INSTANCE",
            display_tool_no="90-1-01",
            tool_info=tool_info,
            tool_parent_type=tool_info.tool_parent_type,
            tool_type_name=tool_info.tool_type_name,
            status="INSTALLED",
        )
        NewToolRecord.objects.create(
            tool_change_detail=previous_detail,
            tool_instance=previous_instance,
            installed_at=previous_opening.open_time,
        )

        detail = self.opening.tool_change_details.get(cutter_position_no="1")
        self.assertFalse(detail.tool_number)
        view = MobileTaskViewSet()
        view.action_map = {}
        request = self.request_for(self.first_operator, method="post", data={
            "detail_id": detail.id,
            "is_replaced": "true",
            "ring_type": "INSERTED",
            "shaft_condition": "NEW",
            "hub_condition": "REPAIRED",
            "old_photos": SimpleUploadedFile("old.png", b"old", content_type="image/png"),
        })
        request = view.initialize_request(request)
        request.user = self.first_operator
        self.assertEqual(view.save_detail(request, pk=self.task.id).data["code"], 2000)

        detail.refresh_from_db()
        self.assertEqual(detail.old_tool_record.old_tool_number, "90-1-01")
        self.assertEqual(detail.old_tool_record.suggested_tool_instance_id, previous_instance.id)
        self.assertNotEqual(detail.tool_number, "90-1-01")

    def test_old_tool_vendor_workflow_uses_explicit_transitions(self):
        previous_opening = WarehouseOpeningBasicInfo.objects.create(
            project=self.opening.project,
            shield_model=self.opening.shield_model,
            ring_no="90",
            open_time=self.opening.open_time - timedelta(days=1),
        )
        previous_detail = previous_opening.tool_change_details.get(cutter_position_no="1")
        tool_info = previous_detail.cutter_position.tool_info
        previous_instance = ToolInstance.objects.create(
            tool_uid="TEST-VENDOR-WORKFLOW",
            display_tool_no="90-1-VENDOR",
            tool_info=tool_info,
            tool_parent_type=tool_info.tool_parent_type,
            tool_type_name=tool_info.tool_type_name,
            status="INSTALLED",
        )
        NewToolRecord.objects.create(
            tool_change_detail=previous_detail,
            tool_instance=previous_instance,
            installed_at=previous_opening.open_time,
        )

        detail = self.opening.tool_change_details.get(cutter_position_no="1")
        mobile_view = MobileTaskViewSet()
        mobile_view.action_map = {}
        save_request = self.request_for(self.first_operator, method="post", data={
            "detail_id": detail.id,
            "is_replaced": "true",
            "ring_type": "INSERTED",
            "shaft_condition": "NEW",
            "hub_condition": "REPAIRED",
            "old_photos": SimpleUploadedFile("vendor-old.png", b"old", content_type="image/png"),
        })
        save_request = mobile_view.initialize_request(save_request)
        save_request.user = self.first_operator
        self.assertEqual(mobile_view.save_detail(save_request, pk=self.task.id).data["code"], 2000)

        detail.refresh_from_db()
        previous_instance.refresh_from_db()
        old_record = detail.old_tool_record
        self.assertEqual(old_record.inspection_status, "PENDING_VENDOR_FEEDBACK")
        self.assertIsNone(old_record.vendor_feedback_at)
        self.assertEqual(previous_instance.status, "REMOVED_PENDING_INSPECTION")
        lifecycle_view = ToolLifecycleViewSet()
        lifecycle_payload = lifecycle_view.serialize_instance(
            previous_instance,
            removal_map=lifecycle_view._instance_removal_map(),
            install_map=lifecycle_view._install_detail_map([previous_instance.id]),
        )
        self.assertEqual(lifecycle_payload["status"], "REMOVED_PENDING_INSPECTION")

        draft_response = self.update_old_tool_record(detail, {
            "workflow_action": "SAVE_DRAFT",
            "ring_wear_amount": "2.5",
            "remark": "厂家检测中",
        })
        self.assertEqual(draft_response.data["code"], 2000)
        old_record.refresh_from_db()
        previous_instance.refresh_from_db()
        self.assertEqual(old_record.inspection_status, "PENDING_VENDOR_FEEDBACK")
        self.assertIsNone(old_record.vendor_feedback_at)
        self.assertEqual(previous_instance.status, "REMOVED_PENDING_INSPECTION")

        invalid_close = self.update_old_tool_record(detail, {
            "workflow_action": "CLOSE",
            "disposition": "REPAIRABLE",
            "repair_result": "更换轴承",
        })
        self.assertNotEqual(invalid_close.data["code"], 2000)
        old_record.refresh_from_db()
        self.assertEqual(old_record.inspection_status, "PENDING_VENDOR_FEEDBACK")

        confirm_response = self.update_old_tool_record(detail, {
            "workflow_action": "CONFIRM",
            "disposition": "REPAIRABLE",
            "repair_result": "更换轴承",
        })
        self.assertEqual(confirm_response.data["code"], 2000)
        old_record.refresh_from_db()
        previous_instance.refresh_from_db()
        self.assertEqual(old_record.inspection_status, "CONFIRMED")
        self.assertEqual(old_record.confirmed_tool_instance_id, previous_instance.id)
        self.assertIsNotNone(old_record.vendor_feedback_at)
        self.assertEqual(previous_instance.status, "INSPECTED")

        close_response = self.update_old_tool_record(detail, {
            "workflow_action": "CLOSE",
            "disposition": "REPAIRABLE",
            "repair_result": "轴承更换完成，返修合格",
            "repair_price": "850.00",
        })
        self.assertEqual(close_response.data["code"], 2000)
        old_record.refresh_from_db()
        previous_instance.refresh_from_db()
        self.assertEqual(old_record.inspection_status, "CLOSED")
        self.assertEqual(previous_instance.status, "REPAIRED_CLOSED")
        repeated_close_response = self.update_old_tool_record(detail, {
            "workflow_action": "CLOSE",
            "disposition": "REPAIRABLE",
            "repair_result": "轴承更换完成，返修合格",
        })
        self.assertEqual(repeated_close_response.data["code"], 2000)
        old_record.refresh_from_db()
        previous_instance.refresh_from_db()
        self.assertEqual(old_record.inspection_status, "CLOSED")
        self.assertEqual(previous_instance.status, "REPAIRED_CLOSED")
        lifecycle_payload = lifecycle_view.serialize_instance(
            previous_instance,
            removal_map=lifecycle_view._instance_removal_map(),
            install_map=lifecycle_view._install_detail_map([previous_instance.id]),
        )
        self.assertEqual(lifecycle_payload["status"], "REPAIRED_CLOSED")

    def test_old_tool_scrap_archive_updates_instance_status(self):
        detail = self.opening.tool_change_details.get(cutter_position_no="2")
        detail.is_replaced = True
        detail.save(update_fields=["is_replaced"])
        removed_instance = ToolInstance.objects.create(
            tool_uid="TEST-SCRAP-WORKFLOW",
            display_tool_no="OLD-SCRAP-01",
            tool_info=detail.cutter_position.tool_info,
            tool_parent_type=detail.tool_parent_type,
            tool_type_name=detail.cutter_position.tool_info.tool_type_name,
            status="REMOVED_PENDING_INSPECTION",
        )
        OldToolRecord.objects.create(
            tool_change_detail=detail,
            suggested_tool_instance=removed_instance,
            old_tool_number=removed_instance.display_tool_no,
        )

        confirm_response = self.update_old_tool_record(detail, {
            "workflow_action": "CONFIRM",
            "disposition": "SCRAP",
            "remark": "厂家判定报废",
        })
        self.assertEqual(confirm_response.data["code"], 2000)
        close_response = self.update_old_tool_record(detail, {
            "workflow_action": "CLOSE",
            "disposition": "SCRAP",
        })
        self.assertEqual(close_response.data["code"], 2000)
        removed_instance.refresh_from_db()
        detail.old_tool_record.refresh_from_db()
        self.assertEqual(detail.old_tool_record.inspection_status, "CLOSED")
        self.assertEqual(removed_instance.status, "SCRAPPED")

    def test_reverting_replacement_restores_removed_instance_status(self):
        previous_opening = WarehouseOpeningBasicInfo.objects.create(
            project=self.opening.project,
            shield_model=self.opening.shield_model,
            ring_no="90",
            open_time=self.opening.open_time - timedelta(days=1),
        )
        previous_detail = previous_opening.tool_change_details.get(cutter_position_no="2")
        tool_info = previous_detail.cutter_position.tool_info
        previous_instance = ToolInstance.objects.create(
            tool_uid="TEST-REVERT-INSTANCE-STATUS",
            display_tool_no="90-2-REVERT",
            tool_info=tool_info,
            tool_parent_type=tool_info.tool_parent_type,
            tool_type_name=tool_info.tool_type_name,
            status="INSTALLED",
        )
        NewToolRecord.objects.create(
            tool_change_detail=previous_detail,
            tool_instance=previous_instance,
            installed_at=previous_opening.open_time,
        )
        detail = self.opening.tool_change_details.get(cutter_position_no="2")
        view = MobileTaskViewSet()
        view.action_map = {}

        replace_request = self.request_for(self.first_operator, method="post", data={
            "detail_id": detail.id,
            "is_replaced": "true",
            "ring_type": "SMOOTH",
            "shaft_condition": "NEW",
            "hub_condition": "NEW",
            "old_photos": SimpleUploadedFile("revert-old.png", b"old", content_type="image/png"),
        })
        replace_request = view.initialize_request(replace_request)
        replace_request.user = self.first_operator
        self.assertEqual(view.save_detail(replace_request, pk=self.task.id).data["code"], 2000)
        previous_instance.refresh_from_db()
        self.assertEqual(previous_instance.status, "REMOVED_PENDING_INSPECTION")

        revert_request = self.request_for(self.first_operator, method="post", data={
            "detail_id": detail.id,
            "is_replaced": "false",
        })
        revert_request = view.initialize_request(revert_request)
        revert_request.user = self.first_operator
        self.assertEqual(view.save_detail(revert_request, pk=self.task.id).data["code"], 2000)
        previous_instance.refresh_from_db()
        self.assertEqual(previous_instance.status, "INSTALLED")

    def test_mobile_photo_replacement_removes_deleted_photos_from_computer_payload(self):
        view = MobileTaskViewSet()
        view.action_map = {}
        detail = self.opening.tool_change_details.get(cutter_position_no="1")

        first_request = self.request_for(self.first_operator, method="post", data={
            "detail_id": detail.id,
            "is_replaced": "true",
            "ring_type": "INSERTED",
            "shaft_condition": "NEW",
            "hub_condition": "REPAIRED",
            "old_photos": [
                SimpleUploadedFile("old-original-a.png", b"old-a", content_type="image/png"),
                SimpleUploadedFile("old-original-b.png", b"old-b", content_type="image/png"),
            ],
        })
        first_request = view.initialize_request(first_request)
        first_request.user = self.first_operator
        self.assertEqual(view.save_detail(first_request, pk=self.task.id).data["code"], 2000)

        detail.refresh_from_db()
        old_photo_ids = list(detail.old_tool_record.photos.values_list("id", flat=True))
        self.assertEqual(len(old_photo_ids), 2)

        second_request = self.request_for(self.first_operator, method="post", data={
            "detail_id": detail.id,
            "is_replaced": "true",
            "ring_type": "INSERTED",
            "shaft_condition": "NEW",
            "hub_condition": "REPAIRED",
            "old_photo_ids": json.dumps([]),
            "old_photos": [
                SimpleUploadedFile("old-new-a.png", b"new-a", content_type="image/png"),
                SimpleUploadedFile("old-new-b.png", b"new-b", content_type="image/png"),
            ],
        })
        second_request = view.initialize_request(second_request)
        second_request.user = self.first_operator
        response = view.save_detail(second_request, pk=self.task.id)
        self.assertEqual(response.data["code"], 2000)

        detail.refresh_from_db()
        photos = list(detail.old_tool_record.photos.order_by("id"))
        self.assertEqual([photo.original_filename for photo in photos], ["old-new-a.png", "old-new-b.png"])
        self.assertTrue(set(old_photo_ids).isdisjoint({photo.id for photo in photos}))
        self.assertEqual(
            [photo["original_filename"] for photo in response.data["data"]["old_photos"]],
            ["old-new-a.png", "old-new-b.png"],
        )
        self.assertTrue(all("?v=" in photo["image_url"] for photo in response.data["data"]["old_photos"]))

        computer_payload = old_tool_inspection_payload(detail.old_tool_record)
        self.assertEqual(
            [photo["name"] for photo in computer_payload["photo_links"]],
            ["old-new-a.png", "old-new-b.png"],
        )
        self.assertTrue(all("?v=" in photo["url"] for photo in computer_payload["photo_links"]))

    def test_submitted_task_can_be_corrected_from_mobile_and_returns_to_in_progress(self):
        view = MobileTaskViewSet()
        view.action_map = {}
        detail = self.opening.tool_change_details.get(cutter_position_no="1")
        detail.tool_number = "LEGACY-OLD-CORRECTION"
        detail.save(update_fields=["tool_number"])

        initial_request = self.request_for(self.first_operator, method="post", data={
            "detail_id": detail.id,
            "is_replaced": "true",
            "ring_type": "INSERTED",
            "shaft_condition": "NEW",
            "hub_condition": "REPAIRED",
            "old_photos": SimpleUploadedFile("before.png", b"before", content_type="image/png"),
        })
        initial_request = view.initialize_request(initial_request)
        initial_request.user = self.first_operator
        self.assertEqual(view.save_detail(initial_request, pk=self.task.id).data["code"], 2000)

        submit_request = view.initialize_request(self.request_for(self.first_operator, method="post"))
        submit_request.user = self.first_operator
        self.assertEqual(view.submit(submit_request, pk=self.task.id).data["code"], 2000)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "SUBMITTED")

        correction_request = self.request_for(self.first_operator, method="post", data={
            "detail_id": detail.id,
            "is_replaced": "true",
            "ring_type": "INSERTED",
            "shaft_condition": "NEW",
            "hub_condition": "REPAIRED",
            "old_photo_ids": json.dumps([]),
            # 手机相机可能返回空 MIME 或非标准 image/jpg，后端应按扩展名兼容处理。
            "old_photos": SimpleUploadedFile("after-camera.jpg", b"after", content_type=""),
        })
        correction_request = view.initialize_request(correction_request)
        correction_request.user = self.first_operator
        response = view.save_detail(correction_request, pk=self.task.id)
        self.assertEqual(response.data["code"], 2000)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "IN_PROGRESS")
        self.assertIsNone(self.task.submitted_at)
        detail.refresh_from_db()
        self.assertEqual(list(detail.old_tool_record.photos.values_list("original_filename", flat=True)), ["after-camera.jpg"])
        self.assertEqual(detail.old_tool_record.old_tool_number, "LEGACY-OLD-CORRECTION")


class CutterImageAnnotationTests(TestCase):
    def setUp(self):
        self.user = Users.objects.create(
            username="annotation-tester",
            name="轮廓测试员",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        self.shield = ShieldMachineBasicInfo.objects.create(
            shield_model_id="ANNOTATION-SHIELD",
            shield_model="轮廓测试盾构机",
        )
        self.other_shield = ShieldMachineBasicInfo.objects.create(
            shield_model_id="OTHER-SHIELD",
            shield_model="其他盾构机",
        )
        self.positions = [
            CutterPositionInfo.objects.create(shield_machine=self.shield, cutter_position_no=str(index))
            for index in range(1, 164)
        ]
        self.other_position = CutterPositionInfo.objects.create(
            shield_machine=self.other_shield,
            cutter_position_no="1",
        )

    def request_for(self, method="post", data=None, query=None):
        factory = APIRequestFactory()
        request = getattr(factory, method)("/", data=data or query or {}, format="json")
        request.user = self.user
        view = CutterImageAnnotationViewSet()
        view.action_map = {}
        view.args = ()
        view.kwargs = {}
        view.format_kwarg = None
        request = view.initialize_request(request)
        request.user = self.user
        view.request = request
        return view, request

    @staticmethod
    def polygon(points=None):
        points = points or [[10, 10], [40, 10], [40, 40], [10, 40]]
        return {"type": "POLYGON", "geometry": {"points": points}}

    def bulk_payload(self, annotations):
        return {
            "shield_machine": self.shield.id,
            "image_key": "cutterhead-final-v1",
            "canvas_width": 1900,
            "canvas_height": 2100,
            "annotations": annotations,
        }

    def test_workspace_returns_all_database_positions(self):
        view, request = self.request_for(
            method="get",
            query={"shield_machine": self.shield.id, "image_key": "cutterhead-final-v1"},
        )
        response = view.workspace(request)
        self.assertEqual(response.data["code"], 2000)
        self.assertEqual(len(response.data["data"]["positions"]), 163)

    def test_bulk_replace_rejects_position_from_another_machine(self):
        view, request = self.request_for(data=self.bulk_payload([{
            "annotation_id": "foreign-position",
            "cutter_position": self.other_position.id,
            "selector": self.polygon(),
        }]))
        response = view.bulk_replace(request)
        self.assertNotEqual(response.data["code"], 2000)
        self.assertEqual(CutterImageAnnotation.objects.count(), 0)

    def test_bulk_replace_rejects_invalid_polygon_points(self):
        for annotation_id, points in (
            ("too-few-points", [[10, 10], [20, 20]]),
            ("out-of-bounds", [[10, 10], [2000, 20], [20, 20]]),
        ):
            view, request = self.request_for(data=self.bulk_payload([{
                "annotation_id": annotation_id,
                "cutter_position": self.positions[0].id,
                "selector": self.polygon(points),
            }]))
            response = view.bulk_replace(request)
            self.assertNotEqual(response.data["code"], 2000)
        self.assertEqual(CutterImageAnnotation.objects.count(), 0)

    def test_bulk_replace_deletes_removed_outlines(self):
        initial = [
            {
                "annotation_id": f"annotation-{index}",
                "cutter_position": position.id,
                "selector": self.polygon(),
            }
            for index, position in enumerate(self.positions[:2], start=1)
        ]
        view, request = self.request_for(data=self.bulk_payload(initial))
        self.assertEqual(view.bulk_replace(request).data["code"], 2000)
        self.assertEqual(CutterImageAnnotation.objects.count(), 2)

        view, request = self.request_for(data=self.bulk_payload(initial[:1]))
        self.assertEqual(view.bulk_replace(request).data["code"], 2000)
        self.assertEqual(
            list(CutterImageAnnotation.objects.values_list("annotation_id", flat=True)),
            ["annotation-1"],
        )


class WarehouseOpeningStratumAutomationTests(TestCase):
    def setUp(self):
        self.project = ProjectInfo.objects.create(
            project_id="STRATUM-AUTO",
            project_name="地层自动获取测试",
        )
        self.shield = ShieldMachineBasicInfo.objects.create(
            shield_model_id="STRATUM-SHIELD",
            shield_model="地层测试盾构机",
        )
        WarehouseOpeningBasicInfo.objects.create(
            project=self.project,
            shield_model=self.shield,
            ring_no="100",
            open_time=timezone.now(),
        )
        StratumBasicInfo.objects.create(
            project=self.project,
            ring_no="101",
            stratum_type_codes="CLAY",
        )
        StratumBasicInfo.objects.create(
            project=self.project,
            ring_no="105",
            stratum_type_codes="SAND",
            stratum_info="局部含砂",
            burial_depth=18.5,
        )

    def test_create_ignores_manual_values_and_uses_stratum_source(self):
        serializer = WarehouseOpeningBasicInfoCreateUpdateSerializer(data={
            "project": self.project.id,
            "shield_model": self.shield.id,
            "ring_no": "105",
            "open_time": timezone.now(),
            "stratum_info_between": {"MANUAL": 99},
            "stratum_info_between_data": [
                {"stratum_type_code": "MANUAL", "ring_count": 99}
            ],
            "geological_conditions": "手工录入值",
            "opening_duration": 99,
            "tool_change_duration": 99,
            "checked_tool_count": 99,
            "replaced_tool_count": 99,
            "usage_distance": 999,
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        opening = serializer.save()

        self.assertEqual(opening.last_ring_no, "100")
        self.assertEqual(opening.rings_between_openings, 5)
        self.assertEqual(opening.usage_distance, 10.0)
        self.assertIsNone(opening.opening_duration)
        self.assertIsNone(opening.tool_change_duration)
        self.assertIsNone(opening.checked_tool_count)
        self.assertIsNone(opening.replaced_tool_count)
        self.assertEqual(opening.stratum_info_between, {"CLAY": 1, "SAND": 1})
        self.assertEqual(opening.geological_conditions, "SAND；局部含砂；埋深 18.5 m")
        self.assertNotIn("MANUAL", opening.stratum_info_between)

    def test_preview_returns_read_only_display_values(self):
        preview = _build_opening_stratum_context(
            self.project.id,
            "105",
            self.shield.id,
        )

        self.assertEqual(preview["last_ring_no"], "100")
        self.assertEqual(preview["rings_between_openings"], 5)
        self.assertEqual(preview["usage_distance"], 10.0)
        self.assertEqual(
            preview["stratum_info_between_list"],
            [
                {"stratum_type_code": "CLAY", "stratum_type_name": "CLAY", "ring_count": 1},
                {"stratum_type_code": "SAND", "stratum_type_name": "SAND", "ring_count": 1},
            ],
        )
        self.assertEqual(preview["geological_conditions"], "SAND；局部含砂；埋深 18.5 m")

    def test_update_recomputes_gap_and_stratum_snapshot(self):
        serializer = WarehouseOpeningBasicInfoCreateUpdateSerializer(data={
            "project": self.project.id,
            "shield_model": self.shield.id,
            "ring_no": "105",
            "open_time": timezone.now(),
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        opening = serializer.save()

        StratumBasicInfo.objects.create(
            project=self.project,
            ring_no="110",
            stratum_type_codes="ROCK",
            stratum_info="微风化",
            burial_depth=20,
        )
        update_serializer = WarehouseOpeningBasicInfoCreateUpdateSerializer(
            opening,
            data={
                "project": self.project.id,
                "shield_model": self.shield.id,
                "ring_no": "110",
                "open_time": opening.open_time,
                "stratum_info_between": {"MANUAL": 99},
                "stratum_info_between_data": [
                    {"stratum_type_code": "MANUAL", "ring_count": 99}
                ],
                "geological_conditions": "手工录入值",
            },
        )
        self.assertTrue(update_serializer.is_valid(), update_serializer.errors)
        updated = update_serializer.save()

        self.assertEqual(updated.last_ring_no, "100")
        self.assertEqual(updated.rings_between_openings, 10)
        self.assertEqual(updated.usage_distance, 20.0)
        self.assertEqual(updated.stratum_info_between, {
            "CLAY": 1,
            "SAND": 1,
            "ROCK": 1,
        })
        self.assertEqual(updated.geological_conditions, "ROCK；微风化；埋深 20 m")
        self.assertNotIn("MANUAL", updated.stratum_info_between)

    def test_first_opening_has_no_previous_and_uses_current_stratum(self):
        project = ProjectInfo.objects.create(
            project_id="FIRST-OPENING",
            project_name="首次开仓测试",
        )
        shield = ShieldMachineBasicInfo.objects.create(
            shield_model_id="FIRST-SHIELD",
            shield_model="首次开仓盾构机",
        )
        StratumBasicInfo.objects.create(
            project=project,
            ring_no="5",
            stratum_type_codes="CLAY",
        )

        serializer = WarehouseOpeningBasicInfoCreateUpdateSerializer(data={
            "project": project.id,
            "shield_model": shield.id,
            "ring_no": "5",
            "open_time": timezone.now(),
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        opening = serializer.save()

        self.assertIsNone(opening.last_ring_no)
        self.assertEqual(opening.rings_between_openings, 5)
        self.assertEqual(opening.usage_distance, 10.0)
        self.assertEqual(opening.stratum_info_between, {})
        self.assertEqual(opening.geological_conditions, "CLAY")

    def test_detail_write_requires_completed_summary_and_counts_can_be_corrected(self):
        opening = WarehouseOpeningBasicInfo.objects.get(
            project=self.project,
            shield_model=self.shield,
            ring_no="100",
        )
        detail = ToolChangeDetail.objects.create(
            warehouse=opening,
            cutter_position_no="TEST-1",
            tool_parent_type="DISC",
        )

        blocked = ToolChangeDetailCreateUpdateSerializer(
            detail,
            data={"remark": "桌面补录"},
            partial=True,
        )
        self.assertFalse(blocked.is_valid())
        self.assertIn("warehouse", blocked.errors)

        invalid_summary = WarehouseOpeningCompletionSerializer(opening, data={
            "opening_duration": 4,
            "tool_change_duration": 2.5,
            "checked_tool_count": 8,
            "replaced_tool_count": 9,
        })
        self.assertFalse(invalid_summary.is_valid())
        self.assertIn("replaced tool count", invalid_summary.errors)

        summary = WarehouseOpeningCompletionSerializer(opening, data={
            "opening_duration": 4,
            "tool_change_duration": 2.5,
            "checked_tool_count": 8,
            "replaced_tool_count": 3,
        })
        self.assertTrue(summary.is_valid(), summary.errors)
        summary.save()

        still_blocked = ToolChangeDetailCreateUpdateSerializer(
            detail,
            data={"remark": "仅填写未确认"},
            partial=True,
        )
        self.assertFalse(still_blocked.is_valid())

        opening.summary_status = WarehouseOpeningBasicInfo.SUMMARY_STATUS_CONFIRMED
        opening.summary_confirmed_at = timezone.now()
        opening.save(update_fields=[
            "summary_status", "summary_confirmed_at", "update_datetime",
        ])
        direct_write = ToolChangeDetailCreateUpdateSerializer(
            detail,
            data={"remark": "桌面补录"},
            partial=True,
        )
        self.assertFalse(direct_write.is_valid())
        self.assertIn("现场明细不可", str(direct_write.errors))

    def test_completion_action_returns_ready_state(self):
        opening = WarehouseOpeningBasicInfo.objects.get(
            project=self.project,
            shield_model=self.shield,
            ring_no="100",
        )
        user = Users.objects.create(
            username="opening-summary-admin",
            name="开仓汇总管理员",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            f"/api/shield/warehouse_opening/{opening.id}/complete_summary/",
            {
                "opening_duration": 4,
                "tool_change_duration": 2.5,
                "checked_tool_count": 8,
                "replaced_tool_count": 3,
            },
            format="json",
            HTTP_USER_AGENT="shield-test-client",
        )

        self.assertEqual(response.data["code"], 2000)
        self.assertTrue(response.data["data"]["supplement_ready"])
        self.assertEqual(response.data["data"]["supplement_missing_fields"], [])
        self.assertEqual(response.data["data"]["checked_tool_count"], 8)

    def test_missing_stratum_data_returns_empty_snapshot(self):
        project = ProjectInfo.objects.create(
            project_id="NO-STRATUM",
            project_name="无地层数据测试",
        )
        shield = ShieldMachineBasicInfo.objects.create(
            shield_model_id="NO-STRATUM-SHIELD",
            shield_model="无地层数据盾构机",
        )
        WarehouseOpeningBasicInfo.objects.create(
            project=project,
            shield_model=shield,
            ring_no="10",
            open_time=timezone.now(),
        )

        preview = _build_opening_stratum_context(project.id, "20", shield.id)
        self.assertEqual(preview["last_ring_no"], "10")
        self.assertEqual(preview["rings_between_openings"], 10)
        self.assertEqual(preview["stratum_info_between"], {})
        self.assertEqual(preview["stratum_info_between_list"], [])
        self.assertEqual(preview["geological_conditions"], "")

        serializer = WarehouseOpeningBasicInfoCreateUpdateSerializer(data={
            "project": project.id,
            "shield_model": shield.id,
            "ring_no": "20",
            "open_time": timezone.now(),
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        opening = serializer.save()
        self.assertEqual(opening.last_ring_no, "10")
        self.assertEqual(opening.rings_between_openings, 10)
        self.assertEqual(opening.stratum_info_between, {})
        self.assertEqual(opening.geological_conditions, "")

    def test_duplicate_ring_uses_unique_warehouse_suffix(self):
        serializer = WarehouseOpeningBasicInfoCreateUpdateSerializer(data={
            "project": self.project.id,
            "shield_model": self.shield.id,
            "ring_no": "100",
            "open_time": timezone.now(),
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        duplicate = serializer.save()

        self.assertEqual(duplicate.warehouse_id, "STRATUM-AUTO-100-2")
        self.assertIsNone(duplicate.last_ring_no)
        self.assertEqual(duplicate.rings_between_openings, 100)

    def test_non_numeric_ring_is_rejected(self):
        serializer = WarehouseOpeningBasicInfoCreateUpdateSerializer(data={
            "project": self.project.id,
            "shield_model": self.shield.id,
            "ring_no": "105环",
            "open_time": timezone.now(),
        })

        self.assertFalse(serializer.is_valid())
        # CustomModelSerializer 按项目统一约定将错误键转换为模型 verbose_name。
        self.assertIn("ring no", serializer.errors)
