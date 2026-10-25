"""Legacy 历史的只追加协议事件；提交和重置由 MemoryService 的事务管理。"""

from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from uuid import uuid4

from langchain.agents.format_scratchpad.tools import format_to_tool_messages
from langchain_core.messages import (
    AIMessage, BaseMessageChunk, HumanMessage, ToolMessage,
    message_chunk_to_message, message_to_dict, messages_from_dict,
)
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, UniqueConstraint, select
from sqlalchemy.schema import CreateTable

logger = logging.getLogger(__name__)


class ContextEventStore:
    table = Table(
        "ai_context_events", MetaData(),
        Column("schema_version", Integer, nullable=False),
        Column("event_id", String(32), primary_key=True),
        Column("scope_key", String(255), nullable=False),
        Column("generation", Integer, nullable=False),
        Column("turn_id", String(32), nullable=False),
        Column("seq", Integer, nullable=False),
        Column("kind", String(32), nullable=False),
        Column("project_id", String(255), nullable=False),
        Column("payload", Text, nullable=False),
        Column("created_at", String(40), nullable=False),
        UniqueConstraint("scope_key", "generation", "turn_id", "seq"),
    )

    @classmethod
    def create(cls, connection):
        connection.execute(CreateTable(cls.table, if_not_exists=True))

    @staticmethod
    def turn_messages(enriched_input, answer, steps=()):
        messages = [HumanMessage(content=enriched_input), *format_to_tool_messages(steps), AIMessage(content=answer)]
        return [message_chunk_to_message(item) if isinstance(item, BaseMessageChunk) else item for item in messages]

    @classmethod
    def append(cls, connection, scope_key, generation, project_id, sequences, messages, usage=None):
        turn_id = uuid4().hex
        entries = []
        for message in messages:
            payload = {"message": message_to_dict(message)}
            if isinstance(message, ToolMessage):
                payload["sha256"] = sha256(message.content.encode("utf-8")).hexdigest()
            entries.append(("message", payload))
        if usage is not None:
            entries.append(("usage", usage))
        entries.append(("turn_commit", {"sequences": sequences}))
        connection.execute(cls.table.insert(), [dict(
            schema_version=1, event_id=uuid4().hex, scope_key=scope_key,
            generation=generation, turn_id=turn_id, seq=seq, kind=kind,
            project_id=str(project_id or ""), payload=json.dumps(payload, ensure_ascii=False),
            created_at=datetime.now(timezone.utc).isoformat(),
        ) for seq, (kind, payload) in enumerate(entries)])

    @classmethod
    def load(cls, connection, scope_key, generation):
        rows = connection.execute(select(cls.table).where(
            cls.table.c.scope_key == scope_key, cls.table.c.generation == generation,
        ).order_by(cls.table.c.turn_id, cls.table.c.seq)).mappings()
        turns = {}
        for row in rows:
            turn = turns.setdefault(row["turn_id"], {"project_id": row["project_id"], "events": []})
            turn["events"].append(dict(row))
        return list(turns.values())

    @classmethod
    def clear(cls, connection, scope_key=None):
        statement = cls.table.delete()
        if scope_key is not None:
            statement = statement.where(cls.table.c.scope_key == scope_key)
        connection.execute(statement)

    @staticmethod
    def replay(turns, events, project_id):
        committed = {}
        for turn in events:
            for event in turn["events"]:
                if event["kind"] == "turn_commit":
                    committed[tuple(json.loads(event["payload"])["sequences"])] = turn
        messages, anchors, used_ids = [], [], set()
        stats = dict(turns=0, tool_results=0, legacy_qa_turns=0, other_project_turns=0, tokens=0)
        for question, answer in turns:
            stats["turns"] += 1
            turn = committed.get((question.sequence, answer.sequence))
            saved_project = turn["project_id"] if turn else question.metadata.get("project_id", "")
            other_project = bool(saved_project) and str(saved_project) != str(project_id or "")
            replayed = None
            if turn and not other_project:
                try:
                    payloads = [json.loads(event["payload"]) for event in turn["events"] if event["kind"] == "message"]
                    if any(event["schema_version"] != 1 for event in turn["events"]):
                        raise ValueError("unsupported schema")
                    replayed = messages_from_dict([payload["message"] for payload in payloads])
                    ids, pending = set(), set()
                    if (not replayed or not isinstance(replayed[0], HumanMessage)
                            or not isinstance(replayed[-1], AIMessage) or replayed[-1].tool_calls):
                        raise ValueError("incomplete turn")
                    for message, payload in zip(replayed, payloads):
                        if isinstance(message, AIMessage):
                            if pending:
                                raise ValueError("missing tool result")
                            for call in message.additional_kwargs.get("tool_calls", message.tool_calls):
                                if not call["id"] or call["id"] in ids | used_ids:
                                    raise ValueError("duplicate tool call id")
                                ids.add(call["id"])
                                pending.add(call["id"])
                        elif isinstance(message, ToolMessage):
                            if (message.tool_call_id not in pending or
                                    sha256(message.content.encode("utf-8")).hexdigest() != payload.get("sha256")):
                                raise ValueError("invalid tool result")
                            pending.remove(message.tool_call_id)
                    if pending:
                        raise ValueError("missing tool result")
                    used_ids.update(ids)
                    anchors.extend(json.loads(event["payload"]) for event in turn["events"] if event["kind"] == "usage")
                except (ValueError, KeyError, TypeError):
                    logger.warning("AI 历史工具配对不完整，退回问答，sequence=%s", question.sequence)
                    replayed = None
            if replayed is None:
                text = question.content
                if other_project:
                    text = f"（以下为项目 {saved_project} 的对话，结果不能作为当前项目的证据）\n{text}"
                    stats["other_project_turns"] += 1
                else:
                    stats["legacy_qa_turns"] += 1
                replayed = [HumanMessage(content=text), AIMessage(content=answer.content)]
            stats["tool_results"] += sum(isinstance(message, ToolMessage) for message in replayed)
            messages.extend(replayed)
        return messages, stats, anchors[-1] if anchors else None
