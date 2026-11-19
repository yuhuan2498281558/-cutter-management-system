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
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.db import connections, transaction
from django.db.models import Count
from application.ai_assistant.evaluation.answer_checks import check_answer

from application.shield.models import (
    MobileToolChangeTask, NewToolRecord, OldToolRecord, ProjectInfo, ShieldTunnelingData,
    StratumBasicInfo, ToolChangeDetail, ToolCost, ToolInfo, ToolInstance,
    WarehouseOpeningBasicInfo,
)


SCHEMA_VERSION = 3
SCOPE_KEYS = ("tool_type", "ring_range", "cutter_position_no")
TOOL_NAMES = (
    "query_tool_change_data", "query_stratum_data", "query_opening_records",
    "query_cutter_position_stats", "query_tool_change_trend",
    "compare_manufacturer_performance", "query_tunneling_summary",
    "query_tunneling_trend", "query_tunneling_anomaly",
    "query_tunneling_wear_correlation", "analyze_stratum_wear_correlation",
    "query_position_stratum_impact", "calculate_tool_performance", "recommend_tools",
)
_NEW_TOOLS = {
    'query_stratum_area': ('tools_stratum_area', 'stratum_area'),
    'query_opening_stratum': ('tools_stratum_area', 'opening_stratum'),
    'query_tool_inspections': ('tools_inspections', 'tool_inspections'),
    'query_old_tool_repairs': ('tools_repairs', 'old_tool_repairs'),
    'trace_tool_lifecycle': ('tools_lifecycle', 'tool_lifecycle'),
    'compare_manufacturer_service': ('tools_manufacturer', 'manufacturer_service'),
    'query_tool_cost_catalog': ('tools_costs', 'tool_cost_catalog'),
    'query_registered_amounts': ('tools_costs', 'registered_amounts'),
    'query_data_catalog': ('tools_catalog', 'data_catalog'),
}


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
        try:
            yield
        finally:
            transaction.set_rollback(True, using=using)


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
    repairs: list[dict] = field(default_factory=list)
    installations: list[dict] = field(default_factory=list)
    quotes: list[dict] = field(default_factory=list)
    tasks: list[dict] = field(default_factory=list)

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
                          "tool_parent_type", "is_checked", "is_replaced", "manufacturer", "price",
                          "check_result", "mobile_status", "replacement_type", "tool_number"], row_limit)
    openings = bounded_rows(WarehouseOpeningBasicInfo.objects.filter(project__project_id=project_id)
        .order_by("id"), ["id", "ring_no", "shield_model_id", "summary_status", "checked_tool_count",
                          "replaced_tool_count", "rings_between_openings", "opening_duration", "open_time"], row_limit)
    strata = bounded_rows(StratumBasicInfo.objects.filter(project__project_id=project_id).order_by("id"),
                          ["ring_no", "stratum_type_codes", "longitudinal_type_ratios", "stratum_type_ratios"], row_limit)
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
    evidence.repairs = bounded_rows(OldToolRecord.objects.filter(
        tool_change_detail__warehouse__project__project_id=project_id).order_by('id'),
        ['id', 'tool_change_detail_id', 'inspection_status', 'disposition', 'repair_price',
         'confirmed_tool_instance_id', 'suggested_tool_instance_id', 'bearing_failed'], row_limit)
    evidence.installations = bounded_rows(NewToolRecord.objects.filter(
        tool_change_detail__warehouse__project__project_id=project_id).order_by('id'),
        ['tool_change_detail_id', 'tool_instance_id', 'tool_instance__tool_uid',
         'tool_instance__status'], row_limit)
    evidence.quotes = bounded_rows(ToolCost.objects.order_by('id'),
        ['tool_info_id', 'tool_info__tool_parent_type', 'tool_info__tool_type_name',
         'tool_info__tool_type_code', 'manufacturer', 'cost_type', 'unit_price'], row_limit)
    evidence.tasks = bounded_rows(MobileToolChangeTask.objects.filter(
        warehouse__project__project_id=project_id).order_by('id'), ['warehouse_id', 'status'], row_limit)
    active_ids = [row["id"] for row in evidence.active_details if row["is_checked"] or row["is_replaced"]]
    for status in ("INSTALLED", "REMOVED_PENDING_INSPECTION", "INSPECTED", "REPAIRED_CLOSED", "SCRAPPED"):
        sample = NewToolRecord.objects.filter(tool_change_detail_id__in=active_ids, tool_instance__status=status)
        sample = sample.exclude(tool_change_detail__tool_number__isnull=True).exclude(tool_change_detail__tool_number="")
        sample = sample.order_by("id").values("tool_change_detail__tool_number", "tool_change_detail__warehouse__ring_no",
                                             "tool_instance__status", "tool_instance_id",
                                             "tool_instance__tool_uid").first()
        if sample:
            evidence.lifecycle_samples[status] = {
                "tool_number": sample["tool_change_detail__tool_number"],
                "install_ring_no": ring_number(sample["tool_change_detail__warehouse__ring_no"]),
                "lifecycle_status": sample["tool_instance__status"],
                "tool_uid": sample['tool_instance__tool_uid'],
                "instance_id": sample['tool_instance_id'],
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
    manual_review: str = ""


def build_cases(evidence):
    first, last = evidence.first_ring, evidence.latest_ring
    recent = [max(1, last - 99), last]
    full = [first, last]
    empty = [last + 1, last + 50]
    cases = []

    def add(case_id, category, question, tool, **params):
        cases.append(QuestionCase(case_id, category, question, tool, params,
                                 expected_branch=_NEW_TOOLS.get(tool, (None, None))[1]))

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
            "compare_manufacturer_service", **({"tool_type": kind} if kind else {}))
    for word, kind in (("滚刀", "DISC"), ("刮刀", "SCRAPER")):
        add(f"manufacturer_{kind}_natural", "manufacturer", f"对比各厂家{word}性能表现",
            "compare_manufacturer_service", tool_type=kind)
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
            f"追溯刀具{sample['tool_uid']}的安装、拆下和服役环数" if sample else f"查询{status}状态刀具的服役追溯",
            "trace_tool_lifecycle", {"tool_ids": [sample["tool_uid"]]} if sample else {},
            gap="当前项目没有该状态且有安装关系的样本" if not sample else "",
            expected_branch='tool_lifecycle', manual_review='确认配对后的服役环数需人工验收；自动只核身份、状态、安装和拆下环。'))
    sample = evidence.lifecycle_samples.get('INSPECTED') or next(iter(evidence.lifecycle_samples.values()), None)
    cases.append(QuestionCase('lifecycle_uid_natural', 'lifecycle',
        f"{sample['tool_uid']}装在哪、拆下时是第几环、服役多少环" if sample else '按完整刀号查询安装、拆下和服役环数',
        'trace_tool_lifecycle', {'tool_ids': [sample['tool_uid']]} if sample else {},
        expected_branch='tool_lifecycle', gap='' if sample else '当前项目没有可追溯的安装样本',
        manual_review='确认配对后的服役环数需人工验收；自动只核身份、状态、安装和拆下环。'))
    add('repair_pending_total', 'repair', '待厂家反馈的旧刀共有多少把', 'query_old_tool_repairs',
        inspection_status='PENDING_VENDOR_FEEDBACK')
    add('repair_closed_total', 'repair', '已归档的旧刀返修登记金额是多少', 'query_old_tool_repairs', inspection_status='CLOSED')
    add('repair_scrapped', 'repair', '旧刀已报废多少，报废建议多少', 'query_old_tool_repairs')
    add('confirmed_openings', 'opening_status', '只统计已确认开仓，排除草稿', opening, summary_status='CONFIRMED')
    cases[-1].expected_branch = 'opening'
    add('cost_project_total', 'cost', '当前项目实际刀具采购加返修总成本是多少', 'query_registered_amounts')
    add('registered_total', 'cost', '项目一共登记了多少金额', 'query_registered_amounts')
    add('registered_disc', 'cost', '滚刀新装和返修登记金额分别多少', 'query_registered_amounts', tool_type='DISC')
    add('area_boulder', 'area', '第2199环孤石占多少', 'query_stratum_area', rings=[2199], basis='longitudinal_area')
    add('area_window', 'area', '100到300环各地层面积占比', 'query_stratum_area', ring_range=[100, 300], basis='longitudinal_area')
    add('area_cross', 'area', '第100环横断面岩性占比', 'query_stratum_area', rings=[100], basis='cross_section')
    add('opening_stratum_first', 'opening_stratum', f'第{first}环开仓位置是什么地层', 'query_opening_stratum', ring_no=first)
    add('opening_stratum_latest', 'opening_stratum', '上次开仓以来经过了哪些地层', 'query_opening_stratum', recent_openings=1)
    add('inspections_attention', 'inspections', '哪些刀需要关注但还没换', 'query_tool_inspections')
    add('inspections_unchecked', 'inspections', '哪些刀位还没检查', 'query_tool_inspections')
    add('inspections_completion', 'inspections', '各次开仓检查完成情况', 'query_tool_inspections')
    names = sorted({row['manufacturer'] for row in evidence.active_details if row.get('manufacturer')})[:2]
    add('manufacturer_named', 'manufacturer', f"对比{'和'.join(names)}的刀具寿命和异常率", 'compare_manufacturer_service', manufacturers=names)
    add('catalog_new_quotes', 'catalog', '各厂家滚刀新刀报价', 'query_tool_cost_catalog', tool_type='DISC', cost_type='NEW_TOOL')
    add('catalog_repair_quotes', 'catalog', '各厂家维修报价', 'query_tool_cost_catalog', cost_type='REPAIR')
    add('catalog_available', 'catalog', '现在有哪些数据可以查', 'query_data_catalog')
    add('catalog_strata_codes', 'catalog', '有哪些地层编码', 'query_data_catalog')
    for case in cases:
        if case.tool == 'compare_manufacturer_service':
            case.manual_review = '确认配对后的寿命和异常率需人工验收；自动只核候选数、供货数和登记金额。'
    inventory_note = (f"报价库有{evidence.catalog.get('nonzero_inventory_rows', 0)}条非零库存登记；"
                      '库存登记值不是库存台账，无法确认可用库存。')
    tunnel_note = f'当前项目掘进数据覆盖{len(tunnel_rings)}个环号；跨环趋势尚未纳入独立真值验收。'
    for case_id, category, question, reason in [
        ("inventory_available", "inventory", "仓库现在可用滚刀库存多少把", inventory_note),
        ("cross_ring_tunneling", "tunneling_coverage", "分析最近100环掘进参数的跨环变化", tunnel_note),
        ("remaining_life", "lifecycle_prediction", "刀具还有多少剩余寿命", '剩余寿命没有预测验收口径。'),
        ("life_warning", "lifecycle_prediction", "哪些刀需要寿命预警", '寿命预警没有阈值和预测验收口径。'),
        ("strata_wear_association", "stratum_wear", "分析地层类型和刀具磨损之间的关联", "规则工具存在，但本套件尚无独立关联统计真值；地层分布与换刀总量通过不代表关联结论已验证"),
        ("position_strata_association", "position_stratum", "分析刀位S1L在不同地层下的磨损差异", "规则工具存在，但本套件尚无刀位与地层关联的独立真值"),
        ("tunneling_wear_association", "tunneling_correlation", "掘进参数变化是否导致刀具异常磨损", f"当前覆盖{len(tunnel_rings)}个掘进环，不能证明因果；关联工具未纳入独立真值评分"),
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
            segments.append({"ring_range": f"{start}-{min(start+interval-1, maximum)}", "total": len(group),
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
        if params.get('summary_status'):
            openings = [row for row in openings if row['summary_status'] == params['summary_status']]
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
    if name in _NEW_TOOLS:
        return _new_expected_facts(evidence, case)
    raise ValueError(f"No independent oracle for tool {name}")


def _area_facts(rows, basis, requested):
    column = 'longitudinal_type_ratios' if basis == 'longitudinal_area' else 'stratum_type_ratios'
    counts = Counter(ring_number(row['ring_no']) for row in rows)
    valid = []
    for row in rows:
        ratios = row.get(column)
        if counts[ring_number(row['ring_no'])] != 1 or not isinstance(ratios, dict) or not ratios:
            continue
        values = list(ratios.values())
        if any(not isinstance(v, (int, float, Decimal)) or isinstance(v, bool)
               or not math.isfinite(v) or not 0 <= v <= 100 for v in values):
            continue
        if not math.isclose(sum(values), 100, abs_tol=0.01):
            continue
        valid.append(ratios)
    codes = set().union(*(row.keys() for row in valid))
    if basis == 'longitudinal_area':
        codes |= {'AREA_CLAY_SAND', 'AREA_SOFT_HARD', 'AREA_WEAK_GRANITE',
                  'AREA_BEDROCK_PROTRUSION', 'AREA_SOFT_SOIL', 'AREA_BOULDER'}
    classes = {}
    for code in sorted(codes):
        total = sum(float(row.get(code, 0)) for row in valid)
        positive = sum(row.get(code, 0) > 0 for row in valid)
        if basis == 'longitudinal_area' or positive:
            classes[code] = {'positive_ring_count': positive, 'area_equivalent_rings': round(total / 100, 6),
                             'share_pct': round(total / len(valid), 1) if valid else None}
    return {'ring_count_requested': requested, 'ring_count_with_data': len(valid),
            'missing_ring_count': requested - len(valid), 'area_classes': classes}


def _amount(values):
    values = list(values)
    return round(float(sum((Decimal(str(v)) for v in values if v is not None), Decimal('0'))), 2) if (
        not values or any(v is not None for v in values)) else None


def _new_expected_facts(evidence, case):
    params, name = case.params, case.tool
    observed = selected_details(evidence, params)
    replaced = [row for row in observed if row['is_replaced']]
    ids = {row['id'] for row in replaced}
    repairs = [row for row in evidence.repairs if row['tool_change_detail_id'] in ids]
    if name == 'query_old_tool_repairs':
        for key in ('inspection_status', 'disposition'):
            if params.get(key):
                repairs = [row for row in repairs if row[key] == params[key]]
        confirmed = [row for row in repairs if row['inspection_status'] in {'CONFIRMED', 'CLOSED'}]
        pending = [row for row in repairs if row['inspection_status'] == 'PENDING_VENDOR_FEEDBACK']
        return {'summary': {'record_count': len(repairs)},
                'status_counts': {status: sum(row['inspection_status'] == status for row in repairs)
                                  for status in ('PENDING_VENDOR_FEEDBACK', 'CONFIRMED', 'CLOSED')},
                'scrapped_count': sum(row['disposition'] == 'SCRAP' for row in confirmed),
                'scrap_suggestion_count': sum(row['disposition'] == 'SCRAP' for row in pending),
                'registered_repair_amount': {
                    'confirmed_yuan': _amount(row['repair_price'] for row in confirmed),
                    'pending_yuan': _amount(row['repair_price'] for row in pending),
                    'priced_count': sum(row['repair_price'] is not None for row in repairs),
                    'zero_price_count': sum(row['repair_price'] == 0 for row in repairs),
                    'missing_price_count': sum(row['repair_price'] is None for row in repairs)}}
    if name == 'query_registered_amounts':
        installed_ids = {row['tool_change_detail_id'] for row in evidence.installations}
        repair_by_id = {row['tool_change_detail_id']: row for row in repairs}
        installs, confirmed, pending, excluded = [], [], [], 0
        for row in replaced:
            old = repair_by_id.get(row['id'])
            overlap = (row['id'] not in installed_ids and row.get('replacement_type') == 'REPAIR'
                       and row['price'] is not None and old and old['repair_price'] is not None)
            if row['id'] in installed_ids:
                installs.append(row['price'])
            else:
                excluded += 1
            if old:
                if overlap:
                    excluded += 1
                elif old['inspection_status'] in {'CONFIRMED', 'CLOSED'}:
                    confirmed.append(old['repair_price'])
                elif old['inspection_status'] == 'PENDING_VENDOR_FEEDBACK':
                    pending.append(old['repair_price'])
        return {'scope': {'observation_count': len(observed), 'replacement_count': len(replaced),
                          'excluded_cost_source_count': excluded},
                'new_install': {'record_count': len(installs), 'amount_yuan': _amount(installs),
                                'zero_price_count': installs.count(0), 'missing_price_count': installs.count(None)},
                'confirmed_repair': {'record_count': len(confirmed), 'amount_yuan': _amount(confirmed)},
                'pending_repair': {'record_count': len(pending), 'amount_yuan': _amount(pending)},
                'total_registered_cost_yuan': _amount(installs + confirmed)}
    if name == 'query_tool_inspections':
        rows = selected_details(evidence, params, observed=False)
        openings = selected_rings(evidence.openings, params)
        if params.get('recent_openings'):
            openings = sorted(openings, key=lambda r: ring_number(r['ring_no']), reverse=True)[:params['recent_openings']]
        opening_ids = {row['id'] for row in openings}
        rows = [row for row in rows if row['warehouse_id'] in opening_ids
                and (not params.get('check_result') or row['check_result'] == params['check_result'])]
        attention = [row for row in rows if not row['is_replaced'] and row['check_result'] in {'ATTENTION', 'ABNORMAL_NOT_REPLACED'}]
        unchecked = [row for row in rows if not row['is_checked'] and not row['is_replaced']]
        completion = {}
        for opening in openings:
            items = [row for row in rows if row['warehouse_id'] == opening['id']]
            checked = sum(row['is_checked'] or row['is_replaced'] for row in items)
            completion[ring_number(opening['ring_no'])] = {
                'position_count': len(items), 'checked_count': checked, 'unchecked_count': len(items) - checked,
                'replaced_count': sum(row['is_replaced'] for row in items), 'summary_status': opening['summary_status']}
        def group(items):
            return {'record_count': len(items), 'position_count': len({normalize_position(r['cutter_position_no']) for r in items})}
        return {'scope': {'record_count': len(rows), 'opening_count': len(openings)},
                'attention_not_replaced': group(attention), 'unchecked': group(unchecked),
                'completion_counts': completion,
                'mobile_status_counts': dict(Counter(row['mobile_status'] for row in rows)),
                'task_status_counts': dict(Counter(row['status'] for row in evidence.tasks if row['warehouse_id'] in opening_ids))}
    if name == 'query_stratum_area':
        rows = selected_rings(evidence.strata, params)
        if params.get('rings'):
            rows = [row for row in rows if ring_number(row['ring_no']) in params['rings']]
        requested = (len(params['rings']) if params.get('rings') else
                     params['ring_range'][1] - params['ring_range'][0] + 1 if params.get('ring_range') else len(rows))
        return {'basis': params.get('basis', 'longitudinal_area'),
                **_area_facts(rows, params.get('basis', 'longitudinal_area'), requested)}
    if name == 'query_opening_stratum':
        openings = sorted(evidence.openings, key=lambda row: ring_number(row['ring_no']), reverse=True)
        chosen = ([row for row in openings if ring_number(row['ring_no']) == params['ring_no']] if params.get('ring_no')
                  else openings[:params.get('recent_openings', 1)])
        facts = []
        for opening in chosen:
            ring = ring_number(opening['ring_no'])
            previous = max((ring_number(row['ring_no']) for row in openings
                            if row['shield_model_id'] == opening['shield_model_id'] and ring_number(row['ring_no']) < ring), default=None)
            interval = [(previous + 1) if previous is not None else 1, ring]
            strata = selected_rings(evidence.strata, {'ring_range': interval})
            labels = Counter(code.strip() for row in strata for code in set((row['stratum_type_codes'] or '').split(',')) if code.strip())
            facts.append({'ring_no': ring, 'previous_opening_ring': previous, 'interval': interval,
                          'interval_summary': {'legacy_label_ring_counts': dict(labels)}})
        return {'scope': {'opening_count': len(chosen)}, 'openings': facts}
    if name == 'query_tool_cost_catalog':
        rows = evidence.quotes
        for parameter, column in (('tool_type', 'tool_info__tool_parent_type'), ('cost_type', 'cost_type'), ('manufacturer', 'manufacturer')):
            if params.get(parameter):
                rows = [row for row in rows if row[column] == params[parameter]]
        models = {}
        for code in sorted({row['tool_info__tool_type_code'] for row in rows}):
            models[code] = {}
            for kind, prefix in (('NEW_TOOL', 'new_tool'), ('REPAIR', 'repair')):
                quotes = [row for row in rows if row['tool_info__tool_type_code'] == code and row['cost_type'] == kind]
                prices = [row['unit_price'] for row in quotes if row['unit_price'] is not None]
                models[code].update({f'{prefix}_quote_count': len(quotes),
                                    f'{prefix}_price_min_yuan': float(min(prices)) if prices else None,
                                    f'{prefix}_price_max_yuan': float(max(prices)) if prices else None})
        return {'scope': {'quote_count': len(rows), 'model_count': len(models)}, 'model_quotes': models}
    if name == 'compare_manufacturer_service':
        names = params.get('manufacturers')
        supply = {}
        for manufacturer in sorted({row['manufacturer'] or '' for row in replaced}):
            if names and manufacturer not in names:
                continue
            rows = [row for row in replaced if (row['manufacturer'] or '') == manufacturer]
            supply[manufacturer] = {'install_count': len(rows), 'registered_amount_yuan': _amount(row['price'] for row in rows)}
        return {'summary': {'candidate_count': len(replaced)}, 'supply_counts': supply}
    if name == 'trace_tool_lifecycle':
        sample = next(row for row in evidence.lifecycle_samples.values() if row['tool_uid'] == params['tool_ids'][0])
        starts = [row for row in evidence.installations if row['tool_instance_id'] == sample['instance_id']]
        details = {row['id']: row for row in observed}
        openings = {row['id']: row for row in evidence.openings}
        segments = []
        for start in starts:
            install = details.get(start['tool_change_detail_id'])
            if not install:
                continue
            ring = ring_number(install['warehouse__ring_no'])
            machine = openings[install['warehouse_id']]['shield_model_id']
            candidates = [row for row in replaced if ring_number(row['warehouse__ring_no']) > ring
                          and openings[row['warehouse_id']]['shield_model_id'] == machine
                          and normalize_position(row['cutter_position_no']) == normalize_position(install['cutter_position_no'])]
            confirmed_ids = {row['tool_change_detail_id'] for row in evidence.repairs
                             if row['confirmed_tool_instance_id'] == sample['instance_id']}
            candidates += [row for row in replaced if row['id'] in confirmed_ids and ring_number(row['warehouse__ring_no']) > ring
                           and openings[row['warehouse_id']]['shield_model_id'] == machine]
            segments.append({'install_ring': ring, 'removal_ring': min((ring_number(row['warehouse__ring_no']) for row in candidates), default=None)})
        return {'results': [{'instance': {'tool_uid': sample['tool_uid'], 'status': sample['lifecycle_status']},
                             'service_segments': sorted(segments, key=lambda row: row['install_ring'])[-20:]}]}
    if name == 'query_data_catalog':
        quote_counts = Counter(row['cost_type'] for row in evidence.quotes)
        observation_ids = {row['id'] for row in observed}
        labels = {}
        for row in evidence.strata:
            for code in {code.strip() for code in (row['stratum_type_codes'] or '').split(',') if code.strip()}:
                labels.setdefault(code, set()).add(ring_number(row['ring_no']))
        return {'legacy_code_counts': {code: len(rings) for code, rings in labels.items()}, 'data_coverage': {
            'openings': {'count': len(evidence.openings), 'summary_status_counts': dict(Counter(row['summary_status'] for row in evidence.openings))},
            'tool_change_observations': {'observation_count': len(observed), 'replacement_count': len(replaced)},
            'tunneling': {'record_count': len(evidence.tunneling)},
            'stratum': {'ring_count': len({row['ring_no'] for row in evidence.strata})},
            'cost_quotes': {'new_tool_count': quote_counts['NEW_TOOL'], 'repair_count': quote_counts['REPAIR']},
            'old_tool_repairs': {'status_counts': dict(Counter(row['inspection_status'] for row in evidence.repairs
                                                             if row['tool_change_detail_id'] in observation_ids))}}}
    raise ValueError(f'No independent oracle for {name}')


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
    elif isinstance(expected, (int, float, Decimal)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float, Decimal)) or not math.isclose(expected, actual, rel_tol=1e-8, abs_tol=1e-7):
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
    elif name == 'query_stratum_area':
        result['area_classes'] = {row['code']: row for row in data.get('classes', [])}
    elif name == 'query_tool_cost_catalog':
        result['model_quotes'] = {row['tool_model_code']: row for row in data.get('by_model', [])}
    elif name == 'compare_manufacturer_service':
        result['supply_counts'] = {row['manufacturer']: row for row in data.get('supply_by_new_manufacturer', [])}
    elif name == 'query_tool_inspections':
        result['completion_counts'] = {row['ring_no']: row for row in data.get('opening_completion', [])}
    elif name == 'query_data_catalog':
        result['legacy_code_counts'] = {row['code']: row['ring_count'] for row in data.get('stratum_codes', {}).get('legacy_labels', [])}
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
        for name in (*TOOL_NAMES, *_NEW_TOOLS):
            original = getattr(llm_service, name, None)
            if original is None:
                continue

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
    row['expected_branch'] = case.expected_branch
    row['manual_review'] = case.manual_review
    if not case.gap:
        row['expected_facts'] = expected_facts(evidence, case)
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
            expected = row['expected_facts']
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
        if not row['failures'] and case.manual_review:
            row['status'] = 'coverage_gap'
            row['coverage_gap'] = case.manual_review
        if case.id == 'cost_project_total' and not re.search(r'不是实际支出|不代表实际支出|无法.*实际|不能.*实际', row['answer']):
            row['failures'].append('实际支出问题必须说明能力边界并提供登记金额')
            row['status'] = 'fail'
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
