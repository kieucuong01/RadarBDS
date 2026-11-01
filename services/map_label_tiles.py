"""Fixed-source OSM Shortbread gateway for satellite labels, within the site CSP."""
from collections import OrderedDict
import math
import queue
import threading
import time

import requests

TTL = 7 * 24 * 3600
MAX_TILE_BYTES = 1_000_000


def valid_tile(z, x, y):
    if z != 14 or not (0 <= x < 2**z and 0 <= y < 2**z):
        return False
    west, east = x / 2**z * 360 - 180, (x+1) / 2**z * 360 - 180
    north = math.degrees(math.atan(math.sinh(math.pi * (1-2*y/2**z))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1-2*(y+1)/2**z))))
    return west < 110 and east > 102 and south < 24 and north > 8


class OSMLabelTiles:
    def __init__(self, max_entries=256):
        self.entries = OrderedDict()
        self.max_entries = max_entries
        self.total_bytes = 0
        self.lock = threading.Lock()
        self.inflight = set()
        self.sessions = queue.LifoQueue()
        for _ in range(2):
            session = requests.Session()
            session.trust_env = False
            session.headers.update({'User-Agent':'RadarBDS/1.0 (+https://radarbds.vn)',
                                    'Referer':'https://radarbds.vn/'})
            self.sessions.put(session)

    def get(self, z, x, y):
        if not valid_tile(z,x,y): raise ValueError('Invalid tile')
        key = (z,x,y)
        with self.lock:
            previous = self.entries.pop(key,None)
            if previous:
                self.total_bytes -= len(previous[1])
                if time.monotonic()-previous[0] < TTL:
                    self.entries[key] = previous
                    self.total_bytes += len(previous[1])
                    return previous[1]
            if key in self.inflight: raise TimeoutError('Tile already loading')
            self.inflight.add(key)
        session = None
        try:
            try: session = self.sessions.get_nowait()
            except queue.Empty: raise TimeoutError('Label source busy') from None
            url = f'https://vector.openstreetmap.org/shortbread_v1/{z}/{x}/{y}.mvt'
            with session.get(url,timeout=(3,8),stream=True,allow_redirects=False) as response:
                response.raise_for_status()
                if response.headers.get('Content-Type','').split(';')[0] not in {
                    'application/vnd.mapbox-vector-tile','application/x-protobuf','application/octet-stream'}:
                    raise ValueError('Not a vector tile')
                chunks = []
                size = 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_TILE_BYTES: raise ValueError('Tile exceeds size limit')
                    chunks.append(chunk)
                payload = b''.join(chunks)
                if not payload or payload[0] != 0x1a: raise ValueError('Invalid vector tile')
            with self.lock:
                self.entries[key] = (time.monotonic(),payload)
                self.total_bytes += len(payload)
                while len(self.entries)>self.max_entries or self.total_bytes>32_000_000:
                    _,(_,evicted) = self.entries.popitem(last=False)
                    self.total_bytes -= len(evicted)
            return payload
        finally:
            if session is not None:
                session.cookies.clear()
                self.sessions.put(session)
            with self.lock: self.inflight.discard(key)


def install(app):
    from flask import make_response
    from services.planning_live import PlanningLimiter
    from auth.core import client_ip_from_request
    cache = OSMLabelTiles()
    limiter = PlanningLimiter()
    app.extensions['osm_label_tiles'] = cache

    @app.get('/api/map-labels/osm/<int:z>/<int:x>/<int:y>.mvt')
    def osm_label_tile(z,x,y):
        if not valid_tile(z,x,y): return ('Invalid tile',400,{'Cache-Control':'no-store'})
        if not limiter.allow(client_ip_from_request(),'osm-labels',1800):
            return ('Too many requests',429,{'Cache-Control':'no-store','Retry-After':'60'})
        try:
            response = make_response(cache.get(z,x,y))
            response.mimetype = 'application/vnd.mapbox-vector-tile'
            response.headers['Cache-Control'] = f'public, max-age={TTL}'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            return response
        except TimeoutError:
            return ('Map labels busy',503,{'Cache-Control':'no-store','Retry-After':'2'})
        except (requests.RequestException, ValueError):
            return ('Map labels unavailable',502,{'Cache-Control':'no-store'})
    return cache
