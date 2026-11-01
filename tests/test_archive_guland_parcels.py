import copy
import json
import sqlite3

import pytest

from scripts.archive_guland_parcels import archive, feature_from_capture


def capture():
    return dict(captured_at='2026-11-02T00:00:00Z', response_status=1,
                source='https://guland.vn/soi-quy-hoach/binh-phuoc', source_id=123,
                province_id='75', district_id='25345', ward_id='0',
                points=[dict(lat=y, lng=x) for x, y in [
                    (106.72, 11.75), (106.721, 11.75), (106.721, 11.751),
                    (106.72, 11.751), (106.72, 11.75)]],
                titles=['Thửa 60 Tờ 118, Diện tích 100m²',
                        'Thông tin cũ: Thửa 60 Tờ 11, Xã Tân Hưng, Huyện Hớn Quản'],
                areas=[[dict(name='Đồng Nai (Mới)', url='https://guland.vn/soi-quy-hoach/dong-nai')],
                       [dict(name='Bình Phước', url='https://guland.vn/soi-quy-hoach/binh-phuoc')]],
                landUse=[dict(code='CLN', area='100m²', label='Đất trồng cây lâu năm')],
                plans=[dict(title='Quy hoạch xây dựng', rows=[dict(area='100m²', label='Đất trồng cây lâu năm')])],
                planning_status='captured')


def test_capture_keeps_original_vertices_and_separates_source_area_from_measurement():
    data = capture()
    f = feature_from_capture(data)
    assert list(f['geometry']['coordinates'][0]) == [(p['lng'], p['lat']) for p in data['points']]
    assert f['id'] == 'guland:binh-phuoc:123'
    assert f['properties']['historic_province'] == 'binh-phuoc'
    assert f['properties']['titles'] == data['titles']
    assert f['properties']['plans'] == data['plans']
    assert f['properties']['measured_area_m2'] != 100
    assert 'source_admin' in f['properties']


@pytest.mark.parametrize('change', [
    {'response_status': 0}, {'response_status': True}, {'source_id': True}, {'source_id': '../123'},
    {'captured_at': '2026-11-02'}, {'source': 'https://evil.invalid/soi-quy-hoach/binh-phuoc'},
    {'source': 'https://guland.vn/soi-quy-hoach/dong-nai'},
    {'owner_name': 'must not be stored'}, {'html': '<p>raw source HTML</p>'},
    {'planning_status': 'not_provided'}, {'plans': []},
])
def test_rejects_unsuccessful_wrong_source_private_or_inconsistent_capture(change):
    with pytest.raises(ValueError):
        feature_from_capture(dict(capture(), **change))


@pytest.mark.parametrize('points', [
    [dict(lat=11.75, lng=x) for x in [106.7, 106.71, 106.72]],
    [dict(lat=y, lng=x) for x, y in [(106.7, 11.7), (106.8, 11.8), (106.7, 11.8), (106.8, 11.7)]],
    [dict(lat=11.75, lng=106.7), dict(lat=float('nan'), lng=106.8), dict(lat=11.8, lng=106.8)],
    [dict(lat=11.75, lng=106.7), dict(lat=True, lng=106.8), dict(lat=11.8, lng=106.8)],
])
def test_invalid_geometry_is_rejected_without_repair(points):
    with pytest.raises(ValueError):
        feature_from_capture(dict(capture(), points=points))


def test_planning_whitelist_rejects_extra_fields_and_html():
    data = capture()
    data['plans'][0]['owner'] = 'private'
    with pytest.raises(ValueError):
        feature_from_capture(data)
    data = capture()
    data['plans'][0]['rows'][0]['label'] = '<script>alert(1)</script>'
    with pytest.raises(ValueError):
        feature_from_capture(data)


def test_archive_is_idempotent_and_retains_planning_when_later_snapshot_has_no_result(tmp_path):
    path = tmp_path/'captures.sqlite'
    data = capture()
    assert archive(path, [data]) == 1
    assert archive(path, [data]) == 0
    newer = copy.deepcopy(data)
    newer.update(captured_at='2026-11-02T01:00:00Z', plans=[], planning_status='not_provided')
    assert archive(path, [newer]) == 1
    with sqlite3.connect(path) as db:
        rows = db.execute('SELECT feature FROM captures ORDER BY captured_at').fetchall()
    assert len(rows) == 2
    assert json.loads(rows[0][0])['properties']['plans'] == data['plans']
    assert json.loads(rows[1][0])['properties']['planning_status'] == 'not_provided'


def test_merged_province_code_does_not_mix_historic_provinces_or_identifiers(tmp_path):
    bp = capture()
    dn = copy.deepcopy(bp)
    dn['source'] = 'https://guland.vn/soi-quy-hoach/dong-nai'
    dn['areas'][-1] = [dict(name='Đồng Nai', url=dn['source'])]
    assert dn['province_id'] == bp['province_id'] == '75'
    assert feature_from_capture(dn)['id'] != feature_from_capture(bp)['id']
    path = tmp_path/'captures.sqlite'
    assert archive(path, [bp, dn]) == 2
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(DISTINCT province) FROM captures').fetchone()[0] == 2


def test_invalid_batch_leaves_existing_archive_unchanged(tmp_path):
    path = tmp_path/'captures.sqlite'
    archive(path, [capture()])
    before = path.read_bytes()
    with pytest.raises(ValueError):
        archive(path, [dict(capture(), source_id=456), dict(capture(), html='private')])
    assert path.read_bytes() == before
