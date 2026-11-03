import pytest

from services.planning_coordinates import coordinate_point


@pytest.mark.parametrize('code,lon,lat', [('tm3-10500',105.8,21.02),
    ('tm3-10530',106.05,20.65),('tm3-10815',109.18,12.24),
    ('tm3-10745',108.44,11.94),('tm3-10630',108.2,16.06)])
def test_local_tm3_roundtrip_preserves_datum_and_axis_order(code,lon,lat):
    from services.planning_coordinates import projection_crs, _transformer
    from pyproj import Transformer, Geod
    easting,northing=Transformer.from_crs(4326,projection_crs(code),always_xy=True).transform(lon,lat)
    actual=coordinate_point(dict(system='vn2000',crs=code,first=str(northing),second=str(easting)))
    assert Geod(ellps='WGS84').inv(lon,lat,*actual[:2])[2]<1
    assert _transformer(code).accuracy>=0


def test_wgs84_uses_latitude_then_longitude_and_accepts_decimal_comma():
    assert coordinate_point({'system': 'wgs84', 'first': '11,02', 'second': '106.65'})[:2] == (106.65, 11.02)
    assert coordinate_point({'system':'wgs84','first':'11.019333467739227','second':'106.61686068570627'})[1] == 11.019333467739227


@pytest.mark.parametrize('values', [
    {}, {'system': 'wgs84', 'first': 'NaN', 'second': '106.65'},
    {'system': 'wgs84', 'first': '106.65', 'second': '11.02'},
    {'system': 'vn2000', 'first': '1200000', 'second': '600000', 'crs': 'http://example.org'},
    {'system': 'vn2000', 'first': '600000', 'second': '1200000', 'crs': 'tm3-10545'},
])
def test_coordinate_input_fails_closed(values):
    with pytest.raises(ValueError): coordinate_point(values)


def test_vn2000_requires_explicit_projection_and_preserves_northing_easting_order():
    # EPSG:9210 / VN-2000 TM-3 105-45; sub-metre tolerance across published datum operations.
    from pyproj import Transformer
    easting, northing = Transformer.from_crs(4326, 9210, always_xy=True).transform(106.65, 11.02)
    lon, lat, _ = coordinate_point({'system': 'vn2000', 'first': str(northing),
                                   'second': str(easting), 'crs': 'tm3-10545'})
    from pyproj import Geod
    assert Geod(ellps='WGS84').inv(lon, lat, 106.65, 11.02)[2] < 1


def test_coordinate_route_selects_a_real_catalogue_parcel_and_distinguishes_missing_coverage(tmp_path):
    from flask import Flask
    from services.planning_parcel_catalog import build_catalog, install_catalog
    from tests.test_planning_parcel_catalog import snapshot
    path = build_catalog(tmp_path, [snapshot(tmp_path, '25765', 'Tân An', 'Thủ Dầu Một', 33013, 106.61)])
    app = Flask('coordinate-test')
    install_catalog(app, path)
    client = app.test_client()
    base = '/local-planning/parcels/coordinates.json'
    response = client.get(base, query_string=dict(system='wgs84', first='11.0205', second='106.6105'))
    assert response.status_code == 200 and response.json['features'][0]['id'] == 33013
    assert response.json['point'] == [11.0205, 106.6105]
    assert client.get(base, query_string=dict(system='wgs84', first='21.02', second='105.8')).json['features'] == []
    assert client.get(base, query_string=dict(system='vn2000', first='1200000', second='600000', crs='bad')).status_code == 400


def test_coordinate_lookup_uses_existing_snapshot_without_waiting_for_remote_gis(tmp_path):
    from flask import Flask
    from services.planning_parcel_catalog import build_catalog, install_catalog
    from tests.test_planning_parcel_catalog import snapshot
    class Remote:
        areas = []
        def point(self, *args):
            raise AssertionError('A verified snapshot hit must not wait for remote GIS')
    path = build_catalog(tmp_path, [snapshot(tmp_path, '25765', 'Tân An', 'Thủ Dầu Một', 33013, 106.61)])
    app = Flask('coordinate-local-first')
    install_catalog(app, path, expanded=Remote())
    response = app.test_client().get('/local-planning/parcels/coordinates.json',
        query_string=dict(system='wgs84', first='11.0205', second='106.6105'))
    assert response.status_code == 200 and response.json['features'][0]['id'] == 33013


def test_corner_outline_converts_ordered_vertices_and_keeps_user_provenance():
    from services.planning_coordinates import coordinate_outline
    result = coordinate_outline({'system': 'wgs84', 'corners':
        '1 11.02 106.61\n2 11.02 106.611\n3 11.021 106.611\n4 11.021 106.61\n5 11.02 106.61'})
    assert tuple(result['geometry']['coordinates'][0][0]) == (106.61, 11.02)
    assert result['properties']['vertex_count'] == 4
    assert result['properties']['origin'] == 'user_corners'
    assert 12000 < result['properties']['area'] < 12500
    assert 430 < result['properties']['perimeter'] < 450
    assert 'id' not in result


@pytest.mark.parametrize('corners', [
    '', '11.02 106.61\n11.021 106.611',
    '11.02 106.61\n11.021 106.611\n11.02 106.611\n11.021 106.61',
    '11.02 106.61\n11.02 106.61\n11.021 106.611',
    '11.02 106.61\n11.02 106.611\nNaN 106.611',
    '\n'.join(['11.02 106.61'] * 102),
])
def test_corner_outline_rejects_invalid_or_unbounded_input(corners):
    from services.planning_coordinates import coordinate_outline
    with pytest.raises(ValueError):
        coordinate_outline({'system': 'wgs84', 'corners': corners})


def test_corner_route_is_local_only_and_bounded(tmp_path):
    from flask import Flask
    from services.planning_parcel_catalog import build_catalog, install_catalog
    from tests.test_planning_parcel_catalog import snapshot
    path = build_catalog(tmp_path, [snapshot(tmp_path, '25765', 'Tân An', 'Thủ Dầu Một', 33013, 106.61)])
    app = Flask('corner-test'); install_catalog(app, path)
    client = app.test_client(); url = '/local-planning/parcels/corners.json'
    body = {'system': 'wgs84', 'corners': '11.02 106.61\n11.02 106.611\n11.021 106.611'}
    assert client.post(url, json=body).status_code == 200
    assert client.post(url, json={'system': 'wgs84', 'corners': 'bad'}).status_code == 400
    assert client.post(url, json={'corners': 'x' * 17000}).status_code == 413


def test_vn2000_corner_outline_matches_wgs84_geometry():
    from pyproj import Transformer, Geod
    from services.planning_coordinates import coordinate_outline
    points = [(106.61, 11.02), (106.611, 11.02), (106.611, 11.021)]
    transformer = Transformer.from_crs(4326, 9210, always_xy=True)
    rows = []
    for lon, lat in points:
        y, x = transformer.transform(lon, lat)
        rows.append(f'{x} {y}')
    result = coordinate_outline({'system': 'vn2000', 'crs': 'tm3-10545', 'corners': '\n'.join(rows)})
    for expected, actual in zip(points, result['geometry']['coordinates'][0]):
        assert Geod(ellps='WGS84').inv(*expected, *actual)[2] < 1
    with pytest.raises(ValueError):
        coordinate_outline({'system': 'vn2000', 'corners': '\n'.join(rows)})
