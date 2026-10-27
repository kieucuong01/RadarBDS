"""Rebuild navigation windows from captured public administrative source files."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]


def regions(districts, wards):
    districts = {str(d['maQuanHuyen']): d['tenQuanHuyen'] for d in districts
                 if str(d['maQuanHuyen']) in {str(n) for n in range(718, 727)}}
    result = []
    for ward in wards:
        district = str(ward['maQuanHuyen'])
        if district not in districts:
            continue
        shape = ward['shape']
        transformer = Transformer.from_crs(shape['spatialReference']['wkt'], 4326, always_xy=True)
        points = [transformer.transform(*p[:2]) for ring in shape['rings'] for p in ring]
        west, south = min(p[0] for p in points), min(p[1] for p in points)
        east, north = max(p[0] for p in points), max(p[1] for p in points)
        if not (106.25 < west < east < 107.1 and 10.75 < south < north < 11.65):
            raise ValueError('Administrative navigation window outside supported region')
        name = re.sub(r'^(Phường|Xã|Thị trấn)\s+', '', ward['tenPhuongXa']).replace('Hoà', 'Hòa')
        result.append({'code': str(ward['maPhuongXa']), 'ward': name, 'city': districts[district],
                       'district': district, 'bounds': [[south, west], [north, east]],
                       'center': [(south+north)/2, (west+east)/2]})
    if len(result) != 91 or len({r['code'] for r in result}) != 91 or len(districts) != 9:
        raise ValueError('Expected all 91 historic units in nine districts')
    return sorted(result, key=lambda r: (r['district'], r['code']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures', type=Path, default=ROOT/'.local/planning-expansion')
    parser.add_argument('--output', type=Path, default=ROOT/'config/planning_regions.json')
    args = parser.parse_args()
    areas = regions(*[json.loads((args.captures/name).read_text(encoding='utf8'))
                      for name in ('districts.json', 'wards.json')])
    result = {'source': 'https://gisxaydung.tphcm.gov.vn/tracuuttqh',
              'captured_on': datetime.now(timezone.utc).date().isoformat(),
              'navigation_geometry': 'Reference bounding windows from official historic administrative polygons, '
                  'transformed from source WKT with pyproj; not a cadastral mask or survey accuracy claim.',
              'areas': areas}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print('Verified 91 navigation windows:', args.output)


if __name__ == '__main__':
    main()
