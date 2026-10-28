"""Build small historical navigation references, never parcel geometry, from public GIS."""
import argparse
import json
from pathlib import Path
import re
import unicodedata

from pyproj import Transformer


def regions(districts, wards):
    districts = {str(d['maQuanHuyen']): d['tenQuanHuyen'] for d in districts}
    result = []
    for ward in wards:
        code, district = str(ward['maPhuongXa']), str(ward['maQuanHuyen'])
        if not re.fullmatch(r'\d{5}', code) or district not in districts:
            raise ValueError('Unknown source administrative code')
        shape = ward['shape']
        transformer = Transformer.from_crs(shape['spatialReference']['wkt'], 4326, always_xy=True)
        points = [transformer.transform(*p[:2]) for ring in shape['rings'] for p in ring]
        west, south = min(p[0] for p in points), min(p[1] for p in points)
        east, north = max(p[0] for p in points), max(p[1] for p in points)
        if not (106.25 < west < east < 107.65 and 8.5 < south < north < 11.65):
            raise ValueError('Reference window outside expanded HCM')
        name = re.sub(r'^(Phường|Xã|Thị trấn|TT|T\.T)\s+', '', ward['tenPhuongXa'],
                      flags=re.IGNORECASE).replace('Hoà', 'Hòa')
        result.append({'code': code, 'area_id': code, 'ward': unicodedata.normalize('NFC', name),
            'city': unicodedata.normalize('NFC', districts[district]), 'district': district,
            'bounds': [[south, west], [north, east]], 'center': [(south+north)/2, (west+east)/2]})
    if len(result) != 422 or len({r['code'] for r in result}) != 422:
        raise ValueError('Expected all 422 distinct public source references')
    return sorted(result, key=lambda r: (r['district'], r['code']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures', type=Path, default=Path('.local/planning-expansion'))
    parser.add_argument('--output', type=Path, default=Path('config/planning_parcel_areas.json'))
    args = parser.parse_args()
    areas = regions(*[json.loads((args.captures/name).read_text(encoding='utf8'))
                      for name in ('districts.json', 'wards.json')])
    args.output.write_text(json.dumps({'source': 'https://gisxaydung.tphcm.gov.vn/tracuuttqh',
        'reference_only': 'Historical administrative bounding windows; not cadastral masks or confirmed parcel coverage.',
        'areas': areas}, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf8')
    print('Verified', len(areas), 'references')


if __name__ == '__main__':
    main()
