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
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.authentication import JWTAuthentication
from dvadmin.utils.permission import CustomPermission
from django.db.models import (
    Count, Sum, Avg, Q, IntegerField, DecimalField, FloatField, Min, Max
)
from django.db.models.functions import TruncMonth, Cast
from django.utils import timezone
from django.core.cache import cache as shared_cache
from .models import (
    WarehouseOpeningBasicInfo,
    ToolChangeDetail,
    ShieldTunnelingData,
    StratumBasicInfo,
    TOOL_TYPES,
    NewToolRecord, OldToolRecord,
)
from .wear import (
    Q_WEAR_ABNORMAL,
    Q_WEAR_NORMAL,
    Q_WEAR_RECORDED,
    normalize_wear,
    classify_wear_counts,
)
from .analysis_metrics import (
    active_observed_queryset, analysis_meta, cost_source_rows, select_cost_rows,
    summarize_cost_rows, confirmed_service_segments,
    RING_NUMERIC_REGEX,
    ANALYSIS_REQUEST, scoped_queryset, blade_track_range,
)


class _AnalysisCache:
    """Business aggregates are fresh per request; only dictionary labels are cached.

    Opening confirmation/withdrawal and vendor feedback can change any old ring.
    There is no analysis invalidation event, so an expiring aggregate cannot claim
    to represent the current confirmed scope.
    """
    @staticmethod
    def get(key):
        return None if key.startswith('analysis_') else shared_cache.get(key)

    @staticmethod
    def set(key, value, timeout):
        if not key.startswith('analysis_'):
            shared_cache.set(key, value, timeout)


cache = _AnalysisCache()


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
_RING_NUMERIC_REGEX = RING_NUMERIC_REGEX


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
    {'value': 'checked_tool_count', 'label': '有效观察记录数', 'unit': '条'},
    {'value': 'replacement_count', 'label': '更换刀具数', 'unit': '把'},
    {'value': 'complete_count', 'label': '整刀更换数', 'unit': '把'},
    {'value': 'repair_count', 'label': '维修数', 'unit': '次'},
    {'value': 'abnormal_count', 'label': '异常磨损数', 'unit': '把'},
    {'value': 'abnormal_rate', 'label': '异常磨损率', 'unit': '%'},
    {'value': 'normal_rate', 'label': '正常磨损率', 'unit': '%'},
    {'value': 'total_cost', 'label': '登记费用合计', 'unit': '元'},
    {'value': 'avg_price', 'label': '更换登记均价（含历史）', 'unit': '元'},
    {'value': 'cost_per_opening', 'label': '平均每次开仓登记费用', 'unit': '元/次'},
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
    qs = active_observed_queryset(
        scoped_queryset(ToolChangeDetail.objects.filter(warehouse__in=openings)),
        track_bounds=blade_track_range(params),
    )
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
        cost_query = Q(pk__in=[])
        if 'COMPLETE' in cost_types:
            cost_query |= Q(id__in=scoped_queryset(NewToolRecord.objects.all()).values('tool_change_detail_id')) | Q(replacement_type='COMPLETE')
        if 'REPAIR' in cost_types:
            cost_query |= Q(id__in=scoped_queryset(OldToolRecord.objects.all()).values('tool_change_detail_id')) | Q(replacement_type='REPAIR')
        qs = qs.filter(cost_query)

    return qs


def _build_opening_queryset(params, include_all_statuses=False, include_invalid_rings=False):
    """
    根据筛选参数构造开仓记录 QuerySet
    params: request.query_params（QueryDict）
    """
    qs = scoped_queryset(WarehouseOpeningBasicInfo.objects.all())
    if not include_invalid_rings:
        qs = qs.filter(ring_no__regex=_RING_NUMERIC_REGEX)
    status = str(params.get('summary_status') or 'CONFIRMED').upper()
    if status not in {'CONFIRMED', 'DRAFT', 'ALL'}:
        raise ValidationError({'summary_status': '请选择 CONFIRMED、DRAFT 或 ALL'})
    if not include_all_statuses and status != 'ALL':
        qs = qs.filter(summary_status=status)

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
    elif project:
        raise ValidationError({'project': '项目编号必须是整数'})
    if machine and machine_int is not None:
        qs = qs.filter(shield_model_id=machine_int)
    elif machine:
        raise ValidationError({'shield_machine': '盾构机编号必须是整数'})
    if start_ring or end_ring:
        # ring_no 是 CharField，转成整数后过滤（跳过非数字环号）
        qs = _with_ring_int(qs)
        start_ring_int = _safe_int(start_ring)
        end_ring_int = _safe_int(end_ring)
        if (start_ring and start_ring_int is None) or (end_ring and end_ring_int is None):
            raise ValidationError({'ring_range': '环号必须是整数'})
        if start_ring_int is not None and end_ring_int is not None and start_ring_int > end_ring_int:
            raise ValidationError({'ring_range': '起始环号不能大于结束环号'})
        if start_ring_int is not None:
            qs = qs.filter(ring_int__gte=start_ring_int)
        if end_ring_int is not None:
            qs = qs.filter(ring_int__lte=end_ring_int)

    if stratum_types:
        qs = qs.filter(stratum_info_between__has_any_keys=stratum_types)

    return qs


def _meta(openings, params, details=None):
    raw = scoped_queryset(ToolChangeDetail.objects.filter(warehouse__in=openings))
    result = analysis_meta(
        openings, params, raw,
        details if details is not None else _build_detail_queryset(openings, params),
        _build_opening_queryset(params, include_all_statuses=True).filter(summary_status='DRAFT').count(),
    )
    ring_free = params.copy()
    for key in ('start_ring', 'end_ring'):
        if key in ring_free:
            del ring_free[key]
    result['excluded_invalid_ring_opening_count'] = _build_opening_queryset(
        ring_free, include_invalid_rings=True,
    ).exclude(ring_no__regex=_RING_NUMERIC_REGEX).count()
    if result['excluded_invalid_ring_opening_count']:
        result['warnings'].append('环号必须为1至9位数字；范围内存在不可定位的历史开仓，已排除并单列数量。')
    return result


def _cost_detail_rows(details):
    """Load only replaced rows and fields used by cost attribution and pairing."""
    return list(details.filter(is_replaced=True).annotate(
        analysis_source_ring=Cast('warehouse__ring_no', output_field=IntegerField()),
    ).order_by('cutter_position_no', 'analysis_source_ring', 'warehouse_id', 'id')
        .select_related('warehouse', 'new_tool_record', 'old_tool_record').only(
        'id', 'warehouse_id', 'cutter_position_no', 'tool_parent_type', 'is_replaced',
        'price', 'manufacturer', 'tool_number', 'replacement_type', 'wear_condition',
        'warehouse__id', 'warehouse__warehouse_id', 'warehouse__ring_no', 'warehouse__open_time',
        'warehouse__project_id', 'warehouse__shield_model_id', 'warehouse__summary_status',
        'new_tool_record__id', 'new_tool_record__tool_change_detail_id',
        'old_tool_record__id', 'old_tool_record__tool_change_detail_id', 'old_tool_record__old_tool_number',
        'old_tool_record__inspection_status', 'old_tool_record__repair_price',
    ))


def _cost_rows(details, params, service_segments=None):
    loaded = _cost_detail_rows(details) if hasattr(details, 'select_related') else details
    rows = cost_source_rows(loaded)
    segments = {row['detail_id']: row for row in (
        service_segments if service_segments is not None else confirmed_service_segments(loaded))}
    for row in rows:
        if row.get('original_source') == 'confirmed_repair':
            segment = segments.get(row['detail_id'])
            row['manufacturer'] = segment['manufacturer'] if segment and segment['paired'] else ''
            row['manufacturer_basis'] = '旧刀原安装厂家' if row['manufacturer'] else '旧刀厂家待核实'
    cost_types = [value.upper() for value in _get_query_values(params, 'cost_type', 'cost_types', 'cost_types[]')]
    rows = select_cost_rows(rows, cost_types)
    manufacturers = _get_query_values(params, 'manufacturer', 'manufacturers', 'manufacturers[]')
    return [row for row in rows if not manufacturers or row['manufacturer'] in manufacturers]


def _ring_allocation(openings, params, sources):
    scopes = set(openings.values_list('project_id', 'shield_model_id'))
    stratum = _get_query_values(params, 'stratum_type', 'stratum_types', 'stratum_types[]', 'stratumType', 'stratumTypes', 'stratumTypes[]')
    span = _get_ring_span(openings)
    available = len(scopes) == 1 and None not in next(iter(scopes), ()) and openings.count() >= 2 and span > 1 and not stratum
    reason = '' if available else '仅单项目、单盾构机、至少两个不同开仓环号且未筛地层时计算'
    return {
        'available': available, 'reason': reason, 'ring_count': span if available else 0,
        'basis': '最大开仓环号 − 最小开仓环号 + 1；不是实际掘进环数',
        'complete': round(sources['installation'] / span, 2) if available else None,
        'repair': round(sources['confirmed_repair'] / span, 2) if available else None,
        'total': round(sources['total'] / span, 2) if available else None,
    }


def _apply_cost_contract(action, data, openings, details, params):
    rows = _cost_rows(_build_detail_queryset(openings, params, include_manufacturer=False), params)
    sources = summarize_cost_rows(rows)
    data['cost_sources'] = sources
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['opening_id']].append(row)
    opening_list = list(_with_ring_int(openings).order_by('ring_int', 'id'))
    if action == 'overview':
        data['kpi']['cost_sources'] = sources
        data['kpi']['total_cost'] = sources['total']
        month_rows = defaultdict(list)
        for op in opening_list:
            month_rows[_date_text(op.open_time, '%Y-%m')].extend(grouped[op.id])
        monthly = {item['month']: item for item in data['monthly_trend']}
        for month, source_rows in month_rows.items():
            item = monthly.setdefault(month, {'month': month, 'replacements': 0, 'repairs': 0, 'untyped': 0, 'total_replacements': 0})
            item['cost_sources'] = summarize_cost_rows(source_rows)
            item['cost'] = item['cost_sources']['total']
        data['monthly_trend'] = [monthly[month] for month in sorted(monthly)]
        for item in data['recent_openings']:
            item['cost_sources'] = summarize_cost_rows(grouped[item['id']])
            item['cost'] = item['cost_sources']['total']
    elif action == 'cost_overview':
        data['source_rows'] = rows
        data['source_rows_total'] = len(rows)
        data['source_rows_truncated'] = False
        data['replacement_vs_repair'] = {'complete': sources['installation'], 'repair': sources['confirmed_repair'], 'legacy': sources['legacy'], 'unresolved': sources['unresolved'], 'total': sources['total']}
        data['cost_per_ring'] = _ring_allocation(openings, params, sources)
        types = list(dict.fromkeys([item['tool_type'] for item in data['type_breakdown']] + [row['tool_parent_type'] for row in rows]))
        data['type_breakdown'] = []
        for tool_type in types:
            part = summarize_cost_rows([row for row in rows if row['tool_parent_type'] == tool_type])
            data['type_breakdown'].append({'tool_type': tool_type, 'cost_sources': part,
                'complete_cost': part['installation'], 'repair_cost': part['confirmed_repair'], 'legacy_cost': part['legacy'], 'total': part['total']})
    elif action == 'cost_trend':
        data['items'] = []
        cumulative = 0
        counts = dict(details.filter(is_replaced=True).values('warehouse_id').annotate(n=Count('id')).values_list('warehouse_id', 'n'))
        for op in opening_list:
            part = summarize_cost_rows(grouped[op.id])
            cumulative = round(cumulative + part['total'], 2)
            data['items'].append({'opening_id': op.id, 'ring_no': op.ring_no, 'open_time': _date_text(op.open_time, '%Y-%m-%d'),
                'complete_cost': part['installation'], 'repair_cost': part['confirmed_repair'],
                'installation_cost': part['installation'], 'confirmed_repair_cost': part['confirmed_repair'],
                'legacy_cost': part['legacy'], 'unresolved_cost': part['unresolved'], 'total_cost': part['total'],
                'cumulative_cost': cumulative, 'replacement_count': counts.get(op.id, 0), 'cost_sources': part})
    return rows


def _brand_contract(action, openings, params):
    broad = _build_detail_queryset(openings, params, only_replaced=True, include_manufacturer=False).select_related('warehouse')
    selected = _get_query_values(params, 'manufacturer', 'manufacturers', 'manufacturers[]')
    supply = _cost_detail_rows(broad)
    visible_install_ids = set(scoped_queryset(NewToolRecord.objects.filter(
        tool_change_detail_id__in=[row.id for row in supply],
    )).values_list('tool_change_detail_id', flat=True))
    segments = confirmed_service_segments(supply)
    costs = _cost_rows(supply, params, service_segments=segments)
    total_sources = summarize_cost_rows(costs)
    allocation = _ring_allocation(openings, params, total_sources)
    if selected:
        supply = [row for row in supply if row.manufacturer in selected]
        segments = [row for row in segments if row['manufacturer'] in selected]
    names = sorted({row.manufacturer for row in supply if row.manufacturer}
                   | {row['manufacturer'] for row in segments if row['manufacturer']}
                   | {row['manufacturer'] for row in costs if row['manufacturer']})
    items = []
    for name in names:
        installed = [row for row in supply if row.manufacturer == name]
        modern = [row for row in installed if row.id in visible_install_ids]
        priced = [row for row in modern if row.price is not None]
        pairs = [row for row in segments if row['manufacturer'] == name and row['paired']]
        wear = [row for row in pairs if row['wear_state'] is not None]
        abnormal = sum(row['wear_state'] == 'ABNORMAL' for row in wear)
        sources = summarize_cost_rows([row for row in costs if row['manufacturer'] == name])
        items.append({
            'manufacturer': name, 'total_cost': sources['total'], 'cost_sources': sources,
            'count': len(installed), 'opening_count': len({row.warehouse_id for row in installed}),
            'installation_count': len(modern), 'legacy_replacement_count': len(installed) - len(modern),
            'priced_count': len(priced), 'missing_price_count': len(modern) - len(priced),
            'avg_cost': round(sum(float(row.price) for row in priced) / len(priced), 2) if priced else None,
            'cost_per_ring': round(sources['total'] / allocation['ring_count'], 2) if allocation['available'] else None,
            'abnormal_count': abnormal,
            'normal_count': len(wear) - abnormal, 'wear_recorded_count': len(wear),
            'unrecorded_wear_count': len(pairs) - len(wear),
            'abnormal_rate': round(abnormal / len(wear), 4) if wear else None,
            'normal_rate': round((len(wear) - abnormal) / len(wear), 4) if wear else None,
            'avg_lifespan': round(sum(row['service_rings'] for row in pairs) / len(pairs), 1) if pairs else None,
            'lifespan_count': len(pairs), 'paired_count': len(pairs),
            'pairing_unresolved_count': sum(row['manufacturer'] == name and not row['paired'] for row in segments),
        })
    items.sort(key=lambda item: (-item['total_cost'], item['manufacturer']))
    base = {
        'items': items, 'ring_count': allocation['ring_count'],
        'service_rows': segments, 'service_rows_total': len(segments), 'service_rows_truncated': False,
        'pairing_unresolved_count': sum(not row['paired'] for row in segments),
        'unknown_manufacturer_count': sum(not row.manufacturer for row in supply),
        'cost_sources': total_sources,
        'source_rows': costs, 'source_rows_total': len(costs), 'source_rows_truncated': False,
        'service_basis': '按拆除环归集的系统已确认配对服役段；已拆刀样本，不代表总体寿命',
    }
    if action == 'brand_cost':
        return base
    ordered = list(_with_ring_int(openings).order_by('ring_int', 'id'))
    base.update(manufacturers=names, time_axis=[{'opening_id': op.id, 'ring_no': op.ring_no, 'open_time': _date_text(op.open_time, '%Y-%m-%d')} for op in ordered])
    if action == 'brand_price_trend':
        series = []
        for name in names:
            values, counts, missing = [], [], []
            for op in ordered:
                installed = [row for row in supply if row.manufacturer == name and row.warehouse_id == op.id]
                modern = [row for row in installed if row.id in visible_install_ids]
                priced = [row for row in modern if row.price is not None]
                values.append(round(sum(float(row.price) for row in priced) / len(priced), 2) if priced else None)
                counts.append(len(priced))
                missing.append(len(modern) - len(priced))
            series.append({'manufacturer': name, 'data': values, 'count_data': counts, 'missing_price_count_data': missing})
        base['series'] = series
    else:
        for field in ('abnormal_rate_series', 'normal_rate_series', 'lifespan_series'):
            base[field] = []
        for name in names:
            abnormal_values, normal_values, wear_counts, abnormal_counts, lives, life_counts = [], [], [], [], [], []
            for op in ordered:
                pairs = [row for row in segments if row['manufacturer'] == name and row['opening_id'] == op.id and row['paired']]
                wear = [row for row in pairs if row['wear_state'] is not None]
                abnormal = sum(row['wear_state'] == 'ABNORMAL' for row in wear)
                abnormal_values.append(round(abnormal / len(wear), 4) if wear else None)
                normal_values.append(round((len(wear) - abnormal) / len(wear), 4) if wear else None)
                wear_counts.append(len(wear)); abnormal_counts.append(abnormal)
                lives.append(round(sum(row['service_rings'] for row in pairs) / len(pairs), 1) if pairs else None)
                life_counts.append(len(pairs))
            for field, values, counts in (('abnormal_rate_series', abnormal_values, wear_counts), ('normal_rate_series', normal_values, wear_counts), ('lifespan_series', lives, life_counts)):
                base[field].append({'manufacturer': name, 'data': values, 'count_data': counts, 'abnormal_count_data': abnormal_counts})
    return base


def _wear_details(openings, params):
    """A manufacturer filter refers to the inspected old tool, not its replacement."""
    details = _build_detail_queryset(openings, params, include_manufacturer=False)
    selected = _get_query_values(params, 'manufacturer', 'manufacturers', 'manufacturers[]')
    if not selected:
        return details
    ids = [row['detail_id'] for row in confirmed_service_segments(details.select_related('warehouse'))
           if row['paired'] and row['manufacturer'] in selected]
    return details.filter(id__in=ids)


def _date_text(value, fmt):
    if value and hasattr(value, 'tzinfo') and timezone.is_aware(value):
        value = timezone.localtime(value)
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
        return round(bucket['abnormal_count'] / denom * 100, 2) if denom else None
    if metric == 'normal_rate':
        return round(
            (bucket['wear_recorded_count'] - bucket['abnormal_count']) / denom * 100, 2
        ) if denom else None
    if metric == 'total_cost':
        return round(bucket['price_total'], 2)
    if metric == 'avg_price':
        return round(bucket['avg_price_total'] / price_count, 2) if price_count else None
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
        'avg_price_total': 0.0,
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
    'avg_price_total',
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
    bucket['detail_count'] += record.get('observation_count', 1)
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
    bucket['price_total'] += record.get('cost_total', record['price'] or 0)
    if record['price'] is not None:
        bucket['avg_price_total'] += record['price']
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


def _build_custom_records(openings, details, metrics=None, params=None):
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
            tunneling_qs = scoped_queryset(ShieldTunnelingData.objects.filter(ring_no__in=ring_nos))
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
                scoped_queryset(StratumBasicInfo.objects
                .filter(project_id__in=project_ids, ring_no__in=ring_nos))
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
    source_map = defaultdict(list)
    for source in _cost_rows(details, params or {}):
        source_map[source['detail_id']].append(source)
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
            'replacement_type': replacement_type_labels.get(detail.replacement_type, '未分类更换' if detail.is_replaced else '未更换'),
            'replacement_type_raw': detail.replacement_type,
            'wear_condition': detail.wear_condition or empty,
            'wear_condition_raw': detail.wear_condition,
            'stratum_types': stratum_types or [empty],
            'geological_conditions': op.geological_conditions or empty,
            'is_replaced': detail.is_replaced,
            'price': price if detail.is_replaced else None,
            'cost_total': summarize_cost_rows(source_map[detail.id])['total'],
            '_cost_sources': source_map[detail.id],
            'opening_duration': _safe_float(op.opening_duration),
            'rings_between_openings': _safe_float(op.rings_between_openings),
            'thrust': _safe_float(tunneling.get('thrust')),
            'torque': _safe_float(tunneling.get('torque')),
            'cutterhead_speed': _safe_float(tunneling.get('cutterhead_speed')),
            'penetration': _safe_float(tunneling.get('penetration')),
            'burial_depth': burial_depth_map.get((op.project_id, op.ring_no)),
        }
        records.append(record)
    if _get_query_values(params or {}, 'manufacturer', 'manufacturers', 'manufacturers[]') and set(metrics) & {'total_cost', 'cost_per_opening'}:
        records = [record for record in records if record['_cost_sources']]
    return records


def _custom_cost_dimensions(records, fields, metrics):
    """Source rows may carry a different supplier than this event's new tool."""
    vendor_axis = bool(set(fields) & {'manufacturer', 'brand'})
    if vendor_axis and set(metrics) & {'abnormal_count', 'abnormal_rate', 'normal_rate'}:
        raise ValidationError({'metrics': '厂家磨损请使用厂家表现页的已确认旧刀配对统计；不支持直接按新装厂家分组'})
    costs = {'total_cost', 'cost_per_opening'}
    if 'replacement_type' in fields and set(metrics) & costs:
        raise ValidationError({'metrics': '同一次更换可有新装与返修费用；费用构成请使用成本分析页，不能按旧更换类型分摊'})
    if not vendor_axis or not set(metrics) & costs:
        return records
    if set(metrics) - costs - {'opening_count'}:
        raise ValidationError({'metrics': '厂家费用按费用来源分组，与新装数量或均价样本不同，请分别查询'})
    if 'brand' in fields:
        raise ValidationError({'x_field': '返修来源没有可靠旧刀品牌快照，请改用厂家分组或移除费用指标'})
    result = []
    for record in records:
        for source in record['_cost_sources']:
            if source['included']:
                result.append({**record, 'manufacturer': source['manufacturer'] or '厂家待核实',
                               'price': source['amount'], 'cost_total': source['amount'],
                               'observation_count': 0, 'is_replaced': False})
    return result


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

    def dispatch(self, request, *args, **kwargs):
        token = ANALYSIS_REQUEST.set(None)
        try:
            return super().dispatch(request, *args, **kwargs)
        finally:
            ANALYSIS_REQUEST.reset(token)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.permission_classes:
            ANALYSIS_REQUEST.set(request)
        # Validate even metadata-only actions before finalization, so invalid
        # scope follows the project's standard error envelope.
        _build_opening_queryset(request.query_params)
        blade_track_range(request.query_params)

    def analysis_success(self, request, data):
        """Enhance inside the action so errors still use DRF's exception handler."""
        openings = _build_opening_queryset(request.query_params)
        details = _build_detail_queryset(openings, request.query_params)
        if self.action in {'wear_distribution', 'wear_trend'}:
            details = _wear_details(openings, request.query_params)
        data['meta'] = _meta(openings, request.query_params, details)
        data['meta']['observed_basis'] = '当前筛选的新装/现场明细样本；费用来源和已拆刀样本分别计数'
        if self.action in {'wear_distribution', 'wear_trend'}:
            data['meta']['observed_basis'] = '当前现场磨损观察样本；筛厂家时仅系统已确认旧刀配对'
        if 'service_rows' in data:
            data['meta']['service_sample_count'] = sum(row['paired'] for row in data['service_rows'])
            data['meta']['pairing_unresolved_count'] = data.get('pairing_unresolved_count', 0)
        if self.action in {'overview', 'cost_overview', 'cost_trend'}:
            sources = _apply_cost_contract(self.action, data, openings, details, request.query_params)
            data['meta']['cost_source_count'] = len(sources)
        elif 'source_rows_total' in data:
            data['meta']['cost_source_count'] = data['source_rows_total']
        if self.action in {'brand_price_trend', 'brand_performance_trend'} and request.query_params.get('include_details') == 'false':
            for key in ('items', 'source_rows', 'service_rows'):
                data.pop(key, None)
        return success(data)

    @action(detail=False, methods=['get'], url_path='brand_stratum_performance')
    def brand_stratum_performance(self, request):
        from .stratum_performance import manufacturer_stratum_performance
        params = request.query_params.copy()
        selected = str(params.get('service_stratum') or '').strip()
        # The ordinary stratum filter selects opening intervals. This action
        # instead examines every ring of each complete installation segment.
        for key in ('stratum_type', 'stratum_types', 'stratum_types[]', 'stratumType', 'stratumTypes', 'stratumTypes[]'):
            params.pop(key, None)
        openings = _build_opening_queryset(params)
        details = _build_detail_queryset(openings, params, only_replaced=True, include_manufacturer=False)
        data = manufacturer_stratum_performance(
            details, selected, _get_query_values(params, 'manufacturer', 'manufacturers', 'manufacturers[]'),
            _get_stratum_label_map(),
        )
        data['meta'] = _meta(openings, params, details)
        data['meta']['scope']['service_stratum'] = selected
        data['meta']['observed_basis'] = '按拆除开仓范围选取已确认旧刀配对，再关联其完整服役环段地层'
        return success(data)

    @action(detail=False, methods=['get'], url_path='filter_options')
    def filter_options(self, request):
        """
        分析筛选项。
        manufacturer 会按项目/盾构机/环号/刀具类型联动，便于厂家图表聚焦。
        """
        cache_key = f"analysis_filter_options_{request.query_params.urlencode()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return self.analysis_success(request, cached)

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
        manufacturers = sorted(set(manufacturers) | {
            row['manufacturer'] for row in confirmed_service_segments(details.select_related('warehouse'))
            if row['manufacturer'] and row['paired']
        })
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
                if value in {'DISC', 'SCRAPER'}
            ],
            'tool_type_names': tool_type_names,
            'stratum_types': stratum_types,
            'manufacturers': manufacturers,
        }
        cache.set(cache_key, result, 300)
        return self.analysis_success(request, result)

    @action(detail=False, methods=['get'], url_path='custom_fields')
    def custom_fields(self, request):
        """
        自定义分析可选字段。
        返回前端可用于 X/Y 轴和矩阵维度的白名单，避免任意字段查询。
        """
        return self.analysis_success(request, {
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
                    'metrics': ['total_cost'],
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
            valid_metrics = ['replacement_count', 'abnormal_rate'] if chart_type == 'line' else ['total_cost']
        valid_metrics = valid_metrics[:2]

        cache_key = (
            f"analysis_custom_chart_v3_{chart_type}_{','.join(x_fields or [x_field])}_{','.join(y_fields or [y_field])}_"
            f"{','.join(valid_metrics)}_{request.query_params.urlencode()}"
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return self.analysis_success(request, cached)

        openings = _build_opening_queryset(request.query_params)
        details = _build_detail_queryset(openings, request.query_params)
        manufacturer_selected = bool(_get_query_values(request.query_params, 'manufacturer', 'manufacturers', 'manufacturers[]'))
        if manufacturer_selected and set(valid_metrics) & {'abnormal_count', 'abnormal_rate', 'normal_rate'}:
            raise ValidationError({'metrics': '厂家磨损请在厂家表现页按已确认旧刀样本查询'})
        cost_metrics = {'total_cost', 'cost_per_opening'}
        if manufacturer_selected and set(valid_metrics) & cost_metrics:
            if set(valid_metrics) - cost_metrics - {'opening_count'}:
                raise ValidationError({'metrics': '筛选厂家时费用来源与新装观察样本不同，请将费用与数量/均价分别查询'})
            details = _build_detail_queryset(openings, request.query_params, include_manufacturer=False)
        records = _build_custom_records(openings, details, valid_metrics, request.query_params)
        records = _custom_cost_dimensions(records, (x_fields + y_fields) if chart_type == 'matrix' else [x_field], valid_metrics)

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
        result['record_basis'] = '费用来源记录' if set(valid_metrics) & cost_metrics and set((x_fields + y_fields) if chart_type == 'matrix' else [x_field]) & {'manufacturer', 'brand'} else '有效现场观察明细'
        result['excluded_combination_note'] = '厂家磨损由厂家表现页按旧刀配对统计；地层组可能重叠'
        cache.set(cache_key, result, 300)
        return self.analysis_success(request, result)

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
            return self.analysis_success(request, cached)

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
        abnormal_rate = None
        healthy_rate = None
        latest = (
            openings
            .filter(ring_no__regex=_RING_NUMERIC_REGEX).annotate(ring_int=Cast('ring_no', output_field=IntegerField()))
            .order_by('ring_int')
            .last()
        )
        if latest:
            latest_all = _wear_details(openings, request.query_params).filter(warehouse=latest)
            total_cnt = latest_all.count()
            # 分母改为"有磨损记录"的行数：自动生成但未填写的行不再被算成异常
            counts = classify_wear_counts(latest_all.values_list('wear_condition', flat=True))
            recorded_cnt = counts['recorded']
            if recorded_cnt > 0:
                healthy_cnt = counts['normal']
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
            'detail_checked_count': all_details.count(),
            'summary_checked_count': openings.filter(summary_status='CONFIRMED').aggregate(n=Sum('checked_tool_count'))['n'] or 0,
            'summary_replaced_count': openings.filter(summary_status='CONFIRMED').aggregate(n=Sum('replaced_tool_count'))['n'] or 0,
        }
        confirmed_details = active_observed_queryset(scoped_queryset(ToolChangeDetail.objects.filter(
            warehouse__in=openings.filter(summary_status='CONFIRMED'), is_replaced=True,
        ))).count()
        kpi['summary_detail_replaced_count'] = confirmed_details
        kpi['replacement_gap'] = kpi['summary_replaced_count'] - confirmed_details

        # ── 月度趋势（整刀+维修 堆叠，附费用） ───────────────────
        monthly_qs = (
            replaced
            .annotate(month=TruncMonth('warehouse__open_time'))
            .values('month')
            .annotate(
                replacements=Count('id', filter=Q(replacement_type='COMPLETE')),
                repairs=Count('id', filter=Q(replacement_type='REPAIR')),
                total_replacements=Count('id'),
                cost=Sum('price', output_field=DecimalField()),
            )
            .order_by('month')
        )
        monthly_trend = [
            {
                'month': r['month'].strftime('%Y-%m') if r['month'] else '',
                'replacements': r['replacements'],
                'repairs': r['repairs'],
                'untyped': r['total_replacements'] - r['replacements'] - r['repairs'],
                'total_replacements': r['total_replacements'],
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
        whole_counts = dict(active_observed_queryset(scoped_queryset(ToolChangeDetail.objects.filter(warehouse__in=openings, is_replaced=True)))
                            .values('warehouse_id').annotate(n=Count('id')).values_list('warehouse_id', 'n'))

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
                'summary_status': op.summary_status,
                'summary_replaced_count': op.replaced_tool_count if op.summary_status == 'CONFIRMED' else None,
                'summary_detail_replaced_count': whole_counts.get(op.id, 0),
                'replacement_gap': (op.replaced_tool_count - whole_counts.get(op.id, 0)) if op.summary_status == 'CONFIRMED' and op.replaced_tool_count is not None else None,
            })

        result = {
            'kpi': kpi,
            'monthly_trend': monthly_trend,
            'type_trend': type_trend,
            'recent_openings': recent_openings,
        }
        cache.set(cache_key, result, 300)
        return self.analysis_success(request, result)

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
            return self.analysis_success(request, cached)

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
        return self.analysis_success(request, result)

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
            return self.analysis_success(request, cached)

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
        return self.analysis_success(request, result)

    @action(detail=False, methods=['get'], url_path='brand_cost')
    def brand_cost(self, request):
        """
        各厂家成本对比
        返回：
          items - [{manufacturer, total_cost, count, avg_cost}] 按费用降序
        """
        return self.analysis_success(request, _brand_contract('brand_cost', _build_opening_queryset(request.query_params), request.query_params))

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
        return self.analysis_success(request, _brand_contract('brand_price_trend', _build_opening_queryset(request.query_params), request.query_params))

    @action(detail=False, methods=['get'], url_path='brand_performance_trend')
    def brand_performance_trend(self, request):
        """
        各厂家刀具性能随时间变化趋势
        指标：异常率、正常磨损率、平均使用寿命（环数）
        服役环数：系统已确认旧刀配对的合法安装—拆除环号之差。
        完整配对先于厂家及拆除环段筛选，未配对样本不计入均值。
        返回：
          manufacturers         - [str]
          time_axis             - [{ring_no, open_time}]
          abnormal_rate_series  - [{manufacturer, data: [rate|null, ...]}]
          normal_rate_series    - [{manufacturer, data: [rate|null, ...]}]
          lifespan_series       - [{manufacturer, data: [avg_rings|null, ...]}]
        """
        return self.analysis_success(request, _brand_contract('brand_performance_trend', _build_opening_queryset(request.query_params), request.query_params))

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
            return self.analysis_success(request, cached)

        openings = _build_opening_queryset(request.query_params)
        details = _wear_details(openings, request.query_params)

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
                'state': normalize_wear(r['wear_condition']),
                'count': r['count'],
                'percentage': round(r['count'] / total * 100, 1) if total else 0,
            }
            for r in wear_qs
        ]
        counts = classify_wear_counts(details.values_list('wear_condition', flat=True))
        result = {'items': items, 'total': total, 'checked_count': total,
                  'wear_recorded_count': counts['recorded'], 'unrecorded_count': counts['unrecorded'],
                  'abnormal_count': counts['abnormal'], 'normal_count': counts['normal']}
        cache.set(cache_key, result, 300)
        return self.analysis_success(request, result)

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
            return self.analysis_success(request, cached)

        openings = _build_opening_queryset(request.query_params)
        all_details = _wear_details(openings, request.query_params)

        # 每次开仓：总数 + 异常数（一次聚合）
        wear_rows = defaultdict(list)
        for row in all_details.values('warehouse_id', 'wear_condition', 'is_replaced'):
            wear_rows[row['warehouse_id']].append(row)

        sorted_openings = (
            openings
            .filter(ring_no__regex=_RING_NUMERIC_REGEX).annotate(ring_int=Cast('ring_no', output_field=IntegerField()))
            .order_by('ring_int')
        )
        items = []
        for op in sorted_openings:
            samples = wear_rows[op.id]
            counts = classify_wear_counts(row['wear_condition'] for row in samples)
            total = counts['recorded']
            abnormal = counts['abnormal']
            abnormal_rate = round(abnormal / total, 3) if total else None
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
                'opening_id': op.id,
                'checked_count': len(samples),
                'replacement_count': sum(row['is_replaced'] for row in samples),
                'wear_recorded_count': total,
                'unrecorded_count': counts['unrecorded'],
                'abnormal_rate': abnormal_rate,
                'geological_conditions': op.geological_conditions or '',
                'stratum_types': stratum_types,
            })

        result = {'items': items}
        cache.set(cache_key, result, 300)
        return self.analysis_success(request, result)
