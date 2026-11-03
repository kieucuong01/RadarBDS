from flask import Flask,request
import pytest
from services.market_data import get_base_filters,build_listing_filters

@pytest.mark.parametrize('province',[None,'binh-duong','ha-noi','dong-nai','invalid'])
def test_province_filter_does_not_leak_binh_duong_listings(province,monkeypatch):
    monkeypatch.setattr('auth.core.current_tier',lambda:'guest')
    query={'city':'THỦ DẦU MỘT','ward':'Tân An'}
    if province is not None:query['province']=province
    with Flask(__name__).test_request_context('/',query_string=query):
        _,wards,*_=get_base_filters(request)
    sql,params=build_listing_filters(wards=wards)
    if province in (None,'binh-duong'):
        assert wards==['Tân An']
    else:
        assert wards==['__NO_WARD_SELECTED__'] and 'Tân An' not in params
    assert 'ward IN (?)' in sql
