"""Exact Phú An data locality: frozen-v8, sample, source and guest gates."""
from copy import deepcopy
from datetime import date
import html
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from tests.test_data_price_seo import engine, packet, row, make_app

LEGACY = Path(__file__).parent / 'fixtures/data_price_seo/registry-v8.json'
V8 = set(json.loads(LEGACY.read_bytes())['scopes'])


def test_v9_adds_only_exact_phu_an_and_preserves_frozen_v8_geography():
    mod = engine()
    assert mod.SCOPE_REGISTRY_VERSION == 9
    assert mod.SCOPE_REGISTRIES[8] == V8
    assert set(mod.SCOPES) == V8 | {'phu-an'}
    assert mod.SCOPES['phu-an'] == {'name':'Phú An', 'wards':('Phú An',), 'parent':'ben-cat'}
    rows = [row(i, ward='Phú An') for i in range(15)]
    rows += [row(100, ward='Tân An'), row(101, ward='Hiệp An'), row(102, ward='Bến Cát')]
    snap = packet(mod, rows)
    assert snap['scopes']['phu-an']['sample_count'] == 15
    assert snap['scopes']['ben-cat']['sample_count'] == 15
    assert snap['scopes']['thu-dau-mot']['sample_count'] == 2
    assert all(f['scope']=='phu-an' and f['sample_count']==15 for f in snap['scopes']['phu-an']['facts'].values())


def test_frozen_v8_bytes_and_claims_survive_without_phu_an_history(tmp_path):
    mod=engine(); raw=LEGACY.read_bytes(); old=json.loads(raw)
    mod.validate_snapshot(old)
    mod.validate_claims(old,old['sha256'],[old['scopes']['an-dien']['facts']['median']])
    target=tmp_path/(old['snapshot_id']+'.json');target.write_bytes(raw)
    snap=packet(mod,[row(i,ward='Phú An',last_seen_at='2026-11-22') for i in range(15)],as_of=date(2026,11,22),previous=[old])
    scope=snap['scopes']['phu-an']
    assert all(p['median'] is None and p['sample_count'] is None for p in scope['history'][:-1])
    assert scope['change_mtd_pct'] is None
    assert target.read_bytes()==raw


def test_phu_an_route_fails_closed_on_frozen_v8_packet(monkeypatch,tmp_path):
    app,mod=make_app(monkeypatch,tmp_path)
    mod.freeze_snapshot(json.loads(LEGACY.read_bytes()),tmp_path)
    r=app.test_client().get('/gia-dat/phu-an')
    assert r.status_code==503
    assert r.headers['X-Robots-Tag']=='noindex'
    assert r.headers['Cache-Control']=='private, no-store'


@pytest.mark.parametrize('n',[14,15])
def test_phu_an_threshold_sitemap_parent_directory_and_exact_ben_cat_cta(monkeypatch,tmp_path,n):
    import app as app_module
    calls=[]
    monkeypatch.setattr(app_module,'_latest_ward_report',lambda *a,**kw:calls.append(a) or None)
    app,mod=make_app(monkeypatch,tmp_path,[row(i,ward='Phú An') for i in range(n)]+[row(100,ward='An Điền')])
    r=app.test_client().get('/gia-dat/phu-an');body=r.get_data(as_text=True)
    assert r.status_code==200
    assert 'Giá rao đất nền Phú An, Bến Cát' in body and f'n = {n}' in body
    assert 'href="https://radarbds.vn/gia-dat/phu-an"' in body
    assert 'href="/gia-dat/ben-cat"' in body
    assert any(urlsplit(html.unescape(h)).path=='/binh-duong/phuong-phu-an' for h in re.findall(r'href="([^"]+)"',body))
    assert ('data-fact-id=' in body)==(n>=15)
    assert ('noindex' in body)==(n<15)
    assert ('/gia-dat/phu-an' in {e['path'] for e in mod.sitemap_entries(tmp_path)})==(n>=15)
    assert r.headers['Cache-Control']=='private, no-store'
    match=re.search(r'<a[^>]+href="([^"]+)"[^>]+data-track-cta="asking_prices_open_deals"',body)
    assert match
    qs=parse_qs(urlsplit(html.unescape(match[1])).query)
    assert qs['city']==['BẾN CÁT'] and qs['ward']==['Phú An']
    assert calls==[]


@pytest.mark.parametrize('invalid',[
    dict(ward='Tân An'),dict(ward='Hiệp An'),dict(ward='Bến Cát'),dict(source='batdongsan'),
    dict(duplicate_of_id=99),dict(possibly_duplicate=1),dict(review_hidden=1),dict(is_blacklisted=1),
    dict(is_outlier=1),dict(valuation_is_outlier=1),dict(suspicious_bait=1),dict(probably_sold=1),
    dict(source_status='inactive'),dict(tx_type='thue'),dict(property_type='nha_tro'),
    dict(price_per_m2=float('nan')),dict(price_ty=0),dict(area_m2=None),dict(price_per_m2=200),
    dict(last_seen_at=None),dict(last_seen_at='2026-09-30'),dict(last_seen_at='2026-10-22'),
    dict(extraction_quality_flags='area_dimension_conflict'),dict(source_quality_flags='suspicious_bait'),
])
def test_invalid_record_cannot_raise_phu_an_to_price_threshold(invalid):
    mod=engine();rows=[row(i,ward='Phú An') for i in range(14)]
    rows.append(row(100,**dict({'ward':'Phú An'},**invalid)))
    scope=packet(mod,rows)['scopes']['phu-an']
    assert scope['sample_count']==14 and not scope['eligible']
    assert all(f['value'] is None for f in scope['facts'].values())
    assert scope['histogram']==[]


def test_repeated_phu_an_identity_does_not_supply_fifteenth_sample():
    mod=engine();rows=[row(i,ward='Phú An') for i in range(14)]
    rows.append(deepcopy(rows[0]))
    assert packet(mod,rows)['scopes']['phu-an']['sample_count']==14


def test_phu_an_internal_aggregate_never_reveals_guland_cards(monkeypatch):
    mod=engine();snap=packet(mod,[row(i,ward='Phú An',source='guland') for i in range(15)])
    assert snap['scopes']['phu-an']['eligible']
    import services.market_data as market
    seen={}
    def load(db,**kwargs):
        seen.update(kwargs)
        return {'signals':[dict(row(88,ward='Phú An',source='guland'),title='INTERNAL',contact_phone='PRIVATE')]}
    monkeypatch.setattr(market,'load_signals',load)
    assert mod.load_public_cards('phu-an')==[]
    assert seen['tier']=='guest' and seen['sources']==['facebook'] and seen['wards']==['Phú An']
    assert seen['limit']==5 and seen['include_total'] is False


@pytest.mark.parametrize('change',['missing_v9_scope','extra_v8_scope','unknown_version'])
def test_v9_registry_packet_validation_fails_closed(change):
    mod=engine();snap=packet(mod)
    assert mod.SCOPE_REGISTRIES[8]==V8
    if change=='missing_v9_scope':snap['scopes'].pop('phu-an')
    elif change=='extra_v8_scope':
        snap=json.loads(LEGACY.read_bytes());snap['scopes']['phu-an']=deepcopy(snap['scopes']['phu-loi'])
    else:snap['scope_registry_version']=999
    snap['sha256']=mod.digest({k:v for k,v in snap.items() if k!='sha256'})
    with pytest.raises(ValueError,match='scope policy'):mod.validate_snapshot(snap)


@pytest.mark.parametrize('key,value',[('unit','billion_vnd'),('sample_count',99),('display','0,00')])
def test_phu_an_claim_binding_rejects_altered_facts(key,value):
    mod=engine();snap=packet(mod,[row(i,ward='Phú An') for i in range(15)])
    fact=deepcopy(snap['scopes']['phu-an']['facts']['median']);fact[key]=value
    with pytest.raises(ValueError):mod.validate_claims(snap,snap['sha256'],[fact])
