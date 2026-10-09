"""Produce a review queue, never invent cross-section areas from line segments."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source = Path(args.source)
    raw = source.read_bytes()
    payload = json.loads(raw.decode('utf-8-sig'))
    rings = payload['rings']
    result = {
        'source': str(source),
        'source_sha256': hashlib.sha256(raw).hexdigest(),
        'drawing': payload.get('source'),
        'status': 'requires_cross_section_geometry',
        'ring_count': len(rings),
        'known_area_ratio_rings': 0,
        'method': 'Audit existing longitudinal engineering-zone labels; no area inference.',
        'missing_requirements': [
            'Verified station-to-ring and elevation scales for the displayed drawing',
            'Tunnel excavation circle and lithology boundary geometry at every ring',
            'Transverse geometry or explicitly approved laterally-horizontal model',
            'Mutually exclusive lithology codes; engineering risk zones can overlap',
        ],
        'rings': {ring: {
            'engineering_zone_codes': codes,
            'stratum_type_ratios': {},
            'status': 'not_extracted',
        } for ring, codes in sorted(rings.items(), key=lambda item: int(item[0]))},
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(f'Inspected {len(rings)} rings; 0 verified area ratios; review queue: {output}')


if __name__ == '__main__':
    main()
