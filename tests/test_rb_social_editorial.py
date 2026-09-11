from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from PIL import Image

import scripts.radar_social_queue as queue
import scripts.rb_social_editorial as editorial


def test_all_six_pillars_are_supported_with_distinct_visual_layouts():
    assert set(editorial.PILLARS) == {
        "news_explainer",
        "radar_insight",
        "map_guide",
        "buyer_checklist",
        "listing_breakdown",
        "radar_howto",
    }
    layouts = {cfg["layout"] for cfg in editorial.PILLARS.values()}
    palettes = {tuple(cfg["palette"]) for cfg in editorial.PILLARS.values()}
    assert len(layouts) == 6
    assert len(palettes) == 6


def test_verified_news_can_use_explicit_social_editorial_caption():
    page = {
        "title": "Đề xuất tuyến kết nối mới",
        "path": "/tin-tuc/de-xuat-tuyen-ket-noi-moi",
        "article": {"published_at": "2026-09-01"},
        "social_editorial": {
            "pillar": "news_explainer",
            "topic": "Phân biệt đề xuất và quyết định đầu tư",
            "caption": "Tin hạ tầng có chữ “đề xuất” thì chưa nên hiểu là sắp khởi công. Người mua nên hỏi văn bản nào, giai đoạn nào và khu đất mình xem có liên quan trực tiếp hay không.",
            "source_url": "https://example.gov.vn/van-ban/tuyen-ket-noi",
            "source_date": "2026-09-01",
            "source_status": "đề xuất",
            "source_scope": "Bình Dương cũ",
            "source_verified": True,
            "reader_benefit": "Biết cách đọc tin hạ tầng trước khi dùng để trả giá.",
        },
    }

    draft = editorial.build_editorial(
        page,
        "https://radarbds.vn/tin-tuc/de-xuat-tuyen-ket-noi-moi",
        "de-xuat-tuyen-ket-noi-moi",
        make_visual=False,
        source_http_status=200,
    )

    assert draft["status"] == "ready"
    assert draft["pillar"] == "news_explainer"
    assert draft["caption"] == page["social_editorial"]["caption"]
    assert draft["metadata"]["source"]["url"] == "https://example.gov.vn/van-ban/tuyen-ket-noi"
    assert draft["metadata"]["source"]["date"] == "2026-09-01"
    assert draft["metadata"]["source"]["status"] == "đề xuất"
    assert draft["metadata"]["source"]["scope"] == "Bình Dương cũ"


def test_news_without_primary_source_is_blocked_not_rewritten_as_a_trend():
    page = {
        "title": "Cao tốc có thể nối về Bình Dương cũ",
        "path": "/tin-tuc/cao-toc-co-the-noi-ve-binh-duong-cu",
        "social_editorial": {"pillar": "news_explainer", "topic": "Tin hạ tầng chờ nguồn"},
    }

    draft = editorial.build_editorial(
        page,
        "https://radarbds.vn/tin-tuc/cao-toc-co-the-noi-ve-binh-duong-cu",
        "cao-toc-co-the-noi-ve-binh-duong-cu",
        make_visual=False,
        source_http_status=200,
    )

    assert draft["status"] == "blocked"
    assert any("primary-source" in reason for reason in draft["blocking_reasons"])
    assert "tăng giá" not in draft.get("caption", "").casefold()


def test_radar_insight_caption_hides_raw_metrics_but_metadata_keeps_evidence():
    page = {
        "title": "Tỷ lệ cắt máu nhà đất Thủ Dầu Một: phường nào cần kiểm tra kỹ?",
        "path": "/tin-tuc/ty-le-cat-mau-nha-dat-thu-dau-mot-phuong-nao-can-kiem-tra",
        "scope_label": "Thủ Dầu Một · 13 phường · dữ liệu Facebook",
        "article": {
            "published_at": "2026-09-10",
            "summary_cards": [
                {"label": "Đất nền", "value": "14/432 · 3,2%", "note": "property_type = dat_nen"},
                {"label": "Nhà đất", "value": "26/610 · 4,3%", "note": "property_type = nha_dat"},
            ],
        },
    }

    draft = editorial.build_editorial(
        page,
        "https://radarbds.vn/tin-tuc/ty-le-cat-mau-nha-dat-thu-dau-mot-phuong-nao-can-kiem-tra",
        "ty-le-cat-mau-nha-dat-thu-dau-mot-phuong-nao-can-kiem-tra",
        make_visual=False,
        source_http_status=200,
    )

    assert draft["status"] == "ready"
    assert "14/432" not in draft["caption"]
    assert "property_type" not in draft["caption"]
    assert "trung vị" not in draft["caption"]
    assert editorial.caption_quality_issues(draft["caption"]) == []
    assert any("14/432" in str(item) for item in draft["metadata"]["evidence"])
    assert any("property_type = dat_nen" in str(item) for item in draft["metadata"]["evidence"])


def test_listing_breakdown_requires_verified_listing_or_hypothetical_label():
    unverified = {
        "title": "Mổ xẻ một tin ghi giảm sâu",
        "path": "/tin-tuc/mo-xe-tin-giam-sau",
        "social_editorial": {"pillar": "listing_breakdown", "topic": "Tin giảm giá"},
    }
    blocked = editorial.build_editorial(
        unverified,
        "https://radarbds.vn/tin-tuc/mo-xe-tin-giam-sau",
        "mo-xe-tin-giam-sau",
        make_visual=False,
        source_http_status=200,
    )
    assert blocked["status"] == "blocked"
    assert any("listing-rights" in reason for reason in blocked["blocking_reasons"])

    hypothetical = {
        **unverified,
        "social_editorial": {
            "pillar": "listing_breakdown",
            "topic": "So một tin giảm giá giả định",
            "hypothetical": True,
        },
    }
    ready = editorial.build_editorial(
        hypothetical,
        "https://radarbds.vn/tin-tuc/mo-xe-tin-giam-sau",
        "mo-xe-tin-giam-sau",
        make_visual=False,
        source_http_status=200,
    )
    assert ready["status"] == "ready"
    assert "giả định" in ready["caption"].casefold()


def test_visual_asset_uses_source_date_and_version_without_overwriting(tmp_path):
    page = {
        "title": "Tin ghi gần Vành đai 3: hỏi lối vào trước khi đi xem",
        "path": "/tin-tuc/gan-vanh-dai-3-hoi-loi-vao",
        "article": {"published_at": "2026-08-24"},
        "social_editorial": {"pillar": "map_guide", "topic": "Gần đường lớn chưa đủ"},
    }

    draft = editorial.build_editorial(
        page,
        "https://radarbds.vn/tin-tuc/gan-vanh-dai-3-hoi-loi-vao",
        "gan-vanh-dai-3-hoi-loi-vao",
        asset_dir=tmp_path,
        source_http_status=200,
    )

    visual_path = Path(draft["visual"]["path"])
    assert visual_path.exists()
    assert "rbedit-v" in visual_path.name
    assert "2026-08-24" in visual_path.name
    with Image.open(visual_path) as image:
        assert image.size in {(1080, 1080), (1080, 1350)}
    assert draft["visual"]["source_date"] == "2026-08-24"


def test_publish_quality_gate_fails_closed_for_missing_or_bad_source_status():
    with pytest.raises(ValueError, match="skip-verify.*review"):
        editorial.enforce_source_gate(
            mode="publish",
            skip_verify=True,
            http_status=200,
            source_url="https://radarbds.vn/tin-tuc/x",
        )
    with pytest.raises(ValueError, match="healthy source"):
        editorial.enforce_source_gate(
            mode="publish",
            skip_verify=False,
            http_status=None,
            source_url="https://radarbds.vn/tin-tuc/x",
        )
    with pytest.raises(ValueError, match="healthy source"):
        editorial.enforce_source_gate(
            mode="publish",
            skip_verify=False,
            http_status=404,
            source_url="https://radarbds.vn/tin-tuc/x",
        )


def test_queue_create_uses_editorial_schema_and_self_comment_without_fake_ward(tmp_path, monkeypatch):
    page = {
        "title": "Tin ghi gần Vành đai 3: hỏi lối vào trước khi đi xem",
        "path": "/tin-tuc/gan-vanh-dai-3-hoi-loi-vao",
        "scope_label": "Thủ Dầu Một · 13 phường · dữ liệu Facebook",
        "article": {"published_at": "2026-08-24"},
        "social_editorial": {"pillar": "map_guide", "topic": "Gần đường lớn chưa đủ"},
    }
    monkeypatch.setattr(queue, "_choose_article", lambda slug: ("gan-vanh-dai-3-hoi-loi-vao", page))
    monkeypatch.setattr(queue, "ASSET_DIR", tmp_path)

    item = queue.create(
        argparse.Namespace(
            slug="latest",
            skip_verify=True,
            platform="facebook",
            surface="page",
            page_url="https://www.facebook.com/radarbdsvn/",
            mode="review",
            style="data_post",
        )
    )

    assert item["content"]["generated_by"] == "rb_social_editorial"
    assert item["content"]["editorial"]["pillar"] == "map_guide"
    assert "utm_medium=pinned_comment" in item["content"]["self_comment"]
    assert "ward=Th%E1%BB%A7" not in item["content"]["self_comment"]
    assert "13%20ph%C6%B0%E1%BB%9Dng" not in item["content"]["self_comment"]
    assert item["content"]["message"] == item["content"]["editorial"]["caption"]
