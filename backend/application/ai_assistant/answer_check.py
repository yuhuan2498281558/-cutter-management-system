"""只读核对本问明确要求的维度，不推断工具未提供的事实。"""
import json
import re

from .answer_reporting import GROUPED_SORT
from .evaluation.answer_checks import _column, _number, _tables


METRICS = (
    (r"观测数|观测记录数", ("total_records", "observation_count", "total"), r"观测|检查|更换"),
    (r"更换数|更换次数|更换", ("replaced_count", "replacement_count", "replaced"), r"更换|换刀"),
    (r"段数|分段数", ("segment_count",), r"段"),
    (r"合计金额|总金额|登记金额合计", ("total_registered_cost_yuan",), r"金额"),
)


def _payloads(tool_results):
    for item in tool_results:
        value = item.get("result", item.get("observation", item))
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                continue
        if isinstance(value, dict) and not value.get("error"):
            yield value


def _walk(value, tool_type):
    if isinstance(value, dict):
        kind = value.get("tool_parent_type", value.get("tool_type"))
        if tool_type and kind in ("DISC", "SCRAPER") and kind != tool_type:
            return
        yield value
        for child in value.values():
            yield from _walk(child, tool_type)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child, tool_type)


def _key(value):
    return re.sub(r"\s*[-–—至]\s*", "-", str(value)).strip().removesuffix("环")


def answer_requirements(question, query_spec, tool_results, generated_tables=()):
    spec = query_spec or {}
    question = question + "\n" + spec.get("effective_query", "")
    payloads = list(_payloads(tool_results))
    manufacturers, objects, summaries, keyed = {}, {}, [], {}
    tool_type = spec.get("tool_type")
    if ("滚刀" in question) != ("刮刀" in question):
        tool_type = "DISC" if "滚刀" in question else "SCRAPER"
    all_objects = bool(re.search(r"全部|所有|每个|逐条|逐把|各型号|按(?:刀位|型号).*列出", question))
    limited = re.search(r"(?:前\s*|最多的\s*|TOP\s*)(\d+)\s*个?刀位", question, re.I)
    top_n = re.search(r"(?:前|TOP)\s*(\d+)\s*(?:个|名|种|家|把|条)", question, re.I)
    # 刀位统计的全集含只有观测的刀位，问"更换过/有异常"等子集时算不准，就不查列全。
    position_filter = re.search(r"更换过|已更换|有更换|未更换|没换|异常|未检查|没检查|需关注|需要关注", question)
    for data in payloads:
        summary = data.get("summary")
        summaries.append({**data, **(summary if isinstance(summary, dict) else {})})
        for node in _walk(data, tool_type):
            for field in ("manufacturer_prices", "new_tool_quotes", "service_by_install_manufacturer",
                          "supply_by_new_manufacturer", "by_manufacturer", "cells", "groups"):
                if "manufacturer_prices" in generated_tables and field in ("manufacturer_prices", "new_tool_quotes"):
                    continue
                for row in node.get(field, []) if isinstance(node.get(field), list) else []:
                    name = row.get("manufacturer")
                    if name and not re.search(r"未知|未能确定|未识别", name):
                        manufacturers.setdefault(name, {name}).add(row.get("brand") or name)
            for field, obj, identity in (("position_counts", "刀位", "cutter_position_no"),
                                         ("top_positions", "刀位", "cutter_position_no"),
                                         ("service_by_model", "型号", "tool_type_name"),
                                         ("recommendations", "型号", "tool_type_name"),
                                         ("records", "旧刀", "old_tool_number"),
                                         ("by_manufacturer", "厂家", "manufacturer")):
                rows = node.get(field)
                requested = all_objects and obj in question
                if field == "position_counts" and re.search(r"列出.*旧刀.*刀位", question):
                    requested = True
                if field == "top_positions" and position_filter:
                    requested = False
                if requested and isinstance(rows, list) and any(identity in row for row in rows):
                    entry = objects.setdefault(obj, {"ids": set(), "total": 0})
                    entry["ids"].update(str(row[identity]) for row in rows if row.get(identity) is not None)
                    total = node.get("_paging", {}).get(field, {}).get("total", 0)
                    if field == "recommendations":
                        total = max(total, node.get("tool_model_count", 0))
                    if field == "records":
                        total = max(total, data.get("scope", {}).get("record_count", 0))
                    if field == "by_manufacturer":
                        total = 0  # 该列表按型号×厂家计行，不能把行数当厂家数。
                    if field == "top_positions":
                        total = max(total, node.get("matched_position_count", 0))
                        if limited:
                            total = min(total, int(limited[1]))
                    entry["total"] = max(entry["total"], total)
            for field, obj in (("ring_range", "环段"), ("cutter_position_no", "刀位"), ("manufacturer", "厂家")):
                if field in node and isinstance(node[field], (str, int)):
                    keyed.setdefault((obj, _key(node[field])), []).append(node)
    order = re.search(r"按([^，。；\n]{1,30}?)(从低到高|从高到低|升序|降序)", question)
    sort = None
    if order:
        metric = re.sub(r"[“”\"\s]|排序|排列", "", order[1])
        sort = (metric, order[2] in ("从高到低", "降序"))
    elif spec.get("sort_by") == "price_per_ring" and "排序" in question:
        sort = ("每环报价", False)
    group = None
    if sort and GROUPED_SORT.search(question):
        # 按组排序：找组名（"各型号内"里的"型号"），认不出就退回常见分组列；都没有时跳过排序检查。
        named = re.search(r"(?:各|每个|每种|每一)([^，。；\n]{1,6}?)(?:内|中|里)", question)
        group = named[1] if named else "型号|刀型|环段"
    return {"manufacturers": manufacturers if re.search(r"逐家|各厂家|按厂家|每家", question) else {},
            "objects": objects, "sort": sort, "group": group, "limit": int(top_n[1]) if top_n else None,
            "summaries": summaries, "keyed": keyed,
            "metrics": [item for item in METRICS if re.search(item[2], question)]}


def _value(facts, fields):
    values = {next((row[k] for k in fields if isinstance(row.get(k), (int, float))), None) for row in facts}
    values.discard(None)
    return next(iter(values)) if len(values) == 1 else None


def _unit_scale(text):
    """表头或数字后的单位换算成元等基本单位的倍数；认不出的单位返回 None，跳过核对。"""
    if "千" in text:
        return None
    return 1e8 if "亿" in text else 1e4 if "万" in text else 1


def _display(value):
    return f"{value:.8f}".rstrip("0").rstrip(".")


def check_final_answer(question, answer, requirements, tool_results) -> list[str]:
    issues, tables = [], _tables(answer)
    names = requirements["manufacturers"]
    # 表格行或正文的一句里出现厂家名并带数字，就算逐家列了；厂家名本身可能带数字，先去掉再看。
    segments = re.split(r"[。；;\n]", answer)
    missing = [name for name, aliases in names.items()
               if not any(alias in segment and re.search(r"\d", segment.replace(alias, ""))
                          for alias in aliases for segment in segments)]
    if missing:
        issues.append(f"没有逐家列出：{'、'.join(missing)}。")
    if requirements["sort"]:
        metric, descending = requirements["sort"]
        for headers, rows in tables:
            col = _column(headers, re.escape(metric))
            group_col = _column(headers, requirements["group"]) if requirements["group"] else None
            if col is None or (requirements["group"] and group_col is None):
                continue
            previous, empty, group = None, None, None
            for row in rows:
                if len(row) != len(headers) or any(cell == "合计" for cell in row):
                    continue
                if group_col is not None and row[group_col] != group:
                    previous, empty, group = None, None, row[group_col]
                current = _number(row[col])
                if current is None:
                    if re.fullmatch(r"暂无|无数据|[—–-]+|N/A", row[col], re.I):
                        empty = row[col]
                    continue
                if empty or (previous is not None and (current > previous if descending else current < previous)):
                    direction = "从高到低" if descending else "从低到高"
                    issues.append(f"“{headers[col]}”没有按{direction}排列：{empty or _display(previous)} 排在 {_display(current)} 前面。")
                    break
                previous = current
    for obj, expected in requirements["objects"].items():
        seen = {_key(row[col]) for headers, rows in tables if (col := _column(headers, obj)) is not None
                for row in rows if len(row) == len(headers) and row[col] not in ("合计", "—", "…", "...")}
        total = max(len(expected["ids"]), expected["total"])
        if requirements["limit"]:
            total = min(total, requirements["limit"])
        # 查看了多少条工具记录，不等于披露回答只列出多少个对象。
        text = answer.replace("**", "")
        disclosed = re.search(rf"(?:只|仅)(?:列出|展示|显示)[^。\n]{{0,12}}(?:前\s*)?\d+\s*(?:个|种|家)?\s*(?:{obj}|[。；\n]|$)", text)
        disclosed = disclosed or re.search(rf"(?:下表|本表)[^。\n]{{0,16}}(?:列出|展示|显示)\s*第\s*\d+\s*页(?:全部)?\s*\d+\s*(?:个|种|家)[^。；\n]{{0,16}}{obj}", text)
        if len(seen) < total and not disclosed:
            issues.append(f"{obj}只列出 {len(seen)} 个，查询结果共有 {total} 个。")
    for headers, rows in tables:
        for row in rows:
            if len(row) != len(headers):
                continue
            facts = []
            for obj in ("环段", "刀位", "厂家"):
                col = _column(headers, obj)
                if col is not None:
                    facts = requirements["keyed"].get((obj, _key(row[col])), [])
                    break
            if "合计" in row or (len(rows) == 1 and not any(re.search("环段|刀位|厂家|型号", h) for h in headers)):
                facts = requirements["summaries"]
            for pattern, fields, _ in requirements["metrics"]:
                for col, header in enumerate(headers):
                    if not re.fullmatch(rf"(?:{pattern})(?:[（(].*?[）)])?", header):
                        continue
                    actual, expected, scale = _number(row[col]), _value(facts, fields), _unit_scale(header + row[col])
                    if actual is None or expected is None or scale is None or abs(actual * scale - expected) < 0.005 * scale:
                        continue
                    expected /= scale
                    observed = _value(facts, ("observation_count", "total_records", "total"))
                    if "更换" in header and actual == observed:
                        issues.append(f"“{header}”列填的是观测数，不是更换数。")
                    else:
                        issues.append(f"“{header}”写的是 {_display(actual)}，查询结果是 {_display(expected)}。")
    prose = "\n".join(line for line in answer.replace("**", "").splitlines() if "|" not in line)
    for pattern, fields, _ in requirements["metrics"]:
        expected = _value(requirements["summaries"], fields)
        if expected is None:
            continue
        # 正文只对独立汇总标签核数，避免把句中的局部统计与全局合计相比。
        prose_pattern = pattern.removesuffix("|更换")
        for match in re.finditer(rf"^(?:[-*]\s*)?({prose_pattern})\s*(?:为|是|共|：|:)?\s*([\d,]+(?:\.\d+)?)(?![\d.%])\s*(千|万|亿)?", prose, re.M):
            actual, scale = _number(match[2]), _unit_scale(match[3] or "")
            if actual is not None and scale is not None and abs(actual * scale - expected) >= 0.005 * scale:
                issues.append(f"“{match[1]}”写的是 {_display(actual)}{match[3] or ''}，查询结果是 {_display(expected / scale)}{match[3] or ''}。")
    if re.search(r"更换|换刀", question):
        for data in _payloads(tool_results):
            count = data.get("matched_position_count")
            replaced = sum(row["count"] for row in data.get("replacement_by_type", []))
            if not count or count != data.get("total_records") or not data.get("replacement_by_type") or replaced == count:
                continue
            ring = data.get("scope", {}).get("ring_range", [])
            scope = f"{ring[0]}–{ring[1]}环" if len(ring) == 2 else ""
            for sentence in re.split(r"[。；\n]", prose):
                mixed = re.search(r"每个刀位[^，。]{0,12}观测[/／]更换\s*1\s*次", sentence)
                universal = re.search(r"各刀位更换次数全部并列\s*1\s*次", sentence)
                if mixed or (universal and len(ring) == 2 and re.search(rf"{ring[0]}\s*[-–—至]\s*{ring[1]}", sentence)):
                    issues.append(f"“{scope}更换数”写的是 {count}，查询结果是 {replaced}。")
                    break
    return list(dict.fromkeys(issues))
