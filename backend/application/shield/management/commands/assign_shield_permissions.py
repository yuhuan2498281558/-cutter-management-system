# -*- coding: utf-8 -*-
"""
为指定角色分配盾构项目管理的菜单和按钮权限
"""
from django.core.management.base import BaseCommand
from dvadmin.system.models import Role, Menu, MenuButton, RoleMenuPermission, RoleMenuButtonPermission


class Command(BaseCommand):
    help = '为指定角色分配盾构项目管理的菜单和按钮权限'

    def add_arguments(self, parser):
        parser.add_argument(
            '--role',
            type=str,
            default='用户',
            help='角色名称，默认为"用户"'
        )

    def handle(self, *args, **options):
        role_name = options['role']

        self.stdout.write(self.style.SUCCESS(f'开始为角色"{role_name}"分配盾构管理权限...'))

        # 查找角色
        try:
            role = Role.objects.get(name=role_name)
        except Role.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'角色"{role_name}"不存在！'))
            return

        # 查找盾构管理的所有菜单
        shield_parent = Menu.objects.filter(name='盾构项目管理').first()
        if not shield_parent:
            self.stdout.write(self.style.ERROR('盾构项目管理菜单不存在！请先运行 init_shield_menus'))
            return

        # 获取父菜单和所有子菜单
        shield_menus = [shield_parent] + list(Menu.objects.filter(parent=shield_parent))

        # 为角色分配菜单权限 - 通过中间表
        menu_count = 0
        for menu in shield_menus:
            RoleMenuPermission.objects.get_or_create(
                role=role,
                menu=menu
            )
            menu_count += 1
        self.stdout.write(self.style.SUCCESS(f'[OK] 已分配 {menu_count} 个菜单'))

        # 为角色分配所有按钮权限 - 通过中间表
        button_count = 0
        for menu in Menu.objects.filter(parent=shield_parent):
            buttons = MenuButton.objects.filter(menu=menu)
            for button in buttons:
                RoleMenuButtonPermission.objects.get_or_create(
                    role=role,
                    menu_button=button
                )
                button_count += 1

        self.stdout.write(self.style.SUCCESS(f'[OK] 已分配 {button_count} 个按钮权限'))
        self.stdout.write(self.style.SUCCESS(f'\n权限分配完成！'))
        self.stdout.write(self.style.SUCCESS(f'请重新登录系统以刷新权限'))
