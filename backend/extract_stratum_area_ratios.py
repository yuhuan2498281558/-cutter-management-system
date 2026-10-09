"""DXF candidate geometry generator (not the final home-map ratio importer).

Its raw overlap / gap ratios are diagnostic only: use extract_pdf_stratum_ratios
to verify visible classes against the home PDF before importing business data.
Run only with the approved horizontal-layer model.
"""
import argparse
import collections
import hashlib
import json
import math
import re
import sys
from pathlib import Path


def circular_area_integral(y, center, radius):
    """Antiderivative of the horizontal chord width of a circle."""
    if radius <= 0:
        raise ValueError('Circle radius must be positive')
    z = max(-radius, min(radius, y-center))
    return z*math.sqrt(max(0,radius*radius-z*z))+radius*radius*math.asin(z/radius)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dxf', required=True)
    parser.add_argument('--dependencies', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--samples-dir')
    parser.add_argument('--diameter-m', type=float, required=True,
                        help='Verified diameter in DXF profile vertical units; 13.1 is drawing outline only')
    parser.add_argument('--diameter-source', required=True)
    parser.add_argument('--approve-horizontal-layers', action='store_true', required=True)
    args = parser.parse_args()
    if not math.isfinite(args.diameter_m) or args.diameter_m <= 0:
        raise ValueError('Section diameter must be positive and finite')
    sys.path.insert(0, args.dependencies)
    import ezdxf
    from ezdxf.path import from_hatch_boundary_path
    from shapely.geometry import Polygon, Point, LineString
    doc = ezdxf.readfile(args.dxf)
    model = doc.modelspace()
    polygons = []
    for hatch in model.query('HATCH'):
        if hatch.dxf.pattern_name != 'SOLID':
            continue
        paths = []
        for boundary in hatch.paths.rendering_paths(hatch.dxf.hatch_style):
            path = from_hatch_boundary_path(boundary, hatch.ocs(), elevation=hatch.dxf.elevation.z)
            paths.extend(path.sub_paths() if path.has_sub_paths else [path])
        parts = []
        for path in paths:
            vertices = [(p.x, p.y) for p in path.flattening(.0001)]
            if len(vertices) >= 3:
                polygon = Polygon(vertices)
                if not polygon.is_valid:
                    polygon = polygon.buffer(0)
                parts.append(polygon)
        if not parts:
            continue
        geom = parts[0]
        for part in parts[1:]:
            geom = geom.symmetric_difference(part)
        left, bottom, right, top = geom.bounds
        if left < 1800 or right > 5200 or bottom < 700 or top > 950:
            continue
        key = (hatch.dxf.color, hatch.dxf.get('true_color'))
        polygons.append((key, geom))
    texts = [(e.dxf.text, Point(e.dxf.insert.x, e.dxf.insert.y)) for e in model.query('TEXT')
             if re.fullmatch(r'\(\d+\)\d+(?:-\d+)?', e.dxf.text)]
    votes = collections.defaultdict(collections.Counter)
    for key, geom in polygons:
        for code, point in texts:
            if geom.contains(point):
                votes[key][code] += 1
    print('COLOR_VOTES', json.dumps({str(k):dict(v) for k,v in votes.items()}), flush=True)
    labels = {
        42: ('FILL', '填土、填石'), 41: ('FILL_SAND', '填砂'),
        40: ('FINE_SAND_2_1', '细砂（2）1-2'), 31: ('FINE_SAND_2_5', '细砂（2）5-5'),
        52: ('SILTY_CLAY_2_5', '淤泥质/粉质黏土（2）5'),
        33: ('CLAY_3_3', '黏土（3）3-2'), 30: ('RESIDUAL_SANDY_CLAY', '残积砂质黏性土'),
        11: ('FULL_WEATHERED_ROCK', '全风化岩'),
        221: ('DISINTEGRATED_STRONGLY_WEATHERED_ROCK', '散体状强风化岩'),
        213: ('BLOCKY_STRONGLY_WEATHERED_ROCK', '碎块状强风化岩'),
        8: ('SILTY_CLAY_3_4', '淤泥质黏土（3）4-1'),
        1: ('WEAKLY_WEATHERED_ROCK', '弱风化岩'),
        51: ('MEDIUM_SAND_3_3', '中砂（3）3-3'),
        3: ('UNRESOLVED', '未识别岩层'),
        251: ('CLAY_3_4_2', '黏性土（3）4-2'),
    }
    outlines = [LineString([(p[0],p[1]) for p in e.get_points()]) for e in model.query('LWPOLYLINE')
                if len(e)==391 and 800<e.get_points()[0][1]<900]
    if len(outlines)!=2:
        raise ValueError('Expected two verified profile tunnel outlines')
    # Physical ring edge positions, not offset TEXT insertions; section at each ring midpoint.
    x0 = 2373.793310798698
    rings, details = {}, {}
    for ring in range(1,2801):
        x = x0+ring-.5
        vertical = LineString([(x,700),(x,950)])
        ys = sorted(line.intersection(vertical).y for line in outlines)
        center, radius = sum(ys)/2,args.diameter_m/2
        bottom, top = center-radius,center+radius
        intervals=[]
        for key,geom in polygons:
            if not geom.bounds[0]<=x<=geom.bounds[2]:
                continue
            hit = geom.intersection(LineString([(x,bottom),(x,top)]))
            parts = list(hit.geoms) if hasattr(hit,'geoms') else [hit]
            for part in parts:
                if part.geom_type=='LineString' and part.length>1e-8:
                    intervals.append((part.bounds[1],part.bounds[3],key[0]))
        cuts=sorted({bottom,top,*[y for a,b,c in intervals for y in (a,b)]})
        areas=collections.defaultdict(float)
        unknown=0
        for a,b in zip(cuts,cuts[1:]):
            active={color for lo,hi,color in intervals if lo-1e-8<=(a+b)/2<=hi+1e-8}
            area=100*(circular_area_integral(b,center,radius)-circular_area_integral(a,center,radius))/(math.pi*radius*radius)
            if len(active)==1:
                code=labels[next(iter(active))][0]
                if code=='UNRESOLVED':
                    unknown+=area
                else:
                    areas[code]+=area
            else:
                unknown+=area
        # Gaps and conflicting colors are not silently filled or averaged.
        ratios={code:round(value,6) for code,value in areas.items() if value>1e-7}
        if round(unknown,6)>0:
            ratios['UNRESOLVED']=round(unknown,6)
        if ratios:
            largest=max(ratios,key=ratios.get)
            ratios[largest]=round(ratios[largest]+100-sum(ratios.values()),6)
        rings[str(ring)]=ratios
        details[str(ring)]={'x':x,'bottom':bottom,'top':top,'unresolved_percent':unknown}
    # Save geometry independently of final classification for review.
    geometry = {'source_sha256': hashlib.sha256(Path(args.dxf).read_bytes()).hexdigest(),
                'colors': {str(k):dict(v) for k,v in votes.items()},
                'polygons': [{'color': key, 'geometry': geom.__geo_interface__} for key,geom in polygons],
                'measurement_kind':'cross_section_area_percent',
                'source':Path(args.dxf).name,
                'method':f'图示断面估算：DXF SOLID区域，层界横向水平延伸，环段中点圆弓积分；直径来源：{args.diameter_source}',
                'estimated':True,'labels':{**{code:label for code,label in labels.values()},'UNRESOLVED':'未识别岩层'},
                'calibration':{'ring0_edge_x':x0,'x_per_ring':1,'ring_width_m':2,
                               'drawing_outline_diameter':13.1,'section_diameter_m':args.diameter_m,
                               'vertical_units_per_m':1.0,
                               'diameter_source':args.diameter_source},
                'rings':rings,'sections':details}
    Path(args.output).write_text(json.dumps(geometry, ensure_ascii=False), encoding='utf-8')
    artifact = {key:value for key,value in geometry.items() if key not in ('polygons','sections','colors')}
    artifact['quality']={'complete_rings':sum('UNRESOLVED' not in r for r in rings.values()),
                         'incomplete_rings':sum('UNRESOLVED' in r for r in rings.values()),
                         'unknown_equivalent_rings':sum(r.get('UNRESOLVED',0)/100 for r in rings.values())}
    Path(args.output).with_name('stratum-area-ratios.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.samples_dir:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon as PlotPolygon
        from ezdxf.colors import int2rgb, aci2rgb
        samples=Path(args.samples_dir)
        samples.mkdir(parents=True,exist_ok=True)
        for ring in (1,100,300,400,487,1000,2000,2800):
            section=details[str(ring)]
            x,bottom,top=section['x'],section['bottom'],section['top']
            fig,ax=plt.subplots(figsize=(10,4))
            for key,geom in polygons:
                if geom.bounds[2]<x-12 or geom.bounds[0]>x+12:continue
                color=tuple(c/255 for c in (int2rgb(key[1]) if key[1] else aci2rgb(key[0])))
                parts=list(geom.geoms) if hasattr(geom,'geoms') else [geom]
                for part in parts:
                    ax.add_patch(PlotPolygon(list(part.exterior.coords),facecolor=color,edgecolor='none'))
                    for interior in part.interiors:
                        ax.add_patch(PlotPolygon(list(interior.coords),facecolor='white',edgecolor='none'))
            for line in outlines:
                ax.plot(*line.xy,color='#006400',linewidth=1.2,label='Drawing outline' if line is outlines[0] else None)
            ax.plot([x,x],[bottom,top],color='black',linewidth=1.4)
            ax.set_xlim(x-12,x+12);ax.set_ylim(bottom-3,top+3)
            ax.set_title(f'Ring {ring}; D={args.diameter_m} m; unknown {section["unresolved_percent"]:.6f}%; horizontal-layer estimate')
            ax.set_xlabel('DXF x');ax.set_ylabel('DXF profile y')
            fig.tight_layout();fig.savefig(samples/f'ring-{ring}.png',dpi=160);plt.close(fig)
    print('POLYGONS', len(polygons), flush=True)
    print('RESOLVED_RINGS',sum('UNRESOLVED' not in r for r in rings.values()),flush=True)


if __name__ == '__main__':
    main()
