from copy import deepcopy

import pytest

from services.planning_dongnai_parcels import DongNaiParcels, RegionalParcels, ID_OFFSET


class Source:
    def __init__(self):
        self.calls = []
        self.row = {'attributes': {'OBJECTID': 49268, 'SoTo': '10', 'SoThua': '281',
            'DienTich': 31.5, 'MaPhuongXa': '25201', 'MaQuanHuyen': '689',
            'TenChuSoHuu': 'PRIVATE'}, 'geometry': {'rings': [[[106.89, 11.53],
            [106.8901, 11.53], [106.8901, 11.5301], [106.89, 11.5301], [106.89, 11.53]]]}}

    def request(self, path, *, params):
        self.calls.append((path, params))
        return {'spatialReference': {'wkid': 4326}, 'features': [deepcopy(self.row)]}


def test_verified_dongnai_source_supports_exact_search_with_namespaced_ids():
    source = Source()
    live = DongNaiParcels(client=source)
    feature = live.search('bp-689-25201', '10', '281')['features'][0]
    assert feature['id'] == ID_OFFSET + 49268
    assert feature['properties']['source'] == 'https://gis.dongnai.gov.vn/'
    assert feature['properties']['province'] == 'binh-phuoc'
    assert 'PRIVATE' not in str(feature)
    assert 'MaPhuongXa' in source.calls[0][1]['where']
    assert live.feature(feature['id'], 'bp-689-25201') == feature
    assert live.feature(49268, 'bp-689-25201') is None


def test_feature_query_uses_source_id_not_public_namespace():
    source = Source()
    live = DongNaiParcels(client=source)
    assert live.feature(ID_OFFSET + 49268, 'bp-689-25201')['id'] == ID_OFFSET + 49268
    assert 'OBJECTID = 49268' in source.calls[0][1]['where']


def test_source_failure_does_not_fall_back_to_hcm():
    source = Source()
    def fail(path, *, params):
        source.calls.append(path)
        raise ValueError('unavailable')
    source.request = fail
    with pytest.raises(ValueError): DongNaiParcels(client=source).search('bp-689-25201', '10', '281')
    assert len(source.calls) == 1


def test_dongnai_rejects_foreign_area_and_ignored_exact_search():
    source = Source()
    live = DongNaiParcels(client=source)
    with pytest.raises(ValueError): live.search('26740', '10', '281')
    with pytest.raises(ValueError): live.search('bp-689-25201', '11', '281')


def test_point_query_returns_only_polygons_covering_the_coordinate():
    source = Source()
    live = DongNaiParcels(client=source)
    assert live.point(106.89005, 11.53005)['features'][0]['properties']['parcel'] == '281'
    assert source.calls[0][1]['geometryType'] == 'esriGeometryPoint'
    with pytest.raises(ValueError): live.point(106.92, 11.55)


def test_region_routing_does_not_send_binhphuoc_queries_to_hcm():
    hcm = Source()
    hcm.areas = []
    def forbidden(*args, **kwargs):
        raise AssertionError('HCM must not receive Binh Phuoc request')
    hcm.search = hcm.viewport = hcm.feature = forbidden
    regional = RegionalParcels(hcm=hcm, dongnai=DongNaiParcels(client=Source()))
    feature = regional.search('bp-689-25201', '10', '281')['features'][0]
    assert regional.feature(feature['id'], 'bp-689-25201') == feature
    assert regional.viewport((106.8899, 11.5299, 106.8902, 11.5302))['features']


def test_new_source_route_never_sends_dongnai_id_to_hcm_planning(monkeypatch):
    from flask import Flask
    from services.planning_parcels import PublicGIS, install_planning_lookup
    from services.planning_dongnai_info import DongNaiPlanning
    def forbidden(*args, **kwargs):
        raise AssertionError('Different providers cannot share planning object IDs')
    monkeypatch.setattr(PublicGIS, 'request', forbidden)
    calls = []
    def planning(self, feature):
        calls.append(feature['id'])
        return {'plans': [{'type': 'Quy hoạch chi tiết', 'name': 'Đồ án A', 'zones': []}], 'unavailable_layers': []}
    monkeypatch.setattr(DongNaiPlanning, 'lookup', planning)
    live = DongNaiParcels(client=Source())
    feature = live.search('bp-689-25201', '10', '281')['features'][0]
    app = Flask('dongnai-planning')
    install_planning_lookup(app, lambda identifier: live.feature(identifier, 'bp-689-25201'))
    response = app.test_client().get('/local-planning/parcels/%s/planning.json' % feature['id'])
    assert response.status_code == 200
    assert response.json['plans'][0]['name'] == 'Đồ án A'
    assert response.json['intersection_method'] == 'geodesic_wgs84'
    assert response.json['parcel']['id'] == feature['id']
    assert response.json['source'] == 'https://gis.dongnai.gov.vn/'
    assert app.test_client().get('/local-planning/parcels/%s/planning.json' % feature['id']).json == response.json
    assert calls == [feature['id']]


def test_dongnai_viewport_and_shared_bounds_keep_limits():
    from services.planning_parcels import parcel_bbox
    assert parcel_bbox('106.88,12.1,106.89,12.11', expanded=True,
                       coverage_bounds=RegionalParcels.coverage_bounds)[1] == 12.1
    with pytest.raises(ValueError): parcel_bbox('106.88,12.1,106.89,12.11', expanded=True)
    with pytest.raises(ValueError): parcel_bbox('106.88,12.1,107.2,12.2', expanded=True,
                                               coverage_bounds=RegionalParcels.coverage_bounds)
