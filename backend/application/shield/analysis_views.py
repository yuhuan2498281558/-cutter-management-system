# -*- coding: utf-8 -*-
"""
盾构刀具数据分析接口
"""
from collections import defaultdict
from itertools import product

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from dvadmin.utils.permission import CustomPermission
from django.db.models import (
    Count, Sum, Avg, Q, IntegerField, DecimalField, FloatField, Min, Max
)
from django.db.models.functions import TruncMonth, Cast
from django.core.cache import cache
from .models import (
    WarehouseOpeningBasicInfo,
    ToolChangeDetail,
    ShieldTunnelingData,
    StratumBasicInfo,
    TOOL_TYPES,
)
from .wear import (
    Q_WEAR_ABNORMAL,
    Q_WEAR_NORMAL,
    Q_WEAR_RECORDED,
    normalize_wear,
)


def success(data):
    """返回标准格式响应 {code: 2000, data: ..., msg: 'success'}"""
    return Response({'code': 2000, 'data': data, 'msg': 'success'})


def _get_stratum_label_map():
    """
    从系统字典获取地层类型编码→中文名映射，带缓存（10分钟）
    返回：{'CLAY_SAND': '粘土砂层', ...}
    """
    cache_key = 'stratum_label_map'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from dvadmin.system.models import Dictionary
        items = Dictionary.objects.filter(
            parent__value='stratum_type', status=True
        ).values('value', 'label')
        label_map = {item['value']: item['label'] for item in items}
    except Exception:
        label_map = {}
    cache.set(cache_key, label_map, 600)
    return label_map

# 磨损判定统一走 shield/wear.py（中英文兼容；未记录不计入分子与分母）。
# 保留该常量仅为兼容历史引用，新代码请勿直接比较它。
NORMAL_WEAR = '正常'

# 环号是自由文本 CharField，直接 Cast 遇到非数字环号会让 PostgreSQL 抛
# DataError 导致整页 500。统一走这个帮助函数：先滤掉非数字环号再转换。
_RING_NUMERIC_REGEX = r'^\d+$'


def _with_ring_int(qs, field='ring_no'):
    """安全地为 queryset 标注 ring_int（跳过非数字环号）。"""
    return qs.filter(**{f'{field}__regex': _RING_NUMERIC_REGEX}).annotate(
        ring_int=Cast(field, output_field=IntegerField())
    )

TOOL_TYPE_LABELS = {
    'DISC': '滚刀',
    'RIPPER': '撕裂刀',
    'SCRAPER': '刮刀',
}

CUSTOM_DIMENSIONS = [
    {'value': 'ring_no', 'label': '开仓环号', 'type': 'number', 'chart_types': ['line', 'matrix']},
    {'value': 'open_time', 'label': '开仓日期', 'type': 'date', 'chart_types': ['line']},
    {'value': 'month', 'label': '开仓月份', 'type': 'date', 'chart_types': ['line', 'matrix']},
    {'value': 'manufacturer', 'label': '厂家', 'type': 'category', 'chart_types': ['line', 'matrix'], 'skip_empty': True},
    {'value': 'brand', 'label': '品牌', 'type': 'category', 'chart_types': ['line', 'matrix'], 'skip_empty': True},
    {'value': 'tool_parent_type', 'label': '刀具父类型', 'type': 'category', 'chart_types': ['line', 'matrix']},
    {'value': 'tool_type_name', 'label': '刀具细分类型', 'type': 'category', 'chart_types': ['line', 'matrix']},
    {'value': 'cutter_position_no', 'label': '刀位号', 'type': 'category', 'chart_types': ['line', 'matrix']},
    {'value': 'replacement_type', 'label': '更换类型', 'type': 'category', 'chart_types': ['line', 'matrix']},
    {'value': 'wear_condition', 'label': '磨损情况', 'type': 'category', 'chart_types': ['line', 'matrix']},
    {'value': 'stratum_types', 'label': '地层类型', 'type': 'category', 'chart_types': ['line', 'matrix']},
    {'value': 'geological_conditions', 'label': '地质情况', 'type': 'category', 'chart_types': ['matrix']},
]

CUSTOM_METRICS = [
    {'value': 'opening_count', 'label': '开仓次数', 'unit': '次'},
    {'value': 'checked_tool_count', 'label': '检查刀具数', 'unit': '把'},
    {'value': 'replacement_count', 'label': '更换刀具数', 'unit': '把'},
    {'value': 'complete_count', 'label': '整刀更换数', 'unit': '把'},
    {'value': 'repair_count', 'label': '维修数', 'unit': '次'},
    {'value': 'abnormal_count', 'label': '异常磨损数', 'unit': '把'},
    {'value': 'abnormal_rate', 'label': '异常磨损率', 'unit': '%'},
    {'value': 'normal_rate', 'label': '正常磨损率', 'unit': '%'},
    {'value': 'total_cost', 'label': '换刀总费用', 'unit': '元'},
    {'value': 'avg_price', 'label': '平均单价', 'unit': '元'},
    {'value': 'cost_per_opening', 'label': '单次开仓费用', 'unit': '元/次'},
    {'value': 'avg_opening_duration', 'label': '平均开仓时长', 'unit': '小时'},
    {'value': 'avg_rings_between_openings', 'label': '平均开仓间隔', 'unit': '环'},
    {'value': 'avg_thrust', 'label': '平均推力', 'unit': ''},
    {'value': 'avg_torque', 'label': '平均扭矩', 'unit': ''},
    {'value': 'avg_cutterhead_speed', 'label': '平均刀盘转速', 'unit': ''},
    {'value': 'avg_penetration', 'label': '平均贯入度', 'unit': ''},
    {'value': 'avg_burial_depth', 'label': '平均埋深', 'unit': 'm'},
]

CUSTOM_DIMENSION_MAP = {item['value']: item for item in CUSTOM_DIMENSIONS}
CUSTOM_METRIC_MAP = {item['value']: item for item in CUSTOM_METRICS}
# 这些维度字段为空时用哨兵值 '未填写' 填充，分析时应跳过
SKIP_EMPTY_FIELDS = {item['value'] for item in CUSTOM_DIMENSIONS if item.get('skip_empty')}


def _get_query_value(params, key):
    value = params.get(key)
    return value if value not in (None, '') else None


def _get_query_values(params, *keys):
    values = []
    for key in keys:
        if hasattr(params, 'getlist'):
            values.extend(params.getlist(key))
        else:
            value = params.get(key)
            if value is not None:
                values.append(value)

    result = []
    for value in values:
        if value in (None, ''):
            continue
        parts = value if isinstance(value, (list, tuple)) else str(value).split(',')
        for part in parts:
            item = str(part).strip()
            if item and item not in result:
                result.append(item)
    return result


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_ring_span(openings):
    ring_range = (
        openings
        .filter(ring_no__regex=_RING_NUMERIC_REGEX).annotate(ring_int=Cast('ring_no', output_field=IntegerField()))
        .aggregate(min_ring=Min('ring_int'), max_ring=Max('ring_int'))
    )
    min_ring = ring_range.get('min_ring')
    max_ring = ring_range.get('max_ring')
    if min_ring is None or max_ring is None:
        return 0
    return max(max_ring - min_ring + 1, 0)


def _build_detail_queryset(openings, params, only_replaced=None, include_manufacturer=True):
    """
    根据开仓记录和分析筛选参数构造换刀明细 QuerySet。
    支持 tool_parent_type / tool_type_name / manufacturer，保证各图表口径一致。
    """
    qs = ToolChangeDetail.objects.filter(warehouse__in=openings)
    if only_replaced is not None:
        qs = qs.filter(is_replaced=only_replaced)

    tool_type = _get_query_value(params, 'tool_parent_type')
    tool_type_names = _get_query_values(
        params,
        'tool_type_name',
        'tool_type_names',
        'tool_type_names[]',
        'toolTypeName',
        'toolTypeNames',
        'toolTypeNames[]',
    )
    manufacturers = (
        _get_query_values(params, 'manufacturer', 'manufacturers', 'manufacturers[]')
        if include_manufacturer else []
    )
    cost_types = _get_query_values(
        params,
        'cost_type',
        'cost_types',
        'cost_types[]',
        'costType',
        'costTypes',
        'costTypes[]',
    )
    valid_cost_types = {'COMPLETE', 'REPAIR'}
    cost_types = [
        str(value).upper()
        for value in cost_types
        if str(value).upper() in valid_cost_types
    ]

    if tool_type:
        qs = qs.filter(tool_parent_type=tool_type)
    if tool_type_names:
        qs = qs.filter(cutter_position__tool_info__tool_type_name__in=tool_type_names)
    if manufacturers:
        qs = qs.filter(manufacturer__in=manufacturers)
    if cost_types:
        qs = qs.filter(replacement_type__in=cost_types)

    return qs


def _build_opening_queryset(params):
    """
    根据筛选参数构造开仓记录 QuerySet
    params: request.query_params（QueryDict）
    """
    qs = WarehouseOpeningBasicInfo.objects.all()

    project = _get_query_value(params, 'project')          # 项目 PK
    machine = _get_query_value(params, 'shield_machine')   # 盾构机 PK
    start_ring = _get_query_value(params, 'start_ring')    # 环号下限
    end_ring = _get_query_value(params, 'end_ring')        # 环号上限

    stratum_types = _get_query_values(
        params,
        'stratum_type',
        'stratum_types',
        'stratum_types[]',
        'stratumType',
        'stratumTypes',
        'stratumTypes[]',
    )

    # project / machine 是 FK 主键，非数字会在查询期抛 ValueError（500），先做安全转换
    project_int = _safe_int(project)
    machine_int = _safe_int(machine)
    if project and project_int is not None:
        qs = qs.filter(project_id=project_int)
    if machine and machine_int is not None:
        qs = qs.filter(shield_model_id=machine_int)
    if start_ring or end_ring:
        # ring_no 是 CharField，转成整数后过滤（跳过非数字环号）
        qs = _with_ring_int(qs)
        start_ring_int = _safe_int(start_ring)
        end_ring_int = _safe_int(end_ring)
        if start_ring_int is not None:
            qs = qs.filter(ring_int__gte=start_ring_int)
        if end_ring_int is not None:
            qs = qs.filter(ring_int__lte=end_ring_int)

    if stratum_types:
        qs = qs.filter(stratum_info_between__has_any_keys=stratum_types)

    return qs


def _date_text(value, fmt):
    return value.strftime(fmt) if value else ''


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_metric_value(bucket, metric, parent_bucket=None):
    # abnormal_rate / normal_rate 若有父桶则用父桶总数做分母
    # 这样当 wear_condition 作轴分组时分母是同 X 轴下所有磨损情况的总数
    denom_bucket = parent_bucket if parent_bucket is not None else bucket
    checked = bucket['detail_count']
    # 异常率/正常率的分母是"有磨损记录的行数"，不是全部检查行数
    denom = denom_bucket['wear_recorded_count']
    opening_count = len(bucket['opening_ids'])
    price_count = bucket['price_count']

    if metric == 'opening_count':
        return opening_count
    if metric == 'checked_tool_count':
        return checked
    if metric == 'replacement_count':
        return bucket['replacement_count']
    if metric == 'complete_count':
        return bucket['complete_count']
    if metric == 'repair_count':
        return bucket['repair_count']
    if metric == 'abnormal_count':
        return bucket['abnormal_count']
    if metric == 'abnormal_rate':
        return round(bucket['abnormal_count'] / denom * 100, 2) if denom else 0
    if metric == 'normal_rate':
        return round(
            (bucket['wear_recorded_count'] - bucket['abnormal_count']) / denom * 100, 2
        ) if denom else 0
    if metric == 'total_cost':
        return round(bucket['price_total'], 2)
    if metric == 'avg_price':
        return round(bucket['price_total'] / price_count, 2) if price_count else 0
    if metric == 'cost_per_opening':
        return round(bucket['price_total'] / opening_count, 2) if opening_count else 0
    if metric == 'avg_opening_duration':
        return round(bucket['opening_duration_total'] / bucket['opening_duration_count'], 2) if bucket['opening_duration_count'] else 0
    if metric == 'avg_rings_between_openings':
        return round(bucket['rings_between_total'] / bucket['rings_between_count'], 2) if bucket['rings_between_count'] else 0
    if metric == 'avg_thrust':
        return round(bucket['thrust_total'] / bucket['thrust_count'], 2) if bucket['thrust_count'] else 0
    if metric == 'avg_torque':
        return round(bucket['torque_total'] / bucket['torque_count'], 2) if bucket['torque_count'] else 0
    if metric == 'avg_cutterhead_speed':
        return round(bucket['cutterhead_speed_total'] / bucket['cutterhead_speed_count'], 2) if bucket['cutterhead_speed_count'] else 0
    if metric == 'avg_penetration':
        return round(bucket['penetration_total'] / bucket['penetration_count'], 2) if bucket['penetration_count'] else 0
    if metric == 'avg_burial_depth':
        return round(bucket['burial_depth_total'] / bucket['burial_depth_count'], 2) if bucket['burial_depth_count'] else 0
    return 0


def _new_custom_bucket():
    return {
        'opening_ids': set(),
        'opening_metric_ids': set(),
        'detail_count': 0,
        'replacement_count': 0,
        'complete_count': 0,
        'repair_count': 0,
        'abnormal_count': 0,
        'wear_recorded_count': 0,
        'price_total': 0.0,
        'price_count': 0,
        'opening_duration_total': 0.0,
        'opening_duration_count': 0,
        'rings_between_total': 0.0,
        'rings_between_count': 0,
        'thrust_total': 0.0,
        'thrust_count': 0,
        'torque_total': 0.0,
        'torque_count': 0,
        'cutterhead_speed_total': 0.0,
        'cutterhead_speed_count': 0,
        'penetration_total': 0.0,
        'penetration_count': 0,
        'burial_depth_total': 0.0,
        'burial_depth_count': 0,
    }


_NUMERIC_BUCKET_KEYS = (
    'detail_count', 'replacement_count', 'complete_count', 'repair_count',
    'abnormal_count', 'wear_recorded_count', 'price_total', 'price_count',
    'opening_duration_total', 'opening_duration_count',
    'rings_between_total', 'rings_between_count',
    'thrust_total', 'thrust_count', 'torque_total', 'torque_count',
    'cutterhead_speed_total', 'cutterhead_speed_count',
    'penetration_total', 'penetration_count',
    'burial_depth_total', 'burial_depth_count',
)


def _merge_buckets(target, source):
    target['opening_ids'].update(source['opening_ids'])
    target['opening_metric_ids'].update(source['opening_metric_ids'])
    for key in _NUMERIC_BUCKET_KEYS:
        target[key] += source[key]


def _add_custom_record(bucket, record):
    bucket['detail_count'] += 1
    if record['is_replaced']:
        bucket['replacement_count'] += 1
        if record['replacement_type_raw'] == 'COMPLETE':
            bucket['complete_count'] += 1
        if record['replacement_type_raw'] == 'REPAIR':
            bucket['repair_count'] += 1
    wear_state = normalize_wear(record['wear_condition_raw'])
    if wear_state is not None:
        # 未记录磨损的行不进分子也不进分母（"没录"≠"正常"）
        bucket['wear_recorded_count'] += 1
        if wear_state == 'ABNORMAL':
            bucket['abnormal_count'] += 1
    if record['price'] is not None:
        bucket['price_total'] += record['price']
        bucket['price_count'] += 1

    opening_id = record['opening_id']
    bucket['opening_ids'].add(opening_id)
    if opening_id in bucket['opening_metric_ids']:
        return
    bucket['opening_metric_ids'].add(opening_id)

    for field, total_key, count_key in [
        ('opening_duration', 'opening_duration_total', 'opening_duration_count'),
        ('rings_between_openings', 'rings_between_total', 'rings_between_count'),
        ('thrust', 'thrust_total', 'thrust_count'),
        ('torque', 'torque_total', 'torque_count'),
        ('cutterhead_speed', 'cutterhead_speed_total', 'cutterhead_speed_count'),
        ('penetration', 'penetration_total', 'penetration_count'),
        ('burial_depth', 'burial_depth_total', 'burial_depth_count'),
    ]:
        value = record.get(field)
        if value is None:
            continue
        bucket[total_key] += value
        bucket[count_key] += 1


def _custom_values(record, field):
    value = record.get(field)
    if isinstance(value, list):
        return value or ['未填写']
    return [value if value not in (None, '') else '未填写']


def _sort_dimension_value(field, value):
    if field == 'ring_no':
        numeric = _safe_int(value)
        return (0, numeric) if numeric is not None else (1, str(value))
    return (0, str(value))


def _sort_dimension_key(fields, values):
    return tuple(_sort_dimension_value(field, value) for field, value in zip(fields, values))


def _format_dimension_key(fields, values):
    if len(fields) == 1:
        return str(values[0])
    parts = []
    for field, value in zip(fields, values):
        label = CUSTOM_DIMENSION_MAP.get(field, {}).get('label', field)
        parts.append(f"{label}:{value}")
    return ' / '.join(parts)


def _combined_dimension_meta(fields):
    labels = [CUSTOM_DIMENSION_MAP.get(field, {}).get('label', field) for field in fields]
    return {
        'value': ','.join(fields),
        'label': ' / '.join(labels),
        'type': 'combined' if len(fields) > 1 else CUSTOM_DIMENSION_MAP[fields[0]].get('type'),
        'fields': [CUSTOM_DIMENSION_MAP[field] for field in fields],
    }


def _aggregate_custom_records(records, group_fields):
    buckets = defaultdict(_new_custom_bucket)
    for record in records:
        value_groups = [_custom_values(record, field) for field in group_fields]
        for key in product(*value_groups):
            buckets[key]  # ensure bucket exists
            _add_custom_record(buckets[key], record)
    return buckets


def _build_custom_records(openings, details, metrics=None):
    metrics = set(metrics or [])
    opening_list = list(
        openings
        .filter(ring_no__regex=_RING_NUMERIC_REGEX).annotate(ring_int=Cast('ring_no', output_field=IntegerField()))
        .order_by('ring_int')
    )
    opening_map = {op.id: op for op in opening_list}
    ring_nos = [op.ring_no for op in opening_list]
    project_ids = {op.project_id for op in opening_list if op.project_id}
    machine_ids = {op.shield_model_id for op in opening_list if op.shield_model_id}

    tunneling_map = {}
    if metrics & {'avg_thrust', 'avg_torque', 'avg_cutterhead_speed', 'avg_penetration'}:
        try:
            tunneling_qs = ShieldTunnelingData.objects.filter(ring_no__in=ring_nos)
            if project_ids:
                tunneling_qs = tunneling_qs.filter(project_id__in=project_ids)
            if machine_ids:
                tunneling_qs = tunneling_qs.filter(shield_machine_id__in=machine_ids)
            tunneling_rows = (
                tunneling_qs
                .values('project_id', 'shield_machine_id', 'ring_no')
                .annotate(
                    thrust=Avg('thrust', output_field=FloatField()),
                    torque=Avg('torque', output_field=FloatField()),
                    cutterhead_speed=Avg('cutterhead_speed', output_field=FloatField()),
                    penetration=Avg('penetration', output_field=FloatField()),
                )
            )
            tunneling_map = {
                (row['project_id'], row['shield_machine_id'], row['ring_no']): row
                for row in tunneling_rows
            }
        except Exception:
            tunneling_map = {}

    burial_depth_map = {}
    if 'avg_burial_depth' in metrics:
        try:
            stratum_rows = (
                StratumBasicInfo.objects
                .filter(project_id__in=project_ids, ring_no__in=ring_nos)
                .values('project_id', 'ring_no')
                .annotate(burial_depth=Avg('burial_depth', output_field=FloatField()))
            )
            burial_depth_map = {
                (row['project_id'], row['ring_no']): _safe_float(row['burial_depth'])
                for row in stratum_rows
            }
        except Exception:
            burial_depth_map = {}

    label_map = _get_stratum_label_map()
    replacement_type_labels = {'COMPLETE': '整刀更换', 'REPAIR': '维修'}
    empty = '未填写'
    records = []
    detail_qs = (
        details
        .select_related('warehouse', 'cutter_position__tool_info')
        .filter(warehouse__ring_no__regex=_RING_NUMERIC_REGEX).annotate(ring_int=Cast('warehouse__ring_no', output_field=IntegerField()))
        .order_by('ring_int', 'cutter_position_no')
    )
    for detail in detail_qs:
        op = opening_map.get(detail.warehouse_id) or detail.warehouse
        tunneling = tunneling_map.get((op.project_id, op.shield_model_id, op.ring_no), {})
        stratum_info = op.stratum_info_between if isinstance(op.stratum_info_between, dict) else {}
        stratum_types = [label_map.get(code, code) for code in stratum_info.keys() if code]
        tool_info = detail.cutter_position.tool_info if detail.cutter_position else None
        price = _safe_float(detail.price)
        record = {
            'opening_id': op.id,
            'ring_no': op.ring_no,
            'open_time': _date_text(op.open_time, '%Y-%m-%d'),
            'month': _date_text(op.open_time, '%Y-%m'),
            'manufacturer': detail.manufacturer or empty,
            'brand': detail.brand or empty,
            'tool_parent_type': TOOL_TYPE_LABELS.get(detail.tool_parent_type, detail.tool_parent_type or empty),
            'tool_type_name': tool_info.tool_type_name if tool_info and tool_info.tool_type_name else empty,
            'cutter_position_no': detail.cutter_position_no or empty,
            'replacement_type': replacement_type_labels.get(detail.replacement_type, '未更换'),
            'replacement_type_raw': detail.replacement_type,
            'wear_condition': detail.wear_condition or empty,
            'wear_condition_raw': detail.wear_condition,
            'stratum_types': stratum_types or [empty],
            'geological_conditions': op.geological_conditions or empty,
            'is_replaced': detail.is_replaced,
            'price': price,
            'opening_duration': _safe_float(op.opening_duration),
            'rings_between_openings': _safe_float(op.rings_between_openings),
            'thrust': _safe_float(tunneling.get('thrust')),
            'torque': _safe_float(tunneling.get('torque')),
            'cutterhead_speed': _safe_float(tunneling.get('cutterhead_speed')),
            'penetration': _safe_float(tunneling.get('penetration')),
            'burial_depth': burial_depth_map.get((op.project_id, op.ring_no)),
        }
        records.append(record)
    return records


def _build_custom_line(records, x_field, metrics):
    buckets = _aggregate_custom_records(records, [x_field])
    skip = x_field in SKIP_EMPTY_FIELDS
    labels = sorted(
        [key[0] for key in buckets.keys() if not (skip and key[0] == '未填写')],
        key=lambda item: _sort_dimension_value(x_field, item),
    )
    series = []
    for metric in metrics:
        metric_info = CUSTOM_METRIC_MAP[metric]
        series.append({
            'metric': metric,
            'name': metric_info['label'],
            'unit': metric_info.get('unit', ''),
            'data': [_get_metric_value(buckets[(label,)], metric) for label in labels],
        })
    rows = []
    for label in labels:
        row = {'x': label}
        for metric in metrics:
            row[metric] = _get_metric_value(buckets[(label,)], metric)
        rows.append(row)
    return {
        'chart_type': 'line',
        'x_field': CUSTOM_DIMENSION_MAP[x_field],
        'metrics': [CUSTOM_METRIC_MAP[metric] for metric in metrics],
        'categories': labels,
        'series': series,
        'rows': rows,
        'record_count': len(records),
    }


def _build_custom_matrix(records, x_fields, y_fields, metrics):
    group_fields = x_fields + y_fields
    x_size = len(x_fields)
    buckets = _aggregate_custom_records(records, group_fields)

    def _has_empty(fields, key):
        return any(
            field in SKIP_EMPTY_FIELDS and val == '未填写'
            for field, val in zip(fields, key)
        )

    x_keys = sorted(
        {key[:x_size] for key in buckets.keys() if not _has_empty(x_fields, key[:x_size])},
        key=lambda item: _sort_dimension_key(x_fields, item),
    )
    y_keys = sorted(
        {key[x_size:] for key in buckets.keys() if not _has_empty(y_fields, key[x_size:])},
        key=lambda item: _sort_dimension_key(y_fields, item),
    )
    x_labels = [_format_dimension_key(x_fields, key) for key in x_keys]
    y_labels = [_format_dimension_key(y_fields, key) for key in y_keys]
    # 需要跨格子计算比率的维度：当这些字段在 x/y 轴时，
    # 以"同 x 轴下所有 y 值合并"作为分母
    RATE_DENOM_FIELDS = {'wear_condition'}
    x_needs_parent = any(f in RATE_DENOM_FIELDS for f in x_fields)
    y_needs_parent = any(f in RATE_DENOM_FIELDS for f in y_fields)

    # 预计算父桶：按 x_key 合并所有 y，按 y_key 合并所有 x
    x_parent_buckets: dict = {}  # x_key → 合并了该 x 下所有 y 的桶
    y_parent_buckets: dict = {}  # y_key → 合并了该 y 下所有 x 的桶
    if y_needs_parent:
        for x_key in x_keys:
            merged = _new_custom_bucket()
            for y_key in y_keys:
                b = buckets.get(x_key + y_key)
                if b:
                    _merge_buckets(merged, b)
            x_parent_buckets[x_key] = merged
    if x_needs_parent:
        for y_key in y_keys:
            merged = _new_custom_bucket()
            for x_key in x_keys:
                b = buckets.get(x_key + y_key)
                if b:
                    _merge_buckets(merged, b)
            y_parent_buckets[y_key] = merged

    series = []
    rows = []
    for x_index, x_key in enumerate(x_keys):
        for y_index, y_key in enumerate(y_keys):
            bucket = buckets.get(x_key + y_key, _new_custom_bucket())
            # y 轴含 wear_condition 时用 x 父桶做分母，x 轴含时用 y 父桶
            parent = x_parent_buckets.get(x_key) if y_needs_parent else y_parent_buckets.get(y_key)
            row = {'x': x_labels[x_index], 'y': y_labels[y_index]}
            for metric in metrics:
                row[metric] = _get_metric_value(bucket, metric, parent)
            rows.append(row)

    for metric in metrics:
        metric_info = CUSTOM_METRIC_MAP[metric]
        data = []
        for x_index, x_key in enumerate(x_keys):
            for y_index, y_key in enumerate(y_keys):
                bucket = buckets.get(x_key + y_key, _new_custom_bucket())
                parent = x_parent_buckets.get(x_key) if y_needs_parent else y_parent_buckets.get(y_key)
                value = _get_metric_value(bucket, metric, parent)
                data.append([x_index, y_index, value])
        series.append({
            'metric': metric,
            'name': metric_info['label'],
            'unit': metric_info.get('unit', ''),
            'data': data,
        })
    return {
        'chart_type': 'matrix',
        'x_field': _combined_dimension_meta(x_fields),
        'y_field': _combined_dimension_meta(y_fields),
        'x_fields': [CUSTOM_DIMENSION_MAP[field] for field in x_fields],
        'y_fields': [CUSTOM_DIMENSION_MAP[field] for field in y_fields],
        'metrics': [CUSTOM_METRIC_MAP[metric] for metric in metrics],
        'x_categories': x_labels,
        'y_categories': y_labels,
        'series': series,
        'rows': rows,
        'record_count': len(records),
    }


class AnalysisViewSet(viewsets.ViewSet):
    """
    数据分析接口集合（只读）
    所有接口均为 GET，支持通用筛选参数：
      project, shield_machine, start_ring, end_ring, tool_parent_type, tool_type_name, manufacturer
    """
    authentication_classes = [JWTAuthentication, SessionAuthentication]
    permission_classes = [CustomPermission]

    @action(detail=False, methods=['get'], url_path='filter_options')
    def filter_options(self, request):
        """
        分析筛选项。
        manufacturer 会按项目/盾构机/环号/刀具类型联动，便于厂家图表聚焦。
        """
        cache_key = f"analysis_filter_options_{request.query_params.urlencode()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return success(cached)

        openings = _build_opening_queryset(request.query_params)
        details = _build_detail_queryset(
            openings,
            request.query_params,
            include_manufacturer=False,
        )
        manufacturers = list(
            details
            .exclude(manufacturer__isnull=True)
            .exclude(manufacturer='')
            .values_list('manufacturer', flat=True)
            .distinct()
            .order_by('manufacturer')
        )

        parent_label_map = dict(TOOL_TYPES)
        tool_type_rows = (
            details
            .exclude(cutter_position__tool_info__tool_type_name__isnull=True)
            .exclude(cutter_position__tool_info__tool_type_name='')
            .values(
                'cutter_position__tool_info__tool_type_name',
                'cutter_position__tool_info__tool_parent_type',
            )
            .distinct()
            .order_by(
                'cutter_position__tool_info__tool_parent_type',
                'cutter_position__tool_info__tool_type_name',
            )
        )
        tool_type_names = [
            {
                'value': row['cutter_position__tool_info__tool_type_name'],
                'label': row['cutter_position__tool_info__tool_type_name'],
                'parent_type': row['cutter_position__tool_info__tool_parent_type'],
                'parent_label': parent_label_map.get(
                    row['cutter_position__tool_info__tool_parent_type'],
                    row['cutter_position__tool_info__tool_parent_type'] or '',
                ),
            }
            for row in tool_type_rows
        ]
        label_map = _get_stratum_label_map()
        stratum_codes = []
        for info in openings.values_list('stratum_info_between', flat=True):
            if not isinstance(info, dict):
                continue
            for code in info.keys():
                if code and code not in stratum_codes:
                    stratum_codes.append(code)
        stratum_types = [
            {
                'value': code,
                'label': label_map.get(code, code),
            }
            for code in stratum_codes
        ]

        result = {
            'tool_types': [
                {'value': value, 'label': label}
                for value, label in TOOL_TYPES
            ],
            'tool_type_names': tool_type_names,
            'stratum_types': stratum_types,
            'manufacturers': manufacturers,
        }
        cache.set(cache_key, result, 300)
        return success(result)

    @action(detail=False, methods=['get'], url_path='custom_fields')
    def custom_fields(self, request):
        """
        自定义分析可选字段。
        返回前端可用于 X/Y 轴和矩阵维度的白名单，避免任意字段查询。
        """
        return success({
            'dimensions': CUSTOM_DIMENSIONS,
            'metrics': CUSTOM_METRICS,
            'defaults': {
                'line': {
                    'x_field': 'ring_no',
                    'metrics': ['replacement_count', 'abnormal_rate'],
                },
                'matrix': {
                    'x_field': 'manufacturer',
                    'y_field': 'tool_parent_type',
                    'metrics': ['abnormal_rate'],
                },
            },
        })

    @action(detail=False, methods=['get'], url_path='custom_chart')
    def custom_chart(self, request):
        """
        自定义图表数据。
        chart_type=line:   x_field + metrics(1~2)
        chart_type=matrix: x_field + y_field + metrics(1~2)
        """
        chart_type = _get_query_value(request.query_params, 'chart_type') or 'line'
        if chart_type not in ('line', 'matrix'):
            chart_type = 'line'

        default_x = 'ring_no' if chart_type == 'line' else 'manufacturer'
        x_field = _get_query_value(request.query_params, 'x_field') or default_x
        y_field = _get_query_value(request.query_params, 'y_field') or 'tool_parent_type'
        x_fields = _get_query_values(request.query_params, 'x_fields', 'x_fields[]')
        y_fields = _get_query_values(request.query_params, 'y_fields', 'y_fields[]')
        metrics = _get_query_values(request.query_params, 'metrics', 'metrics[]')

        valid_dimensions = [
            item['value']
            for item in CUSTOM_DIMENSIONS
            if chart_type in item.get('chart_types', [])
        ]
        if x_field not in valid_dimensions:
            x_field = default_x
        if chart_type == 'matrix' and y_field not in valid_dimensions:
            y_field = 'tool_parent_type'
        if chart_type == 'matrix' and y_field == x_field:
            y_field = next((item for item in valid_dimensions if item != x_field), 'tool_parent_type')

        if chart_type == 'matrix':
            x_fields = [field for field in (x_fields or [x_field]) if field in valid_dimensions]
            if not x_fields:
                x_fields = [default_x]
            x_fields = x_fields[:3]

            y_fields = [field for field in (y_fields or [y_field]) if field in valid_dimensions and field not in x_fields]
            if not y_fields:
                y_fields = [next((item for item in valid_dimensions if item not in x_fields), 'tool_parent_type')]
            y_fields = y_fields[:3]
            x_field = x_fields[0]
            y_field = y_fields[0]

        valid_metrics = [metric for metric in metrics if metric in CUSTOM_METRIC_MAP]
        if not valid_metrics:
            valid_metrics = ['replacement_count', 'abnormal_rate'] if chart_type == 'line' else ['abnormal_rate']
        valid_metrics = valid_metrics[:2]

        cache_key = (
            f"analysis_custom_chart_v3_{chart_type}_{','.join(x_fields or [x_field])}_{','.join(y_fields or [y_field])}_"
            f"{','.join(valid_metrics)}_{request.query_params.urlencode()}"
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return success(cached)

        openings = _build_opening_queryset(request.query_params)
        details = _build_detail_queryset(openings, request.query_params)
        records = _build_custom_records(openings, details, valid_metrics)

        if chart_type == 'matrix':
            result = _build_custom_matrix(records, x_fields, y_fields, valid_metrics)
        else:
            result = _build_custom_line(records, x_field, valid_metrics)

        result['request'] = {
            'chart_type': chart_type,
            'x_field': x_field,
            'y_field': y_field if chart_type == 'matrix' else '',
            'x_fields': x_fields if chart_type == 'matrix' else [x_field],
            'y_fields': y_fields if chart_type == 'matrix' else [],
            'metrics': valid_metrics,
        }
        cache.set(cache_key, result, 300)
        return success(result)

    # ─────────────────────────────────────────────────────────────
    # 概览仪表盘
    # ─────────────────────────────────────────────────────────────
    @action(detail=False, methods=['get'], url_path='overview')
    def overview(self, request):
        """
        概览仪表盘
        返回：
          kpi             - 6 个核心指标
          monthly_trend   - 月度换刀趋势（整刀+维修 堆叠，附费用）
          type_trend      - 各刀具类型累计换刀（按环号时序）
          recent_openings - 最近 10 次开仓摘要
        """
        cache_key = f"analysis_overview_{request.query_params.urlencode()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return success(cached)

        openings = _build_opening_queryset(request.query_params)
        all_details = _build_detail_queryset(openings, request.query_params)
        replaced = all_details.filter(is_replaced=True)

        # ── KPI ──────────────────────────────────────────────────
        total_openings = openings.count()
        # 更换刀具数 = 全部实际发生更换的记录（整体更换 + 维修更换 + 未分类）。
        # 原实现只统计 replacement_type='COMPLETE'，把维修换刀和类型未填写的记录
        # 全部漏掉，与助手/移动端口径相差数倍。COMPLETE / REPAIR 作为构成下钻。
        total_replacements = replaced.count()
        total_completes = replaced.filter(replacement_type='COMPLETE').count()
        total_repairs = replaced.filter(replacement_type='REPAIR').count()
        total_untyped = total_replacements - total_completes - total_repairs
        total_cost = replaced.aggregate(
            total=Sum('price', output_field=DecimalField())
        )['total'] or 0
        avg_rings = openings.aggregate(avg=Avg('rings_between_openings'))['avg'] or 0

        # 最近一次开仓的磨损率（按环号整数排序）
        abnormal_rate = 0.0
        healthy_rate = 0.0
        latest = (
            openings
            .filter(ring_no__regex=_RING_NUMERIC_REGEX).annotate(ring_int=Cast('ring_no', output_field=IntegerField()))
            .order_by('ring_int')
            .last()
        )
        if latest:
            latest_all = all_details.filter(warehouse=latest)
            total_cnt = latest_all.count()
            # 分母改为"有磨损记录"的行数：自动生成但未填写的行不再被算成异常
            recorded_cnt = latest_all.filter(Q_WEAR_RECORDED).count()
            if recorded_cnt > 0:
                healthy_cnt = latest_all.filter(Q_WEAR_NORMAL).count()
                abnormal_rate = round((recorded_cnt - healthy_cnt) / recorded_cnt, 3)
                healthy_rate = round(healthy_cnt / recorded_cnt, 3)

        kpi = {
            'total_openings': total_openings,
            'total_completes': total_completes,
            'total_untyped': total_untyped,
            'total_replacements': total_replacements,
            'total_repairs': total_repairs,
            'total_cost': float(total_cost),
            'avg_rings_between_openings': round(float(avg_rings), 1),
            'abnormal_wear_rate': abnormal_rate,
            'healthy_rate': healthy_rate,
        }

        # ── 月度趋势（整刀+维修 堆叠，附费用） ───────────────────
        monthly_qs = (
            replaced
            .annotate(month=TruncMonth('warehouse__open_time'))
            .values('month')
            .annotate(
                replacements=Count('id', filter=Q(replacement_type='COMPLETE')),
                repairs=Count('id', filter=Q(replacement_type='REPAIR')),
                cost=Sum('price', output_field=DecimalField()),
            )
            .order_by('month')
        )
        monthly_trend = [
            {
                'month': r['month'].strftime('%Y-%m') if r['month'] else '',
                'replacements': r['replacements'],
                'repairs': r['repairs'],
                'cost': float(r['cost'] or 0),
            }
            for r in monthly_qs
        ]

        # ── 各刀具类型累计换刀趋势（按环号时序，避免 N+1） ────────
        # 一次聚合：每个开仓×类型的换刀数
        type_counts_qs = (
            replaced
            .values('warehouse_id', 'tool_parent_type')
            .annotate(cnt=Count('id'))
        )
        # 转成 {warehouse_id: {type: count}}
        type_map: dict = {}
        for row in type_counts_qs:
            wid = row['warehouse_id']
            tp = row['tool_parent_type'] or ''
            type_map.setdefault(wid, {})[tp] = row['cnt']

        # 按环号整数排序，逐步累加
        sorted_openings = (
            openings
            .filter(ring_no__regex=_RING_NUMERIC_REGEX).annotate(ring_int=Cast('ring_no', output_field=IntegerField()))
            .order_by('ring_int')
        )
        cum = {'DISC': 0, 'RIPPER': 0, 'SCRAPER': 0}
        type_trend = []
        for op in sorted_openings:
            op_counts = type_map.get(op.id, {})
            for t in ('DISC', 'RIPPER', 'SCRAPER'):
                cum[t] += op_counts.get(t, 0)
            type_trend.append({
                'ring_no': op.ring_no,
                'DISC': cum['DISC'],
                'RIPPER': cum['RIPPER'],
                'SCRAPER': cum['SCRAPER'],
            })

        # ── 最近 10 次开仓摘要（一次聚合） ────────────────────────
        recent_agg = (
            all_details
            .values('warehouse_id')
            .annotate(
                replaced_count=Count('id', filter=Q(is_replaced=True)),
                cost=Sum('price', filter=Q(is_replaced=True),
                         output_field=DecimalField()),
                abnormal_count=Count('id', filter=Q_WEAR_ABNORMAL),
            )
        )
        # 转成 {warehouse_id: aggregated_data}
        agg_map = {r['warehouse_id']: r for r in recent_agg}

        recent_openings = []
        for op in sorted_openings.reverse()[:10]:
            agg = agg_map.get(op.id, {})
            recent_openings.append({
                'id': op.id,
                'warehouse_id': op.warehouse_id,
                'ring_no': op.ring_no,
                'open_time': (
                    op.open_time.strftime('%Y-%m-%d') if op.open_time else ''
                ),
                'replaced_count': agg.get('replaced_count', 0),
                'cost': float(agg.get('cost') or 0),
                'geological_conditions': op.geological_conditions or '',
                'abnormal_count': agg.get('abnormal_count', 0),
            })

        result = {
            'kpi': kpi,
            'monthly_trend': monthly_trend,
            'type_trend': type_trend,
            'recent_openings': recent_openings,
        }
        cache.set(cache_key, result, 300)
        return success(result)

    # ─────────────────────────────────────────────────────────────
    # 成本分析
    # ─────────────────────────────────────────────────────────────
    @action(detail=False, methods=['get'], url_path='cost_overview')
    def cost_overview(self, request):
        """
        成本构成概览
        返回：
          type_breakdown  - 各刀具类型成本占比（整刀 / 维修分拆）
          replacement_vs_repair - 整刀 vs 维修总额对比
        """
        cache_key = f"analysis_cost_overview_{request.query_params.urlencode()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return success(cached)

        openings = _build_opening_queryset(request.query_params)
        replaced = _build_detail_queryset(openings, request.query_params, only_replaced=True)

        # 整刀 vs 维修
        complete_cost = replaced.filter(replacement_type='COMPLETE').aggregate(
            total=Sum('price', output_field=DecimalField())
        )['total'] or 0
        repair_cost = replaced.filter(replacement_type='REPAIR').aggregate(
            total=Sum('price', output_field=DecimalField())
        )['total'] or 0
        # 总费用按"全部已更换记录"汇总，而不是 COMPLETE+REPAIR 相加——
        # 后者会把 replacement_type 未填写的记录（如移动端录入）静默丢掉，
        # 导致本卡片与概览 KPI 的总费用对不上。
        total_cost = float(
            replaced.aggregate(total=Sum('price', output_field=DecimalField()))['total'] or 0
        )
        untyped_cost = round(total_cost - float(complete_cost) - float(repair_cost), 2)
        ring_count = _get_ring_span(openings)

        tool_type = _get_query_value(request.query_params, 'tool_parent_type')
        display_types = [tool_type] if tool_type else [value for value, _ in TOOL_TYPES]

        cost_rows = (
            replaced
            .values('tool_parent_type', 'replacement_type')
            .annotate(total=Sum('price', output_field=DecimalField()))
        )
        cost_map = {
            (r['tool_parent_type'], r['replacement_type']): float(r['total'] or 0)
            for r in cost_rows
        }

        # 各刀具类型成本（整刀 + 维修分开）
        type_breakdown = []
        for tp in display_types:
            complete = cost_map.get((tp, 'COMPLETE'), 0)
            repair = cost_map.get((tp, 'REPAIR'), 0)
            type_breakdown.append({
                'tool_type': tp,
                'complete_cost': complete,
                'repair_cost': repair,
                'total': complete + repair,
            })

        result = {
            'replacement_vs_repair': {
                'complete': float(complete_cost),
                'repair': float(repair_cost),
                'total': total_cost,
            },
            'cost_per_ring': {
                'ring_count': ring_count,
                'complete': round(float(complete_cost) / ring_count, 2) if ring_count else 0,
                'repair': round(float(repair_cost) / ring_count, 2) if ring_count else 0,
                'total': round(total_cost / ring_count, 2) if ring_count else 0,
            },
            'type_breakdown': type_breakdown,
        }
        cache.set(cache_key, result, 300)
        return success(result)

    @action(detail=False, methods=['get'], url_path='cost_trend')
    def cost_trend(self, request):
        """
        成本时序趋势（每次开仓费用 + 累计费用）
        返回：
          items - [{ring_no, open_time, complete_cost, repair_cost, cumulative_cost}]
        """
        cache_key = f"analysis_cost_trend_{request.query_params.urlencode()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return success(cached)

        openings = _build_opening_queryset(request.query_params)
        replaced = _build_detail_queryset(openings, request.query_params, only_replaced=True)

        # 每次开仓的费用聚合
        cost_agg = (
            replaced
            .values('warehouse_id')
            .annotate(
                complete_cost=Sum('price', filter=Q(replacement_type='COMPLETE'),
                                  output_field=DecimalField()),
                repair_cost=Sum('price', filter=Q(replacement_type='REPAIR'),
                                output_field=DecimalField()),
            )
        )
        cost_map = {r['warehouse_id']: r for r in cost_agg}

        sorted_openings = (
            openings
            .filter(ring_no__regex=_RING_NUMERIC_REGEX).annotate(ring_int=Cast('ring_no', output_field=IntegerField()))
            .order_by('ring_int')
        )

        items = []
        cumulative = 0.0
        for op in sorted_openings:
            agg = cost_map.get(op.id, {})
            c = float(agg.get('complete_cost') or 0)
            r = float(agg.get('repair_cost') or 0)
            cumulative += c + r
            items.append({
                'ring_no': op.ring_no,
                'open_time': op.open_time.strftime('%Y-%m-%d') if op.open_time else '',
                'complete_cost': c,
                'repair_cost': r,
                'cumulative_cost': round(cumulative, 2),
            })

        result = {'items': items}
        cache.set(cache_key, result, 300)
        return success(result)

    @action(detail=False, methods=['get'], url_path='brand_cost')
    def brand_cost(self, request):
        """
        各厂家成本对比
        返回：
          items - [{manufacturer, total_cost, count, avg_cost}] 按费用降序
        """
        cache_key = f"analysis_brand_cost_{request.query_params.urlencode()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return success(cached)

        openings = _build_opening_queryset(request.query_params)
        replaced = _build_detail_queryset(openings, request.query_params, only_replaced=True)
        ring_count = _get_ring_span(openings)

        brand_qs = (
            replaced
            .exclude(manufacturer__isnull=True)
            .exclude(manufacturer='')
            .values('manufacturer')
            .annotate(
                total_cost=Sum('price', output_field=DecimalField()),
                count=Count('id'),
                priced_count=Count('id', filter=Q(price__isnull=False)),
                opening_count=Count('warehouse_id', distinct=True),
                abnormal_count=Count('id', filter=Q_WEAR_ABNORMAL),
                wear_recorded_count=Count('id', filter=Q_WEAR_RECORDED),
            )
            .order_by('-total_cost')
        )

        from collections import defaultdict
        replaced_with_ring = (
            replaced
            .exclude(manufacturer__isnull=True)
            .exclude(manufacturer='')
            .filter(warehouse__ring_no__regex=_RING_NUMERIC_REGEX).annotate(ring_int=Cast('warehouse__ring_no', output_field=IntegerField()))
            .values('cutter_position_id', 'manufacturer', 'replacement_count', 'ring_int')
            .order_by('cutter_position_id', 'replacement_count')
        )
        pos_records = defaultdict(list)
        for r in replaced_with_ring:
            pos_records[r['cutter_position_id']].append(r)

        manufacturer_lifespans = defaultdict(list)
        for records in pos_records.values():
            records.sort(key=lambda x: x['replacement_count'])
            for i in range(1, len(records)):
                prev = records[i - 1]
                curr = records[i]
                if curr['ring_int'] and prev['ring_int']:
                    lifespan = curr['ring_int'] - prev['ring_int']
                    if lifespan > 0:
                        # 归属修正：prev→curr 这段环数是"prev 那次装上的刀"的服役寿命，
                        # 原实现记在 curr（下一把新刀）的厂家名下，使整条链条错位一位，
                        # 厂家寿命排名会系统性反转。
                        manufacturer_lifespans[prev['manufacturer']].append(lifespan)

        items = [
            {
                'manufacturer': r['manufacturer'],
                'total_cost': float(r['total_cost'] or 0),
                'count': r['count'],
                'opening_count': r['opening_count'],
                'abnormal_count': r['abnormal_count'],
                'normal_count': r['count'] - r['abnormal_count'],
                # 均价分母只算"有价格"的记录，缺价格不等于降价
                'avg_cost': round(float(r['total_cost'] or 0) / r['priced_count'], 2) if r['priced_count'] else 0,
                'cost_per_ring': round(float(r['total_cost'] or 0) / ring_count, 2) if ring_count else 0,
                # 异常率分母只算"有磨损记录"的行
                'abnormal_rate': round(r['abnormal_count'] / r['wear_recorded_count'], 4) if r['wear_recorded_count'] else 0,
                'normal_rate': round((r['wear_recorded_count'] - r['abnormal_count']) / r['wear_recorded_count'], 4) if r['wear_recorded_count'] else 0,
                'avg_lifespan': round(
                    sum(manufacturer_lifespans.get(r['manufacturer'], [])) /
                    len(manufacturer_lifespans.get(r['manufacturer'], [])),
                    1,
                ) if manufacturer_lifespans.get(r['manufacturer']) else None,
                'lifespan_count': len(manufacturer_lifespans.get(r['manufacturer'], [])),
            }
            for r in brand_qs
        ]
        result = {'items': items, 'ring_count': ring_count}
        cache.set(cache_key, result, 300)
        return success(result)

    @action(detail=False, methods=['get'], url_path='brand_price_trend')
    def brand_price_trend(self, request):
        """
        各厂家平均单价随时间变化趋势
        返回：
          manufacturers - [str]  参与的厂家列表（用于前端图例）
          time_axis     - [{ring_no, open_time}]  时间轴（按环号升序）
          series        - [{manufacturer, data: [avg_price|null, ...]}]
            data 与 time_axis 等长，无数据点为 null
        """
        cache_key = f"analysis_brand_price_trend_{request.query_params.urlencode()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return success(cached)

        openings = _build_opening_queryset(request.query_params)

        replaced = (
            _build_detail_queryset(openings, request.query_params, only_replaced=True)
            .exclude(manufacturer__isnull=True)
            .exclude(manufacturer='')
        )

        # 按厂家 × 开仓 聚合平均单价
        agg = (
            replaced
            .values('manufacturer', 'warehouse_id')
            .annotate(
                avg_price=Avg('price', output_field=DecimalField()),
                count=Count('id'),
            )
        )

        # 构建 {warehouse_id: {manufacturer: avg_price}}
        from collections import defaultdict
        wh_brand_map = defaultdict(dict)
        all_manufacturers = set()
        for r in agg:
            wh_brand_map[r['warehouse_id']][r['manufacturer']] = {
                'avg_price': round(float(r['avg_price'] or 0), 2),
                'count': r['count'],
            }
            all_manufacturers.add(r['manufacturer'])

        # 时间轴：按环号升序
        sorted_openings = (
            openings
            .filter(ring_no__regex=_RING_NUMERIC_REGEX).annotate(ring_int=Cast('ring_no', output_field=IntegerField()))
            .order_by('ring_int')
        )
        time_axis = [
            {
                'ring_no': op.ring_no,
                'open_time': op.open_time.strftime('%Y-%m-%d') if op.open_time else '',
            }
            for op in sorted_openings
        ]
        wh_ids = [op.id for op in sorted_openings]

        manufacturers = sorted(all_manufacturers)
        series = []
        for mfr in manufacturers:
            data = []
            count_data = []
            for wh_id in wh_ids:
                stat = wh_brand_map[wh_id].get(mfr)
                data.append(stat['avg_price'] if stat else None)
                count_data.append(stat['count'] if stat else 0)
            series.append({'manufacturer': mfr, 'data': data, 'count_data': count_data})

        result = {
            'manufacturers': manufacturers,
            'time_axis': time_axis,
            'series': series,
        }
        cache.set(cache_key, result, 300)
        return success(result)

    @action(detail=False, methods=['get'], url_path='brand_performance_trend')
    def brand_performance_trend(self, request):
        """
        各厂家刀具性能随时间变化趋势
        指标：异常率、正常磨损率、平均使用寿命（环数）
        寿命定义：同一刀位相邻两次更换的开仓环号之差
                  即 ring_no(本次更换) - ring_no(上次更换)
                  通过 replacement_count 字段匹配相邻更换记录
        返回：
          manufacturers         - [str]
          time_axis             - [{ring_no, open_time}]
          abnormal_rate_series  - [{manufacturer, data: [rate|null, ...]}]
          normal_rate_series    - [{manufacturer, data: [rate|null, ...]}]
          lifespan_series       - [{manufacturer, data: [avg_rings|null, ...]}]
        """
        cache_key = f"analysis_brand_perf_trend_{request.query_params.urlencode()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return success(cached)

        openings = _build_opening_queryset(request.query_params)
        details = _build_detail_queryset(openings, request.query_params)

        replaced = details.filter(is_replaced=True).exclude(
            manufacturer__isnull=True).exclude(manufacturer='')

        # 按厂家 × 开仓聚合：总数、异常数
        agg = (
            replaced
            .values('manufacturer', 'warehouse_id')
            .annotate(
                total=Count('id'),
                abnormal=Count('id', filter=Q_WEAR_ABNORMAL),
            )
        )

        from collections import defaultdict
        wh_brand_map = defaultdict(dict)
        all_manufacturers = set()
        for r in agg:
            wh_brand_map[r['warehouse_id']][r['manufacturer']] = {
                'total': r['total'],
                'abnormal': r['abnormal'],
            }
            all_manufacturers.add(r['manufacturer'])

        # ── 寿命计算 ──────────────────────────────────────────────
        # 取所有更换记录（含开仓环号），按刀位 + replacement_count 排序
        # 寿命 = 本次更换环号 - 上次更换环号
        replaced_with_ring = (
            replaced
            .filter(warehouse__ring_no__regex=_RING_NUMERIC_REGEX).annotate(ring_int=Cast('warehouse__ring_no', output_field=IntegerField()))
            .values('cutter_position_id', 'manufacturer', 'warehouse_id', 'replacement_count', 'ring_int')
            .order_by('cutter_position_id', 'replacement_count')
        )

        # {warehouse_id: {manufacturer: [lifespan, ...]}}
        wh_brand_lifespans = defaultdict(lambda: defaultdict(list))

        # 按刀位分组，计算相邻更换的环数差
        pos_records = defaultdict(list)
        for r in replaced_with_ring:
            pos_records[r['cutter_position_id']].append(r)

        for pos_id, records in pos_records.items():
            records.sort(key=lambda x: x['replacement_count'])
            for i in range(1, len(records)):
                prev = records[i - 1]
                curr = records[i]
                if curr['ring_int'] and prev['ring_int']:
                    lifespan = curr['ring_int'] - prev['ring_int']
                    if lifespan > 0:
                        # 同上：寿命归属于装上这把刀的那次更换（prev），而非换下它的那次
                        wh_brand_lifespans[curr['warehouse_id']][prev['manufacturer']].append(lifespan)

        # 聚合为每次开仓的平均寿命
        wh_brand_avg_lifespan = {}
        for wh_id, brand_map in wh_brand_lifespans.items():
            wh_brand_avg_lifespan[wh_id] = {
                mfr: round(sum(ls) / len(ls), 1)
                for mfr, ls in brand_map.items() if ls
            }

        sorted_openings = (
            openings
            .filter(ring_no__regex=_RING_NUMERIC_REGEX).annotate(ring_int=Cast('ring_no', output_field=IntegerField()))
            .order_by('ring_int')
        )
        time_axis = [
            {
                'ring_no': op.ring_no,
                'open_time': op.open_time.strftime('%Y-%m-%d') if op.open_time else '',
            }
            for op in sorted_openings
        ]
        wh_ids = [op.id for op in sorted_openings]

        manufacturers = sorted(all_manufacturers)
        abnormal_rate_series = []
        normal_rate_series = []
        lifespan_series = []

        for mfr in manufacturers:
            abnormal_data = []
            normal_data = []
            total_count_data = []
            abnormal_count_data = []
            lifespan_data = []
            lifespan_count_data = []
            for wh_id in wh_ids:
                stat = wh_brand_map[wh_id].get(mfr)
                if stat is None or stat['total'] == 0:
                    abnormal_data.append(None)
                    normal_data.append(None)
                    total_count_data.append(0)
                    abnormal_count_data.append(0)
                else:
                    abnormal_data.append(round(stat['abnormal'] / stat['total'], 4))
                    normal_data.append(round((stat['total'] - stat['abnormal']) / stat['total'], 4))
                    total_count_data.append(stat['total'])
                    abnormal_count_data.append(stat['abnormal'])
                lifespan_val = wh_brand_avg_lifespan.get(wh_id, {}).get(mfr)
                lifespan_data.append(lifespan_val)
                lifespan_count_data.append(len(wh_brand_lifespans.get(wh_id, {}).get(mfr, [])))
            abnormal_rate_series.append({
                'manufacturer': mfr,
                'data': abnormal_data,
                'count_data': total_count_data,
                'abnormal_count_data': abnormal_count_data,
            })
            normal_rate_series.append({
                'manufacturer': mfr,
                'data': normal_data,
                'count_data': total_count_data,
                'abnormal_count_data': abnormal_count_data,
            })
            lifespan_series.append({
                'manufacturer': mfr,
                'data': lifespan_data,
                'count_data': lifespan_count_data,
            })

        result = {
            'manufacturers': manufacturers,
            'time_axis': time_axis,
            'abnormal_rate_series': abnormal_rate_series,
            'normal_rate_series': normal_rate_series,
            'lifespan_series': lifespan_series,
        }
        cache.set(cache_key, result, 300)
        return success(result)

    # ─────────────────────────────────────────────────────────────
    # 磨损分析
    # ─────────────────────────────────────────────────────────────
    @action(detail=False, methods=['get'], url_path='wear_distribution')
    def wear_distribution(self, request):
        """
        磨损等级分布
        返回：
          items - [{wear_condition, count, percentage}]
        支持 tool_parent_type 筛选
        """
        cache_key = f"analysis_wear_dist_{request.query_params.urlencode()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return success(cached)

        openings = _build_opening_queryset(request.query_params)
        details = _build_detail_queryset(openings, request.query_params)

        wear_qs = (
            details
            .values('wear_condition')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        total = details.count()
        items = [
            {
                'wear_condition': r['wear_condition'] or '未知',
                'count': r['count'],
                'percentage': round(r['count'] / total * 100, 1) if total else 0,
            }
            for r in wear_qs
        ]
        result = {'items': items, 'total': total}
        cache.set(cache_key, result, 300)
        return success(result)

    @action(detail=False, methods=['get'], url_path='wear_trend')
    def wear_trend(self, request):
        """
        磨损率时序趋势（按开仓环号）
        返回：
          items - [{ring_no, open_time, total, abnormal, abnormal_rate, stratum_types}]
        """
        cache_key = f"analysis_wear_trend_{request.query_params.urlencode()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return success(cached)

        openings = _build_opening_queryset(request.query_params)
        all_details = _build_detail_queryset(openings, request.query_params)

        # 每次开仓：总数 + 异常数（一次聚合）
        wear_agg = (
            all_details
            .values('warehouse_id')
            .annotate(
                total=Count('id', filter=Q_WEAR_RECORDED),
                abnormal=Count('id', filter=Q_WEAR_ABNORMAL),
            )
        )
        agg_map = {r['warehouse_id']: r for r in wear_agg}

        sorted_openings = (
            openings
            .filter(ring_no__regex=_RING_NUMERIC_REGEX).annotate(ring_int=Cast('ring_no', output_field=IntegerField()))
            .order_by('ring_int')
        )
        items = []
        for op in sorted_openings:
            agg = agg_map.get(op.id, {'total': 0, 'abnormal': 0})
            total = agg['total']
            abnormal = agg['abnormal']
            abnormal_rate = round(abnormal / total, 3) if total else 0
            # 地层类型信息（转换为中文名）
            stratum_types = ''
            if hasattr(op, 'stratum_info_between') and op.stratum_info_between:
                label_map = _get_stratum_label_map()
                stratum_types = '、'.join(
                    label_map.get(k, k) for k in op.stratum_info_between.keys()
                )
            items.append({
                'ring_no': op.ring_no,
                'open_time': op.open_time.strftime('%Y-%m-%d') if op.open_time else '',
                'total': total,
                'abnormal': abnormal,
                'abnormal_rate': abnormal_rate,
                'geological_conditions': op.geological_conditions or '',
                'stratum_types': stratum_types,
            })

        result = {'items': items}
        cache.set(cache_key, result, 300)
        return success(result)
