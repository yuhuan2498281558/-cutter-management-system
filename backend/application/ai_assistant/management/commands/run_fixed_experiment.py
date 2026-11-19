"""V2 固定题实验与同条件对照实验：原始记录与评分分离，不在本命令计算正确率。"""

import copy
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

# sql_agent：只读 SQL 工具 + 书面口径（A0）；agent_bare / hybrid_bare：关回答核对和程序生成表格（A1 / A2）
# hybrid_ungated：完整系统但关闭规则直答的覆盖检查，即改进前的路由
ARMS = ("hybrid", "agent", "hybrid_no_template", "agent_no_check", "sql_agent", "agent_bare", "hybrid_bare", "hybrid_ungated")
FLAGS = ("AI_ABLATE_TOOL_GROUP", "AI_ABLATE_TEMPLATE", "AI_ABLATE_MEMORY", "AI_ABLATE_ANSWER_CHECK", "AI_ABLATE_GENERATED_TABLE",
         "AI_ABLATE_ROUTE_COVERAGE")
SUITES = {"fixed": "fixed_cases.json", "heldout": "heldout_cases.json", "calibration": "calibration_cases.json",
          "heldout2": "heldout2_cases.json", "heldout3": "heldout3_cases.json",
          "heldout4": "heldout4_cases.json"}
TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "cache_hit_tokens")


def now():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_records(directory):
    path = directory / "records.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


@contextmanager
def readonly():
    if connection.vendor != "postgresql":
        raise CommandError("固定实验要求 PostgreSQL 只读事务")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            cursor.execute("SHOW transaction_read_only")
            if cursor.fetchone()[0] != "on":
                raise CommandError("未能开启只读事务")
        yield


def data_fingerprint():
    # 覆盖工具查询及关联标签；只保存摘要，不落盘业务字段值。
    names = ("ProjectInfo", "ShieldMachineBasicInfo", "ToolCategory", "ToolInfo", "ToolCost",
             "WarehouseOpeningBasicInfo", "ToolChangeDetail", "StratumBasicInfo", "ShieldTunnelingData",
             "CutterPositionInfo", "ToolInstance", "NewToolRecord", "OldToolRecord", "MobileToolChangeTask", "OldToolPhoto")
    models = [apps.get_model("shield", name) for name in names] + [apps.get_model("system", "Dictionary")]
    tables = {}
    with readonly():
        for model in models:
            fields = sorted(f.attname for f in model._meta.concrete_fields
                            if f.name not in {"creator", "modifier", "dept_belong_id"})
            digest, count = hashlib.sha256(), 0
            for row in model.objects.order_by(model._meta.pk.name).values_list(*fields).iterator():
                digest.update((json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
                count += 1
            tables[model._meta.db_table] = {"rows": count, "fields": fields, "sha256": digest.hexdigest()}
    return {"sha256": hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest(), "tables": tables}


def git_info():
    root = Path(__file__).resolve().parents[5]
    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True,
                              encoding="utf-8").stdout
    # 未提交的改动和本模块下未跟踪的文件一起算哈希，补丁另存到输出目录
    patch = git("diff", "HEAD", "--", "backend/application/ai_assistant")
    for name in sorted(git("ls-files", "--others", "--exclude-standard", "--", "backend/application/ai_assistant").split()):
        patch += f"\n--- untracked {name}\n" + (root / name).read_text(encoding="utf-8", errors="replace")
    return {"commit": git("rev-parse", "HEAD").strip(), "dirty": bool(git("status", "--porcelain").strip()),
            "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(), "patch": patch}


def project_id(value):
    from application.shield.models import ProjectInfo
    with readonly():
        projects = list(ProjectInfo.objects.values_list("project_id", flat=True))
    if value and value in projects:
        return value
    if not value and len(projects) == 1:
        return str(projects[0])
    raise CommandError("请用 --project 指定存在的项目；仅有一个项目时可省略")


def case_turns(case):
    return [turn if isinstance(turn, str) else turn["question"] for turn in case["turns"]] if case.get("turns") else [case["question"]]


def make_schedule(cases, arms, repeat, seed):
    schedule = [(case, arm, rep) for case in cases for arm in arms for rep in range(repeat)
                if arm != "hybrid_no_template" or case.get("expected_path") == "rule"]
    random.Random(seed).shuffle(schedule)
    return schedule


def arm_environment(arm):
    mode = "agent" if arm.startswith(("agent", "sql")) else "hybrid"
    bare = arm in ("agent_bare", "hybrid_bare")
    return {**dict.fromkeys(FLAGS, "0"), "AI_ABLATE_TEMPLATE": str(int(arm == "hybrid_no_template")),
            "AI_ABLATE_ANSWER_CHECK": str(int(arm == "agent_no_check" or bare)),
            "AI_ABLATE_GENERATED_TABLE": str(int(bare)), "AI_ABLATE_ROUTE_COVERAGE": str(int(arm == "hybrid_ungated")),
            "AI_ASSISTANT_ROUTE_MODE": mode,
            "AI_STRICT_AGENT": "0", "AI_ASSISTANT_POLISH_DIRECT": "0", "AI_TRACE_TOOL_RESULTS": "1"}


class ModelBudgetReached(BaseException):
    pass


class RequestCapture:
    def __init__(self, directory, maximum, offline=False):
        self.path, self.maximum, self.offline = directory / "model_requests.json", maximum, offline
        self.ledger = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
        self.current, self.responses = {}, []

    def before_request(self):
        if len(self.ledger) >= self.maximum:
            raise ModelBudgetReached()
        entry = {"number": len(self.ledger) + 1, **self.current, "started_at": now()}
        self.ledger.append(entry)
        save_json(self.path, self.ledger)
        return entry

    def network(self, original):
        def send(client, request):
            entry = self.before_request()
            try:
                if self.offline:
                    raise httpx.ConnectError("实验模拟模型服务不可用", request=request)
                response = original(client, request)
                entry["http_status"] = response.status_code
                return response
            except Exception as exc:
                entry["error_type"] = type(exc).__name__
                raise
            finally:
                save_json(self.path, self.ledger)
        return send

    def async_network(self, original):
        async def send(client, request):
            entry = self.before_request()
            try:
                if self.offline:
                    raise httpx.ConnectError("实验模拟模型服务不可用", request=request)
                response = await original(client, request)
                entry["http_status"] = response.status_code
                return response
            except Exception as exc:
                entry["error_type"] = type(exc).__name__
                raise
            finally:
                save_json(self.path, self.ledger)
        return send

    def record_response(self, original):
        def record(usage, message, *args, **kwargs):
            metadata = getattr(message, "response_metadata", {}) or {}
            raw, normalized = metadata.get("token_usage") or {}, getattr(message, "usage_metadata", None) or {}
            response = {"model": metadata.get("model_name") or metadata.get("model"),
                                   "prompt_tokens": raw.get("prompt_tokens", normalized.get("input_tokens")),
                                   "completion_tokens": raw.get("completion_tokens", normalized.get("output_tokens")),
                                   "cache_hit_tokens": raw.get("prompt_cache_hit_tokens", (normalized.get("input_token_details") or {}).get("cache_read"))}
            self.responses.append(response)
            self.ledger[-1]["response"] = response
            save_json(self.path, self.ledger)
            return original(usage, message, *args, **kwargs)
        return record

    def usage(self):
        return {key: sum(values) if (values := [r[key] for r in self.responses]) and all(v is not None for v in values) else None for key in TOKEN_KEYS}


class EphemeralPersistence:
    def __init__(self):
        self.snapshots = {}

    def load(self, scope_key, **kwargs):
        from application.ai_assistant.memory_service import MemorySnapshot
        return copy.deepcopy(self.snapshots.get(scope_key) or MemorySnapshot(scope_key=scope_key, backend="legacy", message_count=0))

    def append_turn(self, scope_key, question, answer, slots=None, metadata=None, **kwargs):
        from application.ai_assistant.memory_service import StoredMessage
        from application.ai_assistant.token_estimation import estimate_tokens
        from application.ai_assistant.messages import ToolMessage, message_to_dict
        snapshot = self.load(scope_key)
        sequence = snapshot.last_sequence
        snapshot.messages.extend([StoredMessage(sequence + 1, "human", question, estimate_tokens(question), metadata or {}),
                                  StoredMessage(sequence + 2, "ai", answer, estimate_tokens(answer), metadata or {})])
        snapshot.slots, snapshot.message_count, snapshot.latest_sequence = dict(slots or {}), len(snapshot.messages), sequence + 2
        snapshot.revision += 1
        events = []
        for message in kwargs.get("context_messages") or []:
            payload = {"message": message_to_dict(message)}
            if isinstance(message, ToolMessage):
                payload["sha256"] = hashlib.sha256(message.content.encode("utf-8")).hexdigest()
            events.append(("message", payload))
        if kwargs.get("usage"):
            events.append(("usage", kwargs["usage"]))
        if events:
            events.append(("turn_commit", {"sequences": [sequence + 1, sequence + 2]}))
            snapshot.context_events.append({"project_id": (metadata or {}).get("project_id", ""), "events": [
                {"schema_version": 1, "kind": kind, "payload": json.dumps(payload, ensure_ascii=False)} for kind, payload in events]})
        self.snapshots[scope_key] = snapshot
        return copy.deepcopy(snapshot)

    def append_compaction(self, snapshot, project_id, payload):
        from application.ai_assistant.context_events import ContextEventStore
        snapshot = copy.deepcopy(snapshot)
        snapshot.context_events.append(ContextEventStore.compaction_turn(snapshot.scope_key, snapshot.generation, project_id, payload))
        self.snapshots[snapshot.scope_key] = snapshot
        return copy.deepcopy(snapshot)

    def restore(self, value):
        from application.ai_assistant.memory_service import MemorySnapshot, StoredMessage
        value = copy.deepcopy(value)
        value["messages"] = [StoredMessage(**item) for item in value["messages"]]
        self.snapshots[value["scope_key"]] = MemorySnapshot(**value)


def estimate(cases, arms, records):
    lines = ["组 | 题型 | 试跑条数 | 每条请求 | 每条输入 token | 每条输出 token | 完整实验请求数 | 完整实验 token"]
    total_calls, total_tokens = 0, 0
    for arm in arms:
        for kind in ("quick", "model", "probe"):
            count = sum(len(case_turns(c)) * 5 for c in cases if c["kind"] == kind
                        and (arm != "hybrid_no_template" or c["expected_path"] == "rule"))
            if not count:
                continue
            rows = [r for r in records if r["arm"] == arm and r["kind"] == kind and r["case_id"] in {c["id"] for c in cases}]
            values = [[r["model_requests"] for r in rows]] + [
                [r["provider_usage"].get(key) if r["model_requests"] else 0 for r in rows] for key in TOKEN_KEYS[:2]]
            means = [sum(v) / len(v) if v and all(x is not None for x in v) else None for v in values]
            calls = means[0] * count if means[0] is not None else None
            tokens = sum(means[1:]) * count if all(v is not None for v in means[1:]) else None
            total_calls = total_calls + calls if total_calls is not None and calls is not None else None
            total_tokens = total_tokens + tokens if total_tokens is not None and tokens is not None else None
            fmt = lambda v: "未知" if v is None else f"{v:.2f}"
            lines.append(" | ".join([arm, kind, str(len(rows)), *map(fmt, means), fmt(calls), fmt(tokens)]))
    lines.append(f"合计完整实验请求数：{total_calls}；完整实验 token：{total_tokens}（缺失用量不按零计）")
    return "\n".join(lines)


class Command(BaseCommand):
    help = "运行 V2 固定题同条件实验，保存原始 JSONL；--estimate 仅离线预估"

    def add_arguments(self, parser):
        parser.add_argument("--arm", action="append", choices=ARMS)
        parser.add_argument("--repeat", type=int, default=5)
        parser.add_argument("--kind", action="append", choices=("quick", "model", "probe"))
        parser.add_argument("--case-id", action="append")
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--max-model-calls", required=True, type=int)
        parser.add_argument("--resume", action="store_true")
        parser.add_argument("--seed", type=int, default=20261028)
        parser.add_argument("--allow-dirty", action="store_true")
        parser.add_argument("--project")
        parser.add_argument("--estimate", action="store_true")
        parser.add_argument("--suite", choices=tuple(SUITES), default="fixed")
        parser.add_argument("--offline", action="store_true", help="模拟模型服务不可用，所有模型请求在发送时失败")

    def handle(self, *args, **options):
        from application.ai_assistant.evaluation.fixed_suite import load_fixed_cases
        cases = [c for c in load_fixed_cases(SUITES[options["suite"]]) if (not options["kind"] or c["kind"] in options["kind"])
                 and (not options["case_id"] or c["id"] in options["case_id"])]
        arms = sorted(set(options["arm"] or ARMS), key=ARMS.index)
        directory = Path(options["output_dir"]).resolve()
        if options["estimate"]:
            self.stdout.write(estimate(cases, arms, read_records(directory)))
            return
        if not cases or options["repeat"] < 1 or options["max_model_calls"] < 0:
            raise CommandError("题目不能为空，repeat 必须为正，模型请求上限不能为负")
        from application.ai_assistant.llm_provider import get_llm_config
        code = git_info()
        if code["dirty"] and not options["allow_dirty"]:
            raise CommandError("工作区有未提交改动；确认后用 --allow-dirty 放行")
        project = project_id(options["project"])
        patch_text = code.pop("patch", "")
        signature = {**code, "project_id": project, "configured_model": get_llm_config().model, "arms": arms,
                     "repeat": options["repeat"], "seed": options["seed"], "cases": cases, "suite": options["suite"],
                     "offline": options["offline"], "environments": {arm: arm_environment(arm) for arm in arms}}
        fingerprint = data_fingerprint()
        meta_path = directory / "run_meta.json"
        records = read_records(directory)
        if options["resume"]:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta["signature"] != signature:
                raise CommandError("续跑配置、代码或题单与原实验不一致")
            self.check_fingerprint(meta["data_fingerprint_start"], fingerprint)
        else:
            if meta_path.exists() or records or (directory / "model_requests.json").exists():
                raise CommandError("输出目录已有实验；请用 --resume 或选择空目录")
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "code.patch").write_text(patch_text, encoding="utf-8")
            meta = {**signature, "signature": signature, "run_id": uuid4().hex, "started_at": now(),
                    "data_fingerprint_start": fingerprint, "data_fingerprint_end": None, "arguments": sys.argv[1:],
                    "invocations": []}
        meta["invocations"].append({"started_at": now(), "arguments": sys.argv[1:], "options": options})
        save_json(meta_path, meta)
        capture = RequestCapture(directory, options["max_model_calls"], options["offline"])
        save_json(capture.path, capture.ledger)
        schedule = make_schedule(cases, arms, options["repeat"], options["seed"])
        total = sum(len(case_turns(case)) for case, _, _ in schedule)
        self.stdout.write(f"实验开始：{','.join(arms)} × {len(cases)} 题 × {options['repeat']} 次，模型请求上限 {options['max_model_calls']}，输出 {directory}")
        started, stopped = time.perf_counter(), False
        try:
            self.run_schedule(directory, schedule, records, meta, capture)
        except ModelBudgetReached:
            stopped = True
        finally:
            meta.update(ended_at=now(), data_fingerprint_end=data_fingerprint(), model_requests=len(capture.ledger))
            meta["invocations"][-1].update(ended_at=meta["ended_at"], budget_stopped=stopped)
            save_json(meta_path, meta)
            self.check_fingerprint(meta["data_fingerprint_start"], meta["data_fingerprint_end"])
        if stopped:
            self.stdout.write(f"已达到模型请求上限 {capture.maximum}，停止。已完成 {len(records)}/{total} 条，用 --resume 续跑。")
        else:
            self.stdout.write(f"实验完成：{len(records)} 条，模型请求 {len(capture.ledger)} 次，用时 {(time.perf_counter() - started) / 60:.2f} 分钟。")

    @staticmethod
    def check_fingerprint(start, end):
        if start != end:
            raise CommandError(f"数据指纹与开始时不同，已中止。开始 {start['sha256']}，现在 {end['sha256']}。")

    def run_schedule(self, directory, schedule, records, meta, capture):
        from application.ai_assistant.context_budget import ContextUsage
        from application.ai_assistant.baselines import SqlAgentBaseline
        from application.ai_assistant.llm_service import ToolAssistant
        from application.ai_assistant.views import _build_project_snapshot
        assistant, memory = ToolAssistant(), EphemeralPersistence()
        sql_agent = SqlAgentBaseline() if "sql_agent" in meta["arms"] else None
        sql_history = {}
        done = {(r["case_id"], r["arm"], r["rep"], r["turn"]): r for r in records}
        with ExitStack() as stack, (directory / "records.jsonl").open("a", encoding="utf-8") as sink:
            for name in ("load", "append_turn", "append_compaction"):
                stack.enter_context(patch.object(assistant.memory, name, getattr(memory, name)))
            stack.enter_context(patch.object(assistant.memory, "backend", "legacy"))
            stack.enter_context(patch.object(httpx.Client, "_send_single_request", capture.network(httpx.Client._send_single_request)))
            stack.enter_context(patch.object(httpx.AsyncClient, "_send_single_request", capture.async_network(httpx.AsyncClient._send_single_request)))
            stack.enter_context(patch.object(ContextUsage, "record_response", capture.record_response(ContextUsage.record_response)))
            order = 0
            for case, arm, rep in schedule:
                session = f"{meta['run_id']}::{case['id']}::{arm}::{rep}"
                try:
                    for turn, question in enumerate(case_turns(case)):
                        order += 1
                        key = (case["id"], arm, rep, turn)
                        if key in done:
                            if arm == "sql_agent":
                                sql_history[session] = done[key]["sql_history"]
                            else:
                                memory.restore(done[key]["memory_snapshot"])
                            continue
                        # 上限为 0 时不预停：规则题照常回放，任何模型请求在发送时被拦下
                        if capture.maximum and len(capture.ledger) >= capture.maximum:
                            raise ModelBudgetReached()
                        capture.current = dict(run_id=meta["run_id"], case=case["id"], arm=arm, rep=rep, turn=turn, execution_order=order)
                        capture.responses = []
                        before, started = len(capture.ledger), time.perf_counter()
                        environment = arm_environment(arm)
                        with readonly():
                            context = {**_build_project_snapshot(meta["project_id"]), "project_id": meta["project_id"],
                                       "require_project": True, "user_id": session, "route_mode": environment["AI_ASSISTANT_ROUTE_MODE"],
                                       "focus_sources": case.get("focus_sources", [])}
                            try:
                                with patch.dict(os.environ, environment):
                                    if arm == "sql_agent":
                                        # 与助手相同的项目上下文消息；多轮时带上本会话前几轮的问答
                                        response = sql_agent.chat(question, context={
                                            "project_id": meta["project_id"], "history": sql_history.get(session, []),
                                            "context_message": assistant._build_context_message(context)})
                                        if response.get("success"):
                                            sql_history[session] = sql_history.get(session, []) + [(question, response["answer"])]
                                    else:
                                        response = assistant.chat(question, context=context)
                            except Exception as exc:
                                response = {"success": False, "error": type(exc).__name__, "answer": ""}
                        row = dict(arm=arm, case_id=case["id"], kind=case["kind"], rep=rep, turn=turn, question=question,
                                   answer=response.get("answer", ""), success=response.get("success", False), error=response.get("error"),
                                   route=response.get("route"), route_stage=response.get("route_stage"), rule_branch=response.get("rule_branch"),
                                   rule_declined=response.get("rule_declined"),
                                   tool_calls=[{key: c.get(key) for key in ("tool", "args", "result", "error", "row_count", "truncated") if key in c}
                                               for c in response.get("tool_calls", [])],
                                   latency_ms=round((time.perf_counter() - started) * 1000, 3), model_requests=len(capture.ledger) - before,
                                   provider_usage=capture.usage(), actual_models=sorted({r["model"] for r in capture.responses if r["model"]}) or None,
                                   model_responses=capture.responses, answer_check=response.get("answer_check"), context=response.get("context"),
                                   config={"route_mode": context["route_mode"], **{k: environment[k] for k in FLAGS},
                                           "AI_STRICT_AGENT": "0", "AI_ASSISTANT_POLISH_DIRECT": "0", "memory_backend": "ephemeral_legacy"},
                                   run_id=meta["run_id"], execution_order=order,
                                   run_metadata={k: meta[k] for k in ("commit", "dirty", "seed", "configured_model", "data_fingerprint_start")},
                                   memory_snapshot=None if arm == "sql_agent" else asdict(memory.load(assistant.memory.scope_key(session))),
                                   sql_history=sql_history.get(session, []) if arm == "sql_agent" else None)
                        sink.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                        sink.flush()
                        records.append(row)
                finally:
                    memory.snapshots.clear()
                    sql_history.pop(session, None)
                    assistant._context_cache.clear()
