"""Non-superuser regression for the narrow shield permission repair."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from dvadmin.system.models import (
    ApiWhiteList, Dept, Menu, MenuButton, Role, RoleMenuButtonPermission,
    RoleMenuPermission, Users,
)
from dvadmin.utils.permission import CustomPermission
from application.shield.management.commands.init_shield_menus import STANDARD_BUTTONS
from application.shield.models import ProjectInfo, ShieldMachineBasicInfo, WarehouseOpeningBasicInfo
from application.shield.views import WarehouseOpeningBasicInfoViewSet


class ShieldPermissionRepairTests(TestCase):
    def setUp(self):
        # Each test runs in the isolated test database; no bypass whitelist applies.
        ApiWhiteList.objects.all().delete()
        self.factory = APIRequestFactory()
        self.dept = Dept.objects.create(name="权限测试部门", key="permission-test")
        self.editor_role = Role.objects.create(name="编辑测试", key="permission-editor")
        self.reader_role = Role.objects.create(name="只读测试", key="permission-reader")
        self.orphan_role = Role.objects.create(name="无菜单测试", key="permission-orphan")
        self.editor = self.user("permission-editor", self.editor_role)
        self.reader = self.user("permission-reader", self.reader_role)
        self.orphan = self.user("permission-orphan", self.orphan_role)
        self.menus = {}
        self.buttons = {}
        for path, module, prefix in (
            ("/shield/warehouseOpening", "warehouse_opening", "ShieldWarehouse_opening"),
            ("/shield/toolChangeDetail", "tool_change_detail", "ShieldToolChangeDetail"),
        ):
            menu = Menu.objects.create(name=module, web_path=path)
            self.menus[module] = menu
            for role in (self.editor_role, self.reader_role):
                RoleMenuPermission.objects.create(menu=menu, role=role)
            for spec in STANDARD_BUTTONS:
                button = MenuButton.objects.create(
                    menu=menu, name=spec["name"], value=prefix + spec["value"],
                    api=spec["api"].replace("{module}", module), method=spec["method"] + 1,
                )
                self.buttons[(module, spec["value"])] = button
                if spec["value"] == "Retrieve":
                    for role in (self.reader_role, self.editor_role):
                        RoleMenuButtonPermission.objects.create(role=role, menu_button=button, data_range=3)
                if spec["value"] == "Update":
                    for role in (self.editor_role, self.orphan_role):
                        RoleMenuButtonPermission.objects.create(role=role, menu_button=button, data_range=3)

    def user(self, username, role):
        user = Users.objects.create(username=username, name=username, dept=self.dept, is_superuser=False)
        user.role.add(role)
        return user

    def repair(self, apply=True):
        output = StringIO()
        call_command("repair_shield_permissions", apply=apply, stdout=output)
        return output.getvalue()

    def allowed(self, user, method, path):
        request = getattr(self.factory, method.lower())(path)
        request.user = user
        return bool(CustomPermission().has_permission(request, None))

    def test_dry_run_is_read_only_and_apply_is_idempotent(self):
        button_ids = set(MenuButton.objects.values_list("id", flat=True))
        grant_ids = set(RoleMenuButtonPermission.objects.values_list("id", flat=True))
        preview = self.repair(apply=False)
        self.assertIn("methods=10 buttons=8", preview)
        self.assertEqual(button_ids, set(MenuButton.objects.values_list("id", flat=True)))
        self.assertEqual(grant_ids, set(RoleMenuButtonPermission.objects.values_list("id", flat=True)))
        self.buttons[("warehouse_opening", "Update")].refresh_from_db()
        self.assertEqual(self.buttons[("warehouse_opening", "Update")].method, 3)
        self.repair()
        self.assertTrue(button_ids.issubset(MenuButton.objects.values_list("id", flat=True)))
        self.assertTrue(grant_ids.issubset(RoleMenuButtonPermission.objects.values_list("id", flat=True)))
        self.assertIn("methods=0 buttons=0 grants=0 skipped=0", self.repair())

    def test_editor_can_edit_confirm_and_supplement_but_cannot_delete(self):
        base = "/api/shield/warehouse_opening/1/"
        self.assertTrue(self.allowed(self.editor, "DELETE", base))  # original regression
        self.assertFalse(self.allowed(self.editor, "PUT", base))
        self.repair()
        for module in ("warehouse_opening", "tool_change_detail"):
            path = f"/api/shield/{module}/1/"
            self.assertTrue(self.allowed(self.editor, "PUT", path))
            self.assertFalse(self.allowed(self.editor, "DELETE", path))
            self.assertFalse(self.allowed(self.editor, "DELETE", f"/api/shield/{module}/multiple_delete/"))
        for action in ("complete_summary", "withdraw_summary"):
            self.assertTrue(self.allowed(self.editor, "POST", base + action + "/"))
            self.assertFalse(self.allowed(self.reader, "POST", base + action + "/"))
            self.assertFalse(self.allowed(self.orphan, "POST", base + action + "/"))
        old_path = "/api/shield/tool_change_detail/1/old_tool_record/"
        for method in ("GET", "POST", "PUT"):
            self.assertTrue(self.allowed(self.editor, method, old_path))
        self.assertTrue(self.allowed(self.reader, "GET", old_path))
        for method in ("POST", "PUT", "DELETE"):
            self.assertFalse(self.allowed(self.reader, method, old_path))
        for path in ("/api/shield/warehouse_opening/", "/api/shield/tool_change_detail/", "/api/shield/cutter_position_info/"):
            self.assertTrue(self.allowed(self.reader, "GET", path))
        self.assertFalse(self.allowed(self.editor, "POST", "/api/shield/tool_change_detail/batch_update/"))

    def test_real_summary_endpoint_accepts_editor_and_rejects_reader(self):
        self.repair()
        project = ProjectInfo.objects.create(project_id="PERMISSION-PROJECT", project_name="权限测试")
        shield = ShieldMachineBasicInfo.objects.create(shield_model_id="PERMISSION-SHIELD", shield_model="权限测试")
        opening = WarehouseOpeningBasicInfo.objects.create(
            project=project, shield_model=shield, ring_no="100", open_time=timezone.now(),
            blade_track="测试", dept_belong_id=self.dept.pk,
        )
        path = f"/api/shield/warehouse_opening/{opening.pk}/complete_summary/"
        view = WarehouseOpeningBasicInfoViewSet.as_view({"post": "complete_summary"})
        payload = {"opening_duration": 2, "tool_change_duration": 1, "checked_tool_count": 0, "replaced_tool_count": 0}
        for user, expected in ((self.reader, 4000), (self.editor, 2000)):
            request = self.factory.post(path, payload, format="json")
            force_authenticate(request, user=user)
            response = view(request, pk=str(opening.pk))
            # This API wraps permission errors in its standard HTTP-200 envelope.
            self.assertEqual(response.data["code"], expected, response.data)
        opening.refresh_from_db()
        self.assertEqual(opening.summary_status, "CONFIRMED")
        self.assertEqual(opening.summary_confirmed_by_id, self.editor.pk)

    def test_custom_buttons_are_preserved_and_not_used_as_inheritance_sources(self):
        source = self.buttons[("warehouse_opening", "Update")]
        source.name = "自定义修改"
        source.save(update_fields=["name"])
        custom = MenuButton.objects.create(
            menu=self.menus["tool_change_detail"], name="自定义", value="ShieldCustomButton",
            api="/api/shield/tool_change_detail/{id}/", method=3,
        )
        conflict = MenuButton.objects.create(
            menu=self.menus["warehouse_opening"], name="自定义确认", value="ShieldWarehouseOpeningCompleteSummary",
            api="/custom/", method=1,
        )
        output = self.repair()
        self.assertIn("SKIP custom/conflicting", output)
        source.refresh_from_db()
        custom.refresh_from_db()
        conflict.refresh_from_db()
        self.assertEqual(source.method, 3)
        self.assertEqual(custom.method, 3)
        self.assertEqual(conflict.api, "/custom/")
        self.assertFalse(RoleMenuButtonPermission.objects.filter(menu_button__value="ShieldWarehouseOpeningWithdrawSummary").exists())

    def test_inherited_data_scope_and_departments_are_preserved(self):
        source = RoleMenuButtonPermission.objects.get(
            role=self.editor_role, menu_button=self.buttons[("warehouse_opening", "Update")]
        )
        source.data_range = 4
        source.save(update_fields=["data_range"])
        source.dept.add(self.dept)
        self.repair()
        inherited = RoleMenuButtonPermission.objects.get(role=self.editor_role, menu_button__value="ShieldWarehouseOpeningCompleteSummary")
        self.assertEqual(inherited.data_range, 4)
        self.assertEqual(list(inherited.dept.values_list("id", flat=True)), [self.dept.pk])
        inherited.data_range = 0  # a later explicit role customization must survive reruns
        inherited.save(update_fields=["data_range"])
        self.repair()
        inherited.refresh_from_db()
        self.assertEqual(inherited.data_range, 0)
