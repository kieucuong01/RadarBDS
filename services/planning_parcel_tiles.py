"""Fixed public parcel cells: shared bounded cache, never cache private lookups."""
import gzip
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
import time

ZOOM = 17
MAX_BYTES = 32_000_000
FIELDS = ('id', 'area_id', 'sheet', 'parcel', 'area', 'ward', 'city',
          'membership_method', 'source_ward_code', 'source_district_code')


def bounds(x, y):
    n = 2**ZOOM
    if not (0 <= x < n and 0 <= y < n):
        raise ValueError('Invalid cell')
    latitude = lambda row: math.degrees(math.atan(math.sinh(math.pi*(1-2*row/n))))
    box = (x/n*360-180, latitude(y+1), (x+1)/n*360-180, latitude(y))
    if not (102 <= box[0] < box[2] <= 110 and 8 <= box[1] < box[3] <= 24):
        raise ValueError('Cell outside supported country bounds')
    return box


class CellBusy(Exception):
    pass


class CellCache:
    """SQLite leases coordinate workers; warm readers never wait on upstream GIS."""
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS cells(key TEXT PRIMARY KEY, expires REAL, payload BLOB)')
            db.execute('CREATE TABLE IF NOT EXISTS leases(key TEXT PRIMARY KEY, expires REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS originals(key TEXT PRIMARY KEY, expires REAL, payload BLOB)')
            db.execute('CREATE INDEX IF NOT EXISTS cells_expiry ON cells(expires)')
            db.execute('CREATE INDEX IF NOT EXISTS originals_expiry ON originals(expires)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=.1)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key, loader, ttl, group='snapshot'):
        now = time.time()
        lease_key=group+':'+key
        with self.connect() as db:
            row = db.execute('SELECT payload FROM cells WHERE key=? AND expires>?', (key, now)).fetchone()
            if row:
                return row[0], True
            db.execute('DELETE FROM leases WHERE expires<?', (now,))
            # Bound all cold work, including across gunicorn processes.
            if db.execute('SELECT count(*) FROM leases WHERE key LIKE ?', (group+':%',)).fetchone()[0] >= 2:
                raise CellBusy()
            if db.execute('INSERT OR IGNORE INTO leases VALUES (?,?)', (lease_key, now+300)).rowcount != 1:
                raise CellBusy()
        try:
            payload = gzip.compress(json.dumps(loader(), ensure_ascii=False, allow_nan=False,
                                              separators=(',', ':')).encode(), mtime=0)
            if len(payload) > 2_000_000:
                raise ValueError('Unbounded parcel tile')
            with self.connect() as db:
                db.execute('DELETE FROM cells WHERE expires<?', (now,))
                db.execute('INSERT OR REPLACE INTO cells VALUES (?,?,?)', (key, now+ttl, payload))
                size, count = db.execute('SELECT coalesce(sum(length(payload)),0), count(*) FROM cells').fetchone()
                while size > MAX_BYTES or count > 2048:
                    old = db.execute('SELECT key,length(payload) FROM cells ORDER BY expires LIMIT 1').fetchone()
                    db.execute('DELETE FROM cells WHERE key=?', (old[0],))
                    size -= old[1]
                    count -= 1
            return payload, False
        finally:
            with self.connect() as db:
                db.execute('DELETE FROM leases WHERE key=?', (lease_key,))

    def originals(self, release, features, ttl):
        now=time.time()
        with self.connect() as db:
            db.execute('DELETE FROM originals WHERE expires<?',(now,))
            db.executemany('INSERT OR REPLACE INTO originals VALUES (?,?,?)',[
                (f"{release}:{f['id']}",now+ttl,gzip.compress(json.dumps(f,separators=(',',':'),ensure_ascii=False).encode(),mtime=0))
                for f in features])
            size,count=db.execute('SELECT coalesce(sum(length(payload)),0),count(*) FROM originals').fetchone()
            while size>MAX_BYTES or count>4096:
                key,length=db.execute('SELECT key,length(payload) FROM originals ORDER BY expires LIMIT 1').fetchone()
                db.execute('DELETE FROM originals WHERE key=?',(key,));size-=length;count-=1

    def original(self, key):
        with self.connect() as db:
            row=db.execute('SELECT payload FROM originals WHERE key=? AND expires>?',(key,time.time())).fetchone()
            return json.loads(gzip.decompress(row[0])) if row else None


def public_feature(feature):
    properties={k:feature['properties'][k] for k in FIELDS if k in feature['properties']}
    source=feature['properties'].get('source')
    if source in ('https://gis.dongnai.gov.vn/', 'https://gisxaydung.tphcm.gov.vn/tracuuttqh',
                  'https://gis.khanhhoa.gov.vn/'):
        properties['source']=source
    return dict(type='Feature',id=feature['id'],geometry=feature['geometry'],properties=properties)


def display_features(features, box):
    """Simplify display only; never introduce false edges along cell boundaries."""
    from shapely.geometry import shape, mapping, box as rectangle
    clip=rectangle(*box)
    result=[]
    for feature in features:
        geometry=shape(feature['geometry'])
        if not geometry.intersects(clip):
            continue
        geometry=geometry.simplify(.000003,preserve_topology=True)
        if geometry.is_empty or geometry.geom_type not in ('Polygon','MultiPolygon'):
            continue
        result.append(dict(feature,geometry=mapping(geometry),display_only=True))
    return result


def install(app, catalog, expanded, directory, release):
    from flask import Response, abort, request
    from services.planning_live_parcels import SourceBusy
    from shapely.errors import GEOSException
    import requests
    cache = CellCache(Path(directory)/'parcel-cells-v1.sqlite')
    template = '/api/planning/parcel-cells/'+release+'/snapshot/{x}/{y}.json'
    app.extensions['planning_parcel_cells'] = dict(template=template, zoom=ZOOM,
        live_template=template.replace('/snapshot/','/live/'),
        feature_template='/api/planning/parcel-original/'+release+'/{id}.json')

    @app.get('/api/planning/parcel-original/<version>/<int:identifier>.json')
    def planning_parcel_original(version, identifier):
        if version!=release or request.args or not 0<identifier<2**53:
            abort(404)
        feature=catalog.feature(identifier) or cache.original(f'{release}:{identifier}')
        if feature is None:
            abort(404)
        return public_feature(feature)

    @app.get('/api/planning/parcel-cells/<version>/<kind>/<int:x>/<int:y>.json')
    def planning_parcel_cell(version, kind, x, y):
        if version != release or kind not in ('snapshot','live') or request.args:
            abort(404)
        try:
            box = bounds(x, y)
        except ValueError:
            abort(404)
        remote = bool(expanded and expanded.needs_viewport(box, catalog.areas))

        def load():
            # Snapshot cells never wait for a remote provider. Live supplementation
            # is a separate lower-priority request, so GIS failure cannot hide local parcels.
            if kind=='snapshot':
                features,count=getattr(catalog,'cell',catalog.viewport)(box)
                truncated=count>1500
            elif remote:
                result=expanded.viewport(box)
                features=result['features'];truncated=result.get('truncated',False)
            else:
                features=[];truncated=False
            features=[public_feature(f) for f in features]
            if kind=='live':
                cache.originals(release,features,900)
            return dict(type='FeatureCollection',features=display_features(features,box),
                        truncated=truncated,needs_live=remote and kind=='snapshot')
        try:
            payload, hit = cache.get(f'{release}:{kind}:{x}:{y}', load, 300 if kind=='live' else 86400,group=kind)
        except (CellBusy, SourceBusy, sqlite3.OperationalError):
            return Response(status=503, headers={'Retry-After': '2'})
        except (ValueError, requests.RequestException, GEOSException):
            return Response(status=502)
        encoded = request.accept_encodings['gzip'] > 0
        response = Response(payload if encoded else gzip.decompress(payload), mimetype='application/json')
        if encoded:
            response.headers['Content-Encoding'] = 'gzip'
        response.vary.add('Accept-Encoding')
        response.headers['X-Radar-Cell-Cache'] = 'HIT' if hit else 'MISS'
        response.headers['X-Radar-Cell-TTL'] = '300' if kind=='live' else '86400'
        return response
