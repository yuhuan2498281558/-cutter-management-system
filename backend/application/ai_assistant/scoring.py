"""实验评分器：严格数值判定 + 幻觉数字率。

设计目标是让"这个回答对不对"变成一个可复现的、二值的判断，而不是关键词包含。

现有回归框架用 must_contain 做子串匹配，存在两类问题：
  1. 单关键词断言几乎恒真（答案里出现"厂家"二字就算通过，排名反了也照样过）；
  2. llm_service._prepend_query_scope 会在答案前自动回显"分析范围：环号范围 100-300"，
     于是断言里的 "100" 是系统自己打印出来的，逻辑上不可能失败。

这里改为：题目自带 gt_sql（独立手写、不复用 tools.py），执行得到真值行；再用
answer_extract 里的正则从答案中抽取对应字段的数值，与真值逐项比较，全部一致才算通过。
"""

import re

# 常见的千分位与单位噪声，抽数前先清掉
_THOUSAND_SEP = re.compile(r"(?<=\d),(?=\d{3}\b)")
# 数值抽取排除嵌在字母数字编号里的数字：刀位号 G3R / S14R 里的 3、14
# 不是数值主张，不应参与幻觉判定（冒烟实验实测踩过这个坑）
_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?![A-Za-z0-9])")

# 允许在答案中自由出现、不计入幻觉判定的数字：
#   0/1 常用于表述，100 用于百分比换算
_ALWAYS_ALLOWED = {0.0, 1.0, 100.0}

# 确定性模板中硬编码的业务阈值（异常率 30%、异常判定系数 1.5）——它们来自代码
# 而非 LLM 生成，出现在答案里不是幻觉（校准实验实测：模板句"异常率超过 30%"被误flag）
_TEMPLATE_CONSTANTS = {30.0, 1.5}

# 明确的"空结果主张"：答案用文字声明查不到记录，等价于主张数量为 0。
# 抽取不到数字且命中这些措辞时，将缺失字段按 0 计。真值确为 0（空结果探针）
# 则判对；真值非 0（如刮刀实有 507 次更换却答"没有记录"）则判错——两个方向
# 都与语义一致，因此作为评分器全局行为而非逐题配置（第四轮校准引入：
# 模板消融组把"检查 0 次、更换 0 次"转述成"未找到换刀记录"被误判为未作答）。
_EMPTY_CLAIM = [
    re.compile(r"未(?:查询|查|找|检索)到[^\n]{0,25}?(?:换刀|更换|开仓|掘进|地层)[^\n]{0,10}?记录"),
    re.compile(r"(?:没有|无|不存在)[^\n]{0,20}?(?:换刀|更换|开仓|掘进|地层)记录"),
    re.compile(r"记录数为?\s*\*{0,2}0\s*条"),
]


def _clean(text: str) -> str:
    return _THOUSAND_SEP.sub("", text or "")


def extract_numbers(text: str) -> set:
    """抽出文本中的全部数值。"""
    return {float(m) for m in _NUMBER.findall(_clean(text))}


def _extract_numbers_with_precision(text: str):
    """抽数并保留小数位数，供舍入感知匹配用。"""
    out = []
    for m in _NUMBER.findall(_clean(text)):
        decimals = len(m.split(".", 1)[1]) if "." in m else 0
        out.append((float(m), decimals))
    return out


def _rounded_match(value: float, decimals: int, allowed) -> bool:
    """答案中的数值与可信来源匹配：允许模板/LLM 对来源值做过合理舍入，
    并允许百分比形态换算（0.075 ↔ 7.5）。
    校准实验实测：模板把工具返回的 11918.6139 印成 11918.614，逐位比对会误判为幻觉。"""
    for a in allowed:
        for candidate in (a, a * 100, a / 100):
            if abs(value - candidate) < 1e-6:
                return True
            if decimals <= 6 and abs(value - round(candidate, decimals)) < 1e-9:
                return True
    return False


def collect_gt_numbers(rows) -> set:
    """把真值查询结果里的全部数值收集成集合（不止被断言的字段）。"""
    values = set()
    for row in rows or []:
        source = row.values() if isinstance(row, dict) else row
        for value in source:
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                values.add(float(value))
            elif isinstance(value, str):
                values |= extract_numbers(value)
    return values


def extract_field(answer: str, pattern):
    """按题目给定的正则从答案中抽一个数值；抽不到返回 None。

    pattern 可以是单条正则，也可以是正则列表（按序尝试，取第一个命中）——
    规则模板与 Agent 自由生成的措辞往往不同（"实际更换 1063 次" vs
    "| 实际更换次数 | **1,063 次** |"），单条正则无法同时覆盖两种口径。"""
    text = _clean(answer or "")
    patterns = pattern if isinstance(pattern, (list, tuple)) else [pattern]
    for p in patterns:
        match = re.search(p, text)
        if match:
            try:
                return float(match.group(1))
            except (IndexError, TypeError, ValueError):
                continue
    return None


def score_answer(answer: str, gt_row: dict, spec: dict) -> dict:
    """逐字段比较答案与真值。

    spec:
        answer_extract: {字段名: 抽取正则（第1个捕获组是数值）}
        tolerance:      {字段名: 允许的绝对误差}，缺省 0（要求完全一致）
    """
    extract_spec = (spec or {}).get("answer_extract") or {}
    tolerance = (spec or {}).get("tolerance") or {}
    if not extract_spec:
        # 没有数值断言的用例（如空结果边界题：只看是否编造数字）——
        # exact_match 记 None（不适用），不能记 False，否则会拉低正确率统计
        return {"exact_match": None, "field_accuracy": None,
                "per_field": {}, "extracted": {}, "missing_fields": []}
    extracted, per_field, missing = {}, {}, []
    empty_claimed = any(p.search(answer or "") for p in _EMPTY_CLAIM)

    for field, pattern in extract_spec.items():
        value = extract_field(answer, pattern)
        if value is None and empty_claimed:
            value = 0.0  # 文字形式的空结果主张 = 主张该数量为 0
        extracted[field] = value
        if value is None:
            per_field[field] = False
            missing.append(field)
            continue
        try:
            truth = float(gt_row.get(field))
        except (TypeError, ValueError):
            per_field[field] = False
            continue
        per_field[field] = abs(value - truth) <= float(tolerance.get(field, 0))

    return {
        "exact_match": bool(per_field) and all(per_field.values()),
        "field_accuracy": (sum(per_field.values()) / len(per_field)) if per_field else None,
        "per_field": per_field,
        "extracted": extracted,
        "missing_fields": missing,
    }


def hallucinated_numbers(answer: str, gt_rows, question: str = "",
                         tool_results=None, extra_allowed=None) -> list:
    """返回答案中出现、但在任何可信来源里都找不到的数字。

    可信来源包括：真值查询结果的全部数值、问题本身出现的数字、工具原始返回里的数值，
    以及百分比换算（x 与 x*100 视为同一来源）。

    工具原始返回来自 llm_service 的调用记录（开 AI_TRACE_TOOL_RESULTS 后随响应返回），
    因此这个指标不需要额外写取数逻辑就能算。
    """
    allowed = set(_ALWAYS_ALLOWED)
    allowed |= collect_gt_numbers(gt_rows)
    allowed |= extract_numbers(question)
    for call in tool_results or []:
        result = call.get("result") if isinstance(call, dict) else call
        if isinstance(result, str):
            allowed |= extract_numbers(result)
    allowed |= _TEMPLATE_CONSTANTS
    allowed |= set(extra_allowed or [])

    flagged = set()
    for value, decimals in _extract_numbers_with_precision(answer):
        if not _rounded_match(value, decimals, allowed):
            flagged.add(value)
    return sorted(flagged)


def score_case(answer: str, gt_rows, spec: dict, question: str = "",
               tool_results=None) -> dict:
    """单条用例的完整评分。"""
    gt_row = (gt_rows or [{}])[0] if gt_rows else {}
    result = score_answer(answer, gt_row, spec)
    fabricated = hallucinated_numbers(
        answer, gt_rows, question=question, tool_results=tool_results
    )
    result.update({
        "hallucinated_numbers": fabricated,
        "has_hallucinated_number": bool(fabricated),
        "gt_row": gt_row,
    })
    return result


def score_routing(response: dict, spec: dict) -> dict:
    """分层指标：路由 / 工具选择 / 工具参数是否符合预期。

    依赖 llm_service.chat() 返回的 route_stage / rule_branch / tool_calls 埋点。
    """
    expected_route = (spec or {}).get("expected_route")
    expected_branch = (spec or {}).get("expected_rule_branch")
    expected_tool = (spec or {}).get("expected_tool")
    expected_args = (spec or {}).get("expected_args") or {}

    calls = response.get("tool_calls") or []
    called_tools = {c.get("tool") for c in calls}

    route_ok = None
    if expected_route:
        route_ok = response.get("route_stage") == expected_route
    branch_ok = None
    if expected_branch:
        branch_ok = response.get("rule_branch") == expected_branch

    tool_ok = None
    arg_ok = None
    if expected_tool:
        tool_ok = expected_tool in called_tools
        if tool_ok and expected_args:
            arg_ok = True
            for call in calls:
                if call.get("tool") != expected_tool:
                    continue
                args = call.get("args") or {}
                arg_ok = all(
                    _args_equal(args.get(key), value)
                    for key, value in expected_args.items()
                )
                if arg_ok:
                    break

    return {
        "route_ok": route_ok,
        "rule_branch_ok": branch_ok,
        "tool_selection_ok": tool_ok,
        "tool_args_ok": arg_ok,
        "called_tools": sorted(t for t in called_tools if t),
    }


def _args_equal(actual, expected) -> bool:
    if isinstance(expected, list) and isinstance(actual, list):
        return [str(x) for x in actual] == [str(x) for x in expected]
    if expected in ("", None):
        return actual in ("", None, [], {})
    return str(actual) == str(expected)
