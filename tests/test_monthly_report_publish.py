"""Read-only verifier regression using excerpts of real October public HTML.

Captured 2026-11-18 from the master and tan-an report URLs. The live pages
currently have no PDF link: tests add ONLY that explicit prerequisite to isolate
the November 1 master-card regression. A separate test retains the real missing
PDF state and must fail closed. No generator, app, DB or publisher main is run.
"""
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from scripts import radar_monthly_report_publish as publisher

FIXTURES = Path(__file__).parent / 'fixtures' / 'monthly_report'
MASTER, PATHS = publisher.expected_paths(10, 2026)
WARD = PATHS[1]


def fixture(name):
    return (FIXTURES / f'{name}_10_2026.html').read_text(encoding='utf-8')


def with_pdf(html, path):
    # Test-only cached-PDF prerequisite, NOT a claim about current live HTML.
    return html + f'<a href="{path}/pdf?v=test-cached-version">PDF</a>'


def with_cards(html, count):
    cards = re.findall(r'<article class="buyer-example">.*?</article>', html, re.S)
    assert len(cards) == 6
    for card in cards:
        html = html.replace(card, '', 1)
    return html + ''.join(cards[i % len(cards)] for i in range(count))


@pytest.fixture
def verify(monkeypatch):
    def check(master_html=None, ward_html=None, status='200', sitemap=None):
        master = with_pdf(fixture('master'), MASTER) if master_html is None else master_html
        ward = with_pdf(fixture('ward'), WARD) if ward_html is None else ward_html
        def http(path):
            if path == MASTER:
                return status, master
            return '200', ward.replace(WARD, path)
        def run(cmd, *, timeout):
            assert cmd == ['curl', '-sS', f'{publisher.DOMAIN}/sitemap.xml']
            return SimpleNamespace(stdout='\n'.join(PATHS) if sitemap is None else sitemap)
        monkeypatch.setattr(publisher, 'http_html', http)
        monkeypatch.setattr(publisher, 'run', run)
        return publisher.verify_live(10, 2026)
    return check


def test_october_master_buyer_examples_are_not_legacy_signal_cards(verify):
    assert fixture('master').count('class="buyer-example"') == 6
    assert verify() == 0


@pytest.mark.parametrize('count', range(7))
def test_buyer_master_allows_only_available_examples_up_to_six(verify, count):
    assert verify(with_cards(with_pdf(fixture('master'), MASTER), count)) == 0


def test_buyer_master_rejects_seven_examples(verify):
    assert verify(with_cards(with_pdf(fixture('master'), MASTER), 7)) == 3


def test_buyer_master_requires_current_listing_cta_with_examples(verify):
    html = with_pdf(fixture('master'), MASTER).replace('data-track-cta="report_buyer_current"', '')
    assert verify(html) == 3


def test_legacy_master_still_rejects_signal_cards(verify):
    html = with_cards(with_pdf(fixture('master'), MASTER), 0).replace('data-buyer-report="v1"', '')
    assert verify(html) == 0
    assert verify(html + '<article class="report-signal-card"></article>') == 3


@pytest.mark.parametrize('old,new', [
    ('radar-report-chart-count" content="2"', 'radar-report-chart-count" content="3"'),
    ('<canvas', '<missing-canvas'),
    ('/?tab=signals', '/?tab=removed'),
    ('city=TH', 'city=removed'),
    ('report-seo-links', 'removed-seo-links'),
    ('Tổng hợp 13 báo cáo phường Thủ Dầu Một', 'Removed heading'),
    ('href="/bao-cao/hoa-phu-thang-10-2026"', 'href="/removed"'),
])
def test_master_required_structure_still_fails_closed(verify, old, new):
    html = with_pdf(fixture('master'), MASTER)
    assert old in html
    assert verify(html.replace(old, new)) == 3


def test_missing_live_pdf_is_not_hidden(verify, capsys):
    assert verify(fixture('master')) == 3
    assert 'pdf=False' in capsys.readouterr().out


def test_http_failure_is_not_hidden(verify):
    assert verify(status='500') == 3


def test_missing_sitemap_path_is_not_hidden(verify):
    assert verify(sitemap='\n'.join(PATHS[:-1])) == 3


@pytest.mark.parametrize('count', [0, 1, 4, 6, 7])
def test_ward_card_limit_unchanged(verify, count):
    html = with_cards(with_pdf(fixture('ward'), WARD), count)
    assert verify(ward_html=html) == (0 if count <= 6 else 3)


@pytest.mark.parametrize('old,new', [
    ('data-track-cta="report_buyer_current"', ''),
    ('report-inline-links', 'removed-inline-links'),
    ('mos_min=10', 'mos_min=removed'),
    ('mos_min=15', 'mos_min=removed'),
    ('prop_type=dat_nen', 'prop_type=removed'),
    ('prop_type=nha_dat', 'prop_type=removed'),
    ('/pdf?v=', '/removed?v='),
])
def test_ward_structure_gates_unchanged(verify, old, new):
    html = with_pdf(fixture('ward'), WARD)
    assert old in html
    assert verify(ward_html=html.replace(old, new)) == 3
