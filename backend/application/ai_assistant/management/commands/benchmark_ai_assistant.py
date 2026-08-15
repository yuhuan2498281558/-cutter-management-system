import json
import os
import csv
import time

from django.core.management.base import BaseCommand

from application.ai_assistant.llm_provider import get_llm_config
from application.ai_assistant.llm_service import get_assistant


DEFAULT_QUESTIONS = [
    "分析地层类型和磨损情况的关联性",
    "对比各厂家刀具性能表现",
    "最近3次开仓情况",
    "哪些刀位最容易磨损",
    "换刀趋势有没有变化",
    "统计换刀数据",
    "地层类型分布",
    "解释一下盾构刀具偏磨通常是什么原因",
]


class Command(BaseCommand):
    help = "Benchmark AI assistant response time and success rate for paper experiments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default="ai_assistant_benchmark.json",
            help="Output JSON file path.",
        )
        parser.add_argument(
            "--question",
            action="append",
            dest="questions",
            help="Question to benchmark. Can be passed multiple times.",
        )
        parser.add_argument(
            "--question-file",
            help="UTF-8 text file with one question per line.",
        )
        parser.add_argument(
            "--csv-output",
            help="Optional CSV output path for paper tables.",
        )
        parser.add_argument(
            "--user-id",
            default="benchmark",
            help="Session/user id for chat history.",
        )

    def handle(self, *args, **options):
        questions = list(options["questions"] or [])
        if options.get("question_file"):
            with open(options["question_file"], "r", encoding="utf-8") as f:
                questions.extend(line.strip() for line in f if line.strip())
        if not questions:
            questions = DEFAULT_QUESTIONS
        output = options["output"]
        csv_output = options.get("csv_output")
        user_id = options["user_id"]

        config = get_llm_config()
        assistant = get_assistant()
        route_mode = os.environ.get("AI_ASSISTANT_ROUTE_MODE", "hybrid")

        rows = []
        started = time.perf_counter()
        for question in questions:
            item_started = time.perf_counter()
            result = assistant.chat(question, {"user_id": user_id, "username": "benchmark"})
            elapsed_ms = round((time.perf_counter() - item_started) * 1000, 2)
            answer = result.get("answer") or result.get("error") or ""
            row = {
                "question": question,
                "success": bool(result.get("success")),
                "type": result.get("type"),
                "elapsed_ms": elapsed_ms,
                "answer_chars": len(answer),
                "preview": answer[:120],
            }
            rows.append(row)
            self.stdout.write(
                f"{elapsed_ms:>8.2f} ms | {row['success']} | {row['type']} | {question}"
            )

        total_ms = round((time.perf_counter() - started) * 1000, 2)
        summary = {
            "provider": config.provider,
            "model": config.model,
            "base_url": config.base_url,
            "route_mode": route_mode,
            "question_count": len(rows),
            "success_count": sum(1 for row in rows if row["success"]),
            "total_ms": total_ms,
            "avg_ms": round(total_ms / len(rows), 2) if rows else 0,
        }
        payload = {"summary": summary, "results": rows}

        with open(output, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        if csv_output:
            with open(csv_output, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "provider",
                        "model",
                        "route_mode",
                        "question",
                        "success",
                        "type",
                        "elapsed_ms",
                        "answer_chars",
                    ],
                )
                writer.writeheader()
                for row in rows:
                    writer.writerow({
                        "provider": config.provider,
                        "model": config.model,
                        "route_mode": route_mode,
                        "question": row["question"],
                        "success": row["success"],
                        "type": row["type"],
                        "elapsed_ms": row["elapsed_ms"],
                        "answer_chars": row["answer_chars"],
                    })

        self.stdout.write(self.style.SUCCESS(f"Saved benchmark result to {output}"))
        if csv_output:
            self.stdout.write(self.style.SUCCESS(f"Saved benchmark CSV to {csv_output}"))
