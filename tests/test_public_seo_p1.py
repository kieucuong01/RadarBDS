"""Public search discovery must agree with content and data readiness."""
import re

import pytest


def test_empty_planning_category_stays_usable_but_not_indexable():
    import app as radar_app
    client = radar_app.app.test_client()
    path = '/quy-hoach-binh-duong/quy-hoach-chi-tiet'
    response = client.get(path)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.headers['X-Robots-Tag'] == 'noindex, follow'
    assert '<meta name="robots" content="noindex, follow">' in html
    assert 'href="/quy-hoach-binh-duong"' in html
    assert f'https://radarbds.vn{path}</loc>' not in client.get('/sitemap.xml').get_data(as_text=True)


@pytest.mark.parametrize(('slug', 'layer'), [
    ('quy-hoach-su-dung-dat', 'land_use_2030'),
    ('quy-hoach-phan-khu', 'partition'),
])
def test_planning_category_with_map_guide_is_discoverable(slug, layer):
    import app as radar_app
    client = radar_app.app.test_client()
    path = '/quy-hoach-binh-duong/' + slug
    response = client.get(path)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'noindex' not in response.headers.get('X-Robots-Tag', '')
    assert 'content="noindex, follow"' not in html
    assert f'planning={layer}' in html
    assert f'https://radarbds.vn{path}</loc>' in client.get('/sitemap.xml').get_data(as_text=True)
    assert f'href="{path}"' in client.get('/quy-hoach-binh-duong').get_data(as_text=True)


def test_category_becomes_indexable_when_specialty_article_is_added(monkeypatch):
    import app as radar_app
    path = '/quy-hoach-binh-duong/quy-hoach-chi-tiet'
    monkeypatch.setitem(radar_app.PLANNING_CATEGORY_PAGES['quy-hoach-chi-tiet'], 'categories', ('detailed',))
    source = dict(radar_app.PLANNING_PAGE_LIST[0], category='detailed')
    monkeypatch.setattr(radar_app, 'PLANNING_PAGE_LIST', [*radar_app.PLANNING_PAGE_LIST, source])
    client = radar_app.app.test_client()
    response = client.get(path)
    assert response.status_code == 200
    assert 'noindex' not in response.headers.get('X-Robots-Tag', '')
    assert 'content="noindex, follow"' not in response.get_data(as_text=True)
    assert 'data-planning-category-card' in response.get_data(as_text=True)
    assert f'https://radarbds.vn{path}</loc>' in client.get('/sitemap.xml').get_data(as_text=True)


@pytest.mark.parametrize('path', ['/binh-duong', '/san-deal-bds', '/binh-duong/thu-dau-mot'])
def test_non_live_landing_hero_does_not_present_demo_statistics(path):
    import app as radar_app
    html = radar_app.app.test_client().get(path).get_data(as_text=True)
    aside = re.search(r'<aside class="hero-map-stage hero-method-stage".*?</aside>', html, re.S).group(0)
    assert 'hero-method-card' in aside
    for fake_metric in ['128', '+24%', 'so với hôm qua', '2.35', '2.95', '20.3%', '<polyline', 'price-tag']:
        assert fake_metric not in aside
    assert 'không phải bản đồ giá trực tiếp' in aside


def test_dashboard_screenshot_is_labelled_and_counters_are_not_claimed_as_live():
    import app as radar_app
    html = radar_app.app.test_client().get('/binh-duong').get_data(as_text=True)
    assert 'số liệu trong ảnh không phản ánh dữ liệu hiện tại' in html
    assert '876+' not in html and '100+' not in html
