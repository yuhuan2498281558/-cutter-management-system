from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from PIL import Image, ImageDraw

from application.shield.cutter_position_scope import sort_cutter_position_items
from application.shield.models import (
    CutterPositionInfo,
    MobileToolChangeTask,
    NewToolRecord,
    OldToolPhoto,
    OldToolRecord,
    ProjectInfo,
    ShieldMachineBasicInfo,
    ToolCost,
    ToolChangeDetail,
    ToolInstance,
    WarehouseOpeningBasicInfo,
)


OPENINGS = [
    (15, date(2024, 6, 13)),
    (45, date(2024, 6, 26)),
    (67, date(2024, 7, 6)),
    (106, date(2024, 7, 24)),
    (151, date(2024, 8, 13)),
    (192, date(2024, 8, 27)),
    (218, date(2024, 9, 7)),
    (258, date(2024, 9, 24)),
    (281, date(2024, 10, 10)),
    (317, date(2024, 10, 27)),
    (339, date(2024, 11, 14)),
    (369, date(2024, 11, 24)),
    (400, date(2024, 12, 13)),
    (443, date(2025, 1, 1)),
    (487, date(2025, 1, 19)),
]

TRACKS = ["中心刀轨", "正面刀轨", "外周刀轨"]
STRATUM_CODES = ["CLAY_SAND", "SOFT_HARD", "WEAK_GRANITE", "BEDROCK_PROTRUSION"]
RING_DAMAGE = ["FRACTURE", "CHIP", "BOLT_LOSS", "C_BLOCK_LOSS"]
BEARING_REASONS = ["SEAL_FAILURE", "LOAD_DEFORMATION", "FATIGUE_DAMAGE"]
HUB_REASONS = ["WEAR", "CRACK", "CHIP", "FRACTURE"]
INSPECTION_STATUSES = ["PENDING_VENDOR_FEEDBACK", "CONFIRMED", "CLOSED"]
WEAR_CONDITIONS = ["正常", "轻微磨损", "中度磨损", "严重磨损", "偏磨", "崩口", "断裂", "脱落"]

# 每次保留约 10% 刀位未交互，其他刀位进入检查结果；换刀记录约占已检查刀位的一半。
UNINSPECTED_RATIO = 0.10
MIN_REPLACEMENTS_FOR_LIFESPAN = 2


class Command(BaseCommand):
    help = "Rebuild deterministic warehouse-opening demo data for the tool-change workflow."

    def add_arguments(self, parser):
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Delete all existing warehouse-opening test data before rebuilding it.",
        )
        parser.add_argument("--project-id", help="ProjectInfo.project_id; defaults to the first project.")
        parser.add_argument(
            "--shield-id",
            help="ShieldMachineBasicInfo.shield_model_id; defaults to the first shield machine.",
        )

    def handle(self, *args, **options):
        project = self._project(options.get("project_id"))
        shield = self._shield(options.get("shield_id"))
        positions = list(
            CutterPositionInfo.objects.filter(shield_machine=shield).select_related("tool_info")
        )
        if not positions:
            raise CommandError("The selected shield machine has no cutter positions.")
        if any(not item.cutter_position_no or not item.tool_info_id for item in positions):
            raise CommandError("Every cutter position must have a position number and tool type.")

        all_positions = sort_cutter_position_items(positions, key=lambda item: item.cutter_position_no)
        if not any(item.tool_type == "DISC" for item in all_positions) or not any(
            item.tool_type == "SCRAPER" for item in all_positions
        ):
            raise CommandError("Both disc and scraper positions are required for the demo plan.")

        costs_by_tool = self._costs_by_tool()
        if not costs_by_tool:
            self.stdout.write(self.style.WARNING("No tool-cost records found; fallback supplier samples will be used."))

        existing = WarehouseOpeningBasicInfo.objects.count()
        if existing and not options["replace"]:
            raise CommandError(
                f"Found {existing} warehouse openings. Re-run with --replace to rebuild test data."
            )

        with transaction.atomic():
            if options["replace"]:
                deleted = self._delete_existing_openings()
                self.stdout.write(f"Deleted {deleted} database rows from the opening test-data chain.")

            state = {}
            checked_total = 0
            replaced_total = 0
            for index, (ring_no, opening_date) in enumerate(OPENINGS):
                opening = self._create_opening(project, shield, index, ring_no, opening_date)
                task = MobileToolChangeTask.objects.get(warehouse=opening)
                details = {
                    item.cutter_position_no: item
                    for item in ToolChangeDetail.objects.filter(warehouse=opening).select_related(
                        "cutter_position", "cutter_position__tool_info"
                    )
                }
                if len(details) != len(positions):
                    raise CommandError(
                        f"Ring {ring_no} generated {len(details)} details; expected {len(positions)}."
                    )

                if index == 0:
                    self._seed_baseline_numbers(details.values())

                replaced, checked_only = self._inspection_plan(
                    all_positions,
                    index,
                )
                for slot, position in enumerate(replaced):
                    self._seed_replacement(
                        details[position.cutter_position_no],
                        task,
                        state,
                        costs_by_tool,
                        index,
                        slot,
                    )
                for slot, position in enumerate(checked_only):
                    self._seed_checked_only(
                        details[position.cutter_position_no],
                        task,
                        index,
                        len(replaced) + slot,
                    )

                checked_total += len(replaced) + len(checked_only)
                replaced_total += len(replaced)

                opening.checked_tool_count = len(replaced) + len(checked_only)
                opening.replaced_tool_count = len(replaced)
                opening.save(update_fields=["checked_tool_count", "replaced_tool_count"])

            # Keep validation in the same transaction so a failed rebuild leaves no partial demo data.
            summary = self._validate(len(positions), checked_total, replaced_total)
        self.stdout.write(self.style.SUCCESS("Tool-change demo data rebuilt successfully."))
        for key, value in summary.items():
            self.stdout.write(f"  {key}: {value}")

    @staticmethod
    def _project(project_id):
        queryset = ProjectInfo.objects.order_by("id")
        project = queryset.filter(project_id=project_id).first() if project_id else queryset.first()
        if not project:
            raise CommandError("No project master data is available.")
        return project

    @staticmethod
    def _shield(shield_id):
        queryset = ShieldMachineBasicInfo.objects.order_by("id")
        shield = queryset.filter(shield_model_id=shield_id).first() if shield_id else queryset.first()
        if not shield:
            raise CommandError("No shield-machine master data is available.")
        return shield

    @staticmethod
    def _costs_by_tool():
        costs_by_tool = {}
        for cost in ToolCost.objects.order_by(
            "tool_info_id", "cost_type", "manufacturer", "brand", "unit_price", "id"
        ):
            costs_by_tool.setdefault((cost.tool_info_id, cost.cost_type), []).append(cost)
        return costs_by_tool

    @staticmethod
    def _window(items, start, count):
        if not items or count <= 0:
            return []
        return [items[(start + offset) % len(items)] for offset in range(count)]

    def _inspection_plan(self, positions, opening_index):
        """Return a dense but partially uninspected plan for one opening."""
        uninspected_count = max(1, int(round(len(positions) * UNINSPECTED_RATIO)))
        pending = {
            item.cutter_position_no
            for item in self._window(positions, opening_index * 11, uninspected_count)
        }
        checked = [item for item in positions if item.cutter_position_no not in pending]
        replaced = [
            item
            for index, item in enumerate(checked)
            if (index + opening_index) % 2 == 0
        ]
        checked_only = [item for item in checked if item not in replaced]
        return replaced, checked_only

    @staticmethod
    def _delete_existing_openings():
        for photo in OldToolPhoto.objects.filter(
            old_tool_record__tool_change_detail__warehouse__isnull=False
        ):
            if photo.image:
                photo.image.delete(save=False)
        for detail in ToolChangeDetail.objects.exclude(wear_image=""):
            if detail.wear_image:
                detail.wear_image.delete(save=False)
        _, deleted_by_model = WarehouseOpeningBasicInfo.objects.all().delete()
        ToolInstance.objects.filter(tool_uid__startswith="DEMO-").delete()
        return sum(deleted_by_model.values())

    @staticmethod
    def _create_opening(project, shield, index, ring_no, opening_date):
        opened_at = timezone.make_aware(datetime.combine(opening_date, time(hour=8, minute=30)))
        previous_ring = OPENINGS[index - 1][0] if index else 0
        ring_gap = ring_no - previous_ring
        return WarehouseOpeningBasicInfo.objects.create(
            project=project,
            shield_model=shield,
            ring_no=str(ring_no),
            open_time=opened_at,
            section="F2-F3区间",
            opening_duration=round(6.5 + (index % 4) * 0.75, 2),
            blade_track=TRACKS[index % len(TRACKS)],
            tool_change_date=opening_date,
            tool_change_duration=round(3.5 + (index % 5) * 0.6, 2),
            usage_distance=round(ring_gap * 2.0, 2),
            stratum_info_between={
                STRATUM_CODES[index % len(STRATUM_CODES)]: max(ring_gap - 3, 1),
                STRATUM_CODES[(index + 1) % len(STRATUM_CODES)]: min(ring_gap, 3),
            },
            geological_conditions=(
                "掌子面整体稳定，局部含砂量增加，现场加强刀具磨损检查。"
                if index % 2 == 0
                else "上软下硬交界明显，滚刀冲击载荷较高。"
            ),
        )

    @staticmethod
    def _seed_baseline_numbers(details):
        for detail in details:
            prefix = "GD" if detail.tool_parent_type == "DISC" else "GGD"
            detail.tool_number = f"BASE-{prefix}-{detail.cutter_position_no}"
            detail.save(update_fields=["tool_number", "update_datetime"])

    def _seed_replacement(self, detail, task, state, costs_by_tool, opening_index, slot):
        position_no = detail.cutter_position_no
        is_disc = detail.tool_parent_type == "DISC"
        previous_instance = state.get(position_no)
        old_number = (
            previous_instance.display_tool_no
            if previous_instance
            else detail.tool_number or f"BASE-{position_no}"
        )
        serial = opening_index * 100 + slot + 1
        type_prefix = "GD" if is_disc else "GGD"
        tool_uid = f"DEMO-{detail.warehouse.ring_no}-{position_no}-{serial:03d}"
        display_no = f"{type_prefix}-TEST-{serial:04d}"
        instance = ToolInstance.objects.create(
            tool_uid=tool_uid,
            display_tool_no=display_no,
            tool_info=detail.cutter_position.tool_info,
            tool_parent_type=detail.tool_parent_type,
            tool_type_name=detail.cutter_position.tool_info.tool_type_name,
            status="INSTALLED",
        )

        replacement_type = "REPAIR" if (opening_index + slot) % 3 == 0 else "COMPLETE"
        new_cost_options = costs_by_tool.get((detail.cutter_position.tool_info_id, "NEW_TOOL"), [])
        repair_cost_options = costs_by_tool.get((detail.cutter_position.tool_info_id, "REPAIR"), [])
        cost_options = repair_cost_options if replacement_type == "REPAIR" and repair_cost_options else new_cost_options
        cost = cost_options[(opening_index + slot) % len(cost_options)] if cost_options else None
        fallback_manufacturer = "福普宁刀具制造" if is_disc else "福普宁刮刀制造"
        fallback_brand = "福普宁" if is_disc else "福普宁"
        manufacturer = cost.manufacturer if cost else fallback_manufacturer
        brand = cost.brand if cost else fallback_brand
        new_cost = new_cost_options[(opening_index + slot) % len(new_cost_options)] if new_cost_options else None
        new_manufacturer = new_cost.manufacturer if new_cost else manufacturer
        new_brand = new_cost.brand if new_cost else brand
        new_price = new_cost.unit_price if new_cost and new_cost.unit_price is not None else price
        price = cost.unit_price if cost and cost.unit_price is not None else (
            Decimal("6200.00") if is_disc else Decimal("3200.00")
        )
        repair_price = (
            cost.unit_price
            if replacement_type == "REPAIR" and cost and cost.unit_price is not None
            else (new_price * Decimal("0.32")).quantize(Decimal("0.01"))
        )
        component_condition = "NEW" if (opening_index + slot) % 2 == 0 else "REPAIRED"
        new_record = NewToolRecord.objects.create(
            tool_change_detail=detail,
            tool_instance=instance,
            installed_at=detail.warehouse.open_time,
            ring_type=("SMOOTH" if (opening_index + slot) % 2 == 0 else "INSERTED") if is_disc else None,
            ring_manufacturer=new_manufacturer if is_disc else None,
            shaft_condition=component_condition if is_disc else None,
            shaft_manufacturer=new_manufacturer if is_disc else None,
            hub_condition=("REPAIRED" if component_condition == "NEW" else "NEW") if is_disc else None,
            hub_manufacturer=new_manufacturer if is_disc else None,
            scraper_manufacturer=new_manufacturer if not is_disc else None,
            remark="结构化新刀字段测试记录",
        )

        inspection_status = INSPECTION_STATUSES[(opening_index + slot) % len(INSPECTION_STATUSES)]
        bearing_failed = is_disc and (opening_index + slot) % 3 != 0
        hub_damaged = is_disc and (opening_index + slot) % 2 == 0
        damage_index = (opening_index * 2 + slot) % len(RING_DAMAGE)
        disposition = "REPAIRABLE" if (opening_index + slot) % 3 else "SCRAP"
        old_record = OldToolRecord.objects.create(
            tool_change_detail=detail,
            suggested_tool_instance=previous_instance,
            confirmed_tool_instance=previous_instance,
            old_tool_number=old_number,
            wear_condition=WEAR_CONDITIONS[(opening_index + slot + 4) % len(WEAR_CONDITIONS)],
            repair_parts=["刀圈", "轴承"] if is_disc else ["刮刀刀体"],
            repair_result=("更换轴承并修复刀毂" if is_disc else "堆焊修复刮刀刃口"),
            repair_price=repair_price,
            ring_wear_amount=round(2.1 + opening_index * 0.08 + slot * 0.15, 2) if is_disc else None,
            bias_wear_amount=round(0.3 + (opening_index % 4) * 0.12, 2) if is_disc else None,
            tool_track=TRACKS[(opening_index + slot) % len(TRACKS)],
            ring_damage=[RING_DAMAGE[damage_index], RING_DAMAGE[(damage_index + 1) % len(RING_DAMAGE)]] if is_disc else [],
            ring_tooth_loss_count=((opening_index + slot) % 5) + 1 if is_disc else None,
            ring_other_condition="刀圈表面存在连续擦痕" if is_disc else None,
            bearing_failed=bearing_failed if is_disc else None,
            bearing_failure_reasons=(
                [
                    BEARING_REASONS[(opening_index + slot) % len(BEARING_REASONS)],
                    BEARING_REASONS[(opening_index + slot + 1) % len(BEARING_REASONS)],
                ]
                if bearing_failed else []
            ),
            bearing_other_condition="转动阻力偏大" if bearing_failed else None,
            hub_damaged=hub_damaged if is_disc else None,
            hub_failure_reasons=(
                [
                    HUB_REASONS[(opening_index + slot) % len(HUB_REASONS)],
                    HUB_REASONS[(opening_index + slot + 1) % len(HUB_REASONS)],
                ]
                if hub_damaged else []
            ),
            hub_other_condition="刀毂端面有轻微压痕" if hub_damaged else None,
            disposition=disposition,
            scraper_wear_amount=round(3.2 + opening_index * 0.1, 2) if not is_disc else None,
            scraper_chipped=(opening_index % 2 == 0) if not is_disc else None,
            scraper_broken=(opening_index % 3 == 0) if not is_disc else None,
            scraper_detached=(opening_index % 5 == 0) if not is_disc else None,
            inspection_status=inspection_status,
            vendor_feedback_at=(timezone.now() if inspection_status != "PENDING_VENDOR_FEEDBACK" else None),
            remark="旧刀厂家返修结构化字段测试记录",
        )
        if previous_instance:
            if inspection_status == "PENDING_VENDOR_FEEDBACK":
                previous_instance.status = "REMOVED_PENDING_INSPECTION"
            elif inspection_status == "CONFIRMED":
                previous_instance.status = "INSPECTED"
            else:
                previous_instance.status = "REPAIRED_CLOSED" if disposition == "REPAIRABLE" else "SCRAPPED"
            previous_instance.save(update_fields=["status", "update_datetime"])
        self._create_photo(old_record, detail, opening_index, slot)

        detail.mobile_task = task
        detail.tool_number = new_record.tool_instance.display_tool_no
        detail.wear_condition = WEAR_CONDITIONS[(opening_index + slot + 4) % len(WEAR_CONDITIONS)]
        detail.blade_wear_amount = old_record.ring_wear_amount if is_disc else old_record.scraper_wear_amount
        detail.is_replaced = True
        detail.manufacturer = manufacturer
        detail.replacement_type = replacement_type
        detail.repair_parts = old_record.repair_parts
        detail.brand = brand
        detail.price = repair_price if replacement_type == "REPAIR" else new_price
        detail.remark = "已完成现场检查并更换"
        detail.is_checked = True
        detail.check_result = "NORMAL"
        detail.mobile_status = "SAVED"
        detail.checked_at = detail.warehouse.open_time
        detail.save()
        state[position_no] = instance

    @staticmethod
    def _seed_checked_only(detail, task, opening_index, slot):
        results = ["NOT_REPLACED", "ATTENTION", "ABNORMAL_NOT_REPLACED"]
        detail.mobile_task = task
        detail.wear_condition = WEAR_CONDITIONS[(opening_index + slot) % len(WEAR_CONDITIONS)]
        detail.blade_wear_amount = round(0.4 + opening_index * 0.03 + slot * 0.2, 2)
        detail.is_replaced = False
        detail.remark = "已检查，本次无需更换"
        detail.is_checked = True
        detail.check_result = (
            "NOT_REPLACED"
            if detail.wear_condition == "正常"
            else results[(opening_index + slot) % len(results)]
        )
        detail.mobile_status = "SAVED"
        detail.checked_at = detail.warehouse.open_time
        detail.save()

    @staticmethod
    def _create_photo(old_record, detail, opening_index, slot):
        colors = [(34, 77, 112), (54, 103, 84), (126, 74, 48)]
        image = Image.new("RGB", (960, 640), color=colors[slot % len(colors)])
        draw = ImageDraw.Draw(image)
        lines = [
            "TOOL WEAR TEST PHOTO",
            f"Ring: {detail.warehouse.ring_no}",
            f"Position: {detail.cutter_position_no}",
            f"Type: {detail.tool_parent_type}",
        ]
        y = 210
        for line in lines:
            draw.text((280, y), line, fill=(255, 255, 255))
            y += 48
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        content = buffer.getvalue()
        filename = f"demo_ring_{detail.warehouse.ring_no}_{detail.cutter_position_no}_{opening_index}_{slot}.png"
        photo = OldToolPhoto(
            old_tool_record=old_record,
            original_filename=filename,
            file_size=len(content),
            mime_type="image/png",
            remark="点击链接查看的测试磨损照片",
        )
        photo.image.save(filename, ContentFile(content), save=False)
        photo.save()

    @staticmethod
    def _validate(position_count, checked_total, replaced_total):
        expected_details = len(OPENINGS) * position_count
        counts = {
            "openings": WarehouseOpeningBasicInfo.objects.count(),
            "details": ToolChangeDetail.objects.count(),
            "tasks": MobileToolChangeTask.objects.count(),
            "checked_details": ToolChangeDetail.objects.filter(is_checked=True).count(),
            "replaced_details": ToolChangeDetail.objects.filter(is_replaced=True).count(),
            "checked_only_details": ToolChangeDetail.objects.filter(
                is_checked=True, is_replaced=False
            ).count(),
            "pending_details": ToolChangeDetail.objects.filter(is_checked=False).count(),
            "new_tool_records": NewToolRecord.objects.count(),
            "old_tool_records": OldToolRecord.objects.count(),
            "photos": OldToolPhoto.objects.count(),
            "replaced_positions": ToolChangeDetail.objects.filter(is_replaced=True)
            .values("cutter_position_no")
            .distinct()
            .count(),
        }
        all_position_nos = set(
            ToolChangeDetail.objects.exclude(cutter_position_no__isnull=True)
            .exclude(cutter_position_no="")
            .values_list("cutter_position_no", flat=True)
        )
        replacement_counts = {
            row["cutter_position_no"]: row["count"]
            for row in ToolChangeDetail.objects.filter(is_replaced=True)
            .values("cutter_position_no")
            .annotate(count=Count("id"))
        }
        insufficient_lifespan_positions = sorted(
            position_no
            for position_no in all_position_nos
            if replacement_counts.get(position_no, 0) < MIN_REPLACEMENTS_FOR_LIFESPAN
        )
        counts["positions_with_lifespan"] = len(
            all_position_nos - set(insufficient_lifespan_positions)
        )
        expected = {
            "openings": len(OPENINGS),
            "details": expected_details,
            "tasks": len(OPENINGS),
            "checked_details": checked_total,
            "replaced_details": replaced_total,
            "checked_only_details": checked_total - replaced_total,
            "pending_details": expected_details - checked_total,
            "new_tool_records": replaced_total,
            "old_tool_records": replaced_total,
            "photos": replaced_total,
            "positions_with_lifespan": len(all_position_nos),
        }
        mismatches = {
            key: (counts[key], value) for key, value in expected.items() if counts[key] != value
        }
        if mismatches:
            raise CommandError(f"Generated data failed count validation: {mismatches}")
        if insufficient_lifespan_positions:
            sample = "、".join(insufficient_lifespan_positions[:10])
            raise CommandError(
                "Some cutter positions have fewer than two replacement records: "
                f"{sample}"
            )

        coverage = {
            "ring_types": set(NewToolRecord.objects.exclude(ring_type__isnull=True).values_list("ring_type", flat=True)),
            "component_conditions": set(NewToolRecord.objects.exclude(shaft_condition__isnull=True).values_list("shaft_condition", flat=True)),
            "ring_damage": {
                item
                for values in OldToolRecord.objects.values_list("ring_damage", flat=True)
                for item in (values or [])
            },
            "bearing_reasons": {
                item
                for values in OldToolRecord.objects.values_list("bearing_failure_reasons", flat=True)
                for item in (values or [])
            },
            "hub_reasons": {
                item
                for values in OldToolRecord.objects.values_list("hub_failure_reasons", flat=True)
                for item in (values or [])
            },
            "dispositions": set(OldToolRecord.objects.values_list("disposition", flat=True)),
            "inspection_statuses": set(OldToolRecord.objects.values_list("inspection_status", flat=True)),
            "wear_conditions": set(
                ToolChangeDetail.objects.filter(is_checked=True).values_list("wear_condition", flat=True)
            ),
            "tool_parent_types": set(
                ToolChangeDetail.objects.filter(is_checked=True).values_list("tool_parent_type", flat=True)
            ),
            "replacement_types": set(
                ToolChangeDetail.objects.filter(is_replaced=True).values_list("replacement_type", flat=True)
            ),
            "check_results": set(
                ToolChangeDetail.objects.filter(is_checked=True).values_list("check_result", flat=True)
            ),
            "manufacturers": set(
                ToolChangeDetail.objects.filter(is_replaced=True)
                .exclude(manufacturer__isnull=True)
                .exclude(manufacturer="")
                .values_list("manufacturer", flat=True)
            ),
        }
        expected_coverage = {
            "ring_types": {"SMOOTH", "INSERTED"},
            "component_conditions": {"NEW", "REPAIRED"},
            "ring_damage": set(RING_DAMAGE),
            "bearing_reasons": set(BEARING_REASONS),
            "hub_reasons": set(HUB_REASONS),
            "dispositions": {"SCRAP", "REPAIRABLE"},
            "inspection_statuses": set(INSPECTION_STATUSES),
            "wear_conditions": set(WEAR_CONDITIONS),
            "tool_parent_types": {"DISC", "SCRAPER"},
            "replacement_types": {"COMPLETE", "REPAIR"},
            "check_results": {"NOT_REPLACED", "NORMAL", "ATTENTION", "ABNORMAL_NOT_REPLACED"},
        }
        missing = {
            key: sorted(values - coverage[key])
            for key, values in expected_coverage.items()
            if values - coverage[key]
        }
        if missing:
            raise CommandError(f"Generated data failed enum coverage validation: {missing}")
        if len(coverage["manufacturers"]) < 2:
            raise CommandError(
                "Generated data needs at least two replacement manufacturers for comparison charts."
            )
        return counts
