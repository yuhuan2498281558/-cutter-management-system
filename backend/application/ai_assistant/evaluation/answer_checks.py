"""Targeted checks of rendered answers against independent ORM facts.

This intentionally does not import the production formatter or query helpers.
It checks selected quantitative tables, not the truth of every prose sentence.
"""
import math
import re


def _cells(line):
    text = line.strip().removeprefix("|").removesuffix("|")
    cells, cell, index = [], [], 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text) and text[index + 1] in "\\|":
            index += 1
            cell.append(text[index])
        elif text[index] == "|":
            cells.append("".join(cell).strip().replace("**", ""))
            cell = []
        else:
            cell.append(text[index])
        index += 1
    return cells + ["".join(cell).strip().replace("**", "")]


def _tables(answer):
    lines = answer.splitlines()
    tables = []
    for index in range(len(lines) - 1):
        headers, separator = _cells(lines[index]), _cells(lines[index + 1])
        if len(separator) < 2 or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
            continue
        rows = []
        for line in lines[index + 2:]:
            if "|" not in line or not line.strip():
                break
            rows.append(_cells(line))
        tables.append((headers, rows))
    return tables


def _number(cell):
    match = re.fullmatch(r"\s*([+-]?[\d,]+(?:\.\d+)?)\s*(?:%|条|次|把)?\s*", cell)
    return float(match[1].replace(",", "")) if match else None


def _column(headers, pattern):
    return next((index for index, value in enumerate(headers) if re.search(pattern, value)), None)


def check_answer(tool, answer, expected):
    checks, errors = [], []
    tables = _tables(answer)
    checks.append("table_integrity")
    for headers, rows in tables:
        if any(len(row) != len(headers) for row in rows):
            errors.append("Answer table has a different number of cells than its header")

    if tool not in {"query_tool_change_trend", "compare_manufacturer_performance"}:
        return {"checks": checks, "failures": errors}
    if expected.get("total") == 0 or expected.get("total_records") == 0:
        checks.append("empty_result")
        if not re.search(r"未找到|暂无|没有.*记录|无.*数据", answer):
            errors.append("Empty result is not explicitly identified in the answer")
        return {"checks": checks, "failures": errors}

    trend = tool == "query_tool_change_trend"
    key_pattern = r"环段|环号范围|环范围" if trend else r"厂家|制造商"
    table = next(((headers, rows) for headers, rows in tables
                  if _column(headers, key_pattern) is not None
                  and _column(headers, r"更换次数|已更换|更换[（(]|更换数") is not None), None)
    checks.append("trend_counts_and_rates" if trend else "manufacturer_replacement_counts")
    if table is None:
        errors.append("Answer is missing the quantitative comparison table")
        return {"checks": checks, "failures": errors}
    headers, rows = table
    key_col = _column(headers, key_pattern)
    count_col = _column(headers, r"更换次数|已更换|更换[（(]|更换数")
    wanted = ({segment["ring_range"]: segment for segment in expected["segments"]} if trend
              else expected["manufacturer_replacements"])
    total_col = _column(headers, r"记录数|样本数|记录[（(]|样本量") if trend else None
    rate_col = _column(headers, "更换率") if trend else None
    if trend and (total_col is None or rate_col is None):
        errors.append("Trend table is missing its denominator or replacement rate")
    seen = set()
    for row in rows:
        if len(row) != len(headers):
            continue
        key = re.sub(r"\s*[-–—至]\s*", "-", row[key_col]).replace(" 环", "").removesuffix("环") if trend else row[key_col]
        if key not in wanted or key in seen:
            errors.append(f"Unexpected or repeated answer row: {key}")
            continue
        seen.add(key)
        fact = wanted[key]
        expected_count = fact["replaced"] if trend else fact
        if _number(row[count_col]) != expected_count:
            errors.append(f"Answer replacement count differs from independent facts: {key}")
        if trend and total_col is not None and _number(row[total_col]) != fact["total"]:
            errors.append(f"Answer denominator differs from independent facts: {key}")
        if trend and rate_col is not None and fact["total"]:
            rate = _number(row[rate_col])
            if rate is None or not math.isclose(rate, 100 * fact["replaced"] / fact["total"], abs_tol=0.051):
                errors.append(f"Answer replacement rate differs from independent facts: {key}")
    if len(seen) < min(len(wanted), 12):
        errors.append("Answer omitted expected comparison rows")
    if len(seen) < len(wanted):
        checks.append("truncation_notice")
        if not re.search(r"展示.*(?:前|仅|段|家)|(?:仅|前).*展示|其余|未展示", answer):
            errors.append("Answer truncates the comparison without a disclosure")
    if trend and len(wanted) < 2:
        checks.append("insufficient_trend_evidence")
        if "整体趋势为平稳" in answer or not re.search(r"不足|不能|无法|不支持", answer):
            errors.append("A single segment must not establish a trend")
    return {"checks": checks, "failures": errors}
