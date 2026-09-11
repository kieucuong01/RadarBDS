"""Regression tests for Radar BDS Facebook editorial truthfulness.

The Page generator should no longer publish metric-heavy legacy captions. Raw
ratios/prices and pipeline labels stay in backstage evidence; the caption must
give a useful, plain-Vietnamese buyer takeaway without laundering counts into
prices or missing data into zero.
"""

from __future__ import annotations

import pytest

import scripts.radar_social_queue as q
import scripts.rb_social_editorial as editorial


REDUCTION_ARTICLE = {
    "path": "/tin-tuc/ty-le-cat-mau-nha-dat-thu-dau-mot-phuong-nao-can-kiem-tra",
    "title": "Tỷ lệ cắt máu nhà đất Thủ Dầu Một: phường nào cần kiểm tra kỹ?",
    "description": "Tỷ lệ tin giảm giá tại 13 phường Thủ Dầu Một.",
    "scope_label": "Thủ Dầu Một · 13 phường · dữ liệu Facebook",
    "map_label": "Tỷ lệ tin giảm giá theo phường",
    "article": {
        "summary_cards": [
            {"label": "Tin Facebook theo dõi", "value": "1.062", "note": "13 phường, cửa sổ 14 ngày"},
            {"label": "Có cờ giảm giá", "value": "40 tin · 3,8%", "note": "Tính trên tổng tin trong snapshot"},
            {"label": "Đất nền", "value": "14/432 · 3,2%", "note": "Chỉ tính property_type = dat_nen"},
            {"label": "Nhà đất", "value": "26/610 · 4,3%", "note": "Chỉ tính property_type = nha_dat"},
        ]
    },
}

PRICE_ARTICLE = {
    "path": "/tin-tuc/mua-dat-ben-cat-my-phuoc-hoa-loi-hay-thoi-hoa",
    "title": "Mỹ Phước, Hòa Lợi hay Thới Hòa: khu nào hợp ngân sách khi mua đất Bến Cát?",
    "scope_label": "Bến Cát · Mỹ Phước / Hòa Lợi / Thới Hòa",
    "article": {
        "summary_cards": [
            {"label": "Tổng mẫu", "value": "780 tin", "note": "Từ 2026-08-24 đến 2026-09-07"},
            {"label": "Đất nền", "value": "7,0–11,7 tr/m²", "note": "214 tin có giá/m²"},
            {"label": "Nhà đất", "value": "18,3–20,6 tr/m²", "note": "162 tin có giá/m²"},
            {"label": "Dấu hiệu", "value": "41 tin", "note": "Tin nên mở ra kiểm tra kỹ hơn"},
        ]
    },
}

NO_SIGNAL_ARTICLE = {
    "path": "/tin-tuc/vi-du-thieu-card-dau-hieu",
    "title": "Ví dụ bài không có card dấu hiệu",
    "scope_label": "Thủ Dầu Một",
    "article": {
        "summary_cards": [
            {"label": "Tổng mẫu", "value": "404 tin", "note": "14 ngày"},
            {"label": "Đất nền", "value": "18,3 tr/m²", "note": "214 tin có giá/m²"},
        ]
    },
}

COUNT_ONLY_ARTICLE = {
    "path": "/tin-tuc/vi-du-chi-co-so-tin",
    "title": "Ví dụ bài chỉ có số tin và tỷ lệ",
    "article": {
        "summary_cards": [
            {"label": "Đất nền", "value": "14/432 · 3,2%", "note": "Số tin có cờ giảm giá"},
            {"label": "Nhà đất", "value": "26/610 · 4,3%", "note": "Số tin có cờ giảm giá"},
        ]
    },
}


def _msg(page, slug="", style="data_post"):
    return q._build_message(page, "https://radarbds.vn/x", style, slug)


@pytest.mark.parametrize("style", ["data_post", "market_pulse"])
def test_count_value_stays_out_of_reader_caption(style):
    """'14/432 · 3,2%' is backstage evidence, not Page-caption copy."""
    out = _msg(REDUCTION_ARTICLE, REDUCTION_ARTICLE["path"], style)
    assert "14/432" not in out
    assert "26/610" not in out
    assert "3,2%" not in out
    assert "4,3%" not in out
    assert "trung vị" not in out


@pytest.mark.parametrize("style", ["data_post", "market_pulse"])
def test_no_price_or_raw_ratio_phrase_when_no_price_card(style):
    """A count-only article should become a buyer lesson, not a raw table row."""
    out = _msg(COUNT_ONLY_ARTICLE, COUNT_ONLY_ARTICLE["path"], style)
    assert "trung vị" not in out
    assert "giá rao trung vị" not in out
    assert "14/432" not in out
    assert "26/610" not in out
    assert "Số liệu đang ghi nhận" not in out


def test_price_card_keeps_value_in_evidence_not_caption():
    out = _msg(PRICE_ARTICLE, PRICE_ARTICLE["path"], "data_post")
    assert "7,0–11,7 tr/m²" not in out
    assert "18,3–20,6 tr/m²" not in out
    draft = editorial.build_editorial(
        PRICE_ARTICLE,
        "https://radarbds.vn/tin-tuc/x",
        "mua-dat-ben-cat-my-phuoc-hoa-loi-hay-thoi-hoa",
        make_visual=False,
        source_http_status=200,
    )
    evidence_text = "\n".join(str(item) for item in draft["metadata"]["evidence"])
    assert "7,0–11,7 tr/m²" in evidence_text
    assert "18,3–20,6 tr/m²" in evidence_text


def test_missing_signal_is_omitted_not_zero():
    out = _msg(NO_SIGNAL_ARTICLE, NO_SIGNAL_ARTICLE["path"], "data_post")
    assert "0 tin có dấu hiệu" not in out
    assert "chưa có tin nổi bật" not in out
    assert "chưa có" not in out.casefold()


def test_real_signal_card_kept_as_evidence_not_forced_caption_line():
    out = _msg(PRICE_ARTICLE, PRICE_ARTICLE["path"], "data_post")
    assert "41 tin" not in out
    draft = editorial.build_editorial(
        PRICE_ARTICLE,
        "https://radarbds.vn/tin-tuc/x",
        "mua-dat-ben-cat-my-phuoc-hoa-loi-hay-thoi-hoa",
        make_visual=False,
        source_http_status=200,
    )
    assert any("41 tin" in str(item) for item in draft["metadata"]["evidence"])


def test_scope_label_is_not_used_as_ward_or_hashtag():
    out = _msg(REDUCTION_ARTICLE, REDUCTION_ARTICLE["path"], "market_pulse")
    assert "ThuDauMot13PhuongDuLieuFacebook" not in out
    assert "13 phường · dữ liệu Facebook" not in out
    assert "#ThuDauMot13" not in out


def test_ward_filter_link_has_no_fake_ward():
    ward = q._extract_ward(REDUCTION_ARTICLE, q._article_cards(REDUCTION_ARTICLE))
    assert ward == "khu vực này"


def test_self_comment_url_is_not_scope_sentence():
    url = q._ward_filter_url(REDUCTION_ARTICLE, "Thủ Dầu Một", "slug-x")
    assert "13%20ph%C6%B0%E1%BB%9Dng" not in url
    assert "%C2%B7" not in url  # the '·' separator must not leak into a query value


def test_editorial_caption_has_no_forbidden_legacy_terms():
    draft = editorial.build_editorial(
        REDUCTION_ARTICLE,
        "https://radarbds.vn/tin-tuc/x",
        "ty-le-cat-mau-nha-dat-thu-dau-mot-phuong-nao-can-kiem-tra",
        make_visual=False,
        source_http_status=200,
    )
    assert draft["status"] == "ready"
    assert draft["pillar"] == "radar_insight"
    assert editorial.caption_quality_issues(draft["caption"]) == []
    assert any("14/432" in str(item) for item in draft["metadata"]["evidence"])
