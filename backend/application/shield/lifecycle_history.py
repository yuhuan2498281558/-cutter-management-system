"""Read-only, scope-local service intervals for the cutterhead history."""
from application.shield.cutter_position_scope import normalize_cutter_position_no, is_active_cutter_position
from application.shield.models import ToolChangeDetail, StratumBasicInfo
from application.shield.stratum_ratios import summarize_stratum_exposure, stratum_label


def build_position_history(project, machine, position):
    rows = list(ToolChangeDetail.objects.filter(
        warehouse__project_id=project, warehouse__shield_model_id=machine,
    ).select_related('warehouse', 'warehouse__project', 'new_tool_record__tool_instance',
                     'old_tool_record', 'cutter_position__tool_info'))
    rows = [row for row in rows if normalize_cutter_position_no(row.cutter_position_no) == position
            and is_active_cutter_position(row.cutter_position_no, row.tool_parent_type)]

    def ring(row):
        try:
            return int(row.warehouse.ring_no)
        except (ValueError, TypeError):
            return -1

    def installed(row):
        # installed_at is the mobile entry timestamp, including historical backfills.
        return row.warehouse.open_time or row.create_datetime

    rows.sort(key=lambda row: (ring(row), installed(row), row.pk))
    segments = []
    for row in rows:
        record = getattr(row, 'new_tool_record', None)
        # A non-replaced inherited inspection is not another installation.
        if not segments or row.is_replaced or record:
            if segments:
                segments[-1]['remove'] = row
            segments.append({'install': row, 'remove': None})
    strata = list(StratumBasicInfo.objects.filter(project_id=project).values(
        'ring_no', 'stratum_type_codes', 'stratum_type_ratios'))
    latest = max((ring(row) for row in rows), default=-1)
    result = []
    for segment in segments:
        start, end = segment['install'], segment['remove']
        record = getattr(start, 'new_tool_record', None)
        instance = record.tool_instance if record else None
        old = getattr(end, 'old_tool_record', None) if end else None
        confirmed = old.confirmed_tool_instance_id if old else None
        conflict = bool(confirmed and (not instance or confirmed != instance.pk))
        install_known = bool(start.is_replaced or record)
        endpoint = ring(end) if end else latest
        exposure = summarize_stratum_exposure(strata, ring(start), endpoint) if install_known and not conflict and 0 <= ring(start) <= endpoint else None
        if exposure is not None:
            exposure['encountered_names'] = [stratum_label(code) for code in exposure['encountered_codes']]
            exposure['engineering_condition_names'] = [stratum_label(code) for code in exposure['engineering_condition_codes']]
        number = instance.display_tool_no if instance else start.tool_number
        status = 'REMOVED' if end else 'INSTALLED'
        if end and old and instance and confirmed == instance.pk:
            status = {'PENDING_VENDOR_FEEDBACK': 'REMOVED_PENDING_INSPECTION',
                      'CONFIRMED': 'INSPECTED', 'CLOSED': 'REPAIRED_CLOSED'}.get(old.inspection_status, status)
            if old.inspection_status == 'CLOSED' and old.disposition == 'SCRAP':
                status = 'SCRAPPED'
        result.append({
            'id': instance.pk if instance else f'legacy-{start.pk}',
            'service_id': start.pk, 'tool_uid': instance.tool_uid if instance else number,
            'display_tool_no': number or '编号未记录', 'tool_parent_type': start.tool_parent_type,
            'tool_type_name': instance.tool_type_name if instance else '',
            'manufacturer': start.manufacturer or '', 'brand': start.brand or '', 'price': start.price,
            'install_ring_no': start.warehouse.ring_no if install_known else '',
            'first_observed_ring_no': start.warehouse.ring_no,
            'remove_ring_no': end.warehouse.ring_no if end else '',
            'usage_rings': endpoint - ring(start) if install_known and end and endpoint >= ring(start) else None,
            'status': status, 'create_datetime': installed(start),
            'installation_known': install_known, 'identity_conflict': conflict,
            'pairing_source': 'confirmed' if instance and confirmed == instance.pk else 'position_sequence',
            'stratum_exposure': exposure, 'exposure_end_ring': endpoint if endpoint >= 0 else None,
            'exposure_is_open': end is None,
            'timeline': [{
                'event': 'INSTALL' if install_known else 'OBSERVED',
                'event_name': '安装' if install_known else '首次可见记录（安装时间未知）',
                'time': installed(start), 'detail_id': start.pk,
                'project_name': start.warehouse.project.project_name,
                'ring_no': start.warehouse.ring_no, 'cutter_position_no': position,
            }] + ([{'event': 'REMOVE', 'event_name': '同刀位下一次更换',
                    'time': installed(end), 'detail_id': end.pk,
                    'project_name': end.warehouse.project.project_name,
                    'ring_no': end.warehouse.ring_no, 'cutter_position_no': position}] if end else []),
        })
    return sorted(result, key=lambda item: (item['create_datetime'], int(item['first_observed_ring_no'])
                  if str(item['first_observed_ring_no']).isdigit() else -1, item['service_id']))
