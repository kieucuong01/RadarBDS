"""Registry v3 rollout: own ward samples, frozen v2 compatibility and guest privacy."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import pytest
from tests.test_data_price_seo import engine, packet, row, make_app

NEW = {'phu-hoa': 'Phú Hòa', 'dinh-hoa': 'Định Hòa', 'phu-tan': 'Phú Tân'}
LEGACY = Path(__file__).parent / 'fixtures/data_price_seo/registry-v2.json'
V2_SCOPES = {'phu-loi', 'hiep-thanh', 'phu-my', 'tan-an', 'thu-dau-mot'}


@pytest.mark.parametrize('slug,name', NEW.items())
def test_v3_ward_uses_own_cohort_not_neighbor_or_parent_samples(slug, name):
    mod = engine()
    rows = [row(i, ward=name) for i in range(15)] + [row(100, ward='Phú Lợi')]
    snap = packet(mod, rows)
    assert snap['scope_registry_version'] == mod.SCOPE_REGISTRY_VERSION
    own = snap['scopes'][slug]
    assert own['wards'] == [name] and own['parent'] == 'thu-dau-mot'
    assert own['sample_count'] == 15
    assert all(f['scope'] == slug and f['sample_count'] == 15 for f in own['facts'].values())
    assert snap['scopes']['thu-dau-mot']['sample_count'] == 16
    assert set(snap['scopes']) == set(mod.SCOPES)


def test_actual_frozen_v2_keeps_bytes_hash_claims_and_exact_original_scope_set(tmp_path):
    mod = engine()
    content = LEGACY.read_bytes()
    old = json.loads(content)
    assert old['scope_registry_version'] == 2
    assert set(old['scopes']) == V2_SCOPES
    assert mod.validate_snapshot(old) == old
    mod.validate_claims(old, old['sha256'], [old['scopes']['phu-loi']['facts']['median']])
    target = tmp_path / (old['snapshot_id'] + '.json')
    target.write_bytes(content)
    (tmp_path / 'latest.json').write_text(json.dumps({'file': target.name, 'sha256': old['sha256']}))
    assert mod.load_latest(tmp_path) == old
    current = packet(mod, [row(i, ward='Phú Hòa') for i in range(15)],
                     as_of=date(2026, 10, 26), previous=[old])
    assert current['scopes']['phu-hoa']['sample_count'] == 15
    assert all(p['median'] is None and p['sample_count'] is None
               for p in current['scopes']['phu-hoa']['history'][:-1])
    assert target.read_bytes() == content


@pytest.mark.parametrize('slug', NEW)
def test_v3_route_is_503_noindex_before_a_covering_snapshot_exists(monkeypatch, tmp_path, slug):
    app, mod = make_app(monkeypatch, tmp_path)
    mod.freeze_snapshot(json.loads(LEGACY.read_bytes()), tmp_path)
    response = app.test_client().get('/gia-dat/' + slug)
    assert response.status_code == 503
    assert response.headers['X-Robots-Tag'] == 'noindex'
    assert response.headers['Cache-Control'] == 'private, no-store'


@pytest.mark.parametrize('slug,name', NEW.items())
@pytest.mark.parametrize('n', [14, 15])
def test_v3_ssr_prices_and_sitemap_require_15_own_samples(monkeypatch, tmp_path, slug, name, n):
    rows = [row(i, ward=name) for i in range(n)] + [row(100, ward='Phú Lợi')]
    app, mod = make_app(monkeypatch, tmp_path, rows)
    response = app.test_client().get('/gia-dat/' + slug)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert f'Giá rao đất nền {name}' in html and f'n = {n}' in html
    assert f'href="https://radarbds.vn/gia-dat/{slug}"' in html
    assert 'href="/gia-dat/thu-dau-mot"' in html
    assert 'ward=' in html and 'prop_type=dat_nen' in html
    assert ('data-fact-id=' in html) is (n >= 15)
    assert ('noindex' in html) is (n < 15)
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert ('/gia-dat/' + slug in {e['path'] for e in mod.sitemap_entries(tmp_path)}) is (n >= 15)


@pytest.mark.parametrize('change', ['missing_v3_scope', 'extra_v2_scope', 'unknown_version'])
def test_v3_validator_preserves_exact_version_specific_registries(change):
    mod = engine()
    snap = packet(mod)
    if change == 'missing_v3_scope':
        snap['scopes'].pop('phu-hoa')
    elif change == 'extra_v2_scope':
        snap = json.loads(LEGACY.read_bytes())
        snap['scopes']['phu-hoa'] = deepcopy(snap['scopes']['phu-loi'])
    else:
        snap['scope_registry_version'] = 999
    snap['sha256'] = mod.digest({k: v for k, v in snap.items() if k != 'sha256'})
    with pytest.raises(ValueError, match='scope policy'):
        mod.validate_snapshot(snap)


@pytest.mark.parametrize('slug,name', NEW.items())
def test_v3_public_cards_keep_exact_guest_filters_and_drop_internal_source(monkeypatch, slug, name):
    mod = engine()
    import services.market_data as market
    seen = {}
    def load(db, **kwargs):
        seen.update(kwargs)
        return {'signals': [dict(row(88, ward=name, source='guland'),
                                 title='INTERNAL', contact_phone='PRIVATE', img='secret.jpg')]}
    monkeypatch.setattr(market, 'load_signals', load)
    assert mod.load_public_cards(slug) == []
    assert seen['tier'] == 'guest' and seen['sources'] == ['facebook']
    assert seen['wards'] == [name] and seen['limit'] == 5
    assert seen['date_range'] == '1m' and seen['include_total'] is False
