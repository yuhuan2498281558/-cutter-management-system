"""Cross-section percentages; missing measurements are never imputed."""
import math
from collections import defaultdict

STRATUM_LABELS = {
    'CLAY_SAND': '黏土夹砂地层', 'SOFT_HARD': '上软下硬地层',
    'WEAK_GRANITE': '弱风化花岗岩段（含局部侵入）', 'BEDROCK_PROTRUSION': '基岩凸起地层',
    'SOFT_SOIL': '软土地基', 'BOULDER': '孤石',
    'FILL': '填土、填石', 'FILL_SAND': '填砂',
    'FINE_SAND_2_1': '细砂（2）1-2', 'FINE_SAND_2_5': '细砂（2）5-5',
    'SILTY_CLAY_2_5': '淤泥质/粉质黏土（2）5', 'CLAY_3_3': '黏土（3）3-2',
    'RESIDUAL_SANDY_CLAY': '残积砂质黏性土', 'FULL_WEATHERED_ROCK': '全风化岩',
    'DISINTEGRATED_STRONGLY_WEATHERED_ROCK': '散体状强风化岩',
    'BLOCKY_STRONGLY_WEATHERED_ROCK': '碎块状强风化岩',
    'SILTY_CLAY_3_4': '淤泥质黏土（3）4-1', 'WEAKLY_WEATHERED_ROCK': '弱风化岩',
    'MEDIUM_SAND_3_3': '中砂（3）3-3',
    'CLAY_3_4_2': '黏性土（3）4-2', 'UNRESOLVED': '未识别岩层',
}


def stratum_label(code):
    return STRATUM_LABELS.get(code, code)


def validate_stratum_ratios(value):
    if not isinstance(value, dict):
        raise ValueError("岩层占比必须为编码到百分数的对象")
    result = {}
    for code, percent in value.items():
        if not isinstance(code, str) or not code.strip() or code != code.strip():
            raise ValueError("岩层编码不能为空或包含首尾空格")
        if isinstance(percent, bool) or not isinstance(percent, (int, float)):
            raise ValueError("岩层占比必须为数值")
        if not math.isfinite(percent) or not 0 <= percent <= 100:
            raise ValueError("岩层占比必须在0至100之间")
        result[code] = float(percent)
    if result and not math.isclose(sum(result.values()), 100, abs_tol=0.000001):
        raise ValueError("岩层占比合计必须为100%（未知请使用空对象）")
    return result


def summarize_stratum_exposure(rows, install_ring, remove_ring):
    """Rows must already be scoped to one project; interval is (install, remove]."""
    start, end = int(install_ring), int(remove_ring)
    if end < start:
        raise ValueError("结束环号不能小于安装环号")
    by_ring = {}
    duplicates = set()
    for row in rows:
        try:
            ring = int(row['ring_no'])
        except (KeyError, ValueError, TypeError):
            continue
        if start < ring <= end:
            if ring in by_ring:
                duplicates.add(ring)
            by_ring[ring] = row
    equivalent = defaultdict(float)
    encountered = set()
    engineering_conditions = set()
    invalid = set(duplicates)
    known = 0
    incomplete = 0
    unknown_area = 0.0
    for ring, row in by_ring.items():
        engineering_conditions.update(c.strip() for c in (row.get('stratum_type_codes') or '').split(',') if c.strip())
        if ring in duplicates:
            continue
        try:
            ratios = validate_stratum_ratios(row.get('stratum_type_ratios', {}))
        except ValueError:
            invalid.add(ring)
            continue
        if not ratios:
            continue
        unresolved = ratios.get('UNRESOLVED', 0)
        if unresolved:
            incomplete += 1
            unknown_area += unresolved / 100
        else:
            known += 1
        for code, percent in ratios.items():
            if percent > 0 and code != 'UNRESOLVED':
                encountered.add(code)
                equivalent[code] += percent / 100
    return {
        'equivalent_rings': dict(sorted(equivalent.items())),
        'encountered_codes': sorted(encountered),
        'engineering_condition_codes': sorted(engineering_conditions),
        'known_rings': known,
        'missing_rings': end - start - known,
        'total_rings': end - start,
        'invalid_rings': sorted(invalid),
        'incomplete_rings': incomplete,
        'unknown_area_equivalent_rings': unknown_area + end - start - known - incomplete,
    }
