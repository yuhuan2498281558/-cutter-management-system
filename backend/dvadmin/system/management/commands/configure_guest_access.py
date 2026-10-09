from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dvadmin.system.models import (
    Menu,
    MenuButton,
    Role,
    RoleMenuButtonPermission,
    RoleMenuPermission,
    Users,
)


GUEST_MENU_PATHS = (
    "/home",
    "/projectInfo",
    "/shield/project",
    "/shield/stratumBasicInfo",
    "/shield/shieldMachineBasicInfo",
    "/shield/toolInfoManage",
    "/shield/warehouseOpening",
    "/shield/toolChangeDetail",
    "/shield/toolCost",
    "/shield/analysis",
    "/shield/analysis/overview",
    "/shield/toolLifePrediction",
    "/shield/tunnelingData",
    "toolLifecycle",
    "/ai-assistant",
)

GUEST_API_RULES = (
    ("/shield/project", "project", "/api/shield/project/.*"),
    ("/shield/stratumBasicInfo", "stratum", "/api/shield/stratum_basic_info/.*"),
    ("/shield/shieldMachineBasicInfo", "shield-machine", "/api/shield/shield_machine_basic_info/.*"),
    ("/shield/shieldMachineBasicInfo", "cutter-position", "/api/shield/cutter_position_info/.*"),
    ("/shield/toolInfoManage", "tool-info", "/api/shield/tool_info/.*"),
    ("/shield/toolInfoManage", "tool-category", "/api/shield/tool_category/.*"),
    ("/shield/warehouseOpening", "warehouse-opening", "/api/shield/warehouse_opening/.*"),
    ("/shield/toolChangeDetail", "tool-change-detail", "/api/shield/tool_change_detail/.*"),
    ("/shield/toolCost", "tool-cost", "/api/shield/tool_cost/.*"),
    ("/shield/analysis/overview", "analysis", "/api/shield/analysis/.*"),
    ("/shield/toolLifePrediction", "tool-life", "/api/shield/tool_life_prediction/.*"),
    ("/shield/tunnelingData", "tunneling", "/api/shield/tunneling_data/.*"),
    ("toolLifecycle", "tool-lifecycle", "/api/shield/mobile/tool_lifecycle/.*"),
)


class Command(BaseCommand):
    help = "Preview or configure the fixed read-only web guest account and role."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the configuration. Without this flag the command is read-only.",
        )

    def handle(self, *args, **options):
        menus = {menu.web_path: menu for menu in Menu.objects.filter(web_path__in=GUEST_MENU_PATHS)}
        missing = sorted(set(GUEST_MENU_PATHS) - set(menus))
        if missing:
            raise CommandError("Required guest menus are missing: " + ", ".join(missing))

        summary = (
            f"username={settings.WEB_GUEST_USERNAME} role={settings.WEB_GUEST_ROLE_KEY} "
            f"menus={len(GUEST_MENU_PATHS)} read_rules={len(GUEST_API_RULES)}"
        )
        if not options["apply"]:
            self.stdout.write("DRY-RUN " + summary)
            return

        with transaction.atomic():
            role, _ = Role.objects.update_or_create(
                key=settings.WEB_GUEST_ROLE_KEY,
                defaults={"name": "只读游客", "status": True, "sort": 99},
            )
            user, _ = Users.objects.get_or_create(
                username=settings.WEB_GUEST_USERNAME,
                defaults={"name": "游客", "pwd_change_count": 1},
            )
            user.name = "游客"
            user.is_active = True
            user.is_staff = False
            user.is_superuser = False
            user.user_type = 0
            user.pwd_change_count = 1
            user.login_error_count = 0
            user.current_role = role
            user.set_unusable_password()
            user.save()
            user.role.set([role])

            RoleMenuPermission.objects.filter(role=role).delete()
            RoleMenuPermission.objects.bulk_create(
                [RoleMenuPermission(role=role, menu=menus[path]) for path in GUEST_MENU_PATHS]
            )

            RoleMenuButtonPermission.objects.filter(role=role).delete()
            buttons = []
            for menu_path, key, api in GUEST_API_RULES:
                button, _ = MenuButton.objects.update_or_create(
                    value=f"guest:read:{key}",
                    defaults={
                        "menu": menus[menu_path],
                        "name": "游客查看",
                        "api": api,
                        "method": 0,
                    },
                )
                buttons.append(button)
            RoleMenuButtonPermission.objects.bulk_create(
                [
                    RoleMenuButtonPermission(role=role, menu_button=button, data_range=3)
                    for button in buttons
                ]
            )

        self.stdout.write(self.style.SUCCESS("APPLIED " + summary))
