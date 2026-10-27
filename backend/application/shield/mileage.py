"""刀具里程：按刀位轨迹半径和每环刀盘转数，推算服役段走过的周向路程。

里程 = 2π × 轨迹半径 × 区间刀盘总圈数，区间为安装环之后到拆除环 (a, b]。
每环圈数按来源取用（取到哪一级用哪一级）：
1. 掘进数据：2000 mm 环宽 ÷ 该环贯入度（各段按采样点数加权）；
2. 参考值：REFERENCE_PENETRATION_MM，页面标明是估算。
开仓累计读数和掘进计数器（实测）接入后排在掘进推算之前。
"""
import math
import re
from collections import defaultdict
from statistics import quantiles

RING_WIDTH_MM = 2000
# 第 5 环掘进数据的加权贯入度（约 120 圈/环）；甲方给出认可值之前的暂定值
REFERENCE_PENETRATION_MM = 16.67
# 第 5 环各段贯入度的范围，用来说明参考值的敏感程度
REFERENCE_PENETRATION_RANGE_MM = (14, 21)
BAND_WIDTH_MM = 1000
# 样本不少于这个数才给中位数和四分位，否则只列出各段的值
QUARTILE_MIN_SAMPLES = 5
TOOL_TYPE_LABELS = {'DISC': '滚刀', 'SCRAPER': '刮刀'}

BASIS = {
    'mileage': '里程是刀具中心沿轨迹半径走过的周向路程：2π × 轨迹半径 × 服役期间刀盘总圈数，'
               '服役期间为安装环之后到拆除环；不含刀具自转和偏磨。',
    'revolutions': f'每环圈数：有掘进数据的环用 {RING_WIDTH_MM} mm 环宽 ÷ 该环贯入度（按采样点数加权）；'
                   f'其余环按参考贯入度 {REFERENCE_PENETRATION_MM} mm/r（约 {RING_WIDTH_MM / REFERENCE_PENETRATION_MM:.0f} 圈/环）估算，'
                   f'第 5 环实测贯入度在 {REFERENCE_PENETRATION_RANGE_MM[0]}–{REFERENCE_PENETRATION_RANGE_MM[1]} mm/r 之间'
                   f'（约 {RING_WIDTH_MM / REFERENCE_PENETRATION_RANGE_MM[1]:.0f}–{RING_WIDTH_MM / REFERENCE_PENETRATION_RANGE_MM[0]:.0f} 圈/环）。',
    'life': '寿命是已拆刀具的至更换里程，只统计系统已确认配对、且安装与拆除在同一刀位的服役段，不代表总体寿命；'
            '在役刀具单列已走里程，不进寿命统计。',
    'trajectory': f'同一半径的刀位算同一条轨迹；汇总按 {BAND_WIDTH_MM} mm 把相邻轨迹归成一带，可展开到轨迹和刀位。',
    'samples': f'每格不少于 {QUARTILE_MIN_SAMPLES} 段才给中位数和四分位，否则列出各段的值；不排名，不评最佳厂家。',
    'wear_rate': '每百公里磨损 = 拆除时刀刃磨损量 ÷ 段里程 × 100，装刀时刀圈按零磨损计。',
    'cost': f'成本强度 = 同一批已拆段的安装登记价合计 ÷ 里程合计，少于 {QUARTILE_MIN_SAMPLES} 段不给出。',
}


def position_sort_key(code):
    return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', str(code or ''))]


class RingRevolutions:
    """每环刀盘圈数：有掘进数据的环用掘进推算，其余用参考值。"""

    def __init__(self, tunneling_rows):
        """tunneling_rows：(项目 id, 盾构机 id, 环号, 贯入度 mm/r, 采样点数)。"""
        weighted = defaultdict(lambda: [0.0, 0])
        for project, machine, ring, penetration, points in tunneling_rows:
            if penetration and penetration > 0 and str(ring).strip().isdigit():
                cell = weighted[(project, machine, int(ring))]
                cell[0] += penetration * (points or 1)
                cell[1] += points or 1
        self.measured = {key: RING_WIDTH_MM / (total / weight) for key, (total, weight) in weighted.items()}

    def span(self, project, machine, start, end):
        """(start, end] 区间的（总圈数, 其中参考值估算的圈数）。"""
        total = estimated = 0.0
        for ring in range(start + 1, end + 1):
            revolutions = self.measured.get((project, machine, ring))
            if revolutions is None:
                revolutions = RING_WIDTH_MM / REFERENCE_PENETRATION_MM
                estimated += revolutions
            total += revolutions
        return total, estimated


def kilometres(radius_mm, revolutions):
    return 2 * math.pi * radius_mm * revolutions / 1e6


def spread(values):
    """中位数和四分位；样本少时只列出各值。没有样本返回 None。"""
    values = sorted(values)
    if not values:
        return None
    if len(values) < QUARTILE_MIN_SAMPLES:
        return {'count': len(values), 'values': [round(value, 2) for value in values]}
    q1, middle, q3 = quantiles(values, n=4, method='inclusive')
    return {'count': len(values), 'median': round(middle, 2), 'q1': round(q1, 2), 'q3': round(q3, 2)}


def summarize(removed, current):
    """一组已拆段和在役刀具的寿命、磨损、成本和在役情况。"""
    classified = [row for row in removed if row['wear_state'] is not None]
    priced = [row for row in removed if row['price'] is not None]
    priced_km = sum(row['km'] for row in priced)
    return {
        'removed_count': len(removed),
        'life_km': spread([row['km'] for row in removed]),
        'abnormal_count': sum(row['wear_state'] == 'ABNORMAL' for row in classified),
        'classified_count': len(classified),
        'unclassified_count': len(removed) - len(classified),
        'wear_per_100km': spread([row['wear_per_100km'] for row in removed if row['wear_per_100km'] is not None]),
        'priced_count': len(priced),
        'cost_per_km': (round(sum(row['price'] for row in priced) / priced_km, 2)
                        if len(priced) >= QUARTILE_MIN_SAMPLES and priced_km > 0 else None),
        'in_service_count': len(current),
        'in_service_km': spread([row['km'] for row in current]),
    }


def manufacturer_cells(segments, in_service):
    """按厂家汇总；厂家按名称排序，不排名。"""
    names = sorted({row['manufacturer'] for row in segments} | {row['manufacturer'] for row in in_service})
    return [{'manufacturer': name, **summarize(
        [row for row in segments if row['manufacturer'] == name],
        [row for row in in_service if row['manufacturer'] == name],
    )} for name in names]


def group_by_trajectory(segments, in_service):
    """刀型 → 1000 mm 分带 → 轨迹（同一半径的刀位），每层给各厂家的汇总。"""
    groups = []
    for tool_type, label in TOOL_TYPE_LABELS.items():
        typed = [row for row in segments if row['tool_parent_type'] == tool_type]
        typed_service = [row for row in in_service if row['tool_parent_type'] == tool_type]
        if not typed and not typed_service:
            continue
        bands = []
        for lower in sorted({band_lower(row['radius_mm']) for row in typed + typed_service}):
            band = [row for row in typed if band_lower(row['radius_mm']) == lower]
            band_service = [row for row in typed_service if band_lower(row['radius_mm']) == lower]
            trajectories = []
            for radius in sorted({row['radius_mm'] for row in band + band_service}):
                track = [row for row in band if row['radius_mm'] == radius]
                track_service = [row for row in band_service if row['radius_mm'] == radius]
                trajectories.append({
                    'radius_mm': radius,
                    'positions': sorted({row['cutter_position_no'] for row in track + track_service}, key=position_sort_key),
                    'summary': summarize(track, track_service),
                    'cells': manufacturer_cells(track, track_service),
                })
            bands.append({
                'radius_min': lower, 'radius_max': lower + BAND_WIDTH_MM,
                'trajectory_count': len(trajectories),
                'summary': summarize(band, band_service),
                'cells': manufacturer_cells(band, band_service),
                'trajectories': trajectories,
            })
        groups.append({
            'tool_parent_type': tool_type, 'label': label,
            'manufacturers': sorted({row['manufacturer'] for row in typed + typed_service}),
            'summary': summarize(typed, typed_service), 'bands': bands,
        })
    return groups


def band_lower(radius_mm):
    return int(radius_mm // BAND_WIDTH_MM) * BAND_WIDTH_MM


def position_coverage(segments, in_service):
    """每个刀位的已核实覆盖累计里程：已拆段里程加在役已走里程。"""
    rows = {}
    for row in segments + in_service:
        key = (row['tool_parent_type'], row['cutter_position_no'])
        item = rows.setdefault(key, {
            'tool_parent_type': row['tool_parent_type'], 'cutter_position_no': row['cutter_position_no'],
            'radius_mm': row['radius_mm'], 'removed_count': 0, 'removed_km': 0.0, 'in_service_km': None,
        })
        if row.get('in_service'):
            item['in_service_km'] = row['km']
        else:
            item['removed_count'] += 1
            item['removed_km'] += row['km']
    result = []
    for item in rows.values():
        item['covered_km'] = round(item['removed_km'] + (item['in_service_km'] or 0), 2)
        item['removed_km'] = round(item['removed_km'], 2)
        result.append(item)
    return sorted(result, key=lambda item: (item['tool_parent_type'], position_sort_key(item['cutter_position_no'])))
