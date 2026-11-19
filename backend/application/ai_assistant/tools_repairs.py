"""旧刀返修登记的只读查询。"""
import json
from collections import Counter, defaultdict
from decimal import Decimal

from django.db.models import Count

from application.ai_assistant.tools import _analysis_payload, _build_json
from application.ai_assistant.tools_inspections import _detail_scope, _filtered_details, _validate_detail_params
from application.shield.analysis_metrics import scoped_queryset
from application.shield.cutter_position_scope import cutter_position_sort_key, normalize_cutter_position_no
from application.shield.models import (
    BEARING_FAILURE_REASON_CHOICES, HUB_FAILURE_REASON_CHOICES, OLD_TOOL_DISPOSITION_CHOICES,
    RING_DAMAGE_CHOICES, OldToolPhoto, OldToolRecord,
)


def _failure_reasons(record):
    result = []
    for component, field, choices in (
        ('刀圈', 'ring_damage', RING_DAMAGE_CHOICES),
        ('轴承', 'bearing_failure_reasons', BEARING_FAILURE_REASON_CHOICES),
        ('刀毂', 'hub_failure_reasons', HUB_FAILURE_REASON_CHOICES),
    ):
        labels = dict(choices)
        for reason in sorted(set(getattr(record, field) or [])):
            result.append({'component': component, 'reason': reason, 'label': labels.get(reason, reason)})
    for field, label in (('scraper_chipped', '崩口'), ('scraper_broken', '断裂'), ('scraper_detached', '脱落')):
        if getattr(record, field) is True:
            result.append({'component': '刮刀', 'reason': field, 'label': label})
    return result


def _repair_payload(record, photo_count):
    return {'inspection_status': record.inspection_status, 'disposition': record.disposition,
            'repair_price_yuan': float(record.repair_price) if record.repair_price is not None else None,
            'failure_reasons': _failure_reasons(record), 'photo_count': photo_count,
            'feedback_time': record.vendor_feedback_at.isoformat() if record.vendor_feedback_at else None}


def query_old_tool_repairs(params_str: str) -> str:
    try:
        params = json.loads(params_str)
        _validate_detail_params(params)
        allowed = {'project_id', 'shield_machine_id', 'ring_range', 'tool_type', 'cutter_position_no',
                   'inspection_status', 'disposition', 'list_limit', 'components'}
        if params.keys() - allowed:
            raise ValueError('不支持的参数；可用参数：' + '、'.join(sorted(allowed)))
        if 'components' in params and (not isinstance(params['components'], list)
                or any(c not in ('轴承', '刀圈', '刀毂') for c in params['components'])):
            raise ValueError('components 必须是轴承、刀圈、刀毂的列表')
        for field, choices in (('inspection_status', OldToolRecord.INSPECTION_STATUS_CHOICES),
                               ('disposition', OLD_TOOL_DISPOSITION_CHOICES)):
            if field in params and (not isinstance(params[field], str) or params[field] not in dict(choices)):
                raise ValueError(field + ' 可用值：' + '、'.join(dict(choices)))
    except (ValueError, TypeError) as exc:
        return _build_json({'error': str(exc) if not isinstance(exc, json.JSONDecodeError) else '参数必须是有效的 JSON 对象'})

    params.setdefault('list_limit', 20)
    details = _filtered_details(params).filter(is_replaced=True)
    query = scoped_queryset(OldToolRecord.objects.all()).filter(tool_change_detail__in=details)
    for field in ('inspection_status', 'disposition'):
        if field in params:
            query = query.filter(**{field: params[field]})
    records = list(query.select_related('tool_change_detail__warehouse'))
    # 先按部件筛全部记录再截取明细。
    if params.get('components'):
        records = [r for r in records if any(f['component'] in params['components'] for f in _failure_reasons(r))]
    rows = {row.pk: row for row in details.filter(pk__in=[r.tool_change_detail_id for r in records])}
    records.sort(key=lambda r: (-rows[r.tool_change_detail_id]._tool_ring,
                               cutter_position_sort_key(r.tool_change_detail.cutter_position_no), r.pk))
    # 照片独立计数，避免一把刀的多张照片放大登记金额。
    photos = dict(scoped_queryset(OldToolPhoto.objects.all()).filter(old_tool_record_id__in=[r.pk for r in records])
                  .values('old_tool_record_id').annotate(n=Count('pk')).values_list('old_tool_record_id', 'n'))
    statuses = Counter(r.inspection_status for r in records)
    disposition = defaultdict(Counter)
    reasons = Counter()
    positions = defaultdict(list)
    for record in records:
        positions[normalize_cutter_position_no(record.tool_change_detail.cutter_position_no)].append(record)
        disposition[record.inspection_status][record.disposition or '未登记'] += 1
        for reason in _failure_reasons(record):
            reasons[(reason['component'], reason['reason'], reason['label'])] += 1
    confirmed = [r for r in records if r.inspection_status in {'CONFIRMED', 'CLOSED'}]
    pending = [r for r in records if r.inspection_status == 'PENDING_VENDOR_FEEDBACK']
    def amount(items):
        return float(sum((r.repair_price for r in items if r.repair_price is not None), Decimal('0.00')))

    scrapped = sum(r.disposition == 'SCRAP' for r in confirmed)
    suggestion = sum(r.disposition == 'SCRAP' for r in pending)
    return _build_json({
        'scope': _detail_scope(params, list(rows.values())),
        'status_counts': {key: statuses[key] for key, _ in OldToolRecord.INSPECTION_STATUS_CHOICES},
        'disposition_by_status': {key: dict(disposition[key]) for key, _ in OldToolRecord.INSPECTION_STATUS_CHOICES},
        'scrapped_count': scrapped, 'scrap_suggestion_count': suggestion,
        'registered_repair_amount': {
            'confirmed_yuan': amount(confirmed), 'pending_yuan': amount(pending),
            'priced_count': sum(r.repair_price is not None for r in records),
            'zero_price_count': sum(r.repair_price == 0 for r in records),
            'missing_price_count': sum(r.repair_price is None for r in records),
        },
        'failure_reasons': [{'component': c, 'reason': r, 'label': label, 'record_count': count}
                            for (c, r, label), count in sorted(reasons.items())],
        'position_counts': [{'cutter_position_no': code, 'count': len(items),
                             'records': [{'old_tool_number': r.old_tool_number,
                                          'ring_no': rows[r.tool_change_detail_id]._tool_ring} for r in items]}
                            for code, items in sorted(positions.items(), key=lambda pair: (-len(pair[1]), cutter_position_sort_key(pair[0])))],
        'photo_count': sum(photos.values()),
        'records': [{'ring_no': rows[r.tool_change_detail_id]._tool_ring,
                     'cutter_position_no': normalize_cutter_position_no(r.tool_change_detail.cutter_position_no),
                     'old_tool_number': r.old_tool_number, **_repair_payload(r, photos.get(r.pk, 0))}
                    for r in records[:params['list_limit']]],
        **_analysis_payload(summary={'record_count': len(records), 'scrapped_count': scrapped,
                                     'scrap_suggestion_count': suggestion},
                            facts=[f'现场观测记录对应旧刀 {len(records)} 条；已报废 {scrapped} 条，待厂家确认的报废建议 {suggestion} 条。',
                                   f'已确认和已归档的登记维修金额合计 {amount(confirmed):.2f} 元。'],
                            conclusion_hint='待反馈、已确认和已归档分别列出；登记金额不代表实际支出。'),
        'note': '金额是登记的维修金额，不是实际支出。"已报废"只算厂家已确认或已归档、且处置为报废的；还在等厂家反馈的报废标记单独列为报废建议。一把刀可能有多个失效原因，原因计数会多于刀数。',
    })
