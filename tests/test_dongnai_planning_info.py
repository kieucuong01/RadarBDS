from copy import deepcopy

import pytest

from services.planning_dongnai_info import DongNaiPlanning, PLAN_SOURCES


RING = [[106.88, 11.53], [106.881, 11.53], [106.881, 11.531],
        [106.88, 11.531], [106.88, 11.53]]
FEATURE = {'type': 'Feature', 'id': 1000000000010,
           'properties': {'source': 'https://gis.dongnai.gov.vn/'},
           'geometry': {'type': 'Polygon', 'coordinates': [RING]}}


class Source:
    def __init__(self):
        self.calls = []
        self.data = {'spatialReference': {'wkid': 4326}, 'features': [
            {'attributes': {'OBJECTID': 50, 'TenDuAn': 'Đồ án A',
                'TenKhuChucNang': 'Đất công viên', 'MucDichSuDung': 'DCX',
                'MatDoXayDungTrungBinh': '10', 'TenChuSoHuu': 'PRIVATE'},
             'geometry': {'rings': [RING]}}]}

    def request(self, path, *, params):
        self.calls.append((path, params))
        return deepcopy(self.data)


def test_real_intersection_uses_source_geometry_and_square_metres():
    source = Source()
    result = DongNaiPlanning(source).lookup(FEATURE)['plans']
    assert len(result) == len(PLAN_SOURCES)
    zone = result[0]['zones'][0]
    assert zone['mucDichSuDungDat'] == 'Đất công viên'
    assert zone['maMucDichSuDungDat'] == 'DCX'
    assert 12000 < zone['dienTich'] < 12500
    assert zone['matDoXayDungTrungBinh'] == '10'
    assert 'PRIVATE' not in str(result)
    assert all('TenChuSoHuu' not in p['outFields'] for _, p in source.calls)
    assert all(p['geometryType'] == 'esriGeometryPolygon' for _, p in source.calls if 'geometry' in p)


def test_bbox_candidates_outside_parcel_are_not_reported_as_intersections():
    source = Source()
    source.data['features'][0]['geometry']['rings'] = [
        [[x + .01, y] for x, y in RING]]
    assert DongNaiPlanning(source).lookup(FEATURE)['plans'] == []


def test_reported_area_is_clipped_to_parcel_not_whole_zone_or_source_area():
    source = Source()
    full_area = DongNaiPlanning(source).lookup(FEATURE)['plans'][0]['zones'][0]['dienTich']
    source.data['features'][0]['attributes']['DienTich'] = 99999999
    source.data['features'][0]['geometry']['rings'] = [[
        [106.8805, 11.529], [106.882, 11.529], [106.882, 11.532],
        [106.8805, 11.532], [106.8805, 11.529]]]
    area = DongNaiPlanning(source).lookup(FEATURE)['plans'][0]['zones'][0]['dienTich']
    assert abs(area / full_area - .5) < .001


def test_geodesic_area_subtracts_holes_independent_of_ring_orientation():
    from shapely.geometry import Polygon
    from services.planning_dongnai_info import _area
    hole = [[106.8802, 11.5302], [106.8808, 11.5302], [106.8808, 11.5308],
            [106.8802, 11.5308], [106.8802, 11.5302]]
    expected = _area(Polygon(RING)) - _area(Polygon(hole))
    assert abs(_area(Polygon(RING, [hole])) - expected) < .001
    assert abs(_area(Polygon(RING[::-1], [hole[::-1]])) - expected) < .001


def test_one_failed_layer_does_not_hide_available_planning():
    source = Source()
    request = source.request
    def partial(path, *, params):
        if path == PLAN_SOURCES[1][0]:
            raise ValueError('private diagnostic')
        return request(path, params=params)
    source.request = partial
    result = DongNaiPlanning(source).lookup(FEATURE)
    assert len(result['plans']) == 1
    assert result['unavailable_layers'] == ['Quy hoạch chung đô thị']
    assert 'private diagnostic' not in str(result)


def test_general_layer_uses_exact_id_geometry_batch_and_validates_completeness():
    source = Source()
    result = DongNaiPlanning(source).lookup(FEATURE)
    general = [p for path, p in source.calls if path == PLAN_SOURCES[1][0]]
    assert general[0]['returnGeometry'] == 'false'
    assert general[1]['objectIds'] == '50' and 'geometry' not in general[1]
    assert result['unavailable_layers'] == []


def test_general_land_code_uses_official_domain_label_when_zone_name_is_missing():
    source = Source()
    source.data['features'][0]['attributes'].update(MucDichSuDung='OLK', TenKhuChucNang=None)
    result = DongNaiPlanning(source).lookup(FEATURE)
    assert result['plans'][1]['zones'][0]['mucDichSuDungDat'] == 'Đất nhà ở liên kế xây mới'


def test_general_geometry_batch_mismatch_is_partial_failure_not_a_false_result():
    source = Source()
    request = source.request
    def mismatched(path, *, params):
        result = request(path, params=params)
        if path == PLAN_SOURCES[1][0] and 'objectIds' in params:
            result['features'][0]['attributes']['OBJECTID'] = 51
        return result
    source.request = mismatched
    result = DongNaiPlanning(source).lookup(FEATURE)
    assert len(result['plans']) == 1
    assert result['unavailable_layers'] == ['Quy hoạch chung đô thị']


@pytest.mark.parametrize('failure', ['truncated', 'crs', 'invalid_polygon', 'too_many'])
def test_incomplete_or_invalid_source_is_an_error_not_no_planning(failure):
    source = Source()
    if failure == 'truncated': source.data['exceededTransferLimit'] = True
    if failure == 'crs': source.data['spatialReference']['wkid'] = 3857
    if failure == 'invalid_polygon': source.data['features'][0]['geometry']['rings'][0][0] = [float('nan'), 11.53]
    if failure == 'too_many': source.data['features'] *= 101
    with pytest.raises(ValueError): DongNaiPlanning(source).lookup(FEATURE)
