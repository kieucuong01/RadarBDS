from contextlib import contextmanager
from unittest import mock

import pytest

from services.listing_map import MapFilters


def test_bbox_validation_clips_to_service_area_and_rejects_invalid_inputs():
    from services.listing_map_viewport import parse_bbox
    assert parse_bbox('106.60,11.01,106.64,11.05') == (106.6, 11.01, 106.64, 11.05)
    assert parse_bbox('100,0,110,20') == (106.25, 10.75, 107.1, 11.65)
    assert parse_bbox('0,0,1,1') == ()
    for value in ('nan,11,106.7,11.1', '106.7,11,106.6,11.1', '1,2,3', '0,0,999,90'):
        with pytest.raises(ValueError):
            parse_bbox(value)


def test_opening_bounds_follow_filtered_wards_not_listing_locations():
    from services.listing_map_viewport import initial_bounds
    single = initial_bounds(['THỦ DẦU MỘT'], ['Tân An'])
    city = initial_bounds(['THỦ DẦU MỘT'], [])
    both = initial_bounds(['THỦ DẦU MỘT', 'BẾN CÁT'], [])
    assert 11.0 < single[0][0] < single[1][0] < 11.07
    assert single[0][1] < 106.62 < single[1][1]
    assert city[0][0] <= single[0][0] and city[1][0] >= single[1][0]
    assert both[1][0] > city[1][0]


def test_navigation_frames_new_districts_and_does_not_return_the_entire_service_area():
    from services.listing_map_viewport import initial_bounds
    for city,ward in (('Dầu Tiếng','Minh Tân'),('Bàu Bàng','Lai Uyên'),
                      ('Bắc Tân Uyên','Đất Cuốc'),('Phú Giáo','An Thái')):
        bounds = initial_bounds([city],[ward])
        assert bounds[1][0]-bounds[0][0] < .2
        assert bounds[1][1]-bounds[0][1] < .2


def test_viewport_sql_applies_after_manual_location_overrides(monkeypatch):
    import services.listing_map as module
    from tests.test_listing_map_service import _MapConnection, _Cursor
    class Connection(_MapConnection):
        def execute(self, sql, params=None):
            if 'WHERE f.location_key IS NOT NULL' in sql:
                self.queries.append((sql, list(params or [])))
                return _Cursor(rows=[])
            return super().execute(sql, params)
    connection = Connection()
    @contextmanager
    def connect():
        yield connection
    monkeypatch.setattr(module, 'get_conn', connect)
    module.clear_listing_map_cache()
    filters = MapFilters(bbox=(106.6,11.01,106.64,11.05))
    module.load_listing_map_summary(mode='all', tier='guest', filters=filters)
    sql, params = next((s,p) for s,p in connection.queries if 'GROUP BY ml.location_key' in s)
    assert 'ml.lat BETWEEN ? AND ?' in sql and 'ml.lng BETWEEN ? AND ?' in sql
    assert 'LIMIT 1001' in sql
    assert params[-4:] == [11.01,11.05,106.6,106.64]
    module.load_listing_map_items(mode='all', tier='guest', filters=filters, location_key='', page=1, limit=20)
    sql, params = next((s,p) for s,p in connection.queries if 'FROM effective_map_locations f' in s and 'LIMIT ? OFFSET ?' in s)
    assert 'f.lat BETWEEN ? AND ?' in sql and 'f.lng BETWEEN ? AND ?' in sql
    assert 'f.location_key = ?' not in sql
    assert params[-6:] == [11.01,11.05,106.6,106.64,20,0]


def test_viewport_api_ignores_dashboard_filters_but_keeps_source_policy(monkeypatch):
    import app as app_module
    captured = []
    def summary(**kwargs):
        captured.append(kwargs)
        return {'locations': [], 'summary': {'total': 0, 'mapped': 0}}
    def items(**kwargs):
        captured.append(kwargs)
        return {'items': [], 'total': 0}
    monkeypatch.setattr(app_module, 'load_listing_map_summary', summary)
    monkeypatch.setattr(app_module, 'load_listing_map_items', items)
    app_module.app.config['TESTING'] = True
    client = app_module.app.test_client()
    url = '/api/map-listings?mode=all&bbox=106.60,11.01,106.64,11.05&include_recent=1&ward=Phú+Mỹ&price_max=1&q=wrong&source=guland'
    result = client.get(url)
    assert result.status_code == 200
    assert 'recent' in result.json
    for call in captured:
        filters = call['filters']
        assert filters.wards == () and filters.keyword == '' and filters.price_max == 0
        assert filters.sources == ('facebook',)
        assert filters.bbox == (106.6,11.01,106.64,11.05)
    assert client.get('/api/map-listings?mode=all&bbox=nan,1,2,3').status_code == 400
