import gzip
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from flask import Flask
import pytest

from services.planning_parcel_tiles import CellBusy, CellCache, bounds, install


def test_cell_bounds_are_fixed_and_country_bounded():
    assert bounds(104354, 61498)[0] > 106
    for xy in [(-1,0),(131072,0),(1,1)]:
        with pytest.raises(ValueError):
            bounds(*xy)


def test_shared_cache_reuses_across_instances_and_does_not_cache_failures(tmp_path):
    path=tmp_path/'cache.sqlite'
    first,second=CellCache(path),CellCache(path)
    calls=[]
    def load():
        calls.append(1)
        return {'hello':'world'}
    assert first.get('one',load,300)[1] is False
    value,hit=second.get('one',load,300)
    assert hit and json.loads(gzip.decompress(value))=={'hello':'world'}
    assert len(calls)==1
    def broken():
        raise ValueError('upstream failed')
    with pytest.raises(ValueError):
        first.get('broken',broken,300)
    assert second.get('broken',load,300)[1] is False


def test_single_flight_is_shared_and_cold_work_is_bounded(tmp_path):
    caches=[CellCache(tmp_path/'cache.sqlite') for _ in range(3)]
    started=threading.Event();release=threading.Event()
    def slow():
        started.set();release.wait(5);return {}
    with ThreadPoolExecutor(2) as pool:
        result=pool.submit(caches[0].get,'key',slow,300)
        assert started.wait(2)
        try:
            with pytest.raises(CellBusy):
                caches[1].get('key',lambda: {},300)
        finally:
            release.set()
        result.result()
    assert caches[2].get('key',lambda: pytest.fail('cache miss'),300)[1]


def test_route_strips_private_fields_and_warm_requests_never_hit_source(tmp_path):
    class Catalog:
        areas=[]
        calls=0
        def feature(self,identifier):
            return None
        def viewport(self,bbox):
            self.calls+=1
            return [dict(type='Feature',id=1,geometry={'type':'Polygon','coordinates':[[[bbox[0]+.0001,bbox[1]+.0001],[bbox[2]-.0001,bbox[1]+.0001],[bbox[2]-.0001,bbox[3]-.0001],[bbox[0]+.0001,bbox[1]+.0001]]]} ,
                         properties={'id':1,'sheet':'3','parcel':'4','owner':'secret','phone':'secret'})],1
    catalog=Catalog();app=Flask(__name__)
    install(app,catalog,None,tmp_path,'release')
    client=app.test_client();url='/api/planning/parcel-cells/release/snapshot/104354/61498.json'
    first=client.get(url,headers={'Accept-Encoding':'gzip'})
    assert first.status_code==200
    assert first.headers['Content-Encoding']=='gzip'
    assert json.loads(gzip.decompress(first.data))['features'][0]['properties']=={'id':1,'sheet':'3','parcel':'4'}
    assert client.get(url).headers['X-Radar-Cell-Cache']=='HIT'
    assert catalog.calls==1
    assert client.get(url+'?anything=1').status_code==404
    assert client.get(url.replace('release/','wrong/')).status_code==404


def test_warm_thousand_requests_do_not_repeat_source_work(tmp_path):
    cache=CellCache(tmp_path/'cache.sqlite')
    cache.get('cell',lambda:{'features':[]},300)
    with ThreadPoolExecutor(16) as pool:
        hits=list(pool.map(lambda _:cache.get('cell',lambda:pytest.fail('source called'),300)[1],range(1000)))
    assert all(hits)


def test_snapshot_does_not_wait_for_or_call_live_gis(tmp_path):
    class Catalog:
        areas=[]
        def viewport(self,bbox):return [],0
        def feature(self,identifier):return None
    class Live:
        def needs_viewport(self,*args):return True
        def viewport(self,*args):raise AssertionError('Snapshot must not contact GIS')
    app=Flask(__name__);install(app,Catalog(),Live(),tmp_path,'release')
    response=app.test_client().get('/api/planning/parcel-cells/release/snapshot/104354/61498.json')
    assert response.status_code==200 and response.json['needs_live'] is True


def test_cache_policy_is_exact_and_keeps_credentials_errors_and_originals_private(tmp_path):
    from services.planning_live import planning_response_headers
    import app as radar_app
    class Catalog:
        areas=[]
        def viewport(self,bbox):return [],0
        def feature(self,identifier):return None
    app=Flask(__name__)
    # Match production registration order: planning policy runs before generic headers.
    app.after_request(radar_app.add_response_headers)
    install(app,Catalog(),None,tmp_path,'release')
    app.add_url_rule('/api/planning/parcels/config.json', 'parcel_config', lambda: {'public':True})
    app.add_url_rule('/api/planning/catalog.json', 'planning_live_catalog', lambda: {'layers':[]})
    app.after_request(planning_response_headers)
    client=app.test_client();url='/api/planning/parcel-cells/release/snapshot/104354/61498.json'
    anonymous=client.get(url)
    assert anonymous.headers['Cache-Control']=='public, max-age=86400'
    assert 'X-Radar-Public-Cache' not in anonymous.headers
    assert client.get(url,headers={'Authorization':'Bearer test'}).headers['Cache-Control']=='private, no-store'
    client.set_cookie('radar_session','test')
    assert client.get(url).headers['Cache-Control']=='private, no-store'
    client.delete_cookie('radar_session')
    assert client.get(url.replace('snapshot/','bad/')).headers['Cache-Control']=='private, no-store'
    assert client.get('/api/planning/parcel-original/release/1.json').headers['Cache-Control']=='private, no-store'
    for path in ('/api/planning/parcels/config.json','/api/planning/catalog.json'):
        assert client.get(path).headers['Cache-Control']=='public, max-age=60'
        assert 'X-Radar-Public-Cache' not in client.get(path).headers
        assert client.get(path,headers={'Authorization':'Bearer test'}).headers['Cache-Control']=='private, no-store'
        client.set_cookie('radar_session','test')
        assert client.get(path).headers['Cache-Control']=='private, no-store'
        client.delete_cookie('radar_session')


def test_slow_live_loads_cannot_starve_snapshot_cache(tmp_path):
    cache=CellCache(tmp_path/'cache.sqlite');release=threading.Event()
    started=[threading.Event(),threading.Event()]
    def load(index):
        started[index].set();release.wait(5);return {}
    with ThreadPoolExecutor(2) as pool:
        work=[pool.submit(cache.get,str(i),lambda i=i:load(i),300,group='live') for i in range(2)]
        assert all(event.wait(2) for event in started)
        try:
            assert cache.get('snapshot',lambda:{},300,group='snapshot')[1] is False
            with pytest.raises(CellBusy):cache.get('third-live',lambda:{},300,group='live')
        finally:release.set()
        for result in work:result.result()


def test_original_geometry_is_exact_and_never_uses_remote_lookup(tmp_path):
    west,south,east,north=bounds(104354,61498)
    original=dict(type='Feature',id=10,properties={'area':100,'owner':'private'},geometry={
        'type':'Polygon','coordinates':[[[west,south],[west+.0001,south+.0000001],
        [east,south],[east,north],[west,north],[west,south]]]})
    class Catalog:
        areas=[]
        def viewport(self,bbox):return [original],1
        def feature(self,identifier):return original
    class Live:
        def needs_viewport(self,*args):return False
        def feature(self,*args):raise AssertionError('Must never call GIS on basic selection')
    app=Flask(__name__);install(app,Catalog(),Live(),tmp_path,'release')
    client=app.test_client()
    display=client.get('/api/planning/parcel-cells/release/snapshot/104354/61498.json').json['features'][0]
    assert display['display_only'] is True
    assert display['geometry']!=original['geometry']
    exact=client.get('/api/planning/parcel-original/release/10.json').json
    assert exact['geometry']==original['geometry']
    assert 'owner' not in exact['properties']
