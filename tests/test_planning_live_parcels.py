"""On-demand public cadastral data must remain bounded, scoped and anonymous."""
from copy import deepcopy

import pytest

from services.planning_live_parcels import LiveParcels, SourceBusy


def source_row(identifier=2821079, code='26740', district='760', west=106.7005):
    return {'attributes': {'OBJECTID': identifier, 'MaPhuongXa': code, 'MaQuanHuyen': district,
            'SoTo': '40', 'SoThua': '74', 'DienTich': 71.7, 'TenChuSoHuu': 'PRIVATE',
            'CCCD_CMND': 'PRIVATE'}, 'geometry': {'rings': [[[west,10.7755],
            [west+.0001,10.7755],[west+.0001,10.7756],[west,10.7756],[west,10.7755]]]}}


class Source:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows if rows is not None else [source_row()]

    def request(self, path, *, params):
        self.calls.append((path, params))
        return {'spatialReference': {'wkid': 4326}, 'features': deepcopy(self.rows)}


BBOX = (106.700,10.775,106.702,10.777)


def test_viewport_uses_native_spatial_query_and_strips_personal_fields():
    source = Source()
    live = LiveParcels(client=source)
    result = live.viewport(BBOX)
    assert result['features'][0]['properties']['area_id'] == '26740'
    assert result['features'][0]['properties']['sheet'] == '40'
    assert 'PRIVATE' not in str(result)
    params = source.calls[0][1]
    assert params['outFields'] == 'OBJECTID,SoTo,SoThua,DienTich,MaPhuongXa,MaQuanHuyen'
    assert params['geometryType'] == 'esriGeometryEnvelope'
    assert params['resultRecordCount'] == 1000
    assert 'NOT IN' in params['where']
    assert live.viewport(BBOX) == result and len(source.calls) == 1
    assert live.feature(2821079, '26740')['id'] == 2821079
    assert live.feature(2821079, '26551') is None


@pytest.mark.parametrize('change', ['outside', 'legacy', 'duplicate', 'wrong_district', 'sr'])
def test_spatial_membership_and_geometry_fail_closed(change):
    source = Source()
    if change == 'outside': source.rows = [source_row(west=107.3)]
    if change == 'legacy': source.rows = [source_row(code='25765', district='718')]
    if change == 'duplicate': source.rows *= 2
    if change == 'wrong_district': source.rows[0]['attributes']['MaQuanHuyen'] = '748'
    if change == 'sr':
        original = source.request
        def wrong(*args, **kwargs):
            data = original(*args, **kwargs); data['spatialReference'] = {'wkid': 3857}; return data
        source.request = wrong
    with pytest.raises(ValueError): LiveParcels(client=source).viewport(BBOX)


def test_invalid_geometry_is_excluded_without_repair_and_adapter_is_validated():
    source = Source()
    source.rows[0]['geometry']['rings'][0][1][0] = float('nan')
    result = LiveParcels(client=source).viewport(BBOX)
    assert result['features'] == [] and result['excluded_count'] == 1
    source = Source()
    original = source.request
    def fallback(path, **kw):
        if path.endswith('/MapServer/0/query'): raise ValueError('source native unavailable')
        return original(path, **kw)
    source.request = fallback
    result = LiveParcels(client=source).viewport(BBOX)
    assert result['query_endpoint'] == '/rest/thua-dat/query'
    assert result['features'][0]['id'] == 2821079


def test_search_is_ward_scoped_escaped_and_checks_returned_identifiers():
    source = Source()
    live = LiveParcels(client=source)
    result = live.search('26740', '40', '74')
    assert len(result['features']) == 1 and result['matched'] == 1
    assert "MaPhuongXa = '26740'" in source.calls[0][1]['where']
    with pytest.raises(ValueError): live.search('26740', "40' OR 1=1--", '74')
    assert "40'' OR 1=1--" in source.calls[-1][1]['where']


def test_empty_source_is_distinct_from_failure_and_busy_requests():
    live = LiveParcels(client=Source([]))
    assert live.viewport(BBOX)['features'] == []
    assert live.viewport(BBOX)['truncated'] is False
    assert live.gate.acquire(False)
    with pytest.raises(SourceBusy): live.viewport((106.701,10.775,106.703,10.777))
    live.gate.release()


def test_cache_byte_budget_and_source_cap_are_enforced():
    live = LiveParcels(client=Source(), cache_bytes=20)
    live.viewport(BBOX)
    assert live.cache_size <= 20 and not live.cache
    with pytest.raises(ValueError): LiveParcels(client=Source([source_row()]*1001)).viewport(BBOX)


def test_hybrid_routes_and_lookup_failures_are_controlled(tmp_path, monkeypatch):
    from flask import Flask
    from services.planning_parcel_catalog import build_catalog, install_catalog
    from services.planning_parcels import PublicGIS
    from tests.test_planning_parcel_catalog import snapshot
    path = build_catalog(tmp_path, [snapshot(tmp_path,'25765','Tân An','Thủ Dầu Một',33013,106.65)])
    source = Source()
    live = LiveParcels(client=source)
    monkeypatch.setattr(PublicGIS, 'request', lambda *a, **kw: [])
    app = Flask('hybrid'); install_catalog(app, path, expanded=live)
    client = app.test_client(); base = '/local-planning/parcels'
    assert len(client.get(base+'/config.json').json['areas']) == 422
    response = client.get(base+'/viewport.json?bbox='+','.join(map(str,BBOX)))
    assert response.status_code == 200 and response.json['features'][0]['id'] == 2821079
    assert client.get(base+'/2821079/planning.json?area=26740').json['parcel']['id'] == 2821079
    assert client.get(base+'/2821079/planning.json?area=26551').status_code == 404
    assert client.get(base+'/33013/planning.json?area=25765').status_code == 200
    assert client.get(base+'/sample.json?area=26740').json['id'] == 2821079
    assert client.get(base+'/search.json?area=26740&sheet=40&parcel=74').json['matched'] == 1
    before = len(source.calls)
    assert client.get(base+'/viewport.json?bbox=106.65,11.02,106.651,11.021').status_code == 200
    assert len(source.calls) == before, 'Interior legacy viewport must not require remote GIS'
    def broken(*args, **kwargs): raise ValueError('private diagnostic')
    source.request = broken
    result = client.get(base+'/999999/planning.json?area=26740')
    assert result.status_code == 502 and 'private diagnostic' not in result.text
    assert client.get(base+'/viewport.json?bbox=107.084,10.353,107.085,10.354').status_code == 502
    assert client.get(base+'/viewport.json?bbox=106,8,109,12').status_code == 400
