"""Legacy 历史的只追加协议事件；提交和重置由 MemoryService 的事务管理。"""

from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from uuid import uuid4

from .messages import (
    AIMessage, AIMessageChunk, HumanMessage, ToolMessage,
    message_chunk_to_message, message_to_dict, messages_from_dict,
)
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, UniqueConstraint, select
from sqlalchemy.schema import CreateTable

from .agent_loop import tool_messages
from .token_estimation import estimate_tokens

logger = logging.getLogger(__name__)

# 早前结果不小于这个估算量才精简，小结果原样保留
PRUNE_MIN_TOKENS = 1000
PRUNED_MAX_CHARS = 2000
PRUNED_HEADER = "【早前查询结果已精简】明细已移出上下文，需要明细时用相同参数重新查询。保留的汇总：\n"
CHECKPOINT_HEADER = "【早前对话摘要】以下是更早几轮对话的整理，数字照抄自当时的查询结果；需要明细或最新数据时重新查询。\n\n"
CHECKPOINT_REPLY = "好的，我会结合这份摘要和后面的对话原文继续回答。"


def _reduce(value, depth=0):
    if isinstance(value, dict):
        return {key: _reduce(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        if len(value) <= 3 and depth < 3 and all(not isinstance(item, (dict, list)) for item in value):
            return value
        return f"（{len(value)} 条明细已移出上下文）"
    return value


def prune_tool_content(content):
    """早前的大查询结果只留口径和汇总：标量字段照抄，列表换成条数。"""
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        data = None
    if isinstance(data, dict):
        body = json.dumps(_reduce(data), ensure_ascii=False)
        if len(body) > PRUNED_MAX_CHARS:
            body = json.dumps({key: item for key, item in data.items()
                               if not isinstance(item, (dict, list))}, ensure_ascii=False)
    else:
        body = str(content)
    return PRUNED_HEADER + body[:PRUNED_MAX_CHARS]


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
        messages = [HumanMessage(content=enriched_input), *tool_messages(steps), AIMessage(content=answer)]
        return [message_chunk_to_message(item) if isinstance(item, AIMessageChunk) else item for item in messages]

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
    def compaction_turn(cls, scope_key, generation, project_id, payload):
        """一次整理记录（mode 为 prune 或 checkpoint），形状与 load() 返回的轮次相同。"""
        return {"project_id": str(project_id or ""), "events": [dict(
            schema_version=1, event_id=uuid4().hex, scope_key=scope_key, generation=generation,
            turn_id=uuid4().hex, seq=0, kind="compaction", project_id=str(project_id or ""),
            payload=json.dumps(payload, ensure_ascii=False),
            created_at=datetime.now(timezone.utc).isoformat(),
        )]}

    @classmethod
    def append_compaction(cls, connection, turn):
        connection.execute(cls.table.insert(), turn["events"])

    @staticmethod
    def compactions(events):
        """按时间排好的整理记录，附带记录时间 at。"""
        found = [
            {**json.loads(event["payload"]), "at": event["created_at"]}
            for turn in events for event in turn["events"] if event["kind"] == "compaction"
        ]
        return sorted(found, key=lambda item: item["at"])

    @classmethod
    def compaction_bounds(cls, events):
        """（摘要覆盖到的回答序号, 精简覆盖到的回答序号），没有为 0。"""
        found = cls.compactions(events)
        summarized = max((item["through_sequence"] for item in found if item["mode"] == "checkpoint"), default=0)
        return summarized, max((item["through_sequence"] for item in found), default=0)

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

    @classmethod
    def replay(cls, turns, events, project_id):
        committed = {}
        for turn in events:
            for event in turn["events"]:
                if event["kind"] == "turn_commit":
                    committed[tuple(json.loads(event["payload"])["sequences"])] = turn
        compactions = cls.compactions(events)
        checkpoints = [item for item in compactions if item["mode"] == "checkpoint"]
        summarized_through, pruned_through = cls.compaction_bounds(events)
        messages, anchors, used_ids = [], [], set()
        if checkpoints:
            messages += [HumanMessage(content=CHECKPOINT_HEADER + checkpoints[-1]["summary"]),
                         AIMessage(content=CHECKPOINT_REPLY)]
        stats = dict(turns=0, tool_results=0, legacy_qa_turns=0, other_project_turns=0, tokens=0,
                     summarized_turns=0, pruned_results=0)
        for question, answer in turns:
            stats["turns"] += 1
            if answer.sequence <= summarized_through:
                stats["summarized_turns"] += 1
                continue
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
            if answer.sequence <= pruned_through:
                for index, message in enumerate(replayed):
                    if isinstance(message, ToolMessage) and estimate_tokens(message.content) >= PRUNE_MIN_TOKENS:
                        replayed[index] = message.model_copy(update={"content": prune_tool_content(message.content)})
                        stats["pruned_results"] += 1
            # 不发给模型，整理时据此按轮切分历史
            replayed[0].response_metadata["turn_sequence"] = answer.sequence
            stats["tool_results"] += sum(isinstance(message, ToolMessage) for message in replayed)
            messages.extend(replayed)
        last = compactions[-1] if compactions else {}
        stats["compaction"] = {
            "state": "checkpoint" if checkpoints else "pruned" if compactions else "none",
            "checkpoints": len(checkpoints), "pruned_results": stats["pruned_results"],
            "last_at": last.get("at"), "last_before": last.get("before"), "last_after": last.get("after"),
            "through_sequence": summarized_through or None,
        }
        return messages, stats, anchors[-1] if anchors else None
