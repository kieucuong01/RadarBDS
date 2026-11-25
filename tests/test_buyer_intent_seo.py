"""Real strict filter/owner behavior; mocks only external feed/DB boundaries."""
import importlib.util
from contextlib import contextmanager
from pathlib import Path
import copy
import json
import pytest

ROOT=Path(__file__).resolve().parents[1]
SLUG='dat-nen-ben-cat-duoi-2-ty-khu-nao-con-nhieu-tin'
PATH='/tin-tuc/'+SLUG

def buyer():
    spec=importlib.util.spec_from_file_location('buyer_under_test',ROOT/'services/buyer_intent_seo.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def record(i=1,**kw):
    result=dict(id=i,source='facebook',ward='Phú An',property_type='dat_nen',tx_type='ban',price_ty=1.5,area_m2=100.0,is_active=1,review_hidden=0,is_blacklisted=0,duplicate_of_id=None,possibly_duplicate=0,source_status='active',probably_sold=0)
    result.update(kw)
    return result

@pytest.mark.parametrize('price',[2,2.000001,0,-1,None,float('nan'),float('inf'),'bad'])
def test_strict_budget_rejects_boundary_or_invalid_price(price):
    m=buyer()
    assert m.select_public_results([record()], [record(price_ty=price)])==[]

@pytest.mark.parametrize('change',[
    {'source':'guland'},{'source':'batdongsan'},{'ward':'Long Nguyên'},
    {'ward':'Thủ Dầu Một'},{'ward':'Other'},{'tx_type':'thue'},
    {'tx_type':None},{'property_type':'nha_dat'},{'property_type':'nha_tro'},
    {'is_active':0},{'review_hidden':1},{'is_blacklisted':1},
    {'duplicate_of_id':2},{'possibly_duplicate':1},{'source_status':'inactive'},
    {'probably_sold':1},{'area_m2':0},{'area_m2':float('nan')},
    {'id':'1'},{'id':-1},
])
def test_current_primary_row_must_still_match_sale_source_location_visibility(change):
    m=buyer()
    assert m.select_public_results([record()], [record(**change)])==[]

def test_guest_candidate_boundary_cannot_be_replaced_with_internal_rows():
    m=buyer()
    assert m.select_public_results([record(source='guland')],[record()])==[]
    assert m.select_public_results([],[record()])==[]
    assert m.select_public_results([record()],[])==[]

def test_projects_only_safe_current_values_and_keeps_feed_order():
    m=buyer()
    candidate=record(title='PRIVATE_TITLE',phone='PRIVATE_PHONE',url='https://guland.vn/private')
    current=record(price_ty=1.99,area_m2=120,title='PRIVATE_DB_TITLE')
    assert m.select_public_results([record(2),candidate,candidate],[current,record(2)])==[
        dict(id=2,ward='Phú An',area_m2=100.0,price_ty=1.5),
        dict(id=1,ward='Phú An',area_m2=120.0,price_ty=1.99),
    ]

def test_result_count_is_bounded_and_not_claimed_as_warehouse_total():
    m=buyer();rows=[record(i) for i in range(1,50)]
    cards=m.select_public_results(rows,rows)
    assert len(cards)==20 and cards[-1]['id']==20


def test_loader_reuses_guest_dispatcher_and_readonly_bounded_primary_keys(monkeypatch):
    m=buyer();calls={};rows=[record(i) for i in range(1,31)]
    def feed(*args,**kw):calls['feed']=kw;return {'listings':rows,'total':9999}
    class Connection:
        def execute(self,sql,params=()):
            calls.setdefault('sql',[]).append((sql,params));return self
        def fetchall(self):return rows
    @contextmanager
    def connection():yield Connection()
    monkeypatch.setattr(m,'load_listing_feed',feed)
    monkeypatch.setattr(m,'get_conn',connection)
    monkeypatch.setattr(m,'get_durable_dataset_versions',lambda names:{'listings':321})
    result=m.load_results()
    kw=calls['feed']
    assert kw['tier']=='guest' and kw['sources']==['facebook']
    assert kw['prop_types']==['dat_nen'] and kw['price_max']==2
    assert kw['limit']==30 and kw['page']==1 and kw['date_range']=='1m'
    assert kw['listings_version']==321 and set(kw['wards'])==set(m.WARDS)
    assert calls['sql'][0][0]=='SET TRANSACTION READ ONLY'
    assert len(calls['sql'][1][1][0])==30 and 'ANY' in calls['sql'][1][0]
    assert result['count']==20 and result['eligible'] and result['available']
    assert 'total' not in result and '9999' not in json.dumps(result)

@pytest.mark.parametrize('stage',['feed','version','primary'])
def test_loader_failure_is_unknown_not_zero_or_empty_market(monkeypatch,stage):
    m=buyer()
    def fail(*a,**kw):raise RuntimeError('secret database details')
    monkeypatch.setattr(m,'get_durable_dataset_versions',fail if stage=='version' else lambda names:{'listings':0})
    monkeypatch.setattr(m,'load_listing_feed',fail if stage=='feed' else lambda *a,**kw:{'listings':[record()]})
    monkeypatch.setattr(m,'get_conn',fail)
    result=m.load_results()
    assert not result['available'] and not result['eligible'] and result['count'] is None
    assert 'secret' not in json.dumps(result)

def test_page_metadata_preserves_exact_owner_without_mutating_static_article():
    m=buyer()
    from config.seo_articles import SEO_ARTICLES
    before=copy.deepcopy(SEO_ARTICLES[SLUG]);page=m.prepare_page(before)
    assert SEO_ARTICLES[SLUG]==before and page['path']==PATH
    assert page['primary_href']=='#tin-dat-duoi-2-ty'
    assert page['article']['data_tables']==before['article']['data_tables']
    assert page['article']['modified_at']=='2026-11-25'
    assert '99 tin' not in page['description']
    assert 'dưới 2 tỷ' in page['hero_title']

@pytest.mark.parametrize('available,count',[(True,3),(True,2),(True,0),(False,None)])
def test_real_owner_ssr_cards_or_honest_fallback_and_private_response(monkeypatch,available,count):
    m=buyer()
    import app as radar_app
    from services import buyer_intent_seo as actual
    cards=[dict(id=100+i,ward='Phú An',price_ty=1.5,area_m2=100.0) for i in range(count or 0)]
    payload=dict(available=available,count=count,cards=cards,eligible=bool(available and count>=3),generated_at='2026-11-25T18:30:00+07:00')
    monkeypatch.setattr(actual,'load_results',lambda:payload)
    response=radar_app.app.test_client().get(PATH)
    body=response.get_data(as_text=True)
    assert response.status_code==200 and 'id="tin-dat-duoi-2-ty"' in body
    assert '<link rel="canonical" href="https://radarbds.vn'+PATH+'">' in body
    assert response.headers['X-Radar-Buyer-Intent']=='dat-duoi-2-ty-ben-cat'
    assert response.headers['X-Radar-Buyer-Intent-Eligible']==str(int(payload['eligible']))
    assert 'private' in response.headers['Cache-Control'] and 'no-store' in response.headers['Cache-Control']
    assert not response.headers.get('X-Radar-Public-Cache')
    assert 'không phải tổng số' in body and 'không gồm tin đúng 2 tỷ' in body
    assert '08–21/09/2026' in body and 'Bản phân tích theo kỳ đã lưu' in body
    assert 'price_max=2' not in body.split('id="tin-dat-duoi-2-ty"',1)[1].split('</section>',1)[0]
    if available:
        assert body.count('data-buyer-listing-id=')==count
    else:
        assert 'Chưa tải được danh sách hiện tại' in body
        assert 'Hiện không có tin công khai' not in body


def test_sitemap_preserves_one_exact_owner_and_real_editorial_update(monkeypatch):
    buyer()
    import app as radar_app
    monkeypatch.setattr(radar_app._public_content_repository,'list_published',lambda **kw:[])
    with radar_app.app.test_request_context('/sitemap.xml'):
        body=radar_app.sitemap_xml().get_data(as_text=True)
    import xml.etree.ElementTree as ET
    entries=[n for n in ET.fromstring(body).findall('{*}url') if n.find('{*}loc').text=='https://radarbds.vn'+PATH]
    assert len(entries)==1 and entries[0].find('{*}lastmod').text=='2026-11-25'
    assert '/mua-dat/ben-cat-duoi-2-ty' not in body
