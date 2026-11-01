"""固定题单的独立 ORM 真值及文本评分；期望值不经过助手工具或回答校验器。"""
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from statistics import quantiles

from application.shield.models import (
    NewToolRecord, OldToolRecord, ShieldTunnelingData, StratumBasicInfo,
    ToolChangeDetail, ToolCost, ToolInstance, WarehouseOpeningBasicInfo,
)
from application.shield.trajectory import (
    ROLLER_POSITION_RADII_MM, SCRAPER_POSITION_RADII_MM, Y_ROLLER_POSITION_RADII_MM,
)

# source_title/source_question：前端模板定位及未替换原文；substitutions：占位符替换值。
# expect：每轮预期；branch：规则分支；tools/name/params：有序工具及参数。
# params 中 recent_openings_100/recent_tunneling_100/overlap/peak_segment 由独立数据动态展开。
# required_sections/forbidden_sections：必须/不得输出的章节标记；memory_slots：该轮完整记忆条件。
# skip_in_ci：无适用数据的原因；known_failure：已证实的生产缺陷（不得放宽断言）。
# 真值 numbers：label/value/unit/aliases 为指标、数值、单位及同义词，empty 表示空结果可作零。
# 真值 objects：每个对象的一组联合标识；sort 为对象及排序值，允许并列。
ACTIVE = {str(n) for n in range(1, 80)} | {"80A", "80B", "Y1", "Y3", "Y5"} | {
    f"S{n}{side}" for n in range(1, 20) for side in "LR"}
NORMAL = {"正常", "良好", "完好", "无异常", "正常磨损", "轻微磨损", "未见异常", "NORMAL", "GOOD"}
ABNORMAL = {"偏磨", "刀圈崩刃", "崩刃", "刀圈脱落", "脱落", "漏油", "轴承损坏", "断裂",
            "严重磨损", "中度磨损", "异常", "异常磨损", "崩口", "刀圈磨平", "刀体磨损",
            "CHIP", "ABNORMAL", "MODERATE", "SEVERE"}
AREA_LABELS = dict(zip(("AREA_CLAY_SAND", "AREA_SOFT_SOIL", "AREA_SOFT_HARD", "AREA_WEAK_GRANITE",
                       "AREA_BEDROCK_PROTRUSION", "AREA_BOULDER"),
                      ("黏土夹砂地层", "软土地基", "上软下硬地层", "弱风化花岗岩段", "基岩凸起地层", "孤石")))
LABELS = {key.removeprefix("AREA_"): value for key, value in AREA_LABELS.items()}
REFERENCE_PENETRATION_MM = 16.67


def load_fixed_cases() -> list[dict]:
    """读取 fixed_cases.json，返回题目列表（字段见任务说明第 1 节）。"""
    return json.loads(Path(__file__).with_name("fixed_cases.json").read_text(encoding="utf-8"))


def _position(value):
    value = (value or "").strip().upper()
    return str(int(value)) if value.isdigit() else value


def _position_key(value):
    if value.isdigit():
        return 0, int(value), ""
    if value.startswith("80"):
        return 0, 80, value[-1]
    return (1, int(value[1:]), "") if value.startswith("Y") else (2, int(value[1:-1]), value[-1])


def _average(values, digits=1):
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), digits) if values else None


def _summarize(rows):
    wear = Counter((row["wear_condition"] or "").strip().upper() for row in rows)
    normal = sum(count for key, count in wear.items() if key in NORMAL)
    abnormal = sum(count for key, count in wear.items() if key in ABNORMAL)
    replaced = sum(row["is_replaced"] for row in rows)
    return {"records": len(rows), "replaced": replaced, "normal": normal, "abnormal": abnormal,
            "unknown": len(rows) - normal - abnormal, "wear_distribution": dict(wear),
            "replacement_rate_pct": round(replaced / len(rows) * 100, 1) if rows else None,
            "abnormal_rate_pct": round(abnormal / (normal + abnormal) * 100, 1) if normal + abnormal else None}


def _sum_money(rows, field):
    return str(sum((row[field] for row in rows if row[field] is not None), Decimal("0")))


def _scope_rows(params, evidence, rows=None):
    selected = list(evidence["observed"] if rows is None else rows)
    for key, field in (("tool_type", "type"), ("cutter_position_no", "position")):
        if params.get(key):
            selected = [row for row in selected if row[field] == params[key]]
    if params.get("ring_range"):
        low, high = params["ring_range"]
        selected = [row for row in selected if low <= row["ring"] <= high]
    count = params.get("last_n_openings") or params.get("recent_openings")
    if count:
        ids = {row["id"] for row in evidence["opening_rows"][:count]}
        selected = [row for row in selected if row["warehouse_id"] in ids]
    return selected


def _collect_evidence(project_id):
    openings = list(WarehouseOpeningBasicInfo.objects.filter(project__project_id=project_id).values(
        "id", "project_id", "shield_model_id", "ring_no", "open_time", "summary_status",
        "rings_between_openings", "opening_duration", "tool_change_duration", "checked_tool_count",
        "replaced_tool_count", "right_revolution_reading", "left_revolution_reading"))
    by_opening = {row["id"]: row for row in openings}
    active = []
    for row in ToolChangeDetail.objects.filter(warehouse_id__in=by_opening).values(
            "id", "warehouse_id", "cutter_position_no", "tool_parent_type", "is_checked", "is_replaced",
            "wear_condition", "manufacturer", "price", "check_result", "tool_number", "blade_wear_amount"):
        row.update(position=_position(row["cutter_position_no"]), type=row["tool_parent_type"].strip().upper(),
                   ring=int(by_opening[row["warehouse_id"]]["ring_no"]))
        expected_type = "SCRAPER" if row["position"].startswith("S") else "DISC"
        if row["position"] in ACTIVE and row["type"] == expected_type:
            active.append(row)
    observed = [row for row in active if row["is_checked"] or row["is_replaced"]]
    details = {row["id"]: row for row in active}
    repairs = list(OldToolRecord.objects.filter(tool_change_detail_id__in=[
        row["id"] for row in observed if row["is_replaced"]]).values(
            "id", "old_tool_number", "tool_change_detail_id", "confirmed_tool_instance_id", "inspection_status",
            "repair_price", "disposition", "ring_damage", "bearing_failure_reasons", "hub_failure_reasons",
            "scraper_chipped", "scraper_broken", "scraper_detached"))
    installations = list(NewToolRecord.objects.filter(tool_change_detail_id__in=details).values(
        "tool_change_detail_id", "tool_instance_id", "tool_instance__tool_info__tool_type_name"))
    by_instance = defaultdict(list)
    for row in installations:
        by_instance[row["tool_instance_id"]].append(row)
    paired = []
    for removal in repairs:
        candidates = by_instance[removal["confirmed_tool_instance_id"]]
        if removal["inspection_status"] not in {"CONFIRMED", "CLOSED"} or len(candidates) != 1:
            continue
        installation = candidates[0]
        before, after = details[installation["tool_change_detail_id"]], details[removal["tool_change_detail_id"]]
        bo, ao = by_opening[before["warehouse_id"]], by_opening[after["warehouse_id"]]
        if (before["is_replaced"] and bo["summary_status"] == ao["summary_status"] == "CONFIRMED"
                and bo["shield_model_id"] == ao["shield_model_id"] and bo["project_id"] == ao["project_id"]
                and bo["open_time"] <= ao["open_time"] and before["ring"] < after["ring"]):
            paired.append({"removal_id": removal["id"], "installation_detail_id": before["id"],
                           "rings": after["ring"] - before["ring"], "manufacturer": before["manufacturer"],
                           "tool_type": before["type"], "model": installation["tool_instance__tool_info__tool_type_name"],
                           "wear_condition": after["wear_condition"]})
    repetitions = Counter(row["installation_detail_id"] for row in paired)
    paired = [row for row in paired if repetitions[row["installation_detail_id"]] == 1]
    for opening in openings:
        rows = [row for row in active if row["warehouse_id"] == opening["id"]]
        for name, field in (("checked", "is_checked"), ("replaced", "is_replaced")):
            opening["chosen_" + name] = (opening[name + "_tool_count"] if opening["summary_status"] == "CONFIRMED"
                                         else sum(row[field] for row in rows))
        opening["position_replacement_counts"] = dict(Counter(row["position"] for row in rows if row["is_replaced"]))
    tunnel = list(ShieldTunnelingData.objects.filter(project__project_id=project_id).values(
        "ring_no", "record_time", "thrust", "torque", "cutterhead_speed", "penetration", "advance_speed",
        "point_count", "shield_machine_id", "counter_revolutions", "integrated_revolutions"))
    return {"project_id": project_id, "observed": observed, "all_active": active, "detail_map": details,
            "openings": openings, "by_opening": by_opening, "repairs": repairs, "paired": paired,
            "opening_rows": sorted(openings, key=lambda row: (-int(row["ring_no"]), row["open_time"], row["id"])),
            "strata": list(StratumBasicInfo.objects.filter(project__project_id=project_id).values(
                "ring_no", "stratum_type_codes", "longitudinal_type_ratios")), "tunnel": tunnel,
            "quotes": list(ToolCost.objects.values("tool_info__tool_type_name", "tool_info__tool_parent_type",
                "cost_type", "manufacturer", "brand", "unit_price"))}


def _radius(position):
    if position.startswith("S"):
        return SCRAPER_POSITION_RADII_MM.get(position)
    return Y_ROLLER_POSITION_RADII_MM.get(position, ROLLER_POSITION_RADII_MM.get(
        int(position) if position.isdigit() else position))


def _segments(params, evidence):
    rows = _scope_rows(params, evidence)
    if not rows:
        return []
    low, high = min(row["ring"] for row in rows), max(row["ring"] for row in rows)
    return [{"range": [start, min(start + params.get("interval", 50) - 1, high)],
             **_summarize([row for row in rows if start <= row["ring"] <= min(start + params.get("interval", 50) - 1, high)])}
            for start in range(low, high + 1, params.get("interval", 50))]


def _resolve_params(params, evidence):
    params = dict(params)
    bounds = params.get("ring_range")
    if bounds in ("recent_openings_100", "recent_tunneling_100"):
        source = evidence["openings"] if bounds == "recent_openings_100" else evidence["tunnel"]
        latest = max((int(row["ring_no"]) for row in source), default=0)
        params["ring_range"] = [max(1, latest - 99), latest]
    elif bounds == "peak_segment":
        params["ring_range"] = max(_segments({}, evidence), key=lambda row: row["replaced"])["range"]
    elif bounds == "overlap":
        changes = [row["ring"] for row in evidence["observed"]]
        tunnel = [int(row["ring_no"]) for row in evidence["tunnel"]]
        low, high = (max(min(changes), min(tunnel)), min(max(changes), max(tunnel))) if changes and tunnel else (1, 0)
        params["ring_range"] = [low, high] if low <= high else None
    return params


def _model_specs(case):
    case_id = case["id"]
    recent = {"ring_range": "recent_openings_100"}
    mapping = {
        "m01": [("query_tool_change_data", recent)], "m02": [("query_tool_change_trend", {"interval": 50})],
        "m03": [("query_opening_records", {"limit": 5}), ("query_tool_inspections", {"recent_openings": 5})],
        "m04": [("query_tool_inspections", {"recent_openings": 5})],
        "m05": [("query_cutter_position_stats", {"top_n": 10, "sort_by": "abnormal"})],
        "m06": [("query_opening_stratum", {"recent_openings": 5})],
        "m07": [("query_stratum_area", recent), ("query_tool_change_data", recent)],
        "m08": [("query_tunneling_summary", {"ring_range": "overlap"}), ("query_tool_change_data", {"ring_range": "overlap"})],
        "m09": [("query_tunneling_anomaly", {})],
        "m10": [("compare_manufacturer_service", {})],
        "m12": [("query_registered_amounts", {})], "m13": [("query_old_tool_repairs", {})],
        "m14": [("query_old_tool_repairs", {"components": ["轴承", "刀圈"]})],
        "m15": [("trace_tool_lifecycle", {"tool_ids": ["GD-TEST-0001"]})],
        "m16": [("query_tool_change_data", recent), ("query_old_tool_repairs", recent)],
        "m17": [("query_tool_change_data", recent), ("query_tunneling_summary", recent)],
    }
    if case_id.startswith("m11-"):
        kind = {"m11-1": None, "m11-2": "DISC", "m11-3": "SCRAPER"}[case_id]
        calls = [("recommend_tools", {"tool_type": kind, "sort_by": "price_per_ring"})]
    elif case_id.startswith("m18-"):
        kind = {"m18-1": None, "m18-2": "DISC", "m18-3": "SCRAPER"}[case_id]
        calls = [("query_tool_mileage", {"tool_type": kind} if kind else {})]
    else:
        calls = mapping[case_id]
    return [{"tools": [{"name": name, "params": params} for name, params in calls]}]


def collect_gold(project_id: str) -> dict:
    """直接查询业务表计算该项目全部固定题的独立期望值，按题号索引；不调用助手工具。"""
    evidence = _collect_evidence(project_id)
    result = {}
    for case in load_fixed_cases():
        turns = []
        for turn, spec in enumerate(case.get("expect") or _model_specs(case)):
            spec = {**spec, "tools": [{**call, "params": _resolve_params(call["params"], evidence)}
                                      for call in spec["tools"]]}
            question = (case.get("turns") or [case.get("question", "")])[turn]
            turns.append(_turn_gold(case, spec, evidence, question))
        # 多题共享只读证据引用，不重复查库；评分仅使用 turns 中的独立事实。
        result[case["id"]] = {"turns": turns, "evidence": evidence}
    return result


def _turn_gold(case, spec, evidence, question):
    numbers, objects, sort = [], [], []
    def add(label, value, unit="", aliases=(), empty=False):
        if value is not None:
            aliases = aliases or [metric for metric in ("现场观测数", "记录数", "更换次数", "更换数", "更换率", "异常率",
                "平均服役", "样本数", "新刀报价", "每环报价", "每公里成本", "已拆段", "在役", "已分类", "非正常", "磨损", "里程") if metric in label]
            numbers.append({"label": label, "value": float(value), "unit": unit,
                            "aliases": list(aliases), "empty": empty})
    for call in spec["tools"]:
        name, params = call["name"], call["params"]
        rows = _scope_rows(params, evidence)
        summary = _summarize(rows)
        case_id = case["id"]
        agent = case["expected_path"] == "agent"
        if name == "query_tool_change_data":
            if case_id not in ("m07", "m08"):
                add("现场观测记录数", len(rows), aliases=["观测", "记录数"], empty=True)
            if case_id not in ("m01", "m17"):
                add("更换数", summary["replaced"], aliases=["实际更换", "更换次数"])
                if case_id != "m08":
                    add("更换率", summary["replacement_rate_pct"], "%")
            if case_id == "m17":
                add("异常观测数", summary["abnormal"], aliases=["异常数量", "异常观测"])
            if case_id in ("m07", "m17"):
                add("已分类异常率", summary["abnormal_rate_pct"], "%", aliases=["异常率"])
            if (not agent and any(word in question for word in ("磨损", "异常"))) or "磨损类型" in question or spec.get("branch") == "position_point_query":
                for label, count in summary["wear_distribution"].items():
                    if not agent or label in ABNORMAL:
                        add(label, count)
                        if case_id == "m01" and summary["normal"] + summary["abnormal"]:
                            add(label + "占比", round(count / (summary["normal"] + summary["abnormal"]) * 100, 1), "%")
            if case_id == "m08":
                for source in (evidence["observed"], evidence["tunnel"]):
                    rings = [row.get("ring", int(row["ring_no"]) if "ring_no" in row else 0) for row in source]
                    if rings:
                        add("覆盖起环", min(rings)); add("覆盖止环", max(rings))
            if case["id"] in ("q01", "q04"):
                counts = Counter(row["position"] for row in rows if row["is_replaced"])
                ranked = sorted(counts, key=lambda position: (-counts[position], _position_key(position)))[:5]
                objects.extend([[position] for position in ranked])
                sort = [(position, counts[position]) for position in ranked]
                for position in ranked:
                    add(position + "更换次数", counts[position])
        elif name == "query_tool_change_trend":
            segments = _segments(params, evidence)
            if spec.get("branch") == "group_service":
                peak = max((segment["replaced"] for segment in segments), default=0)
                for segment in segments:
                    if segment["replaced"] == peak and peak > 0:
                        add("集中更换次数", peak)
                        add("集中更换起环", segment["range"][0], "环")
                        add("集中更换止环", segment["range"][1], "环")
                continue
            for segment in segments:
                for label, key in (("分段观测数", "records"), ("分段更换数", "replaced"),
                                   ("分段更换率", "replacement_rate_pct"), ("分段异常率", "abnormal_rate_pct")):
                    if case["id"] == "q08" and key == "abnormal_rate_pct":
                        continue
                    if agent and key == "records":
                        continue
                    add(label, segment[key], "%" if "率" in label else "")
        elif name == "query_opening_records":
            all_openings = [row for row in evidence["opening_rows"] if not params.get("ring_range")
                            or params["ring_range"][0] <= int(row["ring_no"]) <= params["ring_range"][1]]
            recent = all_openings[:params.get("limit", 10)]
            if not agent:
                add("开仓总数", len(all_openings), aliases=["开仓", "全部"], empty=True)
            if case["id"] in ("q14", "q15"):
                field, count = ("opening_duration", "chosen_checked") if case["id"] == "q14" else ("tool_change_duration", "chosen_replaced")
                valid = [row for row in all_openings if row[field] is not None and row[count]]
                denominator = sum(row[count] for row in valid)
                add("分钟/把", round(sum(row[field] for row in valid) * 60 / denominator, 1) if denominator else None,
                    aliases=["平均检查", "平均更换"])
            else:
                for population in (() if agent else (all_openings, recent)):
                    add("平均间隔", _average([row["rings_between_openings"] for row in population]), "环")
                    if case["id"] != "q16":
                        add("平均开仓时长", _average([row["opening_duration"] for row in population]), "小时")
                objects.extend([[row["ring_no"]] for row in recent])
                for opening in recent:
                    if case["id"] != "q13":
                        add("开仓间隔", opening["rings_between_openings"], "环")
                    if case["id"] != "q16":
                        add("检查数", opening["chosen_checked"])
                        add("更换数", opening["chosen_replaced"])
                    if agent:
                        add("开仓时长", opening["opening_duration"], "小时")
                        add("换刀时长", opening["tool_change_duration"], "小时")
                        add("异常率", _summarize([row for row in rows if row["warehouse_id"] == opening["id"]])["abnormal_rate_pct"], "%")
                if case["id"] == "q13":
                    sort = [(row["ring_no"], _summarize([item for item in rows if item["warehouse_id"] == row["id"]])["abnormal_rate_pct"])
                            for row in recent]
        elif name == "query_cutter_position_stats":
            positions = [p for p in ACTIVE if not params.get("tool_type") or
                         ("SCRAPER" if p.startswith("S") else "DISC") == params["tool_type"]]
            field = "abnormal" if params.get("sort_by") == "abnormal" else "replaced"
            ranked = [(p, _summarize([row for row in rows if row["position"] == p])) for p in positions]
            ranked.sort(key=lambda item: (-item[1][field], _position_key(item[0])))
            ranked = ranked if params.get("include_all") else ranked[:params.get("top_n", 10)]
            objects.extend([[p] for p, _ in ranked])
            sort = [(p, data[field]) for p, data in ranked]
            for p, data in ranked:
                add(f"{p} 更换次数", data["replaced"])
                if field == "abnormal":
                    add(f"{p} 异常数", data["abnormal"])
        elif name == "query_tool_inspections":
            active = _scope_rows(params, evidence, evidence["all_active"])
            if agent:
                for opening in evidence["opening_rows"][:params.get("recent_openings", 5)]:
                    selected = [row for row in active if row["warehouse_id"] == opening["id"]]
                    add(opening["ring_no"] + "需关注未更换", sum(not row["is_replaced"] and row["check_result"] in ("ATTENTION", "ABNORMAL_NOT_REPLACED") for row in selected), aliases=["需关注未更换"])
                    if case_id == "m04":
                        add(opening["ring_no"] + "已检查", sum(row["is_checked"] for row in selected), aliases=["已检查"])
                        add(opening["ring_no"] + "未检查", sum(not row["is_replaced"] and not row["is_checked"] for row in selected), aliases=["未检查"])
                continue
            unchecked = [row for row in active if not row["is_replaced"] and not row["is_checked"]]
            attention = [row for row in active if not row["is_replaced"] and row["check_result"] in ("ATTENTION", "ABNORMAL_NOT_REPLACED")]
            if case["id"] != "q18":
                add("需关注未更换", len(attention), empty=True)
            if case["id"] != "q17":
                add("未检查", len(unchecked), empty=True)
        elif name in ("query_stratum_area", "query_stratum_data", "query_opening_stratum"):
            strata = [row for row in evidence["strata"] if not params.get("ring_range")
                      or params["ring_range"][0] <= int(row["ring_no"]) <= params["ring_range"][1]]
            if name == "query_stratum_data":
                for code, count in Counter(code for row in strata for code in row["stratum_type_codes"].split(",") if code).items():
                    add(LABELS.get(code, code), count)
            else:
                populations = [strata]
                if name == "query_opening_stratum":
                    populations = []
                    for opening in evidence["opening_rows"][:params.get("recent_openings", 1)]:
                        earlier = [int(row["ring_no"]) for row in evidence["openings"]
                                   if row["shield_model_id"] == opening["shield_model_id"] and int(row["ring_no"]) < int(opening["ring_no"])]
                        low, high = max(earlier, default=0) + 1, int(opening["ring_no"])
                        populations.append([row for row in strata if low <= int(row["ring_no"]) <= high])
                for population in populations:
                    for code, label in AREA_LABELS.items():
                        add(label, _average([float((row["longitudinal_type_ratios"] or {}).get(code, 0)) for row in population]), "%")
        elif name == "analyze_stratum_wear_correlation":
            strata = {int(row["ring_no"]): set(filter(None, row["stratum_type_codes"].split(","))) for row in evidence["strata"]}
            for code in sorted({code for codes in strata.values() for code in codes}):
                selected = [row for row in rows if code in strata.get(row["ring"], set())]
                data = _summarize(selected)
                for label, key in (("现场观测数", "records"), ("更换数", "replaced"), ("更换率", "replacement_rate_pct")):
                    add(LABELS.get(code, code) + label, data[key], "%" if "率" in label else "")
        elif name == "query_position_stratum_impact":
            counts = Counter(row["position"] for row in rows if row["is_replaced"])
            for _, count in counts.most_common(params.get("top_n", 10)):
                add("刀位实际更换次数", count)
        elif name.startswith("query_tunneling_"):
            tunnel = [row for row in evidence["tunnel"] if not params.get("ring_range")
                      or params["ring_range"][0] <= int(row["ring_no"]) <= params["ring_range"][1]]
            if name in ("query_tunneling_summary", "query_tunneling_anomaly", "query_tunneling_wear_correlation") and case_id not in ("m08", "m09", "m17"):
                add("掘进记录数", len(tunnel), aliases=["查询到", "记录"], empty=True)
            if case_id == "m17" and not tunnel:
                add("掘进记录数", 0, empty=True)
            if name == "query_tunneling_summary":
                for field, label in (("thrust", "推力"), ("torque", "扭矩"), ("cutterhead_speed", "转速"), ("penetration", "贯入度")):
                    if case_id in ("m08", "m17") and field == "cutterhead_speed":
                        continue
                    add(label, _average([row[field] for row in tunnel], 3))
            elif case_id == "m09":
                for field, label in (("thrust", "推力"), ("torque", "扭矩"), ("penetration", "贯入度")):
                    values = [row[field] for row in tunnel if row[field] is not None]
                    mean = sum(values) / len(values) if values else None
                    for row in tunnel:
                        if mean and row[field] is not None and row[field] > mean * 1.5:
                            add(label + "偏高环号", int(row["ring_no"])); add(label + "偏高数值", row[field])
            elif name in ("query_tunneling_trend", "query_tunneling_wear_correlation") and tunnel:
                low, high = params.get("ring_range") or [min(int(row["ring_no"]) for row in tunnel), max(int(row["ring_no"]) for row in tunnel)]
                for start in range(low, high + 1, params.get("interval", 50)):
                    selected = [row for row in tunnel if start <= int(row["ring_no"]) <= start + params.get("interval", 50) - 1]
                    for field, label in (("thrust", "推力"), ("torque", "扭矩"), ("penetration", "贯入度")):
                        add(label, _average([row[field] for row in selected], 3))
        elif name in ("recommend_tools", "compare_manufacturer_service"):
            removal_map = {row["id"]: row for row in evidence["repairs"]}
            pairs = [row for row in evidence["paired"] if not params.get("tool_type") or row["tool_type"] == params["tool_type"]]
            if params.get("ring_range"):
                pairs = [row for row in pairs if params["ring_range"][0] <= evidence["detail_map"][row["installation_detail_id"] if name == "recommend_tools"
                    else removal_map[row["removal_id"]]["tool_change_detail_id"]]["ring"] <= params["ring_range"][1]]
            if name == "compare_manufacturer_service" and case["id"] != "q34" and not agent or spec.get("branch") == "group_service":
                add("确认配对", len(pairs), aliases=["已确认拆下", "确认段数"])
            if spec.get("branch") == "group_service":
                add("平均服役", _average([row["rings"] for row in pairs]), "环")
            key = "model" if name == "recommend_tools" else "manufacturer"
            groups = defaultdict(list)
            for row in pairs:
                groups[row[key]].append(row)
            for label, samples in groups.items():
                objects.append([label])
                if case["id"] != "q34":
                    add(label + "样本数", len(samples)); add(label + "平均服役", _average([row["rings"] for row in samples]), "环")
                if name == "compare_manufacturer_service":
                    normal = sum(row["wear_condition"].strip().upper() in NORMAL for row in samples)
                    abnormal = sum(row["wear_condition"].strip().upper() in ABNORMAL for row in samples)
                    if case["id"] != "q34":
                        add(label + "已分类异常率", round(abnormal / (normal + abnormal) * 100, 1) if normal + abnormal else None, "%")
                    if "类型" in question:
                        for reason, count in Counter(row["wear_condition"] for row in samples if row["wear_condition"].strip().upper() in ABNORMAL).items():
                            add(label + reason, count)
                elif case["id"] not in ("q41", "q42", "p01", "p02", "p13"):
                    prices = [float(row["unit_price"]) for row in evidence["quotes"] if row["tool_info__tool_type_name"] == label and row["cost_type"] == "NEW_TOOL" and row["unit_price"] is not None]
                    if prices:
                        add(label + "最低新刀报价", min(prices), "元"); add(label + "最高新刀报价", max(prices), "元")
                    if params.get("sort_by") == "price_per_ring" and samples and prices:
                        sort.append((label, -round(min(prices) / _average([row["rings"] for row in samples]), 2)))
                        for quote in evidence["quotes"]:
                            if quote["tool_info__tool_type_name"] == label and quote["cost_type"] == "NEW_TOOL" and quote["unit_price"] is not None:
                                objects.append([label, quote["manufacturer"]])
                                add(label + quote["manufacturer"] + "新刀报价", quote["unit_price"], "元")
                                add(label + quote["manufacturer"] + "每环报价", round(float(quote["unit_price"]) / _average([row["rings"] for row in samples]), 2))
            if case_id == "m10":
                supply = defaultdict(list)
                for row in rows:
                    if row["is_replaced"]:
                        supply[row["manufacturer"]].append(row)
                for manufacturer, items in supply.items():
                    add(manufacturer + "供货次数", len(items), aliases=["供货次数"])
                    add(manufacturer + "登记金额", _sum_money(items, "price"), "元", aliases=["登记金额"])
        elif name == "query_tool_cost_catalog":
            quotes = evidence["quotes"]
            add("报价总数", len(quotes), aliases=["报价", "全部"])
            objects.extend([list(key) for key in sorted({(row["tool_info__tool_type_name"], row["manufacturer"]) for row in quotes})])
            for row in quotes:
                add(row["tool_info__tool_type_name"] + row["manufacturer"], row["unit_price"], "元")
        elif name in ("query_old_tool_repairs", "query_registered_amounts"):
            ids = {row["id"] for row in rows}
            repairs = [row for row in evidence["repairs"] if row["tool_change_detail_id"] in ids]
            if params.get("components"):
                fields = {"轴承": "bearing_failure_reasons", "刀圈": "ring_damage", "刀毂": "hub_failure_reasons"}
                repairs = [row for row in repairs if any(row[fields[c]] for c in params["components"])]
            confirmed = [row for row in repairs if row["inspection_status"] in ("CONFIRMED", "CLOSED")]
            case_id = case["id"]
            if name == "query_registered_amounts":
                add("新装登记金额", _sum_money([row for row in rows if row["is_replaced"]], "price"), "元")
            if case_id in ("q39", "q36", "m12"):
                add("确认返修登记金额", _sum_money(confirmed, "repair_price"), "元", aliases=["已确认", "确认返修"])
            if case_id == "m12":
                add("待反馈返修登记金额", _sum_money([row for row in repairs if row["inspection_status"] == "PENDING_VENDOR_FEEDBACK"], "repair_price"), "元", aliases=["待反馈"])
            if case_id not in ("q38", "q39", "q40", "m14", "q36", "m10", "m12"):
                for status, label in (("PENDING_VENDOR_FEEDBACK", "待厂家反馈"), ("CONFIRMED", "已确认"), ("CLOSED", "已归档")):
                    add(label, sum(row["inspection_status"] == status for row in repairs))
            if case_id in ("q38", "m13"):
                add("已报废", sum(row["disposition"] == "SCRAP" for row in confirmed))
                add("报废建议", sum(row["disposition"] == "SCRAP" and row["inspection_status"] == "PENDING_VENDOR_FEEDBACK" for row in repairs))
            if case_id == "m14":
                for position, count in Counter(evidence["detail_map"][row["tool_change_detail_id"]]["position"] for row in repairs).items():
                    add(position + "失效旧刀次数", count, aliases=["出现次数", "次数"])
            if case_id in ("q40", "m13"):
                reasons = Counter((component, reason) for row in repairs for component, field in
                    (("刀圈", "ring_damage"), ("轴承", "bearing_failure_reasons"), ("刀毂", "hub_failure_reasons")) for reason in set(row[field] or []))
                for (component, reason), count in reasons.items():
                    add(component + reason, count)
        elif name == "trace_tool_lifecycle":
            instances = set(ToolInstance.objects.filter(display_tool_no__in=params["tool_ids"]).values_list("pk", flat=True))
            selected = [pair for pair in evidence["paired"] if _removal_instance(pair, evidence) in instances]
            for pair in selected:
                if agent:
                    installation = evidence["detail_map"][pair["installation_detail_id"]]
                    add("安装环号", installation["ring"], "环")
                    add("拆下环号", installation["ring"] + pair["rings"], "环")
                else:
                    add("服役环数", pair["rings"], "环")
        elif name == "query_tool_mileage" and params.get("cutter_position_no"):
            # 问单个刀位时只回答该刀位的历次服役段和累计里程，不出分带汇总
            samples, active, _ = _mileage_rows(params, evidence)
            position = params["cutter_position_no"]
            selected = [row for row in samples if row["position"] == position]
            for row in selected:
                add(f"{position} {row['installation_ring_no']} 环起服役环数", row["service_rings"], "环", aliases=["服役环数"])
                add(f"{position} {row['installation_ring_no']} 环起里程", row["km"], "km", aliases=["里程"])
            active_km = sum(row["km"] for row in active if row["position"] == position)
            add(f"{position}累计里程", round(sum(row["km"] for row in selected) + active_km, 2), "km", aliases=["累计", "里程"])
        elif name == "query_tool_mileage":
            samples, active, exclusions = _mileage_rows(params, evidence)
            add("未计入里程", sum(exclusions.values()))
            groups = defaultdict(list)
            for row in samples + active:
                groups[row["type"], row["band"], row["manufacturer"]]
            for row in samples:
                groups[row["type"], row["band"], row["manufacturer"]].append(row)
            for (kind, band, manufacturer), selected in groups.items():
                label = f"{kind} {band} {manufacturer}"
                add(label + "已拆段", len(selected))
                current = [row for row in active if (row["type"], row["band"], row["manufacturer"]) == (kind, band, manufacturer)]
                add(label + "在役把数", len(current))
                add(label + "非正常数", sum(row["state"] == "abnormal" for row in selected))
                add(label + "已分类数", sum(row["state"] is not None for row in selected))
                for field, items in (("km", selected), ("wear", selected), ("km", current)):
                    spread = _spread([row[field] for row in items if row[field] is not None])
                    if spread:
                        for value in spread.get("values", [round(spread[key], 1) for key in ("q1", "median", "q3") if key in spread]):
                            add(label + ("磨损" if field == "wear" else "里程"), value, "mm" if field == "wear" else "km")
                if len(selected) >= 5 and sum(row["km"] for row in selected):
                    add(label + "每公里成本", round(sum(row["price"] for row in selected) / sum(row["km"] for row in selected), 2))
        elif name == "query_data_catalog":
            for label, value in (("现场观测记录数", len(evidence["observed"])), ("旧刀返修", len(evidence["repairs"])),
                                 ("开仓总数", len(evidence["openings"])), ("掘进参数", len(evidence["tunnel"]))):
                add(label, value)
    return {"numbers": numbers, "objects": objects or None, "sort": sort or None, "expect": spec}


def _removal_instance(pair, evidence):
    return next(row["confirmed_tool_instance_id"] for row in evidence["repairs"] if row["id"] == pair["removal_id"])


def _normalized_text(text):
    return unicodedata.normalize("NFKC", text).replace("**", "").replace("\u00a0", " ")


def _extract_numbers(text):
    tokens = []
    pattern = r"(?<![A-Za-z0-9_.])[-+]?(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?"
    for match in re.finditer(pattern, text):
        raw = match.group()
        tail = text[match.end():]
        unit = re.match(r"\s*(亿元|万元|千元|元|公里|千米|毫米|厘米|米|km|mm|cm|m|小时|分钟|秒|%|成)", tail)
        tokens.append({"value": float(raw.replace(",", "").replace("，", "")), "raw": raw,
                       "unit": unit[1] if unit else "", "start": match.start(), "end": match.end()})
    return tokens


def _converted_number(token, unit):
    conversions = {"元": {"亿元": 1e8, "万元": 1e4, "千元": 1e3},
                   "km": {"米": .001, "m": .001, "千米": 1, "公里": 1},
                   "mm": {"厘米": 10, "cm": 10, "米": 1000, "m": 1000, "毫米": 1},
                   "小时": {"分钟": 1 / 60, "秒": 1 / 3600}, "%": {"成": 10}}
    return token["value"] * conversions.get(unit, {}).get(token["unit"], 1)


def _metric_candidates(text, fact):
    aliases = [fact["label"], *fact.get("aliases", [])]
    lines = text.splitlines()
    candidates = []
    for index, line in enumerate(lines):
        if not any(alias in line for alias in aliases):
            continue
        if "|" in line and index + 1 < len(lines) and re.search(r"\|\s*:?-{3,}", lines[index + 1]):
            headers = [cell.strip() for cell in line.strip().strip("|").split("|")]
            columns = [i for i, header in enumerate(headers) if any(alias in header for alias in aliases)]
            for row in lines[index + 2:]:
                if not row.strip().startswith("|"):
                    break
                cells = row.strip().strip("|").split("|")
                for column in columns:
                    if column < len(cells):
                        candidates.extend(_extract_numbers(cells[column]))
        else:
            candidates.extend(_extract_numbers(line))
    return candidates


def _object_positions(text, objects):
    positions = {}
    offset = 0
    lines = text.splitlines(keepends=True)
    identity_columns = [0]
    for index, line in enumerate(lines):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if index + 1 < len(lines) and re.search(r"\|\s*:?-{3,}", lines[index + 1]):
            identity_columns = [i for i, cell in enumerate(cells) if re.search(r"刀位|环号", cell)] or [0]
        for identifiers in objects:
            key = tuple(identifiers)
            found = all(((any(column < len(cells) and cells[column] == identifier for column in identity_columns)
                          if "|" in line else re.search(r"(?:刀位|环号)\s*[:：]?\s*" + re.escape(identifier)
                          + r"(?![A-Za-z0-9])|(?<![A-Za-z0-9])" + re.escape(identifier) + r"\s*(?:号刀位|环)", line)) if identifier.isdigit() else
                         re.search(r"(?<![A-Za-z0-9])" + re.escape(identifier) + r"(?![A-Za-z0-9])", line))
                        for identifier in identifiers)
            if found:
                match = re.search(r"(?<![A-Za-z0-9])" + re.escape(identifiers[0]) + r"(?![A-Za-z0-9])", line)
                positions.setdefault(key, offset + match.start())
        offset += len(line)
    return positions


def score_answer(case: dict, answer: str, gold: dict, turn: int = 0) -> dict:
    """只看最终回答文本，对照独立期望值评分。返回：
    {
      "passed": bool,          # 没有 wrong_number / missing_number / missing_objects / bad_sort / unrequested_section
      "numbers": {"checked": int, "correct": int, "format_only": int, "wrong": int, "missing": int},
      "objects": {"expected": int, "listed": int} 或 None,
      "sort_ok": bool 或 None,
      "issues": [{"kind": str, "detail": str}],
    }
    kind 只能取 wrong_number、missing_number、format_only、missing_objects、bad_sort、unrequested_section。
    format_only 表示期望值以其他写法出现在回答里（如千位分隔符、单位换算、与别的数字写在一起），记录但不判为失败。
    数字抽取必须自己实现规范化（去千位分隔符、全角数字、常见单位），
    不得调用 answer_check.py，也不要只依赖 evaluation/answer_checks.py 的抽取函数。
    """
    expected = gold[case["id"]]["turns"][turn]
    text = _normalized_text(answer)
    tokens = _extract_numbers(text)
    full_width_values = {float(unicodedata.normalize("NFKC", match.group()).replace(",", ""))
                         for match in re.finditer(r"(?:[０-９\d]{1,3}(?:[,，][０-９\d]{3})+|[０-９\d]+)(?:[.．][０-９\d]+)?", answer)
                         if any(character in "０１２３４５６７８９" for character in match.group())}
    numbers = {"checked": 0, "correct": 0, "format_only": 0, "wrong": 0, "missing": 0}
    issues = []
    for fact in expected["numbers"]:
        numbers["checked"] += 1
        value, unit = fact["value"], fact.get("unit", "")
        matches = [token for token in tokens if math.isclose(_converted_number(token, unit), value, abs_tol=0.00001)]
        empty_zero = value == 0 and fact.get("empty") and re.search(r"未找到[^。\n]*记录|(?:暂无|没有|无)[^。\n]*(?:记录|数据)|(?:未|没有|不能)覆盖|覆盖不到", text)
        if matches or empty_zero:
            numbers["correct"] += 1
            plain = any(token["value"] == value and "," not in token["raw"] and "，" not in token["raw"]
                        and token["unit"] not in {"万元", "千元", "亿元", "成"}
                        and not re.search(r"/\s*$", text[:token["start"]])
                        and not re.match(r"\s*/", text[token["end"]:]) for token in matches)
            # format_only 同时计入 correct；中文标点规范化本身不算数字格式差异。
            full_width = any(token["value"] in full_width_values for token in matches)
            if not plain or full_width:
                numbers["format_only"] += 1
                issues.append({"kind": "format_only", "detail": f"{case['id']} {fact['label']}：实际为其他写法，期望 {value:g}"})
            continue
        candidates = _metric_candidates(text, fact)
        kind = "wrong_number" if candidates else "missing_number"
        numbers["wrong" if candidates else "missing"] += 1
        actual = "、".join(f"{token['value']:g}" for token in candidates[:5]) if candidates else "未写出"
        issues.append({"kind": kind, "detail": f"{case['id']} {fact['label']}：实际 {actual}，期望 {value:g}"})
    object_result, sort_ok = None, None
    if expected.get("objects"):
        objects = expected["objects"]
        positions = _object_positions(text, objects)
        missing = [" / ".join(keys) for keys in objects if tuple(keys) not in positions]
        object_result = {"expected": len(objects), "listed": len(objects) - len(missing)}
        if missing:
            issues.append({"kind": "missing_objects", "detail": f"{case['id']} 对象集合：实际缺少 {'、'.join(missing)}，期望 {len(objects)} 项齐全"})
    if expected.get("sort"):
        ranking = dict(expected["sort"])
        positions = _object_positions(text, [[key] for key in ranking])
        ordered = [key[0] for key in sorted(positions, key=positions.get)]
        values = [ranking[key] if ranking[key] is not None else -math.inf for key in ordered]
        sort_ok = len(ordered) == len(ranking) and values == sorted(values, reverse=True)
        if not sort_ok:
            issues.append({"kind": "bad_sort", "detail": f"{case['id']} 排序：实际 {ordered}，期望按独立指标降序（允许并列）"})
    for marker in expected["expect"].get("forbidden_sections", []):
        if marker in answer:
            issues.append({"kind": "unrequested_section", "detail": f"{case['id']} 输出章节：实际包含 {marker}，期望不出现"})
    return {"passed": not any(issue["kind"] != "format_only" for issue in issues), "numbers": numbers,
            "objects": object_result, "sort_ok": sort_ok, "issues": issues}


def _spread(values):
    values = sorted(values)
    if not values:
        return None
    if len(values) < 5:
        return {'count': len(values), 'values': [round(v, 2) for v in values]}
    a, b, c = quantiles(values, n=4, method='inclusive')
    return {'count': len(values), 'q1': round(a, 2), 'median': round(b, 2), 'q3': round(c, 2)}


def verify_tool(name, params, data, gold):
    """核对实际工具结果；gold 必须为 collect_gold 返回的该题独立证据。"""
    gold = gold['evidence']
    checks = []
    def equal(label, actual, expected):
        passed = (abs(actual - expected) < 0.00001 if isinstance(actual, (float, int))
                  and isinstance(expected, (float, int)) else actual == expected)
        checks.append({'check': label, 'actual': actual, 'expected': expected, 'passed': passed})
    quote_rows = gold['quotes']
    reading_count = sum(r['right_revolution_reading'] is not None and r['left_revolution_reading'] is not None for r in gold['openings'])
    ring_groups = defaultdict(list)
    for row in gold['tunnel']:
        ring_groups[row['shield_machine_id'], int(row['ring_no'])].append(row)
    revolution_counts = {key + '_ring_count': sum(all(r[key + '_revolutions'] is not None for r in items)
                         for items in ring_groups.values()) for key in ('counter', 'integrated')}
    equal(name + ' 无查询错误', 'error' in data, False)
    rows = _scope_rows(params, gold)
    if name == 'query_tool_change_data':
        expected = _summarize(rows)
        equal('观测数', data.get('total_records', 0), expected['records'])
        equal('更换数', data.get('replaced_count', 0), expected['replaced'])
        equal('更换率', data.get('replacement_rate'), f"{expected['replacement_rate_pct']:.1f}%" if rows else None)
        equal('磨损类型计数', {(row['wear_condition'] or '').strip().upper(): row['count'] for row in data.get('wear_distribution', [])},
              expected['wear_distribution'])
        counts = Counter(row['position'] for row in rows if row['is_replaced'])
        ranked = sorted(counts, key=lambda position: (-counts[position], _position_key(position)))[:5]
        equal('主要更换刀位', [(row['cutter_position_no'], row['replacement_count']) for row in data.get('top_replaced_positions', [])],
              [(position, counts[position]) for position in ranked])
    elif name == 'query_tool_change_trend':
        expected_segments = _segments(params, gold)
        equal('完整分段范围', [list(map(int, re.findall(r'\d+', row['ring_range']))) for row in data.get('segments', [])],
              [row['range'] for row in expected_segments])
        for segment in data.get('segments', []):
            lo, hi = map(int, re.findall(r'\d+', segment['ring_range']))
            expected = _summarize([r for r in rows if lo <= r['ring'] <= hi])
            equal('分段观测 ' + segment['ring_range'], segment['total'], expected['records'])
            equal('分段更换 ' + segment['ring_range'], segment['replaced'], expected['replaced'])
    elif name == 'query_opening_records':
        openings = [r for r in gold['opening_rows'] if not params.get('ring_range') or params['ring_range'][0] <= int(r['ring_no']) <= params['ring_range'][1]]
        if params.get('summary_status'):
            openings = [r for r in openings if r['summary_status'] == params['summary_status']]
        equal('开仓总数', data.get('total_openings', 0), len(openings))
        if not openings:
            return
        recent = openings[:params.get('limit', 10)]
        for field, key in [('rings_between_openings', 'rings_between_openings'), ('opening_duration', 'opening_duration_hours')]:
            equal('全部均值 ' + field, data['avg_' + key], _average([r[field] for r in openings]))
            equal('最近均值 ' + field, data['recent_avg_' + key], _average([r[field] for r in recent]))
        for key, population in [('efficiency_all', openings), ('efficiency_recent', recent)]:
            for label, field, count in [('check', 'opening_duration', 'chosen_checked'), ('replace', 'tool_change_duration', 'chosen_replaced')]:
                valid = [r for r in population if r[field] is not None and r[count]]
                denominator = sum(r[count] for r in valid)
                equal(key + ' 分母 ' + label, data[key][label + '_denominator'], denominator)
                equal(key + ' 效率 ' + label, data[key][label + '_minutes_per_tool'], round(sum(r[field] for r in valid) * 60 / denominator, 1) if denominator else None)
        for row, source in zip(data['recent_records'], recent):
            equal('开仓环号', row['ring_no'], source['ring_no'])
            equal('整仓检查数', row['tool_change_total'], source['chosen_checked'])
            equal('整仓更换数', row['tool_change_replaced'], source['chosen_replaced'])
            counts = source['position_replacement_counts']
            equal('单仓全部一次', row['positions_all_once'], bool(counts) and max(counts.values()) == 1)
            for p in row['top_replaced_positions']:
                equal('单仓刀位次数', p['count'], counts[p['cutter_position_no']])
    elif name == 'query_cutter_position_stats':
        equal('刀位观测总体', data.get('total_records', 0), len(rows))
        for row in data.get('top_positions', []):
            expected = _summarize([r for r in rows if r['position'] == row['cutter_position_no']])
            equal('刀位更换数', row['replacement_count'], expected['replaced'])
            equal('刀位异常观测数', row['abnormal_observation_count'], expected['abnormal'])
        if params.get('include_all'):
            expected = [p for p in ACTIVE if not params.get('tool_type') or ('SCRAPER' if p.startswith('S') else 'DISC') == params['tool_type']]
            equal('全部刀位覆盖', len(data['top_positions']), len(expected))
            equal('全部刀位集合', {row['cutter_position_no'] for row in data['top_positions']}, set(expected))
    elif name == 'query_old_tool_repairs':
        ids = {r['id'] for r in rows}
        repairs = [r for r in gold['repairs'] if r['tool_change_detail_id'] in ids]
        for field in ('inspection_status', 'disposition'):
            if params.get(field):
                repairs = [r for r in repairs if r[field] == params[field]]
        fields = {'轴承': 'bearing_failure_reasons', '刀圈': 'ring_damage', '刀毂': 'hub_failure_reasons'}
        if params.get('components'):
            repairs = [r for r in repairs if any(r[fields[c]] for c in params['components'])]
        equal('返修筛选总体', data['scope']['record_count'], len(repairs))
        counts = Counter(r['inspection_status'] for r in repairs)
        for status, count in data['status_counts'].items():
            equal('返修状态 ' + status, count, counts[status])
        confirmed = [r for r in repairs if r['inspection_status'] in ('CONFIRMED', 'CLOSED')]
        equal('确认金额', data['registered_repair_amount']['confirmed_yuan'], float(_sum_money(confirmed, 'repair_price')))
        equal('报废数', data['scrapped_count'], sum(r['disposition'] == 'SCRAP' for r in confirmed))
        equal('报废建议数', data['scrap_suggestion_count'], sum(r['disposition'] == 'SCRAP' and r['inspection_status'] == 'PENDING_VENDOR_FEEDBACK' for r in repairs))
        for reason in data['failure_reasons']:
            field = fields.get(reason['component'])
            expected = sum(reason['reason'] in (r[field] or []) for r in repairs) if field else sum(r[reason['reason']] is True for r in repairs)
            equal('部件原因 ' + reason['component'] + reason['reason'], reason['record_count'], expected)
        positions = Counter(gold['detail_map'][r['tool_change_detail_id']]['position'] for r in repairs)
        equal('全集刀位计数', {r['cutter_position_no']: r['count'] for r in data['position_counts']}, dict(positions))
    elif name in ('recommend_tools', 'compare_manufacturer_service'):
        paired = [r for r in gold['paired'] if not params.get('tool_type') or r['tool_type'] == params['tool_type']]
        if params.get('ring_range'):
            lo, hi = params['ring_range']
            removal_map = {r['id']: r for r in gold['repairs']}
            paired = [r for r in paired if lo <= gold['detail_map'][r['installation_detail_id'] if name == 'recommend_tools' else removal_map[r['removal_id']]['tool_change_detail_id']]['ring'] <= hi]
        if name == 'recommend_tools':
            equal('确认段数', (data.get('service_summary') or {}).get('completed_service_count', 0), len(paired))
            equal('确认总环数', (data.get('service_summary') or {}).get('total_service_rings', 0), sum(r['rings'] for r in paired))
            for row in data.get('recommendations', []) + data.get('insufficient_evidence', []):
                samples = [r['rings'] for r in paired if r['model'] == row['tool_type_name']]
                equal('型号均值 ' + row['tool_type_name'], row['avg_service_rings'], _average(samples))
                expected_prices = sorted((r['manufacturer'], float(r['unit_price'])) for r in quote_rows if r['tool_info__tool_type_name'] == row['tool_type_name'] and r['cost_type'] == 'NEW_TOOL' and r['unit_price'] is not None)
                equal('逐厂家新刀报价', sorted((r['manufacturer'], r['unit_price_yuan']) for r in row['manufacturer_prices']), expected_prices)
                for quote in row['manufacturer_prices']:
                    equal('每环报价', quote['price_per_ring_yuan'], round(quote['unit_price_yuan'] / _average(samples), 2) if samples else None)
            if params.get('sort_by') == 'price_per_ring':
                costs = [r['cost_per_ring_yuan'] for r in data['recommendations'] if r['cost_per_ring_yuan'] is not None]
                equal('每环报价升序', costs, sorted(costs))
        else:
            for row in data['service_by_install_manufacturer'] + data['insufficient_samples']:
                samples = [r for r in paired if r['manufacturer'] == row['manufacturer']]
                equal('厂家服役样本', row['confirmed_segment_count'], len(samples))
                equal('厂家服役均值', row['avg_service_rings'], _average([r['rings'] for r in samples]))
                expected = Counter(r['wear_condition'] for r in samples if (r['wear_condition'] or '').strip().upper() in ABNORMAL)
                equal('厂家异常类型', row['abnormal_types'], dict(expected))
    elif name == 'query_tool_cost_catalog':
        expected = quote_rows
        for param, field in [('tool_type', 'tool_info__tool_parent_type'), ('manufacturer', 'manufacturer'), ('brand', 'brand'), ('cost_type', 'cost_type')]:
            if params.get(param):
                expected = [r for r in expected if r[field] == params[param]]
        if params.get('tool_model'):
            expected = [r for r in expected if r['tool_info__tool_type_name'] == params['tool_model']]
        equal('报价总数', data['scope']['quote_count'], len(expected))
        equal('完整厂家报价条数', sum(len(r['new_tool_prices']) + len(r['repair_prices']) for r in data['by_manufacturer']), len(expected))
        equal('型号厂家覆盖', sorted({(r['tool_model'], r['manufacturer']) for r in data['by_manufacturer']}),
              sorted({(r['tool_info__tool_type_name'], r['manufacturer']) for r in expected}))
    elif name == 'query_tool_inspections':
        active = _scope_rows(params, gold, gold['all_active'])
        selected = [r for r in active if not params.get('check_result') or r['check_result'] == params['check_result']]
        equal('需关注未换数', data['attention_not_replaced']['record_count'], sum(not r['is_replaced'] and r['check_result'] in ('ATTENTION', 'ABNORMAL_NOT_REPLACED') for r in selected))
        equal('未检查数', data['unchecked']['record_count'], sum(not r['is_replaced'] and not r['is_checked'] for r in active))
    elif name in ('query_stratum_area', 'query_stratum_data', 'query_opening_stratum'):
        strata = gold['strata']
        if params.get('ring_range'):
            strata = [r for r in strata if params['ring_range'][0] <= int(r['ring_no']) <= params['ring_range'][1]]
        if name == 'query_stratum_area':
            if params.get('rings'):
                strata = [r for r in strata if int(r['ring_no']) in params['rings']]
            for row in data['classes']:
                values = [float((r['longitudinal_type_ratios'] or {}).get(row['code'], 0)) for r in strata]
                equal('面积占比 ' + row['code'], row['share_pct'], _average(values))
        elif name == 'query_stratum_data':
            equal('地层记录数', data.get('total_records', data.get('total_rings')), len(strata))
        else:
            for row in data['openings']:
                lower, upper = row['interval']
                equal('开仓区间环数', row['interval_area_coverage']['longitudinal_area']['ring_count_requested'], upper - lower + 1)
                for cell in row['interval_summary']['longitudinal_area']:
                    values = [float((r['longitudinal_type_ratios'] or {}).get(cell['code'], 0)) for r in strata if lower <= int(r['ring_no']) <= upper]
                    equal('仓间面积占比', cell['share_pct'], _average(values))
    elif name.startswith('query_tunneling_'):
        tunnel = gold['tunnel']
        if params.get('ring_range'):
            tunnel = [r for r in tunnel if params['ring_range'][0] <= int(r['ring_no']) <= params['ring_range'][1]]
        equal('掘进记录数', data.get('total_records', 0), len(tunnel))
        for field, metrics in data.get('metrics', {}).items():
            if field in ('thrust', 'torque', 'cutterhead_speed', 'penetration', 'advance_speed'):
                equal('掘进均值 ' + field, round(metrics['avg'], 3) if metrics['avg'] is not None else None, _average([r[field] for r in tunnel], 3))
        for segment in data.get('segments', []):
            if 'tool_change_count' in segment:
                lo, hi = map(int, re.findall(r'\d+', segment['ring_range']))
                selected = [r for r in rows if lo <= r['ring'] <= hi]
                equal('掘进关联更换数', segment['replacement_count'], sum(r['is_replaced'] for r in selected))
    elif name == 'analyze_stratum_wear_correlation':
        strata = {int(r['ring_no']): set((r['stratum_type_codes'] or '').split(',')) for r in gold['strata']}
        for row in data['stratum_analysis']:
            selected = [r for r in rows if row['stratum_type'] in strata.get(r['ring'], set())]
            equal('地层关联观测', row['total_records'], len(selected))
            equal('地层关联更换', row['replaced_count'], sum(r['is_replaced'] for r in selected))
    elif name == 'query_position_stratum_impact':
        for row in data['top_positions']:
            equal('地层刀位实际更换', row['replacement_count'], sum(r['is_replaced'] and r['position'] == row['position'] for r in rows))
    elif name == 'query_registered_amounts':
        ids = {r['id'] for r in rows}
        confirmed = [r for r in gold['repairs'] if r['tool_change_detail_id'] in ids and r['inspection_status'] in ('CONFIRMED', 'CLOSED')]
        equal('新装登记金额', data['new_install']['amount_yuan'], float(_sum_money([r for r in rows if r['is_replaced']], 'price')))
        equal('确认返修登记金额', data['confirmed_repair']['amount_yuan'], float(_sum_money(confirmed, 'repair_price')))
    elif name == 'trace_tool_lifecycle':
        for row in data['results']:
            for segment in row['service_segments']:
                if segment['removal_basis'] == 'confirmed':
                    equal('单刀服役环数', segment['service_rings'], segment['removal_ring'] - segment['install_ring'])
                    instance = ToolInstance.objects.get(display_tool_no=row['query'])
                    removals = [r for r in gold['repairs'] if r['confirmed_tool_instance_id'] == instance.pk]
                    equal('独立拆下环', segment['removal_ring'], gold['detail_map'][removals[0]['tool_change_detail_id']]['ring'])
    elif name == 'query_data_catalog':
        coverage = data['data_coverage']
        for key in ('tool_change_observations', 'old_tool_repairs'):
            equal('关联环号覆盖 ' + key, [coverage[key]['ring_min'], coverage[key]['ring_max']], [min(int(r['ring_no']) for r in gold['openings']), max(int(r['ring_no']) for r in gold['openings'])])
            equal('关联时间覆盖 ' + key, [coverage[key]['time_min'], coverage[key]['time_max']], [min(r['open_time'] for r in gold['openings']).isoformat(), max(r['open_time'] for r in gold['openings']).isoformat()])
        equal('开仓读数覆盖', coverage['opening_readings']['count'], reading_count)
        equal('掘进圈数覆盖', coverage['tunneling_revolutions'], revolution_counts)
    elif name == 'query_tool_mileage':
        _verify_mileage(params, data, gold, equal)
    return checks


def _mileage_rows(params, gold):
    removal_by_id = {r['id']: r for r in gold['repairs']}
    wear_amounts = {r['id']: r['blade_wear_amount'] for r in gold['all_active']}
    samples = []
    for pair in gold['paired']:
        before = gold['detail_map'][pair['installation_detail_id']]
        after = gold['detail_map'][removal_by_id[pair['removal_id']]['tool_change_detail_id']]
        if before['position'] != after['position'] or before['type'] != after['type']:
            continue
        if params.get('tool_type') and after['type'] != params['tool_type']:
            continue
        if params.get('manufacturers') and before['manufacturer'] not in params['manufacturers']:
            continue
        if params.get('ring_range') and not params['ring_range'][0] <= after['ring'] <= params['ring_range'][1]:
            continue
        radius = _radius(after['position'])
        km = 2 * math.pi * radius * pair['rings'] * 2000 / REFERENCE_PENETRATION_MM / 1e6
        wear = wear_amounts[after['id']]
        samples.append({'type': after['type'], 'position': after['position'], 'manufacturer': before['manufacturer'],
                        'installation_ring_no': str(before['ring']), 'ring_no': str(after['ring']), 'service_rings': pair['rings'],
                        'band': int(radius // 1000) * 1000, 'km': round(km, 2), 'price': float(before['price']),
                        'wear': round(wear / km * 100, 3) if wear is not None else None,
                        'state': 'abnormal' if after['wear_condition'].strip().upper() in ABNORMAL else 'normal' if after['wear_condition'].strip().upper() in NORMAL else None})
    ids = {r['id'] for r in _scope_rows({key: value for key, value in params.items() if key != 'cutter_position_no'}, gold)}
    removal_rows = [r for r in gold['repairs'] if r['tool_change_detail_id'] in ids]
    exclusions = {'旧刀身份未确认': sum(r['confirmed_tool_instance_id'] is None for r in removal_rows),
                  '厂家反馈未确认': sum(r['confirmed_tool_instance_id'] is not None and r['inspection_status'] not in ('CONFIRMED', 'CLOSED') for r in removal_rows)}
    through = {}
    for opening in gold['openings']:
        if opening['summary_status'] != 'CONFIRMED':
            continue
        if params.get('ring_range') and not params['ring_range'][0] <= int(opening['ring_no']) <= params['ring_range'][1]:
            continue
        key = (opening['project_id'], opening['shield_model_id'])
        through[key] = max(through.get(key, 0), int(opening['ring_no']))
    current = {}
    opening_map = gold['by_opening']
    for row in sorted(gold['observed'], key=lambda r: (r['ring'], opening_map[r['warehouse_id']]['open_time'], r['id'])):
        opening = opening_map[row['warehouse_id']]
        key = (opening['project_id'], opening['shield_model_id'])
        if row['is_replaced'] and opening['summary_status'] == 'CONFIRMED' and key in through and row['ring'] <= through[key]:
            if not params.get('tool_type') or row['type'] == params['tool_type']:
                current[(key, row['type'], row['position'])] = row
    in_service = []
    for (key, _, _), row in current.items():
        if params.get('manufacturers') and row['manufacturer'] not in params['manufacturers']:
            continue
        radius = _radius(row['position'])
        if radius is not None:
            in_service.append({**row, 'band': int(radius // 1000) * 1000,
                               'km': round(2 * math.pi * radius * (through[key] - row['ring']) * 2000 / REFERENCE_PENETRATION_MM / 1e6, 2)})
    return samples, in_service, exclusions


def _verify_mileage(params, data, gold, equal):
    samples, in_service, exclusions = _mileage_rows(params, gold)
    equal('里程已拆段数', data['summary']['removed_count'], len(samples))
    equal('估算占比', data['revolution_basis']['estimated_share'], 1)
    equal('未计入原因和把数', {r['reason']: r['count'] for r in data['excluded']}, {k: v for k, v in exclusions.items() if v})
    equal('未计入总数', data['excluded_count'], sum(exclusions.values()))
    equal('在役把数', data['summary']['in_service_count'], len(in_service))
    for group in data['groups']:
        for band in group['bands']:
            for cell in band['cells']:
                selected = [r for r in samples if r['type'] == group['tool_parent_type'] and r['band'] == band['radius_min'] and r['manufacturer'] == cell['manufacturer']]
                equal('分带厂家段数', cell['removed_count'], len(selected))
                equal('至更换里程分布', cell['life_km'], _spread([r['km'] for r in selected]))
                equal('每百公里磨损', cell['wear_per_100km'], _spread([r['wear'] for r in selected if r['wear'] is not None]))
                equal('每公里成本', cell['cost_per_km'], round(sum(r['price'] for r in selected) / sum(r['km'] for r in selected), 2) if len(selected) >= 5 and sum(r['km'] for r in selected) else None)
                equal('非正常数', cell['abnormal_count'], sum(r['state'] == 'abnormal' for r in selected))
                equal('已分类数', cell['classified_count'], sum(r['state'] is not None for r in selected))
                equal('未分类数', cell['unclassified_count'], sum(r['state'] is None for r in selected))
                current_rows = [r for r in in_service if r['type'] == group['tool_parent_type'] and r['band'] == band['radius_min'] and r['manufacturer'] == cell['manufacturer']]
                equal('分带厂家在役把数', cell['in_service_count'], len(current_rows))
                equal('在役已走里程分布', cell['in_service_km'], _spread([r['km'] for r in current_rows]))
    if data.get('position'):
        position = data['position']
        selected = [r for r in samples if r['position'] == position['cutter_position_no']]
        removed = sum(r['km'] for r in selected)
        active_km = sum(r['km'] for r in in_service if r['position'] == position['cutter_position_no'])
        equal('刀位已拆累计里程', position['removed_km'], round(removed, 2))
        equal('刀位在役已走里程', position['in_service_km'], active_km)
        equal('刀位累计覆盖里程', position['covered_km'], round(removed + active_km, 2))
        fields = ('installation_ring_no', 'ring_no', 'service_rings', 'km', 'manufacturer')
        equal('刀位历次服役段', sorted(tuple(r[k] for k in fields) for r in position['segments']),
              sorted(tuple(r[k] for k in fields) for r in selected))
        starts = [int(r['installation_ring_no']) for r in position['segments']]
        equal('刀位历次按数值环号排序', starts, sorted(starts))
