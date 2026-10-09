from django.db import migrations
from django.db.models import Q


def remove_dictionary_navigation(apps, schema_editor):
    """Remove only the retired modules; stop before cascading into custom items."""
    alias = schema_editor.connection.alias
    Menu = apps.get_model("system", "Menu")
    MenuButton = apps.get_model("system", "MenuButton")
    MenuField = apps.get_model("system", "MenuField")
    ContentType = apps.get_model("contenttypes", "ContentType")
    menu_filter = Q(
        web_path__in=("wearTypeDict", "/shield/wearTypeDict"),
        component="shield/wearTypeDict/index",
    ) | Q(
        web_path__in=("abnormalCauseDict", "/shield/abnormalCauseDict"),
        component="shield/abnormalCauseDict/index",
    )
    menu_ids = list(Menu.objects.using(alias).filter(menu_filter).values_list("pk", flat=True))
    api_prefixes = (
        "/api/shield/wear_type_dict/",
        "/api/shield/abnormal_cause_dict/",
    )
    retired_models = (
        "WearTypeDict", "AbnormalCauseDict", "shield_wear_type_dict", "shield_abnormal_cause_dict"
    )
    button_ids = [
        pk for pk, api in MenuButton.objects.using(alias).values_list("pk", "api")
        if (api or "").removeprefix("^").startswith(api_prefixes)
    ]
    has_custom_children = Menu.objects.using(alias).filter(parent_id__in=menu_ids).exclude(pk__in=menu_ids).exists()
    has_custom_buttons = MenuButton.objects.using(alias).filter(menu_id__in=menu_ids).exclude(pk__in=button_ids).exists()
    has_custom_fields = MenuField.objects.using(alias).filter(menu_id__in=menu_ids).exclude(
        model__in=retired_models
    ).exists()
    if has_custom_children or has_custom_buttons or has_custom_fields:
        raise RuntimeError(
            "Retired dictionary menus contain custom child menus, buttons or fields. "
            "Move those custom items to an active menu before applying shield 0040."
        )

    # Includes retired guest permissions attached to the active tool-info menu.
    MenuButton.objects.using(alias).filter(pk__in=button_ids).delete()
    MenuField.objects.using(alias).filter(model__in=retired_models).delete()
    Menu.objects.using(alias).filter(pk__in=menu_ids).delete()
    ContentType.objects.using(alias).filter(
        app_label="shield", model__in=("weartypedict", "abnormalcausedict")
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("shield", "0039_warehouseopeningbasicinfo_summary_confirmed_at_and_more"),
        ("system", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    # Dictionary records and navigation permissions cannot be recreated by reversal.
    operations = [
        migrations.RunPython(remove_dictionary_navigation),
        migrations.DeleteModel(name="WearTypeDict"),
        migrations.DeleteModel(name="AbnormalCauseDict"),
    ]
