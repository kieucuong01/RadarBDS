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


def test_report_preview_uses_snapshot_values_with_common_scale():
    import app as radar_app
    from flask import render_template_string
    report = {
        'scope_label': 'Phường thử nghiệm',
        'report': {'period': 'Tháng 09/2026'},
        'charts': [{'type': 'bar', 'title': 'Mẫu hợp lệ', 'labels': ['A', 'B'],
                    'datasets': [{'label': 'Số mẫu', 'data': [10, 20]}]}],
    }
    with radar_app.app.test_request_context():
        html = render_template_string('{% from "partials/report_visual.html" import report_visual %}{{ report_visual(report) }}', report=report)
    heights = re.findall(r'height="([\d.]+)"[^>]+data-report-value="(\d+)"', html)
    assert [(float(height), int(value)) for height, value in heights] == [(46, 10), (92, 20)]
    assert 'A: 10' in html and 'B: 20' in html
    assert 'Tháng 09/2026' in html


def test_report_preview_without_chart_has_no_invented_bars():
    import app as radar_app
    from flask import render_template_string
    report = {'scope_label': 'Khu vực', 'report': {'period': 'Tháng 09/2026'},
              'charts': [], 'hub_meta': {'primary_metric': {'value': '12', 'label': 'Mẫu hợp lệ'}}}
    with radar_app.app.test_request_context():
        html = render_template_string('{% from "partials/report_visual.html" import report_visual %}{{ report_visual(report) }}', report=report)
    assert '<svg' not in html
    assert '12' in html and 'Mẫu hợp lệ' in html
