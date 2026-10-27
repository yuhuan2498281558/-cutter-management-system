"""厂家对比改成一个接口后，原来按接口授权过旧厂家接口的角色同样能访问新接口，数据范围和部门照旧。"""
from django.db import migrations

OLD_APIS = [
    "/api/shield/analysis/brand_cost/",
    "/api/shield/analysis/brand_price_trend/",
    "/api/shield/analysis/brand_performance_trend/",
]
NEW_API = "/api/shield/analysis/brand_comparison/"
GET = 0


def grant_brand_comparison(apps, schema_editor):
    MenuButton = apps.get_model("system", "MenuButton")
    Permission = apps.get_model("system", "RoleMenuButtonPermission")
    # 同一角色在几个旧接口上的授权不一样时，取对照表接口 brand_cost 的（最后写入）
    grants = {}
    for api in reversed(OLD_APIS):
        for grant in Permission.objects.filter(menu_button__api__iexact=api, menu_button__method=GET).select_related("menu_button"):
            grants[grant.role_id] = grant
    for role_id, grant in grants.items():
        menu_id = grant.menu_button.menu_id
        button = MenuButton.objects.filter(menu_id=menu_id, api__iexact=NEW_API, method=GET).first()
        if button is None:
            value = "ShieldAnalysisBrandComparison"
            if MenuButton.objects.filter(value=value).exists():
                value = f"{value}{menu_id}"
            button = MenuButton.objects.create(menu_id=menu_id, name="厂家对比", value=value, api=NEW_API, method=GET)
        if Permission.objects.filter(role_id=role_id, menu_button=button).exists():
            continue
        copy = Permission.objects.create(role_id=role_id, menu_button=button, data_range=grant.data_range)
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
