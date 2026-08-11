import json
import re

import app as radar_app

from config.seo_locations import TDM_LIVE_WARDS
from config.traffic_priority import (
    active_traffic_priority_pages,
    traffic_priority_by_path,
)
from services.marketing_page_audit import audit_marketing_pages
from services.traffic_priority import build_traffic_priority_context


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


def test_priority_proof_uses_available_live_snapshot_date():
    context = build_traffic_priority_context(
        "/binh-duong/phuong-phu-tan",
        page={
            "live_snapshot": {
                "available": True,
                "updated_iso": "2026-08-11T09:00:00+07:00",
            }
        },
    )

    assert context["proof"]["updated_at"] == "2026-08-11T09:00:00+07:00"
    assert context["proof"]["mode"] == "live_snapshot"


def test_priority_proof_falls_back_without_inventing_date_or_count():
    context = build_traffic_priority_context(
        "/binh-duong/phuong-phu-tan",
        page={"live_snapshot": {"available": False}},
    )

    assert context["proof"]["mode"] == "method_only"
    assert "updated_at" not in context["proof"]
    assert "count" not in context["proof"]


def test_priority_links_are_bounded_unique_and_never_self_link():
    context = build_traffic_priority_context("/binh-duong/phuong-phu-tan")
    paths = [
        item["href"].split("?", 1)[0]
        for item in context["related_links"]
    ]

    assert len(paths) <= 4
    assert len(paths) == len(set(paths))
    assert "/binh-duong/phuong-phu-tan" not in paths


def test_non_priority_path_has_no_priority_context():
    assert build_traffic_priority_context("/tin-tuc") == {}


def test_representative_priority_pages_render_one_shared_proof_block():
    client = radar_app.app.test_client()
    paths = (
        "/",
        "/dinh-gia-bds",
        "/binh-duong/phuong-phu-tan",
        "/quy-hoach-binh-duong/dia-gioi-36-phuong-xa-binh-duong-cu",
        "/tin-tuc/cach-dinh-gia-nha-dat-binh-duong-bang-gia-rao-theo-phuong",
    )

    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.get_data(as_text=True).count("data-traffic-priority-proof") == 1, path


def test_all_priority_pages_render_indexable_canonical_proven_contracts():
    client = radar_app.app.test_client()
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)

    for page in active_traffic_priority_pages():
        response = client.get(page.path)
        html = response.get_data(as_text=True)
        canonical = "https://radarbds.vn" + (page.path if page.path != "/" else "/")

        assert response.status_code == 200, page.path
        assert _h1_texts(html) and len(_h1_texts(html)) == 1, page.path
        assert html.count(f'<link rel="canonical" href="{canonical}">') == 1, page.path
        assert not re.search(
            r'<meta[^>]+name=["\']robots["\'][^>]+content=["\'][^"\']*noindex',
            html,
            re.I,
        ), page.path
        assert "noindex" not in response.headers.get("X-Robots-Tag", "").casefold(), page.path
        assert html.count("data-traffic-priority-proof") == 1, page.path
        assert f"<loc>{canonical}</loc>" in sitemap, page.path

        schema_blocks = re.findall(
            r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
            html,
            re.S,
        )
        assert schema_blocks, page.path
        for block in schema_blocks:
            json.loads(block)
