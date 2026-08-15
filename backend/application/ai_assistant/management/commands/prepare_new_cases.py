# -*- coding: utf-8 -*-
"""把新增用例并入题库前的落地检查。

放到 backend/application/ai_assistant/management/commands/ 下，然后：

    python manage.py prepare_new_cases

它做四件事，任何一步不通过都不会写出新题库：
  1. 从库里挑一把【已拆下】的刀实例编号，填掉用例里的 {{TOOL_NO}} 占位符；
  2. 逐条执行 gt_sql，把真值行打印出来供人眼核对（这是我无法在本地替你做的一步）；
  3. 检查用例 id 与现有题库不冲突、answer_extract 的字段名与 gt_sql 的列别名一一对应；
  4. 全部通过后写出 question_bank_v3.json（原 v2 不动）。
"""
import json
import os
import re

from django.core.management.base import BaseCommand
from django.db import connection

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_ID = os.environ.get("DEMO_PROJECT_ID", "demo-project")

# 找一把已经被拆下来的刀：它自己是某次换刀装上去的，且同刀位在更靠后的环上又换过一次
PICK_TOOL_SQL = """
WITH inst AS (
  SELECT d.tool_number AS tool_number, d.cutter_position_no AS pos,
         MIN(CAST(w.ring_no AS INTEGER)) AS install_ring
  FROM shield_tool_change_detail d
  JOIN shield_warehouse_opening_basic w ON d.warehouse_id = w.id
  JOIN shield_project_info p ON w.project_id = p.id
  WHERE p.project_id = %s AND d.is_replaced
    AND d.tool_number IS NOT NULL AND d.tool_number <> ''
    AND w.ring_no ~ '^[0-9]+$'
  GROUP BY d.tool_number, d.cutter_position_no),
nxt AS (
  SELECT i.tool_number, i.pos, i.install_ring,
    (SELECT MIN(CAST(w2.ring_no AS INTEGER))
     FROM shield_tool_change_detail d2
     JOIN shield_warehouse_opening_basic w2 ON d2.warehouse_id = w2.id
     JOIN shield_project_info p2 ON w2.project_id = p2.id
     WHERE p2.project_id = %s AND d2.cutter_position_no = i.pos
       AND d2.is_replaced AND w2.ring_no ~ '^[0-9]+$'
       AND CAST(w2.ring_no AS INTEGER) > i.install_ring) AS removal_ring
  FROM inst i)
SELECT tool_number, pos, install_ring, removal_ring
FROM nxt WHERE removal_ring IS NOT NULL
ORDER BY removal_ring - install_ring DESC, tool_number LIMIT 1
"""


# 路由修复的连带影响：manufacturer_count 修复后由 Agent 路径改走 manufacturer 模板，
# 模板句是"覆盖 6 个厂家"，而该题原正则只认 共/涉及/有 三个前缀，会抽不到值而误判为错。
# 这正是 §7(8) 说的"评分器与题库共同演化"风险，必须在重跑前补掉。
BANK_REGEX_FIXUP = {
    "manufacturer_count": {
        "manufacturer_count": [
            "覆盖\\s*(\\d+)\\s*个厂家",
            "(?:共|涉及|有)\\D{0,10}?(\\d+)\\s*(?:家|个厂家)",
        ]
    },
}


# 排名类用例的并列诊断：真值取 LIMIT 1，若第一名存在并列则该断言不可靠
TIE_CHECK = {
    "ps_top_position": """
        SELECT COUNT(*) FROM (
          SELECT d.cutter_position_no, SUM(GREATEST(1, COALESCE(sc.n, 0))) AS t
          FROM shield_tool_change_detail d
          JOIN shield_warehouse_opening_basic w ON d.warehouse_id = w.id
          JOIN shield_project_info p ON w.project_id = p.id
          LEFT JOIN LATERAL (
            SELECT (SELECT COUNT(*) FROM unnest(string_to_array(s.stratum_type_codes, ',')) tk
                    WHERE btrim(tk) <> '') AS n
            FROM shield_stratum_basic_info s
            WHERE s.project_id = p.id AND btrim(s.ring_no) = btrim(w.ring_no)
              AND COALESCE(s.stratum_type_codes,'') <> '' LIMIT 1) sc ON TRUE
          WHERE p.project_id = %s AND d.is_replaced
          GROUP BY d.cutter_position_no
        ) q WHERE q.t = (SELECT MAX(t2) FROM (
          SELECT SUM(GREATEST(1, COALESCE(sc2.n, 0))) AS t2
          FROM shield_tool_change_detail d2
          JOIN shield_warehouse_opening_basic w2 ON d2.warehouse_id = w2.id
          JOIN shield_project_info p2 ON w2.project_id = p2.id
          LEFT JOIN LATERAL (
            SELECT (SELECT COUNT(*) FROM unnest(string_to_array(s2.stratum_type_codes, ',')) tk2
                    WHERE btrim(tk2) <> '') AS n
            FROM shield_stratum_basic_info s2
            WHERE s2.project_id = p2.id AND btrim(s2.ring_no) = btrim(w2.ring_no)
              AND COALESCE(s2.stratum_type_codes,'') <> '' LIMIT 1) sc2 ON TRUE
          WHERE p2.project_id = %s AND d2.is_replaced
          GROUP BY d2.cutter_position_no) x)
    """,
}


class Command(BaseCommand):
    help = "校验并合并新增规则分支用例，产出 question_bank_v3.json"

    def add_arguments(self, parser):
        parser.add_argument("--new", default=os.path.join(APP_DIR, "new_cases.json"))
        parser.add_argument("--bank", default=os.path.join(APP_DIR, "question_bank_v2.json"))
        parser.add_argument("--out", default=os.path.join(APP_DIR, "question_bank_v3.json"))
        parser.add_argument("--write", action="store_true",
                            help="不加此参数则只做干跑，不写出新题库")

    # ---------- 工具 ----------
    def _load(self, path):
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)

    def _run_sql(self, sql):
        with connection.cursor() as cur:
            cur.execute(sql)
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
        return cols, rows

    # ---------- 主流程 ----------
    def handle(self, *args, **opts):
        new_cases = self._load(opts["new"])
        bank = self._load(opts["bank"])
        problems = []

        # 1. 填占位符
        with connection.cursor() as cur:
            cur.execute(PICK_TOOL_SQL, [PROJECT_ID, PROJECT_ID])
            picked = cur.fetchone()
        if picked:
            # PICK_TOOL_SQL 返回四列：编号、刀位、安装环号、拆卸环号
            tool_no, pos, install_ring, removal_ring = picked
            self.stdout.write(self.style.SUCCESS(
                "选中刀具实例 %s（刀位 %s，安装环号 %s，拆卸环号 %s，服役 %s 环）填入 {{TOOL_NO}}"
                % (tool_no, pos, install_ring, removal_ring,
                   (removal_ring - install_ring) if (removal_ring is not None and install_ring is not None) else "?")))
        else:
            tool_no = None
            self.stdout.write(self.style.WARNING(
                "库中找不到【已拆下】的刀具实例，含 {{TOOL_NO}} 的用例将被跳过（不并入题库）"))

        kept = []
        for case in new_cases:
            blob = json.dumps(case, ensure_ascii=False)
            if "{{TOOL_NO}}" in blob:
                if not tool_no:
                    self.stdout.write("  跳过 %s（缺少可用刀具编号）" % case["id"])
                    continue
                case = json.loads(blob.replace("{{TOOL_NO}}", tool_no))
            kept.append(case)

        # 2. id 冲突
        existing = {c["id"] for c in bank}
        for case in kept:
            if case["id"] in existing:
                problems.append("id 冲突：%s 已存在于题库" % case["id"])

        # 3. 逐条跑 gt_sql，打印真值
        self.stdout.write("\n" + "=" * 78)
        self.stdout.write("gt_sql 干跑结果（请人眼核对每个数字是否合理）")
        self.stdout.write("=" * 78)
        for case in kept:
            sql = case.get("gt_sql")
            self.stdout.write("\n[%s] %s" % (case["id"], case["question"]))
            if not sql:
                self.stdout.write("    （无 gt_sql，仅断言路由与模板结构）")
                continue
            try:
                cols, rows = self._run_sql(sql)
            except Exception as exc:                      # noqa: BLE001
                problems.append("gt_sql 执行失败：%s → %s" % (case["id"], exc))
                self.stdout.write(self.style.ERROR("    SQL 执行失败：%s" % exc))
                continue
            if not rows:
                problems.append("gt_sql 返回空行：%s" % case["id"])
                self.stdout.write(self.style.ERROR("    返回 0 行（真值为空，用例无法判定）"))
                continue
            self.stdout.write("    列：%s" % ", ".join(cols))
            for row in rows[:3]:
                self.stdout.write("    值：%s" % ", ".join(
                    "%s=%s" % (c, v) for c, v in zip(cols, row)))
            # 4. 断言字段必须能在 gt_sql 的列里找到
            for field in (case.get("answer_extract") or {}):
                if field not in cols:
                    problems.append("字段对不上：%s 的 answer_extract['%s'] 在 gt_sql 列 %s 中不存在"
                                    % (case["id"], field, cols))
            # NULL 真值会让断言无法判定
            for c, v in zip(cols, rows[0]):
                if c in (case.get("answer_extract") or {}) and v is None:
                    problems.append("真值为 NULL：%s 的 %s（该口径在当前数据下无有效样本）" % (case["id"], c))

        # 4b. 排名类用例的并列检查
        for cid, sql in TIE_CHECK.items():
            if not any(c["id"] == cid for c in kept):
                continue
            try:
                with connection.cursor() as cur:
                    cur.execute(sql, [PROJECT_ID, PROJECT_ID])
                    tied = cur.fetchone()[0]
            except Exception as exc:                      # noqa: BLE001
                self.stdout.write(self.style.WARNING("    并列检查失败（%s）：%s" % (cid, exc)))
                continue
            if tied and tied > 1:
                problems.append("第一名存在 %d 路并列：%s —— LIMIT 1 取到哪个不确定，该断言不可用" % (tied, cid))
            else:
                self.stdout.write(self.style.SUCCESS("\n[%s] 第一名无并列 ✔" % cid))

        # 5. 汇总
        self.stdout.write("\n" + "=" * 78)
        if problems:
            self.stdout.write(self.style.ERROR("发现 %d 个问题，未写出新题库：" % len(problems)))
            for p in problems:
                self.stdout.write("  - " + p)
            return
        self.stdout.write(self.style.SUCCESS("全部检查通过：%d 条新用例可并入" % len(kept)))
        if not opts["write"]:
            self.stdout.write("干跑模式，未写文件。确认无误后加 --write 再跑一次。")
            return
        fixed = 0
        for case in bank:
            patch = BANK_REGEX_FIXUP.get(case["id"])
            if patch:
                case.setdefault("answer_extract", {}).update(patch)
                fixed += 1
        if fixed:
            self.stdout.write(self.style.SUCCESS(
                "已补正 %d 条既有用例的抽取正则（路由修复的连带影响）" % fixed))
        merged = bank + kept
        with open(opts["out"], "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=1)
        self.stdout.write(self.style.SUCCESS(
            "已写出 %s（%d → %d 条）" % (opts["out"], len(bank), len(merged))))
