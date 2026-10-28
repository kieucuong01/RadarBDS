"""Bounded on-demand parcels outside the immutable historic Bình Dương catalogue."""
from collections import OrderedDict
import json
import math
from pathlib import Path
import threading
import time

from services.planning_parcels import FIELDS, PARCEL_QUERY, PublicGIS, esri_geometry

LEGACY_DISTRICTS = {str(n) for n in range(718, 727)}
# Source WAF rejects an OR/IS NULL expression. Unassigned source rows cannot be
# matched to a verified administrative reference, so do not request them.
EXPANDED_WHERE = 'MaQuanHuyen NOT IN (' + ','.join(
    "'%s'" % d for d in sorted(LEGACY_DISTRICTS)) + ')'


class SourceBusy(Exception):
    """No request queue: protect the public GIS and bounded web workers."""


class LiveParcels:
    def __init__(self, client=None, cache_bytes=8_000_000):
        self.client = client or PublicGIS()
        self.areas = json.loads((Path(__file__).resolve().parents[1]/'config/planning_parcel_areas.json')
                               .read_text(encoding='utf8'))['areas']
        self.by_area = {a['code']: a for a in self.areas}
        self.cache, self.cache_size, self.cache_bytes = OrderedDict(), 0, cache_bytes
        self.lock, self.gate = threading.Lock(), threading.BoundedSemaphore(1)
        self.native_retry_at = 0

    def _get(self, key):
        with self.lock:
            for expired in [k for k, (when, _) in self.cache.items() if time.monotonic()-when >= 300]:
                self.cache_size -= len(self.cache.pop(expired)[1])
            value = self.cache.get(key)
            if value:
                self.cache.move_to_end(key)
                return json.loads(value[1])

    def _put(self, key, value):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        if len(raw) > self.cache_bytes:
            return
        with self.lock:
            if key in self.cache:
                self.cache_size -= len(self.cache.pop(key)[1])
            while self.cache and (len(self.cache) >= 32 or self.cache_size+len(raw) > self.cache_bytes):
                self.cache_size -= len(self.cache.popitem(last=False)[1][1])
            self.cache[key] = time.monotonic(), raw
            self.cache_size += len(raw)

    def _query(self, key, params, *, bbox=None, area=None, identifier=None, search=None, limit=1000):
        cached = self._get(key)
        if cached is not None:
            return cached
        if not self.gate.acquire(False):
            raise SourceBusy()
        try:
            # A concurrent miss may have completed before this gate was acquired.
            cached = self._get(key)
            if cached is not None:
                return cached
            params = dict(params, f='json', outFields=FIELDS, returnGeometry='true', outSR=4326,
                          orderByFields='OBJECTID ASC', resultRecordCount=limit)
            endpoint = PARCEL_QUERY if time.monotonic() >= self.native_retry_at else '/rest/thua-dat/query'
            try:
                data = self.client.request(endpoint, params=params)
            except ValueError:
                if endpoint != PARCEL_QUERY:
                    raise
                # The same public source exposes a REST adapter when native
                # ArcGIS intermittently returns 400/non-JSON. Validate it identically.
                endpoint = '/rest/thua-dat/query'
                self.native_retry_at = time.monotonic()+60
                data = self.client.request(endpoint, params=params)
            if not isinstance(data, dict):
                raise ValueError('Invalid source response')
            rows = data.get('features')
            if not isinstance(rows, list) or len(rows) > limit:
                raise ValueError('Invalid or unbounded parcel response')
            if rows and data.get('spatialReference', {}).get('wkid') != 4326:
                raise ValueError('Unexpected parcel coordinate system')
            features, seen, excluded, outside = [], set(), 0, 0
            from shapely.geometry import box, shape
            from shapely.errors import GEOSException
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get('attributes'), dict):
                    raise ValueError('Invalid source feature')
                attr = row['attributes']
                oid = attr['OBJECTID']
                code, district = str(attr.get('MaPhuongXa')), str(attr.get('MaQuanHuyen'))
                ref = self.by_area.get(code)
                if (type(oid) is not int or not 0 < oid < 2**53 or oid in seen
                        or district in LEGACY_DISTRICTS or not ref or ref['district'] != district
                        or (area is not None and code != area) or (identifier is not None and oid != identifier)):
                    raise ValueError('Parcel membership mismatch')
                seen.add(oid)
                props = {}
                for field, source in [('sheet', 'SoTo'), ('parcel', 'SoThua'), ('area', 'DienTich')]:
                    value = attr.get(source)
                    if value is not None and (type(value) not in (str, int, float)
                            or (isinstance(value, str) and (len(value) > 100 or any(ord(c)<32 for c in value)))
                            or (isinstance(value, (int, float)) and not math.isfinite(value))):
                        raise ValueError('Invalid parcel attribute')
                    props[field] = value
                if search and (str(props['sheet']).strip(), str(props['parcel']).strip()) != search:
                    raise ValueError('Source ignored exact parcel search')
                if not isinstance(row.get('geometry'), dict):
                    excluded += 1
                    continue
                rings = row['geometry'].get('rings')
                if (not isinstance(rings, list) or not rings or len(rings) > 100
                        or any(not isinstance(r, list) for r in rings)
                        or sum(len(r) for r in rings) > 20000 or any(
                        len(r) < 4 or r[0] != r[-1] or any(not isinstance(p, list) or len(p) != 2 or any(
                            type(v) not in (int, float) or not math.isfinite(v) for v in p)
                            or not (106.25 <= p[0] <= 107.65 and 8.5 <= p[1] <= 11.65)
                            for p in r) for r in rings)):
                    excluded += 1
                    continue
                try:
                    geometry = esri_geometry(rings)
                    polygon = shape(geometry)
                    if polygon.is_empty or not polygon.is_valid:
                        excluded += 1
                        continue
                except (GEOSException, ValueError):
                    excluded += 1
                    continue
                if bbox and not polygon.intersects(box(*bbox)):
                    # Source queries may use a projected envelope. Keep only
                    # actual intersections in the requested geographic viewport.
                    outside += 1
                    continue
                props.update(id=oid, area_id=code, ward=ref['ward'], city=ref['city'])
                features.append({'type': 'Feature', 'id': oid, 'properties': props, 'geometry': geometry})
            if rows and outside == len(rows):
                raise ValueError('Source ignored viewport')
            result = {'type': 'FeatureCollection', 'features': features, 'matched': len(features),
                      'excluded_count': excluded, 'query_endpoint': endpoint,
                      'truncated': bool(data.get('exceededTransferLimit')) or len(rows) == limit}
            self._put(key, result)
            return result
        finally:
            self.gate.release()

    def viewport(self, bbox):
        west, south, east, north = bbox
        return self._query(('viewport', *bbox), {'where': EXPANDED_WHERE,
            'geometry': json.dumps({'xmin': west, 'ymin': south, 'xmax': east, 'ymax': north,
                                   'spatialReference': {'wkid': 4326}}),
            'geometryType': 'esriGeometryEnvelope', 'inSR': 4326,
            'spatialRel': 'esriSpatialRelIntersects'}, bbox=bbox)

    def _area_where(self, area):
        ref = self.by_area.get(area)
        if not ref or ref['district'] in LEGACY_DISTRICTS:
            raise ValueError('Unsupported live parcel area')
        return "MaPhuongXa = '%s' AND MaQuanHuyen = '%s'" % (area, ref['district'])

    def search(self, area, sheet, parcel):
        # Values are SQL literals for the fixed source endpoint, never identifiers/URLs.
        where = self._area_where(area) + " AND SoTo = '%s' AND SoThua = '%s'" % (
            sheet.replace("'", "''"), parcel.replace("'", "''"))
        return self._query(('search', area, sheet, parcel), {'where': where}, area=area,
                           search=(sheet, parcel), limit=20)

    def sample(self, area):
        features = self._query(('sample', area), {'where': self._area_where(area)}, area=area, limit=1)['features']
        return features[0] if features else None

    def feature(self, identifier, area=None):
        if type(identifier) is not int or not 0 < identifier < 2**53:
            return None
        if area is not None and (area not in self.by_area or self.by_area[area]['district'] in LEGACY_DISTRICTS):
            return None
        with self.lock:
            cached = [raw for when, raw in self.cache.values() if time.monotonic()-when < 300]
        for raw in cached:
            for feature in json.loads(raw)['features']:
                if feature['id'] == identifier:
                    return feature if area is None or feature['properties']['area_id'] == area else None
        where = (self._area_where(area) if area else EXPANDED_WHERE) + ' AND OBJECTID = ' + str(identifier)
        result = self._query(('id', identifier, area), {'where': where}, identifier=identifier, area=area, limit=1)
        return result['features'][0] if result['features'] else None

    def needs_viewport(self, bbox, legacy_areas):
        west, south, east, north = bbox
        def intersects(a):
            (s, w), (n, e) = a['bounds']
            return w <= east and e >= west and s <= north and n >= south
        # Conservative at borders: reference windows never become cadastral masks.
        if any(intersects(a) for a in self.areas if a['district'] not in LEGACY_DISTRICTS):
            return True
        return not any(a['bounds'][0][1] <= west and a['bounds'][1][1] >= east
                       and a['bounds'][0][0] <= south and a['bounds'][1][0] >= north for a in legacy_areas)
