"""Hermetic tests for the first proprietary-price vertical slice."""
from copy import deepcopy
from datetime import date
import importlib.util
import json
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]


def engine():
    spec = importlib.util.spec_from_file_location('price_engine_test', ROOT / 'services/data_price_seo.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def row(i=1, **changes):
    data = dict(id=i+1, source='facebook', ward='Phú Lợi', area='Thủ Dầu Một',
                property_type='dat_nen', tx_type='ban', price_ty=2.0,
                price_per_m2=20.0, area_m2=100.0, last_seen_at='2026-10-20T09:00:00',
                is_active=1, duplicate_of_id=None, possibly_duplicate=0,
                is_blacklisted=0, review_hidden=0, is_outlier=0, suspicious_bait=0,
                probably_sold=0, source_status='active', extraction_quality_flags='',
                source_quality_flags='', valuation_is_outlier=0)
    data.update(changes)
    return data


def packet(mod, rows=None, as_of=date(2026, 10, 21), previous=()):
    return mod.build_snapshot(rows if rows is not None else [row(i, last_seen_at=as_of.isoformat()) for i in range(15)],
                              as_of=as_of, generated_at=as_of.isoformat()+'T12:00:00+07:00',
                              source_commit='a'*40, previous=previous)


def test_first_slice_computes_mean_median_range_histogram_and_independent_active_count():
    mod = engine()
    rows = [row(i, source='guland' if i < 10 else 'facebook',
                is_active=int(i < 12), price_ty=(10+i)/10,
                price_per_m2=10+i) for i in range(15)]
    scope = packet(mod, rows)['scopes']['phu-loi']
    assert scope['eligible'] is True
    assert scope['sample_count'] == 15
    assert scope['active_count'] == 12
    assert scope['source_counts'] == {'facebook': 5, 'guland': 10}
    assert scope['facts']['mean']['value'] == 17
    assert scope['facts']['median']['value'] == 17
    assert scope['facts']['min']['value'] == 10
    assert scope['facts']['max']['value'] == 24
    assert all(f['sample_count'] == 15 for f in scope['facts'].values())
    assert all(f['unit'] == 'trieu_vnd_per_m2' for f in scope['facts'].values())
    assert sum(b['count'] for b in scope['histogram']) == 15


@pytest.mark.parametrize('n', [0, 1, 14])
def test_small_sample_suppresses_all_local_price_facts_and_histogram(n):
    mod = engine()
    scope = packet(mod, [row(i) for i in range(n)])['scopes']['phu-loi']
    assert scope['eligible'] is False
    assert scope['sample_count'] == n
    assert all(f['value'] is None and f['display'] == 'Chưa đủ mẫu' for f in scope['facts'].values())
    assert scope['histogram'] == []


@pytest.mark.parametrize('changes', [
    {'source':'batdongsan'}, {'ward':'Other'}, {'ward':'Phú An'},
    {'property_type':'nha_dat'}, {'property_type':'nha_tro'}, {'tx_type':'thue'},
    {'duplicate_of_id':99}, {'possibly_duplicate':1}, {'is_blacklisted':1},
    {'review_hidden':1}, {'is_outlier':1}, {'valuation_is_outlier':1},
    {'suspicious_bait':1}, {'probably_sold':1}, {'source_status':'inactive'},
    {'price_ty':0}, {'price_ty':None}, {'price_ty':float('nan')},
    {'price_per_m2':float('inf')}, {'area_m2':0}, {'price_per_m2':2000},
    {'extraction_quality_flags':'area_dimension_conflict'},
    {'source_quality_flags':'suspicious_bait'},
    {'last_seen_at':'2026-09-30'}, {'last_seen_at':'2026-10-22'},
    {'last_seen_at':None}, {'last_seen_at':'not-a-date'},
])
def test_invalid_or_wrong_population_cannot_enter_stats(changes):
    mod = engine()
    assert mod.select_cohort([row(**changes)], 'phu-loi', date(2026,10,21)) == []


def test_known_identity_is_counted_once_without_cross_url_lot_invention():
    mod = engine()
    rows = [row(i) for i in range(15)]
    rows += [row(0), row(45, duplicate_of_id=1)]
    assert packet(mod, rows)['scopes']['phu-loi']['sample_count'] == 15
    assert 'id' not in packet(mod, rows)['scopes']['phu-loi']


def test_missing_historical_panel_is_null_not_backfilled_from_current_prices():
    mod = engine()
    scope = packet(mod)['scopes']['phu-loi']
    assert len(scope['history']) == 6
    assert [p['month'] for p in scope['history']] == ['2026-05','2026-06','2026-07','2026-08','2026-09','2026-10']
    assert all(p['median'] is None and p['sample_count'] is None for p in scope['history'][:-1])
    assert scope['change_mtd_pct'] is None
    assert scope['change_reason'] == 'no_comparable_snapshot'


def test_previous_real_packet_supports_only_matching_elapsed_mtd_window():
    mod = engine()
    old = packet(mod, as_of=date(2026,9,21))
    new = packet(mod, as_of=date(2026,10,21), previous=[old])
    scope = new['scopes']['phu-loi']
    assert scope['history'][-2]['snapshot_sha256'] == old['sha256']
    assert scope['history'][-2]['period_end'] == '2026-09-21'
    assert scope['change_mtd_pct'] == 0
    other = packet(mod, as_of=date(2026,10,20), previous=[old])
    assert other['scopes']['phu-loi']['change_mtd_pct'] is None


def test_january_window_rolls_over_and_utc_is_converted_to_vietnam_date():
    mod = engine()
    rows = [row(i, last_seen_at='2025-12-31T18:00:00+00:00') for i in range(15)]
    snap = packet(mod, rows, as_of=date(2026,1,1))
    assert snap['period_start'] == '2026-01-01'
    assert snap['scopes']['phu-loi']['sample_count'] == 15
    assert snap['scopes']['phu-loi']['history'][0]['month'] == '2025-08'


@pytest.mark.parametrize('field,value', [('value',25),('unit','vnd'),('sample_count',99),('period_end','2026-09-21'),('display','20,01')])
def test_shared_fact_binding_rejects_modified_number_unit_period_count_rounding(field,value):
    mod = engine()
    snap = packet(mod)
    fact = deepcopy(snap['scopes']['phu-loi']['facts']['median'])
    mod.validate_claims(snap, snap['sha256'], [fact])
    fact[field] = value
    with pytest.raises(ValueError):
        mod.validate_claims(snap, snap['sha256'], [fact])


def test_snapshot_hash_wrong_identity_and_private_input_are_not_published(tmp_path):
    mod = engine()
    snap = packet(mod, [row(i, title='PRIVATE', contact_phone='0909999999', url='https://private.example') for i in range(15)])
    text = json.dumps(snap, ensure_ascii=False)
    assert 'PRIVATE' not in text and '0909999999' not in text and 'private.example' not in text
    with pytest.raises(ValueError):
        mod.validate_claims(snap, '0'*64, [])
    bad = deepcopy(snap)
    bad['scopes']['phu-loi']['sample_count'] = 99
    with pytest.raises(ValueError):
        mod.validate_snapshot(bad)
    path = mod.freeze_snapshot(snap, tmp_path)
    original = path.read_bytes()
    assert mod.load_latest(tmp_path)['sha256'] == snap['sha256']
    assert mod.freeze_snapshot(snap, tmp_path) == path
    assert path.read_bytes() == original
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads((tmp_path/'latest.json').read_text())['sha256'] == snap['sha256']


def test_card_adapter_uses_guest_current_model_and_allowlist_not_raw_source(monkeypatch):
    mod = engine()
    seen = {}
    def load(db, **kwargs):
        seen.update(kwargs)
        return {'signals': [dict(row(1), title='Safe', price='2 tỷ', area_size='100 m²'),
                            dict(row(2,source='guland'), title='INTERNAL', img='secret.jpg')]}
    import services.market_data as market
    monkeypatch.setattr(market, 'load_signals', load)
    cards = mod.load_public_cards('phu-loi')
    assert seen['tier'] == 'guest' and seen['sources'] == ['facebook']
    assert seen['wards'] == ['Phú Lợi'] and seen['limit'] == 5 and seen['include_total'] is False
    assert len(cards) == 1
    assert set(cards[0]) == {'id','ward','area_m2','price_ty'}
    assert 'INTERNAL' not in json.dumps(cards)


def make_app(monkeypatch, tmp_path, rows=None):
    mod = engine()
    mod.freeze_snapshot(packet(mod, rows), tmp_path)
    from routes import data_price_seo as route
    monkeypatch.setattr(route, 'snapshot_root', lambda: tmp_path)
    monkeypatch.setattr(route, 'load_public_cards', lambda slug: [])
    app = Flask(__name__, template_folder=str(ROOT/'templates'), static_folder=str(ROOT/'static'))
    app.register_blueprint(route.bp)
    app.config['TESTING'] = True
    return app, mod


def test_ssr_has_mean_median_sample_period_histogram_history_canonical_and_no_private_payload(monkeypatch,tmp_path):
    app, mod = make_app(monkeypatch,tmp_path)
    response = app.test_client().get('/gia-dat/phu-loi')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<link rel="canonical" href="https://radarbds.vn/gia-dat/phu-loi">' in html
    for text in ['Trung bình','Trung vị','Thấp nhất','Cao nhất','n = 15','2026-10-01','2026-10-21','Phân bố','6 tháng','Giá rao','Chưa có dữ liệu lịch sử','sha256']:
        assert text in html
    assert 'noindex' not in html
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'X-Radar-Public-Cache' not in response.headers
    assert app.test_client().get('/gia-dat/Other').status_code == 404
    assert app.test_client().get('/gia-dat/hiep-thanh').status_code == 404


def test_small_local_sample_uses_named_parent_without_local_prices_or_sitemap(monkeypatch,tmp_path):
    rows = [row(i, ward='Hiệp An') for i in range(15)] + [row(100)]
    app, mod = make_app(monkeypatch,tmp_path,rows)
    html = app.test_client().get('/gia-dat/phu-loi').get_data(as_text=True)
    assert 'noindex,follow' in html and 'Chưa đủ mẫu' in html
    assert '/gia-dat/thu-dau-mot' in html and 'Thủ Dầu Một' in html
    assert 'n = 1' in html
    assert [p['path'] for p in mod.sitemap_entries(tmp_path)] == ['/gia-dat/thu-dau-mot']


def test_corrupted_snapshot_fails_closed_not_empty_success(monkeypatch,tmp_path):
    app, mod = make_app(monkeypatch,tmp_path)
    (tmp_path/'latest.json').write_text('{broken')
    assert app.test_client().get('/gia-dat/phu-loi').status_code == 503
    assert mod.sitemap_entries(tmp_path) == []


def test_cards_explicitly_use_one_month_freshness_window(monkeypatch):
    mod = engine()
    import services.market_data as market
    seen = {}
    def load(db, **kwargs):
        seen.update(kwargs)
        return {'signals': []}
    monkeypatch.setattr(market, 'load_signals', load)
    assert mod.load_public_cards('phu-loi') == []
    assert seen.get('date_range') == '1m'


def test_parent_dashboard_cta_uses_real_city_not_nonexistent_ward(monkeypatch,tmp_path):
    app, mod = make_app(monkeypatch,tmp_path)
    from html.parser import HTMLParser
    from urllib.parse import urlparse, parse_qs
    class Links(HTMLParser):
        hrefs=[]
        def handle_starttag(self,tag,attrs):
            if tag=='a':
                self.hrefs.append(dict(attrs).get('href',''))
    parser=Links()
    parser.feed(app.test_client().get('/gia-dat/thu-dau-mot').get_data(as_text=True))
    queries=[parse_qs(urlparse(url).query) for url in parser.hrefs]
    assert any(q.get('city')==['THỦ DẦU MỘT'] and q.get('prop_type')==['dat_nen'] for q in queries)
    assert not any(q.get('ward')==['Thủ Dầu Một'] for q in queries)
