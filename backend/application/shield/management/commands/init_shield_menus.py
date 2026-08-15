# -*- coding: utf-8 -*-
"""
Initialize shield management menus.
"""
from django.core.management.base import BaseCommand
from django.db import models

from dvadmin.system.models import Menu, MenuButton


PARENT_MENU = {
    "name": "盾构项目管理",
    "web_path": "/shield",
    "component": "Layout",
    "component_name": "Shield",
    "icon": "iconfont icon-gongcheng",
}


MENUS = [
    {
        "name": "项目信息管理",
        "web_path": "/shield/project",
        "component": "shield/project/index",
        "component_name": "ShieldProject",
        "api_module": "project",
        "sort": 1,
    },
    {
        "name": "盾构机信息",
        "web_path": "/shield/shieldMachineBasicInfo",
        "component": "shield/shieldMachineBasicInfo/index",
        "component_name": "ShieldMachineBasicInfo",
        "api_module": "shield_machine_basic_info",
        "sort": 2,
    },
    {
        "name": "地层基本信息",
        "web_path": "/shield/stratumBasicInfo",
        "component": "shield/stratumBasicInfo/index",
        "component_name": "ShieldStratumBasicInfo",
        "api_module": "stratum_basic_info",
        "sort": 3,
    },
    {
        "name": "刀具类型管理",
        "web_path": "/shield/toolType",
        "component": "shield/toolType/index",
        "component_name": "ShieldToolType",
        "api_module": "tool_category",
        "sort": 10,
    },
    {
        "name": "刀具成本管理",
        "web_path": "/shield/toolCost",
        "component": "shield/toolCost/index",
        "component_name": "ShieldToolCost",
        "api_module": "tool_cost",
        "sort": 11,
    },
    {
        "name": "刀具信息管理",
        "web_path": "/shield/toolInfo",
        "component": "shield/toolInfo/index",
        "component_name": "ShieldToolInfo",
        "api_module": "tool_info",
        "sort": 12,
    },
    {
        "name": "开仓基本信息",
        "web_path": "/shield/warehouseOpening",
        "component": "shield/warehouseOpening/index",
        "component_name": "ShieldWarehouseOpening",
        "api_module": "warehouse_opening",
        "sort": 20,
    },
    {
        "name": "换刀明细",
        "web_path": "/shield/toolChangeDetail",
        "component": "shield/toolChangeDetail/index",
        "component_name": "ShieldToolChangeDetail",
        "api_module": "tool_change_detail",
        "sort": 21,
    },
    {
        "name": "磨损类型字典",
        "web_path": "/shield/wearTypeDict",
        "component": "shield/wearTypeDict/index",
        "component_name": "ShieldWearTypeDict",
        "api_module": "wear_type_dict",
        "sort": 30,
    },
    {
        "name": "异常原因字典",
        "web_path": "/shield/abnormalCauseDict",
        "component": "shield/abnormalCauseDict/index",
        "component_name": "ShieldAbnormalCauseDict",
        "api_module": "abnormal_cause_dict",
        "sort": 31,
    },
    {
        "name": "掘进动态数据",
        "web_path": "/shield/tunnelingData",
        "component": "shield/tunnelingData/index",
        "component_name": "ShieldTunnelingData",
        "api_module": "tunneling_data",
        "sort": 40,
    },
    {
        "name": "刀具寿命预测",
        "web_path": "/shield/toolLifePrediction",
        "component": "shield/toolLifePrediction/index",
        "component_name": "ShieldToolLifePrediction",
        "api_module": "tool_life_prediction",
        "sort": 41,
    },
    {
        "name": "数据分析",
        "web_path": "/shield/analysis",
        "component": "shield/analysis/index",
        "component_name": "ShieldAnalysis",
        "api_module": "analysis",
        "sort": 50,
        "read_only": True,
    },
]


STANDARD_BUTTONS = [
    {"name": "查看", "value": "Retrieve", "api": "/api/shield/{module}/{id}/", "method": 1},
    {"name": "新增", "value": "Create", "api": "/api/shield/{module}/", "method": 2},
    {"name": "修改", "value": "Update", "api": "/api/shield/{module}/{id}/", "method": 3},
    {"name": "删除", "value": "Delete", "api": "/api/shield/{module}/{id}/", "method": 4},
    {"name": "批量删除", "value": "BatchDelete", "api": "/api/shield/{module}/multiple_delete/", "method": 4},
]


READ_ONLY_BUTTONS = [
    {"name": "查看", "value": "Retrieve", "api": "/api/shield/{module}/", "method": 1},
]


class Command(BaseCommand):
    help = "初始化或补齐盾构项目管理菜单"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("开始初始化盾构项目管理菜单..."))

        parent = Menu.objects.filter(name=PARENT_MENU["name"], parent__isnull=True).first()
        parent_created = parent is None
        if parent_created:
            max_sort = Menu.objects.filter(parent__isnull=True).aggregate(max_sort=models.Max("sort"))["max_sort"] or 0
            parent = Menu.objects.create(
                name=PARENT_MENU["name"],
                web_path=PARENT_MENU["web_path"],
                component=PARENT_MENU["component"],
                component_name=PARENT_MENU["component_name"],
                sort=max_sort + 1,
                status=True,
                is_link=False,
                is_catalog=True,
                parent=None,
                icon=PARENT_MENU["icon"],
                cache=False,
                visible=True,
            )
        else:
            parent.web_path = PARENT_MENU["web_path"]
            parent.component = PARENT_MENU["component"]
            parent.component_name = PARENT_MENU["component_name"]
            parent.status = True
            parent.is_link = False
            parent.is_catalog = True
            parent.parent = None
            parent.icon = PARENT_MENU["icon"]
            parent.cache = False
            parent.visible = True
            parent.save()
        action = "创建" if parent_created else "更新"
        self.stdout.write(self.style.SUCCESS(f"[OK] {action}一级菜单: {parent.name}"))

        menu_created_count = 0
        menu_updated_count = 0
        button_count = 0

        for menu_data in MENUS:
            menu, created = Menu.objects.update_or_create(
                web_path=menu_data["web_path"],
                defaults={
                    "name": menu_data["name"],
                    "component": menu_data["component"],
                    "component_name": menu_data["component_name"],
                    "parent": parent,
                    "sort": menu_data["sort"],
                    "status": True,
                    "is_link": False,
                    "is_catalog": False,
                    "icon": "iconfont icon-caidan",
                    "cache": True,
                    "visible": True,
                },
            )
            if created:
                menu_created_count += 1
            else:
                menu_updated_count += 1

            buttons = READ_ONLY_BUTTONS if menu_data.get("read_only") else STANDARD_BUTTONS
            for btn_data in buttons:
                value = f"Shield{menu_data['component_name'].replace('Shield', '')}{btn_data['value']}"
                MenuButton.objects.update_or_create(
                    menu=menu,
                    value=value,
                    defaults={
                        "name": btn_data["name"],
                        "api": btn_data["api"].replace("{module}", menu_data["api_module"]),
                        "method": btn_data["method"],
                    },
                )
                button_count += 1

            self.stdout.write(self.style.SUCCESS(f"  [OK] {'创建' if created else '更新'}子菜单: {menu.name}"))

        valid_paths = {menu_data["web_path"] for menu_data in MENUS}
        stale_count = Menu.objects.filter(parent=parent).exclude(web_path__in=valid_paths).update(
            status=False,
            visible=False,
        )
        if stale_count:
            self.stdout.write(self.style.WARNING(f"已隐藏废弃菜单：{stale_count} 个"))

        self.stdout.write(self.style.SUCCESS(f"\n菜单初始化完成：新建 {menu_created_count} 个，更新 {menu_updated_count} 个"))
        self.stdout.write(self.style.SUCCESS(f"按钮权限已补齐：{button_count} 个"))
        self.stdout.write(self.style.SUCCESS("请重新执行 assign_shield_permissions 并重新登录系统以刷新权限"))
