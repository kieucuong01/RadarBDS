from __future__ import annotations

import pytest

from services.public_marketing import EDITORIAL_OWNER_NAME, build_trust_context


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
