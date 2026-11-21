"""An Điền exact-locality expansion; frozen v7, source and guest boundaries."""
from copy import deepcopy
from datetime import date
import html
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from tests.test_data_price_seo import engine, packet, row, make_app

LEGACY = Path(__file__).parent / 'fixtures/data_price_seo/registry-v7.json'
V7 = set(json.loads(LEGACY.read_bytes())['scopes'])


def test_v8_adds_only_exact_an_dien_without_expanding_parent_geography():
    mod = engine()
    assert mod.SCOPE_REGISTRY_VERSION == 8
    assert mod.SCOPE_REGISTRIES[7] == V7
    assert set(mod.SCOPES) == V7 | {'an-dien'}
    assert mod.SCOPES['an-dien'] == {'name':'An Điền', 'wards':('An Điền',), 'parent':'ben-cat'}
    rows = [row(i, ward='An Điền') for i in range(15)]
    rows += [row(100, ward='Long Nguyên'), row(101, ward='Bến Cát'), row(102, ward='Phú An')]
    snap = packet(mod, rows)
    assert snap['scopes']['an-dien']['sample_count'] == 15
    assert snap['scopes']['ben-cat']['sample_count'] == 16
    assert snap['scopes']['thu-dau-mot']['sample_count'] == 0
    assert all(f['scope'] == 'an-dien' and f['sample_count'] == 15 for f in snap['scopes']['an-dien']['facts'].values())


def test_frozen_v7_bytes_facts_and_an_dien_history_remain_unchanged(tmp_path):
    mod = engine(); raw = LEGACY.read_bytes(); old = json.loads(raw)
    mod.validate_snapshot(old)
    mod.validate_claims(old, old['sha256'], [old['scopes']['my-phuoc']['facts']['median']])
    target = tmp_path / (old['snapshot_id']+'.json'); target.write_bytes(raw)
    snap = packet(mod, [row(i, ward='An Điền', last_seen_at='2026-11-21') for i in range(15)], as_of=date(2026,11,21), previous=[old])
    scope = snap['scopes']['an-dien']
    assert all(p['median'] is None and p['sample_count'] is None for p in scope['history'][:-1])
    assert scope['change_mtd_pct'] is None
    assert target.read_bytes() == raw


def test_an_dien_fails_closed_until_new_snapshot_exists(monkeypatch,tmp_path):
    app, mod = make_app(monkeypatch,tmp_path)
    mod.freeze_snapshot(json.loads(LEGACY.read_bytes()),tmp_path)
    r = app.test_client().get('/gia-dat/an-dien')
    assert r.status_code == 503
    assert r.headers['X-Robots-Tag'] == 'noindex'
    assert r.headers['Cache-Control'] == 'private, no-store'


@pytest.mark.parametrize('n',[14,15])
def test_an_dien_threshold_sitemap_named_parent_and_ben_cat_cta(monkeypatch,tmp_path,n):
    import app as app_module
    calls=[]
    monkeypatch.setattr(app_module,'_latest_ward_report',lambda *a,**kw:calls.append(a) or None)
    app, mod = make_app(monkeypatch,tmp_path,[row(i,ward='An Điền') for i in range(n)]+[row(100,ward='Phú An')])
    r=app.test_client().get('/gia-dat/an-dien');body=r.get_data(as_text=True)
    assert r.status_code==200
    assert 'Giá rao đất nền An Điền, Bến Cát' in body and f'n = {n}' in body
    assert 'href="https://radarbds.vn/gia-dat/an-dien"' in body
    assert 'href="/gia-dat/ben-cat"' in body
    directory_hrefs = re.findall(r'href="([^"]+)"', body)
    assert any(urlsplit(html.unescape(href)).path == '/binh-duong/phuong-an-dien' for href in directory_hrefs)
    assert ('data-fact-id=' in body)==(n>=15)
    assert ('noindex' in body)==(n<15)
    assert ('/gia-dat/an-dien' in {e['path'] for e in mod.sitemap_entries(tmp_path)})==(n>=15)
    assert r.headers['Cache-Control']=='private, no-store'
    match=re.search(r'<a[^>]+href="([^"]+)"[^>]+data-track-cta="asking_prices_open_deals"',body)
    assert match
    qs=parse_qs(urlsplit(html.unescape(match[1])).query)
    assert qs['city']==['BẾN CÁT'] and qs['ward']==['An Điền']
    assert calls==[]


@pytest.mark.parametrize('invalid',[
    dict(ward='Long Nguyên'),dict(ward='Bến Cát'),dict(ward='Phú An'),dict(source='batdongsan'),
    dict(duplicate_of_id=99),dict(possibly_duplicate=1),dict(review_hidden=1),dict(is_blacklisted=1),
    dict(is_outlier=1),dict(valuation_is_outlier=1),dict(suspicious_bait=1),dict(probably_sold=1),
    dict(source_status='inactive'),dict(tx_type='thue'),dict(property_type='nha_tro'),
    dict(price_per_m2=float('nan')),dict(price_ty=0),dict(area_m2=None),dict(price_per_m2=200),
    dict(last_seen_at=None),dict(last_seen_at='2026-09-30'),dict(last_seen_at='2026-10-22'),
    dict(extraction_quality_flags='area_dimension_conflict'),dict(source_quality_flags='suspicious_bait'),
])
def test_an_dien_invalid_record_never_crosses_local_price_threshold(invalid):
    mod=engine();rows=[row(i,ward='An Điền') for i in range(14)]
    rows.append(row(100,**dict({'ward':'An Điền'},**invalid)))
    scope=packet(mod,rows)['scopes']['an-dien']
    assert scope['sample_count']==14 and not scope['eligible']
    assert all(f['value'] is None for f in scope['facts'].values())
    assert scope['histogram']==[]


def test_an_dien_known_identity_is_not_counted_twice():
    mod=engine();rows=[row(i,ward='An Điền') for i in range(14)]
    rows.append(deepcopy(rows[0]))
    assert packet(mod,rows)['scopes']['an-dien']['sample_count']==14


def test_an_dien_internal_aggregate_does_not_reveal_guland_cards(monkeypatch):
    mod=engine();snap=packet(mod,[row(i,ward='An Điền',source='guland') for i in range(15)])
    assert snap['scopes']['an-dien']['eligible']
    import services.market_data as market
    seen={}
    def load(db,**kwargs):
        seen.update(kwargs)
        return {'signals':[dict(row(88,ward='An Điền',source='guland'),title='INTERNAL',contact_phone='PRIVATE')]}
    monkeypatch.setattr(market,'load_signals',load)
    assert mod.load_public_cards('an-dien')==[]
    assert seen['tier']=='guest' and seen['sources']==['facebook'] and seen['wards']==['An Điền']
    assert seen['limit']==5 and seen['include_total'] is False


@pytest.mark.parametrize('change',['missing_v8_scope','extra_v7_scope','unknown_version'])
def test_v8_frozen_registry_validation_fails_closed(change):
    mod=engine();snap=packet(mod)
    assert mod.SCOPE_REGISTRIES[7]==V7
    if change=='missing_v8_scope':snap['scopes'].pop('an-dien')
    elif change=='extra_v7_scope':
        snap=json.loads(LEGACY.read_bytes());snap['scopes']['an-dien']=deepcopy(snap['scopes']['phu-loi'])
    else:snap['scope_registry_version']=999
    snap['sha256']=mod.digest({k:v for k,v in snap.items() if k!='sha256'})
    with pytest.raises(ValueError,match='scope policy'):mod.validate_snapshot(snap)
