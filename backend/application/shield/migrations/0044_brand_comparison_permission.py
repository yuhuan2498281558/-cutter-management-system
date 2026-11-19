"""厂家对比改成一个接口后，原来按接口授权过旧厂家对照表接口的角色同样能访问新接口，数据范围和部门照旧。

数据权限过滤（dvadmin/utils/filters.py）按请求路径精确找按钮，再把一个用户在这个路径上的全部授权合并：
有"全部"就放开，有"仅本人"就收紧。所以这里按路径精确匹配，并把角色在旧接口上的每一条授权都原样复制。
旧前端三个厂家接口一起请求、缺一个整块报错，能用的角色一定有对照表接口 brand_cost 的授权，只从它复制。
"""
from django.db import migrations

OLD_API = "/api/shield/analysis/brand_cost/"
NEW_API = "/api/shield/analysis/brand_comparison/"
GET = 0
VALUE = "ShieldAnalysisBrandComparison"


def grant_brand_comparison(apps, schema_editor):
    MenuButton = apps.get_model("system", "MenuButton")
    Permission = apps.get_model("system", "RoleMenuButtonPermission")
    # 已经有新接口授权的角色（哪个菜单下都算）是管理员配过的，补一条就可能改变它的合并范围
    configured = set(Permission.objects.filter(menu_button__api=NEW_API, menu_button__method=GET).values_list("role_id", flat=True))
    buttons = {}
    grants = (Permission.objects.filter(menu_button__api=OLD_API, menu_button__method=GET)
              .exclude(role_id__in=configured).select_related("menu_button"))
    for grant in grants:
        menu_id = grant.menu_button.menu_id
        if menu_id not in buttons:
            button = MenuButton.objects.filter(menu_id=menu_id, api=NEW_API, method=GET).first()
            if button is None:
                value, suffix = VALUE, 1
                while MenuButton.objects.filter(value=value).exists():
                    suffix += 1
                    value = f"{VALUE}{suffix}"
                button = MenuButton.objects.create(menu_id=menu_id, name="厂家对比", value=value, api=NEW_API, method=GET)
            buttons[menu_id] = button
        copy = Permission.objects.create(role_id=grant.role_id, menu_button=buttons[menu_id], data_range=grant.data_range)
        copy.dept.set(grant.dept.all())


class Migration(migrations.Migration):

    dependencies = [
        ("shield", "0043_revolution_readings"),
        ("system", "0001_initial"),
    ]

    # 回退时不删授权：之后管理员可能手工调整过
    operations = [
        migrations.RunPython(grant_brand_comparison, migrations.RunPython.noop),
    ]
