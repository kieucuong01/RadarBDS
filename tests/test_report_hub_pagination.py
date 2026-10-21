import json
import re

import pytest

import app as radar_app
from services.report_hub import REPORTS_PER_PAGE, report_archive


@pytest.fixture
def reports():
    return radar_app._decorate_report_hub_pages([
        {"path": f"/bao-cao/report-{n}", "hero_title": f"Báo cáo {n}",
         "scope_label": "Phú Tân" if n == 26 else "Hiệp Thành",
         "report": {"period": "Tháng 09/2026", "published_at": "2026-10-01"}}
        for n in range(28)
    ])


def test_archive_has_bounded_pages_without_lost_or_duplicate_reports(reports):
    pages = [report_archive(*reports, {"page": str(n)}) for n in (1, 2, 3)]
    assert [len(page["items"]) for page in pages] == [12, 12, 3]
    assert pages[0]["featured"]["path"] == "/bao-cao/report-0"
    assert pages[1]["featured"] is None
    paths = [item["path"] for page in pages for item in page["items"]]
    assert paths == [item["path"] for item in reports[0][1:]]
    assert pages[1]["previous"] == "/bao-cao"
    assert pages[1]["next"] == "/bao-cao?page=3"


def test_filters_search_whole_archive_including_featured_and_restore_get_state(reports):
    page = report_archive(*reports, {"q": "phu tan", "period": "2026-09"})
    assert [item["path"] for item in page["items"]] == ["/bao-cao/report-26"]
    assert page["featured"] is None
    assert page["filters"]["q"] == "phu tan"
    latest = report_archive(*reports, {"q": "Báo cáo 0"})
    assert latest["items"][0]["path"] == "/bao-cao/report-0"
    filtered = report_archive(*reports, {"ward": "Hiệp Thành", "page": "2"})
    assert "ward=Hi%E1%BB%87p+Th%C3%A0nh&page=3" in filtered["next"]
    assert "page=" not in filtered["city_links"]["tdm"]


@pytest.mark.parametrize("value", ["0", "-1", "4", "abc", "9999999999999999999999", "١"])
def test_invalid_pages_are_not_soft_duplicates(reports, value):
    with pytest.raises(ValueError):
        report_archive(*reports, {"page": value})


def test_empty_matches_have_no_page_links(reports):
    page = report_archive(*reports, {"q": "no-matching-report"})
    assert page["items"] == []
    assert page["start"] == page["end"] == 0
    assert page["previous"] is page["next"] is None
    literal_all = report_archive(*reports, {"q": "all"})
    assert literal_all["filtered"]
    assert literal_all["url"] == "/bao-cao?q=all"


def test_rendered_archive_has_crawlable_pages_and_only_visible_schema_items(monkeypatch):
    monkeypatch.setattr(radar_app, "current_tier", lambda: "guest")
    monkeypatch.setattr(radar_app, "current_user", lambda: None)
    client = radar_app.app.test_client()
    first = client.get("/bao-cao").get_data(as_text=True)
    second = client.get("/bao-cao?page=2").get_data(as_text=True)
    assert first.count("data-report-card\n") == REPORTS_PER_PAGE
    assert 'href="/bao-cao?page=2#report-archive"' in first
    assert 'rel="canonical" href="https://radarbds.vn/bao-cao?page=2"' in second
    assert "Trang 2</title>" in second
    assert 'data-featured-report=' not in second
    blocks = re.findall(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', second, re.S)
    data = json.loads(blocks[-1])
    items = next(item for item in data["@graph"] if item["@type"] == "ItemList")["itemListElement"]
    paths = re.findall(r'data-report-path="([^"]+)"', second)
    assert [item["url"].split("radarbds.vn")[1] for item in items] == paths
    assert len(items) <= REPORTS_PER_PAGE
    assert client.get("/bao-cao?page=999").status_code == 404


def test_filtered_html_is_restored_without_javascript_and_noindexed(monkeypatch):
    monkeypatch.setattr(radar_app, "current_tier", lambda: "guest")
    monkeypatch.setattr(radar_app, "current_user", lambda: None)
    html = radar_app.app.test_client().get("/bao-cao?q=phu+tan").get_data(as_text=True)
    assert 'name="robots" content="noindex, follow"' in html
    assert 'name="q" value="phu tan"' in html
    assert 'data-ward="Phú Tân"' in html
    assert 'data-ward="Hiệp Thành"' not in html
    assert 'method="get"' in html
