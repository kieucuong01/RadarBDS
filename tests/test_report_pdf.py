"""Snapshot PDF downloads must never render Chromium on the request path."""
from copy import deepcopy

import pytest


@pytest.fixture
def report():
    from config.seo_pages import SEO_PAGES
    return deepcopy(SEO_PAGES['bao-cao/bds-binh-duong-thang-09-2026'])


def test_artifact_key_tracks_snapshot_and_rejects_non_report_paths(report, tmp_path):
    from services.report_pdf import pdf_path, pdf_version
    old = pdf_version(report)
    report['report']['metrics'][0]['value'] = '999'
    assert pdf_version(report) != old
    assert pdf_path(report, root=tmp_path).parent == tmp_path
    for path in ['/bao-cao/../../secret', '/tin-tuc/article', '/bao-cao/slug/nested']:
        report['path'] = path
        with pytest.raises(ValueError):
            pdf_path(report, root=tmp_path)


def test_only_complete_current_snapshot_has_a_download(report, tmp_path, monkeypatch):
    from services import report_pdf
    monkeypatch.setattr(report_pdf, 'PDF_ROOT', tmp_path)
    assert report_pdf.pdf_download_href(report) is None
    target = report_pdf.pdf_path(report)
    target.write_bytes(b'%PDF-1.7\n' + b' ' * 2000)
    assert report_pdf.pdf_download_href(report).startswith(report['path'] + '/pdf?v=')
    report['report']['data_as_of'] = '2099-01-01'
    assert report_pdf.pdf_download_href(report) is None


def test_download_is_attachment_and_gated_by_published_report(report, tmp_path, monkeypatch):
    import app as radar_app
    from services import report_pdf
    monkeypatch.setattr(report_pdf, 'PDF_ROOT', tmp_path)
    target = report_pdf.pdf_path(report)
    target.write_bytes(b'%PDF-1.7\n' + b' ' * 2000)
    client = radar_app.app.test_client()
    response = client.get(report['path'] + '/pdf')
    assert response.status_code == 200
    assert response.mimetype == 'application/pdf'
    assert response.headers['Content-Disposition'].startswith('attachment;')
    assert 'noindex' in response.headers['X-Robots-Tag']
    assert 'X-Radar-Public-Cache' not in response.headers
    assert response.data.startswith(b'%PDF-')
    response.close()
    assert client.get(report['path'] + '/pdf?v=stale').status_code == 404
    assert client.get('/bao-cao/does-not-exist/pdf').status_code == 404
    assert client.get('/bao-cao/../../.env/pdf').status_code == 404
    monkeypatch.setattr(radar_app, '_is_publishable_monthly_report', lambda _: False)
    assert client.get(report['path'] + '/pdf').status_code == 404


def test_buttons_only_link_available_artifacts_and_exports_skip_tracking(report, tmp_path, monkeypatch):
    import app as radar_app
    from services import report_pdf
    monkeypatch.setattr(report_pdf, 'PDF_ROOT', tmp_path)
    client = radar_app.app.test_client()
    html = client.get(report['path']).get_data(as_text=True)
    assert 'Tải báo cáo PDF' not in html
    report_pdf.pdf_path(report).write_bytes(b'%PDF-1.7\n' + b' ' * 2000)
    html = client.get(report['path']).get_data(as_text=True)
    assert 'Tải báo cáo PDF' in html
    assert report['path'] + '/pdf?v=' in html
    assert 'report_print.css' in html
    export = client.get(report['path'] + '?pdf_export=1').get_data(as_text=True)
    assert 'radar-report-pdf-version' in export
    assert report_pdf.pdf_version(report) in export
    assert 'sendRadarEvent' not in export


def test_pdf_command_selects_closed_reports_without_redirecting_to_newer_month(report):
    from scripts.build_report_pdfs import select_reports
    selected = select_reports(month=9, year=2026)
    assert len(selected) == 14
    assert all(p['path'].endswith('-09-2026') for p in selected)
    assert select_reports(slug='not-published') == []


def test_monthly_job_prebuilds_pdf_before_live_verification():
    from pathlib import Path
    script = Path('scripts/radar_monthly_report_publish.py').read_text(encoding='utf-8')
    build = script.index('scripts/build_report_pdfs.py')
    assert build < script.index('verify_code = verify_live(month, year)', build)
    assert 'has_pdf' in script


def test_parent_pdf_version_tracks_related_frozen_price_facts(monkeypatch):
    from services.report_pdf import pdf_version
    from config import seo_pages
    pages = deepcopy(seo_pages.SEO_PAGES)
    monkeypatch.setattr(seo_pages, 'SEO_PAGES', pages)
    master = pages['bao-cao/bds-binh-duong-thang-09-2026']
    before = pdf_version(master)
    pages['bao-cao/tan-an-thang-09-2026']['report']['metrics'][2]['note'] = '18 mẫu đủ giá'
    assert pdf_version(master) != before
