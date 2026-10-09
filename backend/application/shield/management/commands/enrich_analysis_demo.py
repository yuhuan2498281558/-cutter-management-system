"""Enrich explicitly marked tool-change fixtures without rebuilding business data."""
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.db.models.fields.files import FieldFile

from application.shield.analysis_metrics import confirmed_service_segments
from application.shield.cutter_position_scope import sort_cutter_position_items
from application.shield.demo_profiles import installation_price, profile_for, repair_price, wear_values
from application.shield.models import (
    CutterPositionInfo, NewToolRecord, OldToolRecord, ToolChangeDetail,
    ToolInstance, WarehouseOpeningBasicInfo,
)
from .seed_tool_change_demo import Command as SeedCommand, OPENINGS, WEAR_CONDITIONS


VERSION = "analysis-demo-v1"
NEW_MARKER = f"{VERSION}：模拟新刀数据"
OLD_MARKER = f"{VERSION}：模拟旧刀数据"
REPLACED_MARKER = f"{VERSION}：模拟换刀数据"
CHECKED_MARKER = f"{VERSION}：模拟检查数据"
MODELS = {model._meta.label: model for model in (ToolChangeDetail, NewToolRecord, OldToolRecord)}
DETAIL_FIELDS = {"manufacturer", "brand", "price", "wear_condition", "blade_wear_amount", "remark", "repair_parts", "check_result"}
NEW_FIELDS = {"ring_manufacturer", "shaft_manufacturer", "hub_manufacturer", "scraper_manufacturer", "remark"}
OLD_FIELDS = {
    "wear_condition", "ring_wear_amount", "bias_wear_amount", "ring_damage", "ring_tooth_loss_count",
    "ring_other_condition", "bearing_failed", "bearing_failure_reasons", "bearing_other_condition",
    "hub_damaged", "hub_failure_reasons", "hub_other_condition", "scraper_wear_amount",
    "scraper_chipped", "scraper_broken", "scraper_detached", "repair_parts", "repair_result", "repair_price", "remark",
}
ALLOWED = {ToolChangeDetail: DETAIL_FIELDS, NewToolRecord: NEW_FIELDS, OldToolRecord: OLD_FIELDS}


def encoded(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False))


def fingerprint(row):
    values = {field.attname: getattr(row, field.attname) for field in row._meta.concrete_fields}
    values = {key: value.name if isinstance(value, FieldFile) else value for key, value in values.items()}
    return hashlib.sha256(json.dumps(encoded(values), sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def change(row, values, enriched=False):
    if not set(values) <= ALLOWED[type(row)]:
        raise CommandError("Attempt to update a field outside the demo whitelist.")
    before = {name: getattr(row, name) for name in values}
    if enriched and encoded(before) != encoded(values):
        raise CommandError(f"Previously enriched {row._meta.label} #{row.pk} was edited; preserving it. Restore or review manually.")
    before_hash = fingerprint(row)
    for name, value in values.items():
        setattr(row, name, value)
    return {"model": row._meta.label, "id": row.pk, "before": encoded(before), "after": encoded(values),
            "before_hash": before_hash, "after_hash": fingerprint(row)}


def removal_values(profile, parent, key, ring, removed):
    """Match generated observations to the original, unchanged disposal decision."""
    selected = dict(profile)
    if removed.disposition == "SCRAP":
        selected["normal_probability"] = 0
    for attempt in range(100):
        sample_key = key if attempt == 0 else f"{key}:disposition:{attempt}"
        wear = wear_values(selected, parent, sample_key, ring)
        broken = wear["wear_condition"] in {"断裂", "脱落", "刀圈脱落", "严重磨损"}
        if removed.disposition == "SCRAP" and not broken:
            continue
        if removed.disposition == "REPAIRABLE" and wear["wear_condition"] in {"断裂", "脱落"}:
            continue
        amount = repair_price(selected, parent, sample_key, ring)
        if removed.disposition == "SCRAP":
            wear.update(repair_parts=[], repair_result="模拟：损伤达到退役条件，按原记录报废处置")
            amount = Decimal("0.00")
        elif removed.inspection_status == "PENDING_VENDOR_FEEDBACK":
            wear["repair_result"] = "模拟：待厂家反馈，维修项目与费用为预估"
        return wear, amount
    raise CommandError("Could not generate a wear sample consistent with the original disposition.")


def build_plan(project_id, shield_id):
    """All target evidence and identity checks happen before returning any writes."""
    openings = list(WarehouseOpeningBasicInfo.objects.select_for_update().filter(
        project_id=project_id, shield_model_id=shield_id).order_by("pk"))
    expected_openings = {(str(ring), day) for ring, day in OPENINGS}
    openings = [row for row in openings if (row.ring_no, row.open_time.date()) in expected_openings]
    if not openings:
        raise CommandError("No matching demo opening dates/rings in the explicit project and machine.")
    positions = sort_cutter_position_items(list(CutterPositionInfo.objects.filter(
        shield_machine_id=shield_id).select_related("tool_info")), key=lambda row: row.cutter_position_no)
    details = list(ToolChangeDetail.objects.select_for_update().filter(warehouse__in=openings).order_by("pk"))
    by_opening = {row.pk: row for row in openings}
    for detail in details:
        detail.warehouse = by_opening[detail.warehouse_id]
    detail_map = {(row.warehouse_id, row.cutter_position_no): row for row in details}
    new = {row.tool_change_detail_id: row for row in NewToolRecord.objects.select_for_update().filter(
        tool_change_detail__in=details).order_by("pk")}
    old = {row.tool_change_detail_id: row for row in OldToolRecord.objects.select_for_update().filter(
        tool_change_detail__in=details).order_by("pk")}
    instances = {row.pk: row for row in ToolInstance.objects.select_for_update().filter(
        pk__in=[row.tool_instance_id for row in new.values()]).order_by("pk")}
    replacements, checked = [], []
    seed = SeedCommand()
    for opening in sorted(openings, key=lambda row: int(row.ring_no)):
        index = next(i for i, pair in enumerate(OPENINGS) if str(pair[0]) == opening.ring_no)
        replaced_positions, checked_positions = seed._inspection_plan(positions, index)
        for slot, position in enumerate(replaced_positions + checked_positions):
            detail = detail_map.get((opening.pk, position.cutter_position_no))
            if detail is None:
                continue
            record, removed = new.get(detail.pk), old.get(detail.pk)
            is_replacement = slot < len(replaced_positions)
            if is_replacement:
                # An unmarked row is unrelated business data, never a fallback fixture.
                if not record or record.remark not in {"结构化新刀字段测试记录", NEW_MARKER}:
                    continue
                instance = instances[record.tool_instance_id]
                serial = index * 100 + slot + 1
                expected_uid = f"DEMO-{opening.ring_no}-{position.cutter_position_no}-{serial:03d}"
                if (not removed or removed.remark not in {"旧刀厂家返修结构化字段测试记录", OLD_MARKER}
                    or detail.remark not in {"已完成现场检查并更换", REPLACED_MARKER}
                    or instance.tool_uid != expected_uid or detail.tool_number != instance.display_tool_no
                    or record.installed_at != opening.open_time or not detail.is_replaced
                    or detail.tool_parent_type != position.tool_type or instance.tool_info_id != position.tool_info_id):
                    raise CommandError(f"Demo identity/marker mismatch at detail #{detail.pk}; no changes applied.")
                expected_wear = WEAR_CONDITIONS[(index + slot + 4) % len(WEAR_CONDITIONS)]
                if record.remark != NEW_MARKER and (detail.wear_condition != expected_wear or removed.wear_condition != expected_wear):
                    raise CommandError(f"Original demo wear was edited at detail #{detail.pk}; preserving it.")
                replacements.append((detail, record, removed, instance))
            else:
                if detail.remark not in {"已检查，本次无需更换", CHECKED_MARKER}:
                    continue
                if record or removed or detail.is_replaced or detail.tool_parent_type != position.tool_type:
                    raise CommandError(f"Checked-only demo evidence mismatch at detail #{detail.pk}.")
                expected_wear = WEAR_CONDITIONS[(index + slot) % len(WEAR_CONDITIONS)]
                if detail.remark != CHECKED_MARKER and detail.wear_condition != expected_wear:
                    raise CommandError(f"Original checked-only wear was edited at detail #{detail.pk}; preserving it.")
                checked.append(detail)
            if not detail.is_checked or detail.checked_at != opening.open_time or detail.mobile_status != "SAVED":
                raise CommandError(f"Original inspection evidence mismatch at detail #{detail.pk}.")
    if not replacements:
        raise CommandError("No explicitly marked demo installations matched the seed identity plan.")
    target_ids = {row[0].pk for row in replacements}
    instance_ids = {row[3].pk for row in replacements}
    if (NewToolRecord.objects.filter(tool_instance_id__in=instance_ids).exclude(tool_change_detail_id__in=target_ids).exists()
        or OldToolRecord.objects.filter(Q(confirmed_tool_instance_id__in=instance_ids) | Q(suggested_tool_instance_id__in=instance_ids))
        .exclude(tool_change_detail_id__in=target_ids).exists()):
        raise CommandError("A demo instance is referenced outside the target set; preserving the entire dataset.")
    if len(instance_ids) != len(replacements):
        raise CommandError("Demo installation identity is not unique.")
    installed_by_instance = {row[3].pk: row[0] for row in replacements}
    for detail, record, removed, instance in replacements:
        for instance_id in (removed.confirmed_tool_instance_id, removed.suggested_tool_instance_id):
            if instance_id is None:
                continue
            installed = installed_by_instance.get(instance_id)
            if (installed is None or installed.cutter_position_no != detail.cutter_position_no
                or int(installed.warehouse.ring_no) >= int(detail.warehouse.ring_no)
                or installed.warehouse.open_time >= detail.warehouse.open_time):
                raise CommandError(f"Old-tool identity crosses demo scope at detail #{detail.pk}.")
    spans = {row["installation_detail_id"]: row["service_rings"] for row in confirmed_service_segments(
        [item[0] for item in replacements]) if row["paired"]}
    profiles = {instance.pk: profile_for(instance.tool_uid, spans.get(detail.pk))
                for detail, record, removed, instance in replacements}
    plan = []
    for detail, record, removed, instance in replacements:
        profile = profiles[instance.pk]
        previous = profiles.get(removed.confirmed_tool_instance_id) or profile_for(f"baseline:{detail.cutter_position_no}")
        key, ring, parent = instance.tool_uid, int(detail.warehouse.ring_no), detail.tool_parent_type
        wear, repair_amount = removal_values(previous, parent, key, ring, removed)
        detail_values = {"manufacturer": profile["name"], "brand": profile["brand"],
                         "price": installation_price(profile, parent, key, ring),
                         "wear_condition": wear["wear_condition"], "blade_wear_amount": wear["blade_wear_amount"],
                         "repair_parts": wear["repair_parts"], "remark": REPLACED_MARKER}
        new_values = {name: profile["name"] if (parent == "SCRAPER") == (name == "scraper_manufacturer") else None
                      for name in NEW_FIELDS - {"remark"}}
        new_values["remark"] = NEW_MARKER
        old_values = {name: value for name, value in wear.items() if name in OLD_FIELDS}
        old_values.update(repair_price=repair_amount, remark=OLD_MARKER)
        for row, values, marker in ((detail, detail_values, REPLACED_MARKER), (record, new_values, NEW_MARKER),
                                    (removed, old_values, OLD_MARKER)):
            plan.append(change(row, values, row.remark == marker))
    installs_by_position = {}
    for detail, record, removed, instance in replacements:
        installs_by_position.setdefault(detail.cutter_position_no, []).append((int(detail.warehouse.ring_no), profiles[instance.pk]))
    for detail in checked:
        ring = int(detail.warehouse.ring_no)
        prior = [(at_ring, profile) for at_ring, profile in installs_by_position.get(detail.cutter_position_no, []) if at_ring < ring]
        profile = max(prior, key=lambda item: item[0])[1] if prior else profile_for(f"baseline:{detail.cutter_position_no}")
        key = f"check:{ring}:{detail.cutter_position_no}"
        wear = wear_values(profile, detail.tool_parent_type, key, ring, checked_only=True)
        values = {"wear_condition": wear["wear_condition"], "blade_wear_amount": wear["blade_wear_amount"],
                  "check_result": "NOT_REPLACED" if wear["wear_condition"] == "正常" else "ATTENTION", "remark": CHECKED_MARKER}
        plan.append(change(detail, values, detail.remark == CHECKED_MARKER))
    changes = [item for item in plan if item["before"] != item["after"]]
    return changes, {"version": VERSION, "opening_count": len(openings), "replacement_count": len(replacements),
                     "checked_only_count": len(checked), "changed_rows": len(changes),
                     "plan_digest": hashlib.sha256(json.dumps(changes, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
                     "manufacturers": dict(Counter(profile["name"] for profile in profiles.values()))}


def apply_rows(rows, restore=False, scope=None, write=True):
    seen = set()
    for item in rows:
        model = MODELS.get(item["model"])
        if model is None or not set(item["before"]) == set(item["after"]) or not set(item["after"]) <= ALLOWED[model]:
            raise CommandError("Invalid backup model or field whitelist.")
        identity = (item["model"], item["id"])
        if identity in seen:
            raise CommandError("Duplicate row in the backup.")
        seen.add(identity)
        row = model.objects.select_for_update().get(pk=item["id"])
        detail = row if model is ToolChangeDetail else row.tool_change_detail
        if scope and (detail.warehouse.project_id, detail.warehouse.shield_model_id) != scope:
            raise CommandError("Backup row belongs to another project or machine.")
        expected_hash = item["after_hash"] if restore else item["before_hash"]
        if fingerprint(row) != expected_hash:
            raise CommandError(f"{item['model']} #{item['id']} changed since the snapshot; transaction cancelled.")
        if not write:
            continue
        values = item["before"] if restore else item["after"]
        model.objects.filter(pk=row.pk).update(**values)
        row.refresh_from_db()
        if fingerprint(row) != (item["before_hash"] if restore else item["after_hash"]):
            raise CommandError("Stored result differs from the planned snapshot; transaction cancelled.")


class Command(BaseCommand):
    help = "Preview or enrich explicitly marked analysis demo rows, retaining all identities and workflow states."

    def add_arguments(self, parser):
        parser.add_argument("--project-pk", type=int, required=True)
        parser.add_argument("--shield-pk", type=int, required=True)
        parser.add_argument("--apply", action="store_true", help="Apply the reviewed deterministic plan; default is dry-run.")
        parser.add_argument("--backup", help="New local JSON path, required when applying changes; existing files are never overwritten.")
        parser.add_argument("--expected-digest", help="Exact plan_digest from the reviewed dry-run, required for the first write.")
        parser.add_argument("--restore", help="Restore a backup only when every target row still matches its post-enrichment fingerprint.")

    def handle(self, *args, **options):
        with transaction.atomic():
            if options.get("restore"):
                backup = json.loads(Path(options["restore"]).resolve(strict=True).read_text(encoding="utf-8"))
                if (backup.get("version") != VERSION or backup.get("project_pk") != options["project_pk"]
                    or backup.get("shield_pk") != options["shield_pk"]):
                    raise CommandError("Backup version or requested project/machine does not match.")
                apply_rows(backup["rows"], restore=True, scope=(options["project_pk"], options["shield_pk"]), write=options["apply"])
                report = {"restore_rows": len(backup["rows"]), "applied": options["apply"]}
            else:
                rows, report = build_plan(options["project_pk"], options["shield_pk"])
                report["applied"] = options["apply"]
                if options["apply"] and rows:
                    if options.get("expected_digest") != report["plan_digest"]:
                        raise CommandError("--expected-digest must match the reviewed dry-run plan; no writes occurred.")
                    if not options.get("backup"):
                        raise CommandError("--backup is required before any database writes.")
                    backup_path = Path(options["backup"]).resolve()
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    backup = {"version": VERSION, "project_pk": options["project_pk"], "shield_pk": options["shield_pk"], "rows": rows}
                    # Exclusive creation prevents replacing the original rollback snapshot on a later run.
                    with backup_path.open("x", encoding="utf-8") as stream:
                        json.dump(backup, stream, ensure_ascii=False, indent=2)
                    apply_rows(rows, scope=(options["project_pk"], options["shield_pk"]))
                    report["backup"] = str(backup_path)
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
