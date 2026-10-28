import io
import json
import math
from pathlib import Path

from flask import Flask
from PIL import Image
import pytest


def png():
    output = io.BytesIO()
    Image.new('RGBA',(256,256),(180,120,30,255)).save(output,format='PNG')
    return output.getvalue()


def tan_an_tile(z=19):
    return (z,int((106.6168+180)/360*2**z),
            int((1-math.asinh(math.tan(math.radians(11.019)))/math.pi)/2*2**z))


def metadata():
    return {'tileInfo':{'rows':256,'cols':256,'origin':{'x':-20037508.342787,'y':20037508.342787},
        'spatialReference':{'wkid':102100,'latestWkid':3857},
        'lods':[{'level':i,'resolution':156543.03392804097/2**i} for i in range(24)]}}


def test_native_xyz_grid_aligns_neighbors_and_bounds_are_validated():
    from services.planning_tiles import tile_bounds, validate_grid
    z,x,y = tan_an_tile()
    left = tile_bounds(z,x,y); right = tile_bounds(z,x+1,y); below = tile_bounds(z,x,y+1)
    assert left[2] == pytest.approx(right[0],abs=1e-7)
    assert left[1] == pytest.approx(below[3],abs=1e-7)
    assert left[2]-left[0] == pytest.approx(left[3]-left[1],rel=1e-9)
    data=metadata();validate_grid(data)
    data['tileInfo']['origin']['x'] += 100
    with pytest.raises(ValueError): validate_grid(data)
    for args in ((7,1,1),(24,1,1),(19,-1,3),(19,2**19,3)):
        with pytest.raises(ValueError): tile_bounds(*args)


def test_cached_gateway_keeps_exact_source_bytes_and_is_private(tmp_path, monkeypatch):
    from services.planning_tiles import NativeGISTiles, install_tiles
    from scripts.run_planning_pilot import install_pilot
    payload = png(); calls = []
    folder=tmp_path/'tiles'/'metadata';folder.mkdir(parents=True)
    for theme in ('partition','urban_general','partition_supplement','urban_general_supplement'):
        (folder/f'{theme}.json').write_text(json.dumps(metadata()),encoding='utf8')
    def fetch(self,theme,z,x,y):
        calls.append((theme,z,x,y)); return payload
    monkeypatch.setattr(NativeGISTiles,'fetch',fetch)
    cache = NativeGISTiles(tmp_path/'tiles')
    key = ('urban_general',*tan_an_tile())
    assert cache.get(*key) == payload and cache.get(*key) == payload
    assert len(calls) == 1
    with pytest.raises(ValueError): cache.get('../../bad',*tan_an_tile())
    with pytest.raises(LookupError): cache.get('partition',19,1,1)
    app = Flask('tiles');install_pilot(app,tmp_path);install_tiles(app,tmp_path/'tiles')
    client = app.test_client(); z,x,y=tan_an_tile()
    response = client.get(f'/local-planning/gis-tiles/urban_general/{z}/{x}/{y}.png')
    assert response.status_code == 200 and response.data == payload
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert client.get(f'/local-planning/gis-tiles/urban_general/{z}/{x}/{y}.png',headers={'Host':'evil.invalid'}).status_code == 404
    assert client.get('/local-planning/gis-tiles/unknown/19/1/1.png').status_code == 400
    catalog=client.get('/local-planning/catalog.json').json
    native=[x for x in catalog['layers'] if x.get('manifest',{}).get('source_kind')=='official_gis']
    assert {x['theme'] for x in native} == {'partition','urban_general','detailed'}
    assert all(x['manifest']['tile_size']==256 and x['source']=='gis' for x in native)


def test_gateway_rejects_non_native_images_and_bounds_cache_size(tmp_path,monkeypatch):
    from services.planning_tiles import NativeGISTiles
    payload=png()
    monkeypatch.setattr(NativeGISTiles,'fetch',lambda *args:payload)
    cache=NativeGISTiles(tmp_path,max_entries=2)
    z,x,y=tan_an_tile()
    for col in range(x,x+3): cache.get('partition',z,col,y)
    assert len(list(tmp_path.rglob('*.png')))<=2
    monkeypatch.setattr(NativeGISTiles,'fetch',lambda *args:b'not an image')
    with pytest.raises(ValueError): cache.get('partition',z,x+5,y)


def test_public_tile_transport_reuses_session_and_retries_one_transient_failure(tmp_path,monkeypatch):
    import queue
    import requests
    from services.planning_tiles import NativeGISTiles
    cache=NativeGISTiles(tmp_path);cache.verified=True;payload=png();calls=[]
    class Response:
        status_code=200
        content=payload
    class Session:
        def get(self,url,**kwargs):
            calls.append(url)
            if len(calls)==1:raise requests.ReadTimeout('temporary')
            return Response()
    cache.sessions=queue.LifoQueue();session=Session();cache.sessions.put(session)
    def broken(*args,**kwargs):raise requests.ReadTimeout('old one-shot transport')
    monkeypatch.setattr('services.planning_tiles.requests.get',broken)
    monkeypatch.setattr('services.planning_tiles.time.sleep',lambda seconds:None)
    assert cache.fetch('urban_general',*tan_an_tile())==payload
    assert len(calls)==2 and calls[0]==calls[1]
    assert cache.sessions.get_nowait() is session


def test_source_service_change_never_reuses_an_old_collection_tile(tmp_path,monkeypatch):
    from services.planning_tiles import NativeGISTiles, SERVICES
    calls=[]
    def fetch(self,theme,*coords):
        calls.append(SERVICES[theme]);return png()
    monkeypatch.setattr(NativeGISTiles,'fetch',fetch)
    cache=NativeGISTiles(tmp_path);key=('partition',*tan_an_tile())
    cache.get(*key)
    monkeypatch.setitem(SERVICES,'partition','AnotherVerifiedSource')
    cache.get(*key)
    assert len(calls)==2


@pytest.mark.parametrize('theme',['partition','urban_general','detailed'])
def test_supplement_fills_only_source_gaps_without_scaling(tmp_path,monkeypatch,theme):
    from services.planning_tiles import NativeGISTiles,SERVICES,SUPPLEMENTS
    foreground=Image.new('RGBA',(256,256),(0,0,0,0))
    foreground.putpixel((10,10),(255,0,0,255))
    output=io.BytesIO();foreground.save(output,format='PNG');primary=output.getvalue()
    background=png();calls=[]
    def fetch(self,session,service,*coords):
        calls.append(service);return primary if len(calls)==1 else background
    monkeypatch.setattr(NativeGISTiles,'_fetch_service',fetch,raising=False)
    def no_network(*args,**kwargs):raise AssertionError('Unit test must not use the network')
    monkeypatch.setattr(NativeGISTiles,'_public_get',no_network)
    cache=NativeGISTiles(tmp_path);cache.verified=True
    result=Image.open(io.BytesIO(cache.fetch(theme,*tan_an_tile()))).convert('RGBA')
    assert result.size==(256,256)
    assert result.getpixel((10,10))==(255,0,0,255)
    assert result.getpixel((11,10))==(180,120,30,255)
    assert calls==[SERVICES[theme],SUPPLEMENTS[theme]]


@pytest.mark.parametrize('lat,lon', [(10.776,106.701),(10.412,106.954),(10.353,107.084),(10.536,107.405),(8.686,106.61)])
def test_partition_native_tiles_cover_expanded_hcm_without_widening_general(tmp_path, monkeypatch, lat, lon):
    from services.planning_tiles import NativeGISTiles, native_layers
    z=15
    x=int((lon+180)/360*2**z)
    y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
    payload=png()
    monkeypatch.setattr(NativeGISTiles,'fetch',lambda *args:payload)
    cache=NativeGISTiles(tmp_path)
    assert cache.get('partition',z,x,y)==payload
    assert cache.get('detailed',z,x,y)==payload
    if lat<10.75 or lon>107.1:
        with pytest.raises(LookupError):
            cache.get('urban_general',z,x,y)
    layer=next(layer for layer in native_layers() if layer['theme']=='partition')
    south,west=layer['manifest']['bounds'][0];north,east=layer['manifest']['bounds'][1]
    assert south<lat<north and west<lon<east
    assert layer['city']=='TP.HCM mới'


def test_packaged_detailed_grids_are_verified_without_mutating_parcel_release(tmp_path, monkeypatch):
    import services.planning_tiles as tiles
    folder=tmp_path/'metadata';folder.mkdir()
    for name in ('partition','urban_general','partition_supplement','urban_general_supplement'):
        (folder/f'{name}.json').write_text(json.dumps(metadata()),encoding='utf8')
    assert tiles.NativeGISTiles(tmp_path/'cache',metadata_directory=folder).verified
    grids=tmp_path/'grids';grids.mkdir()
    for name in ('detailed','detailed_supplement'):
        data=json.loads((tiles.PACKAGED_GRID_DIR/f'{name}.json').read_text(encoding='utf8'))
        assert data['service']==tiles.METADATA_SERVICES[name]
        tiles.validate_grid(data)
        (grids/f'{name}.json').write_text(json.dumps(data),encoding='utf8')
    monkeypatch.setattr(tiles,'PACKAGED_GRID_DIR',grids)
    path=grids/'detailed.json';data=json.loads(path.read_text())
    data['source_url']='https://example.invalid/other-service'
    path.write_text(json.dumps(data))
    assert not tiles.NativeGISTiles(tmp_path/'cache',metadata_directory=folder).verified
    assert not (folder/'detailed.json').exists(), 'Do not alter the immutable parcel asset metadata'
