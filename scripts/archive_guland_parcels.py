"""Archive sanitized browser parcel captures; no network, credentials or live-map changes."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sqlite3


SOURCES = {p: 'https://guland.vn/soi-quy-hoach/'+p for p in ('dong-nai', 'binh-phuoc')}
FIELDS = {'captured_at', 'response_status', 'source', 'source_id', 'province_id',
          'district_id', 'ward_id', 'points', 'titles', 'areas', 'landUse', 'plans', 'planning_status'}


def text(value):
    if (not isinstance(value, str) or not 0 < len(value) <= 500
            or re.search(r'[<>\x00-\x08]|Tên chủ|Chủ sử dụng|Số GCN', value, re.I)):
        raise ValueError('Invalid or private reference text')
    return value


def objects(rows, fields, limit):
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError('Invalid reference rows')
    for row in rows:
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError('Unexpected reference fields')
        for value in row.values():
            text(value)
    return rows


def feature_from_capture(data):
    """Retain source vertices and planning labels, without inferring missing planning."""
    from pyproj import Geod
    from shapely.geometry import Polygon, mapping

    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError('Unexpected capture fields; raw HTML and personal fields are not accepted')
    identifier = data['source_id']
    if type(data['response_status']) is not int or data['response_status'] != 1 or type(identifier) is not int or not 0 < identifier < 2**53:
        raise ValueError('Unsuccessful capture or invalid source identifier')
    province = next((p for p, url in SOURCES.items() if data['source'] == url), None)
    if not province:
        raise ValueError('Unsupported source')
    try:
        timestamp = datetime.fromisoformat(data['captured_at'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            raise ValueError('Capture time must include timezone')
        timestamp = timestamp.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError('Invalid capture time') from error
    admin = {k: data[k+'_id'] for k in ('province', 'district', 'ward')}
    if any(not isinstance(v, str) or not re.fullmatch(r'\d{1,12}', v) for v in admin.values()):
        raise ValueError('Invalid source administrative identifier')
    titles = data['titles']
    if not isinstance(titles, list) or not 1 <= len(titles) <= 2:
        raise ValueError('Missing parcel identity')
    for title in titles:
        if not re.search(r'Thửa\s+\S+\s+Tờ\s+\S+', text(title)):
            raise ValueError('Missing sheet/parcel identity')
    areas = data['areas']
    if not isinstance(areas, list) or not 1 <= len(areas) <= 2:
        raise ValueError('Missing source locality')
    for group in areas:
        objects(group, {'name', 'url'}, 3)
        if any(not any(a['url'] == url or a['url'].startswith(url+'/') for url in SOURCES.values()) for a in group):
            raise ValueError('Invalid locality link')
    if not any(a['url'] == SOURCES[province] or a['url'].startswith(SOURCES[province]+'/') for a in areas[-1]):
        raise ValueError('Historic province does not match source locality')
    land_use = objects(data['landUse'], {'code', 'area', 'label'}, 50)
    plans = data['plans']
    if not isinstance(plans, list) or len(plans) > 20:
        raise ValueError('Invalid planning sections')
    for plan in plans:
        if not isinstance(plan, dict) or set(plan) != {'title', 'rows'}:
            raise ValueError('Unexpected planning fields')
        if not re.match(r'^(Quy hoạch|Định hướng|Kế hoạch)\b', text(plan['title']), re.I):
            raise ValueError('Unknown planning section')
        if not objects(plan['rows'], {'area', 'label'}, 100):
            raise ValueError('Empty planning section')
    status = 'captured' if plans else 'not_provided'
    if data['planning_status'] != status:
        raise ValueError('Inconsistent planning status')
    points = data['points']
    if not isinstance(points, list) or not 3 <= len(points) <= 20000:
        raise ValueError('Invalid source corners')
    ring = []
    for point in points:
        if not isinstance(point, dict) or set(point) != {'lat', 'lng'}:
            raise ValueError('Invalid corner fields')
        lat, lng = point['lat'], point['lng']
        if (any(type(v) not in (float, int) or not math.isfinite(v) for v in (lat, lng))
                or not (10 < lat < 13 and 106 < lng < 108)):
            raise ValueError('Corner outside Dong Nai/Binh Phuoc reference window')
        ring.append((lng, lat))
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    polygon = Polygon(ring)
    if (len(set(ring[:-1])) != len(ring)-1 or polygon.is_empty or not polygon.is_valid
            or polygon.area <= 0 or polygon.bounds[2]-polygon.bounds[0] > 1
            or polygon.bounds[3]-polygon.bounds[1] > 1):
        raise ValueError('Invalid source polygon; do not repair source vertices')
    area, perimeter = Geod(ellps='WGS84').geometry_area_perimeter(polygon)
    return dict(type='Feature', id=f'guland:{province}:{identifier}', geometry=mapping(polygon),
                properties=dict(historic_province=province, source_url=data['source'], source_id=identifier,
                                source_admin=admin, captured_at=timestamp, titles=titles, localities=areas,
                                source_land_use=land_use, plans=plans, planning_status=status,
                                measured_area_m2=abs(area), measured_perimeter_m=perimeter,
                                origin='guland_browser_reference', cadastral_accuracy_verified=False))


def archive(path, captures):
    features = [feature_from_capture(data) for data in captures]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS captures (
            digest TEXT PRIMARY KEY, province TEXT NOT NULL, source_id INTEGER NOT NULL,
            captured_at TEXT NOT NULL, feature TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS parcel_capture ON captures (province,source_id,captured_at)')
        inserted = 0
        for feature in features:
            payload = json.dumps(feature, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            props = feature['properties']
            inserted += db.execute('INSERT OR IGNORE INTO captures VALUES (?,?,?,?,?)',
                                   (sha256(payload.encode()).hexdigest(), props['historic_province'],
                                    props['source_id'], props['captured_at'], payload)).rowcount
    return inserted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('captures', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1]/'data/planning/guland-parcels.sqlite')
    args = parser.parse_args()
    records = []
    for path in args.captures:
        with path.open('rb') as handle:
            payload = handle.read(2_000_001)
        if len(payload) > 2_000_000:
            raise ValueError('Oversized capture')
        records.append(json.loads(payload))
    print('New sanitized snapshots:', archive(args.output, records))


if __name__ == '__main__':
    main()
