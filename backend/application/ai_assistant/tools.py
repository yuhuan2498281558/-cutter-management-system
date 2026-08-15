"""
工具函数 - 提供给LLM调用的数据查询函数
"""

from application.shield.models import (
    ToolChangeDetail, StratumBasicInfo,
    ToolInfo, ToolCost, ToolInstance, NewToolRecord,
    ProjectInfo, WarehouseOpeningBasicInfo,
    ShieldTunnelingData,
)
from django.db.models import Count, Avg, Q, Sum, Max, Min
from django.db.models.functions import Cast
from django.db.models import IntegerField
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 地层类型中文映射（与系统字典数据保持一致）
STRATUM_TYPE_NAMES = {
    'CLAY_SAND':          '黏土夹砂地层',
    'SOFT_HARD':          '上软下硬地层',
    'WEAK_GRANITE':       '全断面弱风化花岗岩',
    'BEDROCK_PROTRUSION': '基岩凸起地层',
    'SOFT_SOIL':          '软土地基',
    'BOULDER':            '孤石',
}

def _build_json(data) -> str:
    return json.dumps(data, ensure_ascii=False)


def _analysis_payload(summary=None, facts=None, highlights=None, warnings=None, conclusion_hint=""):
    return {
        "summary": summary or {},
        "facts": facts or [],
        "highlights": highlights or [],
        "warnings": warnings or [],
        "conclusion_hint": conclusion_hint,
    }


def _pct_to_float(value):
    if value is None:
        return 0.0
    try:
        if isinstance(value, str):
            value = value.strip().rstrip('%')
        return float(value)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# 磨损状态归一化
#
# ToolChangeDetail.wear_condition 是自由 CharField。库中同时存在两类取值：
#   1) models.ToolChangeDetail.WEAR_CONDITION_CHOICES 定义的英文枚举码
#      （GOOD / NORMAL / MODERATE / SEVERE / ABNORMAL）——开仓时由 post_save
#      信号自动建档写入 "NORMAL"（models.py 中 wear_condition="NORMAL"）；
#   2) 人工/移动端录入的中文描述（正常、偏磨、刀圈崩刃 …）。
#
# 本模块此前在三处各用一套互不兼容的判定（== '正常' / 5 个中文枚举集合 /
# not in ('NORMAL','正常')），在不同存储约定下会给出系统性错误的异常磨损率。
# 统一到下面的归一化函数，中英文两套取值都能正确分类，无法识别的取值归入
# 'unknown' 并单独计数，不再被静默算作异常。
# ---------------------------------------------------------------------------
_WEAR_NORMAL_TOKENS = {
    'GOOD', 'NORMAL',
    '正常', '完好', '良好', '正常磨损', '轻微磨损', '未见异常',
}

_WEAR_ABNORMAL_TOKENS = {
    'MODERATE', 'SEVERE', 'ABNORMAL',
    '偏磨', '刀圈崩刃', '崩刃', '刀圈脱落', '脱落', '漏油', '轴承损坏',
    '断裂', '异常磨损', '严重磨损', '中度磨损', '刀圈磨平', '刀体磨损',
}


def normalize_wear_condition(value) -> str:
    """把 wear_condition 归一为 'normal' / 'abnormal' / 'unknown'。"""
    if value is None:
        return 'unknown'
    token = str(value).strip()
    if not token:
        return 'unknown'
    if token in _WEAR_NORMAL_TOKENS or token.upper() in _WEAR_NORMAL_TOKENS:
        return 'normal'
    if token in _WEAR_ABNORMAL_TOKENS or token.upper() in _WEAR_ABNORMAL_TOKENS:
        return 'abnormal'
    return 'unknown'


def is_abnormal_wear(value) -> bool:
    return normalize_wear_condition(value) == 'abnormal'


def is_normal_wear(value) -> bool:
    return normalize_wear_condition(value) == 'normal'


def classify_wear_counts(rows, condition_key='wear_condition', count_key=None) -> dict:
    """对一组磨损记录做三分类计数。

    rows 既可以是 [{'wear_condition': x, 'count': n}, ...] 这种聚合结果
    （传 count_key='count'），也可以是逐条记录（count_key=None，每条计 1）。
    返回 {'normal': int, 'abnormal': int, 'unknown': int}。
    """
    buckets = {'normal': 0, 'abnormal': 0, 'unknown': 0}
    for row in rows or []:
        if isinstance(row, dict):
            value = row.get(condition_key)
            weight = row.get(count_key, 0) if count_key else 1
        else:
            value = row
            weight = 1
        buckets[normalize_wear_condition(value)] += weight or 0
    return buckets


def _merge_analysis(result: dict, summary=None, facts=None, highlights=None, warnings=None, conclusion_hint="") -> dict:
    result.update(_analysis_payload(
        summary=summary,
        facts=facts,
        highlights=highlights,
        warnings=warnings,
        conclusion_hint=conclusion_hint,
    ))
    return result


def _enrich_tool_change_result(result: dict) -> dict:
    total = result.get("total_records", 0) or 0
    replaced = result.get("replaced_count", 0) or 0
    rate = result.get("replacement_rate", "0%")
    wear_distribution = result.get("wear_distribution") or []
    top_positions = result.get("top_replaced_positions") or []
    facts = [
        f"共查询到 {total} 条换刀检查记录",
        f"其中实际更换 {replaced} 次，更换率为 {rate}",
    ]
    highlights = []
    warnings = []
    if wear_distribution:
        top_wear = wear_distribution[0]
        facts.append(f"最多的磨损状态为 {top_wear.get('wear_condition')}，共 {top_wear.get('count')} 条")
        highlights.append(f"磨损状态主要集中在 {top_wear.get('wear_condition')}")
    if top_positions:
        top_pos = top_positions[0]
        highlights.append(f"更换最频繁刀位为 {top_pos.get('cutter_position_no')}，更换 {top_pos.get('replacement_count')} 次")
    if total < 10:
        warnings.append("样本量少于 10 条，统计结论仅作参考")
    return _merge_analysis(
        result,
        summary={"total_records": total, "replaced_count": replaced, "replacement_rate": rate},
        facts=facts,
        highlights=highlights,
        warnings=warnings,
        conclusion_hint="可优先关注高频更换刀位和占比最高的磨损状态，再结合地层与掘进参数判断原因。",
    )


def _enrich_manufacturer_result(result: dict) -> dict:
    manufacturers = result.get("manufacturers") or []
    total = result.get("total_records", 0) or 0
    facts = [
        f"共分析 {total} 条含厂家信息的换刀记录",
        f"覆盖 {result.get('manufacturer_count', len(manufacturers))} 个厂家",
    ]
    highlights = []
    warnings = []
    if manufacturers:
        best = manufacturers[0]
        worst = manufacturers[-1]
        highlights.append(
            f"{best.get('manufacturer')} 异常磨损率最低，为 {best.get('abnormal_rate_pct')}%"
        )
        if len(manufacturers) > 1:
            highlights.append(
                f"{worst.get('manufacturer')} 异常磨损率最高，为 {worst.get('abnormal_rate_pct')}%"
            )
        for item in manufacturers[:5]:
            facts.append(
                f"{item.get('manufacturer')}：更换 {item.get('replaced_count')} 次，异常磨损 {item.get('abnormal_wear_count')} 次，异常磨损率 {item.get('abnormal_rate_pct')}%"
            )
    if total < 20:
        warnings.append("厂家对比样本量偏少，建议结合更多换刀记录复核")
    return _merge_analysis(
        result,
        summary={"total_records": total, "manufacturer_count": len(manufacturers)},
        facts=facts,
        highlights=highlights,
        warnings=warnings,
        conclusion_hint="厂家排序应优先参考异常磨损率，同时结合更换次数和成本，避免只看单次价格。",
    )


def _enrich_stratum_wear_result(result: dict) -> dict:
    strata = result.get("stratum_analysis") or []
    facts = [f"共形成 {len(strata)} 类地层-磨损统计结果"]
    highlights = []
    warnings = []
    if strata:
        top = strata[0]
        highlights.append(
            f"{top.get('stratum_name')} 的更换率最高，为 {top.get('replacement_rate')}"
        )
        for item in strata[:5]:
            facts.append(
                f"{item.get('stratum_name')}：覆盖 {item.get('ring_count')} 环，更换 {item.get('replaced_count')} 次，更换率 {item.get('replacement_rate')}"
            )
    else:
        warnings.append("未形成可排序的地层磨损统计")
    return _merge_analysis(
        result,
        summary={"stratum_count": len(strata)},
        facts=facts,
        highlights=highlights,
        warnings=warnings,
        conclusion_hint="更换率较高的地层可作为刀具选型、备件配置和掘进参数复核的重点区段。",
    )


def _enrich_opening_result(result: dict) -> dict:
    records = result.get("recent_records") or []
    total = result.get("total_openings", 0) or 0
    facts = [
        f"共查询到 {total} 次开仓记录",
        f"平均开仓间隔为 {result.get('avg_rings_between_openings')} 环",
        f"平均开仓时长为 {result.get('avg_opening_duration_hours')} 小时",
    ]
    highlights = []
    warnings = []
    if records:
        highest = max(records, key=lambda item: _pct_to_float(item.get("abnormal_rate")))
        highlights.append(
            f"最近记录中环号 {highest.get('ring_no')} 的异常磨损率最高，为 {highest.get('abnormal_rate')}"
        )
        for item in records[:5]:
            facts.append(
                f"环号 {item.get('ring_no')}：更换 {item.get('tool_change_replaced')}/{item.get('tool_change_total')}，异常率 {item.get('abnormal_rate')}"
            )
    if total < 3:
        warnings.append("开仓次数少于 3 次，难以判断稳定周期")
    return _merge_analysis(
        result,
        summary={"total_openings": total, "recent_count": len(records)},
        facts=facts,
        highlights=highlights,
        warnings=warnings,
        conclusion_hint="开仓分析应同时看开仓间隔、换刀数量和异常磨损率，异常率高的开仓可回溯对应地层与掘进参数。",
    )


def _enrich_cutter_position_result(result: dict) -> dict:
    positions = result.get("top_positions") or []
    total = result.get("total_records", 0) or 0
    facts = [f"共分析 {total} 条换刀记录"]
    highlights = []
    warnings = []
    if positions:
        top = positions[0]
        highlights.append(
            f"更换最频繁刀位为 {top.get('cutter_position_no')}，更换 {top.get('replacement_count')} 次"
        )
        for item in positions[:5]:
            facts.append(
                f"刀位 {item.get('cutter_position_no')}：更换 {item.get('replacement_count')} 次，刀具类型 {item.get('tool_parent_type')}"
            )
    else:
        warnings.append("没有找到实际更换刀位，无法形成高频刀位排序")
    return _merge_analysis(
        result,
        summary={"total_records": total, "position_count": len(positions)},
        facts=facts,
        highlights=highlights,
        warnings=warnings,
        conclusion_hint="高频更换刀位应优先检查安装姿态、局部地层冲击、刀盘受力分布和相邻刀位联动磨损。",
    )


def _round_num(value, digits=3):
    return round(float(value), digits) if value is not None else None


def _parse_ring_range(ring_range):
    if not isinstance(ring_range, list) or len(ring_range) != 2:
        return None
    try:
        start = int(ring_range[0])
        end = int(ring_range[1])
        return [min(start, end), max(start, end)]
    except Exception:
        return None


def _filter_tunneling_query(params: dict):
    query = ShieldTunnelingData.objects.select_related('project', 'shield_machine').all()
    project_id = (params.get('project_id') or '').strip()
    shield_machine_id = params.get('shield_machine_id')
    ring_range = _parse_ring_range(params.get('ring_range', []))
    start_time = params.get('start_time')
    end_time = params.get('end_time')

    if project_id:
        query = query.filter(project__project_id=project_id)
    if shield_machine_id:
        query = query.filter(shield_machine_id=shield_machine_id)
    if ring_range:
        query = query.annotate(ring_int=Cast('ring_no', output_field=IntegerField())).filter(
            ring_int__gte=ring_range[0],
            ring_int__lte=ring_range[1],
        )
    if start_time:
        query = query.filter(record_time__gte=start_time)
    if end_time:
        query = query.filter(record_time__lte=end_time)
    return query


def _summarize_tunneling_records(query):
    total = query.count()
    if total == 0:
        return {
            "message": "未找到符合条件的掘进动态数据",
            "total_records": 0,
        }

    metrics = {
        "thrust": query.aggregate(avg=Avg('thrust'), max=Max('thrust'), min=Min('thrust')),
        "torque": query.aggregate(avg=Avg('torque'), max=Max('torque'), min=Min('torque')),
        "cutterhead_speed": query.aggregate(avg=Avg('cutterhead_speed'), max=Max('cutterhead_speed'), min=Min('cutterhead_speed')),
        "penetration": query.aggregate(avg=Avg('penetration'), max=Max('penetration'), min=Min('penetration')),
    }
    recent = list(query.order_by('-record_time', '-id').values(
        'ring_no', 'thrust', 'torque', 'cutterhead_speed', 'penetration', 'record_time'
    )[:10])
    for item in recent:
        rt = item.get('record_time')
        if isinstance(rt, datetime):
            item['record_time'] = rt.strftime('%Y-%m-%d %H:%M:%S')

    return {
        "total_records": total,
        "ring_range": [
            query.aggregate(min_ring=Min('ring_no'))['min_ring'],
            query.aggregate(max_ring=Max('ring_no'))['max_ring'],
        ],
        "metrics": metrics,
        "recent_records": recent,
    }


def _enrich_tunneling_analysis(data: dict, conclusion_hint: str = "") -> dict:
    total = data.get("total_records", 0) or 0
    if total == 0:
        data.update(_analysis_payload(
            warnings=[data.get("message") or "未找到符合条件的掘进动态数据"],
            conclusion_hint=conclusion_hint or "当前筛选条件下没有可分析的掘进动态记录。",
        ))
        return data

    facts = [f"共查询到 {total} 条掘进动态记录"]
    highlights = []
    warnings = []
    metric_names = {
        "thrust": ("总推力", "kN"),
        "torque": ("刀盘扭矩", "kNm"),
        "cutterhead_speed": ("刀盘转速", "r/min"),
        "penetration": ("贯入力", ""),
    }
    for key, (label, unit) in metric_names.items():
        stat = data.get("metrics", {}).get(key, {})
        avg = _round_num(stat.get("avg"))
        min_value = _round_num(stat.get("min"))
        max_value = _round_num(stat.get("max"))
        if avg is None and min_value is None and max_value is None:
            warnings.append(f"{label}缺少有效数据")
            continue
        facts.append(f"{label}平均值为 {avg}{unit}，范围为 {min_value}-{max_value}{unit}")
        if avg not in (None, 0) and max_value is not None and max_value >= avg * 1.5:
            highlights.append(f"{label}最大值达到平均值的 1.5 倍以上，存在峰值偏高现象")

    if not highlights:
        highlights.append("按平均值和峰值对比，未发现明显突出的掘进参数峰值")

    data.update(_analysis_payload(
        summary={"total_records": total, "ring_range": data.get("ring_range")},
        facts=facts,
        highlights=highlights,
        warnings=warnings,
        conclusion_hint=conclusion_hint or "可结合推力、扭矩、转速和贯入力判断该区段掘进负荷与效率变化。",
    ))
    return data


def _trend_segments(query, interval: int = 50):
    records = list(query.annotate(ring_int=Cast('ring_no', output_field=IntegerField())).values(
        'id', 'ring_int', 'ring_no', 'thrust', 'torque', 'cutterhead_speed', 'penetration',
        'record_time', 'raw_parameters', 'point_count',
    ))
    if not records:
        return []
    ring_values = [r['ring_int'] for r in records if r.get('ring_int') is not None]
    if not ring_values:
        return []

    if len(set(ring_values)) == 1 and len(records) > 1:
        def segment_sort_key(row):
            raw = row.get('raw_parameters') or {}
            return (
                raw.get('segment_index') or 0,
                row.get('record_time') or datetime.min,
                row.get('id') or 0,
            )

        segments = []
        for index, row in enumerate(sorted(records, key=segment_sort_key), start=1):
            raw = row.get('raw_parameters') or {}
            rt = row.get('record_time')
            segments.append({
                "ring_range": str(row.get('ring_no')),
                "segment_index": raw.get('segment_index') or index,
                "segment_count": raw.get('segment_count') or len(records),
                "count": row.get('point_count') or 1,
                "start_time": raw.get('start_time'),
                "end_time": raw.get('end_time') or (rt.strftime('%Y-%m-%d %H:%M:%S') if rt else None),
                "avg_thrust": _round_num(row.get('thrust')),
                "avg_torque": _round_num(row.get('torque')),
                "avg_cutterhead_speed": _round_num(row.get('cutterhead_speed')),
                "avg_penetration": _round_num(row.get('penetration')),
            })
        return segments

    min_ring = min(ring_values)
    max_ring = max(ring_values)
    segments = []
    seg_start = min_ring
    while seg_start <= max_ring:
        seg_end = seg_start + interval - 1
        seg = [r for r in records if r.get('ring_int') is not None and seg_start <= r['ring_int'] <= seg_end]
        if seg:
            def avg(field):
                vals = [x[field] for x in seg if x.get(field) is not None]
                return round(sum(vals) / len(vals), 3) if vals else None
            segments.append({
                "ring_range": f"{seg_start}-{seg_end}",
                "count": len(seg),
                "avg_thrust": avg('thrust'),
                "avg_torque": avg('torque'),
                "avg_cutterhead_speed": avg('cutterhead_speed'),
                "avg_penetration": avg('penetration'),
            })
        seg_start += interval
    return segments


def query_tool_change_data(params_str: str) -> str:
    """
    查询换刀数据

    Args:
        params_str: JSON字符串，格式：
            {
                "project_id": "项目编号",
                "tool_type": "DISC/RIPPER/SCRAPER",  # 可选
                "ring_range": [起始环号, 结束环号],  # 可选
                "cutter_position_no": "刀位编号"     # 可选，查询特定刀位
            }

    Returns:
        JSON字符串，包含统计数据
    """
    try:
        params = json.loads(params_str)
        logger.info(f"查询换刀数据，参数：{params}")

        project_id = params.get('project_id')
        tool_type = params.get('tool_type')
        ring_range = params.get('ring_range', [])
        last_n_openings = params.get('last_n_openings')
        cutter_position_no = params.get('cutter_position_no', '').strip()

        # 构建查询
        query = ToolChangeDetail.objects.select_related(
            'warehouse__project', 'cutter_position'
        )

        # 项目筛选
        if project_id:
            query = query.filter(warehouse__project__project_id=project_id)

        # 刀具类型筛选
        if tool_type:
            query = query.filter(tool_parent_type=tool_type)

        # 特定刀位筛选
        if cutter_position_no:
            query = query.filter(cutter_position_no=cutter_position_no)

        # 最近N次开仓：取最近N条开仓记录的环号范围
        if last_n_openings:
            opening_qs = WarehouseOpeningBasicInfo.objects.annotate(
                ring_int=Cast('ring_no', output_field=IntegerField())
            ).order_by('-ring_int')
            if project_id:
                opening_qs = opening_qs.filter(project__project_id=project_id)
            recent_openings = list(opening_qs.values('ring_no', 'last_ring_no')[:last_n_openings])
            if recent_openings:
                # 取这N次开仓覆盖的环号范围
                ring_nos = [int(o['ring_no']) for o in recent_openings]
                last_ring_nos = [int(o['last_ring_no']) for o in recent_openings if o['last_ring_no']]
                range_min = min(last_ring_nos) + 1 if last_ring_nos else min(ring_nos)
                range_max = max(ring_nos)
                query = query.annotate(
                    ring_int=Cast('warehouse__ring_no', output_field=IntegerField())
                ).filter(ring_int__gte=range_min, ring_int__lte=range_max)

        # 环号范围筛选
        elif ring_range and len(ring_range) == 2:
            query = query.annotate(
                ring_int=Cast('warehouse__ring_no', output_field=IntegerField())
            ).filter(
                ring_int__gte=ring_range[0],
                ring_int__lte=ring_range[1]
            )

        # 统计数据
        total = query.count()

        if total == 0:
            return json.dumps({
                "message": "未找到符合条件的数据",
                "total_records": 0
            }, ensure_ascii=False)

        replaced = query.filter(is_replaced=True).count()

        # 按磨损情况分组
        wear_stats = list(query.values('wear_condition').annotate(
            count=Count('id')
        ).order_by('-count'))

        # 按刀位统计更换次数（取前5个）
        position_stats = list(query.filter(is_replaced=True).values(
            'cutter_position_no'
        ).annotate(
            replacement_count=Count('id')
        ).order_by('-replacement_count')[:5])

        result = {
            "total_records": total,
            "replaced_count": replaced,
            "replacement_rate": f"{replaced/total*100:.1f}%",
            "wear_distribution": wear_stats,
            "top_replaced_positions": position_stats
        }

        logger.info(f"查询成功，返回数据：{result}")
        return json.dumps(_enrich_tool_change_result(result), ensure_ascii=False)

    except json.JSONDecodeError as e:
        error_msg = f"参数格式错误，必须是JSON字符串：{str(e)}"
        logger.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)

    except Exception as e:
        error_msg = f"查询失败：{str(e)}"
        logger.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)


def query_stratum_data(params_str: str) -> str:
    """
    查询地层数据

    Args:
        params_str: JSON字符串，格式：
            {
                "project_id": "项目编号",
                "ring_range": [起始环号, 结束环号]  # 可选
            }

    Returns:
        JSON字符串，包含地层分布数据
    """
    try:
        params = json.loads(params_str)
        logger.info(f"查询地层数据，参数：{params}")

        project_id = params.get('project_id')
        ring_range = params.get('ring_range', [])

        query = StratumBasicInfo.objects.select_related('project')

        if project_id:
            query = query.filter(project__project_id=project_id)

        if ring_range and len(ring_range) == 2:
            query = query.annotate(
                ring_int=Cast('ring_no', output_field=IntegerField())
            ).filter(
                ring_int__gte=ring_range[0],
                ring_int__lte=ring_range[1]
            )

        total_rings = query.count()

        if total_rings == 0:
            return json.dumps({
                "message": "未找到符合条件的地层数据",
                "total_rings": 0
            }, ensure_ascii=False)

        # 统计地层类型分布（带中文名称）
        stratum_distribution = {}
        for item in query:
            types = item.stratum_type_codes.split(',') if item.stratum_type_codes else []
            for t in types:
                t = t.strip()
                if t:
                    name = STRATUM_TYPE_NAMES.get(t, t)
                    key = f"{name}({t})"
                    stratum_distribution[key] = stratum_distribution.get(key, 0) + 1

        result = {
            "total_rings": total_rings,
            "stratum_distribution": stratum_distribution,
            "ring_range": ring_range if ring_range else "全部"
        }

        logger.info(f"查询成功，返回数据：{result}")
        return json.dumps(result, ensure_ascii=False)

    except json.JSONDecodeError as e:
        error_msg = f"参数格式错误，必须是JSON字符串：{str(e)}"
        logger.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)

    except Exception as e:
        error_msg = f"查询失败：{str(e)}"
        logger.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)


def calculate_tool_performance(params_str: str) -> str:
    """
    单把刀的服役追溯：按【刀具实例编号】还原安装环号、拆卸环号、服役环数与磨损检查历史。

    ── 关于统计口径（旧实现在三处口径都是错的，此处一并纠正）──

    ToolChangeDetail.tool_number 是【物理刀实例的流水号】（格式 "{环号}-{刀位}-{序号}"，
    例如 487-S14R-01），由移动端换刀录入时 next_tool_numbers() 生成，写成新装上去那把
    刀的编号；未换刀的检查行则从上一次开仓继承。因此：
      1. 旧实现的 "replacement_count"（该编号下 is_replaced=True 的行数）对一把物理刀
         最多只能是 1，把它当作"累计更换次数"没有意义；
      2. 旧实现的 "avg_rings_between_replacement" 取的是 warehouse.rings_between_openings，
         即【本次开仓距上次开仓的掘进环数】，与这把刀服役了多久毫无关系；
      3. 旧实现 docstring 举例 "T001、T002"，与真实编号格式不符，会诱导模型编造参数。

    现改为对单把刀做生命周期追溯：
      安装环号 = 该编号首次出现且 is_replaced=True 的那一行的环号；
      拆卸环号 = 同刀位、环号大于安装环号的最近一次换刀的环号；
      服役环数 = 拆卸环号 − 安装环号；尚未拆下的刀标记为在役（右删失），不给出服役环数。

    Args:
        params_str: JSON字符串，格式：
            {
                "project_id": "项目编号",
                "tool_numbers": ["487-S14R-01", ...]   # 刀具实例编号，必填
            }

    Returns:
        JSON字符串：{tools: [...], not_found: [...], note: "..."}
    """
    try:
        params = json.loads(params_str)
    except json.JSONDecodeError as e:
        error_msg = f"参数格式错误，必须是JSON字符串：{str(e)}"
        logger.error(error_msg)
        return _build_json({"error": error_msg})

    try:
        logger.info(f"刀具服役追溯，参数：{params}")

        project_id = params.get('project_id')
        tool_numbers = [
            str(number).strip()
            for number in (params.get('tool_numbers') or [])
            if str(number).strip()
        ]
        if not tool_numbers:
            return _build_json({
                "error": "需要提供刀具实例编号（形如 487-S14R-01）。"
                         "若要按刀位统计请用 query_cutter_position_stats，"
                         "若要按型号比较请用 recommend_tools。"
            })

        rows_qs = ToolChangeDetail.objects.filter(
            tool_number__in=tool_numbers
        ).select_related('warehouse')
        if project_id:
            rows_qs = rows_qs.filter(warehouse__project__project_id=project_id)

        rows_by_number = {}
        for row in rows_qs.values(
            'tool_number', 'cutter_position_no', 'tool_parent_type',
            'warehouse__ring_no', 'wear_condition', 'is_replaced',
            'is_checked', 'manufacturer', 'brand', 'price',
        ):
            ring = _ring_int(row.get('warehouse__ring_no'))
            if ring is None:
                continue
            row['ring'] = ring
            rows_by_number.setdefault(row['tool_number'], []).append(row)

        removal_rings = _replacement_rings_by_position(project_id)

        # 型号信息经 ToolInstance.display_tool_no 关联（tool_number 即实例编号）
        instance_map = {}
        for instance in (
            ToolInstance.objects
            .filter(display_tool_no__in=tool_numbers)
            .select_related('tool_info')
        ):
            instance_map.setdefault(instance.display_tool_no, instance)

        tools, not_found = [], []
        for number in tool_numbers:
            rows = sorted(rows_by_number.get(number, []), key=lambda r: r['ring'])
            if not rows:
                not_found.append(number)
                continue

            install_rows = [r for r in rows if r.get('is_replaced')]
            install_inferred = not install_rows
            install_row = install_rows[0] if install_rows else rows[0]
            install_ring = install_row['ring']
            position = install_row.get('cutter_position_no')

            removal_ring = next(
                (r for r in removal_rings.get(position, []) if r > install_ring),
                None,
            )
            service_rings = (
                removal_ring - install_ring
                if removal_ring is not None and removal_ring >= install_ring
                else None
            )

            instance = instance_map.get(number)
            info = getattr(instance, 'tool_info', None)

            inspections = [
                {
                    "ring_no": r['ring'],
                    "wear_condition": r.get('wear_condition'),
                    "wear_class": normalize_wear_condition(r.get('wear_condition')),
                    "is_checked": bool(r.get('is_checked')),
                    "is_replaced": bool(r.get('is_replaced')),
                }
                for r in rows
            ]
            abnormal_inspections = sum(
                1 for item in inspections if item["wear_class"] == 'abnormal'
            )

            tools.append({
                "tool_number": number,
                "cutter_position_no": position,
                "tool_parent_type": install_row.get('tool_parent_type')
                                    or getattr(instance, 'tool_parent_type', None),
                "tool_type_name": (info.tool_type_name if info else None)
                                  or getattr(instance, 'tool_type_name', None),
                "manufacturer": install_row.get('manufacturer'),
                "brand": install_row.get('brand'),
                "price_yuan": float(install_row['price']) if install_row.get('price') is not None else None,
                "install_ring_no": install_ring,
                "install_ring_inferred": install_inferred,
                "removal_ring_no": removal_ring,
                "service_rings": service_rings,
                "status": "在役" if removal_ring is None else "已拆下",
                "inspection_count": len(inspections),
                "abnormal_inspection_count": abnormal_inspections,
                "inspections": inspections[:20],
            })

        result = {
            "tools": tools,
            "not_found": not_found,
            "note": (
                "service_rings = 拆卸环号 − 安装环号。status 为“在役”表示该刀尚未被换下，"
                "其服役环数只知道下界（右删失），因此不给出数值，不可与已拆下的刀直接比较。"
                "install_ring_inferred=true 表示未找到该编号对应的换刀行，安装环号由最早一条"
                "继承记录推断，可能偏晚。"
            ),
        }
        if not_found:
            result["warnings"] = [
                f"未找到编号 {'、'.join(not_found)} 的换刀记录，请确认编号格式（形如 487-S14R-01）"
            ]

        logger.info(f"刀具服役追溯完成：命中 {len(tools)} 把，未找到 {len(not_found)} 把")
        return _build_json(result)

    except Exception as e:
        error_msg = f"服役追溯失败：{str(e)}"
        logger.error(error_msg)
        return _build_json({"error": error_msg})


def _ring_int(value):
    """环号统一转 int，非法值返回 None。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stratum_codes_by_ring(project_id=None) -> dict:
    """返回 {环号(int): {地层代码大写}}，用于按地层筛选服役区间。"""
    qs = StratumBasicInfo.objects.all()
    if project_id:
        qs = qs.filter(project__project_id=project_id)
    mapping = {}
    for row in qs.values('ring_no', 'stratum_type_codes'):
        ring = _ring_int(row.get('ring_no'))
        if ring is None:
            continue
        mapping[ring] = {
            code.strip().upper()
            for code in (row.get('stratum_type_codes') or '').split(',')
            if code.strip()
        }
    return mapping


def _replacement_rings_by_position(project_id=None) -> dict:
    """返回 {刀位编号: [已换刀的环号(int) 升序]}，用于给每次安装配对拆卸环号。"""
    qs = ToolChangeDetail.objects.filter(is_replaced=True).select_related('warehouse')
    if project_id:
        qs = qs.filter(warehouse__project__project_id=project_id)
    buckets = {}
    for row in qs.values('cutter_position_no', 'warehouse__ring_no'):
        ring = _ring_int(row.get('warehouse__ring_no'))
        position = row.get('cutter_position_no')
        if ring is None or not position:
            continue
        buckets.setdefault(position, []).append(ring)
    for rings in buckets.values():
        rings.sort()
    return buckets


def recommend_tools(params_str: str) -> str:
    """
    刀具选型 / 备刀参考：按【刀具型号】统计实例的实际服役环数，服役越久排名越前。

    ── 关于统计口径（这是本工具与旧实现最主要的差别，也是结论能否成立的关键）──

    ToolChangeDetail.tool_number 不是刀具型号，而是【物理刀实例的流水号】：
    移动端换刀录入时由 next_tool_numbers() 生成，格式为 "{环号}-{刀位}-{序号}"
    （例如 487-S14R-01），并被写成【新装上去那把刀】的编号；未换刀的检查行则
    从上一次开仓继承该刀位当前在役刀具的编号。因此：
      - 按 tool_number 分组 = 按单把物理刀分组，每组样本极少，不构成型号选型；
      - 在已换刀的行上，tool_number 指向新装的刀，把这条更换事件计给它，
        等于把上一把刀的报废算到下一把刀头上，语义是反的。

    正确的型号维度是 ToolInfo，经 NewToolRecord → ToolInstance.tool_info 关联。
    单把刀的服役寿命 = 同刀位下一次换刀的环号 − 本次安装的环号（与
    mobile_views.tool_life_info 的口径一致）；尚未被拆下的实例属于右删失
    (right-censored) 样本，不计入均值，但单独计数并在结果中说明。

    Args:
        params_str: JSON字符串，格式：
            {
                "project_id": "项目编号",
                "stratum_types": ["CLAY_SAND", ...],   # 可选，服役区间途经该地层才计入
                "tool_type": "DISC/RIPPER/SCRAPER",    # 可选
                "ring_range": [起始环号, 结束环号],      # 可选，按安装环号筛选
                "max_unit_price": 单价上限（元），       # 可选，旧参数名 budget 仍兼容
                "top_n": 返回条数，默认5，
                "min_samples": 参与排名所需的最少完整服役样本数，默认3
            }

    Returns:
        JSON字符串：{criteria, tool_model_count, ranked_count, recommendations,
                    insufficient_evidence, warnings, note}
    """
    try:
        params = json.loads(params_str)
    except json.JSONDecodeError as e:
        error_msg = f"参数格式错误，必须是JSON字符串：{str(e)}"
        logger.error(error_msg)
        return _build_json({"error": error_msg})

    try:
        logger.info(f"刀具选型参考，参数：{params}")

        project_id = params.get('project_id')
        stratum_types = {
            str(code).strip().upper()
            for code in (params.get('stratum_types') or [])
            if str(code).strip()
        }
        tool_type = (params.get('tool_type') or '').strip().upper()
        parsed_range = _parse_ring_range(params.get('ring_range', []))

        raw_price_cap = params.get('max_unit_price', params.get('budget'))
        try:
            max_unit_price = float(raw_price_cap) if raw_price_cap else None
        except (TypeError, ValueError):
            max_unit_price = None
        if max_unit_price is not None and max_unit_price <= 0:
            max_unit_price = None

        try:
            top_n = max(1, min(int(params.get('top_n') or 5), 50))
        except (TypeError, ValueError):
            top_n = 5
        try:
            min_samples = max(1, int(params.get('min_samples') or 3))
        except (TypeError, ValueError):
            min_samples = 3

        warnings = []
        criteria = {
            "project_id": project_id,
            "stratum_types": sorted(stratum_types) or "全部",
            "tool_type": tool_type or "全部",
            "ring_range": parsed_range or "全部",
            "max_unit_price_yuan": max_unit_price,
            "min_samples": min_samples,
            "rank_metric": "avg_service_rings（平均服役环数），降序",
            "grouping": "ToolInfo（刀具型号），经 NewToolRecord → ToolInstance 关联",
        }

        if tool_type and tool_type not in {'DISC', 'RIPPER', 'SCRAPER'}:
            warnings.append(f"未知的刀具类型 {tool_type}，已忽略该筛选条件")
            tool_type = ''
            criteria["tool_type"] = "全部"

        # 所有安装事件（每条 NewToolRecord = 一把物理刀装到某个刀位）
        installs = (
            NewToolRecord.objects
            .select_related(
                'tool_instance', 'tool_instance__tool_info',
                'tool_change_detail', 'tool_change_detail__warehouse',
            )
        )
        if project_id:
            installs = installs.filter(
                tool_change_detail__warehouse__project__project_id=project_id
            )
        if tool_type:
            installs = installs.filter(tool_instance__tool_parent_type=tool_type)

        install_rows = list(installs)
        if not install_rows:
            return _build_json({
                "message": (
                    "所选范围内没有新刀安装记录（NewToolRecord），无法按型号统计服役寿命。"
                    "该数据由移动端换刀录入流程生成，若尚未启用或历史数据未回补，"
                    "请改用 tool_query_cutter_position_stats 或 "
                    "tool_compare_manufacturer_performance 从刀位/厂家维度分析。"
                ),
                "criteria": criteria,
                "recommendations": [],
                "warnings": warnings,
            })

        removal_rings = _replacement_rings_by_position(project_id)
        stratum_map = _stratum_codes_by_ring(project_id) if stratum_types else {}
        max_known_ring = max(
            [r for rings in removal_rings.values() for r in rings] or [0]
        )

        # 按型号归并
        models_acc = {}
        skipped_no_ring = 0
        skipped_stratum = 0
        skipped_range = 0
        for record in install_rows:
            detail = record.tool_change_detail
            warehouse = getattr(detail, 'warehouse', None)
            install_ring = _ring_int(getattr(warehouse, 'ring_no', None))
            position = getattr(detail, 'cutter_position_no', None)
            if install_ring is None or not position:
                skipped_no_ring += 1
                continue

            if parsed_range and not (parsed_range[0] <= install_ring <= parsed_range[1]):
                skipped_range += 1
                continue

            # 配对拆卸环号：同刀位、环号大于安装环号的最近一次换刀
            removal_ring = next(
                (r for r in removal_rings.get(position, []) if r > install_ring),
                None,
            )
            service_rings = removal_ring - install_ring if removal_ring is not None else None

            # 地层筛选：服役区间途经的地层与所选地层有交集才计入
            if stratum_types:
                span_end = removal_ring if removal_ring is not None else max_known_ring
                passed = set()
                for ring in range(install_ring, max(install_ring, span_end) + 1):
                    passed |= stratum_map.get(ring, set())
                if not (passed & stratum_types):
                    skipped_stratum += 1
                    continue

            instance = record.tool_instance
            info = getattr(instance, 'tool_info', None)
            key = info.id if info else f"__unknown__{getattr(instance, 'tool_parent_type', '') or ''}"
            acc = models_acc.setdefault(key, {
                "tool_info_id": info.id if info else None,
                "tool_type_name": (info.tool_type_name if info else None)
                                  or getattr(instance, 'tool_type_name', None) or "未登记型号",
                "tool_type_code": info.tool_type_code if info else None,
                "tool_parent_type": (info.tool_parent_type if info else None)
                                    or getattr(instance, 'tool_parent_type', None),
                "installed_count": 0,
                "service_samples": [],
                "in_service_count": 0,
            })
            acc["installed_count"] += 1
            if service_rings is not None and service_rings >= 0:
                acc["service_samples"].append(service_rings)
            else:
                acc["in_service_count"] += 1

        if skipped_no_ring:
            warnings.append(f"{skipped_no_ring} 条安装记录因环号或刀位缺失被跳过")
        if skipped_range:
            warnings.append(f"{skipped_range} 条安装记录不在指定环号范围内")
        if skipped_stratum:
            warnings.append(f"{skipped_stratum} 条安装记录的服役区间未途经所选地层")
        if not stratum_types:
            warnings.append("未指定地层类型，统计范围为筛选条件下的全部环号，结果不代表特定地层的适应性")

        if not models_acc:
            return _build_json({
                "message": "筛选条件过窄，没有符合条件的安装记录",
                "criteria": criteria,
                "recommendations": [],
                "warnings": warnings,
            })

        # 取每个型号最新的一条成本记录（ToolInfo.unit_price 属性会产生 N+1 查询）
        cost_map = {}
        info_ids = [v["tool_info_id"] for v in models_acc.values() if v["tool_info_id"]]
        if info_ids:
            for cost in (
                ToolCost.objects.filter(tool_info_id__in=info_ids)
                .order_by('tool_info_id', '-create_datetime')
            ):
                if cost.tool_info_id not in cost_map:
                    cost_map[cost.tool_info_id] = cost

        ranked, insufficient, price_filtered_out = [], [], 0
        for acc in models_acc.values():
            cost = cost_map.get(acc["tool_info_id"])
            unit_price = float(cost.unit_price) if (cost and cost.unit_price is not None) else None

            if max_unit_price is not None:
                if unit_price is None or unit_price > max_unit_price:
                    price_filtered_out += 1
                    continue

            samples = acc["service_samples"]
            entry = {
                "tool_type_name": acc["tool_type_name"],
                "tool_type_code": acc["tool_type_code"],
                "tool_parent_type": acc["tool_parent_type"],
                "installed_count": acc["installed_count"],
                "completed_service_count": len(samples),
                "in_service_count": acc["in_service_count"],
                "avg_service_rings": round(sum(samples) / len(samples), 1) if samples else None,
                "min_service_rings": min(samples) if samples else None,
                "max_service_rings": max(samples) if samples else None,
                "unit_price_yuan": unit_price,
                "manufacturer": cost.manufacturer if cost else None,
                "inventory": cost.inventory if cost else None,
            }
            (ranked if len(samples) >= min_samples else insufficient).append(entry)

        if price_filtered_out:
            warnings.append(
                f"{price_filtered_out} 种型号因单价高于 {max_unit_price:.0f} 元或缺少单价记录被排除"
            )
        if insufficient:
            warnings.append(
                f"{len(insufficient)} 种型号的完整服役样本少于 {min_samples} 把，样本量不足，未参与排名"
            )

        # 平均服役环数降序；相同则完整样本多的优先；再按型号名保证结果可复现
        ranked.sort(key=lambda x: (
            -(x["avg_service_rings"] or 0),
            -x["completed_service_count"],
            str(x["tool_type_name"]),
        ))

        total_ranked = len(ranked)
        for index, entry in enumerate(ranked, start=1):
            entry["rank"] = index
            price_note = (
                f"，单价 {entry['unit_price_yuan']:.0f} 元，"
                f"折合每环 {entry['unit_price_yuan'] / entry['avg_service_rings']:.2f} 元"
                if entry["unit_price_yuan"] and entry["avg_service_rings"] else ""
            )
            entry["cost_per_ring_yuan"] = (
                round(entry["unit_price_yuan"] / entry["avg_service_rings"], 2)
                if entry["unit_price_yuan"] and entry["avg_service_rings"] else None
            )
            entry["recommendation_reason"] = (
                f"在所选范围内共安装 {entry['installed_count']} 把，其中 "
                f"{entry['completed_service_count']} 把已完成服役，平均服役 "
                f"{entry['avg_service_rings']} 环（{entry['min_service_rings']}~"
                f"{entry['max_service_rings']} 环）{price_note}；"
                f"在满足样本量要求的 {total_ranked} 种型号中按平均服役环数由高到低排名第 {index}"
            )
        for entry in insufficient:
            entry["recommendation_reason"] = (
                f"共安装 {entry['installed_count']} 把，仅 {entry['completed_service_count']} 把"
                f"已完成服役（低于 {min_samples} 把），样本量不足以估计平均寿命，仅供参考"
            )
        insufficient.sort(key=lambda x: (-x["completed_service_count"], str(x["tool_type_name"])))

        total_in_service = sum(v["in_service_count"] for v in models_acc.values())
        result = {
            "criteria": criteria,
            "tool_model_count": len(models_acc),
            "ranked_count": total_ranked,
            "recommendations": ranked[:top_n],
            "insufficient_evidence": insufficient[:top_n],
            "warnings": warnings,
            "note": (
                "recommendations 按所选范围内的平均服役环数由高到低排序。"
                f"另有 {total_in_service} 把刀仍在役、尚未拆下，属于右删失样本，"
                "未计入平均值，因此平均服役环数是对真实寿命的保守估计。"
                "该结果基于历史服役记录，不构成对在役刀具剩余寿命的预测。"
            ),
        }

        logger.info(
            f"刀具选型参考完成：型号 {len(models_acc)} 种，参与排名 {total_ranked} 种，"
            f"样本不足 {len(insufficient)} 种，在役未拆 {total_in_service} 把"
        )
        return _build_json(result)

    except Exception as e:
        error_msg = f"选型参考生成失败：{str(e)}"
        logger.error(error_msg)
        return _build_json({"error": error_msg})


def compare_manufacturer_performance(params_str: str) -> str:
    """
    按厂家统计刀具更换数据，用于比较不同厂家的实际表现

    Args:
        params_str: JSON字符串，格式：
            {
                "project_id": "项目编号",  # 可选
                "tool_type": "DISC/RIPPER/SCRAPER",  # 可选
                "ring_range": [起始环号, 结束环号]  # 可选
            }

    Returns:
        JSON字符串，按厂家分组的更换统计
    """
    try:
        params = json.loads(params_str)
        logger.info(f"厂家性能对比，参数：{params}")

        project_id = params.get('project_id')
        tool_type = params.get('tool_type')
        ring_range = params.get('ring_range', [])

        query = ToolChangeDetail.objects.select_related('warehouse__project')

        if project_id:
            query = query.filter(warehouse__project__project_id=project_id)
        if tool_type:
            query = query.filter(tool_parent_type=tool_type)
        if ring_range and len(ring_range) == 2:
            query = query.annotate(
                ring_int=Cast('warehouse__ring_no', output_field=IntegerField())
            ).filter(ring_int__gte=ring_range[0], ring_int__lte=ring_range[1])

        # 过滤掉厂家为空的记录
        query = query.exclude(manufacturer__isnull=True).exclude(manufacturer='')

        total = query.count()
        if total == 0:
            return json.dumps({
                "message": "未找到含厂家信息的换刀记录，可能数据中未录入厂家字段",
                "total_records": 0
            }, ensure_ascii=False)

        # 按厂家分组统计（基于全部记录，不只是已更换的）
        stats = list(
            query.values('manufacturer')
            .annotate(
                total=Count('id'),
                replaced=Count('id', filter=Q(is_replaced=True)),
            )
            .order_by('-replaced')
        )

        result_list = []
        for s in stats:
            total_count = s['total']
            replaced_count = s['replaced']

            # 磨损分布（已更换记录）
            wear_qs = list(
                query.filter(manufacturer=s['manufacturer'], is_replaced=True)
                .values('wear_condition')
                .annotate(count=Count('id'))
                .order_by('-count')
            )

            # 计算异常磨损比例。
            # 旧实现为 abnormal = replaced - (wear_condition == '正常')，即把所有
            # 非中文"正常"的取值（含英文码 NORMAL、含空值）全部算作异常，在英文码
            # 存储下会使异常率恒为 100%。现改为显式三分类计数，未识别的取值单独
            # 计入 unclassified，不再被静默算作异常。
            wear_buckets = classify_wear_counts(wear_qs, count_key='count')
            normal_count = wear_buckets['normal']
            abnormal_count = wear_buckets['abnormal']
            unclassified_count = wear_buckets['unknown']
            classified_total = normal_count + abnormal_count
            abnormal_rate_val = round(abnormal_count / classified_total * 100, 1) if classified_total else 0.0

            # 价格统计
            price_qs = query.filter(
                manufacturer=s['manufacturer']
            ).exclude(price__isnull=True).aggregate(
                total_cost=Sum('price'), avg_cost=Avg('price'), cost_records=Count('id', filter=Q(price__isnull=False))
            )

            result_list.append({
                "manufacturer": s['manufacturer'],
                "replaced_count": replaced_count,
                "normal_wear_count": normal_count,
                "abnormal_wear_count": abnormal_count,
                "unclassified_wear_count": unclassified_count,
                "abnormal_rate_pct": abnormal_rate_val,
                "abnormal_rate_denominator": classified_total,
                "total_cost_yuan": float(price_qs['total_cost']) if price_qs['total_cost'] else None,
                "avg_cost_per_change_yuan": round(float(price_qs['avg_cost']), 0) if price_qs['avg_cost'] else None,
                "wear_breakdown": wear_qs,
            })

        result_list.sort(key=lambda x: x['abnormal_rate_pct'])

        logger.info(f"厂家对比成功，共{len(result_list)}家厂商")
        return json.dumps({
            "total_records": total,
            "manufacturer_count": len(result_list),
            "note": "manufacturers已按abnormal_rate从低到高排序，排名第一的厂家质量最好",
            "manufacturers": result_list
        }, ensure_ascii=False)

    except json.JSONDecodeError as e:
        error_msg = f"参数格式错误，必须是JSON字符串：{str(e)}"
        logger.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)

    except Exception as e:
        error_msg = f"查询失败：{str(e)}"
        logger.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)


def analyze_stratum_wear_correlation(params_str: str) -> str:
    """
    分析地层类型与刀具磨损的关联关系（论文核心工具）

    通过关联地层数据和换刀数据，分析不同地层条件下的刀具磨损规律，
    为刀具选型和施工策略提供数据支撑。

    Args:
        params_str: JSON字符串，格式：
            {
                "project_id": "项目编号",  # 可选
                "tool_type": "DISC/RIPPER/SCRAPER"  # 可选
            }

    Returns:
        JSON字符串，包含地层-磨损关联分析
    """
    try:
        params = json.loads(params_str)
        logger.info(f"地层磨损关联分析，参数：{params}")

        project_id = params.get('project_id')
        tool_type = params.get('tool_type')
        ring_range = params.get('ring_range', [])

        # 1. 获取地层数据
        stratum_query = StratumBasicInfo.objects.select_related('project')
        if project_id:
            stratum_query = stratum_query.filter(project__project_id=project_id)
        if ring_range and len(ring_range) == 2:
            stratum_query = stratum_query.annotate(
                ring_int=Cast('ring_no', output_field=IntegerField())
            ).filter(ring_int__gte=ring_range[0], ring_int__lte=ring_range[1])

        # 2. 获取换刀数据
        change_query = ToolChangeDetail.objects.select_related('warehouse__project')
        if project_id:
            change_query = change_query.filter(warehouse__project__project_id=project_id)
        if tool_type:
            change_query = change_query.filter(tool_parent_type=tool_type)
        if ring_range and len(ring_range) == 2:
            change_query = change_query.annotate(
                ring_int=Cast('warehouse__ring_no', output_field=IntegerField())
            ).filter(ring_int__gte=ring_range[0], ring_int__lte=ring_range[1])

        # 3. 按环号关联地层和换刀数据
        # 先把地层数据建成 ring_no -> stratum_type_codes 的字典，同时统计各地层环数
        stratum_map = {}
        stratum_ring_count = {}  # 每种地层覆盖的环数
        total_rings = 0
        for s in stratum_query:
            if s.stratum_type_codes:
                stratum_map[str(s.ring_no).strip()] = s.stratum_type_codes
                total_rings += 1
                for t in s.stratum_type_codes.split(','):
                    t = t.strip()
                    if t:
                        stratum_ring_count[t] = stratum_ring_count.get(t, 0) + 1

        stratum_wear_map = {}
        stratum_position_map = {}  # 每种地层下各刀位的更换次数

        unknown_stratum_records = 0
        for change in change_query:
            ring_no_val = str(change.warehouse.ring_no).strip()
            codes = stratum_map.get(ring_no_val)
            if not codes:
                # 原实现直接 continue 把整行丢掉：地层表没覆盖到的环号会无声消失，
                # 各地层的更换率分母被悄悄改小，且与看板侧（归入"未填写"桶）口径相反。
                # 这里显式归入"未知地层"，让缺口在答案里可见。
                unknown_stratum_records += 1
                stratum_types = ['未知地层']
            else:
                stratum_types = [t.strip() for t in codes.split(',') if t.strip()]

            for st in stratum_types:
                if st not in stratum_wear_map:
                    stratum_wear_map[st] = {
                        'total_records': 0,
                        'replaced_count': 0,
                        'wear_conditions': {}
                    }
                    stratum_position_map[st] = {}

                stratum_wear_map[st]['total_records'] += 1
                if change.is_replaced:
                    stratum_wear_map[st]['replaced_count'] += 1
                    pos = change.cutter_position_no
                    if pos:
                        stratum_position_map[st][pos] = stratum_position_map[st].get(pos, 0) + 1

                wear = change.wear_condition
                if wear not in stratum_wear_map[st]['wear_conditions']:
                    stratum_wear_map[st]['wear_conditions'][wear] = 0
                stratum_wear_map[st]['wear_conditions'][wear] += 1

        if not stratum_wear_map:
            return json.dumps({
                "message": "未找到地层与换刀的关联数据，可能地层数据不完整",
                "stratum_count": 0
            }, ensure_ascii=False)

        # 4. 计算每种地层的更换率和主要磨损类型
        result_list = []
        for stratum_type, data in stratum_wear_map.items():
            total = data['total_records']
            replaced = data['replaced_count']
            replacement_rate = f"{replaced / total * 100:.1f}%" if total else "0%"

            # 找出主要磨损类型（前3）
            top_wear = sorted(
                data['wear_conditions'].items(),
                key=lambda x: x[1],
                reverse=True
            )[:3]

            # 高频更换刀位（前5）
            top_positions = sorted(
                stratum_position_map.get(stratum_type, {}).items(),
                key=lambda x: x[1], reverse=True
            )[:5]

            result_list.append({
                "stratum_type": stratum_type,
                "stratum_name": STRATUM_TYPE_NAMES.get(stratum_type, stratum_type),
                "ring_count": stratum_ring_count.get(stratum_type, 0),
                "ring_ratio": f"{stratum_ring_count.get(stratum_type, 0)/total_rings*100:.1f}%" if total_rings else "0%",
                "total_records": total,
                "replaced_count": replaced,
                "replacement_rate": replacement_rate,
                "top_wear_conditions": [
                    {"wear_condition": w[0], "count": w[1]}
                    for w in top_wear
                ],
                "top_replaced_positions": [
                    {"position": p[0], "count": p[1]}
                    for p in top_positions
                ],
            })

        # 按更换率排序
        result_list.sort(key=lambda x: float(x['replacement_rate'].rstrip('%')), reverse=True)

        logger.info(f"地层磨损分析成功，共{len(result_list)}种地层")
        return json.dumps({
            "stratum_count": len(result_list),
            "note": "replacement_rate越高说明该地层对刀具磨损越严重，需要更频繁更换刀具",
            # 地层表未覆盖到的换刀记录数：这些行归入"未知地层"，不再静默丢弃
            "unknown_stratum_records": unknown_stratum_records,
            "stratum_analysis": result_list
        }, ensure_ascii=False)

    except json.JSONDecodeError as e:
        error_msg = f"参数格式错误，必须是JSON字符串：{str(e)}"
        logger.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)

    except Exception as e:
        error_msg = f"分析失败：{str(e)}"
        logger.error(error_msg)
        return json.dumps({"error": error_msg}, ensure_ascii=False)


def query_opening_records(params_str: str) -> str:
    """
    查询开仓记录，支持按项目、环号范围过滤，返回开仓次数、平均间隔环数、开仓时长等统计。
    适用于"最近几次开仓"、"平均多少环开一次仓"、"开仓时长"等问题。

    Args:
        params_str: JSON字符串，格式：
            {
                "project_id": "项目编号",
                "ring_range": [起始环号, 结束环号],
                "limit": 返回条数（默认10）
            }
    """
    try:
        params = json.loads(params_str)
        project_id = params.get('project_id')
        ring_range = params.get('ring_range', [])
        limit = params.get('limit', 10)

        query = WarehouseOpeningBasicInfo.objects.select_related('project').annotate(
            ring_int=Cast('ring_no', output_field=IntegerField())
        )
        if project_id:
            query = query.filter(project__project_id=project_id)
        if ring_range and len(ring_range) == 2:
            query = query.filter(ring_int__gte=ring_range[0], ring_int__lte=ring_range[1])

        total = query.count()
        if total == 0:
            return json.dumps({"message": "未找到开仓记录", "total": 0}, ensure_ascii=False)

        # 整体统计
        avg_interval = query.aggregate(avg=Avg('rings_between_openings'))['avg']
        avg_duration = query.aggregate(avg=Avg('opening_duration'))['avg']

        # 按环号数字从大到小取最近N条
        recent_qs = list(
            query.order_by('-ring_int').values(
                'id', 'ring_no', 'last_ring_no', 'rings_between_openings',
                'open_time', 'opening_duration', 'geological_conditions',
                # checked_tool_count / replaced_tool_count 是开仓表上的手填字段，
                # 与真实明细行数长期不一致，不再透传给模型，改用下面按明细派生的
                # tool_change_total / tool_change_replaced。
            )[:limit]
        )

        # 异常磨损判定统一走 normalize_wear_condition，兼容英文枚举码与中文描述。
        # 为每条开仓记录补充换刀统计
        for r in recent_qs:
            if r['open_time']:
                r['open_time'] = r['open_time'].strftime('%Y-%m-%d %H:%M')
            changes = ToolChangeDetail.objects.filter(warehouse_id=r['id'])
            total_c = changes.count()
            replaced_c = changes.filter(is_replaced=True).count()
            r['tool_change_total'] = total_c
            r['tool_change_replaced'] = replaced_c
            r['replacement_rate'] = f"{replaced_c/total_c*100:.1f}%" if total_c else "0%"
            # 磨损分布
            wear_dist = list(
                changes.values('wear_condition').annotate(cnt=Count('id')).order_by('-cnt')
            )
            r['wear_distribution'] = {w['wear_condition']: w['cnt'] for w in wear_dist}
            # 异常磨损率 = 异常条数 / 已分类条数（正常 + 异常）；未识别取值单独计数
            wear_buckets = classify_wear_counts(wear_dist, count_key='cnt')
            abnormal_c = wear_buckets['abnormal']
            classified_c = wear_buckets['normal'] + wear_buckets['abnormal']
            r['abnormal_count'] = abnormal_c
            r['unclassified_wear_count'] = wear_buckets['unknown']
            r['abnormal_rate'] = f"{abnormal_c/classified_c*100:.1f}%" if classified_c else "0%"
            # 高频更换刀位（前3）
            top_pos = list(
                changes.filter(is_replaced=True)
                .values('cutter_position_no')
                .annotate(cnt=Count('id'))
                .order_by('-cnt')[:3]
            )
            r['top_replaced_positions'] = [p['cutter_position_no'] for p in top_pos]
            del r['id']

        return json.dumps({
            "INSTRUCTION": "以下是真实数据库数据，回答时必须原样使用这些数字，禁止修改任何环号、比率或刀位编号",
            "total_openings": total,
            "avg_rings_between_openings": round(avg_interval, 1) if avg_interval else None,
            "avg_opening_duration_hours": round(avg_duration, 1) if avg_duration else None,
            "recent_records": recent_qs,
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"查询失败：{str(e)}"}, ensure_ascii=False)


def query_cutter_position_stats(params_str: str) -> str:
    """
    统计各刀位的磨损和更换情况，找出高频更换刀位和主要磨损类型。
    适用于"哪个刀位最容易坏"、"刀盘磨损分布"、"哪个区域损耗最大"等问题。

    Args:
        params_str: JSON字符串，格式：
            {
                "project_id": "项目编号",
                "tool_type": "DISC/RIPPER/SCRAPER",
                "top_n": 返回前N个刀位（默认10）
            }
    """
    try:
        params = json.loads(params_str)
        project_id = params.get('project_id')
        tool_type = params.get('tool_type')
        top_n = params.get('top_n', 10)

        query = ToolChangeDetail.objects.select_related('warehouse__project')
        if project_id:
            query = query.filter(warehouse__project__project_id=project_id)
        if tool_type:
            query = query.filter(tool_parent_type=tool_type)

        total = query.count()
        if total == 0:
            return json.dumps({"message": "未找到换刀记录", "total": 0}, ensure_ascii=False)

        # 按刀位统计更换次数和磨损分布
        position_stats = list(
            query.filter(is_replaced=True)
            .values('cutter_position_no', 'tool_parent_type')
            .annotate(replacement_count=Count('id'))
            .order_by('-replacement_count')[:top_n]
        )

        # 为每个高频刀位补充磨损类型分布
        for pos in position_stats:
            wear_dist = list(
                query.filter(
                    cutter_position_no=pos['cutter_position_no'],
                    is_replaced=True
                ).values('wear_condition').annotate(count=Count('id')).order_by('-count')
            )
            pos['wear_distribution'] = wear_dist

        # 刀位类型分布（按 tool_parent_type 汇总）
        type_summary = list(
            query.filter(is_replaced=True)
            .values('tool_parent_type')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        return json.dumps({
            "total_records": total,
            "top_positions": position_stats,
            "replacement_by_type": type_summary,
            "note": "replacement_count越高说明该刀位磨损越严重，需重点关注"
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"查询失败：{str(e)}"}, ensure_ascii=False)


def query_tool_change_trend(params_str: str) -> str:
    """
    按环号区间统计换刀趋势，分析掘进过程中刀具损耗是否在增加。
    适用于"换刀频率有没有在增加"、"哪个阶段损耗最大"、"掘进越深是否越损刀"等问题。

    Args:
        params_str: JSON字符串，格式：
            {
                "project_id": "项目编号",
                "tool_type": "DISC/RIPPER/SCRAPER",
                "interval": 每段环数（默认50）
            }
    """
    try:
        params = json.loads(params_str)
        project_id = params.get('project_id')
        tool_type = params.get('tool_type')
        # interval 必须为正整数：为 0 或负数会让下方的分段 while 循环
        # （seg_start += interval）永不递增，导致死循环与无界内存增长。
        # 与 query_tunneling_trend / query_tunneling_wear_correlation 保持一致的钳制范围。
        try:
            interval = int(params.get('interval', 50) or 50)
        except (TypeError, ValueError):
            interval = 50
        interval = max(1, min(interval, 500))

        query = ToolChangeDetail.objects.select_related('warehouse')
        if project_id:
            query = query.filter(warehouse__project__project_id=project_id)
        if tool_type:
            query = query.filter(tool_parent_type=tool_type)

        # 获取所有记录的环号
        records = list(
            query.annotate(
                ring_int=Cast('warehouse__ring_no', output_field=IntegerField())
            ).values('ring_int', 'is_replaced', 'wear_condition')
        )

        if not records:
            return json.dumps({"message": "未找到换刀记录", "total": 0}, ensure_ascii=False)

        # 按区间分组
        min_ring = min(r['ring_int'] for r in records)
        max_ring = max(r['ring_int'] for r in records)

        segments = []
        seg_start = min_ring
        while seg_start <= max_ring:
            seg_end = seg_start + interval - 1
            seg_records = [r for r in records if seg_start <= r['ring_int'] <= seg_end]
            replaced = sum(1 for r in seg_records if r['is_replaced'])
            segments.append({
                "ring_range": f"{seg_start}-{seg_end}",
                "total": len(seg_records),
                "replaced": replaced,
                "replacement_rate": f"{replaced/len(seg_records)*100:.1f}%" if seg_records else "0%",
            })
            seg_start += interval

        # 判断趋势
        rates = [float(s['replacement_rate'].rstrip('%')) for s in segments if s['total'] > 0]
        trend = "上升" if len(rates) >= 2 and rates[-1] > rates[0] else "下降" if len(rates) >= 2 and rates[-1] < rates[0] else "平稳"

        return json.dumps({
            "ring_range": f"{min_ring}-{max_ring}",
            "interval": interval,
            "trend": trend,
            "segments": segments,
            "note": f"换刀率整体呈{trend}趋势，interval={interval}环/段"
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"查询失败：{str(e)}"}, ensure_ascii=False)


def query_tunneling_summary(params_str: str) -> str:
    """查询掘进动态数据概览"""
    try:
        params = json.loads(params_str)
        query = _filter_tunneling_query(params)
        return _build_json(_enrich_tunneling_analysis(_summarize_tunneling_records(query)))
    except Exception as e:
        return _build_json({"error": f"掘进概览查询失败：{str(e)}"})


def query_tunneling_trend(params_str: str) -> str:
    """按环号区间统计掘进动态趋势"""
    try:
        params = json.loads(params_str)
        interval = int(params.get('interval', 50) or 50)
        interval = max(1, min(interval, 500))
        query = _filter_tunneling_query(params)
        segments = _trend_segments(query, interval=interval)
        if not segments:
            return _build_json({"message": "未找到符合条件的掘进动态数据", "total_records": 0})

        first = next((s for s in segments if s.get('avg_penetration') is not None), None)
        last = next((s for s in reversed(segments) if s.get('avg_penetration') is not None), None)
        trend = "稳定"
        if first and last and first['avg_penetration'] is not None and last['avg_penetration'] is not None:
            if last['avg_penetration'] > first['avg_penetration']:
                trend = "上升"
            elif last['avg_penetration'] < first['avg_penetration']:
                trend = "下降"

        result = {
            "total_records": query.count(),
            "interval": interval,
            "trend": trend,
            "segments": segments,
        }
        segment_mode = any(s.get("segment_index") for s in segments)
        result.update(_analysis_payload(
            summary={
                "total_records": result["total_records"],
                "interval": interval,
                "trend": trend,
                "segment_mode": "single_ring_time_segments" if segment_mode else "ring_interval",
            },
            facts=[
                f"共查询到 {result['total_records']} 条掘进动态记录",
                (
                    f"按单环内时间顺序分段统计，形成 {len(segments)} 个有效区段"
                    if segment_mode else
                    f"按 {interval} 环分段统计，形成 {len(segments)} 个有效区段"
                ),
                f"贯入力整体趋势为 {trend}",
            ],
            highlights=[
                f"首个有效区段平均贯入力为 {first.get('avg_penetration') if first else None}",
                f"末个有效区段平均贯入力为 {last.get('avg_penetration') if last else None}",
            ],
            warnings=[] if len(segments) >= 2 else ["有效分段少于 2 个，趋势判断仅供参考"],
            conclusion_hint="贯入力趋势可作为掘进效率变化的参考，需结合推力、扭矩和地层条件共同判断。",
        ))
        return _build_json(result)
    except Exception as e:
        return _build_json({"error": f"掘进趋势查询失败：{str(e)}"})


def query_tunneling_anomaly(params_str: str) -> str:
    """查询掘进动态异常段"""
    try:
        params = json.loads(params_str)
        query = _filter_tunneling_query(params)
        summary = _summarize_tunneling_records(query)
        if summary.get("total_records", 0) == 0:
            return _build_json(summary)

        metrics = summary["metrics"]
        threshold_k = float(params.get('threshold_k', 1.5) or 1.5)
        anomaly_fields = []
        for field in ('thrust', 'torque', 'penetration'):
            avg = metrics.get(field, {}).get('avg')
            mx = metrics.get(field, {}).get('max')
            if avg is not None and mx is not None and avg != 0 and mx > avg * threshold_k:
                anomaly_fields.append({
                    "field": field,
                    "avg": round(float(avg), 3),
                    "max": round(float(mx), 3),
                })

        summary["anomaly_fields"] = anomaly_fields
        summary = _enrich_tunneling_analysis(
            summary,
            conclusion_hint="异常峰值需要结合对应环号的地层、换刀和刀具磨损记录进一步判断原因。",
        )
        if anomaly_fields:
            summary["highlights"] = [
                f"{item['field']} 最大值 {item['max']} 明显高于平均值 {item['avg']}"
                for item in anomaly_fields
            ] + summary.get("highlights", [])
        else:
            summary["highlights"] = ["按当前阈值未发现推力、扭矩或贯入力的明显异常峰值"] + summary.get("highlights", [])
        return _build_json(summary)
    except Exception as e:
        return _build_json({"error": f"掘进异常查询失败：{str(e)}"})


def query_tunneling_wear_correlation(params_str: str) -> str:
    """按环号分段关联掘进动态、换刀磨损和地层数据。"""
    try:
        params = json.loads(params_str)
        project_id = (params.get('project_id') or '').strip()
        interval = int(params.get('interval', 50) or 50)
        interval = max(1, min(interval, 500))

        tunneling_qs = _filter_tunneling_query(params).annotate(
            ring_int=Cast('ring_no', output_field=IntegerField())
        )
        tunneling_records = list(tunneling_qs.values(
            'ring_int', 'thrust', 'torque', 'cutterhead_speed', 'penetration'
        ))
        tunneling_records = [r for r in tunneling_records if r.get('ring_int') is not None]
        if not tunneling_records:
            return _build_json({
                "message": "未找到符合条件的掘进动态数据",
                "total_records": 0,
                **_analysis_payload(
                    warnings=["未找到可用于关联分析的掘进动态数据"],
                    conclusion_hint="需要先导入对应项目和环号范围内的掘进动态数据。",
                ),
            })

        ring_range = _parse_ring_range(params.get('ring_range', []))
        min_ring = ring_range[0] if ring_range else min(r['ring_int'] for r in tunneling_records)
        max_ring = ring_range[1] if ring_range else max(r['ring_int'] for r in tunneling_records)

        change_qs = ToolChangeDetail.objects.select_related('warehouse__project')
        stratum_qs = StratumBasicInfo.objects.select_related('project')
        if project_id:
            change_qs = change_qs.filter(warehouse__project__project_id=project_id)
            stratum_qs = stratum_qs.filter(project__project_id=project_id)

        change_records = list(
            change_qs.annotate(ring_int=Cast('warehouse__ring_no', output_field=IntegerField()))
            .filter(ring_int__gte=min_ring, ring_int__lte=max_ring)
            .values('ring_int', 'is_replaced', 'wear_condition')
        )
        stratum_records = list(
            stratum_qs.annotate(ring_int=Cast('ring_no', output_field=IntegerField()))
            .filter(ring_int__gte=min_ring, ring_int__lte=max_ring)
            .values('ring_int', 'stratum_type_codes')
        )

        segments = []
        seg_start = min_ring
        while seg_start <= max_ring:
            seg_end = min(seg_start + interval - 1, max_ring)
            t_seg = [r for r in tunneling_records if seg_start <= r['ring_int'] <= seg_end]
            c_seg = [r for r in change_records if seg_start <= r['ring_int'] <= seg_end]
            s_seg = [r for r in stratum_records if seg_start <= r['ring_int'] <= seg_end]

            def avg(field):
                vals = [x[field] for x in t_seg if x.get(field) is not None]
                return round(sum(vals) / len(vals), 3) if vals else None

            stratum_count = {}
            for row in s_seg:
                codes = row.get('stratum_type_codes') or ''
                for code in [item.strip() for item in codes.split(',') if item.strip()]:
                    name = STRATUM_TYPE_NAMES.get(code, code)
                    stratum_count[name] = stratum_count.get(name, 0) + 1
            main_stratum = None
            if stratum_count:
                main_stratum = sorted(stratum_count.items(), key=lambda item: item[1], reverse=True)[0][0]

            replaced_count = sum(1 for r in c_seg if r.get('is_replaced'))
            abnormal_wear_count = sum(
                1 for r in c_seg if is_abnormal_wear(r.get('wear_condition'))
            )
            segments.append({
                "ring_range": f"{seg_start}-{seg_end}",
                "tunneling_count": len(t_seg),
                "avg_thrust": avg('thrust'),
                "avg_torque": avg('torque'),
                "avg_cutterhead_speed": avg('cutterhead_speed'),
                "avg_penetration": avg('penetration'),
                "tool_change_count": len(c_seg),
                "replacement_count": replaced_count,
                "abnormal_wear_count": abnormal_wear_count,
                "main_stratum": main_stratum,
            })
            seg_start += interval

        max_torque_seg = max(segments, key=lambda item: item.get('avg_torque') or 0)
        max_wear_seg = max(segments, key=lambda item: item.get('abnormal_wear_count') or 0)
        max_replacement_seg = max(segments, key=lambda item: item.get('replacement_count') or 0)

        facts = [
            f"共形成 {len(segments)} 个环号分段",
            f"掘进动态记录 {len(tunneling_records)} 条，换刀明细记录 {len(change_records)} 条，地层记录 {len(stratum_records)} 条",
            f"平均扭矩最高区段为 {max_torque_seg.get('ring_range')}，平均扭矩 {max_torque_seg.get('avg_torque')}kNm",
            f"异常磨损最多区段为 {max_wear_seg.get('ring_range')}，异常磨损 {max_wear_seg.get('abnormal_wear_count')} 次",
            f"更换次数最多区段为 {max_replacement_seg.get('ring_range')}，更换 {max_replacement_seg.get('replacement_count')} 次",
        ]
        facts = [
            f"共形成 {len(segments)} 个环号分段",
            f"掘进动态记录 {len(tunneling_records)} 条，换刀明细记录 {len(change_records)} 条，地层记录 {len(stratum_records)} 条",
            f"平均扭矩最高区段为 {max_torque_seg.get('ring_range')}，平均扭矩 {max_torque_seg.get('avg_torque')}kNm",
        ]
        if max_wear_seg.get('abnormal_wear_count', 0) > 0:
            facts.append(
                f"异常磨损最多区段为 {max_wear_seg.get('ring_range')}，异常磨损 {max_wear_seg.get('abnormal_wear_count')} 次"
            )
        if max_replacement_seg.get('replacement_count', 0) > 0:
            facts.append(
                f"更换次数最多区段为 {max_replacement_seg.get('ring_range')}，更换 {max_replacement_seg.get('replacement_count')} 次"
            )
        highlights = []
        if max_wear_seg.get('abnormal_wear_count', 0) > 0 and max_torque_seg.get('ring_range') == max_wear_seg.get('ring_range'):
            highlights.append("平均扭矩最高区段与异常磨损最多区段重合，掘进负荷与刀具异常磨损可能存在关联")
        if max_replacement_seg.get('replacement_count', 0) > 0 and max_torque_seg.get('ring_range') == max_replacement_seg.get('ring_range'):
            highlights.append("平均扭矩最高区段与换刀最多区段重合，应重点复核该区段刀具受力和地层条件")
        if max_torque_seg.get('main_stratum'):
            highlights.append(f"平均扭矩最高区段的主要地层为 {max_torque_seg.get('main_stratum')}")
        if not highlights:
            highlights.append("当前分段内掘进峰值与换刀/异常磨损高发区段未明显重合")

        warnings = []
        if len(segments) < 2:
            warnings.append("有效分段少于 2 个，关联判断仅供参考")
        if not stratum_records:
            warnings.append("未找到对应环号范围内的地层数据，无法判断地层影响")
        if not change_records:
            warnings.append("未找到对应环号范围内的换刀明细，无法判断刀具磨损关联")

        result = {
            "total_records": len(tunneling_records),
            "ring_range": [min_ring, max_ring],
            "interval": interval,
            "segments": segments,
        }
        result.update(_analysis_payload(
            summary={"ring_range": [min_ring, max_ring], "interval": interval, "segment_count": len(segments)},
            facts=facts,
            highlights=highlights,
            warnings=warnings,
            conclusion_hint="该结果用于判断掘进负荷、地层条件与刀具磨损/换刀之间是否存在同区段聚集现象。",
        ))
        return _build_json(result)
    except Exception as e:
        return _build_json({"error": f"掘进-磨损关联分析失败：{str(e)}"})


def query_position_stratum_impact(params_str: str) -> str:
    """分析各刀位在不同地层下的更换次数，找出受地层影响最大的刀位。"""
    try:
        params = json.loads(params_str)
        project_id = params.get('project_id')
        tool_type = params.get('tool_type')
        ring_range = params.get('ring_range', [])
        top_n = params.get('top_n', 10)

        change_query = ToolChangeDetail.objects.select_related('warehouse__project').filter(is_replaced=True)
        if project_id:
            change_query = change_query.filter(warehouse__project__project_id=project_id)
        if tool_type:
            change_query = change_query.filter(tool_parent_type=tool_type)
        if ring_range and len(ring_range) == 2:
            change_query = change_query.annotate(
                ring_int=Cast('warehouse__ring_no', output_field=IntegerField())
            ).filter(ring_int__gte=ring_range[0], ring_int__lte=ring_range[1])

        if not change_query.exists():
            return json.dumps({"message": "未找到换刀记录", "total": 0}, ensure_ascii=False)

        stratum_query = StratumBasicInfo.objects.all()
        if project_id:
            stratum_query = stratum_query.filter(project__project_id=project_id)
        stratum_map = {}
        for s in stratum_query:
            if s.stratum_type_codes:
                stratum_map[str(s.ring_no).strip()] = [
                    t.strip() for t in s.stratum_type_codes.split(',') if t.strip()
                ]

        position_stratum = {}
        for change in change_query:
            pos = change.cutter_position_no
            if not pos:
                continue
            strata = stratum_map.get(str(change.warehouse.ring_no).strip(), ['未知地层'])
            if pos not in position_stratum:
                position_stratum[pos] = {}
            for st in strata:
                name = STRATUM_TYPE_NAMES.get(st, st)
                position_stratum[pos][name] = position_stratum[pos].get(name, 0) + 1

        ranked = sorted(
            [{"position": pos, "total": sum(v.values()), "by_stratum": v}
             for pos, v in position_stratum.items()],
            key=lambda x: x['total'], reverse=True
        )[:top_n]

        return json.dumps({
            "INSTRUCTION": "以下是真实数据库数据，回答时必须原样使用这些数字",
            "note": "total越高说明该刀位受地层影响越大，by_stratum显示各地层下的更换次数",
            "top_positions": ranked,
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": f"刀位地层影响分析失败：{str(e)}"}, ensure_ascii=False)
