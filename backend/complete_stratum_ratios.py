"""Complete reviewed estimates for presentation, retaining raw data for audit.

Only the unresolved share is distributed. Existing class areas are retained;
the current ring has twice the weight of each adjacent ring. This is display
estimation requested by the project owner, not additional source recognition.
"""
import argparse
import hashlib
import json
from pathlib import Path

from application.shield.stratum_ratios import validate_stratum_ratios

COMPLETION_METHOD = 'adjacent_ring_weighted_allocation_v1'
FIXED_CODES = {'AREA_BOULDER'}


def smooth_unresolved_areas(rings):
    original = {str(int(r)): validate_stratum_ratios(v) for r, v in rings.items()}
    if len(original) != len(rings) or any(str(int(r)) != r for r in rings):
        raise ValueError('Ring keys must be distinct canonical integers')
    completed, allocated = {}, {}

    def matrix(value):
        return {k: v for k, v in value.items() if v > 0 and k not in FIXED_CODES | {'UNRESOLVED'}}

    for ring in sorted(original, key=int):
        raw = original[ring]
        unknown = raw.get('UNRESOLVED', 0)
        known = {k: v for k, v in raw.items() if k != 'UNRESOLVED' and v > 0}
        if not raw:
            raise ValueError(f'Ring {ring} has no extracted source data')
        if unknown <= 0:
            completed[ring] = known
            continue
        current = matrix(raw)
        neighbors = [(matrix(original.get(str(int(ring) + offset), {})), 1)
                     for offset in (-1, 1)]
        if current:
            candidates = set(current)
            samples = [(current, 2), *neighbors]
        else:
            # Entirely obscured rings may borrow only from the closest source
            # ring(s), never from earlier completion results in this loop.
            available = [(abs(int(r) - int(ring)), matrix(v)) for r, v in original.items()
                         if matrix(v)]
            if not available:
                raise ValueError(f'Ring {ring} has no neighboring lithology evidence')
            distance = min(d for d, _ in available)
            samples = [(v, 1) for d, v in available if d == distance]
            candidates = set().union(*(v.keys() for v, _ in samples))
        scores = dict.fromkeys(sorted(candidates), 0.0)
        for values, weight in samples:
            total = sum(values.get(k, 0) for k in candidates)
            if total > 0:
                for code in scores:
                    scores[code] += weight * values.get(code, 0) / total
        total_score = sum(scores.values())
        if total_score <= 0:
            raise ValueError(f'Ring {ring} has no allocatable source class')
        result = {**known}
        for code, score in scores.items():
            result[code] = round(result.get(code, 0) + unknown * score / total_score, 6)
        # Keep explicitly measured boulder areas fixed, including rounding.
        largest = max(scores, key=lambda code: result[code])
        result[largest] = round(result[largest] + 100 - sum(result.values()), 6)
        completed[ring] = validate_stratum_ratios({k: v for k, v in result.items() if v > 0})
        allocated[ring] = {'source_unresolved_percent': unknown,
                           'added_percent': {k: round(v - known.get(k, 0), 6)
                                             for k, v in completed[ring].items()
                                             if v != known.get(k, 0)}}
    return completed, allocated


def complete_payload(payload):
    if payload.get('completion'):
        raise ValueError('Use the raw extraction, not an already completed result')
    if payload.get('measurement_kind') not in {
        'cross_section_area_percent', 'longitudinal_section_area_percent'
    } or payload.get('estimated') is not True:
        raise ValueError('Only explicitly estimated section areas may be completed')
    rings, allocation = smooth_unresolved_areas(payload['rings'])
    quality = dict(payload.get('quality', {}))
    quality.update({'complete_rings': len(rings), 'incomplete_rings': 0,
                    'unknown_equivalent_rings': 0,
                    'completed_by_allocation_rings': len(allocation)})
    return {**payload, 'rings': rings, 'raw_rings': payload['rings'],
            'raw_quality': payload.get('quality', {}), 'quality': quality,
            'method': payload['method'] + '；按甲方展示用途，将未识别面积按本环及相邻环已识别比例加权分配；保留孤石图示轮廓占比；此补齐不代表新增图纸识别。',
            'completion': {'method': COMPLETION_METHOD, 'estimated': True,
                           'current_ring_weight': 2, 'adjacent_ring_weight': 1,
                           'fixed_codes': sorted(FIXED_CODES), 'allocation': allocation}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('Keep the raw extraction; output must use a different path')
    raw = args.input.read_bytes()
    result = complete_payload(json.loads(raw.decode('utf-8-sig')))
    result['completion']['raw_payload_sha256'] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result['quality'], ensure_ascii=False))
