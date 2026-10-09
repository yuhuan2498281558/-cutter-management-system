"""Read-only rule evaluation against independently collected project evidence.

No chat(), memory persistence, or model provider is used. Expected facts are
computed from ORM rows and the engineering contract, never from tool results.
Real inventories/reports belong in the caller's output directory, not Git.
"""
from __future__ import annotations

import json
import logging
import hashlib
import math
import re
import time
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from django.db import connections, transaction
from django.db.models import Count
from application.ai_assistant.evaluation.answer_checks import check_answer

from application.shield.models import (
    NewToolRecord, OldToolRecord, ProjectInfo, ShieldTunnelingData,
    StratumBasicInfo, ToolChangeDetail, ToolCost, ToolInfo, ToolInstance,
    WarehouseOpeningBasicInfo,
)


SCHEMA_VERSION = 2
SCOPE_KEYS = ("tool_type", "ring_range", "cutter_position_no")
TOOL_NAMES = (
    "query_tool_change_data", "query_stratum_data", "query_opening_records",
    "query_cutter_position_stats", "query_tool_change_trend",
    "compare_manufacturer_performance", "query_tunneling_summary",
    "query_tunneling_trend", "query_tunneling_anomaly",
    "query_tunneling_wear_correlation", "analyze_stratum_wear_correlation",
    "query_position_stratum_impact", "calculate_tool_performance", "recommend_tools",
)


@contextmanager
def readonly_database(using="default", timeout_ms=15000):
    connection = connections[using]
    if connection.vendor != "postgresql":
        raise ValueError("Current-data evaluation requires PostgreSQL READ ONLY transactions.")
    if connection.in_atomic_block:
        raise ValueError("Start evaluation outside an existing database transaction.")
    with transaction.atomic(using=using):
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SELECT set_config('statement_timeout', %s, true)",
                           [str(max(100, min(int(timeout_ms), 120000)))])
            cursor.execute("SHOW transaction_read_only")
            if cursor.fetchone()[0] != "on":
                raise RuntimeError("The database did not enable read-only mode.")
        yield


def normalize_position(value):
    value = str(value or "").strip().upper()
    if value.isdigit():
        return str(int(value))
    return value


def valid_detail(row):
    """Independent expression of the 122-position/type business invariant."""
    position = normalize_position(row.get("cutter_position_no"))
    kind = str(row.get("tool_parent_type") or "").strip().upper()
    disc = (position.isdigit() and 1 <= int(position) <= 79) or position in {
        "80A", "80B", "Y1", "Y3", "Y5",
    }
    scraper = re.fullmatch(r"S([1-9]|1[0-9])[LR]", position) is not None
    return (disc and kind == "DISC") or (scraper and kind == "SCRAPER")


def ring_number(value):
    value = str(value or "").strip()
    return int(value) if re.fullmatch(r"\d+", value) else None


def bounded_rows(query, fields, limit):
    rows = list(query.values(*fields)[:limit + 1])
    if len(rows) > limit:
        raise ValueError(f"Oracle row limit exceeded ({limit}); refusing a partial-data score.")
    return rows


@dataclass
class ProjectEvidence:
    project_id: str
    details: list[dict]
    openings: list[dict]
    strata: list[dict]
    tunneling: list[dict]
    lifecycle_samples: dict = field(default_factory=dict)
    catalog: dict = field(default_factory=dict)
    repair_states: dict = field(default_factory=dict)

    @property
    def active_details(self):
        return [row for row in self.details if valid_detail(row)]

    @property
    def latest_ring(self):
        # Project progress comes from openings, not the preloaded geology plan.
        return max((ring_number(row["ring_no"]) or 0 for row in self.openings), default=0)

    @property
    def first_ring(self):
        rings = [ring_number(row["ring_no"]) for row in self.openings]
        return min((ring for ring in rings if ring is not None), default=1)

    def inventory(self):
        active = self.active_details
        observed = [row for row in active if row["is_checked"] or row["is_replaced"]]
        tunnel_rings = sorted({ring_number(row["ring_no"]) for row in self.tunneling}
                              - {None})
        return {
            "project_id": self.project_id,
            "details": {"raw": len(self.details), "active_position_rows": len(active),
                        "observed": len(observed), "replaced": sum(row["is_replaced"] for row in observed),
                        "uninspected_active_rows": sum(not row["is_checked"] and not row["is_replaced"] for row in active),
                        "observed_by_type": dict(Counter(row["tool_parent_type"] for row in observed))},
            "openings": {"count": len(self.openings), "first_ring": self.first_ring,
                         "latest_ring": self.latest_ring,
                         "summary_statuses": dict(Counter(row["summary_status"] for row in self.openings))},
            "strata": {"count": len(self.strata)},
            "tunneling": {"count": len(self.tunneling), "ring_count": len(tunnel_rings),
                          "ring_range": [min(tunnel_rings), max(tunnel_rings)] if tunnel_rings else [],
                          "cross_ring_trend_available": len(tunnel_rings) > 1},
            "repair_states": self.repair_states,
            "lifecycle_sample_statuses": sorted(self.lifecycle_samples),
            "global_catalog_not_project_cost": self.catalog,
        }


def collect_evidence(project_id, row_limit=100000):
    if not ProjectInfo.objects.filter(project_id=project_id).exists():
        raise ValueError("Project ID does not exist; no implicit project fallback is allowed.")
    details = bounded_rows(ToolChangeDetail.objects.filter(warehouse__project__project_id=project_id)
        .order_by("id"), ["id", "warehouse_id", "warehouse__ring_no", "cutter_position_no",
                          "tool_parent_type", "is_checked", "is_replaced", "manufacturer", "price"], row_limit)
    openings = bounded_rows(WarehouseOpeningBasicInfo.objects.filter(project__project_id=project_id)
        .order_by("id"), ["id", "ring_no", "shield_model_id", "summary_status", "checked_tool_count",
                          "replaced_tool_count", "rings_between_openings", "opening_duration"], row_limit)
    strata = bounded_rows(StratumBasicInfo.objects.filter(project__project_id=project_id).order_by("id"),
                          ["ring_no", "stratum_type_codes"], row_limit)
    tunneling = bounded_rows(ShieldTunnelingData.objects.filter(project__project_id=project_id).order_by("id"),
                             ["ring_no", "thrust", "torque", "cutterhead_speed", "penetration"], row_limit)
    states = dict(OldToolRecord.objects.filter(tool_change_detail__warehouse__project__project_id=project_id)
                  .values("inspection_status").annotate(n=Count("id")).values_list("inspection_status", "n"))
    # Catalog costs are global/model-level; never relabel them project expenditure.
    catalog = {"tool_models": ToolInfo.objects.count(), "cost_rows": ToolCost.objects.count(),
               "nonzero_inventory_rows": ToolCost.objects.exclude(inventory=0).count(),
               "cost_types": dict(ToolCost.objects.values("cost_type").annotate(n=Count("id"))
                                  .values_list("cost_type", "n")),
               "instance_statuses": dict(ToolInstance.objects.values("status").annotate(n=Count("id"))
                                          .values_list("status", "n"))}
    evidence = ProjectEvidence(project_id, details, openings, strata, tunneling,
                               catalog=catalog, repair_states=states)
    active_ids = [row["id"] for row in evidence.active_details if row["is_checked"] or row["is_replaced"]]
    for status in ("INSTALLED", "REMOVED_PENDING_INSPECTION", "INSPECTED", "REPAIRED_CLOSED", "SCRAPPED"):
        sample = NewToolRecord.objects.filter(tool_change_detail_id__in=active_ids, tool_instance__status=status)
        sample = sample.exclude(tool_change_detail__tool_number__isnull=True).exclude(tool_change_detail__tool_number="")
        sample = sample.order_by("id").values("tool_change_detail__tool_number", "tool_change_detail__warehouse__ring_no",
                                             "tool_instance__status").first()
        if sample:
            evidence.lifecycle_samples[status] = {
                "tool_number": sample["tool_change_detail__tool_number"],
                "install_ring_no": ring_number(sample["tool_change_detail__warehouse__ring_no"]),
                "lifecycle_status": sample["tool_instance__status"],
            }
    return evidence


@dataclass
class QuestionCase:
    id: str
    category: str
    question: str
    tool: str | None
    params: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    gap: str = ""
    expected_slots: dict | None = None
    expected_branch: str | None = None


def build_cases(evidence):
    first, last = evidence.first_ring, evidence.latest_ring
    recent = [max(1, last - 99), last]
    full = [first, last]
    empty = [last + 1, last + 50]
    cases = []

    def add(case_id, category, question, tool, **params):
        cases.append(QuestionCase(case_id, category, question, tool, params))

    change = "query_tool_change_data"
    add("change_all", "change", "统计当前项目全部刀具换刀情况", change)
    add("change_disc", "change", "统计当前项目滚刀换刀情况", change, tool_type="DISC")
    add("change_scraper", "change", "统计当前项目刮刀换刀情况", change, tool_type="SCRAPER")
    add("change_recent", "ring", "统计最近100环换刀情况", change, ring_range=recent)
    add("change_range", "ring", f"统计{first}环到{last}环换刀情况", change, ring_range=full)
    add("change_single_ring", "ring", f"统计第{first}环换刀情况", change, ring_range=[first, first])
    add("change_empty_window", "empty", f"统计{empty[0]}环到{empty[1]}环换刀情况", change, ring_range=empty)
    add("change_inactive_type", "boundary", "统计撕裂刀换刀情况", change, tool_type="RIPPER")
    for position in ("1", "79", "80A", "80B", "Y1", "Y3", "S1L", "S19R", "G3R", "Y2", "S20L", "s1l"):
        add(f"position_{position}", "position", f"查询刀位{position}的换刀情况", change,
            cutter_position_no=normalize_position(position))
    for label, kind in (("all", None), ("disc", "DISC"), ("scraper", "SCRAPER")):
        word = {None: "", "DISC": "滚刀", "SCRAPER": "刮刀"}[kind]
        add(f"ranking_{label}", "ranking", f"哪些{word}刀位更换最频繁", "query_cutter_position_stats",
            **({"tool_type": kind} if kind else {}))
    opening = "query_opening_records"
    add("opening_all", "opening", "当前项目总共有多少次开仓", opening)
    add("opening_recent3", "opening", "最近3次开仓情况", opening, limit=3)
    add("opening_latest", "opening", "最近1次开仓检查数与更换数是多少", opening, limit=1)
    add("opening_window", "opening", f"{first}环到{last}环的开仓情况", opening, ring_range=full)
    add("opening_empty", "empty", f"{empty[0]}环到{empty[1]}环的开仓情况", opening, ring_range=empty)
    trend = "query_tool_change_trend"
    add("trend_50", "trend", "按50环为一段统计换刀趋势", trend, interval=50)
    add("trend_100", "trend", "按100环为一段统计换刀趋势", trend, interval=100)
    add("trend_disc", "trend", "按100环为一段统计滚刀换刀趋势", trend, tool_type="DISC", interval=100)
    add("trend_window", "trend", f"按50环为一段统计{first}环到{last}环换刀趋势", trend,
        ring_range=full, interval=50)
    for word, kind in (("全部", None), ("滚刀", "DISC"), ("刮刀", "SCRAPER")):
        add(f"manufacturer_{kind or 'all'}", "manufacturer", f"对比各厂家{word}刀具性能表现",
            "compare_manufacturer_performance", **({"tool_type": kind} if kind else {}))
    for word, kind in (("滚刀", "DISC"), ("刮刀", "SCRAPER")):
        add(f"manufacturer_{kind}_natural", "manufacturer", f"对比各厂家{word}性能表现",
            "compare_manufacturer_performance", tool_type=kind)
    add("strata_all", "strata", "当前项目地层类型分布", "query_stratum_data")
    add("strata_window", "strata", f"{first}环到{last}环地层类型分布", "query_stratum_data", ring_range=full)
    geology_end = max((ring_number(row["ring_no"]) or 0 for row in evidence.strata), default=last)
    add("strata_empty", "empty", f"{geology_end+1}环到{geology_end+10}环地层类型分布",
        "query_stratum_data", ring_range=[geology_end+1, geology_end+10])
    tunnel_rings = sorted({ring_number(row["ring_no"]) for row in evidence.tunneling} - {None})
    ring = tunnel_rings[0] if tunnel_rings else first
    add("tunneling_summary", "tunneling", f"第{ring}环掘进参数概览", "query_tunneling_summary", ring_range=[ring, ring])
    add("tunneling_segments", "tunneling", f"第{ring}环掘进参数趋势怎么样", "query_tunneling_trend", ring_range=[ring, ring])
    add("tunneling_anomaly", "tunneling", f"第{ring}环掘进参数有异常吗", "query_tunneling_anomaly", ring_range=[ring, ring])
    missing_ring = max(tunnel_rings, default=first) + 1
    add("tunneling_empty", "empty", f"第{missing_ring}环掘进参数概览", "query_tunneling_summary",
        ring_range=[missing_ring, missing_ring])
    for status in ("INSTALLED", "REMOVED_PENDING_INSPECTION", "INSPECTED", "REPAIRED_CLOSED", "SCRAPPED"):
        sample = evidence.lifecycle_samples.get(status)
        cases.append(QuestionCase(f"lifecycle_{status}", "lifecycle",
            f"查询刀具{sample['tool_number']}的服役追溯" if sample else f"查询{status}状态刀具的服役追溯",
            "calculate_tool_performance", {"tool_numbers": [sample["tool_number"]]} if sample else {},
            gap="当前项目没有该状态且有安装关系的样本" if not sample else ""))
    for case_id, category, question, reason in [
        ("repair_pending_total", "repair", "待厂家反馈的旧刀共有多少把", "有旧刀状态数据，尚无返修状态汇总规则工具"),
        ("repair_closed_total", "repair", "已归档的旧刀维修费用总额是多少", "尚无按返修归档状态聚合费用的规则工具"),
        ("confirmed_openings", "opening_status", "只统计已确认开仓，排除草稿", "开仓工具展示确认来源，但尚无summary_status筛选契约"),
        ("cost_project_total", "cost", "当前项目实际刀具采购加返修总成本是多少", "全局型号成本表不能替代项目实际支出台账，尚无对应规则工具"),
        ("inventory_available", "inventory", "仓库现在可用滚刀库存多少把", "inventory字段存在但当前全零，助手没有库存台账工具，不能认定真实库存为零"),
        ("cross_ring_tunneling", "tunneling_coverage", "分析最近100环掘进参数的跨环变化", "需至少两个环号的掘进记录；当前inventory会单独报告是否具备，未验证跨环趋势算法"),
        ("strata_wear_association", "stratum_wear", "分析地层类型和刀具磨损之间的关联", "规则工具存在，但本套件尚无独立关联统计真值；地层分布与换刀总量通过不代表关联结论已验证"),
        ("position_strata_association", "position_stratum", "分析刀位S1L在不同地层下的磨损差异", "规则工具存在，但本套件尚无刀位与地层关联的独立真值"),
        ("tunneling_wear_association", "tunneling_correlation", "掘进参数变化是否导致刀具异常磨损", "现有单环掘进记录不能证明因果，关联工具未纳入独立真值评分"),
        ("tool_recommendation", "recommendation", "根据完整服役记录推荐适合当前地层的刀具", "推荐工具存在，但需要独立核对服役终点、右删失与样本下限，当前套件不把建议文案计为通过"),
    ]:
        cases.append(QuestionCase(case_id, category, question, None, gap=reason))
    return cases


def selected_details(evidence, params, observed=True):
    rows = evidence.active_details
    if observed:
        rows = [row for row in rows if row["is_checked"] or row["is_replaced"]]
    if params.get("tool_type"):
        rows = [row for row in rows if str(row["tool_parent_type"]).strip().upper() == params["tool_type"]]
    if params.get("cutter_position_no"):
        rows = [row for row in rows if normalize_position(row["cutter_position_no"]) == params["cutter_position_no"]]
    if params.get("ring_range"):
        low, high = params["ring_range"]
        rows = [row for row in rows if ring_number(row["warehouse__ring_no"]) is not None
                and low <= ring_number(row["warehouse__ring_no"]) <= high]
    return rows


def selected_rings(rows, params):
    if not params.get("ring_range"):
        return rows
    low, high = params["ring_range"]
    return [row for row in rows if ring_number(row["ring_no"]) is not None
            and low <= ring_number(row["ring_no"]) <= high]


def expected_facts(evidence, case):
    """No import of application.ai_assistant.tools belongs in this oracle."""
    params, name = case.params, case.tool
    rows = selected_details(evidence, params)
    if name == "query_tool_change_data":
        result = {"total_records": len(rows)}
        if rows:
            result["replaced_count"] = sum(row["is_replaced"] for row in rows)
        return result
    if name == "query_cutter_position_stats":
        return {"total_records" if rows else "total": len(rows),
                "position_replacements": dict(Counter(normalize_position(row["cutter_position_no"])
                                                      for row in rows if row["is_replaced"]))}
    if name == "query_tool_change_trend":
        if not rows:
            return {"total": 0}
        interval = params.get("interval", 50)
        minimum = min(ring_number(row["warehouse__ring_no"]) for row in rows)
        maximum = max(ring_number(row["warehouse__ring_no"]) for row in rows)
        segments = []
        for start in range(minimum, maximum + 1, interval):
            group = [row for row in rows if start <= ring_number(row["warehouse__ring_no"]) < start + interval]
            segments.append({"ring_range": f"{start}-{start+interval-1}", "total": len(group),
                             "replaced": sum(row["is_replaced"] for row in group)})
        return {"interval": interval, "segments": segments}
    if name == "compare_manufacturer_performance":
        rows = [row for row in rows if row["manufacturer"] not in (None, "")]
        result = {"total_records": len(rows)}
        if rows:
            result["manufacturer_count"] = len({row["manufacturer"] for row in rows})
            result["manufacturer_replacements"] = dict(Counter(row["manufacturer"] for row in rows if row["is_replaced"]))
        return result
    if name == "query_stratum_data":
        return {"total_rings": len(selected_rings(evidence.strata, params))}
    if name == "query_opening_records":
        openings = selected_rings(evidence.openings, params)
        if not openings:
            return {"total": 0}
        result = {"total_openings": len(openings), "opening_counts": {}}
        for row in sorted(openings, key=lambda item: ring_number(item["ring_no"]), reverse=True)[:params.get("limit", 10)]:
            details = [item for item in evidence.active_details if item["warehouse_id"] == row["id"]]
            checked = sum(item["is_checked"] for item in details)
            replaced = sum(item["is_replaced"] for item in details)
            confirmed = row["summary_status"] == "CONFIRMED"
            result["opening_counts"][f"{row['ring_no']}:{row['shield_model_id']}"] = {
                "detail_record_count": len(details), "detail_checked_count": checked,
                "detail_replaced_count": replaced, "summary_status": row["summary_status"],
                "tool_change_total": row["checked_tool_count"] if confirmed else checked,
                "tool_change_replaced": row["replaced_tool_count"] if confirmed else replaced,
                "count_source": "confirmed_summary" if confirmed else "detail_draft",
            }
        return result
    if name in {"query_tunneling_summary", "query_tunneling_trend", "query_tunneling_anomaly"}:
        records = selected_rings(evidence.tunneling, params)
        result = {"total_records": len(records)}
        if records and name != "query_tunneling_trend":
            result["metrics"] = {}
            for metric in ("thrust", "torque", "cutterhead_speed", "penetration"):
                values = [row[metric] for row in records if row[metric] is not None]
                result["metrics"][metric] = {"avg": sum(values)/len(values) if values else None,
                                             "min": min(values) if values else None,
                                             "max": max(values) if values else None}
        if records and name == "query_tunneling_trend":
            single_ring = len({ring_number(row["ring_no"]) for row in records}) == 1 and len(records) > 1
            result["summary"] = {"segment_mode": "single_ring_time_segments" if single_ring else "ring_interval"}
        return result
    if name == "calculate_tool_performance":
        number = params["tool_numbers"][0]
        sample = next(sample for sample in evidence.lifecycle_samples.values() if sample["tool_number"] == number)
        return {"lifecycle": sample}
    raise ValueError(f"No independent oracle for tool {name}")


def compare_subset(expected, actual, path=""):
    failures = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path or 'result'} expected object"]
        for key, value in expected.items():
            failures.extend(compare_subset(value, actual.get(key), f"{path}.{key}".strip(".")))
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return [f"{path} length mismatch"]
        for index, value in enumerate(expected):
            failures.extend(compare_subset(value, actual[index], f"{path}[{index}]"))
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or not math.isclose(expected, actual, rel_tol=1e-8, abs_tol=1e-7):
            failures.append(f"{path}: expected {expected}, got {actual}")
    elif expected != actual:
        failures.append(f"{path}: expected {expected!r}, got {actual!r}")
    return failures


def comparable_tool_result(name, data):
    result = dict(data)
    if name == "query_cutter_position_stats":
        result["position_replacements"] = {normalize_position(row["cutter_position_no"]): row["replacement_count"]
                                            for row in data.get("top_positions", [])}
    elif name == "compare_manufacturer_performance":
        result["manufacturer_replacements"] = {row["manufacturer"]: row["replaced_count"]
                                               for row in data.get("manufacturers", [])}
    elif name == "query_opening_records":
        result["opening_counts"] = {f"{row['ring_no']}:{row['shield_model_id']}": row
                                    for row in data.get("recent_records", [])}
    return result


@contextmanager
def rule_runtime():
    from application.ai_assistant import llm_service
    from application.ai_assistant.memory_service import MemoryService
    calls = []
    with ExitStack() as stack:
        for name in ("application.ai_assistant.tools", "application.ai_assistant.llm_service"):
            logger = logging.getLogger(name)
            level = logger.level
            logger.setLevel(logging.WARNING)
            stack.callback(logger.setLevel, level)
        # The guard fails closed if a future route unexpectedly needs an LLM or
        # memory DB. It is not enough to rely on current environment defaults.
        stack.enter_context(patch.object(llm_service.ToolAssistant, "_ensure_llm_runtime",
                                         side_effect=RuntimeError("Evaluation forbids model initialization")))
        stack.enter_context(patch.object(llm_service, "create_chat_model",
                                         side_effect=RuntimeError("Evaluation forbids model provider calls")))
        for method in ("load", "append_turn", "reset", "history_page", "_get_legacy_engine"):
            stack.enter_context(patch.object(MemoryService, method,
                side_effect=RuntimeError("Evaluation forbids memory access")))
        for name in TOOL_NAMES:
            original = getattr(llm_service, name)

            def capture(params_str, _function=original, _name=name):
                result = _function(params_str)
                calls.append({"tool": _name, "params": json.loads(params_str), "result": json.loads(result)})
                return result

            stack.enter_context(patch.object(llm_service, name, side_effect=capture))
        yield llm_service.ToolAssistant(), calls


def prepare_context(assistant, question, snapshot, context):
    if not hasattr(assistant, "_prepare_query_context"):
        raise NotImplementedError("Query memory policy contract _prepare_query_context is not available")
    prepared = assistant._prepare_query_context(question, snapshot, context)
    if not isinstance(prepared, dict):
        raise TypeError("_prepare_query_context must return the working context dict")
    return prepared


def evaluate_case(assistant, calls, evidence, case, snapshot=None):
    from application.ai_assistant.memory_service import MemorySnapshot
    snapshot = snapshot or MemorySnapshot(scope_key="experiment:current-data-evaluation", backend="django")
    context = {"project_id": evidence.project_id, "latest_ring_no": evidence.latest_ring,
               "route_mode": "rule", "require_project": True, **case.context}
    start = time.perf_counter()
    calls.clear()
    row = {"id": case.id, "category": case.category, "question": case.question,
           "expected_tool": case.tool, "expected_params": {"project_id": evidence.project_id, **case.params},
           "status": "coverage_gap" if case.gap else "fail", "failures": [], "coverage_gap": case.gap,
           "correctness_errors": []}
    try:
        if hasattr(assistant, "_prepare_query_context"):
            context = prepare_context(assistant, case.question, snapshot, context)
        elif snapshot.slots:
            raise NotImplementedError("Multi-turn policy unavailable")
        effective_query = context.get("effective_query", case.question)
        result = assistant._direct_route(effective_query, context)
        row["effective_query"] = effective_query
        row["resolved_context_mode"] = context.get("resolved_context_mode")
        row["query_intent"] = context.get("query_spec", {})
        row["rule_branch"] = (result or {}).get("rule_branch")
        row["answer"] = (result or {}).get("answer", "")
        row["effective_slots"] = context.get("memory_slots", {})
        row["tool_calls"] = [{"tool": call["tool"], "params": call["params"]} for call in calls]
        if case.gap:
            if case.id in {"cost_project_total", "inventory_available"} and row["rule_branch"] in {
                "tool_recommendation", "tool_change_summary", "manufacturer", "opening", "change_trend",
            }:
                row["correctness_errors"].append("Unsupported cost/inventory question was answered using unrelated recommendation/statistics")
            return row, context
        if not result or not row["answer"]:
            row["failures"].append("No deterministic answer; model fallback is intentionally not executed")
        if case.expected_branch and row["rule_branch"] != case.expected_branch:
            row["failures"].append(f"Expected rule_branch {case.expected_branch}, got {row['rule_branch']}")
        matching = [call for call in calls if call["tool"] == case.tool]
        if len(matching) != 1:
            row["failures"].append(f"Expected one {case.tool} call; got {len(matching)}")
        else:
            call = matching[0]
            row["failures"].extend(compare_subset(row["expected_params"], call["params"], "params"))
            for key in SCOPE_KEYS:
                if key not in case.params and call["params"].get(key) not in (None, "", []):
                    row["failures"].append(f"Unexpected inherited scope: {key}={call['params'][key]!r}")
            expected = expected_facts(evidence, case)
            scored_expected = dict(expected)
            actual = comparable_tool_result(case.tool, call["result"])
            if call["result"].get("error"):
                row["failures"].append(f"Tool error: {call['result']['error']}")
            if case.tool == "query_cutter_position_stats":
                # Only the returned top-N subset is scored; ties need not have a
                # deterministic order. Every returned count must be correct.
                wanted = scored_expected.pop("position_replacements")
                got = actual.pop("position_replacements")
                if len(got) != min(call["params"].get("top_n", 10), len(wanted)):
                    row["failures"].append("ranking size mismatch")
                for position, count in got.items():
                    row["failures"].extend(compare_subset(wanted.get(position), count, f"ranking.{position}"))
                if got and wanted:
                    threshold = sorted(wanted.values(), reverse=True)[len(got)-1]
                    if min(got.values()) < threshold:
                        row["failures"].append("ranking omits a higher-count position")
            if case.tool == "calculate_tool_performance":
                samples = call["result"].get("tools", [])
                if not any(not compare_subset(expected["lifecycle"], sample) for sample in samples):
                    row["failures"].append("lifecycle identity/status/installation differs from installation relation")
            else:
                row["failures"].extend(compare_subset(scored_expected, actual))
            row["expected_facts"] = expected
            row["output_checks"] = check_answer(case.tool, row["answer"], expected)
            row["failures"].extend(row["output_checks"]["failures"])
            row["data_state"] = "empty" if any(expected.get(key) == 0 for key in ("total", "total_records", "total_rings")) else "available"
        if case.expected_slots is not None:
            if context.get("memory_slots", {}) != case.expected_slots:
                row["failures"].append(f"effective memory slots mismatch: expected {case.expected_slots}")
        row["status"] = "pass" if not row["failures"] else "fail"
    except NotImplementedError as error:
        row["status"] = "coverage_gap"
        row["coverage_gap"] = str(error)
    except Exception as error:
        row["status"] = "fail"
        row["failures"].append(f"{type(error).__name__}: {error}")
    finally:
        row["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 2)
    return row, context


def build_chains(evidence):
    first, last = evidence.first_ring, evidence.latest_ring
    change = "query_tool_change_data"
    window = [first, last]

    def step(case_id, question, params=None, *, mode="auto", clear=None, reset=False, tool=change):
        case = QuestionCase(case_id, "multi_turn", question, tool, params or {},
                            {"context_mode": mode})
        case.expected_branch = {"query_tool_change_trend": "change_trend",
                                "query_tunneling_anomaly": "tunneling_anomaly"}.get(tool)
        if clear:
            case.context["clear_slots"] = clear
        return {"case": case, "reset_before": reset}

    return [
        {"id": "chain_type_switch", "steps": [step("disc", "统计滚刀换刀情况", {"tool_type": "DISC"}),
            step("scraper", "那刮刀呢", {"tool_type": "SCRAPER"}), step("all", "全部刀具呢")]},
        {"id": "chain_clear_range", "steps": [step("range", f"统计{first}环到{last}环换刀情况", {"ring_range": window}),
            step("clear", "取消范围，统计换刀情况")]},
        {"id": "chain_new_question", "steps": [step("scoped", f"统计{first}环到{last}环滚刀换刀情况", {"ring_range": window, "tool_type": "DISC"}),
            step("new", "统计刮刀换刀情况", {"tool_type": "SCRAPER"}, mode="new")]},
        {"id": "chain_position_followup", "steps": [step("left", "刀位S1L换刀情况", {"cutter_position_no": "S1L"}),
            step("right", "那S1R呢", {"cutter_position_no": "S1R"})]},
        {"id": "chain_explicit_continue", "steps": [step("range", f"统计{first}环到{last}环滚刀换刀情况", {"ring_range": window, "tool_type": "DISC"}),
            step("continue", "刮刀换刀情况", {"ring_range": window, "tool_type": "SCRAPER"}, mode="continue")]},
        {"id": "chain_clear_slot_api", "steps": [step("disc", "统计滚刀换刀情况", {"tool_type": "DISC"}),
            step("clear", "换刀情况", clear=["tool_type"], mode="continue")]},
        {"id": "chain_reset", "steps": [step("range", f"统计{first}环到{last}环滚刀换刀情况", {"ring_range": window, "tool_type": "DISC"}),
            step("reset", "统计全部刀具换刀情况", reset=True)]},
        {"id": "chain_independent_same_scope", "steps": [step("position", "刀位S1L换刀情况", {"cutter_position_no": "S1L"}),
            step("independent", "统计当前项目滚刀换刀情况", {"tool_type": "DISC"}, mode="new")]},
        {"id": "chain_trend_interval", "steps": [
            step("trend", "按100环为一段统计滚刀换刀趋势", {"tool_type": "DISC", "interval": 100}, tool="query_tool_change_trend"),
            step("scraper", "那刮刀呢", {"tool_type": "SCRAPER", "interval": 100}, tool="query_tool_change_trend"),
            step("all", "那全部刀具呢", {"interval": 100}, tool="query_tool_change_trend"),
            step("disc_again", "那滚刀呢", {"tool_type": "DISC", "interval": 100}, tool="query_tool_change_trend"),
            step("scraper_again", "那刮刀呢", {"tool_type": "SCRAPER", "interval": 100}, tool="query_tool_change_trend"),
            step("all_after_window", "那全部刀具呢", {"interval": 100}, tool="query_tool_change_trend")]},
        {"id": "chain_tunneling_anomaly_scope", "steps": [
            step("anomaly", "第5环掘进参数有异常吗", {"ring_range": [5, 5]}, tool="query_tunneling_anomaly"),
            step("range", "那400环到500环呢", {"ring_range": [400, 500]}, tool="query_tunneling_anomaly")]},
    ]


def evaluate(evidence):
    from application.ai_assistant.memory_service import MemorySnapshot, StoredMessage, estimate_tokens
    rows, chains = [], []
    with rule_runtime() as (assistant, calls):
        for case in build_cases(evidence):
            try:
                with transaction.atomic():
                    row, _ = evaluate_case(assistant, calls, evidence, case)
            except Exception as error:
                row = {"id": case.id, "category": case.category, "question": case.question,
                       "status": "fail", "failures": [f"Database transaction failed: {type(error).__name__}"],
                       "coverage_gap": ""}
            rows.append(row)
        for chain in build_chains(evidence):
            snapshot = MemorySnapshot(scope_key=f"experiment:{chain['id']}", backend="django")
            results = []
            for step in chain["steps"]:
                if step["reset_before"]:
                    snapshot = MemorySnapshot(scope_key=snapshot.scope_key, backend="django", generation=snapshot.generation+1)
                case = step["case"]
                if not hasattr(assistant, "_prepare_query_context"):
                    case.gap = "Multi-turn _prepare_query_context contract not available"
                try:
                    with transaction.atomic():
                        row, context = evaluate_case(assistant, calls, evidence, case, snapshot)
                except Exception as error:
                    row = {"id": case.id, "question": case.question, "status": "fail",
                           "failures": [f"Database transaction failed: {type(error).__name__}"], "coverage_gap": ""}
                    context = {}
                results.append(row)
                snapshot.slots = dict(context.get("memory_slots", {}))
                sequence = snapshot.last_sequence
                snapshot.messages = (snapshot.messages + [
                    StoredMessage(sequence + 1, "human", case.question, estimate_tokens(case.question),
                                  metadata={"query_intent": dict(context.get("query_spec", {}))}),
                    StoredMessage(sequence + 2, "ai", row.get("answer", ""), estimate_tokens(row.get("answer", "")),
                                  metadata={"query_intent": dict(context.get("query_spec", {}))}),
                ])[-6:]
                snapshot.latest_sequence = sequence + 2
            states = {row["status"] for row in results}
            chains.append({"id": chain["id"], "status": "fail" if "fail" in states else (
                "coverage_gap" if "coverage_gap" in states else "pass"), "steps": results,
                "reset_scope": "in-memory reset semantics only; persistent reset is covered by separate storage tests"})
    counts = Counter(row["status"] for row in rows)
    chain_counts = Counter(row["status"] for row in chains)
    return {"schema_version": SCHEMA_VERSION, "inventory": evidence.inventory(),
            "legacy_question_sets": legacy_question_sets(),
            "method": {"path": "rule dispatcher + real read-only tools; no HTTP/SSE/model/memory IO",
                       "oracle": "independent ORM rows + explicit 122-position/type/inspection contract",
                       "limits": ["Scores structured facts, scope, table integrity, and trend/manufacturer answer counts; does not prove every prose claim",
                                  "Multi-turn resets are in-memory; database reset races belong to storage tests",
                                  "Unsupported or unavailable scenarios are coverage gaps, excluded from pass denominator"]},
            "summary": {"independent_cases": len(rows), "pass": counts["pass"], "fail": counts["fail"],
                        "coverage_gaps": counts["coverage_gap"], "multi_turn_chains": len(chains),
                        "gap_correctness_errors": sum(bool(row.get("correctness_errors")) for row in rows),
                        "chains_pass": chain_counts["pass"], "chains_fail": chain_counts["fail"],
                        "chains_coverage_gaps": chain_counts["coverage_gap"]},
            "cases": rows, "chains": chains}


def legacy_question_sets():
    """Record existing paper-suite provenance without importing its old truth."""
    folder = Path(__file__).resolve().parents[1]
    result = []
    for filename in ("question_bank.json", "question_bank_v2.json", "question_bank_v3.json", "new_cases.json"):
        path = folder / filename
        if not path.exists():
            continue
        raw = path.read_bytes()
        try:
            cases = json.loads(raw.decode("utf-8-sig"))
            categories = dict(Counter(item.get("category", "unspecified") for item in cases if isinstance(item, dict)))
            count = len(cases)
        except (UnicodeError, ValueError, TypeError):
            categories, count = {}, None
        result.append({"file": filename, "case_count": count, "categories": categories,
                       "sha256": hashlib.sha256(raw).hexdigest(), "evaluated_in_this_run": False,
                       "changed_by_this_command": False})
    return result


def markdown_report(report):
    summary = report["summary"]
    lines = ["# 当前数据智能助手只读评测", "", f"项目：`{report['inventory']['project_id']}`", "",
             f"独立题 {summary['independent_cases']}：通过 {summary['pass']}、失败 {summary['fail']}、覆盖缺口 {summary['coverage_gaps']}。",
             f"覆盖缺口中另有 {summary['gap_correctness_errors']} 题出现答非所问等正确性错误。",
             f"多轮链 {summary['multi_turn_chains']}：通过 {summary['chains_pass']}、失败 {summary['chains_fail']}、覆盖缺口 {summary['chains_coverage_gaps']}。", "",
             "覆盖缺口不计通过。检查规则路由、工具范围、结构化事实、表格完整性及换刀趋势/厂家表的独立真值；未调用真实模型、HTTP/SSE、持久记忆，也未逐句证明全部结论。", "",
             "## 数据可用性", "", "```json", json.dumps(report["inventory"], ensure_ascii=False, indent=2), "```", "",
             "## 失败与覆盖缺口", ""]
    for row in report["cases"]:
        if row["status"] != "pass":
            detail = row.get("coverage_gap") or "; ".join(row.get("failures", []))
            if row.get("correctness_errors"):
                detail += "；正确性错误：" + "; ".join(row["correctness_errors"])
            lines.append(f"- **{row['id']} [{row['status']}]** {row['question']} — {detail}")
    for chain in report["chains"]:
        if chain["status"] != "pass":
            lines.append(f"- **{chain['id']} [{chain['status']}]**")
            for row in chain["steps"]:
                if row["status"] != "pass":
                    lines.append(f"  - {row['question']}：{row.get('coverage_gap') or '; '.join(row.get('failures', []))}")
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines.extend(["", "## 独立题清单", "", "| 编号 | 问题 | 结果 |", "| --- | --- | --- |"])
    for row in report["cases"]:
        lines.append(f"| {cell(row['id'])} | {cell(row['question'])} | {cell(row['status'])} |")
    lines.extend(["", "## 连续追问清单", "", "按每条链的顺序提问；各链独立开始。reset 步骤的完整控制参数见 JSON。", ""])
    for chain in report["chains"]:
        lines.extend([f"### {cell(chain['id'])} · {cell(chain['status'])}", ""])
        for index, row in enumerate(chain["steps"], 1):
            scope = json.dumps(row.get("effective_slots", {}), ensure_ascii=False)
            lines.append(f"{index}. {cell(row['question'])} — {cell(row['status'])}；实际条件 `{cell(scope)}`")
        lines.append("")
    lines.extend(["完整参数、独立真值、逐题回答和耗时见同目录 JSON。旧论文题集未覆盖或修改。", ""])
    return "\n".join(lines)
