"""Public GIS parcel capture and sanitized lookup; source credentials stay in memory."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import threading
import time

import requests

SOURCE = 'https://gisxaydung.tphcm.gov.vn/tracuuttqh'
API = 'https://api-gisxaydung.tphcm.gov.vn'
WHERE = "MaPhuongXa = '25765' AND MaQuanHuyen = '718'"
FIELDS = 'OBJECTID,SoTo,SoThua,DienTich,MaPhuongXa,MaQuanHuyen'
PARCEL_QUERY = '/arcgis/rest/services/HCM/RanhThuaDat/MapServer/0/query'


class PublicGIS:
    """Use the source's public guest handshake; credentials stay in process memory."""
    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': SOURCE,
                                     'Origin': 'https://gisxaydung.tphcm.gov.vn', 'Accept': 'application/json'})
        self.lock = threading.Lock()
        self.expires = 0

    @staticmethod
    def packets(value):
        while value:
            length, separator, rest = value.partition(':')
            if not separator or not length.isdigit() or int(length) > len(rest):
                raise ValueError('Invalid public guest handshake')
            yield rest[:int(length)]
            value = rest[int(length):]

    def guest(self):
        self.session.headers.pop('Authorization', None)
        params = {'EIO': 3, 'transport': 'polling'}
        response = self.session.get(API+'/socket.io/', params=params, timeout=(5, 15))
        response.raise_for_status()
        hello = list(self.packets(response.text))
        params['sid'] = json.loads(hello[0][1:])['sid']
        event = '42["token"]'
        response = self.session.post(API+'/socket.io/', params=params,
            data=str(len(event))+':'+event, headers={'Content-Type': 'text/plain;charset=UTF-8'}, timeout=(5, 15))
        response.raise_for_status()
        response = self.session.get(API+'/socket.io/', params=params, timeout=(5, 15))
        response.raise_for_status()
        for packet in self.packets(response.text):
            if packet.startswith('42'):
                name, value = json.loads(packet[2:])
                if name == 'token':
                    self.session.headers['Authorization'] = 'Bearer '+value['accessToken']
                    self.expires = min(float(value['expired'])-60, time.time()+900)
        if 'Authorization' not in self.session.headers:
            raise ValueError('Public guest session unavailable')
        # Release the short-lived polling connection, keeping only its issued guest token.
        try:
            self.session.post(API+'/socket.io/', params=params, data='1:1',
                headers={'Content-Type': 'text/plain;charset=UTF-8'}, timeout=(3, 5))
        except requests.RequestException:
            pass

    def request(self, path, *, params=None, body=None):
        if path not in ('/rest/thua-dat/query', '/thong-tin-quy-hoach/dnm', PARCEL_QUERY):
            raise ValueError('Unsupported GIS endpoint')
        with self.lock:
            for attempt in range(2):
                if self.expires <= time.time():
                    self.guest()
                response = self.session.request('POST' if body is not None else 'GET', API+path,
                    params=params, json=body, timeout=(5, 25))
                if response.status_code == 401 and attempt == 0:
                    self.expires = 0
                    continue
                response.raise_for_status()
                if len(response.content) > 10_000_000:
                    raise ValueError('GIS response too large')
                data = response.json()
                if isinstance(data, dict) and ('error' in data or data.get('statusCode', 200) >= 400):
                    raise ValueError('GIS returned a service error')
                return data


def esri_geometry(rings):
    """Assign ring nesting without moving, simplifying or inventing source vertices."""
    from shapely.geometry import Polygon
    polygons = [Polygon(ring) for ring in rings]
    parents = []
    for index, polygon in enumerate(polygons):
        containers = [i for i, outer in enumerate(polygons) if i != index
                      and outer.area > polygon.area and outer.covers(polygon)]
        parents.append(min(containers, key=lambda i: polygons[i].area) if containers else None)
    def depth(index):
        count, parent = 0, parents[index]
        while parent is not None:
            count, parent = count+1, parents[parent]
        return count
    groups = [[ring, *(rings[j] for j, parent in enumerate(parents) if parent == i)]
              for i, ring in enumerate(rings) if depth(i) % 2 == 0]
    if not groups:
        raise ValueError('Empty parcel geometry')
    return {'type': 'Polygon', 'coordinates': groups[0]} if len(groups) == 1 else {
        'type': 'MultiPolygon', 'coordinates': groups}


def complete_identifiers(client, where, limit=4000):
    """Split ID predicates: the public REST adapter silently caps/ignores offsets."""
    def collect(condition, depth=0):
        count = client.request('/rest/thua-dat/query', params={
            'f': 'json', 'where': condition, 'returnCountOnly': 'true'})['count']
        if not isinstance(count, int) or not 0 <= count <= 100000 or depth > 32:
            raise ValueError('Unexpected parcel count or partition depth')
        if not count:
            return []
        ids = client.request('/rest/thua-dat/query', params={
            'f': 'json', 'where': condition, 'returnIdsOnly': 'true', 'resultRecordCount': limit})['objectIds']
        if (not ids or len(ids) > count or len(set(ids)) != len(ids)
                or any(type(i) is not int or not 0 < i < 2**31 for i in ids)):
            raise ValueError('Invalid parcel identifiers')
        if len(ids) == count:
            return sorted(ids)
        if len(ids) < 2:
            raise ValueError('Incomplete parcel identifiers')
        pivot = sorted(ids)[len(ids)//2]
        left = collect(condition + ' AND OBJECTID < ' + str(pivot), depth+1)
        right = collect(condition + ' AND OBJECTID >= ' + str(pivot), depth+1)
        if (len(left)+len(right) != count or len(set(left+right)) != count
                or any(i >= pivot for i in left) or any(i < pivot for i in right)):
            raise ValueError('Incomplete or overlapping parcel ID partitions')
        return sorted(left+right)
    return collect(where)


def capture(directory, client=None, area=None):
    """Bounded, ward-filtered snapshot; no owner, address or contact fields are requested."""
    from shapely.geometry import shape
    from config.planning_parcels import PARCEL_AREAS
    from hashlib import sha256
    area = area or next(a for a in PARCEL_AREAS if a['code'] == '25765')
    if area not in PARCEL_AREAS:
        raise ValueError('Unknown parcel area')
    where = "MaPhuongXa = '%s' AND MaQuanHuyen = '%s'" % (area['code'], area['district'])
    client = client or PublicGIS()
    identifiers = complete_identifiers(client, where)
    count = len(identifiers)
    if not count:
        raise ValueError('Source has no parcels for '+area['ward'])
    features, seen, excluded = [], set(), []
    for offset in range(0, count, 500):
        requested = identifiers[offset:offset+500]
        data = client.request('/rest/thua-dat/query', params={'f': 'json',
            'where': where+' AND OBJECTID IN ('+','.join(map(str, requested))+')',
            'outFields': FIELDS, 'returnGeometry': 'true', 'outSR': 4326,
            'orderByFields': 'OBJECTID ASC', 'resultRecordCount': min(500, count-offset)})
        if data.get('spatialReference', {}).get('wkid') != 4326:
            raise ValueError('Unexpected coordinate system')
        page = data.get('features', [])
        if len(page) != min(500, count-offset):
            raise ValueError('Incomplete parcel page')
        for row in page:
            attributes = row['attributes']
            identifier = attributes['OBJECTID']
            if identifier in seen or str(attributes.get('MaPhuongXa')) != area['code'] or str(attributes.get('MaQuanHuyen')) != area['district']:
                raise ValueError('Duplicate or outside selected ward parcel')
            seen.add(identifier)
            rings = (row.get('geometry') or {}).get('rings', [])
            if not rings or any(len(ring) < 4 or ring[0] != ring[-1] or any(
                len(p) != 2 or not all(math.isfinite(v) for v in p)
                or not (106.25 < p[0] < 107.1 and 10.75 < p[1] < 11.65) for p in ring) for ring in rings):
                excluded.append({'id': identifier, 'reason': 'invalid_source_ring_or_outside_coverage'})
                continue
            from shapely.errors import GEOSException
            try:
                geometry = esri_geometry(rings)
                valid = shape(geometry).is_valid
            except (GEOSException, ValueError):
                valid = False
            if not valid:
                excluded.append({'id': identifier, 'reason': 'invalid_source_polygon'})
                continue
            features.append({'type': 'Feature', 'id': identifier,
                'properties': {'id': identifier, 'area_id': area['code'], 'ward': area['ward'], 'city': area['city'],
                               'sheet': attributes.get('SoTo'), 'parcel': attributes.get('SoThua'),
                               'area': attributes.get('DienTich')}, 'geometry': geometry})
        if {row['attributes']['OBJECTID'] for row in page} != set(requested):
            raise ValueError('GIS did not honor requested object identifiers')
        print(area['ward'], len(seen), '/', count, '; accepted', len(features), '; excluded', len(excluded), flush=True)
    if seen != set(identifiers):
        raise ValueError('Incomplete parcel snapshot')
    if client.request('/rest/thua-dat/query', params={'f':'json','where':where,'returnCountOnly':'true'})['count'] != count:
        raise ValueError('Source count changed during capture')
    result = {'type': 'FeatureCollection', 'ward': area['ward'], 'city': area['city'], 'area_id': area['code'], 'count': len(features),
              'source_count': count, 'excluded_count': len(excluded),
              'source': SOURCE, 'captured_at': datetime.now(timezone.utc).isoformat(), 'features': features}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory/'parcels.geojson'
    temporary = directory/'parcels.geojson.download'
    temporary.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')), encoding='utf8')
    temporary.replace(target)
    (directory/'excluded.json').write_text(json.dumps(excluded, indent=2), encoding='utf8')
    metadata = {k:v for k,v in result.items() if k != 'features'}
    metadata.update(sha256=sha256(target.read_bytes()).hexdigest(),
                    ids_sha256=sha256(json.dumps(identifiers).encode()).hexdigest(),
                    query_endpoint='/rest/thua-dat/query', pagination='verified disjoint OBJECTID predicates')
    (directory/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf8')
    return result


def planning_info(data):
    """Keep source values verbatim and remove geometry/internal or personal fields."""
    if not isinstance(data, list) or len(data) > 20:
        raise ValueError('Invalid GIS planning result')
    result = []
    for group in data:
        if not isinstance(group, dict) or not isinstance(group.get('doAns', []), list) or len(group.get('doAns', [])) > 40:
            raise ValueError('Invalid GIS plan group')
        for plan in group.get('doAns', []):
            if not isinstance(plan, dict) or not isinstance(plan.get('phanKhuChucNangs', []), list) or len(plan.get('phanKhuChucNangs', [])) > 200:
                raise ValueError('Invalid GIS zones')
            if any(not isinstance(zone, dict) for zone in plan.get('phanKhuChucNangs', [])):
                raise ValueError('Invalid GIS zone')
            zones = [{key: zone.get(key) for key in (
                'maMucDichSuDungDat', 'mucDichSuDungDat', 'dienTich', 'kyHieuLoDat',
                'tangCaoXayDung', 'matDoXayDungTrungBinh', 'heSoSuDungDat')}
                for zone in plan.get('phanKhuChucNangs', [])[:200]]
            result.append({'type': group.get('tenLoaiQuyHoach'), 'name': plan.get('tenDuAn'),
                'scale': plan.get('tyLe'), 'decision': plan.get('soQD'), 'date': plan.get('soQD_NgayKy'),
                'amendment': plan.get('soQD_DC'), 'amendment_date': plan.get('soQD_DC_NgayKy'),
                'intersection_area': plan.get('dienTich'), 'zones': zones})
    return result


def install_parcel_pilot(app, directory):
    """Local-only HTTP endpoints inherit the runner's loopback and no-store guards."""
    from flask import abort, jsonify, request
    from shapely.geometry import box, shape
    from shapely.strtree import STRtree
    data = json.loads((Path(directory)/'parcels.geojson').read_text(encoding='utf8'))
    features = data['features']
    if data.get('ward') != 'Tân An' or not 0 < len(features) <= 25000:
        raise ValueError('Invalid Tân An snapshot')
    lookup = {str(feature['id']): feature for feature in features}
    tree = STRtree([shape(feature['geometry']) for feature in features])
    bounds = tree.geometries
    minx = min(g.bounds[0] for g in bounds); miny = min(g.bounds[1] for g in bounds)
    maxx = max(g.bounds[2] for g in bounds); maxy = max(g.bounds[3] for g in bounds)

    @app.context_processor
    def parcel_context():
        return {'parcel_pilot_enabled': True}

    @app.get('/local-planning/parcels/config.json')
    def parcel_config():
        return jsonify(ward='Tân An', city='Thủ Dầu Một', count=len(features), min_zoom=17,
            excluded_count=data.get('excluded_count', 0), source_count=data.get('source_count', len(features)),
            bounds=[[miny, minx], [maxy, maxx]], source=SOURCE, captured_at=data['captured_at'],
            example=lookup.get('33013'))

    @app.get('/local-planning/parcels/viewport.json')
    def parcel_viewport():
        try:
            west, south, east, north = parcel_bbox(request.args.get('bbox', ''))
        except ValueError:
            return jsonify(error='Vùng xem không hợp lệ. Hãy phóng to bản đồ.'), 400
        matches = sorted(map(int, tree.query(box(west, south, east, north))))
        return jsonify(type='FeatureCollection', features=[features[i] for i in matches[:1500]],
                       truncated=len(matches)>1500, matched=len(matches))

    install_planning_lookup(app, lambda identifier: lookup.get(str(identifier)))


def parcel_bbox(value, expanded=False):
    west, south, east, north = map(float, value.split(','))
    min_south, max_east = (8.5, 107.65) if expanded else (10.75, 107.1)
    if not all(math.isfinite(v) for v in (west, south, east, north)) or not (
        106.25 <= west < east <= max_east and min_south <= south < north <= 11.65
        and east-west <= .05 and north-south <= .05):
        raise ValueError('Invalid viewport')
    return west, south, east, north


def install_planning_lookup(app, feature_by_id, prefix='/local-planning/parcels'):
    from flask import abort, jsonify
    client, cache = PublicGIS(), {}
    gate = threading.BoundedSemaphore(2)

    @app.get(prefix+'/<int:identifier>/planning.json')
    def parcel_planning(identifier):
        if not 0 < identifier < 2**53:
            abort(404)
        if not gate.acquire(blocking=False):
            return jsonify(error='GIS đang bận. Vui lòng thử lại sau.'), 503
        try:
            from services.planning_live_parcels import SourceBusy
            feature = feature_by_id(identifier)
            if feature is None:
                abort(404)
            cached = cache.get(identifier)
            if cached and time.monotonic()-cached[0] < 300:
                return jsonify(cached[1])
            plans = planning_info(client.request('/thong-tin-quy-hoach/dnm', body={'objectId': identifier}))
            result = {'parcel': feature['properties'], 'plans': plans, 'source': SOURCE,
                      'queried_at': datetime.now(timezone.utc).isoformat()}
            if len(cache) >= 128:
                cache.pop(next(iter(cache)))
            cache[identifier] = time.monotonic(), result
            return jsonify(result)
        except SourceBusy:
            return jsonify(error='GIS đang bận. Vui lòng thử lại sau.'), 503
        except (requests.RequestException, ValueError, KeyError, TypeError):
            return jsonify(error='Chưa lấy được thông tin từ GIS. Không thể kết luận quy hoạch thửa này.'), 502
        finally:
            gate.release()
