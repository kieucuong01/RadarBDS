"""Production wiring must keep the loopback pilot private and snapshots usable."""
import hashlib
import json
import sqlite3

from flask import Flask
import pytest


def live_assets(tmp_path):
    from config.planning_parcels import PARCEL_AREAS
    from services.planning_assets import release_id
    from tests.test_planning_tiles import metadata
    staging = tmp_path/'staging'
    (staging/'metadata').mkdir(parents=True)
    with sqlite3.connect(staging/'parcels.sqlite') as conn:
        conn.executescript('CREATE TABLE areas(code TEXT PRIMARY KEY,metadata TEXT);'
                           'CREATE TABLE parcels(id INTEGER PRIMARY KEY,area TEXT,feature TEXT);'
                           'CREATE VIRTUAL TABLE bounds USING rtree(id,west,east,south,north);')
        for i,a in enumerate(PARCEL_AREAS,1):
            feature={'type':'Feature','id':i,'properties':{'id':i,'area_id':a['code'],
                'ward':a['ward'],'city':a['city'],'sheet':'1','parcel':'2','area':100},
                'geometry':{'type':'Polygon','coordinates':[[[106.61,11.02],[106.611,11.02],
                    [106.611,11.021],[106.61,11.02]]]}}
            row={'area_id':a['code'],'ward':a['ward'],'city':a['city'],'count':1,
                 'excluded_count':0,'source_count':1,'sample_id':i}
            conn.execute('INSERT INTO areas VALUES (?,?)',(a['code'],json.dumps(row)))
            conn.execute('INSERT INTO parcels VALUES (?,?,?)',(i,a['code'],json.dumps(feature)))
            conn.execute('INSERT INTO bounds VALUES (?,?,?,?,?)',(i,106.61,106.611,11.02,11.021))
    conn.close()
    for name in ('partition','urban_general','partition_supplement','urban_general_supplement'):
        (staging/'metadata'/f'{name}.json').write_text(json.dumps(metadata()))
    files={str(p.relative_to(staging)).replace('\\','/'):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
        'bytes':p.stat().st_size} for p in staging.rglob('*') if p.is_file()}
    config={'release':release_id(files),'files':files,'count':91,'areas':91}
    directory=tmp_path/'data/planning'/config['release'];directory.parent.mkdir(parents=True)
    staging.rename(directory)
    (tmp_path/'config').mkdir()
    (tmp_path/'config/planning_live_release.json').write_text(json.dumps(config))
    return directory,config


def test_live_is_opt_in_and_rejects_missing_or_invalid_assets(tmp_path,monkeypatch):
    from services.planning_live import install_live
    app=Flask('disabled');monkeypatch.delenv('RADAR_PLANNING_LIVE_ENABLED',raising=False)
    assert install_live(app,tmp_path) is False
    monkeypatch.setenv('RADAR_PLANNING_LIVE_ENABLED','1')
    assert install_live(app,tmp_path) is False
    folder,config=live_assets(tmp_path)
    (folder/'metadata/partition.json').write_text('{}')
    assert install_live(app,tmp_path) is False
    assert app.test_client().get('/api/planning/parcels/config.json').status_code==404


def test_live_routes_keep_source_scope_and_pdf_assets(tmp_path,monkeypatch):
    from services.planning_live import install_live,validate_assets
    from services.planning_tiles import NativeGISTiles
    from services.planning_parcels import PublicGIS
    from tests.test_planning_tiles import png,tan_an_tile
    folder,config=live_assets(tmp_path)
    validate_assets(tmp_path,verify_hashes=True)
    static=tmp_path/'static/maps/planning/overlays/old';static.mkdir(parents=True)
    (static/'catalog.json').write_text(json.dumps({'layers':[{'id':'old-gis','source':'gis'},
        {'id':'drawing','source':'document'}]}))
    app=Flask('live')
    app.config['PLANNING_OVERLAY_CONFIG']={'assetBase':'/static/maps/planning/overlays/old/',
        'catalogUrl':'/static/maps/planning/overlays/old/catalog.json'}
    monkeypatch.setenv('RADAR_PLANNING_LIVE_ENABLED','1')
    monkeypatch.setattr(NativeGISTiles,'fetch',lambda *a:png())
    monkeypatch.setattr(PublicGIS,'request',lambda self,path,**kw:
        [] if path == '/thong-tin-quy-hoach/dnm' else {'features': []})
    assert install_live(app,tmp_path) is True
    assert app.config['PLANNING_OVERLAY_CONFIG']['assetBase'].endswith('/old/')
    assert app.config['PLANNING_OVERLAY_CONFIG']['parcelBase']=='/api/planning/parcels'
    client=app.test_client()
    data=client.get('/api/planning/catalog.json').json
    assert next(a for a in data['layers'] if a['id']=='old-gis')['inspection_only']
    assert next(a for a in data['layers'] if a['id']=='drawing')['source']=='document'
    native=[a for a in data['layers'] if a.get('manifest',{}).get('source_kind')=='official_gis']
    assert len(native)==3
    assert all(a['manifest']['tile_template'].startswith('/api/planning/gis-tiles/') for a in native)
    reference=[a for a in data['layers'] if a.get('theme')=='land_use_2030']
    assert len(reference)==5 and all(a['source']=='guland' for a in reference)
    assert any(a['area_id']=='dong-nai-expanded' for a in reference)
    vision=[a for a in data['layers'] if a.get('theme')=='urban_vision_100']
    assert len(vision)==1 and vision[0]['manifest']['planning_status']=='draft'
    assert vision[0]['manifest']['min_native_zoom']==10
    assert vision[0]['manifest']['max_native_zoom']==19
    transport=[a for a in data['layers'] if a.get('theme')=='transport']
    assert len(transport)==2
    assert {a['source'] for a in transport}=={'gis','guland'}
    assert next(a for a in transport if a['source']=='gis')['manifest']['render_mode']=='geojson'
    assert next(a for a in transport if a['source']=='guland')['manifest']['max_native_zoom']==19
    response=client.get('/api/planning/parcels/config.json')
    assert len(response.json['areas'])==422 and response.json['count']==91
    assert response.json['count_scope']=='historic_binh_duong_snapshot'
    assert response.json['live_expanded'] is True
    assert response.headers['Cache-Control']=='private, no-store'
    assert client.get('/local-planning/parcels/config.json').status_code==404
    assert client.get('/api/planning/parcels/999999/planning.json').status_code==404
    assert client.get('/api/planning/parcels/1/planning.json?area=bad').status_code==404
    assert client.get('/api/planning/parcels/1/planning.json').status_code==200
    z,x,y=tan_an_tile()
    assert client.get(f'/api/planning/gis-tiles/partition/{z}/{x}/{y}.png').data==png()
    detailed=client.get(f'/api/planning/gis-tiles/detailed/{z}/{x}/{y}.png')
    assert detailed.status_code==200 and detailed.data==png()
    assert detailed.headers['Cache-Control']=='private, no-store'
    (folder/'parcels.sqlite').write_bytes(b'changed')
    with pytest.raises(ValueError):validate_assets(tmp_path,verify_hashes=True)


def test_planning_limiter_is_bounded_and_returns_backpressure():
    from services.planning_live import PlanningLimiter
    limiter=PlanningLimiter(max_keys=2)
    assert limiter.allow('one','tile',1,0)
    assert not limiter.allow('one','tile',1,1)
    assert limiter.allow('two','tile',1,1)
    assert limiter.allow('three','tile',1,1)
    assert len(limiter.entries)==2
    assert limiter.allow('three','tile',1,3601)
