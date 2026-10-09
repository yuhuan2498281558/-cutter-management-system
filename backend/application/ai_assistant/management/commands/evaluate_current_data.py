"""Generate a current-data evaluation without calling models or writing memory."""
import json
import hashlib
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from application.ai_assistant.evaluation.current_data_suite import (
    SCHEMA_VERSION, collect_evidence, evaluate, markdown_report, readonly_database,
)


class Command(BaseCommand):
    help = "以PostgreSQL只读事务评估当前数据规则能力，输出JSON/Markdown；不调用模型或写入记忆。"

    def add_arguments(self, parser):
        parser.add_argument("--project-id", required=True, help="明确的项目编号，不自动选择项目。")
        parser.add_argument("--output", required=True, help="本次结果输出目录；真实数据结果不得提交Git。")
        parser.add_argument("--statement-timeout-ms", type=int, default=15000)
        parser.add_argument("--row-limit", type=int, default=100000,
                            help="每类ORM证据最多加载行数，超限中止而不评分截断数据。")
        parser.add_argument("--inventory-only", action="store_true", help="只盘点数据，不执行规则问题。")
        parser.add_argument("--fail-on-error", action="store_true", help="保存报告后，若有失败题则以非零状态退出。")

    def handle(self, *args, **options):
        project_id = str(options["project_id"]).strip()
        if not project_id:
            raise CommandError("--project-id must not be empty")
        if options["row_limit"] < 1:
            raise CommandError("--row-limit must be positive")
        output = Path(options["output"]).expanduser().resolve()
        started_at = datetime.now(timezone.utc)
        source_root = Path(__file__).resolve().parents[2]
        source_files = [source_root / name for name in (
            "llm_service.py", "answer_reporting.py", "tools.py", "memory_service.py",
            "evaluation/current_data_suite.py", "evaluation/answer_checks.py",
        )]
        fingerprints = {path.relative_to(source_root).as_posix():
                        hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
        try:
            with readonly_database(timeout_ms=options["statement_timeout_ms"]):
                evidence = collect_evidence(project_id, row_limit=options["row_limit"])
                if options["inventory_only"]:
                    report = {"schema_version": SCHEMA_VERSION, "inventory": evidence.inventory(),
                              "mode": "inventory_only"}
                else:
                    report = evaluate(evidence)
        except Exception as error:
            raise CommandError(f"Read-only evaluation stopped: {type(error).__name__}: {error}") from error
        try:
            revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                      text=True, timeout=5, check=True).stdout.strip()
            dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                                       text=True, timeout=5, check=True).stdout.strip())
        except (OSError, subprocess.SubprocessError):
            revision = "unavailable"
            dirty = None
        changed_sources = [path.relative_to(source_root).as_posix() for path in source_files
                           if hashlib.sha256(path.read_bytes()).hexdigest() !=
                           fingerprints[path.relative_to(source_root).as_posix()]]
        run_id = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        report["run"] = {"id": run_id, "started_at": started_at.isoformat(), "git_revision": revision,
                         "git_dirty": dirty, "source_sha256": fingerprints,
                         "source_changed_during_run": changed_sources,
                         "database_transaction": "PostgreSQL REPEATABLE READ, READ ONLY",
                         "external_model_calls": 0, "persistent_memory_access": False}
        output.mkdir(parents=True, exist_ok=True)
        json_path = output / f"current-data-{run_id}.json"
        markdown_path = output / f"current-data-{run_id}.md"
        with json_path.open("x", encoding="utf-8") as target:
            json.dump(report, target, ensure_ascii=False, indent=2)
        markdown = ("# 当前项目只读数据盘点\n\n```json\n" + json.dumps(report["inventory"], ensure_ascii=False, indent=2)
                    + "\n```\n") if options["inventory_only"] else markdown_report(report)
        with markdown_path.open("x", encoding="utf-8") as target:
            target.write(markdown)
        self.stdout.write(f"JSON: {json_path}")
        self.stdout.write(f"Markdown: {markdown_path}")
        if "summary" in report:
            self.stdout.write(json.dumps(report["summary"], ensure_ascii=False))
            if options["fail_on_error"] and (report["summary"]["fail"] or report["summary"]["chains_fail"]
                                              or report["summary"].get("gap_correctness_errors") or changed_sources):
                raise CommandError("Evaluation found failures; inspect the saved report.")
