"""可查编码和数据覆盖范围的只读目录。"""
from collections import Counter, defaultdict

from django.db.models import Count, IntegerField, Max, Min
from django.db.models.functions import Cast

from application.ai_assistant.tools import (
    STRATUM_TYPE_NAMES, _active_detail_query, _analysis_payload, _build_json, _tunneling_revolution_counts,
)
from application.ai_assistant.tools_stratum_area import (
    _area_summary, _legacy_codes, _read_params, _stratum_query, _stratum_rows,
)
from application.shield.analysis_metrics import RING_NUMERIC_REGEX
from application.shield.longitudinal_ratios import AREA_LABELS
from application.shield.models import (
    TOOL_TYPES, MobileToolChangeTask, OldToolRecord, ShieldTunnelingData,
    ToolCost, ToolInfo, WarehouseOpeningBasicInfo,
)
from application.shield.stratum_ratios import STRATUM_LABELS, stratum_label


_NOT_AVAILABLE = [
    '剩余寿命预测', '寿命预警', '备刀数量规划', '库存台账',
    '实际采购和支付金额', '掘进原始点数据（库里只有分段均值）',
]


def _status_counts(query, field):
    return {row[field]: row['count'] for row in query.order_by().values(field).annotate(count=Count('pk')).order_by(field)}


def _coverage(query, time_field, ring_field='ring_no'):
    rings = query.filter(**{f'{ring_field}__regex': RING_NUMERIC_REGEX}).annotate(_ring=Cast(ring_field, IntegerField())).aggregate(
        ring_min=Min('_ring'), ring_max=Max('_ring'),
    )
    times = query.aggregate(time_min=Min(time_field), time_max=Max(time_field))
    return {**rings, **{key: value.isoformat() if value else None for key, value in times.items()}}


def query_data_catalog(params_str: str) -> str:
    try:
        params = _read_params(params_str)
        project_id = params.get('project_id')
        openings = WarehouseOpeningBasicInfo.objects.all()
        tunneling = ShieldTunnelingData.objects.all()
        tasks = MobileToolChangeTask.objects.all()
        if project_id is not None:
            openings = openings.filter(project__project_id=project_id)
            tunneling = tunneling.filter(project__project_id=project_id)
            tasks = tasks.filter(warehouse__project__project_id=project_id)
        details = _active_detail_query(params)
        repairs = OldToolRecord.objects.filter(tool_change_detail__in=details)
        # 型号和报价是共用资料库，没有项目外键；项目筛选只作用于现场业务记录。
        models = list(ToolInfo.objects.order_by('tool_parent_type', 'tool_type_name', 'tool_type_code', 'id').values(
            'tool_parent_type', 'tool_type_name', 'tool_type_code',
        ))
        model_counts = Counter(row['tool_parent_type'] for row in models)
        strata = _stratum_rows(_stratum_query(project_id))
        legacy_rings = defaultdict(set)
        for row in strata:
            for code in _legacy_codes(row):
                legacy_rings[code].add((row['project__project_id'], int(row['ring_no'])))
        area, invalid_area = _area_summary(strata, 'longitudinal_area')
        cross, invalid_cross = _area_summary(strata, 'cross_section')
        area_counts = {row['code']: row['positive_ring_count'] for row in area['classes']}
        cross_counts = {row['code']: row['positive_ring_count'] for row in cross['classes']}
        opening_coverage = _coverage(openings, 'open_time')
        quote_counts = _status_counts(ToolCost.objects.all(), 'cost_type')
        stratum_rings = [int(row['ring_no']) for row in strata]
        coverage = {
            'openings': {
                'count': openings.count(), 'ring_min': opening_coverage['ring_min'], 'ring_max': opening_coverage['ring_max'],
                'open_time_min': opening_coverage['time_min'], 'open_time_max': opening_coverage['time_max'],
                'summary_status_counts': _status_counts(openings, 'summary_status'),
            },
            'tool_change_observations': {'observation_count': details.count(), 'replacement_count': details.filter(is_replaced=True).count(),
                                         **_coverage(details, 'warehouse__open_time', 'warehouse__ring_no')},
            'tunneling': {'record_count': tunneling.count(), **_coverage(tunneling, 'record_time')},
            'stratum': {
                'ring_count': area['ring_count_requested'],
                'ring_min': min(stratum_rings, default=None), 'ring_max': max(stratum_rings, default=None),
                'longitudinal_area_ring_count': area['ring_count_with_data'], 'cross_section_ring_count': cross['ring_count_with_data'],
            },
            'cost_quotes': {'new_tool_count': quote_counts.get('NEW_TOOL', 0), 'repair_count': quote_counts.get('REPAIR', 0)},
            'old_tool_repairs': {'status_counts': _status_counts(repairs, 'inspection_status'),
                                **_coverage(repairs, 'tool_change_detail__warehouse__open_time', 'tool_change_detail__warehouse__ring_no')},
            'opening_readings': {'count': openings.filter(right_revolution_reading__isnull=False, left_revolution_reading__isnull=False).count(),
                                 'total': openings.count()},
            'tunneling_revolutions': _tunneling_revolution_counts(tunneling),
            'mobile_tasks': {'status_counts': _status_counts(tasks, 'status')},
        }
        warnings = []
        if invalid_area or invalid_cross:
            warnings.append(f'纵断面有{invalid_area}环、横断面有{invalid_cross}环占比未通过校验或环号重复，未计入面积覆盖。')
        note = '现场业务数据按项目筛选，刀型、型号和报价来自共用资料库。现场观测记录只计有效刀位上已检查或已更换的记录；历史地层标签与两套面积分别列出。'
        return _build_json({
            'scope': {'project_id': project_id, 'tool_models_scope': '共用资料库', 'cost_quotes_scope': '共用资料库'},
            'tool_types': [{'code': code, 'label': label, 'model_count': model_counts[code]} for code, label in TOOL_TYPES],
            'tool_models': [{'name': row['tool_type_name'], 'code': row['tool_type_code'], 'tool_type': row['tool_parent_type']} for row in models],
            'stratum_codes': {
                'legacy_labels': [{'code': code, 'label': stratum_label(code), 'ring_count': len(legacy_rings[code])} for code in STRATUM_TYPE_NAMES],
                'longitudinal_area': [{'code': code, 'label': label, 'positive_ring_count': area_counts.get(code, 0)} for code, label in AREA_LABELS.items()],
                'cross_section': [{'code': code, 'label': label, 'positive_ring_count': cross_counts.get(code, 0)} for code, label in STRATUM_LABELS.items()],
            },
            'data_coverage': coverage, 'not_available': _NOT_AVAILABLE, 'note': note,
            **_analysis_payload(
                summary={'opening_count': coverage['openings']['count'],
                         'observation_count': coverage['tool_change_observations']['observation_count'],
                         'stratum_ring_count': coverage['stratum']['ring_count']},
                facts=[f"可查{coverage['openings']['count']}次开仓、{coverage['tool_change_observations']['observation_count']}条现场观测记录、{coverage['stratum']['ring_count']}环地层数据。"],
                warnings=warnings, conclusion_hint=note,
            ),
        })
    except (ValueError, TypeError) as exc:
        return _build_json({'error': f'参数或数据格式错误：{exc}'})
