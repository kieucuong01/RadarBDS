"""Mỹ Phước grouped locality and Bến Cát parent; no geography/guest widening."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import re
import html
import pytest
from tests.test_data_price_seo import engine,packet,row,make_app

LEGACY=Path(__file__).parent/'fixtures/data_price_seo/registry-v6.json'
V6=set(json.loads(LEGACY.read_bytes())['scopes'])
NEW={'my-phuoc','ben-cat'}


def test_v7_groups_only_existing_my_phuoc_subwards_and_explicit_ben_cat_whitelist():
    mod=engine()
    from config.area_profiles import MY_PHUOC_PROFILE
    from services.market_data import CITY_MAP
    assert set(mod.SCOPES['my-phuoc']['wards'])=={'Mỹ Phước'}|set(MY_PHUOC_PROFILE['sub_wards'])
    assert set(mod.SCOPES['ben-cat']['wards'])==set(CITY_MAP['BẾN CÁT'])
    rows=[row(i,ward='Mỹ Phước '+str(i%4+1)) for i in range(15)]
    rows += [row(50,ward='Phú An'),row(51,ward='Phú Lợi'),row(52,ward='Bến Cát'),row(53,ward='Other')]
    snap=packet(mod,rows)
    assert snap['scope_registry_version']==7 and set(snap['scopes'])==V6|NEW
    scope=snap['scopes']['my-phuoc']
    assert scope['parent']=='ben-cat' and scope['sample_count']==15
    assert snap['scopes']['ben-cat']['sample_count']==16
    assert snap['scopes']['thu-dau-mot']['sample_count']==1
    assert all(f['scope']=='my-phuoc' and f['sample_count']==15 for f in scope['facts'].values())


def test_v7_retains_exact_v6_packet_and_no_invented_new_locality_history(tmp_path):
    mod=engine();raw=LEGACY.read_bytes();old=json.loads(raw)
    assert mod.SCOPE_REGISTRIES[6]==V6
    mod.validate_snapshot(old);mod.validate_claims(old,old['sha256'],[old['scopes']['phu-loi']['facts']['median']])
    path=tmp_path/(old['snapshot_id']+'.json');path.write_bytes(raw)
    snap=packet(mod,[row(i,ward='Mỹ Phước 3',last_seen_at='2026-11-20') for i in range(15)],as_of=date(2026,11,20),previous=[old])
    for slug in NEW:
        scope=snap['scopes'][slug]
        assert scope['change_mtd_pct'] is None
        assert all(p['median'] is None and p['sample_count'] is None for p in scope['history'][:-1])
    assert path.read_bytes()==raw


@pytest.mark.parametrize('slug',sorted(NEW))
def test_new_routes_fail_closed_with_frozen_v6_packet(monkeypatch,tmp_path,slug):
    app,mod=make_app(monkeypatch,tmp_path)
    mod.freeze_snapshot(json.loads(LEGACY.read_bytes()),tmp_path)
    response=app.test_client().get('/gia-dat/'+slug)
    assert response.status_code==503
    assert response.headers['X-Robots-Tag']=='noindex'
    assert response.headers['Cache-Control']=='private, no-store'


@pytest.mark.parametrize('n',[14,15])
def test_my_phuoc_threshold_parent_sitemap_and_correct_filter_destination(monkeypatch,tmp_path,n):
    app,mod=make_app(monkeypatch,tmp_path,[row(i,ward='Mỹ Phước 3') for i in range(n)]+[row(100,ward='Phú An')])
    r=app.test_client().get('/gia-dat/my-phuoc');body=r.get_data(as_text=True)
    assert r.status_code==200
    assert 'Giá rao đất nền Mỹ Phước, Bến Cát' in body
    assert f'n = {n}' in body
    assert ('data-fact-id=' in body)==(n>=15)
    assert ('noindex' in body)==(n<15)
    assert 'href="/gia-dat/ben-cat"' in body
    assert ('/gia-dat/my-phuoc' in {e['path'] for e in mod.sitemap_entries(tmp_path)})==(n>=15)
    assert r.headers['Cache-Control']=='private, no-store'
    match=re.search(r'<a[^>]+href="([^"]+)"[^>]+data-track-cta="asking_prices_open_deals"',body)
    assert match
    qs=parse_qs(urlsplit(html.unescape(match[1])).query)
    assert qs['city']==['BẾN CÁT'] and set(qs['ward'])==set(mod.SCOPES['my-phuoc']['wards'])
    assert '/binh-duong/phuong-my-phuoc' not in body
    assert 'href="/binh-duong/my-phuoc"' in body
    assert 'không phải một phường hành chính' in body


def test_ben_cat_parent_does_not_borrow_tdm_caption_or_closed_month_report(monkeypatch,tmp_path):
    import app as app_module
    calls=[]
    monkeypatch.setattr(app_module,'_latest_ward_report',lambda *a,**kw:calls.append(a) or None)
    app,mod=make_app(monkeypatch,tmp_path,[row(i,ward='Mỹ Phước 3') for i in range(15)])
    body=app.test_client().get('/gia-dat/ben-cat').get_data(as_text=True)
    assert '<caption>Bến Cát, từ ' in body
    assert '<caption>Thủ Dầu Một, từ ' not in body
    assert calls==[]
    qs=parse_qs(urlsplit(html.unescape(re.search(r'<a[^>]+href="([^"]+)"[^>]+data-track-cta="asking_prices_open_deals"',body)[1])).query)
    assert qs['city']==['BẾN CÁT'] and 'ward' not in qs


@pytest.mark.parametrize('invalid',[dict(ward='Phú Lợi'),dict(ward='Bến Cát'),dict(duplicate_of_id=99),dict(possibly_duplicate=1),dict(review_hidden=1),dict(is_blacklisted=1),dict(is_outlier=1),dict(suspicious_bait=1),dict(probably_sold=1),dict(tx_type='thue'),dict(property_type='nha_pho'),dict(price_per_m2=float('nan')),dict(price_ty=0),dict(last_seen_at=None)])
def test_my_phuoc_invalid_rows_never_cross_small_n_gate(invalid):
    mod=engine();rows=[row(i,ward='Mỹ Phước 3') for i in range(14)]
    rows.append(row(100,**dict({'ward':'Mỹ Phước 3'},**invalid)))
    s=packet(mod,rows)['scopes']['my-phuoc']
    assert s['sample_count']==14 and not s['eligible']
    assert all(f['value'] is None for f in s['facts'].values())


@pytest.mark.parametrize('slug',sorted(NEW))
def test_new_scopes_keep_internal_guland_out_of_guest_cards(monkeypatch,slug):
    mod=engine()
    import services.market_data as market
    seen={}
    def load(db,**kwargs):
        seen.update(kwargs)
        return {'signals':[dict(row(99,ward='Mỹ Phước 3',source='guland'),title='INTERNAL',contact_phone='PRIVATE')]}
    monkeypatch.setattr(market,'load_signals',load)
    assert mod.load_public_cards(slug)==[]
    assert seen['tier']=='guest' and seen['sources']==['facebook']
    assert seen['limit']==5 and seen['include_total'] is False


@pytest.mark.parametrize('change',['missing_new_scope','extra_frozen_scope','unknown_version'])
def test_v7_rejects_missing_or_extra_registry_scope(change):
    mod=engine();assert mod.SCOPE_REGISTRIES[7]==V6|NEW
    snap=packet(mod)
    if change=='missing_new_scope':snap['scopes'].pop('my-phuoc')
    elif change=='extra_frozen_scope':
        snap=json.loads(LEGACY.read_bytes());snap['scopes']['my-phuoc']=deepcopy(snap['scopes']['phu-loi'])
    else:snap['scope_registry_version']=999
    snap['sha256']=mod.digest({k:v for k,v in snap.items() if k!='sha256'})
    with pytest.raises(ValueError,match='scope policy'):mod.validate_snapshot(snap)
