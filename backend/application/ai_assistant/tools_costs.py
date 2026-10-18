"""型号报价和分来源登记金额的只读查询。"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import IntegerField, Q
from django.db.models.functions import Cast

from application.ai_assistant.tools import _active_detail_query, _analysis_payload, _build_json
from application.ai_assistant.tools_stratum_area import _checked_ring_range, _positive_int, _read_params
from application.shield.analysis_metrics import (
    RING_NUMERIC_REGEX, confirmed_service_segments, cost_source_rows, summarize_cost_rows,
)
from application.shield.models import TOOL_TYPES, ToolCost


_CATALOG_NOTE = '报价库里每个型号、类型、品牌、厂家组合只有一条登记，没有多期报价，看不出价格涨跌。库存登记值不是库存台账，这里不提供库存。登记时间是录入时间，不是报价生效日期。'
_AMOUNTS_NOTE = '这些是系统里登记的金额，不是实际支出。合计 = 新装登记金额 + 厂家已确认的返修金额；还在等厂家反馈的返修金额单独列出，没有算进合计。'


def _check_tool_type(params):
    tool_type = params.get('tool_type')
    if tool_type is not None and tool_type not in tuple(code for code, _ in TOOL_TYPES):
        raise ValueError(f"tool_type可用值为{'、'.join(code for code, _ in TOOL_TYPES)}。")
    return tool_type


def _money(value):
    return round(float(value), 2) if value is not None else None


def query_tool_cost_catalog(params_str: str) -> str:
    try:
        params = _read_params(params_str)
        tool_type = _check_tool_type(params)
        cost_type = params.get('cost_type')
        if cost_type is not None and cost_type not in tuple(code for code, _ in ToolCost.COST_TYPE_CHOICES):
            raise ValueError(f"cost_type可用值为{'、'.join(code for code, _ in ToolCost.COST_TYPE_CHOICES)}。")
        limit = _positive_int(params.get('list_limit', 50), 'list_limit', 200)
        for key in ('tool_model', 'brand', 'manufacturer'):
            if params.get(key) is not None and (not isinstance(params[key], str) or not params[key].strip()):
                raise ValueError(f'{key}须为非空字符串。')
        query = ToolCost.objects.select_related('tool_info')
        if tool_type is not None:
            query = query.filter(tool_info__tool_parent_type=tool_type)
        if cost_type is not None:
            query = query.filter(cost_type=cost_type)
        if params.get('tool_model') is not None:
            query = query.filter(Q(tool_info__tool_type_name__icontains=params['tool_model']) |
                                 Q(tool_info__tool_type_code__icontains=params['tool_model']))
        for key in ('brand', 'manufacturer'):
            if params.get(key) is not None:
                query = query.filter(**{key: params[key]})
        records = list(query.order_by('tool_info__tool_type_name', 'cost_type', 'unit_price', 'id'))
        grouped = defaultdict(list)
        for row in records:
            grouped[row.tool_info_id].append(row)
        by_model = []
        for rows in grouped.values():
            model = rows[0].tool_info
            item = {'tool_model': model.tool_type_name, 'tool_model_code': model.tool_type_code,
                    'tool_type': model.tool_parent_type}
            for code, prefix in (('NEW_TOOL', 'new_tool'), ('REPAIR', 'repair')):
                quotes = [row for row in rows if row.cost_type == code]
                prices = [row.unit_price for row in quotes if row.unit_price is not None]
                item.update({
                    f'{prefix}_price_min_yuan': _money(min(prices)) if prices else None,
                    f'{prefix}_price_max_yuan': _money(max(prices)) if prices else None,
                    f'{prefix}_quote_count': len(quotes),
                })
            by_model.append(item)
        warnings = []
        if len(records) > limit:
            warnings.append(f'报价明细仅列前{limit}条，型号价格范围和条数按全部匹配报价统计。')
        if not records:
            warnings.append('没有找到符合条件的报价。')
        missing_count = sum(row.unit_price is None for row in records)
        if missing_count:
            warnings.append(f'有{missing_count}条报价未登记单价，未计入价格范围。')
        return _build_json({
            'scope': {**{key: params.get(key) for key in ('tool_type', 'tool_model', 'brand', 'manufacturer', 'cost_type')},
                      'list_limit': limit, 'quote_count': len(records), 'returned_quote_count': min(limit, len(records)),
                      'model_count': len(by_model)},
            'by_model': by_model,
            'quotes': [{
                'tool_model': row.tool_info.tool_type_name, 'tool_type': row.tool_info.tool_parent_type,
                'cost_type': row.cost_type, 'brand': row.brand, 'manufacturer': row.manufacturer,
                'unit_price_yuan': _money(row.unit_price),
                'registered_at': row.create_datetime.isoformat() if row.create_datetime else None,
            } for row in records[:limit]],
            'note': _CATALOG_NOTE,
            **_analysis_payload(
                summary={'model_count': len(by_model), 'quote_count': len(records)},
                facts=[f'查到{len(by_model)}个型号、{len(records)}条报价，新刀与维修分别统计。'],
                warnings=warnings, conclusion_hint=_CATALOG_NOTE,
            ),
        })
    except (ValueError, TypeError) as exc:
        return _build_json({'error': f'参数或数据格式错误：{exc}'})


def _registered_totals(rows):
    # 无明确新装来源的历史金额不改名为新装；归属待核对的金额不重复计入。
    installs = [row for row in rows if row['source'] == 'installation']
    repairs = [row for row in rows if row['source'] == 'confirmed_repair'
               and row.get('inspection_status') in {'CONFIRMED', 'CLOSED'}]
    pending = [row for row in rows if row['source'] == 'confirmed_repair'
               and row.get('inspection_status') == 'PENDING_VENDOR_FEEDBACK']
    summary = summarize_cost_rows(installs + repairs + pending)

    def amount(items, value):
        return None if items and all(row['amount'] is None for row in items) else _money(value)

    pending_amount = sum((Decimal(str(row['amount'])) for row in pending if row['amount'] is not None), Decimal('0'))
    return {
        'new_install': {
            'amount_yuan': amount(installs, summary['installation']), 'record_count': len(installs),
            'zero_price_count': sum(row['amount'] == 0 for row in installs),
            'missing_price_count': sum(row['amount'] is None for row in installs),
        },
        'confirmed_repair': {'amount_yuan': amount(repairs, summary['confirmed_repair']), 'record_count': len(repairs)},
        'pending_repair': {'amount_yuan': amount(pending, pending_amount), 'record_count': len(pending)},
        'total_registered_cost_yuan': amount(installs + repairs, summary['total']),
    }


def query_registered_amounts(params_str: str) -> str:
    try:
        params = _read_params(params_str)
        tool_type = _check_tool_type(params)
        if params.get('shield_machine_id') is not None:
            _positive_int(params['shield_machine_id'], 'shield_machine_id')
        ring_range = _checked_ring_range(params['ring_range']) if params.get('ring_range') is not None else None
        group_by = params.get('group_by', 'none')
        if group_by not in ('none', 'manufacturer', 'tool_type', 'opening'):
            raise ValueError('group_by可用值为none、manufacturer、tool_type、opening。')
        query = _active_detail_query(params)
        if tool_type is not None:
            query = query.filter(_ai_type=tool_type)
        if ring_range:
            query = query.filter(warehouse__ring_no__regex=RING_NUMERIC_REGEX).annotate(
                _cost_ring=Cast('warehouse__ring_no', IntegerField()),
            ).filter(_cost_ring__range=ring_range)
        details = list(query.select_related('warehouse__project', 'new_tool_record', 'old_tool_record'))
        rows = cost_source_rows(details)
        totals = _registered_totals(rows)
        groups, warnings = [], []
        excluded = [row for row in rows if row['source'] not in {'installation', 'confirmed_repair'}]
        missing_repairs = [row for row in rows if row['source'] == 'confirmed_repair' and row['amount'] is None]
        if excluded:
            warnings.append(f'有{len(excluded)}条历史或归属待核对的金额来源，未计入新装和已确认返修合计。')
        if totals['new_install']['missing_price_count'] or missing_repairs:
            warnings.append(f"新装缺价{totals['new_install']['missing_price_count']}条、返修缺价{len(missing_repairs)}条；已登记金额只汇总有价格的记录，没有把缺价补成0。")
        if group_by != 'none':
            grouped = defaultdict(list)
            detail_by_id = {detail.id: detail for detail in details}
            segments = {row['detail_id']: row for row in confirmed_service_segments(details)} if group_by == 'manufacturer' else {}
            unknown_repairs = 0
            for row in rows:
                if row['source'] not in {'installation', 'confirmed_repair'}:
                    continue
                if group_by == 'manufacturer':
                    if row['source'] == 'installation':
                        key = row['manufacturer'] or '未登记厂家'
                    else:
                        segment = segments.get(row['detail_id'], {})
                        key = segment.get('manufacturer') if segment.get('paired') else None
                        if not key:
                            key = '未能确定原厂家'
                            unknown_repairs += 1
                elif group_by == 'tool_type':
                    key = detail_by_id[row['detail_id']]._ai_type
                else:
                    key = row['opening_id']
                grouped[key].append(row)
            for key, items in grouped.items():
                if group_by == 'opening':
                    opening = detail_by_id[items[0]['detail_id']].warehouse
                    identity = {'opening_id': key, 'warehouse_id': opening.warehouse_id,
                                'project_id': opening.project.project_id, 'shield_machine_id': opening.shield_model_id,
                                'ring_no': int(opening.ring_no)}
                else:
                    identity = {group_by: key}
                groups.append({**identity, **_registered_totals(items)})
            groups.sort(key=lambda row: (row['ring_no'], row['opening_id']) if group_by == 'opening' else row[group_by])
            if unknown_repairs:
                warnings.append(f'有{unknown_repairs}条返修记录未能确定原厂家，已单独列出。')
        rings = [int(detail.warehouse.ring_no) for detail in details if detail.warehouse.ring_no.isdigit()]
        return _build_json({
            'scope': {'project_id': params.get('project_id'), 'shield_machine_id': params.get('shield_machine_id'),
                      'ring_range': ring_range, 'tool_type': tool_type, 'group_by': group_by,
                      'ring_min': min(rings, default=None), 'ring_max': max(rings, default=None),
                      'observation_count': len(details), 'replacement_count': sum(detail.is_replaced for detail in details),
                      'excluded_cost_source_count': len(excluded)},
            **totals, 'groups': groups, 'note': _AMOUNTS_NOTE,
            **_analysis_payload(
                summary=totals,
                facts=[f"本次范围内有{len(details)}条现场观测记录，待厂家反馈的返修记录{totals['pending_repair']['record_count']}条。"],
                warnings=warnings, conclusion_hint=_AMOUNTS_NOTE,
            ),
        })
    except (ValueError, TypeError) as exc:
        return _build_json({'error': f'参数或数据格式错误：{exc}'})
