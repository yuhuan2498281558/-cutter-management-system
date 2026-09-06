"""Import LangChain's legacy message_store into Django-managed memory."""

from __future__ import annotations

import json
import os
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sqlalchemy import create_engine, inspect, text

from application.ai_assistant.memory_service import estimate_tokens
from application.ai_assistant.models import AssistantMemoryMessage, AssistantMemoryScope


class Command(BaseCommand):
    help = "把 LangChain message_store 幂等迁移到 Django AI 记忆表"

    def add_arguments(self, parser):
        parser.add_argument("--database-url", default=os.environ.get(
            "LANGCHAIN_HISTORY_DB_URL", "sqlite:///langchain_history.db"
        ))
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--user-id", default="", help="只迁移指定数字 user/session id")
        parser.add_argument(
            "--include-experiment-sessions",
            action="store_true",
            help="同时迁移非数字 session_id，并映射为 experiment:<session_id>",
        )

    def handle(self, *args, **options):
        database_url = options["database_url"]
        engine = create_engine(database_url)
        if not inspect(engine).has_table("message_store"):
            engine.dispose()
            raise CommandError("legacy message_store 不存在：" + database_url)

        requested_user = str(options.get("user_id") or "").strip()
        if requested_user and not requested_user.isdigit():
            raise CommandError("--user-id 必须是数字")

        rows = self._read_rows(engine, requested_user)
        grouped = defaultdict(list)
        stats = {"read": 0, "migrated": 0, "skipped": 0, "failed": 0}
        for row in rows:
            stats["read"] += 1
            session_id = str(row["session_id"])
            if session_id.isdigit():
                scope_key = f"user:{session_id}"
            elif options["include_experiment_sessions"]:
                scope_key = f"experiment:{session_id}"
            else:
                stats["skipped"] += 1
                continue
            try:
                raw_message = row["message"]
                message = json.loads(raw_message) if isinstance(raw_message, str) else raw_message
                role, content = self._decode_message(message)
            except (TypeError, ValueError, KeyError, json.JSONDecodeError):
                stats["failed"] += 1
                self.stderr.write(self.style.WARNING(
                    f"跳过损坏消息 id={row['id']} session={session_id}"
                ))
                continue
            grouped[scope_key].append((int(row["id"]), role, content))

        if options["dry_run"]:
            stats["migrated"] = sum(len(items) for items in grouped.values())
            self._report(stats, grouped, dry_run=True)
            engine.dispose()
            return

        User = get_user_model()
        for scope_key, items in sorted(grouped.items()):
            try:
                with transaction.atomic():
                    owner_id = None
                    if scope_key.startswith("user:"):
                        candidate = int(scope_key.split(":", 1)[1])
                        if User.objects.filter(pk=candidate).exists():
                            owner_id = candidate
                    scope, _ = AssistantMemoryScope.objects.get_or_create(
                        scope_key=scope_key,
                        defaults={"owner_id": owner_id},
                    )
                    existing = set(
                        AssistantMemoryMessage.objects.filter(
                            scope=scope,
                            legacy_message_id__in=[legacy_id for legacy_id, _, _ in items],
                        ).values_list("legacy_message_id", flat=True)
                    )
                    sequence = (
                        AssistantMemoryMessage.objects.filter(scope=scope)
                        .order_by("-sequence")
                        .values_list("sequence", flat=True)
                        .first()
                        or 0
                    )
                    pending = []
                    for legacy_id, role, content in items:
                        if legacy_id in existing:
                            continue
                        sequence += 1
                        pending.append(AssistantMemoryMessage(
                            scope=scope,
                            sequence=sequence,
                            role=role,
                            content=content,
                            token_count=estimate_tokens(content),
                            legacy_message_id=legacy_id,
                            metadata={"source": "langchain_message_store"},
                        ))
                    AssistantMemoryMessage.objects.bulk_create(pending)
                    stats["migrated"] += len(pending)
                    self.stdout.write(f"{scope_key}: final_sequence={sequence}")
            except Exception as exc:
                stats["failed"] += len(items)
                self.stderr.write(self.style.ERROR(f"迁移失败 scope={scope_key}: {exc}"))

        self._report(stats, grouped, dry_run=False)
        engine.dispose()

    @staticmethod
    def _read_rows(engine, requested_user):
        query = "SELECT id, session_id, message FROM message_store"
        params = {}
        if requested_user:
            query += " WHERE session_id = :session_id"
            params["session_id"] = requested_user
        query += " ORDER BY session_id, id"
        with engine.connect() as conn:
            return conn.execute(text(query), params).mappings().all()

    @staticmethod
    def _decode_message(message):
        if not isinstance(message, dict):
            raise ValueError("message 不是对象")
        role = message.get("type") or message.get("data", {}).get("type")
        content = message.get("content")
        if content is None:
            content = message.get("data", {}).get("content")
        if role in {"human", "user"}:
            return AssistantMemoryMessage.ROLE_HUMAN, str(content or "")
        if role in {"ai", "assistant"}:
            return AssistantMemoryMessage.ROLE_AI, str(content or "")
        raise ValueError(f"未知消息角色：{role}")

    def _report(self, stats, grouped, dry_run):
        prefix = "dry-run " if dry_run else ""
        self.stdout.write(
            f"{prefix}读取 {stats['read']}，迁移 {stats['migrated']}，"
            f"跳过 {stats['skipped']}，失败 {stats['failed']}，scope {len(grouped)}"
        )
