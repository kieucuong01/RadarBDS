from __future__ import annotations

import json
import re

import pytest

from services.public_marketing import EDITORIAL_OWNER_NAME, build_public_entities, build_trust_context


def test_failed_live_snapshot_omits_false_update_date():
    page = {"variant": "location", "live_snapshot": {"available": False}}

    trust = build_trust_context(page, page_type="location")

    assert "modified_at" not in trust
    assert "tạm thời chưa khả dụng" in trust["source_label"]


@pytest.mark.parametrize(
    ("path", "marker"),
    [
        ("/tin-tuc/gia-rao-khac-gia-giao-dich-the-nao", "Thông tin biên tập"),
        ("/bao-cao/bds-binh-duong-thang-07-2026", "Phương pháp và giới hạn"),
        ("/binh-duong/phuong-hiep-thanh", "Nguồn dữ liệu"),
        ("/tin-tuc/du-lieu-radarbds", "Thông tin biên tập"),
    ],
)
def test_public_page_types_render_truthful_trust(path, marker):
    import app as radar_app

    response = radar_app.app.test_client().get(path)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'class="seo-trust-panel"' in html
    assert marker in html
    assert EDITORIAL_OWNER_NAME in html


@pytest.mark.parametrize("path", ["/quy-hoach-binh-duong", "/ban-do-binh-duong"])
def test_map_and_planning_pages_keep_existing_source_sections_without_trust_panel(path):
    import app as radar_app

    html = radar_app.app.test_client().get(path).get_data(as_text=True)

    assert 'class="seo-trust-panel"' not in html


def _json_ld_graph(html: str) -> list[dict]:
    scripts = re.findall(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, flags=re.DOTALL)
    graphs = []
    for script in scripts:
        payload = json.loads(script)
        graphs.extend(payload.get("@graph", [payload]))
    return graphs


def test_public_entity_builder_returns_fresh_stable_entities():
    first = build_public_entities("https://radarbds.vn")
    second = build_public_entities("https://radarbds.vn/")

    assert first["organization"]["@id"] == "https://radarbds.vn/#organization"
    assert first["website"]["@id"] == "https://radarbds.vn/#website"
    assert first["organization"] == second["organization"]
    assert first["organization"] is not second["organization"]


@pytest.mark.parametrize(
    "path",
    [
        "/tin-tuc/gia-rao-khac-gia-giao-dich-the-nao",
        "/bao-cao/bds-binh-duong-thang-07-2026",
        "/binh-duong/phuong-hiep-thanh",
        "/tin-tuc",
        "/quy-hoach-binh-duong",
        "/ban-do-binh-duong",
        "/dinh-gia-bds",
        "/bang-gia-dat-tphcm",
    ],
)
def test_representative_public_schema_uses_stable_entities_and_vietnamese_language(path):
    import app as radar_app

    response = radar_app.app.test_client().get(path)
    graph = _json_ld_graph(response.get_data(as_text=True))
    by_id = {item.get("@id"): item for item in graph if item.get("@id")}

    assert response.status_code == 200
    assert by_id["https://radarbds.vn/#organization"]["url"] == "https://radarbds.vn/"
    assert by_id["https://radarbds.vn/#website"]["inLanguage"] == "vi-VN"
    for item in graph:
        if item.get("@type") in {"BlogPosting", "Article", "Report", "WebPage", "CollectionPage", "Dataset", "WebApplication"}:
            assert item.get("inLanguage") == "vi-VN"
