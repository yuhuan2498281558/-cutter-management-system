"""Repair known shield button definitions without resetting menus or role policy."""
from django.core.management.base import BaseCommand
from django.db import transaction

from dvadmin.system.models import Menu, MenuButton, RoleMenuButtonPermission, RoleMenuPermission
from .init_shield_menus import MENUS, READ_ONLY_BUTTONS, STANDARD_BUTTONS, WORKFLOW_BUTTONS


# Explicit legacy definitions observed in the original installers/current database.
# Do not infer arbitrary Shield* buttons as managed permissions.
LEGACY_PREFIXES = {
    "warehouse_opening": ("ShieldWarehouse_opening",),
    "stratum_basic_info": ("ShieldStratum_basic_info",),
    "shield_machine_basic_info": ("ShieldShield_machine_basic_info",),
    "tool_cost": ("ShieldToolcost",),
    "tool_info": ("ShieldTool_info",),
}
LEGACY_PATHS = {"tool_info": ("/shield/toolInfoManage",)}


class Command(BaseCommand):
    help = "最小修复盾构标准按钮方法和补录权限；默认只预览，--apply 才写入"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="应用已预览的修复（不初始化菜单或授予全部权限）")

    @transaction.atomic
    def handle(self, *args, **options):
        apply = options["apply"]
        self.stdout.write("APPLY" if apply else "DRY RUN: no writes")
        counts = {"methods": 0, "buttons": 0, "grants": 0, "skipped": 0}
        for menu_data in MENUS:
            module = menu_data["api_module"]
            paths = (menu_data["web_path"],) + LEGACY_PATHS.get(module, ())
            menus = list(Menu.objects.filter(web_path__in=paths))
            if not menus:
                continue
            if len(menus) != 1:
                self.stdout.write(f"SKIP ambiguous menu: {module}")
                counts["skipped"] += 1
                continue
            menu = menus[0]
            prefix = "Shield" + menu_data["component_name"].replace("Shield", "")
            prefixes = (prefix,) + LEGACY_PREFIXES.get(module, ())
            sources = {}
            standards = READ_ONLY_BUTTONS if menu_data.get("read_only") else STANDARD_BUTTONS
            for spec in standards:
                api = spec["api"].replace("{module}", module)
                apis = (api, "/api/shield/analysis/overview/") if module == "analysis" else (api,)
                candidates = MenuButton.objects.filter(menu=menu, value__in=[p + spec["value"] for p in prefixes])
                for button in candidates:
                    if button.name != spec["name"] or button.api not in apis or button.method not in (spec["method"], spec["method"] + 1):
                        self.stdout.write(f"SKIP custom/conflicting button id={button.pk} value={button.value}")
                        counts["skipped"] += 1
                        continue
                    sources.setdefault(spec["value"], []).append(button.pk)
                    if button.method != spec["method"]:
                        self.stdout.write(f"METHOD id={button.pk} {button.value}: {button.method} -> {spec['method']}")
                        counts["methods"] += 1
                        if apply:
                            MenuButton.objects.filter(pk=button.pk, method=button.method).update(method=spec["method"])

            menu_roles = set(RoleMenuPermission.objects.filter(menu=menu).values_list("role_id", flat=True))
            for spec in WORKFLOW_BUTTONS.get(module, []):
                value = prefix + spec["value"]
                api = spec["api"].replace("{module}", module)
                button = MenuButton.objects.filter(value=value).first()
                if button and (button.menu_id != menu.pk or button.name != spec["name"] or button.api != api or button.method != spec["method"]):
                    self.stdout.write(f"SKIP custom/conflicting workflow button: {value}")
                    counts["skipped"] += 1
                    continue
                if not button:
                    self.stdout.write(f"BUTTON menu={menu.pk} {value}: {spec['method']} {api}")
                    counts["buttons"] += 1
                    if apply:
                        button = MenuButton.objects.create(menu=menu, name=spec["name"], value=value, api=api, method=spec["method"])

                # Reads prefer the existing Retrieve scope, falling back to Update.
                # Writes derive ONLY from Update. Preserve custom dept scope too.
                source_grants = {}
                for semantic in spec["sources"]:
                    for grant in RoleMenuButtonPermission.objects.filter(
                        role_id__in=menu_roles, menu_button_id__in=sources.get(semantic, [])
                    ).order_by("id").prefetch_related("dept"):
                        source_grants.setdefault(grant.role_id, grant)
                for role_id, source in source_grants.items():
                    if button and RoleMenuButtonPermission.objects.filter(role_id=role_id, menu_button=button).exists():
                        continue
                    dept_ids = list(source.dept.values_list("id", flat=True))
                    self.stdout.write(f"GRANT role={role_id} {value} from={source.menu_button_id} data_range={source.data_range} dept_ids={dept_ids}")
                    counts["grants"] += 1
                    if apply:
                        grant = RoleMenuButtonPermission.objects.create(role_id=role_id, menu_button=button, data_range=source.data_range)
                        grant.dept.set(dept_ids)
        self.stdout.write("RESULT " + " ".join(f"{key}={value}" for key, value in counts.items()))
        if not apply:
            self.stdout.write("Review this plan, then run: python manage.py repair_shield_permissions --apply")
