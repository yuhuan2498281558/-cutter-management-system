"""Per-ring area aggregation into the six project classes from annotated strata.

This is an explicit project aggregation, not a replacement geological assessment
of the engineering segment. Raw lithologies and masks are retained for audit.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
from extract_pdf_stratum_ratios import (
    START_X, X_PER_RING, DXF_COLORS, prepare_pdf, sample_pdf_columns,
    classify_colors, constrain_classes, LEGEND,
)

SCHEME = 'annotated_substrata_area_v5'
DXF_SHA = '138b0fa7bca488440e3923e41115590c9f270a3c0fa420b63e105195f43a86b5'
DXF_START = 2373.793310798698
CHILD_CLASSES = {
    'CLAY_3_3': 'AREA_CLAY_SAND', 'CLAY_3_4_2': 'AREA_CLAY_SAND',
    'CLAY_2_5_4': 'AREA_CLAY_SAND',
    'FINE_SAND_2_1': 'AREA_CLAY_SAND', 'FINE_SAND_2_5': 'AREA_CLAY_SAND',
    'MEDIUM_SAND_3_3': 'AREA_CLAY_SAND', 'RESIDUAL_SANDY_CLAY': 'AREA_CLAY_SAND',
    'FILL_SAND': 'AREA_CLAY_SAND',  # Original symbol legend: 中砂（填砂）.
    'SILTY_CLAY_2_5': 'AREA_SOFT_SOIL', 'SILTY_CLAY_3_4': 'AREA_SOFT_SOIL',
    'FULL_WEATHERED_ROCK': 'AREA_SOFT_HARD',
    'DISINTEGRATED_STRONGLY_WEATHERED_ROCK': 'AREA_SOFT_HARD',
    'BLOCKY_STRONGLY_WEATHERED_ROCK': 'AREA_SOFT_HARD',
    'WEAKLY_WEATHERED_ROCK': 'AREA_WEAK_GRANITE',
    'UNRESOLVED': 'UNRESOLVED',
}


def aggregate_samples(classes, codes, weights, boulder_mask, bedrock_mask):
    """One sample contributes to exactly one parent; unknown is never normalized."""
    keys = [CHILD_CLASSES.get(code, 'OTHER_IDENTIFIED') for code in codes]
    chosen = np.asarray(keys, dtype=object)[classes]
    weak = classes == codes.index('WEAKLY_WEATHERED_ROCK') if 'WEAKLY_WEATHERED_ROCK' in codes else np.zeros(classes.shape, dtype=bool)
    chosen[weak & bedrock_mask] = 'AREA_BEDROCK_PROTRUSION'
    chosen[boulder_mask] = 'AREA_BOULDER'
    result = {code: round(float(weights[chosen == code].sum() / weights.sum() * 100), 6)
              for code in np.unique(chosen)}
    largest = max(result, key=result.get)
    result[largest] = round(result[largest] + 100 - sum(result.values()), 6)
    return {k: v for k, v in result.items() if v > 0}


def annotated_geometry(dxf_path):
    import ezdxf
    from shapely.geometry import Polygon, Point
    from shapely.ops import unary_union
    if hashlib.sha256(dxf_path.read_bytes()).hexdigest() != DXF_SHA:
        raise ValueError('DXF differs from reviewed legend/annotations')
    doc = ezdxf.readfile(dxf_path)
    labels = [e for e in doc.modelspace().query('MTEXT')
              if e.dxf.layer == '03-孤石引线' and e.dxf.insert.y > 700
              and e.plain_text().strip() == '孤石']
    boulders, evidence = [], []
    for e in doc.modelspace().query('ELLIPSE'):
        center, major, ratio = e.dxf.center, e.dxf.major_axis, e.dxf.ratio
        if not (2373 < center.x < 5174 and 790 < center.y < 910 and e.dxf.color == 0):
            continue
        if abs(e.dxf.end_param - e.dxf.start_param - 2*math.pi) > 1e-6:
            raise ValueError('Unreviewed open boulder contour')
        # Analytic sampling handles negative start parameters that the DXF
        # flattening utility can otherwise return as an empty polygon.
        angles = np.linspace(0, 2*math.pi, 1025)
        poly = Polygon(np.c_[center.x + major.x*np.cos(angles)-major.y*ratio*np.sin(angles),
                             center.y + major.y*np.cos(angles)+major.x*ratio*np.sin(angles)])
        distance, label = min((poly.distance(Point(t.dxf.insert.x, t.dxf.insert.y)), t.dxf.handle)
                              for t in labels)
        # Grey (ACI253) lenticular lithology outlines have no boulder label;
        # only the pinned black complete ellipses with nearby boulder annotation qualify.
        if not poly.is_valid or distance > 12:
            raise ValueError(f'Boulder contour {e.dxf.handle} needs annotation review')
        boulders.append(poly)
        evidence.append({'handle': e.dxf.handle, 'label_handle': label,
                         'annotation_distance': distance, 'bounds': list(poly.bounds)})
    # Reviewed main bedrock protrusion spans; they constrain only weak-rock
    # pixels, never the whole height of a ring or any soil/weathered pixels.
    bedrock = []
    for handle in ('102F2F', '102F43', '102F4B'):
        points = doc.entitydb[handle].paths[0].vertices
        bedrock.append((min(p[0] for p in points), max(p[0] for p in points)))
    return unary_union(boulders), bedrock, evidence


def extract(args):
    from shapely.geometry import box, shape
    from shapely import contains_xy
    geometry = json.loads(args.geometry.read_text(encoding='utf-8'))
    if geometry['source_sha256'] != DXF_SHA:
        raise ValueError('Unreviewed lithology candidate geometry')
    candidates = [(DXF_COLORS[p['color'][0]], shape(p['geometry'])) for p in geometry['polygons']]
    boulders, bedrock, evidence = annotated_geometry(args.dxf)
    axis = np.array([geometry['sections'][str(n)]['x'] for n in range(1,2801)])
    tops = np.array([geometry['sections'][str(n)]['top'] for n in range(1,2801)])
    prepared = prepare_pdf(args.pdf)
    # The legacy rock summary merged (2)5-4 silty CLAY and (2)5-2 muddy clay.
    # The original legend gives separate fills; only the muddy material belongs
    # to the soft-soil aggregate. Preserve the legacy extractor for its callers.
    for i, (_, position) in enumerate(LEGEND):
        if position == (9300, 320):
            prepared[3][i] = ('CLAY_2_5_4', prepared[3][i][1])
    rings, raw_rings, boulder_hits = {}, {}, []
    numbers = sorted(set(args.rings or range(1, 2801)))
    if not numbers or min(numbers) < 1 or max(numbers) > 2800:
        raise ValueError('Ring outside calibrated range')
    try:
        for start in range(0, len(numbers), 100):
            batch = numbers[start:start+100]
            left = START_X + (np.asarray(batch)-1)*X_PER_RING
            covered = np.minimum(left+X_PER_RING, prepared[2].bounds[2])-left
            xs = left[:, None] + covered[:, None]*(np.arange(args.columns)+.5)/args.columns
            rgb, edges, legend, digest = sample_pdf_columns(args.pdf, xs.ravel(), args.samples, prepared)
            for i, ring in enumerate(batch):
                lo, hi = i*args.columns, (i+1)*args.columns
                classes, codes = classify_colors(rgb[lo:hi], legend)
                section = geometry['sections'][str(ring)]
                nearby = [geometry['sections'][str(n)] for n in (max(1,ring-1),ring,min(2800,ring+1))]
                bounds = box(section['x']-.5,min(s['bottom'] for s in nearby)-.07,
                             section['x']+.5,max(s['top'] for s in nearby)+.07)
                eligible = {c for c,p in candidates if p.intersects(bounds)}
                if 'SILTY_CLAY_2_5' in eligible:
                    eligible.add('CLAY_2_5_4')
                classes = constrain_classes(classes,codes,eligible)
                weights = np.broadcast_to(np.diff(edges[lo:hi],axis=1)*covered[i]/args.columns/args.samples,classes.shape).copy()
                dx = DXF_START+(xs[i]-START_X)/X_PER_RING
                # Both sources share the physical ring axis. The local DXF
                # outline elevation interpolates continuously through ring centers.
                dy_top = np.interp(dx,axis,tops)
                dy = dy_top[:,None]-13.1*(np.arange(args.samples)+.5)/args.samples
                bm = contains_xy(boulders,dx[:,None],dy)
                pm = np.zeros(classes.shape,dtype=bool)
                for a,b in bedrock:
                    pm |= np.broadcast_to(((dx>=a)&(dx<=b))[:,None],classes.shape)
                missing = X_PER_RING-covered[i]
                if missing > 1e-6:
                    classes = np.vstack([classes,np.full(args.samples,codes.index('UNRESOLVED'))])
                    weights = np.vstack([weights,np.full(args.samples,np.diff(edges[hi-1]).item()*missing/args.samples)])
                    bm = np.vstack([bm,np.zeros(args.samples,dtype=bool)])
                    pm = np.vstack([pm,np.zeros(args.samples,dtype=bool)])
                rings[str(ring)] = aggregate_samples(classes,codes,weights,bm,pm)
                raw_rings[str(ring)] = {code:round(float(weights[classes==j].sum()/weights.sum()*100),6)
                                        for j,code in enumerate(codes) if np.any(classes==j)}
                if np.any(bm): boulder_hits.append(ring)
            print(f'Classified {batch[0]}-{batch[-1]}',flush=True)
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.with_suffix('.partial.json').write_text(json.dumps(
                {'rings':rings,'raw_lithology_rings':raw_rings}),encoding='utf-8')
    finally:
        prepared[0].close()
    payload = {'measurement_kind':'longitudinal_section_area_percent','classification_scheme':SCHEME,
        'estimated':True,'source':args.pdf.name,'source_sha256':digest,'dxf_sha256':DXF_SHA,
        'method':'每环完整纵断面内按原图子岩性面积归并六类；标注孤石轮廓优先，凸起区间内弱岩单列，其他岩性按显式归并表；未知不归一化。',
        'child_classes':CHILD_CLASSES,'bedrock_intervals_dxf':bedrock,'boulder_contours':evidence,
        'calibration':{'columns':args.columns,'samples':args.samples,'dxf_ring0':DXF_START,'pdf_ring0':START_X,'pdf_per_ring':X_PER_RING},
        'quality':{'boulder_rings':boulder_hits,'unallocated_rings':[r for r,v in rings.items() if v.get('OTHER_IDENTIFIED')],
                   'mixed_rings':sum(sum(k.startswith('AREA_') for k in v)>1 for v in rings.values())},
        'rings':rings,'raw_lithology_rings':raw_rings}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(payload['quality']),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('pdf','dxf','geometry','output','dependencies'):
        p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--columns',type=int,default=32)
    p.add_argument('--samples',type=int,default=1024)
    p.add_argument('--rings',type=int,nargs='+')
    args=p.parse_args()
    if args.columns<8 or args.samples<256: p.error('At least 8 columns and 256 samples required')
    sys.path.insert(0,str(args.dependencies.resolve()))
    extract(args)
