"""盘点 ToolChangeDetail.wear_condition 的实际取值分布。

背景：wear_condition 是自由 CharField，库中可能同时存在
  - models.ToolChangeDetail.WEAR_CONDITION_CHOICES 定义的英文枚举码
    （GOOD / NORMAL / MODERATE / SEVERE / ABNORMAL），开仓自动建档写入 "NORMAL"；
  - 人工 / 移动端录入的中文描述（正常、偏磨、刀圈崩刃 …）。

tools.normalize_wear_condition 已统一兼容两套取值，但仍需要确认：
  1. 库里到底存的是哪一套（决定论文里怎么描述数据）；
  2. 有没有落到 'unknown' 的取值 —— 这些取值既不算正常也不算异常，
     会被排除在异常磨损率的分母之外，必须补进 tools.py 的词表。

用法：
    python manage.py inspect_wear_conditions
    python manage.py inspect_wear_conditions --project demo-project
    python manage.py inspect_wear_conditions --output wear_conditions.json
"""

import json

from django.core.management.base import BaseCommand
from django.db.models import Count

from application.shield.models import ToolChangeDetail
from application.ai_assistant.tools import normalize_wear_condition


class Command(BaseCommand):
    help = "盘点 wear_condition 的实际取值，检查归一化词表是否覆盖完整"

    def add_arguments(self, parser):
        parser.add_argument("--project", default="", help="按项目编号过滤，默认全部")
        parser.add_argument("--output", default="", help="可选：把结果写成 JSON")

    def handle(self, *args, **options):
        qs = ToolChangeDetail.objects.all()
        project = (options.get("project") or "").strip()
        if project:
            qs = qs.filter(warehouse__project__project_id=project)

        rows = list(
            qs.values("wear_condition")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        total = sum(r["count"] for r in rows)

        buckets = {"normal": 0, "abnormal": 0, "unknown": 0}
        unknown_values = []
        for r in rows:
            bucket = normalize_wear_condition(r["wear_condition"])
            buckets[bucket] += r["count"]
            if bucket == "unknown":
                unknown_values.append({"value": r["wear_condition"], "count": r["count"]})

        self.stdout.write(f"记录总数: {total}")
        if project:
            self.stdout.write(f"项目筛选: {project}")
        self.stdout.write("")
        self.stdout.write(f"{'wear_condition':<28}{'count':>8}  {'归一化':<10}")
        self.stdout.write("-" * 50)
        for r in rows:
            value = r["wear_condition"]
            shown = "<NULL>" if value is None else (repr(value) if value.strip() == "" else value)
            self.stdout.write(f"{shown:<28}{r['count']:>8}  {normalize_wear_condition(value):<10}")

        self.stdout.write("")
        self.stdout.write(
            f"归一化结果  正常={buckets['normal']}  异常={buckets['abnormal']}  未识别={buckets['unknown']}"
        )
        classified = buckets["normal"] + buckets["abnormal"]
        if classified:
            self.stdout.write(
                f"异常磨损率（异常 / 已分类）= {buckets['abnormal'] / classified * 100:.1f}%"
            )

        if unknown_values:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "以下取值未被 tools.py 的归一化词表覆盖，会被排除在异常磨损率分母之外，"
                "请补进 _WEAR_NORMAL_TOKENS 或 _WEAR_ABNORMAL_TOKENS："
            ))
            for item in unknown_values:
                self.stdout.write(self.style.WARNING(f"  {item['value']!r}  ({item['count']} 条)"))
        else:
            self.stdout.write(self.style.SUCCESS("所有取值均已被归一化词表覆盖。"))

        if options.get("output"):
            payload = {
                "project": project or None,
                "total": total,
                "distribution": rows,
                "normalized": buckets,
                "unclassified_values": unknown_values,
            }
            with open(options["output"], "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            self.stdout.write(f"\n已写出 {options['output']}")
