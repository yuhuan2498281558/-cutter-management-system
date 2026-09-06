"""User-scoped memory storage and context budgeting for the AI assistant.

The service intentionally owns memory orchestration so synchronous and SSE
requests cannot drift into different history semantics again.  Project and
conversation scoping are deliberately deferred; ``scope_key`` is the seam for
that future change.
"""

from __future__ import annotations

import logging
import json
import math
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterable

from django.db import transaction
from django.db.models import Count, Max

from langchain_core.messages import AIMessage, HumanMessage, message_to_dict
from sqlalchemy import (
    Column, Index, Integer, MetaData, String, Table, Text, create_engine,
    func, insert, select, update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex, CreateTable

from .models import AssistantMemoryMessage, AssistantMemoryScope

logger = logging.getLogger(__name__)


_TRUTHY = {"1", "true", "yes", "on"}

# Keep LangChain's existing table and serialization unchanged. The companion
# table only stores reset generations and the latest structured slots.
_legacy_metadata = MetaData()
_legacy_messages = Table(
    "message_store", _legacy_metadata,
    Column("id", Integer, primary_key=True),
    Column("session_id", String(255)),
    Column("message", Text),
)
_legacy_message_index = Index(
    "ai_memory_message_session_id_idx", _legacy_messages.c.session_id, _legacy_messages.c.id,
)
_legacy_scopes = Table(
    "ai_memory_legacy_scope", _legacy_metadata,
    Column("session_id", String(255), primary_key=True),
    Column("generation", Integer, nullable=False, default=0),
    Column("slots", Text, nullable=True),
)


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
    generation: int = 0
    message_count: int | None = None
    latest_sequence: int = 0
    summary_messages: list[StoredMessage] | None = field(default=None, repr=False)

    @property
    def last_sequence(self) -> int:
        return self.latest_sequence or (self.messages[-1].sequence if self.messages else 0)


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
        self._legacy_engine = None
        self._legacy_engine_lock = threading.Lock()

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

    def _get_legacy_engine(self):
        if self._legacy_engine is None:
            with self._legacy_engine_lock:
                if self._legacy_engine is None:
                    kwargs = {"connect_args": {"timeout": 30}} if self.history_db_url.startswith("sqlite:") else {}
                    engine = create_engine(self.history_db_url, **kwargs)
                    try:
                        with engine.begin() as connection:
                            for table in (_legacy_messages, _legacy_scopes):
                                connection.execute(CreateTable(table, if_not_exists=True))
                            connection.execute(CreateIndex(_legacy_message_index, if_not_exists=True))
                    except Exception:
                        engine.dispose()
                        raise
                    self._legacy_engine = engine
        return self._legacy_engine

    def close(self):
        """Release the optional legacy connection pool (also useful in tests)."""
        if self._legacy_engine is not None:
            self._legacy_engine.dispose()
            self._legacy_engine = None

    @contextmanager
    def _legacy_transaction(self):
        with self._get_legacy_engine().connect() as connection:
            # SQLite ignores SELECT FOR UPDATE. Acquire its write reservation
            # before reading the generation so reset and append serialize.
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @staticmethod
    def _legacy_scope(connection, session_id):
        values = {"session_id": session_id, "generation": 0, "slots": None}
        if connection.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as dialect_insert
            connection.execute(dialect_insert(_legacy_scopes).values(**values).on_conflict_do_nothing())
        elif connection.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as dialect_insert
            connection.execute(dialect_insert(_legacy_scopes).values(**values).on_conflict_do_nothing())
        else:
            try:
                with connection.begin_nested():
                    connection.execute(insert(_legacy_scopes).values(**values))
            except IntegrityError:
                pass
        return connection.execute(
            select(_legacy_scopes).where(_legacy_scopes.c.session_id == session_id).with_for_update()
        ).mappings().one()

    @staticmethod
    def _decode_legacy_rows(rows):
        messages = []
        slots = None
        for row in rows:
            try:
                raw = json.loads(row["message"])
                data = raw.get("data", raw)
                role = raw.get("type") or data.get("type")
                if role not in {"human", "ai"}:
                    continue
                content = str(data.get("content") or "")
                metadata = data.get("additional_kwargs") or {}
                saved_slots = metadata.get("memory_slots")
                if role == "human" and isinstance(saved_slots, dict):
                    slots = dict(saved_slots)
                messages.append(StoredMessage(row["id"], role, content, estimate_tokens(content)))
            except (ValueError, TypeError, AttributeError):
                logger.warning("跳过损坏的 AI 历史记录 id=%s", row["id"])
        return messages, slots

    @staticmethod
    def _stored_rows(rows):
        return [StoredMessage(row.sequence, row.role, row.content,
                              row.token_count or estimate_tokens(row.content)) for row in rows]

    @staticmethod
    def _context_limit():
        return min(100, _int_setting("AI_MEMORY_RECENT_TURNS", 3) * 2)

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
            session_id = self.legacy_session_id(scope_key)
            with self._legacy_transaction() as connection:
                scope = self._legacy_scope(connection, session_id)
                filtered = _legacy_messages.c.session_id == session_id
                count, last = connection.execute(select(
                    func.count(), func.max(_legacy_messages.c.id),
                ).where(filtered)).one()
                rows = list(connection.execute(select(_legacy_messages).where(filtered)
                    .order_by(_legacy_messages.c.id.desc()).limit(self._context_limit())).mappings())
                messages, saved_slots = self._decode_legacy_rows(reversed(rows))
                slots = json.loads(scope["slots"]) if scope["slots"] is not None else saved_slots or {}
                return MemorySnapshot(
                    scope_key=scope_key, slots=slots, messages=messages, backend="legacy",
                    generation=scope["generation"], message_count=count, latest_sequence=last or 0,
                )

        with transaction.atomic():
            scope = self._get_scope(scope_key, owner_id=owner_id)
            scope = AssistantMemoryScope.objects.select_for_update().get(pk=scope.pk)
            stats = scope.messages.aggregate(count=Count("id"), last=Max("sequence"))
            rows = list(scope.messages.order_by("-sequence")[:self._context_limit()])
            return MemorySnapshot(
                scope_key=scope_key, summary=scope.summary or "", slots=dict(scope.slots or {}),
                messages=self._stored_rows(reversed(rows)),
                summary_through_sequence=scope.summary_through_sequence,
                summary_revision=scope.summary_revision, revision=scope.revision,
                backend="django", generation=scope.generation,
                message_count=stats["count"], latest_sequence=stats["last"] or 0,
            )

    def history_page(self, scope_key: str, owner_id: int | None = None, *,
                     before_sequence: int | None = None, limit: int = 50) -> dict:
        """Return an ascending page using a stable, exclusive sequence cursor."""
        limit = max(1, min(int(limit), 100))
        if before_sequence is not None and int(before_sequence) < 1:
            raise ValueError("before_sequence must be positive")
        if self.backend == "legacy":
            session_id = self.legacy_session_id(scope_key)
            with self._legacy_transaction() as connection:
                scope = self._legacy_scope(connection, session_id)
                filtered = _legacy_messages.c.session_id == session_id
                count = connection.scalar(select(func.count()).select_from(_legacy_messages).where(filtered))
                query = select(_legacy_messages).where(filtered)
                if before_sequence is not None:
                    query = query.where(_legacy_messages.c.id < int(before_sequence))
                rows = list(connection.execute(query.order_by(_legacy_messages.c.id.desc())
                                              .limit(limit + 1)).mappings())
                selected = rows[:limit]
                messages, _ = self._decode_legacy_rows(reversed(selected))
                generation = scope["generation"]
                cursor = selected[-1]["id"] if selected else None
        else:
            with transaction.atomic():
                scope = self._get_scope(scope_key, owner_id=owner_id)
                scope = AssistantMemoryScope.objects.select_for_update().get(pk=scope.pk)
                count = scope.messages.count()
                query = scope.messages.all()
                if before_sequence is not None:
                    query = query.filter(sequence__lt=int(before_sequence))
                rows = list(query.order_by("-sequence")[:limit + 1])
                selected = rows[:limit]
                messages = self._stored_rows(reversed(selected))
                generation = scope.generation
                cursor = selected[-1].sequence if selected else None
        has_more = len(rows) > limit
        return {"messages": messages, "message_count": count, "has_more": has_more,
                "next_before_sequence": cursor if has_more else None,
                "generation": generation, "backend": self.backend}

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
        if snapshot.summary_messages is not None:
            return snapshot.summary_messages
        if snapshot.message_count is None:
            candidates = [item for item in snapshot.messages
                          if snapshot.summary_through_sequence < item.sequence <= cutoff]
        elif self.backend == "django" and cutoff > snapshot.summary_through_sequence:
            # Read an incremental batch independently of the six-message chat
            # window. A reset changes generation and makes this batch empty.
            candidates = self._stored_rows(AssistantMemoryMessage.objects.filter(
                scope__scope_key=snapshot.scope_key, scope__generation=snapshot.generation,
                sequence__gt=snapshot.summary_through_sequence, sequence__lte=cutoff,
            ).order_by("sequence")[:200])
        else:
            candidates = []
        budget = min(12000, _int_setting("AI_MEMORY_SUMMARY_SOURCE_TOKEN_BUDGET", 6000))
        selected = []
        used = 0
        for item in candidates:
            if used + item.token_count > budget:
                break
            selected.append(item)
            used += item.token_count
        # Advance a summary watermark only through a complete response.
        while selected and selected[-1].role != "ai":
            selected.pop()
        snapshot.summary_messages = selected
        return selected

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
        expected_generation: int | None = None,
    ) -> MemorySnapshot:
        if not ai_content:
            return self.load(scope_key, owner_id=owner_id)

        mirror = None
        mirror_generation = None
        if _flag_enabled("AI_MEMORY_DUAL_WRITE"):
            try:
                mirror = MemoryService(backend="django" if self.backend == "legacy" else "legacy")
                mirror.history_db_url = self.history_db_url
                # Capture before the primary write. A concurrent reset of the
                # mirror cannot subsequently be undone by this delayed write.
                mirror_generation = mirror._generation(scope_key, owner_id)
            except Exception:
                logger.exception("AI 记忆双写准备失败，scope=%s", scope_key)
                if mirror is not None:
                    mirror.close()
                mirror = None
        try:
            appended = self._append_backend_turn(
                scope_key, user_content, ai_content, slots=slots, owner_id=owner_id,
                metadata=metadata, expected_generation=expected_generation,
            )
            if appended and mirror is not None:
                try:
                    if not mirror._append_backend_turn(
                        scope_key, user_content, ai_content, slots=slots, owner_id=owner_id,
                        metadata=metadata, expected_generation=mirror_generation,
                    ):
                        logger.info("AI 双写因记忆重置跳过，scope=%s", scope_key)
                except Exception:
                    logger.exception("AI 记忆双写失败，scope=%s", scope_key)
        finally:
            if mirror is not None:
                mirror.close()
        return self.load(scope_key, owner_id=owner_id)

    def _generation(self, scope_key, owner_id=None):
        if self.backend == "legacy":
            with self._legacy_transaction() as connection:
                return self._legacy_scope(connection, self.legacy_session_id(scope_key))["generation"]
        return self._get_scope(scope_key, owner_id=owner_id).generation

    def _append_backend_turn(self, scope_key, user_content, ai_content, slots=None,
                             owner_id=None, metadata=None, expected_generation=None):
        if self.backend == "django":
            return self._append_django_turn(
                scope_key, user_content, ai_content, slots=slots, owner_id=owner_id,
                metadata=metadata, expected_generation=expected_generation,
            )
        session_id = self.legacy_session_id(scope_key)
        with self._legacy_transaction() as connection:
            scope = self._legacy_scope(connection, session_id)
            if expected_generation is not None and scope["generation"] != expected_generation:
                return False
            current_slots = slots
            if current_slots is None:
                if scope["slots"] is not None:
                    current_slots = json.loads(scope["slots"])
                else:
                    rows = list(connection.execute(select(_legacy_messages).where(
                        _legacy_messages.c.session_id == session_id,
                    ).order_by(_legacy_messages.c.id.desc()).limit(self._context_limit())).mappings())
                    _, saved_slots = self._decode_legacy_rows(reversed(rows))
                    current_slots = saved_slots or {}
            messages = [HumanMessage(content=user_content, additional_kwargs={
                "memory_slots": dict(current_slots),
            }), AIMessage(content=ai_content)]
            # One transaction owns both inserts and slots, including rollback
            # when the second insert fails. No SQLChat per-message commits.
            connection.execute(insert(_legacy_messages), [{
                "session_id": session_id,
                "message": json.dumps(message_to_dict(message), ensure_ascii=False),
            } for message in messages])
            connection.execute(update(_legacy_scopes).where(
                _legacy_scopes.c.session_id == session_id,
            ).values(slots=json.dumps(current_slots, ensure_ascii=False)))
        return True

    def _append_django_turn(
        self,
        scope_key: str,
        user_content: str,
        ai_content: str,
        slots: dict | None = None,
        owner_id: int | None = None,
        metadata: dict | None = None,
        expected_generation: int | None = None,
    ) -> bool:
        metadata = metadata or {}
        with transaction.atomic():
            scope = self._get_scope(scope_key, owner_id=owner_id)
            scope = AssistantMemoryScope.objects.select_for_update().get(pk=scope.pk)
            if expected_generation is not None and scope.generation != expected_generation:
                return False
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

        return True

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
            with self._legacy_transaction() as connection:
                delete = _legacy_messages.delete()
                change = update(_legacy_scopes)
                if scope_key:
                    session_id = self.legacy_session_id(scope_key)
                    self._legacy_scope(connection, session_id)
                    delete = delete.where(_legacy_messages.c.session_id == session_id)
                    change = change.where(_legacy_scopes.c.session_id == session_id)
                else:
                    # Lock existing scope rows in the same order for reset-all.
                    list(connection.execute(select(_legacy_scopes.c.session_id)
                         .order_by(_legacy_scopes.c.session_id).with_for_update()))
                connection.execute(delete)
                connection.execute(change.values(
                    generation=_legacy_scopes.c.generation + 1, slots="{}",
                ))
        else:
            with transaction.atomic():
                scopes = AssistantMemoryScope.objects.select_for_update().order_by("pk")
                if scope_key:
                    scope = self._get_scope(scope_key, owner_id=owner_id)
                    scopes = scopes.filter(pk=scope.pk)
                for scope in scopes:
                    scope.messages.all().delete()
                    scope.slots = {}
                    scope.summary = ""
                    scope.summary_through_sequence = 0
                    scope.summary_revision += 1
                    scope.revision += 1
                    scope.generation += 1
                    scope.save(update_fields=[
                        "slots", "summary", "summary_through_sequence", "summary_revision",
                        "revision", "generation", "updated_at",
                    ])
        if write_legacy and _flag_enabled("AI_MEMORY_DUAL_WRITE"):
            mirror = MemoryService(backend="django" if self.backend == "legacy" else "legacy")
            mirror.history_db_url = self.history_db_url
            try:
                mirror.reset(scope_key, owner_id=owner_id, write_legacy=False)
            except Exception:
                logger.exception("AI 记忆双写 reset 失败，scope=%s", scope_key)
            finally:
                mirror.close()


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
