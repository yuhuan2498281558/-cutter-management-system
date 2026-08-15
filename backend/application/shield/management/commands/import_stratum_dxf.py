# -*- coding: utf-8 -*-
"""从 DXF 解析产物导入每环多地层数据（替代 import_stratum_pdf 的图例 Voronoi 启发式）。

数据来源与方法（详见 ring_stratum_v2.json 的生成过程）：
  1. 环号轴：图纸"N环"标签 843 个，环0=x2374.66，1环=1图纸单位=2.000m，
     环0=DK28+849.8、环2800=DK34+449.8，与图框里程 5599.8m 分毫不差；
  2. 主分段：图上五个大类各占一行的分段条形表（几何色块），四个稀有类与
     黏土夹砂的补集完全吻合，铺满 0~2800 环零缝隙；三处基岩凸起与图上
     起止里程标注（DK29+935.1~976.5 / DK33+108.5~368.0 / DK33+971.8~999.1）、
     软土地基与"软基加固DK33+670~970"逐一对上；
  3. 叠加层：孤石预估①~⑨段（标签+长度，合计 1747m 与表头一致，左端对齐经
     37 个剖面孤石引线点验证）+ 钻探揭露孤石段 DK33+450~475 +
     弱风化侵入洞身勘察原文 8 段 + 碎块状强风化 5 段（合计 588.8m 与表头一致）。

⚠ 导入会改变 StratumBasicInfo（当前 487 条模拟数据 → 2800 条图纸真实数据），
  从而改变实验真值与数据指纹。正在跑 benchmark（run_experiment）时严禁执行；
  导入后必须重跑 verify_ground_truth 重新生成快照。

用法：
    python manage.py import_stratum_dxf --json path/to/ring_stratum.json --project demo-project --dry-run
    python manage.py import_stratum_dxf --json path/to/ring_stratum.json --project demo-project            # 实际写入（upsert）
    python manage.py import_stratum_dxf --json path/to/ring_stratum.json --project demo-project --purge    # 先删该项目全部地层记录再导入
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

VALID_CODES = {"CLAY_SAND", "SOFT_HARD", "WEAK_GRANITE",
               "BEDROCK_PROTRUSION", "SOFT_SOIL", "BOULDER"}


class Command(BaseCommand):
    help = "从 ring_stratum_v2.json 导入每环多地层数据"

    def add_arguments(self, parser):
        parser.add_argument("--json", required=True, help="ring_stratum_v2.json 路径")
        parser.add_argument("--project", required=True, help="项目编号（project_id）")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--purge", action="store_true",
                            help="导入前删除该项目现有全部地层记录（清掉模拟数据）")

    def handle(self, *args, **options):
        from application.shield.models import StratumBasicInfo, ProjectInfo

        path = Path(options["json"])
        if not path.exists():
            raise CommandError(f"文件不存在：{path}")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        rings = payload.get("rings") or {}
        if not rings:
            raise CommandError("JSON 中没有 rings 数据")

        bad = {c for codes in rings.values() for c in codes} - VALID_CODES
        if bad:
            raise CommandError(f"存在未知地层编码：{bad}")

        try:
            project = ProjectInfo.objects.get(project_id=options["project"])
        except ProjectInfo.DoesNotExist:
            raise CommandError(f"项目 {options['project']} 不存在")

        multi = sum(1 for codes in rings.values() if len(codes) > 1)
        self.stdout.write(
            f"待导入 {len(rings)} 环（多地层 {multi} 环），"
            f"环宽 {payload.get('ring_width_m')}m，环0 里程 {payload.get('ring0_station_m')}m"
        )
        existing = StratumBasicInfo.objects.filter(project=project).count()
        self.stdout.write(f"该项目现有地层记录 {existing} 条"
                          + ("（--purge 将全部删除）" if options["purge"] else ""))

        if options["dry_run"]:
            sample = sorted(rings.items(), key=lambda kv: int(kv[0]))
            for ring_no, codes in sample[:5] + sample[-5:]:
                self.stdout.write(f"  环 {ring_no}: {','.join(codes)}")
            self.stdout.write(self.style.WARNING("DRY RUN，未写入。"))
            return

        with transaction.atomic():
            if options["purge"]:
                deleted, _ = StratumBasicInfo.objects.filter(project=project).delete()
                self.stdout.write(f"已删除 {deleted} 条旧记录")
            created = updated = 0
            for ring_no, codes in rings.items():
                _, is_created = StratumBasicInfo.objects.update_or_create(
                    project=project, ring_no=str(ring_no),
                    defaults={"stratum_type_codes": ",".join(codes)},
                )
                created += is_created
                updated += (not is_created)
        self.stdout.write(self.style.SUCCESS(
            f"完成：新建 {created}，更新 {updated}。"
            "请重跑 verify_ground_truth 更新真值快照与数据指纹。"
        ))
