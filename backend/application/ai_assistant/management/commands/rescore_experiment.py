# -*- coding: utf-8 -*-
"""对已有实验 JSONL 按当前题库正则 + 评分器离线重评 exact_match。

评分器/题库每轮校准后，历史运行结果无需重跑 LLM：答案文本、真值行、
配置都在记录里，重评只是重新执行"抽取-比对"这一确定性步骤。
幻觉字段不动（运行时白名单含工具原始返回，离线不可完整复现）。

用法：
    python manage.py rescore_experiment --input experiment_r1_hybrid.jsonl
    # 输出 experiment_r1_hybrid.rescored.jsonl：
    #   exact_match 为新值，原值保留在 exact_match_prev；
    #   断言被撤销的用例 exact_match 置 null（不计入分母）。
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from application.ai_assistant import scoring

_INHERITED_KEYS = ("gt_sql", "answer_extract", "tolerance",
                   "expected_tool", "expected_args", "expected_route", "expected_rule_branch")


def load_bank(path):
    bank = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    cases = bank if isinstance(bank, list) else bank["cases"]
    byid = {c["id"]: c for c in cases}
    for c in cases:  # resolve_refs 等价
        ref = c.get("gt_ref")
        if ref and ref in byid:
            for k in _INHERITED_KEYS:
                if not c.get(k) and byid[ref].get(k):
                    c[k] = byid[ref][k]
    return byid


def spec_for(record, byid):
    case = byid.get(record.get("root_case_id") or record["case_id"])
    if case is None:
        return None
    ti = record.get("turn_index")
    if ti:
        unit = (case.get("turns") or [])[ti - 1]
        spec = {k: case.get(k) for k in _INHERITED_KEYS if case.get(k)}
        spec.update(unit)
        return spec
    return case


class Command(BaseCommand):
    help = "按当前题库/评分器离线重评实验 JSONL 的 exact_match"

    def add_arguments(self, parser):
        parser.add_argument("--input", required=True)
        parser.add_argument("--bank", default="")
        parser.add_argument("--output", default="", help="默认 <input>.rescored.jsonl")

    def handle(self, *args, **options):
        src = Path(options["input"])
        if not src.exists():
            raise CommandError(f"文件不存在：{src}")
        bank_path = options["bank"] or (
            Path(__file__).resolve().parents[2] / "question_bank_v2.json")
        byid = load_bank(bank_path)
        dst = Path(options["output"] or src.with_suffix(".rescored.jsonl"))

        flips = kept = 0
        with src.open(encoding="utf-8-sig") as fin, dst.open("w", encoding="utf-8") as fout:
            for line in fin:
                if not line.strip():
                    continue
                r = json.loads(line)
                spec = spec_for(r, byid)
                old = r.get("exact_match")
                if spec is not None and spec.get("answer_extract") == {}:
                    new = None                      # 断言已撤销
                elif not spec or not spec.get("answer_extract") or not r.get("gt_available"):
                    new = old
                else:
                    res = scoring.score_answer(r.get("answer") or "", r.get("gt_row") or {}, spec)
                    new = res["exact_match"]
                    if new != old:
                        r["extracted"] = res["extracted"]
                        r["per_field"] = res["per_field"]
                if new != old:
                    r["exact_match_prev"] = old
                    r["exact_match"] = new
                    flips += 1
                else:
                    kept += 1
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")

        self.stdout.write(self.style.SUCCESS(
            f"重评完成：翻转 {flips}，不变 {kept} → {dst}"))
