from __future__ import annotations

import copy

from config.seo_articles import SEO_ARTICLES
from scripts import rb_social_editorial as editorial

SLUG = "phu-loi-hay-hiep-an-nen-xem-khu-nao-truoc"
URL = "https://radarbds.vn/tin-tuc/phu-loi-hay-hiep-an-nen-xem-khu-nao-truoc"


def build(page: dict | None = None) -> dict:
    return editorial.build_editorial(
        copy.deepcopy(page or SEO_ARTICLES[SLUG]),
        URL,
        SLUG,
        make_visual=False,
        source_http_status=200,
    )


def test_actual_config_generates_reader_led_ward_budget_caption():
    draft = build()

    caption = draft["caption"]
    assert draft["status"] == "ready"
    assert caption.startswith("Tìm nhà đất giá rao dưới 3 tỷ: Phú Lợi hay Hiệp An?")
    assert "11/09/2026" in caption
    assert "Hiệp An" in caption and "63" in caption
    assert "Phú Lợi" in caption and "1" in caption
    assert "bắt đầu" in caption.casefold()
    assert "không phải khuyến nghị mua" in caption.casefold()
    assert "còn hàng" in caption.casefold()
    assert "giá chào hiện tại" in caption.casefold()
    assert "Số tin có thể gồm bài đăng lại" in caption
    assert "không phải 63 căn" in caption
    assert "giá rao, không phải giá đã bán" in caption
    assert "bình luận" in caption.casefold() or "comment" in caption.casefold()
    assert editorial.caption_quality_issues(caption) == []


def test_reader_caption_uses_dynamic_counts_from_source_rows():
    page = copy.deepcopy(SEO_ARTICLES[SLUG])
    for row in page["market_snapshot"]["rows"]:
        if row["ward_type"] == "Phú Lợi · nhà đất":
            row["under3"] = "17"
        if row["ward_type"] == "Hiệp An · nhà đất":
            row["under3"] = "4"

    caption = build(page)["caption"]

    assert "Phú Lợi" in caption and "17" in caption
    assert "Hiệp An" in caption and "4" in caption
    assert "bắt đầu ở Phú Lợi" in caption
    assert "63" not in caption


def test_reader_caption_has_no_low_value_snapshot_or_stat_jargon():
    caption = build()["caption"].casefold()

    for forbidden in ("snapshot", "trung vị", "dấu hiệu", "76", "96", "22 tin đất nền", "9 tin"):
        assert forbidden not in caption


def test_budget_counts_are_described_as_listing_rows_not_unique_houses():
    caption = build()["caption"].casefold()

    assert "không phải 63 căn" in caption
    assert "không phải 63 nhà" not in caption
    assert "63 căn nhà" not in caption


def test_equal_counts_do_not_pick_a_winner():
    page = copy.deepcopy(SEO_ARTICLES[SLUG])
    for row in page["market_snapshot"]["rows"]:
        if row["ward_type"] in {"Phú Lợi · nhà đất", "Hiệp An · nhà đất"}:
            row["under3"] = "12"

    caption = build(page)["caption"]

    assert "12" in caption
    assert "ngang nhau" in caption.casefold()
    assert "bắt đầu ở Phú Lợi" not in caption
    assert "bắt đầu ở Hiệp An" not in caption
    assert "phù hợp đường đi" in caption.casefold() or "đường đi" in caption.casefold()


def test_missing_or_non_comparable_budget_data_uses_safe_existing_fallback():
    page = copy.deepcopy(SEO_ARTICLES[SLUG])
    page["market_snapshot"]["rows"] = [
        {"ward_type": "Phú Lợi · đất nền", "under3": "9", "under4": "22"},
        {"ward_type": "Hiệp An · đất nền", "under3": "22", "under4": "22"},
    ]

    draft = build(page)

    assert draft["status"] == "ready"
    assert not draft["caption"].startswith("Tìm nhà đất giá rao dưới")
    assert "đừng dùng một con số chung" in draft["caption"]


def test_authored_multiline_caption_is_sanitized_without_collapsing_paragraphs():
    page = {
        "title": "Bài đã có caption riêng",
        "path": "/tin-tuc/bai-da-co-caption-rieng",
        "article": {"published_at": "2026-09-12"},
        "social_editorial": {
            "pillar": "radar_insight",
            "caption": "<p>Đoạn một đã viết kỹ.</p><p>Đoạn hai giữ nhịp đọc.</p>",
        },
    }

    caption = build(page)["caption"]

    assert caption == "Đoạn một đã viết kỹ.\n\nĐoạn hai giữ nhịp đọc."


def test_authored_stats_dump_is_replaced_when_structured_comparison_data_is_available():
    page = copy.deepcopy(SEO_ARTICLES[SLUG])
    page["social_editorial"] = {
        "pillar": "radar_insight",
        "caption": "Snapshot: Phú Lợi 76, Hiệp An 96, nhà đất dưới 3 tỷ 1/63, giá trung vị 52,0 vs 24,9 tr/m², dấu hiệu 9.",
    }

    caption = build(page)["caption"]

    assert caption.startswith("Tìm nhà đất giá rao dưới 3 tỷ")
    assert "Snapshot" not in caption
    assert "trung vị" not in caption
    assert "dấu hiệu" not in caption
