"""按原安装厂家比较已确认的服役段。"""
import json
from collections import Counter, defaultdict
from decimal import Decimal

from application.ai_assistant.tools import _analysis_payload, _build_json, classify_wear_counts, is_abnormal_wear
from application.ai_assistant.tools_inspections import _detail_scope, _filtered_details, _validate_detail_params
from application.shield.analysis_metrics import confirmed_service_segments
from application.shield.cutter_position_scope import normalize_cutter_position_no


def _manufacturer_result(name, segments):
    rings = [s['service_rings'] for s in segments]
    wear = Counter(s['wear_condition'] for s in segments)
    classified = classify_wear_counts(segments)
    denominator = classified['normal'] + classified['abnormal']
    return {'manufacturer': name, 'confirmed_segment_count': len(segments),
            'avg_service_rings': round(sum(rings) / len(rings), 1),
            'min_service_rings': min(rings), 'max_service_rings': max(rings),
            'classified_count': denominator, 'abnormal_count': classified['abnormal'],
            'abnormal_rate_pct': round(classified['abnormal'] / denominator * 100, 1) if denominator else None,
            'abnormal_type_counts': {key: value for key, value in sorted(wear.items()) if is_abnormal_wear(key)},
            'abnormal_types': {key: value for key, value in sorted(wear.items()) if is_abnormal_wear(key)}}


def compare_manufacturer_service(params_str: str) -> str:
    try:
        params = json.loads(params_str)
        _validate_detail_params(params)
        allowed = {'project_id', 'shield_machine_id', 'tool_type', 'ring_range', 'manufacturers', 'min_samples'}
        if params.keys() - allowed:
            raise ValueError('不支持的参数；可用参数：' + '、'.join(sorted(allowed)))
        if 'manufacturers' in params and (not isinstance(params['manufacturers'], list)
                or any(not isinstance(name, str) or not name.strip() for name in params['manufacturers'])):
            raise ValueError('manufacturers 必须是非空厂家名称的字符串列表，按名称精确匹配')
        if 'min_samples' in params and (type(params['min_samples']) is not int or params['min_samples'] < 1):
            raise ValueError('min_samples 必须是正整数')
    except (ValueError, TypeError) as exc:
        return _build_json({'error': str(exc) if not isinstance(exc, json.JSONDecodeError) else '参数必须是有效的 JSON 对象'})

    params.setdefault('min_samples', 3)
    details = list(_filtered_details(params).filter(is_replaced=True).select_related('warehouse'))
    # 候选按拆下环筛选；共享函数自行查询窗口外的原安装，不设置或覆盖请求权限上下文。
    segments = confirmed_service_segments(details)
    names = params.get('manufacturers')
    groups = defaultdict(list)
    pending = no_identity = 0
    for segment in segments:
        if segment['paired']:
            if not names or segment['manufacturer'] in names:
                groups[segment['manufacturer']].append(segment)
        elif segment['pairing_source'] != 'confirmed':
            no_identity += 1
        elif segment['inspection_status'] == 'PENDING_VENDOR_FEEDBACK':
            pending += 1
        else:
            no_identity += 1
    manufacturers = [_manufacturer_result(name, rows) for name, rows in groups.items()]
    manufacturers.sort(key=lambda item: (-item['avg_service_rings'], item['manufacturer']))
    supply = defaultdict(list)
    for detail in details:
        name = detail.manufacturer or ''
        if not names or name in names:
            supply[name].append(detail)

    # 在役没有拆下环，不套用拆下环段；按同项目、同机器、同刀位的末次安装判断。
    current_params = {key: value for key, value in params.items() if key != 'ring_range'}
    history = list(_filtered_details(current_params).filter(is_replaced=True)
                   .select_related('warehouse', 'new_tool_record__tool_instance'))
    latest = {}
    for row in sorted(history, key=lambda r: (r._tool_ring, r.warehouse.open_time, r.pk)):
        key = (row.warehouse.project_id, row.warehouse.shield_model_id, normalize_cutter_position_no(row.cutter_position_no))
        latest[key] = row
    current = [row for row in latest.values() if getattr(row, 'new_tool_record', None)
               and (not names or (row.manufacturer or '') in names)]
    warnings = ['在役数量按当前末次安装统计，不受拆下环段限制。']
    if names:
        warnings.append('待反馈及无法组成确认配对的数量按整个候选范围统计，无法可靠按原安装厂家筛选。')
    unpaired_reasons = Counter(s['reason'] for s in segments if not s['paired'])
    if no_identity:
        warnings.append('缺确认身份数量也包括安装记录不完整或配对冲突的记录，不能计入平均寿命。')
    return _build_json({
        'scope': {**_detail_scope(params, details), 'unconfirmed_reasons': dict(unpaired_reasons)},
        'service_by_install_manufacturer': [m for m in manufacturers if m['confirmed_segment_count'] >= params['min_samples']],
        'insufficient_samples': [m for m in manufacturers if m['confirmed_segment_count'] < params['min_samples']],
        'unconfirmed': {'pending_feedback_count': pending, 'no_confirmed_identity_count': no_identity,
                        'in_service_count': len(current)},
        'supply_by_new_manufacturer': [
            {'manufacturer': name, 'install_count': len(rows),
             'registered_amount_yuan': float(sum((r.price for r in rows if r.price is not None), Decimal('0.00')))
             if any(r.price is not None for r in rows) else None}
            for name, rows in sorted(supply.items())],
        **_analysis_payload(summary={'confirmed_segment_count': sum(m['confirmed_segment_count'] for m in manufacturers),
                                     'candidate_count': len(details)},
                            facts=[f'现场观测记录中有 {len(details)} 条更换候选；筛选厂家后可比较的确认服役段共 {sum(m["confirmed_segment_count"] for m in manufacturers)} 段。'],
                            warnings=warnings, conclusion_hint='寿命和磨损归原安装厂家；供货次数及登记金额另列。'),
        'note': '寿命和磨损按刀具原安装时的厂家统计，只用厂家已确认或已归档的拆下记录；还没确认的单独计数。供货统计按本次新装的厂家，金额是登记金额。样本量小的厂家差异不能说明质量高低。',
    })
