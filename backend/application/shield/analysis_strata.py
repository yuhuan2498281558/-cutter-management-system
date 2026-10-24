"""Current per-ring engineering classes for analysis opening intervals."""
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import re

from .analysis_metrics import ANALYSIS_REQUEST, RING_NUMERIC_REGEX, scoped_queryset
from .longitudinal_ratios import engineering_zones
from .models import StratumBasicInfo, WarehouseOpeningBasicInfo


def _ring(value):
    text = str(value or '')
    return int(text) if re.fullmatch(RING_NUMERIC_REGEX, text) else None


def _project_intervals(project_ids):
    # Previous openings must be found outside the selected status/ring window,
    # but within the same project, machine and user's existing data permissions.
    openings = list(scoped_queryset(WarehouseOpeningBasicInfo.objects.filter(
        project_id__in=project_ids, ring_no__regex=RING_NUMERIC_REGEX,
    )).values('id', 'project_id', 'shield_model_id', 'ring_no', 'last_ring_no', 'stratum_info_between'))
    history = defaultdict(set)
    for row in openings:
        history[row['project_id'], row['shield_model_id']].add(int(row['ring_no']))
    history = {key: sorted(rings) for key, rings in history.items()}

    strata = defaultdict(dict)
    for row in scoped_queryset(StratumBasicInfo.objects.filter(
        project_id__in=project_ids, ring_no__regex=RING_NUMERIC_REGEX,
    )).values('project_id', 'ring_no', 'longitudinal_type_ratios', 'stratum_type_codes'):
        ratios = row['longitudinal_type_ratios']
        if ratios:
            try:
                codes = {item['code'].removeprefix('AREA_') for item in engineering_zones(ratios)}
            except ValueError:
                codes = set()
        else:
            # Projects not yet supplied with area classes retain entered tags.
            codes = {code.strip() for code in (row['stratum_type_codes'] or '').split(',') if code.strip()}
        strata[row['project_id']][int(row['ring_no'])] = codes
    rings_by_project = {project: sorted(rows) for project, rows in strata.items()}
    result = {project: {} for project in project_ids}
    for row in openings:
        project, end = row['project_id'], int(row['ring_no'])
        start = _ring(row['last_ring_no'])
        if row['last_ring_no'] in (None, ''):
            previous = history[project, row['shield_model_id']]
            index = bisect_left(previous, end)
            start = previous[index - 1] if index else 0
        if start is None or start >= end:
            result[project][row['id']] = {}
            continue
        rings = rings_by_project.get(project, [])
        interval = rings[bisect_right(rings, start):bisect_right(rings, end)]
        if interval:
            counts = Counter(code for ring in interval for code in strata[project][ring])
        else:
            # Historical projects without any ring rows keep their saved scope.
            snapshot = row['stratum_info_between']
            counts = snapshot if isinstance(snapshot, dict) else {}
        result[project][row['id']] = dict(counts)
    return result


def opening_strata(openings):
    """Return {opening_id: {legacy API code: encountered ring count}}.

    AREA_* positive percentages are authoritative when present. This is an
    occurrence filter, not an area-weighted allocation of costs or tool wear.
    Cache only within one request, so edits/imports affect the next query.
    """
    openings = list(openings)
    projects = {row.project_id for row in openings}
    request = ANALYSIS_REQUEST.get()
    cache = getattr(request, '_opening_strata_by_project', {}) if request is not None else {}
    missing = projects - cache.keys()
    if missing:
        cache.update(_project_intervals(missing))
    if request is not None:
        request._opening_strata_by_project = cache
    return {row.id: cache.get(row.project_id, {}).get(row.id, {}) for row in openings}
