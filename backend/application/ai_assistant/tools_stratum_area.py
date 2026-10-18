"""地层面积及开仓地层的只读查询。"""
import json
from collections import Counter, defaultdict
from itertools import islice

from django.db.models import IntegerField
from django.db.models.functions import Cast

from application.ai_assistant.tools import _analysis_payload, _build_json
from application.shield.analysis_metrics import RING_NUMERIC_REGEX
from application.shield.longitudinal_ratios import (
    AREA_LABELS, LONGITUDINAL_LABELS, longitudinal_area_notes,
    validate_condition_alignment, validate_longitudinal_ratios,
)
from application.shield.models import StratumBasicInfo, WarehouseOpeningBasicInfo
from application.shield.stratum_ratios import (
    STRATUM_LABELS, stratum_label, validate_stratum_ratios,
)


_BASIS_LABELS = {
    'longitudinal_area': '纵断面六类面积', 'cross_section': '横断面岩性占比',
}
_SOURCE_NOTE = (
    '两套面积都来自图纸标注的估算。图上没能识别的部分，按本环和前后相邻环已识别的比例补齐后用于展示；'
    '孤石按图上的明确轮廓计算，不做补齐。补齐的部分不代表实测精度。'
)
_AREA_NOTE = '面积占比来自图纸标注的估算，部分环是展示补齐的数据，只用来描述地层组成，不能据此判断刀具磨损的原因。'
_OPENING_NOTE = '"当时保存"是开仓录入时写进记录的地层信息；"现在重算"是按现有地层表计算的结果。两者不同时并列给出，不改写原记录。'


def _read_params(params_str):
    params = json.loads(params_str)
    if not isinstance(params, dict):
        raise ValueError('参数必须是JSON对象。')
    if params.get('project_id') is not None and (
        not isinstance(params['project_id'], str) or not params['project_id'].strip()
    ):
        raise ValueError('project_id须为非空项目编号字符串。')
    return params


def _positive_int(value, name, maximum=None):
    if type(value) is not int or value < 1 or (maximum and value > maximum):
        limit = f'1–{maximum}之间的' if maximum else '大于0的'
        raise ValueError(f'{name}须为{limit}整数。')
    return value


def _checked_ring_range(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('ring_range须为[起始环号, 结束环号]，两项都是正整数。')
    start, end = [_positive_int(item, 'ring_range中的环号') for item in value]
    if start > end:
        raise ValueError('ring_range的起始环号不能大于结束环号。')
    return [start, end]


def _stratum_query(project_id=None):
    query = StratumBasicInfo.objects.filter(ring_no__regex=RING_NUMERIC_REGEX)
    if project_id is not None:
        query = query.filter(project__project_id=project_id)
    return query.annotate(_ring=Cast('ring_no', IntegerField()))


def _stratum_rows(query):
    return list(query.order_by('_ring', 'project_id', 'id').values(
        'project__project_id', 'ring_no', 'stratum_type_codes',
        'longitudinal_type_ratios', 'stratum_type_ratios',
    ))


def _legacy_codes(row):
    return {code.strip() for code in (row.get('stratum_type_codes') or '').split(',') if code.strip()}


def _area_ratios(row, basis):
    if basis == 'longitudinal_area':
        ratios = validate_longitudinal_ratios(row['longitudinal_type_ratios'])
        if ratios:
            # 旧分区归属不能冒充已确认的六类面积。
            validate_condition_alignment(ratios, _legacy_codes(row))
        return ratios
    return validate_stratum_ratios(row['stratum_type_ratios'])


def _ratio_items(ratios, basis):
    labels = LONGITUDINAL_LABELS if basis == 'longitudinal_area' else STRATUM_LABELS
    return [{'code': code, 'label': labels.get(code, stratum_label(code)), 'pct': round(pct, 1)}
            for code, pct in sorted(ratios.items(), key=lambda item: (-item[1], item[0]))]


def _area_summary(rows, basis, requested_rings=None, projects=None):
    by_ring = defaultdict(list)
    for row in rows:
        by_ring[row['project__project_id'], int(row['ring_no'])].append(row)
    valid = {}
    invalid_count = 0
    for key, items in by_ring.items():
        if len(items) != 1:
            invalid_count += 1
            continue
        try:
            ratios = _area_ratios(items[0], basis)
        except ValueError:
            invalid_count += 1
            continue
        if ratios:
            valid[key] = ratios
    if requested_rings is None:
        requested_count = len(by_ring)
        missing = (key[1] for key in sorted(by_ring, key=lambda key: (key[1], key[0])) if key not in valid)
        requested_keys = sorted(by_ring, key=lambda key: (key[1], key[0]))
    else:
        projects = projects or [None]
        requested_count = len(requested_rings) * len(projects)
        missing = (ring for ring in requested_rings for project in projects if (project, ring) not in valid)
        requested_keys = ((project, ring) for ring in requested_rings for project in projects)
    totals, positive = defaultdict(float), Counter()
    for ratios in valid.values():
        for code, pct in ratios.items():
            totals[code] += pct / 100
            positive[code] += pct > 0
    labels = AREA_LABELS if basis == 'longitudinal_area' else STRATUM_LABELS
    all_labels = LONGITUDINAL_LABELS if basis == 'longitudinal_area' else STRATUM_LABELS
    classes = [{
        'code': code, 'label': all_labels.get(code, stratum_label(code)),
        'positive_ring_count': positive[code],
        'area_equivalent_rings': round(totals[code], 6),
        'share_pct': round(totals[code] / len(valid) * 100, 1) if valid else None,
    } for code in sorted(set(labels) | set(totals), key=lambda code: (-totals[code], code))
        # 纵断面固定列出六类；横断面的岩性名单很长，只列这段范围里出现过的。
        if basis == 'longitudinal_area' or positive[code]]
    per_ring = None
    if requested_count <= 20:
        per_ring = [{
            'project_id': project, 'ring_no': ring,
            'ratios': _ratio_items(valid.get((project, ring), {}), basis),
        } for project, ring in requested_keys]
    return {
        'ring_count_requested': requested_count, 'ring_count_with_data': len(valid),
        'missing_rings': list(islice(missing, 50)), 'missing_ring_count': requested_count - len(valid),
        'classes': classes, 'per_ring': per_ring,
    }, invalid_count


def query_stratum_area(params_str: str) -> str:
    try:
        params = _read_params(params_str)
        basis = params.get('basis', 'longitudinal_area')
        if basis not in tuple(_BASIS_LABELS):
            raise ValueError('basis可用值为longitudinal_area（纵断面六类面积）或cross_section（横断面岩性占比）。')
        if params.get('rings') is not None and params.get('ring_range') is not None:
            raise ValueError('rings和ring_range只能提供一个。')
        requested = None
        ring_range = None
        if params.get('ring_range') is not None:
            ring_range = _checked_ring_range(params['ring_range'])
            requested = range(ring_range[0], ring_range[1] + 1)
        elif params.get('rings') is not None:
            rings = params['rings']
            if not isinstance(rings, list) or not 1 <= len(rings) <= 50:
                raise ValueError('rings须为包含1–50个正整数环号的列表。')
            requested = sorted(_positive_int(ring, 'rings中的环号') for ring in rings)
            if len(set(requested)) != len(requested):
                raise ValueError('rings中的环号不能重复。')
        query = _stratum_query(params.get('project_id'))
        projects = ([params['project_id']] if params.get('project_id') is not None else
                    list(query.order_by().values_list('project__project_id', flat=True).distinct()))
        if ring_range:
            query = query.filter(_ring__range=ring_range)
        elif requested is not None:
            query = query.filter(_ring__in=requested)
        rows = _stratum_rows(query)
        result, invalid_count = _area_summary(rows, basis, requested, projects)
        warnings = []
        if result['missing_ring_count']:
            warnings.append(f"有{result['missing_ring_count']}环缺少可用面积数据，未计入平均面积占比。")
        if invalid_count:
            warnings.append(f'其中{invalid_count}环的占比未通过校验或环号重复。')
        if basis == 'longitudinal_area':
            for row in rows:
                try:
                    warnings.extend(longitudinal_area_notes(_legacy_codes(row), _area_ratios(row, basis)))
                except ValueError:
                    continue
        result.update({
            'scope': {
                'project_id': params.get('project_id'), 'project_ids': projects,
                'ring_range': ring_range, 'rings': list(requested) if params.get('rings') is not None else None,
                'ring_min': min((int(row['ring_no']) for row in rows), default=None),
                'ring_max': max((int(row['ring_no']) for row in rows), default=None),
                'record_count': len(rows), 'count_unit': '同一项目内的环号',
            },
            'basis': basis, 'basis_label': _BASIS_LABELS[basis],
            'source_note': _SOURCE_NOTE, 'note': _AREA_NOTE,
            **_analysis_payload(
                summary={'ring_count_with_data': result['ring_count_with_data'], 'basis': basis},
                facts=[f"本次查询{result['ring_count_requested']}环，其中{result['ring_count_with_data']}环有可用的{_BASIS_LABELS[basis]}。"],
                warnings=list(dict.fromkeys(warnings)), conclusion_hint=_AREA_NOTE,
            ),
        })
        return _build_json(result)
    except (ValueError, TypeError) as exc:
        return _build_json({'error': f'参数或数据格式错误：{exc}'})


def query_opening_stratum(params_str: str) -> str:
    try:
        params = _read_params(params_str)
        if params.get('ring_no') is not None and params.get('recent_openings') is not None:
            raise ValueError('ring_no和recent_openings只能提供一个。')
        if params.get('shield_machine_id') is not None:
            _positive_int(params['shield_machine_id'], 'shield_machine_id')
        ring = params.get('ring_no')
        if ring is not None:
            _positive_int(ring, 'ring_no')
        recent = _positive_int(params.get('recent_openings', 1), 'recent_openings', 20)
        query = WarehouseOpeningBasicInfo.objects.filter(ring_no__regex=RING_NUMERIC_REGEX)
        if params.get('project_id') is not None:
            query = query.filter(project__project_id=params['project_id'])
        if params.get('shield_machine_id') is not None:
            query = query.filter(shield_model_id=params['shield_machine_id'])
        query = query.annotate(_ring=Cast('ring_no', IntegerField())).select_related('project')
        history = list(query.order_by('-_ring', '-open_time', '-id'))
        selected = [row for row in history if row._ring == ring] if ring is not None else history[:recent]
        openings, warnings = [], []
        for opening in selected:
            previous = next((row._ring for row in history if row.project_id == opening.project_id
                             and row.shield_model_id == opening.shield_model_id and row._ring < opening._ring), None)
            interval = [previous + 1 if previous is not None else 1, opening._ring]
            rows = _stratum_rows(_stratum_query(opening.project.project_id).filter(_ring__range=interval))
            current = [row for row in rows if int(row['ring_no']) == opening._ring]
            legacy_counts = Counter(code for row in rows for code in _legacy_codes(row))
            current_ring = {'legacy_labels': [
                {'code': code, 'label': stratum_label(code), 'pct': None}
                for code in sorted(set().union(*(_legacy_codes(row) for row in current)))
            ]}
            interval_summary = {'legacy_label_ring_counts': dict(sorted(legacy_counts.items()))}
            coverage = {}
            for basis in _BASIS_LABELS:
                area, invalid_count = _area_summary(rows, basis, range(interval[0], interval[1] + 1), [opening.project.project_id])
                interval_summary[basis] = area['classes']
                coverage[basis] = {key: area[key] for key in (
                    'ring_count_requested', 'ring_count_with_data', 'missing_rings', 'missing_ring_count',
                )}
                current_area, _ = _area_summary(current, basis)
                current_ring[basis] = current_area['per_ring'][0]['ratios'] if current_area['per_ring'] else []
                if area['missing_ring_count']:
                    warnings.append(f"第{opening._ring}环开仓的区间有{area['missing_ring_count']}环缺少可用的{_BASIS_LABELS[basis]}。")
                if invalid_count:
                    warnings.append(f'其中{invalid_count}环的占比未通过校验或环号重复。')
            openings.append({
                'project_id': opening.project.project_id, 'shield_machine_id': opening.shield_model_id,
                'ring_no': opening._ring, 'previous_opening_ring': previous, 'interval': interval,
                'current_ring': current_ring, 'interval_summary': interval_summary,
                'interval_area_coverage': coverage,
                'saved_snapshot': {'stratum_info_between': opening.stratum_info_between,
                                   'geological_conditions': opening.geological_conditions},
                'snapshot_differs_from_current': opening.stratum_info_between != dict(legacy_counts),
            })
        if not openings:
            warnings.append('没有找到符合条件的开仓记录。')
        return _build_json({
            'scope': {'project_id': params.get('project_id'), 'shield_machine_id': params.get('shield_machine_id'),
                      'ring_no': ring, 'recent_openings': recent if ring is None else None,
                      'opening_count': len(openings), 'recent_order': '环号从大到小'},
            'openings': openings, 'source_note': _SOURCE_NOTE, 'note': _OPENING_NOTE,
            **_analysis_payload(
                summary={'opening_count': len(openings), 'snapshot_difference_count': sum(row['snapshot_differs_from_current'] for row in openings)},
                facts=[f'查到{len(openings)}次开仓；首次区间从第1环开始，其余区间不含上次开仓环。'],
                warnings=warnings, conclusion_hint=_OPENING_NOTE,
            ),
        })
    except (ValueError, TypeError) as exc:
        return _build_json({'error': f'参数或数据格式错误：{exc}'})
