# 添加Home菜单的Django管理命令

from django.core.management.base import BaseCommand
from dvadmin.system.models import Menu

class Command(BaseCommand):
    help = '添加Home首页菜单'

    def handle(self, *args, **options):
        # 检查是否已存在home菜单
        home_menu = Menu.objects.filter(web_path='/home').first()

        if home_menu:
            self.stdout.write(self.style.SUCCESS('Home menu already exists'))
            return

        # 创建home菜单
        Menu.objects.create(
            name='home',
            web_path='/home',
            component_name='home',
            sort=0,
            visible=True,
            status=True,
            is_catalog=False,
            is_link=False,
            is_iframe=False,
            is_affix=True,
            cache=True,
            icon='iconfont icon-shouye',
            parent=None
        )

        self.stdout.write(self.style.SUCCESS('Home menu created successfully'))
