"""Versioned, prebuilt public report artifacts. No browser work in HTTP requests."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

PROJECT = Path(__file__).resolve().parents[1]
PDF_ROOT = PROJECT / 'reports' / 'monthly-pdf'
PDF_PUBLIC_ORIGIN = 'https://radarbds.vn'


@lru_cache(maxsize=1)
def _layout_version() -> str:
    digest = hashlib.sha256()
    for name in ('templates/seo_report.html', 'static/css/report_print.css',
                 'static/css/seo.css', 'static/css/public_research.css',
                 'static/css/public_brand.css', 'scripts/build_report_pdfs.py',
                 'services/report_buyer.py', 'services/report_buyer_snapshot.py',
                 'templates/partials/report_buyer_overview.html',
                 'templates/partials/report_buyer_checklist.html', 'static/css/report_buyer.css'):
        digest.update((PROJECT / name).read_bytes())
    return digest.hexdigest()


def pdf_version(page: dict) -> str:
    # Ward price/sample facts also drive master/neighbor comparison blocks.
    from config.seo_pages import SEO_PAGES
    period = re.search(r'-thang-(\d{2}-\d{4})$', page.get('path', ''))
    related = []
    if period:
        for other in SEO_PAGES.values():
            if other.get('variant') == 'report' and other.get('path', '').endswith(period.group(0)):
                body = other.get('report') or {}
                related.append({key: body.get(key) for key in ('basis_count', 'metrics', 'area_rows', 'buyer_snapshot')})
    snapshot = json.dumps(dict(page=page, related=related), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256((_layout_version() + snapshot).encode()).hexdigest()[:20]


def pdf_path(page: dict, *, root: Path | None = None) -> Path:
    path = str(page.get('path') or '')
    if page.get('variant') != 'report' or not re.fullmatch(r'/bao-cao/[a-z0-9-]+', path):
        raise ValueError('Expected a published monthly report path')
    return (root if root is not None else PDF_ROOT) / f'{path.rsplit("/", 1)[1]}-{pdf_version(page)}.pdf'


def pdf_download_href(page: dict) -> str | None:
    if page.get('variant') != 'report':
        return None
    if not pdf_path(page).is_file():
        return None
    return f'{page["path"]}/pdf?v={pdf_version(page)}'
