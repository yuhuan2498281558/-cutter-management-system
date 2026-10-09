"""Per-ring longitudinal area classes explicitly agreed for this project."""
from application.shield.stratum_ratios import validate_stratum_ratios

ZONE_LABELS = {
    'ZONE_CLAY_SAND': '黏土夹砂地层',
    'ZONE_SOFT_HARD': '上软下硬地层',
    'ZONE_WEAK_GRANITE': '全断面弱风化花岗岩',
    'ZONE_BEDROCK_PROTRUSION': '基岩凸起地层',
    'ZONE_SOFT_SOIL': '软土地基',
}
AREA_LABELS = {code.replace('ZONE_', 'AREA_'): label for code, label in ZONE_LABELS.items()}
AREA_LABELS['AREA_BOULDER'] = '孤石'
LONGITUDINAL_LABELS = {
    **AREA_LABELS,
    **ZONE_LABELS,
    'CLAY_SAND': '黏土夹砂地层',
    'SOFT_HARD': '上软下硬地层',
    'SOFT_SOIL': '软土地基',
    'WEAK_GRANITE': '弱风化花岗岩',
    'OTHER_IDENTIFIED': '已识别区域（分类面积待核定）',
    'UNRESOLVED': '未识别区域',
}
CLASSIFICATION_SCHEME = 'annotated_substrata_area_v5'
MATRIX_CONDITIONS = {'CLAY_SAND', 'SOFT_HARD', 'SOFT_SOIL'}


def withhold_condition_derived_ratios(value):
    """A route-level condition label is not evidence of a measured area boundary.

    Preserve old stored estimates for audit, but never serve condition-derived
    percentages as measured engineering-class areas while this is unresolved.
    """
    result = validate_longitudinal_ratios(value)
    unallocated = result.get('OTHER_IDENTIFIED', 0)
    for code in MATRIX_CONDITIONS | {'WEAK_GRANITE'} | ZONE_LABELS.keys():
        unallocated += result.pop(code, 0)
    if unallocated:
        result['OTHER_IDENTIFIED'] = round(unallocated, 6)
    return {code: percent for code, percent in result.items() if percent > 0}


def engineering_zones(value):
    ratios = validate_longitudinal_ratios(value)
    return [{'code': code, 'name': label} for code, label in AREA_LABELS.items()
            if ratios.get(code, 0) > 0]


def longitudinal_area_notes(condition_codes, ratios=None):
    conditions = set(condition_codes)
    notes = []
    zones = engineering_zones(ratios or {})
    if not zones and conditions & (MATRIX_CONDITIONS | {'BEDROCK_PROTRUSION', 'WEAK_GRANITE'}):
        notes.append('工程地质条件的分类面积尚未核定')
    if (ratios or {}).get('AREA_BOULDER'):
        notes.append('孤石按图示轮廓面积估算')
    elif zones and 'BOULDER' in conditions:
        notes.append('有孤石区段记录，本环未取得可计量轮廓交集')
    elif 'BOULDER' in conditions:
        notes.append('孤石：有区段记录，面积尚未核定')
    return notes


def validate_longitudinal_ratios(value):
    result = validate_stratum_ratios(value)
    if set(result) - LONGITUDINAL_LABELS.keys():
        raise ValueError('纵断面占比包含不支持的工程地质分类')
    return result


def longitudinal_class(code, condition_codes=()):
    """Only keep direct weak-rock identification; tags alone do not define areas."""
    conditions = set(condition_codes)
    if code == 'UNRESOLVED':
        return code
    if code == 'WEAKLY_WEATHERED_ROCK':
        return 'WEAK_GRANITE' if 'WEAK_GRANITE' in conditions else 'OTHER_IDENTIFIED'
    # Engineering tags cannot partition pixels without actual class boundaries.
    return 'OTHER_IDENTIFIED'


def validate_condition_alignment(ratios, condition_codes):
    # Historical route tags include overlays and a different ring-axis fit.
    # They cannot validate (or override) the reviewed primary zone geometry.
    if not ratios or set(ratios) - (AREA_LABELS.keys() | {'UNRESOLVED', 'OTHER_IDENTIFIED'}):
        raise ValueError('必须使用按图注子地层及面积边界归并的六类编码，拒绝旧分区归属百分比')
