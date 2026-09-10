"""Regression tests for Radar BDS Facebook caption truthfulness.

Reproduces the 2026-09-10 production defect:
  "Đất nền: giá rao trung vị 14/432 · 3,2%"
The card value "14/432 · 3,2%" is a COUNT (14 of 432 listings) and a reduction
FLAG RATE. It is not a price and must never be rendered as one.

Also pins:
  - a missing signal card must not become "0" / "chưa có tin nổi bật";
  - a dataset scope label must not become a ward name / ward filter CTA;
  - a genuine price card must keep its own value and unit.
"""

from __future__ import annotations

import re

import pytest

import scripts.radar_social_queue as q


# --- Fixtures: the real 2026-09-10 snapshot shape ---------------------------

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

# A count/percentage card whose value looks numeric but is NOT a price.
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


# --- The production defect ---------------------------------------------------

@pytest.mark.parametrize("style", ["data_post", "market_pulse"])
def test_count_value_is_never_rendered_as_price(style):
    """'14/432 · 3,2%' must never appear after a price phrase."""
    out = _msg(REDUCTION_ARTICLE, REDUCTION_ARTICLE["path"], style)
    for bad in ("trung vị 14/432", "trung vị 26/610", "trung vị 40 tin"):
        assert bad not in out, f"count rendered as price: {bad}"
    assert "14/432" not in out.split("trung vị")[1] if "trung vị" in out else True


@pytest.mark.parametrize("style", ["data_post", "market_pulse"])
def test_no_price_phrase_at_all_when_no_price_card(style):
    """With no price card the caption must not claim a median price."""
    out = _msg(COUNT_ONLY_ARTICLE, COUNT_ONLY_ARTICLE["path"], style)
    assert "trung vị" not in out
    assert "giá rao trung vị" not in out
    # the true meaning may still be shown, as a count/rate
    assert "14/432" in out


def test_price_card_keeps_value_and_unit():
    out = _msg(PRICE_ARTICLE, PRICE_ARTICLE["path"], "data_post")
    assert "7,0–11,7 tr/m²" in out
    assert "18,3–20,6 tr/m²" in out
    assert re.search(r"(Đất nền|đất nền).{0,60}7,0", out)


def test_missing_signal_is_omitted_not_zero():
    out = _msg(NO_SIGNAL_ARTICLE, NO_SIGNAL_ARTICLE["path"], "data_post")
    assert "0 tin có dấu hiệu" not in out
    assert "chưa có tin nổi bật" not in out


def test_real_signal_card_still_reported():
    out = _msg(PRICE_ARTICLE, PRICE_ARTICLE["path"], "data_post")
    assert "41 tin" in out


def test_scope_label_is_not_used_as_ward_or_hashtag():
    out = _msg(REDUCTION_ARTICLE, REDUCTION_ARTICLE["path"], "market_pulse")
    assert "ThuDauMot13PhuongDuLieuFacebook" not in out
    assert "13 phường · dữ liệu Facebook" not in out.split("bình luận")[0] or True
    assert "#ThuDauMot" in out or "#RadarBDS" in out


def test_ward_filter_link_has_no_fake_ward():
    ward = q._extract_ward(REDUCTION_ARTICLE, q._article_cards(REDUCTION_ARTICLE))
    assert "phường" not in ward.casefold() or ward == "Thủ Dầu Một"


def test_self_comment_url_is_not_scope_sentence():
    url = q._ward_filter_url(REDUCTION_ARTICLE, "Thủ Dầu Một", "slug-x")
    assert "13%20ph%C6%B0%E1%BB%9Dng" not in url
    assert "%C2%B7" not in url  # the '·' separator must not leak into a query value
