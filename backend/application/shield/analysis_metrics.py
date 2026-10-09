"""Read-only analysis calculations; never infer missing prices or tool identity."""
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from contextvars import ContextVar
import re
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .cutter_position_scope import is_active_cutter_position
from .trajectory import get_tool_trajectory
from .wear import normalize_wear

# int32-safe positive text rings, compatible with existing Cast(IntegerField).
RING_NUMERIC_REGEX = r'^[0-9]{1,9}$'
ANALYSIS_REQUEST = ContextVar('analysis_request', default=None)


def blade_track_range(params):
    """Parse inclusive, non-negative centre-radius bounds in millimetres."""
    bounds = []
    for key in ('blade_track_min', 'blade_track_max'):
        raw = params.get(key)
        text = '' if raw is None else str(raw).strip()
        if not text:
            bounds.append(None)
            continue
        try:
            value = Decimal(text)
        except InvalidOperation:
            value = None
        if (value is None or not value.is_finite() or value < 0
                or not re.fullmatch(r'(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)', text)):
            raise ValidationError({key: '刀刃轨迹须为有限的非负十进制数，单位 mm'})
        bounds.append(value)
    if bounds[0] is not None and bounds[1] is not None and bounds[0] > bounds[1]:
        raise ValidationError({'blade_track_range': '刀刃轨迹下限不能大于上限'})
    return tuple(bounds)


def matches_blade_track(detail, bounds):
    lower, upper = bounds
    if lower is None and upper is None:
        return True
    radius = get_tool_trajectory(detail.cutter_position_no, detail.tool_parent_type)['radius_mm']
    if radius is None:
        return False
    radius = Decimal(str(radius))
    return (lower is None or radius >= lower) and (upper is None or radius <= upper)


def scoped_queryset(queryset):
    """Use the same existing department/data-range filter as business CRUD."""
    request = ANALYSIS_REQUEST.get()
    if request is None:
        return queryset
    from dvadmin.utils.filters import DataLevelPermissionMargeFilter
    return DataLevelPermissionMargeFilter().filter_queryset(request, queryset, None)


def _event_key(detail):
    try:
        return (int(detail.warehouse.ring_no), detail.warehouse.open_time, detail.id)
    except (ValueError, TypeError):
        return None


def confirmed_service_segments(details):
    """Resolve complete installation segments before any vendor/ring filtering.

    Removal candidates are already in the requested opening scope. Installation
    history and competing confirmed removals are intentionally queried outside
    that ring window. Ambiguous/same-ring/cross-machine pairs never make a mean.
    """
    from .models import NewToolRecord, OldToolRecord, ToolChangeDetail, WarehouseOpeningBasicInfo
    details = list(details)
    event_fields = (
        'tool_change_detail__id', 'tool_change_detail__warehouse_id',
        'tool_change_detail__is_replaced', 'tool_change_detail__cutter_position_no',
        'tool_change_detail__tool_parent_type', 'tool_change_detail__manufacturer',
        'tool_change_detail__warehouse__id', 'tool_change_detail__warehouse__ring_no',
        'tool_change_detail__warehouse__open_time', 'tool_change_detail__warehouse__project_id',
        'tool_change_detail__warehouse__shield_model_id', 'tool_change_detail__warehouse__summary_status',
    )
    old_records = {record.tool_change_detail_id: record for record in scoped_queryset(OldToolRecord.objects.filter(
        tool_change_detail_id__in=[detail.id for detail in details],
    )).only('id', 'tool_change_detail_id', 'confirmed_tool_instance_id', 'suggested_tool_instance_id', 'inspection_status', 'old_tool_number')}
    instance_ids = {record.confirmed_tool_instance_id for record in old_records.values() if record.confirmed_tool_instance_id}
    installs = defaultdict(list)
    visible_details = scoped_queryset(ToolChangeDetail.objects.all())
    visible_openings = scoped_queryset(WarehouseOpeningBasicInfo.objects.all())
    for record in scoped_queryset(NewToolRecord.objects.filter(tool_instance_id__in=instance_ids,
            tool_change_detail_id__in=visible_details.values('id'),
            tool_change_detail__warehouse_id__in=visible_openings.values('id'))).select_related('tool_change_detail__warehouse').only(
                'id', 'tool_instance_id', *event_fields):
        installs[record.tool_instance_id].append(record.tool_change_detail)
    removals = list(scoped_queryset(OldToolRecord.objects.filter(
        confirmed_tool_instance_id__in=instance_ids,
        tool_change_detail_id__in=visible_details.values('id'),
        tool_change_detail__warehouse_id__in=visible_openings.values('id'),
    )).select_related('tool_change_detail__warehouse').only(
        'id', 'confirmed_tool_instance_id', 'inspection_status', *event_fields))
    candidates = {}
    conflicts = {}
    competing = defaultdict(list)
    for record in removals:
        removed = record.tool_change_detail
        if (record.inspection_status not in {'CONFIRMED', 'CLOSED'}
            or removed.warehouse.summary_status != 'CONFIRMED'
            or not removed.is_replaced
            or not is_active_cutter_position(removed.cutter_position_no, removed.tool_parent_type)):
            continue
        remove_key = _event_key(removed)
        legal = []
        for installed in installs[record.confirmed_tool_instance_id]:
            key = _event_key(installed)
            if (key and remove_key and key[:2] < remove_key[:2]
                and installed.warehouse.project_id == removed.warehouse.project_id
                and installed.warehouse.shield_model_id == removed.warehouse.shield_model_id
                and installed.is_replaced
                and is_active_cutter_position(installed.cutter_position_no, installed.tool_parent_type)):
                legal.append(installed)
        if not legal:
            continue
        latest_key = max(_event_key(item)[:2] for item in legal)
        nearest = [item for item in legal if _event_key(item)[:2] == latest_key]
        if len(nearest) != 1:
            continue
        installed = nearest[0]
        install_key = _event_key(installed)
        older = []
        conflict = ''
        for other in installs[record.confirmed_tool_instance_id]:
            other_key = _event_key(other)
            if other.id == installed.id or not other_key:
                continue
            if other.warehouse.open_time <= removed.warehouse.open_time:
                if (other.warehouse.project_id != removed.warehouse.project_id
                    or other.warehouse.shield_model_id != removed.warehouse.shield_model_id):
                    if other.warehouse.open_time >= installed.warehouse.open_time:
                        conflict = '前序安装至拆除之间存在跨项目或盾构机安装'
                elif other_key[:2] < install_key[:2]:
                    older.append(other)
        # A repeated installation is a new service segment only if the previous
        # segment was explicitly removed. Never silently reset an installed tool.
        if older:
            previous = max(older, key=_event_key)
            prior_removals = [r for r in removals
                              if r.confirmed_tool_instance_id == record.confirmed_tool_instance_id
                              and r.inspection_status in {'CONFIRMED', 'CLOSED'}
                              and r.tool_change_detail.is_replaced
                              and r.tool_change_detail.warehouse.summary_status == 'CONFIRMED'
                              and r.tool_change_detail.warehouse.project_id == previous.warehouse.project_id
                              and r.tool_change_detail.warehouse.shield_model_id == previous.warehouse.shield_model_id
                              and _event_key(r.tool_change_detail)
                              and _event_key(previous)[:2] < _event_key(r.tool_change_detail)[:2] < install_key[:2]]
            if len(prior_removals) != 1:
                conflict = '实例重复安装且前一服役段没有唯一已确认拆除'
        if conflict:
            conflicts[record.id] = conflict
        candidates[record.id] = installed
        competing[installed.id].append(record.id)
    rows = []
    for detail in details:
        if not detail.is_replaced:
            continue
        record = old_records.get(detail.id)
        installed = candidates.get(record.id) if record else None
        reason = ''
        if not record or not record.confirmed_tool_instance_id:
            reason = '旧刀身份未确认'
        elif record.inspection_status not in {'CONFIRMED', 'CLOSED'}:
            reason = '厂家反馈未确认'
        elif detail.warehouse.summary_status != 'CONFIRMED':
            reason = '拆除开仓尚未确认'
        elif not installed:
            reason = '没有唯一合法的前序安装记录'
        elif record.id in conflicts:
            reason = conflicts[record.id]
        elif installed.warehouse.open_time > detail.warehouse.open_time:
            reason = '安装时间晚于拆除时间'
        elif len(competing[installed.id]) != 1:
            reason = '同一安装段存在多个已确认拆除记录'
        elif int(detail.warehouse.ring_no) == int(installed.warehouse.ring_no):
            reason = '同环拆装待核对'
        elif installed.warehouse.summary_status != 'CONFIRMED':
            reason = '前序安装开仓尚未确认'
        manufacturer = (installed.manufacturer or '') if installed else ''
        state = normalize_wear(detail.wear_condition)
        rows.append({
            'detail_id': detail.id, 'opening_id': detail.warehouse_id,
            'warehouse_id': detail.warehouse.warehouse_id, 'ring_no': detail.warehouse.ring_no,
            'cutter_position_no': detail.cutter_position_no, 'tool_parent_type': detail.tool_parent_type,
            'old_tool_number': (record.old_tool_number or '') if record else '',
            'new_tool_number': detail.tool_number or '', 'manufacturer': manufacturer,
            'instance_id': record.confirmed_tool_instance_id if record else None,
            'installation_detail_id': installed.id if installed else None,
            'installation_opening_id': installed.warehouse_id if installed else None,
            'installation_ring_no': installed.warehouse.ring_no if installed else None,
            'paired': not reason, 'reason': reason,
            'service_rings': int(detail.warehouse.ring_no) - int(installed.warehouse.ring_no) if not reason else None,
            'wear_condition': detail.wear_condition or '', 'wear_state': state,
            'inspection_status': record.inspection_status if record else None,
            'pairing_source': 'confirmed' if record and record.confirmed_tool_instance_id else ('suggested' if record and record.suggested_tool_instance_id else 'none'),
        })
    return rows


def empty_cost_sources():
    return dict(installation=0.0, confirmed_repair=0.0, legacy=0.0,
                unresolved=0.0, total=0.0, missing_price_count=0,
                pending_repair_count=0, repair_missing_price_count=0,
                unresolved_count=0, priced_count=0)


def cost_source_rows(details):
    """Each row identifies an amount's origin, not a second replacement event."""
    from .models import NewToolRecord, OldToolRecord
    details = list(details)
    ids = [row.id for row in details]
    visible_installs = set(scoped_queryset(NewToolRecord.objects.filter(tool_change_detail_id__in=ids)).values_list('tool_change_detail_id', flat=True))
    visible_repairs = set(scoped_queryset(OldToolRecord.objects.filter(tool_change_detail_id__in=ids)).values_list('tool_change_detail_id', flat=True))
    rows = []
    for detail in details:
        if not detail.is_replaced:
            continue
        install = getattr(detail, 'new_tool_record', None)
        repair = getattr(detail, 'old_tool_record', None)
        if repair and detail.id not in visible_repairs:
            repair = None
        if install and detail.id not in visible_installs:
            install = None
        base = {
            'detail_id': detail.id, 'opening_id': detail.warehouse_id,
            'warehouse_id': detail.warehouse.warehouse_id, 'ring_no': detail.warehouse.ring_no,
            'tool_parent_type': detail.tool_parent_type, 'cutter_position_no': detail.cutter_position_no,
            'manufacturer': detail.manufacturer or '', 'new_tool_number': detail.tool_number or '',
            'old_tool_number': repair.old_tool_number if repair else '',
        }
        # Legacy REPAIR could already represent this same vendor amount. No
        # source identifier proves two expenses, even when their values differ.
        overlap = bool(not install and detail.replacement_type == 'REPAIR'
                       and detail.price is not None and repair and repair.repair_price is not None)
        source = 'installation' if install else {
            'COMPLETE': 'legacy_complete', 'REPAIR': 'legacy_repair',
        }.get(detail.replacement_type, 'legacy_untyped')
        rows.append({**base, 'id': f'detail:{detail.id}', 'source': 'unresolved' if overlap else source,
                     'original_source': source, 'amount': float(detail.price) if detail.price is not None else None,
                     'included': detail.price is not None and not overlap,
                     'reason': '历史维修与返修金额归属待核对' if overlap else ('缺少登记价格' if detail.price is None else '')})
        if repair:
            confirmed = repair.inspection_status in {'CONFIRMED', 'CLOSED'}
            rows.append({**base, 'id': f'repair:{repair.id}', 'source': 'unresolved' if overlap else 'confirmed_repair',
                         'original_source': 'confirmed_repair', 'inspection_status': repair.inspection_status,
                         'amount': float(repair.repair_price) if repair.repair_price is not None else None,
                         'included': confirmed and repair.repair_price is not None and not overlap,
                         'reason': '历史维修与返修金额归属待核对' if overlap else (
                             '待厂家反馈确认' if not confirmed else ('缺少返修价格' if repair.repair_price is None else ''))})
    return rows


def select_cost_rows(rows, cost_types):
    if not cost_types:
        return rows
    def matches(row):
        source = row.get('original_source', row['source'])
        return (('COMPLETE' in cost_types and source in {'installation', 'legacy_complete'})
                or ('REPAIR' in cost_types and source in {'confirmed_repair', 'legacy_repair'}))
    return [row for row in rows if matches(row)]


def summarize_cost_rows(rows):
    result = empty_cost_sources()
    totals = {key: Decimal('0') for key in ('installation', 'confirmed_repair', 'legacy', 'unresolved')}
    unresolved_ids = set()
    for row in {row['id']: row for row in rows}.values():
        source, amount = row['source'], row['amount']
        if source == 'unresolved':
            unresolved_ids.add(row['detail_id'])
            if amount is not None:
                totals['unresolved'] += Decimal(str(amount))
        elif source == 'confirmed_repair' and row.get('inspection_status') not in {'CONFIRMED', 'CLOSED'}:
            result['pending_repair_count'] += 1
        elif amount is None:
            result['repair_missing_price_count' if source == 'confirmed_repair' else 'missing_price_count'] += 1
        elif row['included']:
            result['priced_count'] += 1
            key = 'legacy' if source.startswith('legacy_') else source
            totals[key] += Decimal(str(amount))
    result.update({key: float(value) for key, value in totals.items()})
    result['total'] = float(totals['installation'] + totals['confirmed_repair'] + totals['legacy'])
    result['unresolved_count'] = len(unresolved_ids)
    return result


def observed_detail(detail):
    """Legacy non-default observations count; inherited NORMAL alone does not."""
    return bool(
        detail.is_checked or detail.is_replaced or detail.checked_at
        or detail.blade_wear_amount is not None
        or (str(detail.wear_condition or '').strip().upper()
            not in {'', 'NORMAL', 'GOOD', '正常', '良好'})
    )


def active_observed_queryset(queryset, track_bounds=(None, None)):
    queryset = queryset.filter(warehouse__ring_no__regex=RING_NUMERIC_REGEX)
    ids = [row.id for row in queryset.values_list(
        'id', 'cutter_position_no', 'tool_parent_type', 'is_checked', 'is_replaced',
        'checked_at', 'blade_wear_amount', 'wear_condition',
        named=True,
    ) if is_active_cutter_position(row.cutter_position_no, row.tool_parent_type)
        and observed_detail(row) and matches_blade_track(row, track_bounds)]
    return queryset.filter(id__in=ids)


def analysis_meta(openings, params, raw_details, selected_details, draft_count):
    raw = list(raw_details.values_list(
        'id', 'cutter_position_no', 'tool_parent_type', 'is_checked', 'is_replaced',
        'checked_at', 'blade_wear_amount', 'wear_condition',
        named=True,
    ))
    active = [r for r in raw if is_active_cutter_position(r.cutter_position_no, r.tool_parent_type)]
    def names(field):
        # Distinct can retain annotation/ordering columns. Deduplicate the actual
        # labels too, independently of the opening queryset's SQL shape.
        return '、'.join(sorted({str(value).strip() for value in
            openings.order_by().values_list(field, flat=True).distinct()
            if value is not None and str(value).strip()}))
    return {
        'schema_version': 2,
        'filter_capabilities': ['blade_track_range'],
        'generated_at': timezone.now().isoformat(),
        'summary_status': str(params.get('summary_status') or 'CONFIRMED').upper(),
        'opening_count': openings.count(),
        'draft_opening_count': draft_count,
        'excluded_inactive_count': len(raw) - len(active),
        'unobserved_count': sum(not observed_detail(r) for r in active),
        'observed_count': selected_details.count(),
        'legacy_observed_count': selected_details.filter(is_checked=False).count(),
        'scope': {**{key: params.get(key) for key in (
            'project', 'shield_machine', 'start_ring', 'end_ring', 'stratum_type',
            'stratum_types', 'tool_parent_type', 'tool_type_name', 'tool_type_names',
            'manufacturer', 'manufacturers', 'cost_type', 'cost_types',
            'blade_track_min', 'blade_track_max',
        ) if params.get(key) not in (None, '')},
            'project_name': names('project__project_name'),
            'shield_machine_name': names('shield_model__shield_model'),
        },
        'blade_track_basis': '按当前刀位权威映射的中心轨迹半径（mm），含上下限；S19采用中心参考半径，不采用开挖侧定位半径。旧刀按拆除刀位筛选，配对保留范围外安装历史。',
        'wear_basis': '现场已识别异常磨损记录 / 已分类样本（正常+异常）；未记录或未识别不计分母，不是故障率',
        'warnings': [
            '整仓确认汇总与筛选明细分别统计，确认状态不代表财务审核。',
            '金额是登记金额，缺价不按零价补齐；地层分组可能重叠，不能加总。',
            '细分刀型沿用刀位当前绑定档案；历史刀型快照比较尚未提供，不据此判定同型厂家优劣。',
        ],
    }
