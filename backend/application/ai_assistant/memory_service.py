"""User-scoped memory storage and context budgeting for the AI assistant.

The service intentionally owns memory orchestration so synchronous and SSE
requests cannot drift into different history semantics again.  Project and
conversation scoping are deliberately deferred; ``scope_key`` is the seam for
that future change.
"""

from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass, field
from typing import Iterable

from django.db import transaction
from django.db.models import F

from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.messages import HumanMessage
from sqlalchemy import create_engine, inspect, text

from .models import AssistantMemoryMessage, AssistantMemoryScope

logger = logging.getLogger(__name__)


_TRUTHY = {"1", "true", "yes", "on"}


def _flag_enabled(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in _TRUTHY


def _int_setting(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def estimate_tokens(text: str) -> int:
    """Conservative provider-neutral token estimate.

    The assistant supports Ollama and OpenAI-compatible providers, so relying
    on a provider tokenizer here would add a deployment-specific dependency.
    The estimate is intentionally conservative for budgeting, not billing.
    """

    if not text:
        return 0
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    non_cjk = len(text) - cjk
    return max(1, math.ceil(cjk * 1.5 + non_cjk / 4))


@dataclass(frozen=True)
class StoredMessage:
    sequence: int
    role: str
    content: str
    token_count: int = 0


@dataclass
class MemorySnapshot:
    scope_key: str
    summary: str = ""
    slots: dict = field(default_factory=dict)
    messages: list[StoredMessage] = field(default_factory=list)
    summary_through_sequence: int = 0
    summary_revision: int = 0
    revision: int = 0
    backend: str = "django"

    @property
    def last_sequence(self) -> int:
        return self.messages[-1].sequence if self.messages else 0


class MemoryService:
    """Read, write and budget one user-level memory scope."""

    def __init__(self, backend: str | None = None):
        # Rollout keeps the legacy store as the safe default.  Set
        # AI_MEMORY_BACKEND=django only after migration and dual-write checks.
        self.backend = (backend or os.environ.get("AI_MEMORY_BACKEND", "legacy")).strip().lower()
        if self.backend not in {"django", "legacy"}:
            logger.warning("未知 AI_MEMORY_BACKEND=%s，回退 legacy", self.backend)
            self.backend = "legacy"
        self.history_db_url = os.environ.get(
            "LANGCHAIN_HISTORY_DB_URL", "sqlite:///langchain_history.db"
        )

    @staticmethod
    def scope_key(user_id: str | int | None) -> str:
        value = str(user_id or "anonymous")
        if value.isdigit():
            return f"user:{value}"
        return f"experiment:{value}"

    @staticmethod
    def legacy_session_id(scope_key: str) -> str:
        if scope_key.startswith("user:"):
            return scope_key.split(":", 1)[1]
        if scope_key.startswith("experiment:"):
            return scope_key.split(":", 1)[1]
        return scope_key

    def _legacy_history(self, scope_key: str) -> SQLChatMessageHistory:
        return SQLChatMessageHistory(
            session_id=self.legacy_session_id(scope_key),
            connection_string=self.history_db_url,
        )

    def _get_scope(self, scope_key: str, owner_id: int | None = None) -> AssistantMemoryScope:
        defaults = {"owner_id": owner_id} if owner_id is not None else {}
        scope, created = AssistantMemoryScope.objects.get_or_create(
            scope_key=scope_key,
            defaults=defaults,
        )
        if owner_id is not None and scope.owner_id is None:
            scope.owner_id = owner_id
            scope.save(update_fields=["owner", "updated_at"])
        return scope

    def load(self, scope_key: str, owner_id: int | None = None) -> MemorySnapshot:
        if self.backend == "legacy":
            history = self._legacy_history(scope_key)
            slots = {}
            stored_messages = []
            for index, message in enumerate(history.messages, start=1):
                if message.type == "human":
                    metadata = getattr(message, "additional_kwargs", {}) or {}
                    saved_slots = metadata.get("memory_slots")
                    if isinstance(saved_slots, dict):
                        slots = dict(saved_slots)
                content = str(message.content or "")
                stored_messages.append(StoredMessage(
                    sequence=index,
                    role="human" if message.type == "human" else "ai",
                    content=content,
                    token_count=estimate_tokens(content),
                ))
            return MemorySnapshot(
                scope_key=scope_key,
                slots=slots,
                messages=stored_messages,
                backend="legacy",
            )

        scope = self._get_scope(scope_key, owner_id=owner_id)
        rows = scope.messages.order_by("sequence").all()
        return MemorySnapshot(
            scope_key=scope_key,
            summary=scope.summary or "",
            slots=dict(scope.slots or {}),
            messages=[
                StoredMessage(
                    sequence=row.sequence,
                    role=row.role,
                    content=row.content,
                    token_count=row.token_count or estimate_tokens(row.content),
                )
                for row in rows
            ],
            summary_through_sequence=scope.summary_through_sequence,
            summary_revision=scope.summary_revision,
            revision=scope.revision,
            backend="django",
        )

    def context_messages(
        self,
        snapshot: MemorySnapshot,
        recent_turns: int | None = None,
        budget: int | None = None,
    ) -> list[StoredMessage]:
        """Return only recent, unsummarized messages inside the memory budget."""

        recent_turns = recent_turns or _int_setting("AI_MEMORY_RECENT_TURNS", 3)
        budget = budget or _int_setting("AI_MEMORY_CONTEXT_TOKEN_BUDGET", 1200)
        eligible = [
            item
            for item in snapshot.messages
            if item.sequence > snapshot.summary_through_sequence
        ]
        max_messages = recent_turns * 2
        eligible = eligible[-max_messages:]

        while eligible and sum(item.token_count for item in eligible) > budget:
            eligible.pop(0)
        return eligible

    def summary_source(self, snapshot: MemorySnapshot, recent_turns: int | None = None) -> list[StoredMessage]:
        recent_turns = recent_turns or _int_setting("AI_MEMORY_RECENT_TURNS", 3)
        cutoff = max(0, snapshot.last_sequence - recent_turns * 2)
        return [
            item
            for item in snapshot.messages
            if snapshot.summary_through_sequence < item.sequence <= cutoff
        ]

    def summary_due(self, snapshot: MemorySnapshot) -> bool:
        if self.backend != "django":
            return False
        source = self.summary_source(snapshot)
        if not source:
            return False
        pending_tokens = sum(item.token_count for item in source)
        trigger = _int_setting("AI_MEMORY_SUMMARY_TRIGGER_TOKENS", 1800)
        return pending_tokens >= trigger

    @staticmethod
    def format_slots(slots: dict) -> str:
        labels = {
            "ring_range": "环号范围",
            "tool_type": "刀具类型",
            "cutter_position_no": "刀位",
        }
        parts = []
        for key, value in (slots or {}).items():
            if value in (None, "", []):
                continue
            label = labels.get(key, key)
            if key == "ring_range" and isinstance(value, (list, tuple)) and len(value) == 2:
                value = f"{value[0]}-{value[1]}"
            parts.append(f"{label}：{value}")
        return "；".join(parts)

    def append_turn(
        self,
        scope_key: str,
        user_content: str,
        ai_content: str,
        slots: dict | None = None,
        owner_id: int | None = None,
        metadata: dict | None = None,
    ) -> MemorySnapshot:
        if not ai_content:
            return self.load(scope_key, owner_id=owner_id)

        if self.backend == "legacy":
            history = self._legacy_history(scope_key)
            history.add_message(HumanMessage(
                content=user_content,
                additional_kwargs={"memory_slots": dict(slots or {})},
            ))
            history.add_ai_message(ai_content)
            if _flag_enabled("AI_MEMORY_DUAL_WRITE"):
                try:
                    self._append_django_turn(
                        scope_key,
                        user_content,
                        ai_content,
                        slots=slots,
                        owner_id=owner_id,
                        metadata=metadata,
                        write_legacy=False,
                    )
                except Exception:
                    logger.exception("AI 记忆 legacy->django 双写失败，scope=%s", scope_key)
            return self.load(scope_key, owner_id=owner_id)

        self._append_django_turn(
            scope_key,
            user_content,
            ai_content,
            slots=slots,
            owner_id=owner_id,
            metadata=metadata,
            write_legacy=True,
        )
        return self.load(scope_key, owner_id=owner_id)

    def _append_django_turn(
        self,
        scope_key: str,
        user_content: str,
        ai_content: str,
        slots: dict | None = None,
        owner_id: int | None = None,
        metadata: dict | None = None,
        write_legacy: bool = True,
    ) -> None:
        metadata = metadata or {}
        with transaction.atomic():
            scope = self._get_scope(scope_key, owner_id=owner_id)
            scope = AssistantMemoryScope.objects.select_for_update().get(pk=scope.pk)
            last = (
                AssistantMemoryMessage.objects.filter(scope=scope)
                .order_by("-sequence")
                .values_list("sequence", flat=True)
                .first()
                or 0
            )
            AssistantMemoryMessage.objects.bulk_create(
                [
                    AssistantMemoryMessage(
                        scope=scope,
                        sequence=last + 1,
                        role=AssistantMemoryMessage.ROLE_HUMAN,
                        content=user_content,
                        token_count=estimate_tokens(user_content),
                        metadata=metadata,
                    ),
                    AssistantMemoryMessage(
                        scope=scope,
                        sequence=last + 2,
                        role=AssistantMemoryMessage.ROLE_AI,
                        content=ai_content,
                        token_count=estimate_tokens(ai_content),
                        metadata=metadata,
                    ),
                ]
            )
            if slots is not None:
                scope.slots = dict(slots)
            scope.revision += 1
            scope.save(update_fields=["slots", "revision", "updated_at"])

        if write_legacy and _flag_enabled("AI_MEMORY_DUAL_WRITE"):
            try:
                legacy = self._legacy_history(scope_key)
                legacy.add_user_message(user_content)
                legacy.add_ai_message(ai_content)
            except Exception:
                logger.exception("AI 记忆双写 legacy 失败，scope=%s", scope_key)

    def save_summary(
        self,
        scope_key: str,
        summary: str,
        through_sequence: int,
        expected_revision: int,
        owner_id: int | None = None,
    ) -> bool:
        if self.backend != "django" or not summary:
            return False
        max_tokens = _int_setting("AI_MEMORY_SUMMARY_TOKEN_BUDGET", 400)
        if estimate_tokens(summary) > max_tokens:
            logger.warning("AI 摘要超过预算，拒绝覆盖 scope=%s", scope_key)
            return False
        with transaction.atomic():
            scope = self._get_scope(scope_key, owner_id=owner_id)
            scope = AssistantMemoryScope.objects.select_for_update().get(pk=scope.pk)
            if scope.revision != expected_revision:
                return False
            if through_sequence <= scope.summary_through_sequence:
                return False
            scope.summary = summary.strip()
            scope.summary_through_sequence = through_sequence
            scope.summary_revision += 1
            scope.revision += 1
            scope.save(
                update_fields=[
                    "summary",
                    "summary_through_sequence",
                    "summary_revision",
                    "revision",
                    "updated_at",
                ]
            )
        return True

    def reset(
        self,
        scope_key: str | None = None,
        owner_id: int | None = None,
        write_legacy: bool = True,
    ) -> None:
        if self.backend == "legacy":
            if scope_key:
                self._legacy_history(scope_key).clear()
            else:
                engine = create_engine(self.history_db_url)
                try:
                    if inspect(engine).has_table("message_store"):
                        with engine.begin() as conn:
                            conn.execute(text("DELETE FROM message_store"))
                finally:
                    engine.dispose()
            if write_legacy and _flag_enabled("AI_MEMORY_DUAL_WRITE"):
                try:
                    MemoryService(backend="django").reset(
                        scope_key,
                        owner_id=owner_id,
                        write_legacy=False,
                    )
                except Exception:
                    logger.exception("AI 记忆 legacy->django reset 双写失败，scope=%s", scope_key)
            return
        if not scope_key:
            with transaction.atomic():
                AssistantMemoryMessage.objects.all().delete()
                AssistantMemoryScope.objects.all().update(
                    slots={},
                    summary="",
                    summary_through_sequence=0,
                    summary_revision=F("summary_revision") + 1,
                    revision=F("revision") + 1,
                )
            if write_legacy and _flag_enabled("AI_MEMORY_DUAL_WRITE"):
                try:
                    engine = create_engine(self.history_db_url)
                    try:
                        if inspect(engine).has_table("message_store"):
                            with engine.begin() as conn:
                                conn.execute(text("DELETE FROM message_store"))
                    finally:
                        engine.dispose()
                except Exception:
                    logger.exception("AI 记忆双写 reset all legacy 失败")
            return
        with transaction.atomic():
            scope = self._get_scope(scope_key, owner_id=owner_id)
            scope = AssistantMemoryScope.objects.select_for_update().get(pk=scope.pk)
            scope.messages.all().delete()
            scope.slots = {}
            scope.summary = ""
            scope.summary_through_sequence = 0
            scope.summary_revision += 1
            scope.revision += 1
            scope.save(
                update_fields=[
                    "slots",
                    "summary",
                    "summary_through_sequence",
                    "summary_revision",
                    "revision",
                    "updated_at",
                ]
            )
        if write_legacy and _flag_enabled("AI_MEMORY_DUAL_WRITE"):
            try:
                self._legacy_history(scope_key).clear()
            except Exception:
                logger.exception("AI 记忆双写 reset legacy 失败，scope=%s", scope_key)


def serialize_messages(messages: Iterable[StoredMessage]) -> list[dict]:
    """Convert stored messages to a JSON-safe diagnostic representation."""

    return [
        {
            "sequence": item.sequence,
            "role": item.role,
            "content": item.content,
            "token_count": item.token_count,
        }
        for item in messages
    ]
