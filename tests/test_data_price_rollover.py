"""Month rollover must retain only real, eligible end-of-month frozen facts."""
from datetime import date, timedelta
import json

import pytest
from tests.test_data_price_seo import engine, packet, row, make_app


def store(mod, root, when, n=15, ward='Phú Lợi', previous=()):
    snap = packet(mod, [row(i, ward=ward, last_seen_at=when.isoformat()) for i in range(n)],
                  as_of=when, previous=previous)
    mod.freeze_snapshot(snap, root)
    return snap


def test_rollover_retains_real_closed_month_facts_without_rewriting_either_packet(monkeypatch, tmp_path):
    app, mod = make_app(monkeypatch, tmp_path)
    old = store(mod, tmp_path, date(2026, 10, 31))
    current = store(mod, tmp_path, date(2026, 11, 1), n=14, previous=[old])
    before = {p.name: p.read_bytes() for p in tmp_path.glob('*.json')}
    response = app.test_client().get('/gia-dat/phu-loi')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.headers['X-Radar-Price-Snapshot'] == old['sha256']
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'noindex' not in html and 'X-Robots-Tag' not in response.headers
    assert 'data-fact-id="phu-loi.dat_nen.median"' in html
    assert 'n = 15' in html and '2026-10-01' in html and '2026-10-31' in html
    assert '2026-11-01' in html and 'n = 14' in html
    assert 'Tháng mới chưa đủ 15 mẫu' in html
    assert 'tháng đã kết thúc' in html
    assert response.headers['X-Radar-Price-Current-Snapshot'] == current['sha256']
    assert 'href="https://radarbds.vn/gia-dat/phu-loi"' in html
    assert before == {p.name: p.read_bytes() for p in tmp_path.glob('*.json')}


@pytest.mark.parametrize('start', [date(2027, 1, 1), date(2027, 3, 1), date(2028, 3, 1)])
def test_sitemap_retains_actual_closed_month_lastmod_across_year_and_leap_boundaries(tmp_path, start):
    mod = engine()
    last = start - timedelta(days=1)
    old = store(mod, tmp_path, last)
    store(mod, tmp_path, start, n=0, previous=[old])
    assert {e['path']: e['updated_at'] for e in mod.sitemap_entries(tmp_path)} == {
        '/gia-dat/phu-loi': last.isoformat(), '/gia-dat/thu-dau-mot': last.isoformat()}


@pytest.mark.parametrize('last,n', [(date(2026, 10, 30), 15), (date(2026, 10, 31), 14),
                                     (date(2026, 9, 30), 15)])
def test_missing_partial_small_or_stale_previous_month_cannot_be_relabelled_closed(monkeypatch, tmp_path, last, n):
    app, mod = make_app(monkeypatch, tmp_path)
    old = store(mod, tmp_path, last, n=n)
    store(mod, tmp_path, date(2026, 11, 1), n=1, previous=[old])
    response = app.test_client().get('/gia-dat/phu-loi')
    html = response.get_data(as_text=True)
    assert response.headers['X-Robots-Tag'] == 'noindex, follow'
    assert 'data-fact-id=' not in html
    assert mod.sitemap_entries(tmp_path) == []


def test_15_new_month_samples_restore_current_facts_and_current_sitemap_lastmod(monkeypatch, tmp_path):
    app, mod = make_app(monkeypatch, tmp_path)
    old = store(mod, tmp_path, date(2026, 10, 31))
    current = store(mod, tmp_path, date(2026, 11, 2), previous=[old])
    response = app.test_client().get('/gia-dat/phu-loi')
    assert response.headers['X-Radar-Price-Snapshot'] == current['sha256']
    assert 'Tháng mới chưa đủ 15 mẫu' not in response.get_data(as_text=True)
    assert all(e['updated_at'] == '2026-11-02' for e in mod.sitemap_entries(tmp_path))


def test_retention_is_per_scope_not_parent_or_neighbor_eligibility(monkeypatch, tmp_path):
    app, mod = make_app(monkeypatch, tmp_path)
    old = store(mod, tmp_path, date(2026, 10, 31), ward='Hiệp Thành')
    store(mod, tmp_path, date(2026, 11, 1), n=0, previous=[old])
    phu_loi = app.test_client().get('/gia-dat/phu-loi')
    hiep_thanh = app.test_client().get('/gia-dat/hiep-thanh')
    assert phu_loi.headers['X-Robots-Tag'] == 'noindex, follow'
    assert hiep_thanh.headers['X-Radar-Price-Snapshot'] == old['sha256']
    assert 'X-Robots-Tag' not in hiep_thanh.headers
    paths = {e['path'] for e in mod.sitemap_entries(tmp_path)}
    assert paths == {'/gia-dat/hiep-thanh', '/gia-dat/thu-dau-mot'}
    assert 'data-fact-id=' not in phu_loi.get_data(as_text=True)


def test_corrupt_closed_month_packet_cannot_be_used_as_a_recovery_source(monkeypatch, tmp_path):
    app, mod = make_app(monkeypatch, tmp_path)
    old = store(mod, tmp_path, date(2026, 10, 31))
    store(mod, tmp_path, date(2026, 11, 1), n=0, previous=[old])
    path = tmp_path / (old['snapshot_id'] + '.json')
    altered = json.loads(path.read_text())
    altered['scopes']['phu-loi']['facts']['median']['value'] = 9999
    path.write_text(json.dumps(altered))
    response = app.test_client().get('/gia-dat/phu-loi')
    assert response.status_code == 503
    assert response.headers['X-Robots-Tag'] == 'noindex'
    assert mod.sitemap_entries(tmp_path) == []


def test_corrupt_latest_pointer_is_not_hidden_by_valid_historical_packet(monkeypatch, tmp_path):
    app, mod = make_app(monkeypatch, tmp_path)
    store(mod, tmp_path, date(2026, 10, 31))
    (tmp_path / 'latest.json').write_text('{bad')
    assert app.test_client().get('/gia-dat/phu-loi').status_code == 503
    assert mod.sitemap_entries(tmp_path) == []


def test_latest_actual_endpoint_packet_is_selected_deterministically(monkeypatch, tmp_path):
    app, mod = make_app(monkeypatch, tmp_path)
    first = store(mod, tmp_path, date(2026, 10, 31))
    later = mod.build_snapshot([row(i, last_seen_at='2026-10-31', price_ty=3, price_per_m2=30) for i in range(15)],
                               as_of=date(2026, 10, 31), generated_at='2026-10-31T23:00:00+07:00',
                               source_commit='b' * 40)
    mod.freeze_snapshot(later, tmp_path)
    store(mod, tmp_path, date(2026, 11, 1), n=0, previous=[first, later])
    response = app.test_client().get('/gia-dat/phu-loi')
    assert response.headers['X-Radar-Price-Snapshot'] == later['sha256']
    assert '30,00' in response.get_data(as_text=True)


def test_retained_cards_are_still_live_guest_filtered_not_historical_private_inputs(monkeypatch, tmp_path):
    app, mod = make_app(monkeypatch, tmp_path)
    old = store(mod, tmp_path, date(2026, 10, 31))
    store(mod, tmp_path, date(2026, 11, 1), n=0, previous=[old])
    from routes import data_price_seo as route
    called = []
    def cards(slug):
        called.append(slug)
        return [{'id': 4321, 'ward': 'Phú Lợi', 'area_m2': 100, 'price_ty': 2}]
    monkeypatch.setattr(route, 'load_public_cards', cards)
    response = app.test_client().get('/gia-dat/phu-loi')
    assert response.headers['X-Radar-Price-Snapshot'] == old['sha256']
    assert called == ['phu-loi']
    assert '/listing/4321' in response.get_data(as_text=True)
