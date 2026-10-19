"""Keep useful tools ahead of marketing and retain existing interaction hooks."""
import re
from urllib.parse import parse_qs, urlsplit

import pytest


@pytest.mark.parametrize('path', ['/ban-do-thu-dau-mot', '/ban-do-ben-cat', '/ban-do-di-an', '/ban-do-thuan-an'])
def test_city_map_precedes_lead_and_context(path):
    import app as radar_app
    html = radar_app.app.test_client().get(path).get_data(as_text=True)
    assert html.index('data-binh-duong-map-canvas') < html.index('class="seo-lead-capture"')
    assert html.index('data-binh-duong-map-canvas') < html.index('class="tdm-product-proof-list"')
    assert 'href="#ban-do-tuong-tac"' in html
    assert 'data-map-layer="legacy"' in html and 'data-map-layer="current"' in html
    assert html.count('class="seo-lead-capture"') == 1


@pytest.mark.parametrize(('slug','name','city'), [('thu-dau-mot','Thủ Dầu Một','THỦ DẦU MỘT'), ('ben-cat','Bến Cát','BẾN CÁT'), ('my-phuoc','Mỹ Phước','BẾN CÁT')])
def test_area_copy_and_dashboard_handoff_match_scope(slug,name,city):
    from config.seo_locations import SEO_LOCATION_PAGES
    import app as radar_app
    page=SEO_LOCATION_PAGES['binh-duong/'+slug]
    params=parse_qs(urlsplit(page['dashboard_href']).query)
    assert params['city']==[city]
    if slug=='my-phuoc': assert params['q']==['Mỹ Phước']
    html=radar_app.app.test_client().get('/binh-duong/'+slug).get_data(as_text=True)
    assert 'ở '+name+'?' in html
    assert 'discovery-area-guide' in html
    assert html.index('discovery-area-guide') < html.index('class="seo-lead-capture"')


def test_method_explains_example_before_lead():
    import app as radar_app
    html=radar_app.app.test_client().get('/san-deal-bds').get_data(as_text=True)
    assert html.index('id="quy-trinh-loc"') < html.index('class="seo-lead-capture"')
    assert html.index('id="vi-du-mos"') < html.index('class="seo-lead-capture"')
    assert 'Ví dụ giả định' in html and '20%' in html
    assert 'href="#vi-du-mos"' in html


def test_mobile_dashboard_has_one_header_map_button_and_collapsible_context():
    from pathlib import Path
    import app as radar_app
    html=radar_app.app.test_client().get('/').get_data(as_text=True)
    header=re.search(r'<header class="header">.*?</header>',html,re.S).group(0)
    assert html.count('id="listingMapLauncher"')==1
    assert 'id="listingMapLauncher"' in header
    assert '<details class="dashboard-context">' in html
    assert 'id="areaScopeLabel"' in html and 'id="keywordSearchSignals"' in html
    assert 'onclick="openListingMap()"' in html
    assert 'dashboard_mobile_discovery.css' in html
