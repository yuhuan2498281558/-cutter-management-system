"""刀具里程：按刀位轨迹半径和每环刀盘转数，推算服役段走过的周向路程。

里程 = 2π × 轨迹半径 × 区间刀盘总圈数，区间为安装环之后到拆除环 (a, b]。
圈数按来源逐级取用（取到哪一级用哪一级）：
1. reading：开仓登记的刀盘右转、左转累计读数，与同机下一次有读数的开仓相减（实测）；
2. counter：掘进数据的累计旋转数之差（实测，按环）；
3. integrated：掘进数据推进速度 ÷ 贯入度逐点积分（推算，按环）；
4. reference：参考贯入度 REFERENCE_PENETRATION_MM，页面标明是估算。
读数变小（计数器清零）的区间退到下一级。
"""
import math
import re
from bisect import bisect_right
from collections import defaultdict
from statistics import quantiles

RING_WIDTH_MM = 2000
# 第 5 环掘进数据的加权贯入度（约 120 圈/环）；甲方给出认可值之前的暂定值
REFERENCE_PENETRATION_MM = 16.67
# 第 5 环各段贯入度的范围，用来说明参考值的敏感程度
REFERENCE_PENETRATION_RANGE_MM = (14, 21)
REFERENCE_REVOLUTIONS = RING_WIDTH_MM / REFERENCE_PENETRATION_MM
REVOLUTION_SOURCES = ('reading', 'counter', 'integrated', 'reference')
BAND_WIDTH_MM = 1000
# 样本不少于这个数才给中位数和四分位，否则只列出各段的值
QUARTILE_MIN_SAMPLES = 5
TOOL_TYPE_LABELS = {'DISC': '滚刀', 'SCRAPER': '刮刀'}

BASIS = {
    'mileage': '里程是刀具中心沿轨迹半径走过的周向路程：2π × 轨迹半径 × 服役期间刀盘总圈数，'
               '服役期间为安装环之后到拆除环；不含刀具自转和偏磨。',
    'revolutions': '刀盘圈数按来源逐级取用：开仓登记的右转、左转累计读数与同机下一次有读数的开仓相减；'
                   '其次是掘进数据的累计旋转数之差；再次是掘进数据推进速度 ÷ 贯入度逐点积分（推算）；'
                   f'都没有的环按参考贯入度 {REFERENCE_PENETRATION_MM} mm/r（约 {REFERENCE_REVOLUTIONS:.0f} 圈/环）估算，'
                   f'第 5 环实测贯入度在 {REFERENCE_PENETRATION_RANGE_MM[0]}–{REFERENCE_PENETRATION_RANGE_MM[1]} mm/r 之间'
                   f'（约 {RING_WIDTH_MM / REFERENCE_PENETRATION_RANGE_MM[1]:.0f}–{RING_WIDTH_MM / REFERENCE_PENETRATION_RANGE_MM[0]:.0f} 圈/环）。'
                   '读数变小（计数器清零）的区间退到下一级。',
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
    """服役区间的刀盘圈数，按 REVOLUTION_SOURCES 的顺序逐级取用。"""

    def __init__(self, tunneling_rows, opening_readings=()):
        """tunneling_rows：(项目 id, 盾构机 id, 环号, 计数器圈数, 积分圈数)，每段一行，一环各段都有值才算这一环有；
        opening_readings：(项目 id, 盾构机 id, 环号, 开仓时间, 右转读数, 左转读数)，同一环多次开仓取最后一次。"""
        rings = defaultdict(list)
        for project, machine, ring, counter, integrated in tunneling_rows:
            if str(ring).strip().isdigit():
                rings[(project, machine, int(ring))].append((counter, integrated))
        self.counter = {key: sum(row[0] for row in rows) for key, rows in rings.items() if all(row[0] is not None for row in rows)}
        self.integrated = {key: sum(row[1] for row in rows) for key, rows in rings.items() if all(row[1] is not None for row in rows)}
        self.readings = defaultdict(dict)
        for project, machine, ring, _opened, right, left in sorted(opening_readings, key=lambda row: row[3]):
            if right is not None and left is not None and str(ring).strip().isdigit():
                self.readings[(project, machine)][int(ring)] = (right, left)
        self.reading_rings = {key: sorted(values) for key, values in self.readings.items()}

    def _reading_step(self, machine_key, ring, end):
        """ring 有读数、下一次有读数的开仓不超过 end 且两侧读数都没变小时，返回 (下一次开仓环号, 期间圈数)。"""
        readings = self.readings.get(machine_key, {})
        if ring not in readings:
            return None
        rings = self.reading_rings[machine_key]
        index = bisect_right(rings, ring)
        if index == len(rings) or rings[index] > end:
            return None
        following = rings[index]
        steps = [after - before for before, after in zip(readings[ring], readings[following])]
        return (following, sum(steps)) if min(steps) >= 0 else None

    def span(self, project, machine, start, end):
        """(start, end] 区间各来源的圈数，以及实测部分与积分推算的对照 (实测, 推算)；没有可对照的部分时为 None。"""
        parts = dict.fromkeys(REVOLUTION_SOURCES, 0.0)
        measured = integrated = 0.0
        compared = False
        ring = start
        while ring < end:
            step = self._reading_step((project, machine), ring, end)
            if step:
                following, value = step
                parts['reading'] += value
                integrals = [self.integrated.get((project, machine, item)) for item in range(ring + 1, following + 1)]
                if None not in integrals:
                    measured, integrated, compared = measured + value, integrated + sum(integrals), True
                ring = following
                continue
            ring += 1
            key = (project, machine, ring)
            if key in self.counter:
                parts['counter'] += self.counter[key]
                if key in self.integrated:
                    measured, integrated, compared = measured + self.counter[key], integrated + self.integrated[key], True
            elif key in self.integrated:
                parts['integrated'] += self.integrated[key]
            else:
                parts['reference'] += REFERENCE_REVOLUTIONS
        return parts, ((measured, integrated) if compared else None)


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
