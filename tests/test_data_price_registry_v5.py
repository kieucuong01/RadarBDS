"""Chánh Mỹ: one qualified ward; frozen v4 packets remain unchanged."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import pytest
from tests.test_data_price_seo import engine, packet, row, make_app

LEGACY = Path(__file__).parent / 'fixtures/data_price_seo/registry-v4.json'
V4_SCOPES = {'phu-loi', 'hiep-thanh', 'phu-my', 'tan-an', 'phu-hoa', 'dinh-hoa',
             'phu-tan', 'hiep-an', 'tuong-binh-hiep', 'chanh-nghia', 'thu-dau-mot'}


def test_v5_adds_only_authorized_chanh_my_with_own_monthly_cohort():
    mod = engine()
    snap = packet(mod, [row(i, ward='Chánh Mỹ') for i in range(15)] + [row(100)])
    assert snap['scope_registry_version'] == 5
    assert set(snap['scopes']) == V4_SCOPES | {'chanh-my'}
    scope = snap['scopes']['chanh-my']
    assert scope['wards'] == ['Chánh Mỹ'] and scope['parent'] == 'thu-dau-mot'
    assert scope['sample_count'] == 15
    assert scope['facts']['median']['value'] == 20
    assert all(f['scope'] == 'chanh-my' and f['sample_count'] == 15 for f in scope['facts'].values())
    assert snap['scopes']['thu-dau-mot']['sample_count'] == 16


def test_v5_reads_frozen_v4_without_rewriting_or_inventing_chanh_my_history(tmp_path):
    mod = engine()
    content = LEGACY.read_bytes()
    old = json.loads(content)
    assert old['scope_registry_version'] == 4 and set(old['scopes']) == V4_SCOPES
    assert mod.validate_snapshot(old) == old
    mod.validate_claims(old, old['sha256'], [old['scopes']['phu-loi']['facts']['median']])
    target = tmp_path / (old['snapshot_id'] + '.json')
    target.write_bytes(content)
    (tmp_path/'latest.json').write_text(json.dumps({'file':target.name, 'sha256':old['sha256']}))
    assert mod.load_latest(tmp_path) == old
    snap = packet(mod, [row(i, ward='Chánh Mỹ', last_seen_at='2026-11-02') for i in range(15)],
                  as_of=date(2026,11,2), previous=[old])
    assert snap['scope_registry_version'] == 5
    scope = snap['scopes']['chanh-my']
    assert all(p['median'] is None and p['sample_count'] is None for p in scope['history'][:-1])
    assert scope['change_mtd_pct'] is None
    assert target.read_bytes() == content


def test_chanh_my_route_fails_closed_until_a_covering_packet_exists(monkeypatch,tmp_path):
    app, mod = make_app(monkeypatch,tmp_path)
    mod.freeze_snapshot(json.loads(LEGACY.read_bytes()),tmp_path)
    response = app.test_client().get('/gia-dat/chanh-my')
    assert response.status_code == 503
    assert response.headers['X-Robots-Tag'] == 'noindex'
    assert response.headers['Cache-Control'] == 'private, no-store'


@pytest.mark.parametrize('n', [14,15])
def test_chanh_my_threshold_controls_local_facts_parent_link_and_sitemap(monkeypatch,tmp_path,n):
    app, mod = make_app(monkeypatch,tmp_path,
        [row(i, ward='Chánh Mỹ') for i in range(n)] + [row(100)])
    response = app.test_client().get('/gia-dat/chanh-my')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Giá rao đất nền Chánh Mỹ' in html and f'n = {n}' in html
    assert 'href="https://radarbds.vn/gia-dat/chanh-my"' in html
    assert 'href="/gia-dat/thu-dau-mot"' in html
    assert ('data-fact-id=' in html) is (n >= 15)
    assert ('noindex' in html) is (n < 15)
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert ('/gia-dat/chanh-my' in {e['path'] for e in mod.sitemap_entries(tmp_path)}) is (n >= 15)


@pytest.mark.parametrize('change', ['missing_v5_scope','extra_v4_scope','unknown_version'])
def test_v5_validator_enforces_exact_version_scope_sets(change):
    mod = engine()
    assert mod.SCOPE_REGISTRIES.get(4) == V4_SCOPES
    assert mod.SCOPE_REGISTRIES.get(5) == V4_SCOPES | {'chanh-my'}
    snap = packet(mod)
    if change == 'missing_v5_scope':
        snap['scopes'].pop('chanh-my')
    elif change == 'extra_v4_scope':
        snap = json.loads(LEGACY.read_bytes())
        snap['scopes']['chanh-my'] = deepcopy(snap['scopes']['phu-loi'])
    else:
        snap['scope_registry_version'] = 999
    snap['sha256'] = mod.digest({k:v for k,v in snap.items() if k != 'sha256'})
    with pytest.raises(ValueError,match='scope policy'):
        mod.validate_snapshot(snap)


def test_chanh_my_cards_keep_guest_source_ward_freshness_and_private_allowlist(monkeypatch):
    mod = engine()
    import services.market_data as market
    seen = {}
    def load(db,**kwargs):
        seen.update(kwargs)
        return {'signals':[dict(row(88,ward='Chánh Mỹ',source='guland'),
                                title='INTERNAL',contact_phone='PRIVATE',img='secret.jpg')]}
    monkeypatch.setattr(market,'load_signals',load)
    assert mod.load_public_cards('chanh-my') == []
    assert seen['tier'] == 'guest' and seen['sources'] == ['facebook']
    assert seen['wards'] == ['Chánh Mỹ'] and seen['limit'] == 5
    assert seen['date_range'] == '1m' and seen['include_total'] is False
