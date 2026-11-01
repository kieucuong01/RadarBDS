from flask import Flask
import pytest

from services.map_label_tiles import OSMLabelTiles, install, valid_tile


TILE = b'\x1a\x08\x0a\x01x\x28\x80\x20\x78\x02'


@pytest.mark.parametrize('coords', [(13,13045,7681),(15,13045,7681),(14,-1,7681),(14,0,0),(14,16384,7681)])
def test_rejects_out_of_scope_tiles(coords):
    assert not valid_tile(*coords)


def test_all_overview_zoom_levels_are_supported():
    assert valid_tile(0,0,0)
    assert valid_tile(13,6522,3840)
    assert valid_tile(14,13045,7681)


def test_reuses_tile_and_bounds_cache_without_forwarding_cookies(monkeypatch):
    cache = OSMLabelTiles(max_entries=1)
    calls = []
    class Reply:
        headers = {'Content-Type':'application/vnd.mapbox-vector-tile'}
        def raise_for_status(self): pass
        def iter_content(self, size): yield TILE
        def __enter__(self): return self
        def __exit__(self, *args): pass
    for session in list(cache.sessions.queue):
        monkeypatch.setattr(session, 'get', lambda url, **kw: (calls.append((url,kw)) or Reply()))
    assert cache.get(14,13045,7681) == TILE
    assert cache.get(14,13045,7681) == TILE
    assert len(calls) == 1
    assert calls[0][0] == 'https://vector.openstreetmap.org/shortbread_v1/14/13045/7681.mvt'
    assert calls[0][1]['allow_redirects'] is False
    assert 'cookies' not in calls[0][1]
    cache.get(14,13044,7681)
    assert len(cache.entries) == 1


def test_invalid_upstream_never_enters_cache(monkeypatch):
    cache = OSMLabelTiles()
    class Reply:
        headers = {'Content-Type':'text/html'}
        def raise_for_status(self): pass
        def iter_content(self, size): yield b'<html>Error</html>'
        def __enter__(self): return self
        def __exit__(self, *args): pass
    for session in list(cache.sessions.queue):
        monkeypatch.setattr(session, 'get', lambda *a, **kw: Reply())
    with pytest.raises(ValueError): cache.get(14,13045,7681)
    assert not cache.entries
    assert cache.sessions.qsize() == 2


def test_route_cache_and_backpressure(monkeypatch):
    app = Flask(__name__)
    cache = install(app)
    monkeypatch.setattr(cache, 'get', lambda *args: TILE)
    client = app.test_client()
    response = client.get('/api/map-labels/osm/14/13045/7681.mvt')
    assert response.status_code == 200
    assert 'max-age=604800' in response.headers['Cache-Control']
    assert response.mimetype == 'application/vnd.mapbox-vector-tile'
    assert client.get('/api/map-labels/osm/14/0/0.mvt').status_code == 400
    def busy(*args): raise TimeoutError()
    monkeypatch.setattr(cache, 'get', busy)
    response = client.get('/api/map-labels/osm/14/13045/7681.mvt')
    assert response.status_code == 503
    assert response.headers['Retry-After'] == '2'
    assert 'no-store' in response.headers['Cache-Control']
