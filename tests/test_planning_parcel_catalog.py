import json

import pytest
from flask import Flask

from services.planning_parcels import PublicGIS, capture


def test_partitioned_ids_never_trust_a_silently_capped_page():
    from services.planning_parcels import complete_identifiers
    class Source:
        def request(self, path, *, params):
            import re
            ids = [3, 8, 12, 19, 27, 38, 45]
            for op, value in re.findall(r'OBJECTID (>=|<) (\d+)', params['where']):
                ids = [i for i in ids if (i >= int(value) if op == '>=' else i < int(value))]
            return {'count': len(ids)} if params.get('returnCountOnly') else {'objectIds': ids[:3]}
    assert complete_identifiers(Source(), 'fixed ward', limit=3) == [3, 8, 12, 19, 27, 38, 45]
    class Broken(Source):
        def request(self, path, *, params):
            if params.get('returnCountOnly'):
                return {'count': 7}
            return {'objectIds': [3, 3]}
    with pytest.raises(ValueError):
        complete_identifiers(Broken(), 'fixed ward', limit=3)


def snapshot(directory, code, ward, city, identifier, west):
    from hashlib import sha256
    target = directory/code
    target.mkdir()
    feature = {'type': 'Feature', 'id': identifier,
               'properties': {'id': identifier, 'area_id': code, 'ward': ward, 'city': city,
                              'sheet': '1', 'parcel': '2', 'area': 100},
               'geometry': {'type': 'Polygon', 'coordinates': [[[west,11.02],[west+.001,11.02],
                            [west+.001,11.021],[west,11.021],[west,11.02]]]}}
    data = {'ward': ward, 'city': city, 'area_id': code, 'count': 1, 'source_count': 1,
            'excluded_count': 0, 'captured_at': '2026-10-27', 'features': [feature]}
    raw = json.dumps(data).encode()
    (target/'parcels.geojson').write_bytes(raw)
    metadata = {k:v for k,v in data.items() if k != 'features'}
    metadata['sha256'] = sha256(raw).hexdigest()
    (target/'metadata.json').write_text(json.dumps(metadata), encoding='utf8')
    return {'code': code, 'ward': ward, 'city': city, 'district': '718'}


def test_spatial_catalog_queries_only_viewport_and_checks_ward_membership(tmp_path, monkeypatch):
    from services.planning_parcel_catalog import build_catalog, ParcelCatalog, install_catalog
    areas = [snapshot(tmp_path, '25765', 'Tân An', 'Thủ Dầu Một', 33013, 106.61),
             snapshot(tmp_path, '25813', 'Mỹ Phước', 'Bến Cát', 900, 106.65)]
    path = build_catalog(tmp_path, areas)
    catalog = ParcelCatalog(path)
    assert len(catalog.areas) == 2
    features, count = catalog.viewport((106.609,11.019,106.612,11.022))
    assert count == 1 and features[0]['properties']['ward'] == 'Tân An'
    assert catalog.feature(900, '25765') is None
    assert catalog.feature(900, '25813')['properties']['city'] == 'Bến Cát'
    calls = []
    def query(self, path, **kwargs):
        calls.append(kwargs['body']['objectId'])
        return []
    monkeypatch.setattr(PublicGIS, 'request', query)
    app = Flask('catalog')
    install_catalog(app, path)
    client = app.test_client()
    assert client.get('/local-planning/parcels/config.json').json['count'] == 2
    assert client.get('/local-planning/parcels/900/planning.json?area=25765').status_code == 404
    assert client.get('/local-planning/parcels/900/planning.json?area=25813').status_code == 200
    assert calls == [900]
    assert client.get('/local-planning/parcels/sample.json?area=25813').json['id'] == 900
    assert client.get('/local-planning/parcels/viewport.json?bbox=106,11,107,12').status_code == 400


def test_catalog_does_not_replace_previous_good_index_on_incomplete_capture(tmp_path):
    from services.planning_parcel_catalog import build_catalog
    areas = [snapshot(tmp_path, '25765', 'Tân An', 'Thủ Dầu Một', 33013, 106.61)]
    path = build_catalog(tmp_path, areas)
    before = path.read_bytes()
    (tmp_path/'25765'/'parcels.geojson').write_text('{}')
    with pytest.raises(ValueError):
        build_catalog(tmp_path, areas)
    assert path.read_bytes() == before


def test_multi_area_parcel_browser_runtime():
    import subprocess
    result = subprocess.run(['node','tests/planning_parcels_runtime.cjs'],capture_output=True,text=True)
    assert result.returncode == 0, result.stdout+result.stderr


def test_exact_sheet_parcel_search_is_indexed_scoped_and_bounded(tmp_path):
    import sqlite3
    from services.planning_parcel_catalog import build_catalog, ParcelCatalog, install_catalog
    areas = [snapshot(tmp_path, '25765', 'Tân An', 'Thủ Dầu Một', 33013, 106.61),
             snapshot(tmp_path, '25813', 'Mỹ Phước', 'Bến Cát', 900, 106.65)]
    path = build_catalog(tmp_path, areas)
    catalog = ParcelCatalog(path)
    features,count = catalog.search('25813','1','2')
    assert count == 1 and features[0]['id'] == 900
    assert catalog.search('25765','1','2')[0][0]['id'] == 33013
    assert catalog.search('25813',"1' OR 1=1--",'2') == ([],0)
    with sqlite3.connect(path) as conn:
        sql = "SELECT feature FROM parcels WHERE area=? AND trim(CAST(json_extract(feature,'$.properties.sheet') AS TEXT))=? AND trim(CAST(json_extract(feature,'$.properties.parcel') AS TEXT))=?"
        plan = conn.execute('EXPLAIN QUERY PLAN '+sql,('25813','1','2')).fetchall()
        assert any('parcel_lookup' in row[-1] for row in plan)
        feature = catalog.feature(900)
        for identifier in range(901,925):
            feature['id'] = feature['properties']['id'] = identifier
            conn.execute('INSERT INTO parcels VALUES (?,?,?)',(identifier,'25813',json.dumps(feature)))
    matches,count = catalog.search('25813','1','2')
    assert len(matches) == 20 and count == 25
    app = Flask('search')
    install_catalog(app,path)
    client = app.test_client()
    url = '/local-planning/parcels/search.json'
    result = client.get(url,query_string={'area':'25813','sheet':'1','parcel':'2'})
    assert result.status_code == 200 and result.json['truncated'] is True
    for query in ({},{'area':'25813','sheet':'','parcel':'2'},
                  {'area':'25813','sheet':'1'*33,'parcel':'2'},
                  {'area':'25813','sheet':'1\n2','parcel':'2'}):
        assert client.get(url,query_string=query).status_code == 400
    assert client.get(url,query_string={'area':'00000','sheet':'1','parcel':'2'}).status_code == 404


def test_all_supported_historic_wards_have_distinct_verified_codes():
    from config.planning_parcels import PARCEL_AREAS
    assert len(PARCEL_AREAS) == len({a['code'] for a in PARCEL_AREAS}) == 91
    assert sum(a['district'] == '718' for a in PARCEL_AREAS) == 14
    assert sum(a['district'] == '721' for a in PARCEL_AREAS) == 8
    assert {d:sum(a['district']==d for a in PARCEL_AREAS) for d in map(str,range(718,727))} == {
        '718':14,'719':7,'720':12,'721':8,'722':11,'723':12,'724':7,'725':10,'726':10}


def test_capture_fails_closed_when_source_ignores_requested_ids(tmp_path):
    class Source:
        def request(self, path, *, params):
            if params.get('returnCountOnly'):
                return {'count': 1}
            if params.get('returnIdsOnly'):
                return {'objectIds': [33013]}
            return {'spatialReference': {'wkid':4326}, 'features': [{
                'attributes':{'OBJECTID':999,'MaPhuongXa':'25765','MaQuanHuyen':'718'},
                'geometry':{'rings':[[[106.61,11.02],[106.611,11.02],[106.611,11.021],[106.61,11.02]]]}}]}
    with pytest.raises(ValueError,match='honor requested'):
        capture(tmp_path,client=Source())
    assert not (tmp_path/'parcels.geojson').exists()
