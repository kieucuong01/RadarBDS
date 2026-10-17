"""Shared navigation and report form placement stay usable across research pages."""
import re

import pytest


@pytest.mark.parametrize('path', ['/dinh-gia-bds', '/bang-gia-dat-tphcm', '/bao-cao', '/bao-cao/bds-binh-duong-thang-06-2026'])
def test_research_navigation_and_assets_are_present(path):
    import app as radar_app
    html = radar_app.app.test_client().get(path).get_data(as_text=True)
    nav = re.search(r'<nav class="research-nav".*?</nav>', html, re.S).group(0)
    assert nav.count('aria-current="page"') == 1
    assert 'public_research.css' in html
    for href in ['/dinh-gia-bds', '/bang-gia-dat-tphcm', '/bao-cao']:
        assert f'href="{href}"' in nav


def test_report_lead_form_does_not_interrupt_or_repeat_inside_metrics():
    import app as radar_app
    html = radar_app.app.test_client().get('/bao-cao/bds-binh-duong-thang-06-2026').get_data(as_text=True)
    assert html.count('class="seo-lead-capture"') == 1
    assert html.index('id="report-method"') < html.index('class="seo-lead-capture"')
    assert 'href="#report-method"' in html
