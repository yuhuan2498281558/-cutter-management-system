"""复用分析页的刀具里程计算，只返回分带汇总和所问刀位。"""
import json
from collections import Counter

from django.http import QueryDict
from pydantic import ValidationError

from .tool_contracts import ToolMileageQuery, tool_validation_error
from .tools import _analysis_payload, _build_json
from .tools_inspections import _validate_detail_params
from application.shield.analysis_views import _build_opening_queryset, _life_mileage
from application.shield.models import ProjectInfo


def query_tool_mileage(params_str: str) -> str:
    try:
        params = json.loads(params_str)
        _validate_detail_params(params)
        ToolMileageQuery.model_validate({k: v for k, v in params.items() if k != 'project_id'})
    except ValidationError as exc:
        return tool_validation_error(exc)
    except (ValueError, TypeError) as exc:
        return _build_json({'error': str(exc) if not isinstance(exc, json.JSONDecodeError) else '参数必须是有效的 JSON 对象'})

    q = QueryDict(mutable=True)
    if params.get('project_id'):
        project = ProjectInfo.objects.filter(project_id=params['project_id']).values_list('pk', flat=True).first()
        if project is None:
            return _build_json({'error': '未找到绑定项目'})
        q['project'] = str(project)
    if params.get('shield_machine_id'):
        q['shield_machine'] = str(params['shield_machine_id'])
    if params.get('ring_range'):
        q['start_ring'], q['end_ring'] = map(str, params['ring_range'])
    if params.get('tool_type'):
        q['tool_parent_type'] = params['tool_type']
    q.setlist('manufacturers', params.get('manufacturers', []))
    openings = _build_opening_queryset(q)
    data = _life_mileage(openings, q)
    rings = [int(ring) for ring in openings.values_list('ring_no', flat=True)]
    groups = [{'tool_parent_type': group['tool_parent_type'], 'label': group['label'],
               'bands': [{key: band[key] for key in ('radius_min', 'radius_max', 'cells')}
                         for band in group['bands']]} for group in data['groups']]
    basis = {key: data['revolution_basis'][key] for key in (
        'source_share', 'estimated_share', 'reference_revolutions_per_ring',
        'reading_opening_count', 'tunneling_ring_count')}
    warnings = []
    share = basis['estimated_share']
    if share == 1:
        warnings.append(f"里程全部按参考贯入度约 {basis['reference_revolutions_per_ring']:.0f} 圈/环估算，不是实测")
    elif share is not None and 0 < share < 1:
        warnings.append(f'{share * 100:.0f}% 的圈数按参考值估算')
    warnings.extend(['只统计已拆刀至更换的里程，不代表总体寿命；不排名，不评最佳厂家。',
                     '每格少于 5 段只列各段的值，不给中位数。'])
    scope = {'project_id': params.get('project_id'), 'tool_type': params.get('tool_type'),
             'ring_range': params.get('ring_range'), 'manufacturers': params.get('manufacturers', []),
             'shield_machine_id': params.get('shield_machine_id'),
             'data_ring_range': [min(rings), max(rings)] if rings else None,
             'shield_machine_ids': sorted(set(openings.values_list('shield_model_id', flat=True)))}
    result = {'scope': scope, 'groups': groups, 'revolution_basis': basis, 'excluded': data['excluded'],
              'excluded_count': sum(row['count'] for row in data['excluded']),
              **_analysis_payload(summary={'removed_count': len(data['segments']), 'in_service_count': len(data['in_service'])},
                                  facts=[f"已核实至更换里程 {len(data['segments'])} 段，在役 {len(data['in_service'])} 把。"],
                                  warnings=warnings)}
    if params.get('cutter_position_no'):
        code = params['cutter_position_no']
        position = next((row for row in data['positions'] if row['cutter_position_no'] == code), {})
        segments = sorted((row for row in data['segments'] if row['cutter_position_no'] == code),
                          key=lambda row: (int(row['installation_ring_no']), int(row['ring_no'])))
        excluded = Counter(row['reason'] for row in data['excluded_rows'] if row['cutter_position_no'] == code)
        result['position'] = {**position, 'cutter_position_no': code,
                              'segments': [{key: row[key] for key in (
                                  'installation_ring_no', 'ring_no', 'service_rings', 'km', 'revolution_sources', 'manufacturer')}
                                  for row in segments],
                              'excluded': [{'reason': reason, 'count': count} for reason, count in excluded.most_common()]}
    return _build_json(result)
