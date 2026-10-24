"""Additive ward rollout preserves frozen v1 packets and privacy boundaries."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import pytest
from tests.test_data_price_seo import engine, packet, row, make_app

NEW = {'hiep-thanh': 'Hiệp Thành', 'phu-my': 'Phú Mỹ', 'tan-an': 'Tân An'}
LEGACY = Path(__file__).parent / 'fixtures/data_price_seo/registry-v1.json'


@pytest.mark.parametrize('slug,name', NEW.items())
def test_registered_new_ward_has_its_own_cohort_and_real_parent(slug, name):
    mod = engine()
    rows = [row(i, ward=name) for i in range(15)] + [row(100)]
    snapshot = packet(mod, rows)
    assert snapshot['scope_registry_version'] == 2
    scope = snapshot['scopes'][slug]
    assert scope['wards'] == [name]
    assert scope['parent'] == 'thu-dau-mot'
    assert scope['sample_count'] == 15
    assert scope['facts']['median']['sample_count'] == 15
    assert snapshot['scopes']['thu-dau-mot']['sample_count'] == 16


def test_legacy_packet_remains_loadable_unchanged_after_registry_expansion(tmp_path):
    mod = engine()
    old_bytes = LEGACY.read_bytes()
    old = json.loads(old_bytes)
    assert mod.validate_snapshot(old) == old
    path = tmp_path / (old['snapshot_id'] + '.json')
    path.write_bytes(old_bytes)
    (tmp_path / 'latest.json').write_text(json.dumps({'file': path.name, 'sha256': old['sha256']}))
    assert mod.load_latest(tmp_path) == old
    new = packet(mod, previous=[old], as_of=date(2026, 10, 22))
    assert new['scopes']['phu-loi']['sample_count'] == 15
    assert path.read_bytes() == old_bytes
    assert all(p['median'] is None for p in new['scopes']['tan-an']['history'][:-1])


@pytest.mark.parametrize('change', ['unknown_version', 'missing_scope', 'unregistered_scope'])
def test_registry_validator_rejects_unknown_or_incomplete_packet_even_if_rehashed(change):
    mod = engine()
    snap = packet(mod)
    if change == 'unknown_version':
        snap['scope_registry_version'] = 999
    elif change == 'missing_scope':
        snap['scopes'].pop('tan-an')
    else:
        snap['scopes']['Other'] = deepcopy(snap['scopes']['phu-loi'])
    snap['sha256'] = mod.digest({k:v for k,v in snap.items() if k != 'sha256'})
    with pytest.raises(ValueError, match='scope policy'):
        mod.validate_snapshot(snap)


def test_new_route_fails_closed_until_expanded_snapshot_exists(monkeypatch, tmp_path):
    app, mod = make_app(monkeypatch, tmp_path)
    mod.freeze_snapshot(json.loads(LEGACY.read_bytes()), tmp_path)
    response = app.test_client().get('/gia-dat/tan-an')
    assert response.status_code == 503
    assert response.headers['X-Robots-Tag'] == 'noindex'
    assert response.headers['Cache-Control'] == 'private, no-store'


@pytest.mark.parametrize('slug,name', NEW.items())
@pytest.mark.parametrize('n', [14, 15])
def test_new_ward_ssr_sitemap_threshold_real_filters_and_crawlable_parent(monkeypatch, tmp_path, slug, name, n):
    rows = [row(i, ward=name) for i in range(n)] + [row(100)]
    app, mod = make_app(monkeypatch, tmp_path, rows)
    response = app.test_client().get('/gia-dat/' + slug)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert f'Giá rao đất nền {name}' in html
    assert f'href="https://radarbds.vn/gia-dat/{slug}"' in html
    assert f'n = {n}' in html
    assert 'href="/gia-dat/thu-dau-mot"' in html
    assert 'ward=' in html and 'prop_type=dat_nen' in html
    urls = {p['path'] for p in mod.sitemap_entries(tmp_path)}
    assert ('/gia-dat/' + slug in urls) is (n >= 15)
    assert ('noindex' in html) is (n < 15)
    assert ('data-fact-id=' in html) is (n >= 15)


def test_parent_links_only_to_eligible_published_scopes(monkeypatch, tmp_path):
    rows = [row(i, ward='Hiệp Thành') for i in range(15)] + [row(100, ward='Tân An')]
    app, _ = make_app(monkeypatch, tmp_path, rows)
    html = app.test_client().get('/gia-dat/thu-dau-mot').get_data(as_text=True)
    assert 'href="/gia-dat/hiep-thanh"' in html
    assert 'href="/gia-dat/tan-an"' not in html
    assert 'href="/gia-dat/phu-my"' not in html


@pytest.mark.parametrize('slug,name', NEW.items())
def test_new_ward_public_cards_use_exact_guest_filter_and_never_internal_rows(monkeypatch, slug, name):
    mod = engine()
    import services.market_data as market
    seen = {}
    def load(db, **kwargs):
        seen.update(kwargs)
        return {'signals': [dict(row(88, source='guland', ward=name), title='INTERNAL') ]}
    monkeypatch.setattr(market, 'load_signals', load)
    assert mod.load_public_cards(slug) == []
    assert seen['tier'] == 'guest' and seen['sources'] == ['facebook']
    assert seen['wards'] == [name] and seen['limit'] == 5
    assert seen['date_range'] == '1m' and seen['include_total'] is False
