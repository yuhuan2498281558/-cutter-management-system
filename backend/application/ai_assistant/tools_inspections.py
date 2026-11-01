"""移动检查和任务状态的只读查询。"""
import json
from collections import Counter, defaultdict

from django.db.models import IntegerField
from django.db.models.functions import Cast

from application.ai_assistant.tools import _active_detail_query, _analysis_payload, _build_json, is_abnormal_wear
from application.shield.analysis_metrics import scoped_queryset
from application.shield.cutter_position_scope import (
    ACTIVE_CUTTER_POSITION_CODES, cutter_position_sort_key, normalize_cutter_position_no,
)
from application.shield.models import MobileToolChangeTask, ToolChangeDetail, WarehouseOpeningBasicInfo


def _validate_detail_params(params):
    if not isinstance(params, dict):
        raise ValueError('参数必须是 JSON 对象')
    if 'project_id' in params and (not isinstance(params['project_id'], str) or not params['project_id'].strip()):
        raise ValueError('project_id 必须是非空字符串')
    if 'shield_machine_id' in params and (type(params['shield_machine_id']) is not int or params['shield_machine_id'] < 1):
        raise ValueError('shield_machine_id 必须是盾构机主键正整数')
    if 'ring_range' in params:
        rings = params['ring_range']
        if (not isinstance(rings, list) or len(rings) != 2
                or any(type(r) is not int or not 1 <= r <= 999999999 for r in rings)
                or rings[0] > rings[1]):
            raise ValueError('ring_range 必须是两个递增的正整数，范围为 1–999999999')
    if 'tool_type' in params:
        if not isinstance(params['tool_type'], str) or params['tool_type'].strip().upper() not in {'DISC', 'SCRAPER'}:
            raise ValueError('tool_type 可用值：DISC、SCRAPER')
        params['tool_type'] = params['tool_type'].strip().upper()
    if 'cutter_position_no' in params:
        if not isinstance(params['cutter_position_no'], str):
            raise ValueError('cutter_position_no 必须是有效刀位编号字符串')
        position = normalize_cutter_position_no(params['cutter_position_no'])
        if position not in ACTIVE_CUTTER_POSITION_CODES:
            raise ValueError('cutter_position_no 可用值：1–79、80A、80B、Y1、Y3、Y5、S1L–S19L、S1R–S19R')
        if params.get('tool_type') and params['tool_type'] != ('SCRAPER' if position.startswith('S') else 'DISC'):
            raise ValueError('刀型和刀位不匹配：S 开头刀位用 SCRAPER，其余有效刀位用 DISC')
        params['cutter_position_no'] = position
    if 'list_limit' in params and (type(params['list_limit']) is not int or not 1 <= params['list_limit'] <= 200):
        raise ValueError('list_limit 必须是 1–200 的整数')


def _filtered_details(params, *, checked_only=True):
    query = _active_detail_query(params, checked_only=checked_only)
    if params.get('tool_type'):
        query = query.filter(_ai_type=params['tool_type'])
    if params.get('cutter_position_no'):
        query = query.filter(_ai_position=params['cutter_position_no'])
    query = query.annotate(_tool_ring=Cast('warehouse__ring_no', IntegerField()))
    if 'ring_range' in params:
        query = query.filter(_tool_ring__range=params['ring_range'])
    return query


def _detail_scope(params, rows):
    rings = [row._tool_ring for row in rows if row._tool_ring is not None]
    return {**params, 'record_count': len(rows),
            'data_ring_range': [min(rings), max(rings)] if rings else None}


def _inspection_record(row):
    return {'ring_no': row._tool_ring, 'cutter_position_no': normalize_cutter_position_no(row.cutter_position_no),
            'tool_type': row.tool_parent_type.strip().upper(), 'check_result': row.check_result,
            'wear_condition': row.wear_condition, 'mobile_status': row.mobile_status}


def _record_group(rows, limit):
    return {'record_count': len(rows),
            'position_count': len({normalize_cutter_position_no(row.cutter_position_no) for row in rows}),
            'records': [_inspection_record(row) for row in rows[:limit]]}


def query_tool_inspections(params_str: str) -> str:
    try:
        params = json.loads(params_str)
        _validate_detail_params(params)
        allowed = {'project_id', 'shield_machine_id', 'ring_range', 'recent_openings', 'tool_type',
                   'cutter_position_no', 'check_result', 'list_limit'}
        if params.keys() - allowed:
            raise ValueError('不支持的参数；可用参数：' + '、'.join(sorted(allowed)))
        if 'recent_openings' in params:
            if type(params['recent_openings']) is not int or not 1 <= params['recent_openings'] <= 100:
                raise ValueError('recent_openings 必须是 1–100 的整数')
            if 'ring_range' in params:
                raise ValueError('recent_openings 和 ring_range 不能同时指定')
        choices = dict(ToolChangeDetail.CHECK_RESULT_CHOICES)
        if 'check_result' in params and (not isinstance(params['check_result'], str) or params['check_result'] not in choices):
            raise ValueError('check_result 可用值：' + '、'.join(choices))
    except (ValueError, TypeError) as exc:
        return _build_json({'error': str(exc) if not isinstance(exc, json.JSONDecodeError) else '参数必须是有效的 JSON 对象'})

    params.setdefault('list_limit', 20)
    openings = scoped_queryset(WarehouseOpeningBasicInfo.objects.all())
    if params.get('project_id'):
        openings = openings.filter(project__project_id=params['project_id'])
    if params.get('shield_machine_id'):
        openings = openings.filter(shield_model_id=params['shield_machine_id'])
    openings = openings.annotate(_tool_ring=Cast('ring_no', IntegerField())).order_by('-_tool_ring', '-open_time', '-pk')
    if 'ring_range' in params:
        openings = openings.filter(_tool_ring__range=params['ring_range'])
    if 'recent_openings' in params:
        openings = openings[:params['recent_openings']]
    openings = list(openings)
    query = _filtered_details(params, checked_only=False).filter(warehouse_id__in=[o.pk for o in openings])
    all_rows = list(query)
    all_rows.sort(key=lambda row: (-row._tool_ring, cutter_position_sort_key(row.cutter_position_no), row.pk))
    rows = [r for r in all_rows if r.check_result == params['check_result']] if 'check_result' in params else all_rows
    by_opening = defaultdict(list)
    for row in all_rows:
        by_opening[row.warehouse_id].append(row)
    tasks = list(scoped_queryset(MobileToolChangeTask.objects.all()).filter(warehouse_id__in=[o.pk for o in openings]).values('warehouse_id', 'status'))
    statuses = defaultdict(list)
    for task in tasks:
        statuses[task['warehouse_id']].append(task['status'])
    completion = []
    for opening in openings:
        details = by_opening[opening.pk]
        checked = sum(row.is_checked or row.is_replaced for row in details)
        completion.append({'ring_no': opening._tool_ring, 'summary_status': opening.summary_status,
                           'task_status': sorted(statuses[opening.pk]), 'position_count': len(details),
                           'checked_count': checked, 'unchecked_count': len(details) - checked,
                           'replaced_count': sum(row.is_replaced for row in details),
                           'attention_not_replaced_count': sum(
                               not row.is_replaced and row.check_result in {'ATTENTION', 'ABNORMAL_NOT_REPLACED'}
                               for row in details)})
    attention = [r for r in rows if not r.is_replaced and r.check_result in {'ATTENTION', 'ABNORMAL_NOT_REPLACED'}]
    unchecked = [r for r in all_rows if not r.is_checked and not r.is_replaced]
    counts = Counter(r.check_result for r in all_rows)
    # 模型 choices 的标签目前为英文；枚举仍以模型为准，展示名与移动端一致。
    labels = {'PENDING': '待检查', 'NOT_REPLACED': '未更换', 'NORMAL': '正常',
              'ATTENTION': '需关注', 'ABNORMAL_NOT_REPLACED': '异常未换'}
    abnormal = sum(r.is_replaced and r.check_result == 'NORMAL' and is_abnormal_wear(r.wear_condition) for r in all_rows)
    scope = {**_detail_scope(params, rows), 'opening_count': len(openings)}
    if 'check_result' in params:
        scope['note'] = '检查结果筛选只影响列出的记录；各次开仓完成度、未检查数和检查结果分布按全部明细计算。'
    return _build_json({
        'scope': scope,
        'check_result_counts': [{'check_result': key, 'label': labels.get(key, label), 'record_count': counts[key]}
                                for key, label in choices.items()],
        'attention_not_replaced': _record_group(attention, params['list_limit']),
        'unchecked': _record_group(unchecked, params['list_limit']),
        'opening_completion': completion,
        'task_status_counts': dict(Counter(task['status'] for task in tasks)),
        'mobile_status_counts': dict(Counter(r.mobile_status for r in all_rows)),
        'replaced_rows_with_abnormal_wear': abnormal,
        **_analysis_payload(summary={'record_count': len(rows), 'attention_count': len(attention), 'unchecked_count': len(unchecked)},
                            facts=[f'有效刀位明细共 {len(rows)} 条，需关注未更换 {len(attention)} 条，未检查 {len(unchecked)} 条。'],
                            warnings=['任务状态、明细移动状态和开仓汇总状态分别列出，不能据此判断是否完工。'],
                            conclusion_hint='按记录数回答；同一刀位可能在多次开仓中出现。'),
        'note': '更换行的检查结果"正常"是移动端保存时的默认值，不代表磨损正常；看磨损要看磨损状态。记录数按明细行计，同一个刀位在不同开仓会各算一次。',
    })
