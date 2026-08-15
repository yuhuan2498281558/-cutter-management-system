# -*- coding: utf-8 -*-
"""重算全部开仓记录的地层快照（stratum_info_between）。

背景：开仓记录保存时会把"上次开仓环号 ~ 本次开仓环号之间经过的地层统计"
写入 stratum_info_between 字段作为快照，此后地层表的变更不会回写。
用 import_stratum_dxf 替换地层数据后，历史开仓记录的快照仍是旧值，
需要用本命令按新地层表批量重算。

计算口径与 views.py 序列化器的 _build_auto_stratum_info 保持一致：
  区间 = (last_ring_no, ring_no]，逐环取地层表的 stratum_type_codes
  按逗号拆分计数，得到 {地层编码: 环数}。

用法：
    python manage.py refresh_opening_stratum --project demo-project --dry-run
    python manage.py refresh_opening_stratum --project demo-project
"""
from django.core.management.base import BaseCommand, CommandError


def _ring_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class Command(BaseCommand):
    help = "按当前地层表重算开仓记录的 stratum_info_between 快照"

    def add_arguments(self, parser):
        parser.add_argument("--project", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        from application.shield.models import (
            WarehouseOpeningBasicInfo, StratumBasicInfo, ProjectInfo,
        )

        try:
            project = ProjectInfo.objects.get(project_id=options["project"])
        except ProjectInfo.DoesNotExist:
            raise CommandError(f"项目 {options['project']} 不存在")

        # 地层表一次读入：{环号int: [codes]}
        stratum = {}
        for row in StratumBasicInfo.objects.filter(project=project).values(
            "ring_no", "stratum_type_codes"
        ):
            ring = _ring_int(row["ring_no"])
            if ring is None:
                continue
            stratum[ring] = [
                c.strip() for c in (row["stratum_type_codes"] or "").split(",") if c.strip()
            ]

        openings = WarehouseOpeningBasicInfo.objects.filter(project=project).order_by("id")
        changed = unchanged = skipped = 0
        for opening in openings:
            current = _ring_int(opening.ring_no)
            last = _ring_int(opening.last_ring_no)
            if current is None or last is None or current <= last:
                skipped += 1
                continue
            counts = {}
            for ring in range(last + 1, current + 1):
                for code in stratum.get(ring, []):
                    counts[code] = counts.get(code, 0) + 1
            if opening.stratum_info_between == counts:
                unchanged += 1
                continue
            self.stdout.write(
                f"环 {opening.ring_no}（{opening.last_ring_no}~{opening.ring_no}）: "
                f"{opening.stratum_info_between} -> {counts}"
            )
            if not options["dry_run"]:
                opening.stratum_info_between = counts
                opening.save(update_fields=["stratum_info_between"])
            changed += 1

        tail = "（DRY RUN 未写入）" if options["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"完成：更新 {changed}，无变化 {unchanged}，跳过（环号缺失/区间无效）{skipped}{tail}"
        ))
