"""Offline per-ring longitudinal area integration from the pinned home PDF."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from extract_pdf_stratum_ratios import (
    START_X, X_PER_RING, DXF_COLORS, sample_pdf_columns, prepare_pdf,
    classify_colors, constrain_classes,
)
from application.shield.longitudinal_ratios import (
    LONGITUDINAL_LABELS, longitudinal_class, validate_longitudinal_ratios,
)


def integrate_columns(classes, codes, heights, widths=None, condition_codes=()):
    """Integrate equal y strips with actual column heights and optional x widths."""
    counts = {code: 0.0 for code in LONGITUDINAL_LABELS}
    if widths is None:
        widths = np.ones(len(heights))
    for column, height, width in zip(classes, heights, widths):
        for index, count in enumerate(np.bincount(column, minlength=len(codes))):
            counts[longitudinal_class(codes[index], condition_codes)] += float(count) * height * width / len(column)
    total = sum(counts.values())
    result = {code: round(value / total * 100, 6) for code, value in counts.items() if value > 0}
    largest = max(result, key=result.get)
    result[largest] = round(result[largest] + 100 - sum(result.values()), 6)
    return validate_longitudinal_ratios(result)


def extract(source, output, geometry_path, conditions_path, columns=32, samples=1024, ring_numbers=None):
    from shapely.geometry import box, shape
    geometry = json.loads(geometry_path.read_text(encoding='utf-8'))
    conditions = json.loads(conditions_path.read_text(encoding='utf-8'))
    if geometry['source_sha256'] != '138b0fa7bca488440e3923e41115590c9f270a3c0fa420b63e105195f43a86b5':
        raise ValueError('Unreviewed DXF candidate source')
    polygons = [(DXF_COLORS[p['color'][0]], shape(p['geometry'])) for p in geometry['polygons']]
    rings = {}
    prepared = prepare_pdf(source)
    outline_end = prepared[2].bounds[2]
    missing_outline = {}
    all_numbers = np.asarray(sorted(set(ring_numbers or range(1, 2801))))
    if np.any((all_numbers < 1) | (all_numbers > 2800)):
        raise ValueError('Ring outside calibrated 1-2800 range')
    for ring in all_numbers:
        if not isinstance(conditions.get(str(ring)), list):
            raise ValueError(f'Missing engineering conditions for ring {ring}')
    for start in range(0, len(all_numbers), 100):
        numbers = all_numbers[start:start+100]
        left = START_X + (numbers - 1) * X_PER_RING
        covered_width = np.minimum(left + X_PER_RING, outline_end) - left
        if np.any(covered_width <= 0):
            raise ValueError('Entire ring outside source outline; recalibration required')
        xs = left[:, None] + covered_width[:, None] * (np.arange(columns) + .5) / columns
        rgb, edges, legend, digest = sample_pdf_columns(source, xs.ravel(), samples, prepared)
        for offset, ring in enumerate(numbers):
            section = geometry['sections'][str(ring)]
            # Candidates cover the full ring width; DXF does not supply the areas.
            nearby = [geometry['sections'][str(n)] for n in (max(1, ring-1), ring, min(2800, ring+1))]
            bounds = box(section['x']-.5, min(s['bottom'] for s in nearby)-.07,
                         section['x']+.5, max(s['top'] for s in nearby)+.07)
            candidates = {code for code, polygon in polygons if polygon.intersects(bounds)}
            a, b = offset * columns, (offset + 1) * columns
            classes, codes = classify_colors(rgb[a:b], legend)
            classes = constrain_classes(classes, codes, candidates)
            heights = np.diff(edges[a:b], axis=1).ravel()
            widths = np.full(columns, covered_width[offset] / columns)
            missing_width = X_PER_RING - covered_width[offset]
            if missing_width > 1e-6:
                # Preserve the full calibrated ring denominator. The missing end
                # uses the adjacent outline height only as an area reference;
                # every sample there is UNKNOWN, never inferred geology.
                classes = np.vstack([classes, np.full(samples, codes.index('UNRESOLVED'))])
                heights = np.r_[heights, heights[-1]]
                widths = np.r_[widths, missing_width]
                missing_outline[str(ring)] = round(missing_width / X_PER_RING * 100, 6)
            rings[str(ring)] = integrate_columns(classes, codes, heights, widths, conditions[str(ring)])
        print(f'Integrated rings {numbers[0]}-{numbers[-1]}', flush=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.with_suffix('.partial.json').write_text(json.dumps(rings), encoding='utf-8')
    prepared[0].close()
    payload = {
        'measurement_kind': 'longitudinal_section_area_percent', 'estimated': True,
        # Lithology pixels cannot be imported as engineering-zone polygons.
        'classification_scheme': 'area_boundaries_pending_v3',
        'source': source.name, 'source_sha256': digest,
        'method': '每环纵断面面积积分；PDF真实填充/透明蒙版及DXF候选佐证。弱风化岩与本环弱风化条件对应时单列；其余已识别面积保持分类面积待核定，不再根据工程区段标签分配面积。孤石、基岩凸起、上软下硬尚无已核验独立面积边界。未知不归一化；末环缺图作为未知。',
        'labels': LONGITUDINAL_LABELS,
        'calibration': {'ring0_edge_x': START_X, 'x_per_ring': X_PER_RING,
                        'columns_per_ring': columns, 'samples_per_column': samples,
                        'dxf_geometry_sha256': hashlib.sha256(geometry_path.read_bytes()).hexdigest(),
                        'conditions_sha256': hashlib.sha256(conditions_path.read_bytes()).hexdigest(),
                        'missing_outline_width_percent': missing_outline},
        'quality': {'unknown_equivalent_rings': sum(r.get('UNRESOLVED', 0)/100 for r in rings.values()),
                    'unknown_over_10_percent': [r for r, v in rings.items() if v.get('UNRESOLVED', 0) > 10]},
        'rings': rings,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(payload['quality']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--dxf-geometry', required=True, type=Path)
    parser.add_argument('--conditions-json', required=True, type=Path, help='Ring-to-engineering-condition-code-list snapshot')
    parser.add_argument('--dependencies', required=True)
    parser.add_argument('--columns', type=int, default=32)
    parser.add_argument('--samples', type=int, default=1024)
    parser.add_argument('--rings', type=int, nargs='+', help='Optional selected rings for convergence checks')
    args = parser.parse_args()
    if args.columns < 8 or args.samples < 256:
        parser.error('Use at least 8 columns and 256 vertical samples')
    sys.path.insert(0, args.dependencies)
    extract(args.pdf, args.output, args.dxf_geometry, args.conditions_json, args.columns, args.samples, args.rings)
