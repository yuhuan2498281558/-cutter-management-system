from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from application.ai_assistant.views import _memory_user_id
from dvadmin.system.management.commands.configure_guest_access import (
    GUEST_API_RULES,
    GUEST_MENU_PATHS,
)
from dvadmin.system.models import (
    Menu,
    Role,
    RoleMenuButtonPermission,
    RoleMenuPermission,
    Users,
)
from dvadmin.utils.filters import DataLevelPermissionsFilter, is_web_guest_full_read


class GuestAccessTests(TestCase):
    def setUp(self):
        self.role = Role.objects.create(name="只读游客", key=settings.WEB_GUEST_ROLE_KEY)
        self.user = Users.objects.create(
            username=settings.WEB_GUEST_USERNAME,
            name="游客",
            pwd_change_count=1,
            is_active=True,
        )
        self.user.set_unusable_password()
        self.user.save()
        self.user.role.add(self.role)

    def guest_token(self):
        response = APIClient(HTTP_USER_AGENT="guest-access-test").post(
            "/api/guest-login/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["code"], 2000)
        self.assertEqual(response.data["data"]["username"], settings.WEB_GUEST_USERNAME)
        return response.data["data"]["access"]

    def test_guest_login_requires_the_reserved_active_non_admin_role(self):
        token = self.guest_token()
        self.assertTrue(token)

        self.user.role.clear()
        unavailable = APIClient(HTTP_USER_AGENT="guest-access-test").post(
            "/api/guest-login/", {}, format="json"
        )
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.data["code"], 4000)

    def test_guest_login_sessions_have_distinct_stable_memory_scopes(self):
        first = APIClient(HTTP_USER_AGENT="guest-access-test").post(
            "/api/guest-login/", {}, format="json"
        ).data["data"]
        second = APIClient(HTTP_USER_AGENT="guest-access-test").post(
            "/api/guest-login/", {}, format="json"
        ).data["data"]

        first_access = AccessToken(first["access"])
        first_refresh = RefreshToken(first["refresh"])
        claim = settings.WEB_GUEST_SESSION_CLAIM
        self.assertEqual(first_access[claim], first_refresh[claim])
        self.assertNotEqual(first_access[claim], AccessToken(second["access"])[claim])
        self.assertEqual(
            _memory_user_id(self.user, first_access),
            _memory_user_id(self.user, first_refresh),
        )
        self.assertNotEqual(
            _memory_user_id(self.user, first_access),
            _memory_user_id(self.user, AccessToken(second["access"])),
        )

    def test_guest_can_read_but_cannot_write_or_use_mobile_workflows(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"JWT {self.guest_token()}")

        info = client.get("/api/system/user/user_info/")
        self.assertEqual(info.status_code, 200, info.content)
        self.assertEqual(info.data["data"]["username"], settings.WEB_GUEST_USERNAME)

        update = client.put("/api/system/user/update_user_info/", {"name": "changed"}, format="json")
        self.assertEqual(update.status_code, 403)
        self.assertEqual(update.json()["code"], 4000)
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "游客")

        unguarded_action = client.post("/api/system/menu/move_up/", {"menu_id": 1}, format="json")
        self.assertEqual(unguarded_action.status_code, 403)

        mobile_get = client.get("/api/shield/mobile/tasks/1/")
        self.assertEqual(mobile_get.status_code, 403)
        self.assertIn("移动作业", mobile_get.json()["msg"])

        lifecycle = client.get("/api/shield/mobile/tool_lifecycle/?page=1&limit=1")
        self.assertEqual(lifecycle.status_code, 200, lifecycle.content)
        self.assertEqual(lifecycle.data["code"], 2000)

        invalid_ai_query = client.post("/api/ai/chat/", {}, format="json")
        self.assertEqual(invalid_ai_query.status_code, 200, invalid_ai_query.content)
        self.assertEqual(invalid_ai_query.data["code"], 4000)

        with patch("application.ai_assistant.views.get_assistant") as get_assistant:
            get_assistant.return_value.reset_memory.return_value = None
            reset = client.post("/api/ai/reset/", {}, format="json")
        self.assertEqual(reset.status_code, 200, reset.content)
        reset_scope = get_assistant.return_value.reset_memory.call_args.kwargs["user_id"]
        self.assertTrue(reset_scope.startswith(f"guest-session-{self.user.id}-"))

        wrong_method = client.put("/api/ai/chat/", {}, format="json")
        self.assertEqual(wrong_method.status_code, 403)

        logout = client.post("/api/logout/", {}, format="json")
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(logout.data["code"], 2000)

    def test_guest_full_data_scope_is_limited_to_configured_business_reads(self):
        self.assertEqual(
            set(settings.WEB_GUEST_READ_API_PREFIXES),
            {api[:-2] for _, _, api in GUEST_API_RULES},
        )
        allowed = SimpleNamespace(
            user=self.user,
            method="GET",
            path="/api/shield/project/1/",
        )
        self.assertTrue(is_web_guest_full_read(allowed))
        queryset = Users.objects.order_by("id")
        filtered = DataLevelPermissionsFilter().filter_queryset(allowed, queryset, view=None)
        self.assertEqual(
            list(filtered.values_list("id", flat=True)),
            list(queryset.values_list("id", flat=True)),
        )

        for method, path in (
            ("POST", "/api/shield/project/"),
            ("GET", "/api/shield/mobile/tasks/"),
            ("GET", "/api/system/user/"),
        ):
            denied = SimpleNamespace(user=self.user, method=method, path=path)
            self.assertFalse(is_web_guest_full_read(denied))


class ConfigureGuestAccessTests(TestCase):
    def setUp(self):
        for index, path in enumerate(GUEST_MENU_PATHS):
            Menu.objects.create(name=f"menu-{index}", web_path=path, status=True)

    def test_dry_run_is_read_only_and_apply_is_idempotent(self):
        output = StringIO()
        call_command("configure_guest_access", stdout=output)
        self.assertIn("DRY-RUN", output.getvalue())
        self.assertFalse(Users.objects.filter(username=settings.WEB_GUEST_USERNAME).exists())
        self.assertFalse(Role.objects.filter(key=settings.WEB_GUEST_ROLE_KEY).exists())

        call_command("configure_guest_access", apply=True, stdout=StringIO())
        role = Role.objects.get(key=settings.WEB_GUEST_ROLE_KEY)
        user = Users.objects.get(username=settings.WEB_GUEST_USERNAME)
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(list(user.role.values_list("id", flat=True)), [role.id])
        self.assertEqual(RoleMenuPermission.objects.filter(role=role).count(), len(GUEST_MENU_PATHS))
        self.assertIn("toolLifecycle", GUEST_MENU_PATHS)
        self.assertIn("/ai-assistant", GUEST_MENU_PATHS)
        permissions = RoleMenuButtonPermission.objects.filter(role=role).select_related("menu_button")
        self.assertEqual(permissions.count(), len(GUEST_API_RULES))
        self.assertTrue(all(item.data_range == 3 for item in permissions))
        self.assertTrue(all(item.menu_button.method == 0 for item in permissions))
        self.assertTrue(all(item.menu_button.api.endswith(".*") for item in permissions))

        call_command("configure_guest_access", apply=True, stdout=StringIO())
        self.assertEqual(RoleMenuPermission.objects.filter(role=role).count(), len(GUEST_MENU_PATHS))
        self.assertEqual(RoleMenuButtonPermission.objects.filter(role=role).count(), len(GUEST_API_RULES))
