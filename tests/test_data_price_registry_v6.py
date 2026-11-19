"""Phú Cường expansion: independent cohorts, frozen v5 and guest privacy."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import pytest
from tests.test_data_price_seo import engine, packet, row, make_app

LEGACY = Path(__file__).parent / 'fixtures/data_price_seo/registry-v5.json'
V5_SCOPES = {'phu-loi', 'hiep-thanh', 'phu-my', 'tan-an', 'phu-hoa', 'dinh-hoa',
             'phu-tan', 'hiep-an', 'tuong-binh-hiep', 'chanh-nghia', 'chanh-my', 'thu-dau-mot'}


def test_v6_adds_only_phu_cuong_with_own_qualified_monthly_cohort():
    mod = engine()
    snap = packet(mod, [row(i, ward='Phú Cường') for i in range(15)] + [row(100)])
    assert snap['scope_registry_version'] == 6
    assert set(snap['scopes']) == V5_SCOPES | {'phu-cuong'}
    scope = snap['scopes']['phu-cuong']
    assert scope['wards'] == ['Phú Cường'] and scope['parent'] == 'thu-dau-mot'
    assert scope['sample_count'] == 15
    assert scope['facts']['median']['value'] == 20
    assert all(f['scope'] == 'phu-cuong' and f['sample_count'] == 15 for f in scope['facts'].values())
    assert snap['scopes']['thu-dau-mot']['sample_count'] == 16


def test_v6_keeps_frozen_v5_bytes_hash_facts_and_absent_phu_cuong_history(tmp_path):
    mod = engine()
    content = LEGACY.read_bytes()
    old = json.loads(content)
    assert old['scope_registry_version'] == 5 and set(old['scopes']) == V5_SCOPES
    assert mod.validate_snapshot(old) == old
    mod.validate_claims(old, old['sha256'], [old['scopes']['phu-loi']['facts']['median']])
    target = tmp_path / (old['snapshot_id'] + '.json')
    target.write_bytes(content)
    (tmp_path/'latest.json').write_text(json.dumps({'file':target.name, 'sha256':old['sha256']}))
    assert mod.load_latest(tmp_path) == old
    snap = packet(mod, [row(i, ward='Phú Cường', last_seen_at='2026-11-19') for i in range(15)],
                  as_of=date(2026,11,19), previous=[old])
    scope = snap['scopes']['phu-cuong']
    assert all(p['median'] is None and p['sample_count'] is None for p in scope['history'][:-1])
    assert scope['change_mtd_pct'] is None
    assert target.read_bytes() == content


def test_phu_cuong_route_fails_closed_until_v6_packet_exists(monkeypatch,tmp_path):
    app, mod = make_app(monkeypatch,tmp_path)
    mod.freeze_snapshot(json.loads(LEGACY.read_bytes()),tmp_path)
    response = app.test_client().get('/gia-dat/phu-cuong')
    assert response.status_code == 503
    assert response.headers['X-Robots-Tag'] == 'noindex'
    assert response.headers['Cache-Control'] == 'private, no-store'


@pytest.mark.parametrize('n', [14,15])
def test_phu_cuong_threshold_controls_own_prices_parent_and_sitemap(monkeypatch,tmp_path,n):
    app, mod = make_app(monkeypatch,tmp_path,
        [row(i, ward='Phú Cường') for i in range(n)] + [row(100)])
    response = app.test_client().get('/gia-dat/phu-cuong')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Giá rao đất nền Phú Cường' in html and f'n = {n}' in html
    assert 'href="https://radarbds.vn/gia-dat/phu-cuong"' in html
    assert 'href="/gia-dat/thu-dau-mot"' in html
    assert ('data-fact-id=' in html) is (n >= 15)
    assert ('noindex' in html) is (n < 15)
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert ('/gia-dat/phu-cuong' in {e['path'] for e in mod.sitemap_entries(tmp_path)}) is (n >= 15)


@pytest.mark.parametrize('change', ['missing_v6_scope','extra_v5_scope','unknown_version'])
def test_v6_validator_enforces_frozen_scope_sets(change):
    mod = engine()
    assert mod.SCOPE_REGISTRIES.get(5) == V5_SCOPES
    assert mod.SCOPE_REGISTRIES.get(6) == V5_SCOPES | {'phu-cuong'}
    snap = packet(mod)
    if change == 'missing_v6_scope':
        snap['scopes'].pop('phu-cuong')
    elif change == 'extra_v5_scope':
        snap = json.loads(LEGACY.read_bytes())
        snap['scopes']['phu-cuong'] = deepcopy(snap['scopes']['phu-loi'])
    else:
        snap['scope_registry_version'] = 999
    snap['sha256'] = mod.digest({k:v for k,v in snap.items() if k != 'sha256'})
    with pytest.raises(ValueError,match='scope policy'):
        mod.validate_snapshot(snap)


@pytest.mark.parametrize('invalid', [dict(ward='Phú Lợi'),dict(duplicate_of_id=99),dict(possibly_duplicate=1),dict(review_hidden=1),dict(is_blacklisted=1),dict(is_outlier=1),dict(suspicious_bait=1),dict(probably_sold=1),dict(tx_type='thue'),dict(property_type='nha_pho'),dict(price_per_m2=float('nan')),dict(price_ty=0),dict(last_seen_at=None)])
def test_phu_cuong_invalid_record_cannot_cross_the_price_threshold(invalid):
    mod = engine()
    rows = [row(i,ward='Phú Cường') for i in range(14)]
    rows.append(row(100,**dict({'ward':'Phú Cường'},**invalid)))
    scope = packet(mod,rows)['scopes']['phu-cuong']
    assert scope['sample_count'] == 14 and scope['eligible'] is False
    assert all(f['value'] is None for f in scope['facts'].values())
    assert scope['histogram'] == []


def test_phu_cuong_guest_cards_never_return_internal_guland_metadata(monkeypatch):
    mod = engine()
    import services.market_data as market
    seen = {}
    def load(db,**kwargs):
        seen.update(kwargs)
        return {'signals':[dict(row(88,ward='Phú Cường',source='guland'),
                                title='INTERNAL',contact_phone='PRIVATE',img='secret.jpg')]}
    monkeypatch.setattr(market,'load_signals',load)
    assert mod.load_public_cards('phu-cuong') == []
    assert seen['tier'] == 'guest' and seen['sources'] == ['facebook']
    assert seen['wards'] == ['Phú Cường'] and seen['limit'] == 5
    assert seen['date_range'] == '1m' and seen['include_total'] is False
