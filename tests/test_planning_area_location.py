from pathlib import Path
import json
from flask import Flask
import pytest
from services.planning_area_location import resolve_area


@pytest.mark.parametrize('lat,lon,province,district',[
    (11.022086,106.617125,'binh-duong','718'),
    (10.78,106.69,'hcm','770'),(21.028,105.834,'ha-noi','006')])
def test_existing_old_boundary_snapshot_resolves_locality(lat,lon,province,district):
    assert resolve_area(Path.cwd(),lat,lon)==dict(matched=True,province=province,district=district)


def test_polygon_holes_are_not_treated_as_bbox_matches(tmp_path):
    config=tmp_path/'config';config.mkdir()
    province=dict(id='test',bounds=[[0,0],[4,4]],districts=[dict(id='1',name='Huyện Một')])
    (config/'planning_landuse_areas.json').write_text(json.dumps(dict(provinces=[province])))
    folder=tmp_path/'static/data/admin_vn_legacy/test';folder.mkdir(parents=True)
    feature=dict(properties=dict(bounds=[[0,0],[4,4]],district='Huyện Một'),
                 geometry=dict(type='Polygon',coordinates=[[[0,0],[4,0],[4,4],[0,4],[0,0]],[[1,1],[3,1],[3,3],[1,3],[1,1]]]))
    (folder/'overview.json').write_text(json.dumps(dict(features=[feature])))
    assert resolve_area(tmp_path,2,2)==dict(matched=False)
    assert resolve_area(tmp_path,.5,.5)==dict(matched=True,province='test',district='1')


def test_area_location_post_validation_and_private_no_store(tmp_path,monkeypatch):
    from tests.test_planning_live import live_assets
    from services.planning_live import install_live
    live_assets(tmp_path);app=Flask('area-location');monkeypatch.setenv('RADAR_PLANNING_LIVE_ENABLED','1')
    assert install_live(app,tmp_path)
    seen=[]
    monkeypatch.setattr('services.planning_area_location.resolve_area',lambda *args:seen.append(args) or dict(matched=False))
    client=app.test_client()
    for data in [dict(latitude=True,longitude=106),dict(latitude=100,longitude=106),dict(latitude=1,longitude='106'),dict(latitude=10**400,longitude=106),dict(latitude=11,longitude=106,extra=1)]:
        assert client.post('/api/planning/locate-area.json',json=data).status_code==400
    assert not seen
    response=client.post('/api/planning/locate-area.json',json=dict(latitude=11,longitude=106))
    assert response.status_code==200 and response.json==dict(matched=False)
    assert response.headers['Cache-Control']=='private, no-store'
    assert 'X-Radar-Public-Cache' not in response.headers
    assert client.get('/api/planning/locate-area.json').status_code==405
