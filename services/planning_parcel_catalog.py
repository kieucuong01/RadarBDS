"""Local spatial asset index: never load the full parcel catalogue into the browser."""
from contextlib import closing
from hashlib import sha256
import json
import math
from pathlib import Path
import sqlite3

from services.planning_parcels import SOURCE


def build_catalog(directory, areas):
    """Publish one complete, verified index atomically; keep the previous on failure."""
    from shapely.geometry import shape
    from config.listing_map import LISTING_MAP_WARD_REGISTRY_PATH
    wards = json.loads(LISTING_MAP_WARD_REGISTRY_PATH.read_text(encoding='utf8'))['wards']
    centers = {(w['city'].casefold(),w['ward'].casefold()):(w['lng'],w['lat']) for w in wards}
    from config.planning_parcels import PLANNING_REGIONS
    for region in PLANNING_REGIONS:
        centers.setdefault((region['city'].casefold(),region['ward'].casefold()),
                           (region['center'][1],region['center'][0]))
    directory = Path(directory)
    target = directory/'parcels.sqlite'
    temporary = directory/'parcels.sqlite.download'
    if temporary.exists():
        temporary.unlink()
    try:
        with closing(sqlite3.connect(temporary)) as conn:
            conn.executescript('''
                CREATE TABLE areas (code TEXT PRIMARY KEY, metadata TEXT NOT NULL);
                CREATE TABLE parcels (id INTEGER PRIMARY KEY, area TEXT NOT NULL, feature TEXT NOT NULL);
                CREATE VIRTUAL TABLE bounds USING rtree(id, west, east, south, north);
            ''')
            for area in areas:
                folder = directory/area['code']
                metadata = json.loads((folder/'metadata.json').read_text(encoding='utf8'))
                raw = (folder/'parcels.geojson').read_bytes()
                if sha256(raw).hexdigest() != metadata['sha256']:
                    raise ValueError('Parcel snapshot hash mismatch')
                data = json.loads(raw)
                features = data['features']
                if (data['area_id'] != area['code'] or data['ward'] != area['ward'] or data['city'] != area['city']
                        or not 0 < len(features) == data['count'] <= 100000
                        or data['count']+data['excluded_count'] != data['source_count']):
                    raise ValueError('Incomplete or wrong-area parcel capture')
                extent = [math.inf, math.inf, -math.inf, -math.inf]
                sample, sample_score = None, math.inf
                shapes = []
                for feature in features:
                    if (feature['id'] != feature['properties']['id']
                            or feature['properties'].get('area_id') != area['code']):
                        raise ValueError('Parcel area membership mismatch')
                    geometry = shape(feature['geometry'])
                    w, s, e, n = geometry.bounds
                    if not geometry.is_valid or geometry.is_empty or not (106.25 < w <= e < 107.1 and 10.75 < s <= n < 11.65):
                        raise ValueError('Invalid captured parcel geometry')
                    extent = [min(extent[0],w),min(extent[1],s),max(extent[2],e),max(extent[3],n)]
                    shapes.append((feature, geometry))
                    value = json.dumps(feature,ensure_ascii=False,separators=(',',':'))
                    conn.execute('INSERT INTO parcels VALUES (?,?,?)',(feature['id'],area['code'],value))
                    conn.execute('INSERT INTO bounds VALUES (?,?,?,?,?)',(feature['id'],w,e,s,n))
                cx, cy = centers.get((area['city'].casefold(),area['ward'].casefold()),
                                     ((extent[0]+extent[2])/2,(extent[1]+extent[3])/2))
                for feature, geometry in shapes:
                    point = geometry.representative_point()
                    score = (point.x-cx)**2+(point.y-cy)**2
                    if feature['id'] == 33013:
                        score = -1
                    if score < sample_score:
                        sample, sample_score = feature['id'], score
                metadata.update(bounds=[[extent[1],extent[0]],[extent[3],extent[2]]],
                                center=[cy,cx],sample_id=sample)
                conn.execute('INSERT INTO areas VALUES (?,?)',(area['code'],json.dumps(metadata,ensure_ascii=False)))
            conn.execute("""CREATE INDEX parcel_lookup ON parcels(
                area,trim(CAST(json_extract(feature,'$.properties.sheet') AS TEXT)),
                trim(CAST(json_extract(feature,'$.properties.parcel') AS TEXT)))""")
            conn.commit()
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Parcel spatial index integrity failure')
        temporary.replace(target)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return target


class ParcelCatalog:
    def __init__(self, path):
        self.path = Path(path).resolve()
        with self.connect() as conn:
            self.areas = [json.loads(row[0]) for row in conn.execute('SELECT metadata FROM areas ORDER BY code')]
        if not self.areas:
            raise ValueError('Empty parcel catalogue')

    def connect(self):
        return closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=2))

    def feature(self, identifier, area=None):
        with self.connect() as conn:
            row = conn.execute('SELECT feature FROM parcels WHERE id=?'+(' AND area=?' if area else ''),
                               (identifier,area) if area else (identifier,)).fetchone()
        return json.loads(row[0]) if row else None

    def viewport(self, bbox):
        west,south,east,north = bbox
        params = (east,west,north,south)
        condition = 'b.west<=? AND b.east>=? AND b.south<=? AND b.north>=?'
        with self.connect() as conn:
            count = conn.execute('SELECT count(*) FROM bounds b WHERE '+condition,params).fetchone()[0]
            rows = conn.execute('SELECT p.feature FROM bounds b JOIN parcels p ON p.id=b.id WHERE '
                                +condition+' ORDER BY p.id LIMIT 1500',params).fetchall()
        return [json.loads(row[0]) for row in rows],count

    def search(self, area, sheet, parcel):
        condition = """area=? AND trim(CAST(json_extract(feature,'$.properties.sheet') AS TEXT))=?
            AND trim(CAST(json_extract(feature,'$.properties.parcel') AS TEXT))=?"""
        params = (area,sheet,parcel)
        with self.connect() as conn:
            count = conn.execute('SELECT count(*) FROM parcels WHERE '+condition,params).fetchone()[0]
            rows = conn.execute('SELECT feature FROM parcels WHERE '+condition+' ORDER BY id LIMIT 20',params).fetchall()
        return [json.loads(row[0]) for row in rows],count


def install_catalog(app, path, prefix='/local-planning/parcels', expanded=None):
    """Adapt the existing loopback routes; retain lookup guards and bounded cache."""
    from flask import abort, jsonify, request
    from services.planning_parcels import install_planning_lookup
    catalog = ParcelCatalog(path)
    areas = {a['area_id']:a for a in catalog.areas}
    if expanded is True:
        from services.planning_live_parcels import LiveParcels
        expanded = LiveParcels()
    live_areas = {a['code']: a for a in expanded.areas} if expanded else {}

    def source_result(callback):
        import requests
        from services.planning_live_parcels import SourceBusy
        from shapely.errors import GEOSException
        try:
            result = callback()
            if result is None:
                abort(404)
            return jsonify(result)
        except SourceBusy:
            return jsonify(error='GIS đang bận. Vui lòng thử lại sau.'), 503
        except (requests.RequestException, ValueError, KeyError, TypeError, GEOSException):
            return jsonify(error='Chưa lấy được ranh từ GIS. Vui lòng thử lại; chưa thể kết luận khu vực không có dữ liệu.'), 502

    def feature_by_id(identifier):
        area = request.args.get('area')
        feature = catalog.feature(identifier, area)
        return feature or (expanded.feature(identifier, area) if expanded else None)

    @app.context_processor
    def parcel_context():
        return {'parcel_pilot_enabled': True}

    @app.get(prefix+'/config.json')
    def parcel_config():
        from config.planning_parcels import PLANNING_REGIONS
        result = dict(areas=catalog.areas, count=sum(a['count'] for a in catalog.areas), min_zoom=17,
                      navigation_areas=PLANNING_REGIONS,
                      excluded_count=sum(a['excluded_count'] for a in catalog.areas), source=SOURCE)
        if expanded:
            from config.planning_regions import HCM_EXPANDED_BOUNDS
            result.update(areas=[dict(a, **areas.get(a['code'], {})) for a in expanded.areas],
                          navigation_areas=expanded.areas, live_expanded=True,
                          coverage_bounds=HCM_EXPANDED_BOUNDS, count_scope='historic_binh_duong_snapshot')
        return jsonify(result)

    @app.get(prefix+'/sample.json')
    def parcel_sample():
        code = request.args.get('area')
        area = areas.get(code)
        if expanded and code in live_areas and area is None:
            return source_result(lambda: expanded.sample(code))
        if area is None:
            abort(404)
        return jsonify(catalog.feature(area['sample_id'],area['area_id']))

    @app.get(prefix+'/search.json')
    def parcel_search():
        values = [request.args.get(key,'').strip() for key in ('area','sheet','parcel')]
        if any(not value or len(value)>32 or any(ord(c)<32 or ord(c)==127 for c in value) for value in values):
            return jsonify(error='Chọn phường và nhập số tờ, số thửa hợp lệ.'),400
        area,sheet,parcel = values
        if expanded and area in live_areas and area not in areas:
            return source_result(lambda: expanded.search(area,sheet,parcel))
        if area not in areas:
            abort(404)
        features,count = catalog.search(area,sheet,parcel)
        return jsonify(type='FeatureCollection',features=features,matched=count,truncated=count>20)

    @app.get(prefix+'/viewport.json')
    def parcel_viewport():
        from services.planning_parcels import parcel_bbox
        try:
            bbox = parcel_bbox(request.args.get('bbox',''), expanded=bool(expanded))
        except ValueError:
            return jsonify(error='Vùng xem không hợp lệ. Hãy phóng to bản đồ.'),400
        features,count = catalog.viewport(bbox)
        if expanded and expanded.needs_viewport(bbox, catalog.areas):
            def combined():
                live = expanded.viewport(bbox)
                merged = {f['id']: f for f in features}
                merged.update({f['id']: f for f in live['features']})
                result = sorted(merged.values(), key=lambda f: f['id'])
                return dict(type='FeatureCollection', features=result[:1500],
                            matched=count+live['matched'],
                            excluded_count=live.get('excluded_count',0),
                            truncated=live['truncated'] or count+live['matched']>1500)
            return source_result(combined)
        return jsonify(type='FeatureCollection',features=features,truncated=count>1500,matched=count)

    install_planning_lookup(app, feature_by_id, prefix=prefix)
