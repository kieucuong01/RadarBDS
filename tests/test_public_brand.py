"""Every shared-header page must load the public identity after layout CSS."""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_TEMPLATES = [
    p for p in (ROOT / 'templates').glob('*.html')
    if 'partials/seo_header.html' in p.read_text(encoding='utf-8')
]


@pytest.mark.parametrize('template', PUBLIC_TEMPLATES, ids=lambda p: p.name)
def test_public_identity_follows_page_layout_assets(template):
    source = template.read_text(encoding='utf-8')
    head = source.split('</head>', 1)[0]
    include = '{% include "partials/public_brand_assets.html" %}'
    assert source.count(include) == 1
    assert head.rstrip().endswith(include)


@pytest.mark.parametrize('path', [
    '/tin-tuc', '/tin-tuc/chu-de-nong', '/tin-tuc/du-lieu-radarbds',
    '/tin-tuc/quyet-dinh-van-ban', '/dinh-gia-bds', '/bang-gia-dat-tphcm',
    '/bao-cao', '/bao-cao/bds-binh-duong-thang-06-2026',
    '/ban-do-thu-dau-mot', '/binh-duong/my-phuoc', '/quy-hoach-binh-duong',
])
def test_public_response_loads_brand_after_all_layout_styles(path):
    import app as radar_app
    response = radar_app.app.test_client().get(path)
    assert response.status_code == 200
    head = response.get_data(as_text=True).split('</head>', 1)[0]
    stylesheets = re.findall(r'<link[^>]+href="([^"]+\.css[^" ]*)"', head)
    assert sum('public_brand.css' in href for href in stylesheets) == 1
    assert 'public_brand.css' in stylesheets[-1]
    html = response.get_data(as_text=True)
    assert html.count('class="public-brand-mark"') == 2
    assert html.count('class="public-brand-wordmark"') == 2
    assert 'fonts/noto-serif' not in head
