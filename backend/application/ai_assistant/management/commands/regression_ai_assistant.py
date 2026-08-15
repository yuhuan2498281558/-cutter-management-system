# -*- coding: utf-8 -*-
import json
import os
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from application.ai_assistant.llm_service import get_assistant


def _compact_text(value):
    return "".join(str(value or "").split())


DEFAULT_CASES = [
    {
        "id": "tunneling_trend_ring5",
        "category": "tunneling_trend",
        "question": "第5环掘进参数趋势怎么样",
        "expected_type": "analysis",
        "must_contain": ["掘进", "第 1/10 段", "贯入力"],
    },
    {
        "id": "tunneling_summary",
        "category": "tunneling",
        "question": "最近掘进动态怎么样",
        "expected_type": "analysis",
        "must_contain": ["掘进", "推力"],
    },
    {
        "id": "cutter_position_top",
        "category": "cutter_position",
        "question": "哪个刀位更换最频繁",
        "expected_type": "analysis",
        "must_contain": ["刀位", "更换"],
    },
    {
        "id": "manufacturer_compare",
        "category": "manufacturer",
        "question": "对比各厂家刀具性能表现",
        "expected_type": "analysis",
        "must_contain": ["厂家"],
    },
    {
        "id": "opening_recent",
        "category": "opening",
        "question": "最近几次开仓情况",
        "expected_type": "analysis",
        "must_contain": ["开仓"],
    },
]


class Command(BaseCommand):
    help = "Run regression checks for AI assistant routing, tool calls, and final answers."

    def add_arguments(self, parser):
        parser.add_argument("--case-file", help="UTF-8 JSON file containing regression cases.")
        parser.add_argument("--output", default="", help="Optional JSON result output path.")
        parser.add_argument("--user-id", default="ai_regression", help="Session/user id for chat history.")
        parser.add_argument("--category", action="append", default=[], help="Run only cases in this category. Repeatable.")
        parser.add_argument("--case-id", action="append", default=[], help="Run only cases with this id. Repeatable.")
        parser.add_argument("--limit", type=int, default=0, help="Run at most N cases after filtering.")
        parser.add_argument("--list-categories", action="store_true", help="Print categories and exit.")
        parser.add_argument("--fail-fast", action="store_true", help="Stop at first failed case.")

    def _default_case_file(self):
        return Path(__file__).resolve().parents[2] / "question_bank.json"

    def _load_cases(self, path):
        if not path:
            default_path = self._default_case_file()
            if default_path.exists():
                path = str(default_path)
            else:
                return DEFAULT_CASES

        if not os.path.exists(path):
            raise CommandError(f"case-file not found: {path}")
        # utf-8-sig：question_bank.json 以 UTF-8 BOM 开头，用 "utf-8" 打开会让
        # json.load 抛 "Unexpected UTF-8 BOM"，导致本命令走默认题库时完全无法运行。
        # utf-8-sig 对无 BOM 的文件同样兼容。
        with open(path, "r", encoding="utf-8-sig") as f:
            cases = json.load(f)
        if not isinstance(cases, list):
            raise CommandError("case-file must contain a JSON array.")
        return cases

    def _filter_cases(self, cases, options):
        categories = set(options.get("category") or [])
        case_ids = set(options.get("case_id") or [])
        if categories:
            cases = [case for case in cases if case.get("category") in categories]
        if case_ids:
            cases = [case for case in cases if case.get("id") in case_ids]
        limit = options.get("limit") or 0
        if limit > 0:
            cases = cases[:limit]
        return cases

    def handle(self, *args, **options):
        cases = self._load_cases(options.get("case_file"))

        if options.get("list_categories"):
            category_counts = {}
            for case in cases:
                category = case.get("category", "uncategorized")
                category_counts[category] = category_counts.get(category, 0) + 1
            for category, count in sorted(category_counts.items()):
                self.stdout.write(f"{category}: {count}")
            return

        cases = self._filter_cases(cases, options)
        if not cases:
            raise CommandError("No regression cases matched the filters.")

        assistant = get_assistant()
        user_id = options["user_id"]

        rows = []
        for index, case in enumerate(cases, start=1):
            question = case["question"]
            started = time.perf_counter()
            result = assistant.chat(question, {"user_id": user_id, "username": "regression"})
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            answer = result.get("answer") or result.get("error") or ""

            failures = []
            if not result.get("success"):
                failures.append("success=false")
            expected_type = case.get("expected_type")
            if expected_type and result.get("type") != expected_type:
                failures.append(f"type={result.get('type')!r}, expected={expected_type!r}")
            compact_answer = _compact_text(answer)
            for keyword in case.get("must_contain", []):
                if keyword not in answer and _compact_text(keyword) not in compact_answer:
                    failures.append(f"missing keyword: {keyword}")

            ok = not failures
            row = {
                "index": index,
                "id": case.get("id", ""),
                "category": case.get("category", ""),
                "question": question,
                "success": bool(result.get("success")),
                "type": result.get("type"),
                "elapsed_ms": elapsed_ms,
                "answer_chars": len(answer),
                "ok": ok,
                "failures": failures,
                "preview": answer[:240],
            }
            rows.append(row)

            status = "PASS" if ok else "FAIL"
            self.stdout.write(
                f"{status} #{index} [{row['category']}] {row['id']} "
                f"{elapsed_ms:>8.2f} ms | {result.get('type')} | {question}"
            )
            if failures:
                self.stdout.write("  " + "; ".join(failures))
                if options["fail_fast"]:
                    break

        payload = {
            "summary": {
                "case_count": len(rows),
                "pass_count": sum(1 for row in rows if row["ok"]),
                "fail_count": sum(1 for row in rows if not row["ok"]),
            },
            "results": rows,
        }

        if options.get("output"):
            with open(options["output"], "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            self.stdout.write(self.style.SUCCESS(f"Saved regression result to {options['output']}"))

        if payload["summary"]["fail_count"]:
            raise CommandError(f"AI assistant regression failed: {payload['summary']['fail_count']} case(s).")

        self.stdout.write(self.style.SUCCESS("AI assistant regression passed."))
