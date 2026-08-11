import re

import app as radar_app

from config.seo_locations import TDM_LIVE_WARDS
from config.traffic_priority import (
    active_traffic_priority_pages,
    traffic_priority_by_path,
)
from services.marketing_page_audit import audit_marketing_pages


def test_priority_registry_has_exact_twenty_unique_active_paths():
    pages = active_traffic_priority_pages()

    assert len(pages) == 20
    assert len({page.path for page in pages}) == 20
    assert traffic_priority_by_path("/").buyer_stage == "decide"


def test_priority_registry_matches_exact_canonical_tdm_wards():
    actual = {
        page.path.removeprefix("/binh-duong/phuong-")
        for page in active_traffic_priority_pages()
        if page.cluster == "ward"
    }

    assert actual == set(TDM_LIVE_WARDS)


def test_strict_marketing_audit_accepts_priority_registry():
    result = audit_marketing_pages(strict=True)

    assert not [
        item
        for item in result.hard_failures
        if item.code.startswith("traffic_priority_")
    ]


def _h1_texts(html: str) -> list[str]:
    return [
        re.sub(r"<[^>]+>", "", item).strip()
        for item in re.findall(r"<h1\b[^>]*>(.*?)</h1>", html, re.S)
    ]


def test_homepage_has_one_signal_first_h1():
    html = radar_app.app.test_client().get("/").get_data(as_text=True)

    assert _h1_texts(html) == ["Săn deal nhà đất Bình Dương bằng dữ liệu"]


def test_saved_page_keeps_one_saved_listings_h1():
    html = radar_app.app.test_client().get("/bds-da-luu").get_data(as_text=True)

    assert _h1_texts(html) == ["BDS đã lưu"]
