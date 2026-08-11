from __future__ import annotations

from pathlib import Path

from config.traffic_priority import active_traffic_priority_pages
from scripts.verify_traffic_visibility import (
    FetchedResponse,
    aggregate_gsc_csv,
    verify_visibility,
)


BASE_URL = "https://radarbds.vn"


def _valid_html(path: str) -> str:
    canonical = BASE_URL + (path if path != "/" else "/")
    return (
        "<!doctype html><html><head>"
        f'<link rel="canonical" href="{canonical}">'
        '<meta name="robots" content="index,follow">'
        "</head><body><h1>Priority page</h1></body></html>"
    )


def _valid_responses() -> dict[str, FetchedResponse]:
    paths = [page.path for page in active_traffic_priority_pages()]
    sitemap = "".join(
        f"<url><loc>{BASE_URL}{path if path != '/' else '/'}</loc></url>"
        for path in paths
    )
    responses = {
        f"{BASE_URL}/robots.txt": FetchedResponse(
            200,
            {"content-type": "text/plain"},
            f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n",
        ),
        f"{BASE_URL}/sitemap.xml": FetchedResponse(
            200,
            {"content-type": "application/xml"},
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sitemap}</urlset>',
        ),
    }
    for path in paths:
        responses[f"{BASE_URL}{path if path != '/' else '/'}"] = FetchedResponse(
            200,
            {"content-type": "text/html"},
            _valid_html(path),
        )
    return responses


def _fetcher(responses: dict[str, FetchedResponse]):
    def fetch(url: str, timeout: float) -> FetchedResponse:
        assert timeout > 0
        return responses[url]

    return fetch


def test_visibility_rejects_noindex_x_robots_and_wrong_canonical():
    responses = _valid_responses()
    path = "/binh-duong/phuong-phu-tan"
    responses[f"{BASE_URL}{path}"] = FetchedResponse(
        200,
        {"x-robots-tag": "noindex"},
        (
            '<html><head><meta name="robots" content="noindex">'
            f'<link rel="canonical" href="{BASE_URL}/wrong"></head>'
            "<body><h1>One</h1><h1>Two</h1></body></html>"
        ),
    )

    report = verify_visibility(BASE_URL, fetcher=_fetcher(responses), timeout=2)
    codes = {item.code for item in report.failures if item.path == path}

    assert {
        "x_robots_noindex",
        "meta_robots_noindex",
        "canonical_mismatch",
        "h1_count",
    } <= codes


def test_visibility_reports_network_error_as_unknown():
    def unavailable(url: str, timeout: float) -> FetchedResponse:
        raise OSError("network unavailable")

    report = verify_visibility(BASE_URL, fetcher=unavailable, timeout=1)

    assert report.failures == ()
    assert report.unknowns
    assert {item.code for item in report.unknowns} == {"fetch_unknown"}


def test_visibility_requires_priority_paths_in_sitemap():
    responses = _valid_responses()
    responses[f"{BASE_URL}/sitemap.xml"] = FetchedResponse(
        200,
        {"content-type": "application/xml"},
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>',
    )

    report = verify_visibility(BASE_URL, fetcher=_fetcher(responses), timeout=2)

    missing = [item for item in report.failures if item.code == "sitemap_missing_path"]
    assert len(missing) == 20


def _write_csv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8-sig")
    return path


def test_gsc_csv_accepts_english_and_vietnamese_headers(tmp_path: Path):
    english = _write_csv(
        tmp_path / "english.csv",
        "Query,Page,Clicks,Impressions,CTR,Position\n"
        f"phu tan,{BASE_URL}/binh-duong/phuong-phu-tan,2,10,20%,4.5\n",
    )
    vietnamese = _write_csv(
        tmp_path / "vietnamese.csv",
        "Truy vấn,Trang,Lượt nhấp,Lượt hiển thị,CTR,Vị trí\n"
        f"phu tan,{BASE_URL}/binh-duong/phuong-phu-tan,3,15,20%,5.5\n",
    )

    assert aggregate_gsc_csv(english)[0].clicks == 2
    assert aggregate_gsc_csv(vietnamese)[0].impressions == 15


def test_gsc_csv_normalizes_utm_pages_to_canonical_priority_paths(tmp_path: Path):
    export = _write_csv(
        tmp_path / "utm.csv",
        "Query,Page,Clicks,Impressions,CTR,Position\n"
        f"radar bds,{BASE_URL}/?utm_source=facebook#signal,4,20,20%,2\n"
        f"radar bds,{BASE_URL}/?utm_source=ai,1,5,20%,4\n",
    )

    rows = aggregate_gsc_csv(export)

    assert len(rows) == 1
    assert rows[0].page == "/"
    assert rows[0].clicks == 5
    assert rows[0].impressions == 25
    assert rows[0].ctr == 0.2


def test_gsc_report_does_not_infer_dashboard_clicks(tmp_path: Path):
    export = _write_csv(
        tmp_path / "gsc.csv",
        "Query,Page,Clicks,Impressions,CTR,Position\n"
        f"bao cao,{BASE_URL}/bao-cao,7,70,10%,3\n",
    )

    row = aggregate_gsc_csv(export)[0]

    assert row.dashboard_clicks is None
