import json

from django.test import TestCase
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIRequestFactory

from dvadmin.system.models import Role, Users
from application.shield.models import (
    CutterImageAnnotation,
    CutterPositionInfo,
    MobileToolChangeTask,
    ProjectInfo,
    ShieldMachineBasicInfo,
    StratumBasicInfo,
    ToolCost,
    ToolInfo,
    WarehouseOpeningBasicInfo,
)
from application.shield.mobile_views import MobileTaskViewSet, mobile_field_options, old_tool_inspection_payload
from application.shield.mobile_views import MobileToolChangeDetailSerializer
from application.shield.views import (
    CutterImageAnnotationViewSet,
    ToolChangeDetailViewSet,
    WarehouseOpeningBasicInfoCreateUpdateSerializer,
    _build_opening_stratum_context,
)
from application.shield.trajectory import get_tool_trajectory


class ToolChangeFlowTests(TestCase):
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
            tool_change_duration=2.5,
            usage_distance=120.0,
        )
        self.task = MobileToolChangeTask.objects.get(warehouse=self.opening)

    @staticmethod
    def request_for(user, method="get", data=None):
        factory = APIRequestFactory()
        request = getattr(factory, method)("/", data=data or {})
        request.user = user
        return request

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

    def test_mobile_save_and_submit_keep_uninspected_positions_pending(self):
        view = MobileTaskViewSet()
        detail = self.opening.tool_change_details.get(cutter_position_no="1")
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
        self.assertEqual(detail.old_tool_record.photos.count(), 1)

        self.first_operator.is_superuser = True
        self.first_operator.save(update_fields=["is_superuser"])
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
        detail.old_tool_record.refresh_from_db()
        self.assertEqual(detail.old_tool_record.ring_tooth_loss_count, 3)
        self.assertEqual(detail.old_tool_record.ring_damage, ["CHIP", "BOLT_LOSS"])
        self.assertEqual(detail.old_tool_record.disposition, "REPAIRABLE")

        submit_request = view.initialize_request(self.request_for(self.first_operator, method="post"))
        submit_request.user = self.first_operator
        submit_response = view.submit(submit_request, pk=self.task.id)
        self.assertEqual(submit_response.data["code"], 2000)
        self.assertEqual(submit_response.data["data"]["progress"]["saved"], 1)
        untouched = self.opening.tool_change_details.get(cutter_position_no="2")
        self.assertFalse(untouched.is_checked)
        self.assertEqual(untouched.mobile_status, "SUBMITTED")
        self.assertEqual(untouched.check_result, "PENDING")

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
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        opening = serializer.save()

        self.assertEqual(opening.last_ring_no, "100")
        self.assertEqual(opening.rings_between_openings, 5)
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
        self.assertEqual(
            preview["stratum_info_between_list"],
            [
                {"stratum_type_code": "CLAY", "stratum_type_name": "CLAY", "ring_count": 1},
                {"stratum_type_code": "SAND", "stratum_type_name": "SAND", "ring_count": 1},
            ],
        )
        self.assertEqual(preview["geological_conditions"], "SAND；局部含砂；埋深 18.5 m")
