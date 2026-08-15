"""执行题库里的全部 gt_sql，产出真值快照与数据指纹。

论文的"实验可复现"要靠两件事：真值是独立于被测系统算出来的，以及跑实验时的数据
状态是可标识的。这个命令负责第二件事——把每张相关表的行数与最后更新时间拼成
sha256 指纹，写进快照文件。论文方法节里写明 "Dataset frozen on YYYY-MM-DD,
fingerprint abc123..."，返修时能证明前后跑的是同一份数据。

顺带做一次题库体检：哪些用例还没有 gt_sql、哪些 gt_sql 跑不通、哪些 answer_extract
的正则抓不到自己 gt 的字段名。这些都是跑正式实验前必须清零的。

用法：
    python manage.py verify_ground_truth
    python manage.py verify_ground_truth --output ground_truth_snapshot.json
"""

import hashlib
import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

FINGERPRINT_TABLES = [
    "shield_project_info",
    "shield_stratum_basic_info",
    "shield_warehouse_opening_basic",
    "shield_tool_change_detail",
    "shield_tunneling_data",
    "shield_tool_info",
    "shield_tool_cost",
    "shield_cutter_position_info",
    "shield_tool_instance",
    "shield_new_tool_record",
    "shield_old_tool_record",
]


class Command(BaseCommand):
    help = "执行题库 gt_sql，输出真值快照与数据指纹"

    def add_arguments(self, parser):
        parser.add_argument("--bank", default="")
        parser.add_argument("--output", default="ground_truth_snapshot.json")
        parser.add_argument("--project", default=os.environ.get("DEMO_PROJECT_ID", "demo-project"))

    def handle(self, *args, **options):
        bank_path = Path(options["bank"] or (Path(__file__).resolve().parents[2] / "question_bank_v2.json"))
        if not bank_path.exists():
            raise CommandError(f"题库不存在：{bank_path}")
        cases = json.loads(bank_path.read_text(encoding="utf-8-sig"))

        fingerprint, table_stats = self._fingerprint()
        self.stdout.write("数据指纹：" + fingerprint)
        for table, stat in table_stats.items():
            self.stdout.write(f"  {table:36s} rows={stat['rows']:<8} last_update={stat['last_update']}")

        # 展开 gt_ref 变体与多轮题
        from .run_experiment import resolve_refs
        cases = resolve_refs(cases)
        units = []
        for case in cases:
            if case.get("turns"):
                for index, turn in enumerate(case["turns"]):
                    units.append((f"{case['id']}#t{index + 1}", turn))
            else:
                units.append((case["id"], case))

        snapshot, problems = {}, []
        no_gt = []
        for unit_id, case in units:
            case = dict(case, id=unit_id)
            sql = case.get("gt_sql")
            if not sql:
                no_gt.append(unit_id)
                continue
            try:
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                    columns = [c[0] for c in cursor.description]
                    rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
                snapshot[case["id"]] = rows
                if not rows:
                    problems.append(f"{case['id']}: gt_sql 返回 0 行")
                else:
                    missing = [
                        field for field in (case.get("answer_extract") or {})
                        if field not in rows[0]
                    ]
                    if missing:
                        problems.append(
                            f"{case['id']}: answer_extract 的字段 {missing} 不在 gt_sql 结果列 {columns} 中"
                        )
            except Exception as e:
                problems.append(f"{case['id']}: gt_sql 执行失败 - {e}")

        self.stdout.write("")
        self.stdout.write(f"用例总数 {len(cases)}，其中有 gt_sql 的 {len(snapshot)} 条")
        if no_gt:
            self.stdout.write(self.style.WARNING(
                f"以下 {len(no_gt)} 条还没有 gt_sql（知识题/拒答题可用人工评分，"
                f"数值题必须补上）：\n  " + "、".join(no_gt)
            ))
        if problems:
            self.stdout.write(self.style.ERROR("需要修正的问题："))
            for item in problems:
                self.stdout.write(self.style.ERROR(f"  {item}"))
        else:
            self.stdout.write(self.style.SUCCESS("全部 gt_sql 执行通过，字段与 answer_extract 对得上。"))

        payload = {
            "project": options["project"],
            "fingerprint": fingerprint,
            "tables": table_stats,
            "case_count": len(cases),
            "ground_truth": snapshot,
            "cases_without_gt_sql": no_gt,
            "problems": problems,
        }
        Path(options["output"]).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        self.stdout.write(f"\n快照已写出：{options['output']}")

    def _fingerprint(self):
        stats = {}
        parts = []
        with connection.cursor() as cursor:
            for table in FINGERPRINT_TABLES:
                try:
                    cursor.execute(f"SELECT COUNT(*), MAX(update_datetime) FROM {table}")
                    rows, last_update = cursor.fetchone()
                except Exception:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        rows, last_update = cursor.fetchone()[0], None
                    except Exception:
                        rows, last_update = None, None
                stats[table] = {"rows": rows, "last_update": str(last_update) if last_update else ""}
                parts.append(f"{table}:{rows}:{stats[table]['last_update']}")
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
        return digest, stats
