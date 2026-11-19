"""同条件对照实验的持出题：按信息需求族独立计算真值，并做确定性评分。

真值只读业务表（复用 fixed_suite 的独立 ORM 证据），不调用助手工具、规则或回答核对器。
题目问法由不接触代码的独立会话按需求说明撰写，见 heldout_items.json 的 intent 字段。
"""
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from application.shield.models import NewToolRecord, OldToolRecord, ToolInstance

from .fixed_suite import (ABNORMAL, AREA_LABELS, NORMAL, _average, _collect_evidence,
                          _position_key, _summarize)

TYPE_NAMES = {"DISC": "滚刀", "SCRAPER": "刮刀", None: "全部刀具"}
STATUS_NAMES = {"PENDING_VENDOR_FEEDBACK": "待厂家反馈", "CONFIRMED": "已确认", "CLOSED": "已归档"}
WEAR_LABELS = sorted(NORMAL | ABNORMAL, key=len, reverse=True)
# 平台各处对弱风化花岗岩的写法不一（全断面弱风化花岗岩、弱风化花岗岩段（含局部侵入）），锚点取共同部分
AREA_NAMES = {**AREA_LABELS, "AREA_WEAK_GRANITE": "弱风化花岗岩"}
STRATUM_NAMES = {key.removeprefix("AREA_"): value for key, value in AREA_NAMES.items()}
NO_DATA = re.compile(r"没有|暂无|无法|不具备|未记录|不包含|未包含|没记录|无相关|不能提供|查不到|未查到|不支持|无此类|缺少")


def load_items(name="heldout_items.json"):
    return json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 真值：每个族返回 facts（数值，可带同行锚点）、objects（须出现的对象）、order（须按此顺序出现）
# ---------------------------------------------------------------------------

# 不带锚点的事实：数值所在行或其表头须出现其中一个指标词，免得别处恰好相等的数被算作命中
KEYS = {
    "现场观测记录数": ("观测", "记录", "检查"), "更换数": ("换",), "更换次数": ("换",), "更换率": ("率", "%"),
    "异常记录数": ("异常",), "已分类异常率": ("率", "%", "占比"),
    "开仓时长（小时）": ("开仓", "时长", "小时"), "换刀时长（小时）": ("换刀", "时长", "小时"),
    "距上次开仓环数": ("间隔", "距", "上次", "上一次"), "最长开仓间隔": ("间隔", "最长"),
    "平均每次更换把数": ("平均", "均"), "换下旧刀数": ("旧刀", "换下", "拆"), "已报废": ("报废",), "报废建议": ("报废",),
    "最低报价": ("低", "报价", "元"), "最低新刀报价": ("低",), "最高新刀报价": ("高",), "差价": ("差",),
    "确认返修登记金额": ("金额", "元", "合计"), "轴承失效旧刀数": ("轴承",), "刀圈损坏旧刀数": ("刀圈",),
    "安装环号": ("装",), "拆下环号": ("拆", "换下", "卸"), "服役环数": ("服役", "使用", "寿命", "环"),
    "掘进记录数": ("记录", "条", "掘进"), "覆盖环号": ("环",), "平均推力": ("推力",),
    "更换刀位数": ("刀位", "换", "个"),
}


def _fact(label, value, *anchors, also=()):
    # also：口径确有两种合理读法时，另一种读法的数值也算对
    return {"label": label, "value": float(value), "anchors": [str(a) for a in anchors],
            **({"keys": list(KEYS[label])} if not anchors and label in KEYS else {}),
            **({"also": [float(v) for v in also]} if also else {})}


def _rows(evidence, low=None, high=None, kind=None, position=None, rows=None):
    selected = evidence["observed"] if rows is None else rows
    return [row for row in selected if (low is None or low <= row["ring"] <= high)
            and (not kind or row["type"] == kind) and (not position or row["position"] == position)]


def _classified(rows):
    summary = _summarize(rows)
    abnormal = Counter(row["wear_condition"].strip() for row in rows if row["wear_condition"].strip().upper() in ABNORMAL)
    return summary, abnormal


def _opening(evidence, ring):
    return next(row for row in evidence["openings"] if int(row["ring_no"]) == ring)


def gold_range_change(evidence, low, high, kind=None):
    summary = _summarize(_rows(evidence, low, high, kind))
    return {"facts": [_fact("现场观测记录数", summary["records"]), _fact("更换数", summary["replaced"]),
                      _fact("更换率", summary["replacement_rate_pct"])]}


def gold_range_abnormal(evidence, low, high, kind=None):
    summary, abnormal = _classified(_rows(evidence, low, high, kind))
    facts = [_fact("异常记录数", summary["abnormal"]), _fact("已分类异常率", summary["abnormal_rate_pct"])]
    facts += [_fact(f"{label}次数", count, label) for label, count in sorted(abnormal.items())]
    return {"facts": facts, "objects": sorted(abnormal)}


def gold_opening_detail(evidence, ring):
    opening = _opening(evidence, ring)
    return {"facts": [_fact("开仓时长（小时）", opening["opening_duration"]),
                      _fact("换刀时长（小时）", opening["tool_change_duration"]),
                      _fact("距上次开仓环数", opening["rings_between_openings"])]}


def gold_opening_observed(evidence, ring):
    opening = _opening(evidence, ring)
    rows = [row for row in evidence["observed"] if row["warehouse_id"] == opening["id"]]
    summary = _summarize(rows)
    return {"facts": [_fact("现场观测记录数", summary["records"]), _fact("更换数", summary["replaced"]),
                      _fact("已分类异常率", summary["abnormal_rate_pct"])]}


def gold_opening_longest_interval(evidence):
    longest = max(row["rings_between_openings"] for row in evidence["openings"])
    rings = [row["ring_no"] for row in evidence["openings"] if row["rings_between_openings"] == longest]
    return {"facts": [_fact("最长开仓间隔", longest)], "objects": rings}


def gold_opening_change_over(evidence, count, hours):
    recent = evidence["opening_rows"][:count]
    selected = [row for row in recent if row["tool_change_duration"] > hours]
    return {"facts": [_fact(f"{row['ring_no']}环换刀时长", row["tool_change_duration"], row["ring_no"]) for row in selected],
            "objects": [row["ring_no"] for row in selected]}


def gold_recent_replaced_average(evidence, count):
    recent = evidence["opening_rows"][:count]
    replaced = [sum(row["is_replaced"] for row in evidence["observed"] if row["warehouse_id"] == opening["id"])
                for opening in recent]
    manual = [opening["chosen_replaced"] for opening in recent]
    return {"facts": [_fact("平均每次更换把数", sum(replaced) / len(replaced), also=[sum(manual) / len(manual)])]}


def gold_position_detail(evidence, position):
    summary, abnormal = _classified(_rows(evidence, position=position))
    return {"facts": [_fact("现场观测记录数", summary["records"]), _fact("更换次数", summary["replaced"]),
                      _fact("异常记录数", summary["abnormal"])]}


def gold_position_most_replaced(evidence, kind=None, low=None, high=None):
    counts = Counter(row["position"] for row in _rows(evidence, low, high, kind) if row["is_replaced"])
    peak = max(counts.values())
    tied = sorted((position for position, count in counts.items() if count == peak), key=_position_key)
    return {"facts": [_fact(f"{position}更换次数", peak, position) for position in tied], "objects": tied}


def gold_position_most_abnormal(evidence, kind=None):
    counts = Counter(row["position"] for row in _rows(evidence, kind=kind)
                     if row["wear_condition"].strip().upper() in ABNORMAL)
    peak = max(counts.values())
    tied = sorted((position for position, count in counts.items() if count == peak), key=_position_key)
    return {"facts": [_fact(f"{position}异常次数", peak, position) for position in tied], "objects": tied}


def gold_type_rate_gap(evidence):
    disc, scraper = (_summarize(_rows(evidence, kind=kind))["replacement_rate_pct"] for kind in ("DISC", "SCRAPER"))
    return {"facts": [_fact("滚刀更换率", disc, "滚刀"), _fact("刮刀更换率", scraper, "刮刀")]}


def gold_position_scrapped(evidence, position):
    details = {row["id"] for row in _rows(evidence, position=position) if row["is_replaced"]}
    repairs = [row for row in evidence["repairs"] if row["tool_change_detail_id"] in details]
    confirmed = [row for row in repairs if row["inspection_status"] in ("CONFIRMED", "CLOSED")]
    return {"facts": [_fact("换下旧刀数", len(repairs)), _fact("已报废", sum(row["disposition"] == "SCRAP" for row in confirmed))]}


def gold_supply(evidence, low=None, high=None, kind=None, amount=False):
    groups = defaultdict(list)
    for row in _rows(evidence, low, high, kind):
        if row["is_replaced"]:
            groups[row["manufacturer"]].append(row)
    facts = []
    for manufacturer, rows in sorted(groups.items()):
        facts.append(_fact(f"{manufacturer}供货次数", len(rows), manufacturer))
        if amount:
            facts.append(_fact(f"{manufacturer}登记金额", sum((row["price"] or Decimal(0) for row in rows), Decimal(0)), manufacturer))
    return {"facts": facts, "objects": sorted(groups)}


def _pairs(evidence, kind=None):
    return [row for row in evidence["paired"] if not kind or row["tool_type"] == kind]


def gold_manufacturer_service(evidence, kind=None):
    groups = defaultdict(list)
    for row in _pairs(evidence, kind):
        groups[row["manufacturer"]].append(row)
    facts = []
    for manufacturer, rows in sorted(groups.items()):
        facts.append(_fact(f"{manufacturer}样本数", len(rows), manufacturer))
        facts.append(_fact(f"{manufacturer}平均服役环数", sum(row["rings"] for row in rows) / len(rows), manufacturer))
    return {"facts": facts, "objects": sorted(groups)}


def gold_manufacturer_abnormal(evidence, kind=None):
    groups = defaultdict(list)
    for row in _pairs(evidence, kind):
        groups[row["manufacturer"]].append(row)
    facts = []
    for manufacturer, rows in sorted(groups.items()):
        normal = sum(row["wear_condition"].strip().upper() in NORMAL for row in rows)
        abnormal = sum(row["wear_condition"].strip().upper() in ABNORMAL for row in rows)
        facts.append(_fact(f"{manufacturer}已分类异常率", abnormal / (normal + abnormal) * 100, manufacturer))
    return {"facts": facts, "objects": sorted(groups)}


def gold_model_service(evidence, kind):
    groups = defaultdict(list)
    for row in _pairs(evidence, kind):
        groups[row["model"]].append(row)
    facts = []
    for model, rows in sorted(groups.items()):
        facts.append(_fact(f"{model}样本数", len(rows), model))
        facts.append(_fact(f"{model}平均服役环数", sum(row["rings"] for row in rows) / len(rows), model))
    return {"facts": facts, "objects": sorted(groups)}


def gold_longest_service_manufacturer(evidence, kind, model):
    groups = defaultdict(list)
    for row in _pairs(evidence, kind):
        if row["model"] == model:
            groups[row["manufacturer"]].append(row["rings"])
    eligible = {name: sum(values) / len(values) for name, values in groups.items() if len(values) >= 10}
    best = max(eligible.values())
    winners = sorted(name for name, value in eligible.items() if value == best)
    return {"facts": [_fact("最长平均服役环数", best, *winners[:1]), *[_fact(f"{name}样本数", len(groups[name]), name) for name in winners]],
            "objects": winners}


def _quotes(evidence, model, cost_type):
    return [row for row in evidence["quotes"] if row["tool_info__tool_type_name"] == model
            and row["cost_type"] == cost_type and row["unit_price"] is not None]


def gold_quotes(evidence, model, cost_type="NEW_TOOL"):
    quotes = _quotes(evidence, model, cost_type)
    return {"facts": [_fact(f"{row['manufacturer']}报价", row["unit_price"], row["manufacturer"]) for row in quotes],
            "objects": sorted({row["manufacturer"] for row in quotes})}


def gold_cheapest_quote(evidence, model, cost_type="NEW_TOOL"):
    quotes = _quotes(evidence, model, cost_type)
    low = min(row["unit_price"] for row in quotes)
    winners = sorted({row["manufacturer"] for row in quotes if row["unit_price"] == low})
    return {"facts": [_fact("最低报价", low)], "objects": winners}


def gold_quote_spread(evidence, model):
    prices = [row["unit_price"] for row in _quotes(evidence, model, "NEW_TOOL")]
    return {"facts": [_fact("最低新刀报价", min(prices)), _fact("最高新刀报价", max(prices)),
                      _fact("差价", max(prices) - min(prices))]}


def _repairs(evidence, kind=None, low=None, high=None):
    details = {row["id"] for row in _rows(evidence, low, high, kind) if row["is_replaced"]}
    return [row for row in evidence["repairs"] if row["tool_change_detail_id"] in details]


def gold_repair_status(evidence, kind=None):
    repairs = _repairs(evidence, kind)
    return {"facts": [_fact(label, sum(row["inspection_status"] == status for row in repairs), label)
                      for status, label in STATUS_NAMES.items()]}


def gold_scrap(evidence, kind=None, low=None, high=None):
    repairs = _repairs(evidence, kind, low, high)
    confirmed = [row for row in repairs if row["inspection_status"] in ("CONFIRMED", "CLOSED")]
    return {"facts": [_fact("已报废", sum(row["disposition"] == "SCRAP" for row in confirmed)),
                      _fact("报废建议", sum(row["disposition"] == "SCRAP" and row["inspection_status"] == "PENDING_VENDOR_FEEDBACK"
                                            for row in repairs))]}


def gold_repair_amount(evidence, kind=None):
    confirmed = [row for row in _repairs(evidence, kind) if row["inspection_status"] in ("CONFIRMED", "CLOSED")]
    return {"facts": [_fact("确认返修登记金额", sum((row["repair_price"] or Decimal(0) for row in confirmed), Decimal(0)))]}


def gold_bearing_failures(evidence, kind=None):
    repairs = _repairs(evidence, kind)
    return {"facts": [_fact("轴承失效旧刀数", sum(bool(row["bearing_failure_reasons"]) for row in repairs)),
                      _fact("刀圈损坏旧刀数", sum(bool(row["ring_damage"]) for row in repairs))]}


def _strata(evidence, low, high):
    return [row for row in evidence["strata"] if low <= int(row["ring_no"]) <= high]


def gold_stratum_area(evidence, low, high):
    strata = _strata(evidence, low, high)
    facts = []
    for code, label in AREA_NAMES.items():
        value = _average([float((row["longitudinal_type_ratios"] or {}).get(code, 0)) for row in strata], 6)
        if value and value >= 0.05:
            facts.append(_fact(f"{label}面积占比", value, label))
    return {"facts": facts, "objects": [fact["anchors"][0] for fact in facts]}


def gold_stratum_labels(evidence, low, high):
    counts = Counter(code for row in _strata(evidence, low, high) for code in set(filter(None, row["stratum_type_codes"].split(","))))
    return {"facts": [_fact(f"{STRATUM_NAMES.get(code, code)}环数", count, STRATUM_NAMES.get(code, code)) for code, count in sorted(counts.items())],
            "objects": [STRATUM_NAMES.get(code, code) for code in sorted(counts)]}


def gold_opening_stratum(evidence, ring):
    opening = _opening(evidence, ring)
    earlier = [int(row["ring_no"]) for row in evidence["openings"]
               if row["shield_model_id"] == opening["shield_model_id"] and int(row["ring_no"]) < ring]
    result = gold_stratum_area(evidence, max(earlier, default=0) + 1, ring)
    result["facts"] = [{**fact, "label": "仓间" + fact["label"]} for fact in result["facts"]]
    return result


def gold_trace(evidence, tool_no):
    instance = ToolInstance.objects.get(display_tool_no=tool_no)
    install = NewToolRecord.objects.get(tool_instance=instance)
    removal = OldToolRecord.objects.get(confirmed_tool_instance=instance)
    install_ring = evidence["detail_map"][install.tool_change_detail_id]["ring"]
    removal_ring = evidence["detail_map"][removal.tool_change_detail_id]["ring"]
    return {"facts": [_fact("安装环号", install_ring), _fact("拆下环号", removal_ring),
                      _fact("服役环数", removal_ring - install_ring)],
            "objects": [STATUS_NAMES[removal.inspection_status]]}


def gold_tunneling_coverage(evidence):
    rings = sorted({int(row["ring_no"]) for row in evidence["tunnel"]})
    thrust = [row["thrust"] for row in evidence["tunnel"] if row["thrust"] is not None]
    return {"facts": [_fact("掘进记录数", len(evidence["tunnel"])), _fact("覆盖环号", rings[0]),
                      _fact("平均推力", sum(thrust) / len(thrust))]}


def gold_no_data(evidence):
    return {"facts": [], "no_data": True}


# 第四轮（针对性检验）：要求逐家列出、排序、列全对象的需求。order 为对象的先后，数值相同的并列为一组。

def _order(pairs, descending):
    groups = defaultdict(list)
    for name, value in pairs:
        groups[round(float(value), 6)].append(name)
    return [sorted(groups[value]) for value in sorted(groups, reverse=descending)]


def gold_quotes_sorted(evidence, model, descending=False, cost_type="NEW_TOOL"):
    result = gold_quotes(evidence, model, cost_type)
    result["order"] = _order([(row["manufacturer"], row["unit_price"]) for row in _quotes(evidence, model, cost_type)], descending)
    return result


def gold_supply_sorted(evidence, low=None, high=None, kind=None, descending=True):
    result = gold_supply(evidence, low, high, kind)
    counts = Counter(row["manufacturer"] for row in _rows(evidence, low, high, kind) if row["is_replaced"])
    result["order"] = _order(counts.items(), descending)
    return result


def _pair_groups(evidence, kind, field):
    groups = defaultdict(list)
    for row in _pairs(evidence, kind):
        groups[row[field]].append(row)
    return groups


def gold_manufacturer_service_sorted(evidence, kind=None, descending=True):
    result = gold_manufacturer_service(evidence, kind)
    groups = _pair_groups(evidence, kind, "manufacturer")
    result["order"] = _order([(name, sum(row["rings"] for row in rows) / len(rows)) for name, rows in groups.items()], descending)
    return result


def gold_manufacturer_abnormal_sorted(evidence, kind=None, descending=True):
    result = gold_manufacturer_abnormal(evidence, kind)
    rates = []
    for name, rows in _pair_groups(evidence, kind, "manufacturer").items():
        normal = sum(row["wear_condition"].strip().upper() in NORMAL for row in rows)
        abnormal = sum(row["wear_condition"].strip().upper() in ABNORMAL for row in rows)
        rates.append((name, abnormal / (normal + abnormal) * 100))
    result["order"] = _order(rates, descending)
    return result


def gold_model_service_sorted(evidence, kind=None, descending=True):
    result = gold_model_service(evidence, kind)
    groups = _pair_groups(evidence, kind, "model")
    result["order"] = _order([(name, sum(row["rings"] for row in rows) / len(rows)) for name, rows in groups.items()], descending)
    return result


def gold_opening_replaced_positions(evidence, ring, kind=None):
    opening = _opening(evidence, ring)
    positions = sorted({row["position"] for row in evidence["observed"] if row["warehouse_id"] == opening["id"]
                        and row["is_replaced"] and (not kind or row["type"] == kind)}, key=_position_key)
    return {"facts": [_fact("更换刀位数", len(positions))], "objects": positions}


def gold_position_old_tools(evidence, position):
    details = {row["id"]: row for row in _rows(evidence, position=position) if row["is_replaced"]}
    repairs = [row for row in evidence["repairs"] if row["tool_change_detail_id"] in details]
    facts = [_fact("换下旧刀数", len(repairs))]
    facts += [_fact(f"{row['old_tool_number']}换下环号", details[row["tool_change_detail_id"]]["ring"], row["old_tool_number"])
              for row in repairs]
    return {"facts": facts, "objects": sorted(row["old_tool_number"] for row in repairs)}


def gold_range_position_counts(evidence, low, high, kind="SCRAPER"):
    counts = Counter(row["position"] for row in _rows(evidence, low, high, kind) if row["is_replaced"])
    positions = sorted(counts, key=_position_key)
    return {"facts": [_fact(f"{position}更换次数", counts[position], position) for position in positions],
            "objects": positions}


GOLD = {name.removeprefix("gold_"): value for name, value in globals().items() if name.startswith("gold_")}


def collect_heldout_gold(project_id, items):
    """按题号计算每一轮的真值；同一题多轮各自独立。"""
    evidence = _collect_evidence(project_id)
    result = {}
    for item in items:
        turns = item.get("turns") or [item]
        result[item["id"]] = [GOLD[turn["family"]](evidence, **turn.get("params", {})) for turn in turns]
    return result


# ---------------------------------------------------------------------------
# 评分：数值按回答写出的小数位四舍五入比较；带锚点的数值要和锚点出现在同一行
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"(?<![A-Za-z0-9.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s*(万)?(\s*%)?")


def _numbers(line, percent=False):
    # percent：只取带百分号的数，比率和占比都写成百分数（表头已注明 % 的列除外，由调用方判断）
    values = []
    for match in _NUMBER.finditer(line):
        whole, fraction, wan, pct = match.groups()
        if percent and not pct:
            continue
        value = float(whole.replace(",", "") + ("." + fraction if fraction else ""))
        decimals = len(fraction) if fraction else 0
        values.append((value * 10000 if wan else value, decimals - 4 if wan else decimals))
    return values


def _matches(value, candidate, decimals):
    decimals = max(decimals, -4)
    tolerance = 0.5 * 10 ** (-decimals) + 1e-9
    return abs(candidate - value) <= tolerance


def _anchor_span(anchor, line):
    # 先遮住更长的同类标签（如“刀圈崩刃”之于“崩刃”）再找，刀位编号要求前后不是字母数字
    for longer in WEAR_LABELS:
        if anchor != longer and anchor in longer:
            line = line.replace(longer, "□" * len(longer))
    if re.fullmatch(r"[A-Za-z0-9]+", anchor):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(anchor)}(?![A-Za-z0-9])"
    else:
        # 名称内部允许空白（“可更换式刮刀 H=389”）；厂家名也可只写“·”后的简称
        names = [anchor] + ([anchor.split("·", 1)[1]] if "·" in anchor else [])
        pattern = "|".join(r"\s*".join(map(re.escape, name)) for name in names)
    match = re.search(pattern, line)
    return match.span() if match else None


def _anchor_in(anchor, line):
    return _anchor_span(anchor, line) is not None


def _without_anchors(line, anchors):
    # 去掉锚点本身第一次出现的位置，免得刀位号“10”被当成数值 10
    for anchor in anchors:
        start, end = _anchor_span(anchor, line)
        line = line[:start] + " " + line[end:]
    return line


def _lines(answer):
    # 表格行、列表行各算一行；去掉千分位以外的 Markdown 粗体等记号
    return [line.replace("**", "") for line in (answer or "").splitlines() if line.strip()]


_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}")


def _table_headers(lines):
    """每行所在表格的表头；不在表格里的行为空串。"""
    headers, current = [], ""
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            current = ""
        elif index + 1 < len(lines) and _TABLE_RULE.match(lines[index + 1]):
            current = line
        headers.append(current)
    return headers


def _indicator_words(label):
    if "率" in label or "占比" in label:
        return ("率", "%", "占比", "比例")
    if "平均" in label:
        return ("平均", "均")
    return ()


def _accepts(fact, target, value, decimals, context):
    # 真值带小数而回答写成整数时，所在行或表头须有对应的指标词，免得表里某个计数恰好舍入到均值或比率
    if not _matches(target, value, decimals):
        return False
    if fact.get("keys") and not any(word in context for word in fact["keys"]):
        return False
    words = _indicator_words(fact["label"])
    if words and decimals <= 0 and abs(target - round(target)) > 1e-9:
        return any(word in context for word in words)
    return True


_LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.、)])\s*")


def _blocks(lines):
    """连续的表格行、列表行各成一块；每一行也单独成一块（一句话里依次列出的情况）。"""
    blocks, current, kind = [], [], None
    for line in lines:
        this = "table" if line.lstrip().startswith("|") else "list" if _LIST_ITEM.match(line) else None
        if this != kind:
            if kind and current:
                blocks.append(current)
            current, kind = [], this
        current.append(line)
    if kind and current:
        blocks.append(current)
    return blocks + [[line] for line in lines]


def _first_spot(name, block):
    for row, line in enumerate(block):
        span = _anchor_span(name, line)
        if span:
            return row, span[0]
    return None


def _in_order(lines, groups):
    """有一块文字按要求的先后列出了全部对象即算排对；并列的对象之间先后不限。"""
    for block in _blocks(lines):
        spots = [[_first_spot(name, block) for name in group] for group in groups]
        if any(spot is None for group in spots for spot in group):
            continue
        if all(max(earlier) < min(later) for earlier, later in zip(spots, spots[1:])):
            return True
    return False


def score_turn(answer, gold):
    lines = _lines(answer)
    headers = _table_headers(lines)
    hits, matched = [], []
    for fact in gold.get("facts", []):
        line_hit = next((line for line, header in zip(lines, headers)
                         if all(_anchor_in(anchor, line) for anchor in fact["anchors"])
                         and any(_accepts(fact, target, value, decimals, line + header)
                                 for target in [fact["value"], *fact.get("also", [])]
                                 for value, decimals in _numbers(_without_anchors(line, fact["anchors"]),
                                                                 percent=("率" in fact["label"] or "占比" in fact["label"])
                                                                 and "%" not in header))), None)
        hits.append(line_hit is not None)
        matched.append(line_hit)
    text = "\n".join(lines)
    objects = [obj for obj in gold.get("objects") or [] if not _anchor_in(obj, text)]
    no_data_ok = None
    if gold.get("no_data"):
        no_data_ok = bool(NO_DATA.search(text))
    order_ok = _in_order(lines, gold["order"]) if gold.get("order") else None
    correct = all(hits) and not objects and (no_data_ok is not False) and (order_ok is not False) and bool(text.strip())
    return {"correct": correct, "fact_hits": hits, "matched_lines": matched, "missing_objects": objects, "no_data_ok": no_data_ok,
            **({"order_ok": order_ok} if gold.get("order") else {})}


# ---------------------------------------------------------------------------
# 未溯源数字：回答里的数字在问题和查询结果里都找不到（按回答的小数位四舍五入比较）
# ---------------------------------------------------------------------------

_GENERATED_TABLE = re.compile(r"[#\s]*各厂家新刀报价（系统按查询结果生成）[\s\S]*")
_IGNORED_LINE = re.compile(r"^\s*(?:\d+[.、)]\s|#+\s)")


def untraceable_numbers(answer, sources):
    pool = set()
    for text in sources:
        for value, _ in _numbers(text or ""):
            pool.add(value)
    found, missing = 0, []
    for line in _lines(_GENERATED_TABLE.sub("", answer or "")):
        line = _IGNORED_LINE.sub("", line)
        for value, decimals in _numbers(line):
            if decimals == 0 and value < 10:
                continue  # 个位整数多为序号、数量词，不计
            found += 1
            if not any(_matches(value, source, decimals) or _matches(value * 0.01, source, decimals + 2) for source in pool):
                missing.append(value)
    return found, missing
