"""Estimate circular sections from the exact PDF displayed on the home page.

The PDF's visible fills / soft masks are authoritative: the DXF has overlapping
and self-intersecting hatches which do not reproduce this PDF. Text, boreholes
and outline strokes are excluded, never interpolated into geological classes.
This is an offline extraction utility, not a server dependency.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import fitz
import numpy as np

PDF_SHA256 = 'cb7b79b71e2f8098175539424087b9d601baee067709d230f40c59277abd5c0e'
START_X = 1165.117010888432
X_PER_RING = 2.8318711705290296
DXF_COLORS = {
    42: 'FILL', 41: 'FILL_SAND', 40: 'FINE_SAND_2_1', 31: 'FINE_SAND_2_5',
    52: 'SILTY_CLAY_2_5', 33: 'CLAY_3_3', 30: 'RESIDUAL_SANDY_CLAY',
    11: 'FULL_WEATHERED_ROCK', 221: 'DISINTEGRATED_STRONGLY_WEATHERED_ROCK',
    213: 'BLOCKY_STRONGLY_WEATHERED_ROCK', 8: 'SILTY_CLAY_3_4',
    1: 'WEAKLY_WEATHERED_ROCK', 51: 'MEDIUM_SAND_3_3', 3: 'UNRESOLVED', 251: 'CLAY_3_4_2',
}
LEGEND = [
    ('FILL', (9198, 320)), ('FILL_SAND', (9198, 338)),
    ('FINE_SAND_2_1', (9198, 372)), ('SILTY_CLAY_2_5', (9198, 390)),
    ('SILTY_CLAY_2_5', (9300, 320)), ('FINE_SAND_2_5', (9300, 338)),
    ('CLAY_3_3', (9300, 355)), ('MEDIUM_SAND_3_3', (9300, 372)),
    ('SILTY_CLAY_3_4', (9300, 390)), ('RESIDUAL_SANDY_CLAY', (9400, 320)),
    ('FULL_WEATHERED_ROCK', (9400, 338)),
    ('DISINTEGRATED_STRONGLY_WEATHERED_ROCK', (9400, 355)),
    ('BLOCKY_STRONGLY_WEATHERED_ROCK', (9400, 372)),
    ('WEAKLY_WEATHERED_ROCK', (9400, 390)),
]


def classify_colors(pixels, legend, tolerance=20, margin=8):
    """Require a separated best geological class; close colors stay unknown."""
    codes = sorted({code for code, _ in legend})
    scores = []
    for code in codes:
        prototypes = np.array([rgb for c, rgb in legend if c == code], dtype=float)
        scores.append(np.abs(pixels[..., None, :] - prototypes).max(axis=-1).min(axis=-1))
    scores = np.stack(scores, axis=-1)
    nearest = scores.argmin(axis=-1)
    ranked = np.sort(scores, axis=-1)
    accepted = (ranked[..., 0] <= tolerance) & (ranked[..., 1] - ranked[..., 0] >= margin)
    return np.where(accepted, nearest, len(codes)), codes + ['UNRESOLVED']


def chord_weights(samples):
    """Exact circular area of each horizontal sampling strip, summing to 100."""
    edges = np.linspace(-1, 1, samples + 1)
    primitive = edges * np.sqrt(np.maximum(0, 1 - edges**2)) + np.arcsin(edges)
    return np.diff(primitive) / math.pi * 100


def constrain_classes(classes, codes, candidates):
    eligible = [j for j, c in enumerate(codes) if c in candidates or c == 'UNRESOLVED']
    return np.where(np.isin(classes, eligible), classes, codes.index('UNRESOLVED'))


def hybrid_bands(section, polygons, pdf_top, pdf_bottom, classes, codes):
    """Use exact DXF bands only when their interiors AND edges match the PDF.

    No competing color or unknown interior is accepted. Boundary tolerance is
    one native PDF raster pixel (0.18pt), not a general gap-filling distance.
    """
    from shapely.geometry import LineString
    x, lo, hi = section['x'], section['bottom'], section['top']
    hits = []
    for color, geom in polygons:
        if not geom.bounds[0] <= x <= geom.bounds[2]:
            continue
        for part in line_parts(geom.intersection(LineString([(x, lo), (x, hi)]))):
            hits.append((part.bounds[1], part.bounds[3], DXF_COLORS[color]))
    cuts = sorted({lo, hi, *[y for a, b, _ in hits for y in (a, b)]})
    bands = []
    for a, b in zip(cuts, cuts[1:]):
        active = {c for l, h, c in hits if l <= (a+b)/2 <= h}
        code = next(iter(active)) if len(active) == 1 else 'UNRESOLVED'
        if bands and bands[-1][2] == code:
            bands[-1][1] = b
        else:
            bands.append([a, b, code])
    step = (pdf_bottom-pdf_top) / len(classes)
    sample_y = pdf_top + (np.arange(len(classes)) + .5) * step
    accepted = []
    for a, b, code in bands:
        if code == 'UNRESOLVED' or code not in codes:
            continue
        top = pdf_top + (hi-b)/(hi-lo)*(pdf_bottom-pdf_top)
        bottom = pdf_top + (hi-a)/(hi-lo)*(pdf_bottom-pdf_top)
        if bottom-top <= .36:
            continue
        index = codes.index(code)
        interior = (sample_y > top+.18) & (sample_y < bottom-.18)
        if not interior.any() or not np.all(classes[interior] == index):
            continue
        # A transition farther than a native pixel from the candidate edge
        # contradicts the proposed exact boundary, even if the interior agrees.
        boundary_ok = True
        for y, direction in ((top, -1), (bottom, 1)):
            if abs(y-pdf_top) < 1e-8 or abs(y-pdf_bottom) < 1e-8:
                continue
            outside = y + direction*(.18+step)
            j = int((outside-pdf_top)/step)
            if not 0 <= j < len(classes) or classes[j] in (index, codes.index('UNRESOLVED')):
                boundary_ok = False
        if boundary_ok:
            accepted.append((top, bottom, code))
    return accepted


def integrate_hybrid(classes, codes, top, bottom, accepted):
    """Integrate PDF strips, split exactly where verified DXF boundaries cross."""
    n = len(classes)
    base = np.linspace(top, bottom, n+1)
    cuts = np.unique(np.r_[base, [v for a, b, _ in accepted for v in (a, b)]])
    mid = (cuts[:-1] + cuts[1:])/2
    indices = np.clip(((mid-top)/(bottom-top)*n).astype(int), 0, n-1)
    chosen = classes[indices].copy()
    verified = np.zeros(len(chosen), dtype=bool)
    for a, b, code in accepted:
        inside = (mid >= a) & (mid <= b)
        chosen[inside] = codes.index(code)
        verified |= inside
    z = np.clip((cuts-(top+bottom)/2)/((bottom-top)/2), -1, 1)
    f = z*np.sqrt(np.maximum(0, 1-z*z))+np.arcsin(z)
    weights = np.diff(f)/math.pi*100
    areas = np.bincount(chosen, weights=weights, minlength=len(codes))
    return areas, float(weights[verified].sum())


def path_geometry(drawing):
    from shapely.geometry import Polygon, LineString
    from shapely.ops import unary_union, polygonize
    parts, points = [], []

    def close():
        if len(points) >= 3:
            poly = Polygon(points)
            if poly.is_valid and poly.area < 1e-10:
                return
            if not poly.is_valid:
                # Export paths can traverse an edge forward and backward. Split
                # them into faces and evaluate PDF's nonzero winding rule,
                # rather than buffer(0), whose self-intersection semantics differ.
                closed = points + [points[0]]
                faces = polygonize(unary_union([LineString([a, b])
                    for a, b in zip(closed, closed[1:]) if a != b]))
                selected = []
                for face in faces:
                    q = face.representative_point()
                    winding = 0
                    for (ax, ay), (bx, by) in zip(closed, closed[1:]):
                        side = (bx-ax)*(q.y-ay)-(q.x-ax)*(by-ay)
                        if ay <= q.y < by and side > 0:
                            winding += 1
                        elif by <= q.y < ay and side < 0:
                            winding -= 1
                    if winding:
                        selected.append(face)
                poly = unary_union(selected)
            parts.append(poly)

    for op, *p in drawing['items']:
        if op != 'l':
            raise ValueError(f'Unreviewed PDF path operator {op}')
        a, b = tuple(p[0]), tuple(p[1])
        if points and points[-1] != a:
            close()
            points = []
        if not points:
            points.append(a)
        points.append(b)
    close()
    if not parts:
        return Polygon()  # Degenerate zero-area export triangles do not paint.
    # This pinned PDF contains nonzero-winding solid triangles / quads only.
    if drawing.get('even_odd') or drawing.get('fill_opacity') != 1:
        raise ValueError('Unreviewed PDF fill rule / opacity')
    return unary_union(parts)


def line_parts(geometry):
    if geometry.geom_type == 'LineString':
        if geometry.length > 0:
            yield geometry
    elif hasattr(geometry, 'geoms'):
        for part in geometry.geoms:
            yield from line_parts(part)


def prepare_pdf(source):
    """Read pinned source once for repeated bounded-memory sampling batches."""
    from shapely.ops import unary_union
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != PDF_SHA256:
        raise ValueError('PDF changed: recalibrate ring axis and verify its legend before extracting')
    doc = fitz.open(source)
    page = doc[0]
    drawings = page.get_drawings()
    green = [path_geometry(d) for d in drawings
             if d.get('layer') == 'Prof_GradeLine' and tuple(d.get('fill') or ()) == (0, 1, 0)]
    outline = unary_union(green)
    legend = []
    for code, (x, y) in LEGEND:
        pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=fitz.Rect(x, y, x+1, y+1), alpha=False)
        values = np.frombuffer(pix.samples, dtype=np.uint8).reshape(-1, 3)
        legend.append((code, np.median(values, axis=0).tolist()))
    infos = page.get_image_info(xrefs=True)
    image_seq = [i for i, b in enumerate(page.get_bboxlog()) if b[0] == 'fill-image']
    if len(infos) != len(image_seq):
        raise ValueError('Image / display-list mismatch')
    refs = {ref[0]: ref for ref in page.get_images()}
    return doc, drawings, outline, legend, infos, image_seq, refs, digest


def sample_pdf_columns(source, xs, samples, prepared=None):
    """Composite geological fills at explicit PDF x coordinates (no area weighting)."""
    from shapely.geometry import LineString
    doc, drawings, outline, legend, infos, image_seq, refs, digest = prepared or prepare_pdf(source)
    edges = []
    for x in xs:
        bands = sorted((p.bounds[1], p.bounds[3]) for p in line_parts(
            outline.intersection(LineString([(x, 300), (x, 490)]))))
        if len(bands) != 2:
            raise ValueError(f'Expected two outline strokes at x={x}: {bands}')
        edges.append([sum(b) / 2 for b in bands])
    edges = np.asarray(edges)
    fractions = (np.arange(samples) + .5) / samples
    ys = edges[:, 0, None] + np.diff(edges, axis=1) * fractions
    rgb = np.full((len(xs), samples, 3), 255, dtype=np.float32)
    # Native PDF sequence numbers preserve the order of vector and raster fills.
    events = []
    min_y, max_y = ys.min(), ys.max()
    for d in drawings:
        fill = d.get('fill')
        if not fill or fill[0] < .1 or d.get('layer') == 'Prof_GradeLine':
            continue
        x0, y0, x1, y1 = d['rect']
        if x1 >= xs[0] and x0 <= xs[-1] and y1 >= min_y and y0 <= max_y:
            events.append((d['seqno'], 'vector', d))
    for seq, info in zip(image_seq, infos):
        x0, y0, x1, y1 = info['bbox']
        if refs[info['xref']][1] and x1 >= xs[0] and x0 <= xs[-1] and y1 >= min_y and y0 <= max_y:
            events.append((seq, 'image', info))
    # Cache extrema: recomputing over all samples for each fill is unnecessary.
    for _, kind, data in sorted(events, key=lambda e: e[0]):
        if kind == 'vector':
            geom = path_geometry(data)
            if geom.is_empty:
                continue
            x0, _, x1, _ = geom.bounds
            color = np.asarray(data['fill']) * 255
            for i in range(np.searchsorted(xs, x0), np.searchsorted(xs, x1, side='right')):
                hit = geom.intersection(LineString([(xs[i], edges[i, 0]), (xs[i], edges[i, 1])]))
                for part in line_parts(hit):
                    lo = np.searchsorted(ys[i], part.bounds[1])
                    hi = np.searchsorted(ys[i], part.bounds[3], side='right')
                    rgb[i, lo:hi] = color
        else:
            a, b, c, d, tx, ty = data['transform']
            if b != 0 or c != 0 or a <= 0 or d <= 0:
                raise ValueError('Unreviewed image transform')
            xref = data['xref']
            pix = fitz.Pixmap(doc, xref)
            mask = fitz.Pixmap(doc, refs[xref][1])
            if pix.n != 3 or mask.n != 1 or (pix.width, pix.height) != (mask.width, mask.height):
                raise ValueError('Unexpected image colorspace or soft-mask dimensions')
            colors = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            alpha = np.frombuffer(mask.samples, dtype=np.uint8).reshape(pix.height, pix.width)
            for i in range(np.searchsorted(xs, tx), np.searchsorted(xs, tx+a, side='right')):
                valid = (ys[i] >= ty) & (ys[i] < ty+d)
                iy = ((ys[i, valid]-ty) / d * pix.height).astype(int)
                ix = min(pix.width-1, int((xs[i]-tx) / a * pix.width))
                opacity = alpha[iy, ix, None].astype(float) / 255
                # RGB is unassociated: apply soft mask exactly once.
                rgb[i, valid] = colors[iy, ix] * opacity + rgb[i, valid] * (1-opacity)
    if prepared is None:
        doc.close()
    return rgb, edges, legend, digest


def extract(source, output, samples=8192, dxf_geometry=None):
    from shapely.geometry import LineString, shape
    from application.shield.stratum_ratios import STRATUM_LABELS
    xs = START_X + (np.arange(1, 2801) - .5) * X_PER_RING
    rgb, edges, legend, digest = sample_pdf_columns(source, xs, samples)
    print(f'Composited PDF fills at {samples} samples/section', flush=True)
    weights = chord_weights(samples)
    geometry = None
    if dxf_geometry:
        geometry = json.loads(dxf_geometry.read_text(encoding='utf-8'))
        if geometry['source_sha256'] != '138b0fa7bca488440e3923e41115590c9f270a3c0fa420b63e105195f43a86b5':
            raise ValueError('Unreviewed DXF geometry source')
        if geometry['calibration']['section_diameter_m'] != 13.1 or len(geometry['sections']) != 2800:
            raise ValueError('Unreviewed DXF circle calibration')
        polygons = [(p['color'][0], shape(p['geometry'])) for p in geometry['polygons']]
    rings, sections = {}, {}
    for i in range(2800):
        classes, codes = classify_colors(rgb[i], legend)
        if geometry:
            # JPEG / alpha blending can accidentally resemble an unrelated
            # legend swatch (e.g. sand + clay edges resembling artificial fill).
            # Require geological evidence in this DXF section before accepting
            # a PDF color. A missing class stays unknown, never relabelled as the
            # next-nearest swatch. Overlapping candidates remain eligible.
            s = geometry['sections'][str(i+1)]
            column = LineString([(s['x'], s['bottom']-.07), (s['x'], s['top']+.07)])
            candidates = {DXF_COLORS[color] for color, poly in polygons
                if poly.bounds[0] <= s['x'] <= poly.bounds[2] and poly.intersects(column)}
            classes = constrain_classes(classes, codes, candidates)
        areas = np.bincount(classes, weights=weights, minlength=len(codes))
        verified_area, accepted = 0, []
        if geometry:
            accepted = hybrid_bands(geometry['sections'][str(i+1)], polygons,
                *edges[i], classes, codes)
            areas, verified_area = integrate_hybrid(classes, codes, *edges[i], accepted)
        ratios = {code: round(float(value), 6) for code, value in zip(codes, areas) if round(float(value), 6) > 0}
        largest = max(ratios, key=ratios.get)
        ratios[largest] = round(ratios[largest] + 100 - sum(ratios.values()), 6)
        rings[str(i+1)] = ratios
        changes = np.r_[0, np.flatnonzero(np.diff(classes)) + 1, samples]
        sections[str(i+1)] = {'x': float(xs[i]), 'top': float(edges[i, 0]), 'bottom': float(edges[i, 1]),
            'verified_dxf_area_percent': verified_area, 'verified_dxf_bands': accepted,
            'bands': [[int(a), int(b), codes[classes[a]]] for a, b in zip(changes, changes[1:])]}
    payload = {'measurement_kind': 'cross_section_area_percent', 'estimated': True,
        'source': source.name, 'source_sha256': digest,
        'method': '首页PDF实际彩色填充与透明蒙版合成；排除独立文本线条；图例唯一近色识别并要求本环DXF候选岩性佐证，异色不强行归类；仅内部岩性及双边界均与PDF一致时沿用DXF精确单色层界；层界横向水平延伸；每环中点圆弓面积估算；不能辨认的面积保留UNRESOLVED',
        'labels': {c: STRATUM_LABELS[c] for c in codes},
        'calibration': {'ring0_edge_x': START_X, 'x_per_ring': X_PER_RING,
            'ring_width_m': 2, 'drawing_outline_diameter': 13.1, 'section_diameter_m': 13.1,
            'diameter_source': '设计纵断面上下轮廓间距，非实测开挖直径',
            'samples_per_section': samples, 'color_tolerance': 20, 'color_class_margin': 8,
            'verified_dxf_boundary_tolerance_pdf_pt': .18 if geometry else None,
            'dxf_candidate_vertical_margin': .07 if geometry else None,
            'dxf_geometry_sha256': hashlib.sha256(dxf_geometry.read_bytes()).hexdigest() if geometry else None,
            'rounding_note': '存储小数用于合计一致，不代表测量精度；原PDF栅格约0.18pt/像素，圆心附近单边界1像素约0.62个百分点'},
        'quality': {'complete_rings': sum('UNRESOLVED' not in v for v in rings.values()),
            'incomplete_rings': sum('UNRESOLVED' in v for v in rings.values()),
            'unknown_equivalent_rings': sum(v.get('UNRESOLVED', 0)/100 for v in rings.values())},
        'rings': rings}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    output.with_name(f'{output.stem}-sections.json').write_text(json.dumps(
        {'samples': samples, 'legend': legend, 'sections': sections}, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(payload['quality']), flush=True)
    for ring in ('300', '400', '487', '2077', '2213', '2735', '2760'):
        print(ring, rings[ring], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--dependencies', required=True)
    parser.add_argument('--samples', type=int, default=8192)
    parser.add_argument('--dxf-geometry', type=Path)
    args = parser.parse_args()
    if args.samples < 256:
        parser.error('At least 256 vertical samples are required')
    sys.path.insert(0, args.dependencies)
    extract(args.pdf, args.output, args.samples, args.dxf_geometry)
