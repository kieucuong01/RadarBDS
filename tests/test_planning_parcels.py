import json

from flask import Flask
import pytest
from shapely.geometry import shape

from scripts.run_planning_pilot import install_pilot
from services.planning_parcels import PublicGIS, esri_geometry, install_parcel_pilot, planning_info


def square(west, south, width):
    return [[west, south], [west+width, south], [west+width, south+width], [west, south+width], [west, south]]


def test_esri_rings_preserve_disconnected_parts_holes_and_islands():
    rings = [square(106.61, 11.02, .01), square(106.612, 11.022, .006),
             square(106.614, 11.024, .002), square(106.64, 11.02, .001)]
    geometry = esri_geometry(rings)
    assert geometry['type'] == 'MultiPolygon'
    assert shape(geometry).is_valid
    assert len(geometry['coordinates']) == 3
    assert geometry['coordinates'][0] == rings[:2]
    assert geometry['coordinates'][1] == [rings[2]]


def test_planning_allowlist_keeps_raw_indicators_and_removes_internal_fields():
    value = planning_info([{'tenLoaiQuyHoach': 'Quy hoạch phân khu', 'doAns': [{
        'tenDuAn': 'Tân An', 'soQD': '1271/QĐ-UBND', 'dienTich': 1748.9, 'private': 'secret',
        'phanKhuChucNangs': [{'mucDichSuDungDat': 'Nhóm nhà ở', 'heSoSuDungDat': '0-05',
                             'shape': {'type': 'Polygon'}, 'owner': 'private', 'dienTich': 1748.9}]}]}])
    assert value[0]['zones'][0]['heSoSuDungDat'] == '0-05'
    assert value[0]['intersection_area'] == 1748.9
    assert 'secret' not in json.dumps(value) and 'owner' not in json.dumps(value)
    assert 'shape' not in value[0]['zones'][0]
    with pytest.raises(ValueError):
        planning_info([{'doAns': 'wrong'}])


def test_public_client_does_not_accept_arbitrary_remote_paths():
    with pytest.raises(ValueError, match='Unsupported'):
        PublicGIS().request('https://example.com/')
    assert list(PublicGIS.packets('2:402:41')) == ['40', '41']
    with pytest.raises(ValueError):
        list(PublicGIS.packets('30:short'))


def test_local_parcel_routes_are_bounded_private_and_scope_checked(tmp_path, monkeypatch):
    geometry = {'type': 'Polygon', 'coordinates': [square(106.61, 11.02, .001)]}
    feature = {'type': 'Feature', 'id': 33013, 'properties': {'id': 33013, 'sheet': '17', 'parcel': '13', 'area': 100},
               'geometry': geometry}
    (tmp_path/'parcels.geojson').write_text(json.dumps({'ward': 'Tân An', 'features': [feature], 'captured_at': '2026-10-27'}))
    calls = []
    def query(self, path, **kwargs):
        calls.append((path, kwargs))
        return [{'tenLoaiQuyHoach': 'Quy hoạch phân khu', 'doAns': []}]
    monkeypatch.setattr(PublicGIS, 'request', query)
    app = Flask(__name__)
    install_pilot(app, tmp_path)
    install_parcel_pilot(app, tmp_path)
    client = app.test_client()
    url = '/local-planning/parcels/viewport.json'
    for bbox in ('nan,11,106.7,11.1', '106.4,11,106.8,11.2', 'invalid'):
        assert client.get(url, query_string={'bbox': bbox}).status_code == 400
    response = client.get(url, query_string={'bbox': '106.605,11.015,106.62,11.03'})
    assert response.status_code == 200 and len(response.json['features']) == 1
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert client.get(url, query_string={'bbox': '106.605,11.015,106.62,11.03'}, headers={'Host': 'evil.com'}).status_code == 404
    assert client.get('/local-planning/parcels/999/planning.json').status_code == 404
    for _ in range(2):
        assert client.get('/local-planning/parcels/33013/planning.json').status_code == 200
    assert len(calls) == 1 and calls[0][1]['body'] == {'objectId': 33013}
    def broken(self, path, **kwargs):
        raise ValueError('upstream error')
    monkeypatch.setattr(PublicGIS, 'request', broken)
    other = Flask('other')
    install_pilot(other, tmp_path)
    install_parcel_pilot(other, tmp_path)
    result = other.test_client().get('/local-planning/parcels/33013/planning.json')
    assert result.status_code == 502 and 'upstream error' not in result.text
