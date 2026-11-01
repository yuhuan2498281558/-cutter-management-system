"""从刀具身份追溯安装、检查、拆下和返修。"""
import json
from collections import defaultdict

from django.db.models import Count

from application.ai_assistant.tools import _analysis_payload, _build_json, _visible_records
from application.ai_assistant.tools_inspections import _filtered_details, _validate_detail_params
from application.ai_assistant.tools_repairs import _repair_payload
from application.shield.analysis_metrics import confirmed_service_segments, scoped_queryset
from application.shield.cutter_position_scope import normalize_cutter_position_no
from application.shield.models import OldToolPhoto, ToolInstance
from application.shield.tool_identity import resolve_removed_tool_identity


def _event_key(row):
    return row._tool_ring, row.warehouse.open_time, row.pk


def _position_key(row):
    return row.warehouse.project_id, row.warehouse.shield_model_id, normalize_cutter_position_no(row.cutter_position_no)


def _instance_payload(instance):
    if instance is None:
        return None
    labels = {'PENDING_VERIFY': '待核实', 'INSTALLED': '在役',
              'REMOVED_PENDING_INSPECTION': '已拆下待检查', 'INSPECTED': '已检查',
              'REPAIRED_CLOSED': '返修已归档', 'SCRAPPED': '已报废'}
    return {'tool_uid': instance.tool_uid, 'display_tool_no': instance.display_tool_no,
            'tool_model': instance.tool_info.tool_type_name if instance.tool_info else instance.tool_type_name,
            'tool_type': instance.tool_parent_type, 'status': instance.status,
            'status_label': labels.get(instance.status, instance.get_status_display())}


def _removal_only(row, photos):
    old = row.old_tool_record
    return {'cutter_position_no': normalize_cutter_position_no(row.cutter_position_no),
            'install_ring': None, 'install_time': None, 'removal_ring': row._tool_ring,
            'removal_basis': 'confirmed' if old.confirmed_tool_instance_id else
                             ('suggested' if old.suggested_tool_instance_id else 'inferred'),
            'service_rings': None, 'inspections': [], 'repair': _repair_payload(old, photos.get(old.pk, 0))}


def _service_segment(start, instance, positions, removals, paired, photos, missing):
    # 对齐 build_position_history：按项目、机器、规范刀位构段，继承编号的检查不是安装。
    position_rows = positions[_position_key(start)]
    following = [r for r in position_rows if _event_key(r) > _event_key(start)
                 and (r.is_replaced or getattr(r, 'new_tool_record', None))]
    end = following[0] if following else None
    if instance:
        identified = [r for r in removals[instance.pk] if _event_key(r) > _event_key(start)
                      and r.warehouse.project_id == start.warehouse.project_id
                      and r.warehouse.shield_model_id == start.warehouse.shield_model_id]
        if identified and (end is None or _event_key(identified[0]) <= _event_key(end)):
            end = identified[0]
    old = getattr(end, 'old_tool_record', None) if end else None
    basis = 'in_service' if end is None else 'inferred'
    if old and instance:
        if old.confirmed_tool_instance_id == instance.pk:
            basis = 'confirmed'
        elif not old.confirmed_tool_instance_id and old.suggested_tool_instance_id == instance.pk:
            basis = 'suggested'
        elif old.confirmed_tool_instance_id:
            missing.append('同刀位拆下记录确认的是另一把刀，身份需要核对')
    valid = paired.get(start.pk)
    service = valid['service_rings'] if basis == 'confirmed' and valid and valid['detail_id'] == end.pk else None
    if basis == 'in_service':
        missing.append('尚无拆下记录，服役环数未确定')
    elif basis == 'suggested':
        missing.append('拆下身份只有建议，服役环数未确定')
    elif basis == 'inferred':
        missing.append('拆下身份未确认，仅按同刀位下一次更换推断')
    elif service is None:
        missing.append('厂家反馈或安装拆下配对尚未确认，服役环数未确定')
    # 磨损属于拆下的刀：不把安装行上前一把刀的磨损放进这段检查。
    inspections = [r for r in position_rows if _event_key(r) > _event_key(start)
                   and (end is None or _event_key(r) <= _event_key(end))]
    repair = None
    if old and (not instance or not old.confirmed_tool_instance_id or old.confirmed_tool_instance_id == instance.pk):
        repair = _repair_payload(old, photos.get(old.pk, 0))
        if old.inspection_status == 'PENDING_VENDOR_FEEDBACK':
            missing.append('拆下后厂家还没反馈')
    elif end:
        missing.append('没有可归属这把刀的返修记录')
    return {'cutter_position_no': normalize_cutter_position_no(start.cutter_position_no),
            'install_ring': start._tool_ring,
            'install_time': start.warehouse.open_time.isoformat() if start.warehouse.open_time else None,
            'removal_ring': end._tool_ring if end else None, 'removal_basis': basis,
            'service_rings': service,
            'inspections': [{'ring_no': r._tool_ring, 'check_result': r.check_result, 'wear_condition': r.wear_condition}
                            for r in inspections], 'repair': repair}


def trace_tool_lifecycle(params_str: str) -> str:
    try:
        params = json.loads(params_str)
        _validate_detail_params(params)
        if params.keys() - {'project_id', 'tool_ids'}:
            raise ValueError('可用参数：project_id、tool_ids')
        ids = params.get('tool_ids')
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 20
                or any(not isinstance(value, str) or not value.strip() for value in ids)):
            raise ValueError('tool_ids 必须包含 1–20 个非空字符串，可用刀具 UID、显示编号或旧刀编号')
    except (ValueError, TypeError) as exc:
        return _build_json({'error': str(exc) if not isinstance(exc, json.JSONDecodeError) else '参数必须是有效的 JSON 对象'})

    rows = list(_visible_records(
        _filtered_details(params).select_related('warehouse'),
        new_tool_record=('tool_instance__tool_info',),
        old_tool_record=('confirmed_tool_instance__tool_info', 'suggested_tool_instance__tool_info')))
    rows.sort(key=_event_key)
    positions, installs, removals = defaultdict(list), defaultdict(list), defaultdict(list)
    old_rows = []
    for row in rows:
        positions[_position_key(row)].append(row)
        new = getattr(row, 'new_tool_record', None)
        if new:
            installs[new.tool_instance_id].append(row)
        old = getattr(row, 'old_tool_record', None)
        if old and row.is_replaced:
            old_rows.append(row)
            identity = old.confirmed_tool_instance_id or old.suggested_tool_instance_id
            if identity:
                removals[identity].append(row)
    photos = dict(scoped_queryset(OldToolPhoto.objects.all()).filter(old_tool_record_id__in=[r.old_tool_record.pk for r in old_rows])
                  .values('old_tool_record_id').annotate(n=Count('pk')).values_list('old_tool_record_id', 'n'))
    paired = {s['installation_detail_id']: s for s in confirmed_service_segments(rows) if s['paired']}
    instances = scoped_queryset(ToolInstance.objects.all()).select_related('tool_info')
    results = []
    for original in ids:
        value = original.strip()
        instance = instances.filter(tool_uid=value).first()
        resolved = 'tool_uid' if instance else 'not_found'
        missing, matched_old, matched_details = [], [], []
        ambiguous = False
        if instance is None:
            matches = list(instances.filter(display_tool_no=value)[:2])
            if matches:
                resolved = 'display_tool_no'
                if len(matches) == 1:
                    instance = matches[0]
                else:
                    ambiguous = True
                    missing.append('显示编号对应多个实例，请用刀具 UID 查询')
        if instance is None and not ambiguous:
            matched_old = [r for r in old_rows if r.old_tool_record.old_tool_number == value]
            if matched_old:
                resolved = 'old_tool_number'
                identities = {r.old_tool_record.confirmed_tool_instance_id or r.old_tool_record.suggested_tool_instance_id
                              for r in matched_old}
                if len(identities) == 1 and None not in identities:
                    # 对齐 tool_identity：确认实例优先于建议；不把本行新刀编号当作拆下身份。
                    instance, _ = resolve_removed_tool_identity(matched_old[0])
                elif len(identities) > 1:
                    missing.append('旧刀编号的实例关联不唯一，仅列出匹配的拆下和返修记录')
            else:
                matched_details = [r for r in rows if r.tool_number == value]
                if matched_details:
                    resolved = 'tool_number'
                    new_instances = {r.new_tool_record.tool_instance_id: r.new_tool_record.tool_instance
                                     for r in matched_details if getattr(r, 'new_tool_record', None)}
                    if len(new_instances) == 1:
                        instance = next(iter(new_instances.values()))
                    elif len(new_instances) > 1:
                        ambiguous = True
                        missing.append('明细编号对应多个实例，请用刀具 UID 查询')
        starts = installs[instance.pk] if instance else [r for r in matched_details if r.is_replaced]
        segments = []
        if not ambiguous:
            segments = [_service_segment(start, instance, positions, removals, paired, photos, missing)
                        for start in starts[-20:]]
        if instance and not starts:
            missing.append('存在这把刀的实例，但没有安装记录')
            if params.get('project_id'):
                missing.append('没有能锚定到指定项目的安装段，不返回其他项目的数据')
        if not starts and not ambiguous:
            candidates = matched_old or (removals[instance.pk] if instance else [])
            segments = [_removal_only(row, photos) for row in candidates[-20:]]
            if candidates:
                missing.append('没有安装记录，无法确定装在哪个刀位')
                if any(row.old_tool_record.inspection_status == 'PENDING_VENDOR_FEEDBACK' for row in candidates):
                    missing.append('拆下后厂家还没反馈')
            elif resolved == 'not_found':
                missing.append('没有找到这把刀的实例或记录')
            elif not instance and not ambiguous:
                missing.append('只有现场观测记录，没有安装记录')
        event_count = len(starts) or len(matched_old) or (len(removals[instance.pk]) if instance else 0)
        results.append({'query': original, 'resolved_by': resolved, 'instance': _instance_payload(instance),
                        'service_segments': segments, 'missing_steps': list(dict.fromkeys(missing)),
                        'truncated': event_count > 20})
    return _build_json({
        'scope': {**params, 'query_count': len(ids), 'record_count': len(rows), 'segment_limit': 20},
        'results': results,
        **_analysis_payload(summary={'query_count': len(ids), 'found_count': sum(r['resolved_by'] != 'not_found' for r in results)},
                            facts=[f'查询 {len(ids)} 个编号，每个编号最多返回最近 20 段。'],
                            warnings=['建议身份、位置推断和在役段不计算服役环数。'],
                            conclusion_hint='按每把刀的身份和缺失环节解释，不把缺安装记录说成刀不存在。'),
        'note': '服役环数只用于厂家已确认或已归档且安装、拆下配对完整的记录。安装时间取开仓时间；返修金额是登记金额，不是实际支出。',
    })
