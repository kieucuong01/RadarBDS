"""Prebuild A4 PDFs from published report pages, including rendered Chart.js charts.

Run after the web process has loaded the current report config. Artifacts are
atomic, ignored runtime files; a failed render never replaces a valid PDF.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from services.report_pdf import PDF_PUBLIC_ORIGIN, pdf_path, pdf_version


def select_reports(*, month=None, year=None, slug=None) -> list[dict]:
    from app import _published_report_pages, _report_period_key
    pages = _published_report_pages()
    if slug:
        return [p for p in pages if p['path'] == f'/bao-cao/{slug}']
    if month is not None and year is not None:
        return [p for p in pages if _report_period_key(p) == (year, month)]
    return pages


def build_pdf(browser, report: dict, base_url: str) -> Path:
    target = pdf_path(report)
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    # Match A4's content width after the 14 mm side margins so canvases do not stretch.
    page = browser.new_page(viewport={'width': 688, 'height': 970}, locale='vi-VN')
    origin = urlsplit(base_url)
    chart_url = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js'

    def allow_asset(route):
        url = urlsplit(route.request.url)
        local = (url.scheme, url.netloc) == (origin.scheme, origin.netloc)
        allowed = local and (url.path == report['path'] or url.path.startswith('/static/'))
        if route.request.method == 'GET' and (allowed or route.request.url == chart_url):
            route.continue_()
        else:
            route.abort()

    temporary = None
    try:
        page.route('**/*', allow_asset)
        page.emulate_media(media='print')
        response = page.goto(base_url + report['path'] + '?pdf_export=1', wait_until='networkidle', timeout=60000)
        if response is None or response.status != 200 or urlsplit(page.url).path != report['path']:
            raise RuntimeError('Report did not load at its exact published path')
        version = page.locator('meta[name="radar-report-pdf-version"]').get_attribute('content')
        if version != pdf_version(report):
            raise RuntimeError('Web report snapshot differs from PDF job; restart web service first')
        page.evaluate('document.fonts.ready')
        if not page.evaluate("document.fonts.check('500 12px \"Plus Jakarta Sans\"')"):
            raise RuntimeError('Vietnamese report font is not ready')
        page.evaluate("""publicOrigin => {
            const canonicalOrigin = new URL(document.querySelector('link[rel="canonical"]').href).origin;
            document.querySelectorAll('a[href]').forEach(link => {
                const target = new URL(link.href);
                if (target.origin === location.origin || target.origin === canonicalOrigin) {
                    link.href = publicOrigin + target.pathname + target.search + target.hash;
                }
            });
        }""", PDF_PUBLIC_ORIGIN)
        chart_ids = page.locator('canvas[id]').evaluate_all('(els) => els.map(el => el.id)')
        if chart_ids:
            page.wait_for_function("ids => typeof Chart !== 'undefined' && ids.every(id => Chart.getChart(id))",
                                   arg=chart_ids, timeout=30000)
            page.evaluate("""() => {
                Object.values(Chart.instances).forEach(chart => {
                    chart.options.animation = false;
                    chart.resize(); chart.update('none');
                });
            }""")
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
        page.pdf(path=str(temporary), format='A4', print_background=True,
                 margin={'top': '15mm', 'right': '14mm', 'bottom': '18mm', 'left': '14mm'},
                 display_header_footer=True,
                 header_template='<span></span>',
                 footer_template='''<div style="font:9px Arial;color:#64748b;width:100%;margin:0 14mm;display:flex;justify-content:space-between"><span>RADAR BDS | radarbds.vn</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>''')
        if temporary.stat().st_size < 1000 or temporary.read_bytes()[:5] != b'%PDF-':
            raise RuntimeError('Invalid PDF output')
        temporary.chmod(0o644)
        temporary.replace(target)
        return target
    finally:
        page.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--month', type=int)
    parser.add_argument('--year', type=int)
    parser.add_argument('--slug')
    parser.add_argument('--all', action='store_true', help='Backfill all published closed-month reports')
    parser.add_argument('--base-url', default='http://127.0.0.1:5000')
    args = parser.parse_args()
    if not (args.all or args.slug or (args.month and args.year)):
        parser.error('Select --all, --slug, or both --month and --year')
    origin = urlsplit(args.base_url)
    if origin.scheme not in {'http', 'https'} or not origin.netloc or origin.username or origin.password or origin.query or origin.fragment or origin.path not in {'', '/'}:
        parser.error('--base-url must be an HTTP(S) origin without credentials')
    reports = select_reports(month=args.month, year=args.year, slug=args.slug)
    if not reports:
        parser.error('No published closed-month report matches this selection')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as driver:
        with driver.chromium.launch(headless=True) as browser:
            for report in reports:
                result = build_pdf(browser, report, args.base_url.rstrip('/'))
                print(f'PDF OK {report["path"]} ({result.stat().st_size:,} bytes)', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
