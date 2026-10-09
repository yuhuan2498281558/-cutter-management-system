"""Manufacturer cohorts based on the strata traversed during a confirmed service segment."""
from collections import defaultdict

from .analysis_metrics import confirmed_service_segments, scoped_queryset
from .models import StratumBasicInfo, ToolChangeDetail
from .stratum_ratios import summarize_stratum_exposure, STRATUM_LABELS


def manufacturer_stratum_performance(details, selected_code='', selected_manufacturers=(), labels=None):
    labels = {**STRATUM_LABELS, **(labels or {})}
    loaded = list(details.select_related('warehouse'))
    by_detail = {row.id: row for row in loaded}
    segments = confirmed_service_segments(loaded)
    paired = [row for row in segments if row['paired'] and (
        not selected_manufacturers or row['manufacturer'] in selected_manufacturers)]
    projects = {by_detail[row['detail_id']].warehouse.project_id for row in paired}
    strata = defaultdict(list)
    for row in scoped_queryset(StratumBasicInfo.objects.filter(project_id__in=projects)).values(
        'project_id', 'ring_no', 'stratum_type_codes', 'stratum_type_ratios',
    ):
        strata[row['project_id']].append(row)
    installs = {row.id: row for row in scoped_queryset(ToolChangeDetail.objects.filter(
        id__in=[row['installation_detail_id'] for row in paired],
    )).only('id', 'price')}
    grouped = defaultdict(list)
    service_rows = []
    available_codes = set()
    for segment in paired:
        project_id = by_detail[segment['detail_id']].warehouse.project_id
        exposure = summarize_stratum_exposure(
            strata[project_id], segment['installation_ring_no'], segment['ring_no'],
        )
        # Cohorts use positive area rock types only; historical engineering
        # conditions remain separate metadata and never become area cohorts.
        codes = [code for code in exposure['encountered_codes'] if code != 'UNRESOLVED']
        available_codes.update(codes)
        installed = installs.get(segment['installation_detail_id'])
        item = {**segment, 'stratum_exposure': exposure,
                'installation_price': float(installed.price) if installed and installed.price is not None else None}
        if not selected_code or selected_code in codes:
            service_rows.append(item)
        for code in codes:
            if not selected_code or selected_code == code:
                grouped[(code, segment['manufacturer'])].append(item)
    items = []
    for (code, manufacturer), cohort in sorted(grouped.items()):
        if not manufacturer:
            continue
        wear = [row for row in cohort if row['wear_state'] is not None]
        abnormal = sum(row['wear_state'] == 'ABNORMAL' for row in wear)
        priced = [row['installation_price'] for row in cohort if row['installation_price'] is not None]
        quantified = [row for row in cohort if code in row['stratum_exposure']['equivalent_rings']]
        complete = [row for row in quantified if not row['stratum_exposure']['missing_rings']]
        known_equivalent = sum(row['stratum_exposure']['equivalent_rings'][code] for row in quantified)
        items.append({
            'stratum_code': code, 'stratum_name': labels.get(code, code), 'manufacturer': manufacturer,
            'sample_count': len(cohort), 'priced_count': len(priced),
            'avg_installation_price': round(sum(priced) / len(priced), 2) if priced else None,
            'avg_service_rings': round(sum(row['service_rings'] for row in cohort) / len(cohort), 1),
            'wear_recorded_count': len(wear), 'abnormal_count': abnormal,
            'abnormal_rate': round(abnormal / len(wear), 4) if wear else None,
            'known_equivalent_rings': round(known_equivalent, 4) if quantified else None,
            'ratio_sample_count': len(quantified), 'complete_ratio_sample_count': len(complete),
            'avg_equivalent_rings': round(sum(row['stratum_exposure']['equivalent_rings'][code]
                                            for row in complete) / len(complete), 2) if complete else None,
            'missing_ratio_rings': sum(row['stratum_exposure']['missing_rings'] for row in cohort),
        })
    return {
        'items': items, 'service_rows': service_rows,
        'stratum_options': [{'value': code, 'label': labels.get(code, code)} for code in sorted(available_codes)],
        'selected_stratum': selected_code,
        'paired_count': len(paired),
        'unpaired_count': sum(not row['paired'] for row in segments),
        'unknown_manufacturer_count': sum(not row['manufacturer'] for row in paired),
        'missing_stratum_segment_count': sum(not row['stratum_exposure']['encountered_codes'] for row in service_rows),
        'basis': '按已确认旧刀完整服役环段的正占比岩层类型分组；安装环不计、拆除环计入。缺占比不回退为历史工程标签。经过多种岩层的刀具参与多个组，组间不可相加。',
        'ratio_basis': '等效环数为每环横断面面积占比之和；按图示轮廓和岩层横向水平延伸假设作图示断面估算。缺占比不补零，平均等效环数仅使用占比完整的服役段。',
    }
