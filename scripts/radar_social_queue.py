#!/usr/bin/env python3
"""Create token-light social post queue items for Radar BDS.

This script intentionally does not use an LLM. It converts an existing
production `/tin-tuc` article config entry into a structured social post JSON.
The browser-use worker can later publish or prepare this queue item.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import textwrap
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = Path("/opt/radar-bds/var/social_queue")
ASSET_DIR = Path("/opt/radar-bds/var/social_assets")
SITE = "https://radarbds.vn"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_articles() -> dict[str, dict[str, Any]]:
    from config.seo_articles import SEO_ARTICLES  # pylint: disable=import-error

    return SEO_ARTICLES


def _article_date(page: dict[str, Any]) -> str:
    article = page.get("article") or {}
    return str(article.get("modified_at") or article.get("published_at") or "")


def _choose_article(slug: str) -> tuple[str, dict[str, Any]]:
    articles = _load_articles()
    candidates = {
        k: v
        for k, v in articles.items()
        if isinstance(v, dict) and str(v.get("path", "")).startswith("/tin-tuc/")
    }
    if not candidates:
        raise SystemExit("No /tin-tuc articles found in config/seo_articles.py")
    if slug == "latest":
        key = sorted(candidates, key=lambda k: (_article_date(candidates[k]), k), reverse=True)[0]
        return key, candidates[key]
    if slug not in candidates:
        raise SystemExit(f"Article slug not found or not /tin-tuc: {slug}")
    return slug, candidates[slug]


def _plain(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _absolute_url(path_or_url: str) -> str:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    if not path_or_url.startswith("/"):
        path_or_url = "/" + path_or_url
    return SITE + path_or_url


def _short_title(page: dict[str, Any]) -> str:
    title = _plain(page.get("hero_title") or page.get("title") or "Bài mới trên Radar BDS")
    title = title.replace(" | Radar BDS", "")
    return title


def _article_cards(page: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    article = page.get("article") or {}
    for key in ("summary_cards", "data_cards", "metrics"):
        value = article.get(key) or page.get(key)
        if isinstance(value, list):
            cards.extend([x for x in value if isinstance(x, dict)])
    return cards


def _find_card(cards: list[dict[str, Any]], *needles: str) -> dict[str, str]:
    for card in cards:
        label = _plain(card.get("label") or card.get("title") or "")
        haystack = label.casefold()
        if all(n.casefold() in haystack for n in needles):
            return {
                "label": label,
                "value": _plain(card.get("value") or card.get("body") or card.get("note") or ""),
                "note": _plain(card.get("note") or ""),
            }
    return {"label": "", "value": "", "note": ""}


def _extract_ward(page: dict[str, Any], cards: list[dict[str, Any]]) -> str:
    for card in cards:
        label = _plain(card.get("label") or card.get("title") or "")
        m = re.search(r"(?:Tin|Đất nền|Nhà đất)\s+(.+?)\s+(?:14 ngày|$)", label)
        if m:
            return m.group(1).strip()
    title = _short_title(page)
    m = re.search(r"Giá đất\s+(.+?)\s+Thủ Dầu Một", title, flags=re.I)
    if m:
        return m.group(1).strip()
    return _plain(page.get("scope_label") or page.get("map_label") or "khu vực này")


def _value(card: dict[str, str], fallback: str = "chưa đủ dữ liệu") -> str:
    return card.get("value") or fallback


def _signal_phrase(signal_card: dict[str, str]) -> str:
    value = _value(signal_card, "0")
    digits = re.search(r"\d+", value)
    if digits and int(digits.group(0)) <= 0:
        return "chưa có tin nổi bật cần kiểm tra gấp"
    return f"{value} tin có dấu hiệu đáng kiểm tra"


def _slug_hashtag(ward: str) -> str:
    text = unicodedata.normalize("NFD", ward)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"Đ", "D", text).replace("đ", "d")
    text = re.sub(r"[^A-Za-z0-9]+", "", text.title())
    return text or "ThuDauMot"



def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    return ImageFont.truetype(bold_path if bold else regular, size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    cur = ""
    for word in words:
        test = (cur + " " + word).strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _visual_kind(slug: str, page: dict[str, Any]) -> str:
    """Classify article into a compact visual style for Facebook scanability."""
    text = " ".join([slug, _short_title(page), _plain(page.get("description"))]).casefold()
    if any(key in text for key in ("bất thường", "checklist", "kiểm tra gì", "tin re bat thuong")):
        return "risk_checklist"
    if any(key in text for key in (" hay ", " vs ", "so sánh", "so sanh", "lọc giá theo phường")):
        return "ward_compare"
    if any(key in text for key in ("dưới", "duoi", "ngân sách", "ngan sach", "2-4 tỷ", "3 tỷ", "4 tỷ")):
        return "budget_filter"
    if "giá đất" in text and any(key in text for key in ("phường", "thủ dầu một", "đọc riêng", "hien bao nhieu", "hiện bao nhiêu")):
        return "ward_price"
    cards = _article_cards(page)
    if _find_card(cards, "dấu hiệu").get("value") or any(key in text for key in ("tín hiệu", "tin đáng", "signal")):
        return "signal_filter"
    if any(key in text for key in ("báo cáo", "tháng", "market")):
        return "market_report"
    return "ward_price"


VISUAL_STYLES: dict[str, dict[str, Any]] = {
    "ward_compare": {
        "label": "SO GIÁ 2 KHU",
        "accent": (34, 211, 238),
        "accent2": (45, 212, 191),
        "bg1": (6, 32, 52),
        "bg2": (13, 71, 95),
        "icon": "↔",
        "note": "Đừng gộp đất nền với nhà đất khi so giá.",
    },
    "budget_filter": {
        "label": "LỌC THEO NGÂN SÁCH",
        "accent": (167, 139, 250),
        "accent2": (244, 114, 182),
        "bg1": (33, 24, 72),
        "bg2": (88, 28, 135),
        "icon": "₫",
        "note": "Xem giá/m² trước, rồi mới gọi hỏi vị trí và giấy tờ.",
    },
    "risk_checklist": {
        "label": "TIN RẺ CẦN CHECK",
        "accent": (251, 191, 36),
        "accent2": (248, 113, 113),
        "bg1": (54, 32, 12),
        "bg2": (127, 29, 29),
        "icon": "!",
        "note": "Giá thấp chỉ là tín hiệu lọc ban đầu, chưa phải kết luận nên mua.",
    },
    "signal_filter": {
        "label": "DẤU HIỆU ĐÁNG XEM",
        "accent": (52, 211, 153),
        "accent2": (96, 165, 250),
        "bg1": (6, 44, 41),
        "bg2": (14, 116, 144),
        "icon": "✓",
        "note": "Mở nhóm đáng kiểm tra trước để tiết kiệm thời gian lọc tin.",
    },
    "market_report": {
        "label": "BÁO CÁO THỊ TRƯỜNG",
        "accent": (96, 165, 250),
        "accent2": (129, 140, 248),
        "bg1": (15, 23, 42),
        "bg2": (30, 64, 175),
        "icon": "▦",
        "note": "Số liệu là giá rao tham khảo, nên đối chiếu theo loại hình.",
    },
    "ward_price": {
        "label": "GIÁ RAO THEO PHƯỜNG",
        "accent": (56, 189, 248),
        "accent2": (45, 212, 191),
        "bg1": (7, 30, 50),
        "bg2": (14, 82, 111),
        "icon": "⌂",
        "note": "Dùng dữ liệu để lọc nhanh trước khi đi xem thực tế.",
    },
}


def _visual_design_prompt(kind: str, page: dict[str, Any]) -> str:
    preset = VISUAL_STYLES.get(kind, VISUAL_STYLES["ward_price"])
    headline = _visual_headline(kind, page)
    if kind == "ward_price":
        ward = _extract_ward(page, _article_cards(page))
        return (
            f"Facebook square 1080x1080 for Radar BDS, style=classic ward price card; "
            f"teal background with large red/green/orange circles; left headline: ĐANG SO GIÁ {ward.upper()}? Đừng dùng một con số chung; "
            "right white rounded data card with Đất nền and Nhà đất price boxes plus total tracked listings; "
            "bottom white explanation box: So đúng hơn, tách đất nền và nhà đất, giá rao chỉ để lọc ban đầu."
        )
    return (
        f"Facebook square 1080x1080 for Radar BDS, style={kind}/{preset['label']}; "
        f"dark premium real-estate data card, big Vietnamese headline: {headline}; "
        "maximum 2 key metrics, no long paragraph, high contrast, clean brand badge, "
        "bottom note: giá rao tham khảo / cần kiểm tra thực tế; modern SaaS dashboard feel."
    )


def _lerp(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _draw_gradient(draw: ImageDraw.ImageDraw, width: int, height: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> None:
    for y in range(height):
        draw.line((0, y, width, y), fill=_lerp(top, bottom, y / height))


def _visual_headline(kind: str, page: dict[str, Any]) -> str:
    title = _short_title(page)
    if kind == "ward_compare":
        return title.split(":", 1)[0].replace("nên lọc", "lọc").strip()
    if kind == "budget_filter":
        match = re.search(r"(dưới\s+[^:]+?)(?:[:?]|$)", title, flags=re.I)
        if match:
            return match.group(1).strip().capitalize() + "?"
    if kind == "risk_checklist":
        return "Tin rẻ bất thường: kiểm tra gì?"
    return title.replace(" | Radar BDS", "")


def _visual_metrics(kind: str, page: dict[str, Any]) -> list[tuple[str, str]]:
    cards = _article_cards(page)
    listing = _find_card(cards, "tin")
    land = _find_card(cards, "đất nền")
    house = _find_card(cards, "nhà đất")
    signal = _find_card(cards, "dấu hiệu")
    metrics: list[tuple[str, str]] = []
    if kind in {"ward_compare", "ward_price", "market_report"}:
        if land.get("value"):
            metrics.append(("Đất nền", land["value"]))
        if house.get("value"):
            metrics.append(("Nhà đất", house["value"]))
        if listing.get("value") and len(metrics) < 2:
            metrics.append(("Tin theo dõi", listing["value"]))
    elif kind == "budget_filter":
        if listing.get("value"):
            metrics.append(("Tin phù hợp", listing["value"]))
        if land.get("value"):
            metrics.append(("Giá/m²", land["value"]))
        elif house.get("value"):
            metrics.append(("Giá/m²", house["value"]))
    elif kind == "risk_checklist":
        if signal.get("value"):
            metrics.append(("Cần kiểm tra", signal["value"]))
        if listing.get("value"):
            metrics.append(("Tin theo dõi", listing["value"]))
    elif kind == "signal_filter":
        if signal.get("value"):
            metrics.append(("Dấu hiệu", signal["value"]))
        if listing.get("value"):
            metrics.append(("Tin theo dõi", listing["value"]))
    if not metrics:
        metrics.append(("Radar BDS", "lọc tin bằng dữ liệu"))
    return metrics[:2]


def _draw_metric_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    accent: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, 28, fill=(248, 250, 252))
    draw.rounded_rectangle((x1 + 24, y1 + 24, x1 + 34, y2 - 24), 5, fill=accent)
    draw.text((x1 + 54, y1 + 28), label.upper(), font=_font(25, bold=True), fill=(71, 85, 105))
    value_font = _font(46, bold=True)
    value_lines = _wrap(draw, value, value_font, x2 - x1 - 84)
    yy = y1 + 72
    for line in value_lines[:2]:
        draw.text((x1 + 54, yy), line, font=value_font, fill=(15, 23, 42))
        yy += 54


def _count_from_note(note: str) -> str:
    match = re.search(r"(\d+)\s+tin", _plain(note), flags=re.I)
    return match.group(1) if match else ""


def _draw_classic_price_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    count: str,
    *,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int],
    text_color: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, 24, fill=fill, outline=outline, width=3)
    draw.text((x1 + 30, y1 + 24), label.upper(), font=_font(30, bold=True), fill=text_color)
    draw.text((x1 + 30, y1 + 74), value, font=_font(54, bold=True), fill=text_color)
    if count:
        cb = draw.textbbox((0, 0), f"{count} tin", font=_font(23))
        draw.text((x2 - (cb[2] - cb[0]) - 30, y2 - 40), f"{count} tin", font=_font(23), fill=(91, 103, 117))


def _make_classic_ward_price_visual(slug: str, page: dict[str, Any], now: dt.datetime) -> str:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    out = ASSET_DIR / f"{now.date().isoformat()}-{slug}.png"
    if out.exists():
        return str(out)

    cards = _article_cards(page)
    ward = _extract_ward(page, cards)
    listing = _find_card(cards, "tin")
    land = _find_card(cards, "đất nền")
    house = _find_card(cards, "nhà đất")
    total = listing.get("value") or ""
    land_count = _count_from_note(land.get("note", ""))
    house_count = _count_from_note(house.get("note", ""))

    width = height = 1080
    bg = (28, 84, 93)
    im = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(im)

    # Large flat color circles like the earlier approved ward-price style.
    draw.ellipse((760, -210, 1250, 320), fill=(225, 45, 50))
    draw.ellipse((-150, 640, 360, 1240), fill=(34, 143, 126))
    draw.ellipse((760, 720, 1240, 1240), fill=(249, 127, 24))

    # Brand pill.
    draw.rounded_rectangle((74, 70, 336, 136), 28, fill=(255, 255, 255))
    draw.text((108, 91), "Radar BDS", font=_font(29, bold=True), fill=(21, 60, 68))

    # Left headline block.
    draw.text((74, 204), "ĐANG SO GIÁ", font=_font(32, bold=True), fill=(172, 242, 221))
    ward_line = (ward or "PHƯỜNG").upper()
    title_font = _font(58, bold=True)
    for idx, line in enumerate(_wrap(draw, f"{ward_line}?", title_font, 430)[:2]):
        draw.text((74, 256 + idx * 68), line, font=title_font, fill=(255, 255, 255))
    draw.text((74, 382), "Đừng dùng một", font=_font(44, bold=True), fill=(255, 255, 255))
    draw.text((74, 446), "con số chung.", font=_font(44, bold=True), fill=(255, 255, 255))

    # Right data card.
    card = (530, 122, 976, 740)
    draw.rounded_rectangle((card[0] + 14, card[1] + 18, card[2] + 14, card[3] + 18), 44, fill=(16, 49, 58))
    draw.rounded_rectangle(card, 44, fill=(248, 250, 252), outline=(226, 232, 240), width=2)
    draw.text((570, 166), f"{ward} / 14 ngày", font=_font(31, bold=True), fill=(13, 20, 34))

    _draw_classic_price_box(
        draw,
        (570, 222, 936, 372),
        "Đất nền",
        land.get("value") or "chưa đủ dữ liệu",
        land_count,
        fill=(235, 253, 248),
        outline=(174, 235, 224),
        text_color=(14, 126, 112),
    )
    _draw_classic_price_box(
        draw,
        (570, 414, 936, 564),
        "Nhà đất",
        house.get("value") or "chưa đủ dữ liệu",
        house_count,
        fill=(255, 248, 238),
        outline=(239, 218, 184),
        text_color=(184, 67, 24),
    )

    draw.rounded_rectangle((570, 606, 936, 692), 22, fill=(11, 18, 34))
    total_text = f"{total} tin đang theo dõi" if total else "Tin đang theo dõi"
    draw.text((592, 625), total_text, font=_font(25, bold=True), fill=(255, 255, 255))
    draw.text((592, 661), "Nguồn: Facebook / Radar", font=_font(22), fill=(202, 213, 225))

    # Bottom explanation card.
    bottom = (74, 798, 1010, 976)
    draw.rounded_rectangle(bottom, 30, fill=(255, 255, 255))
    draw.text((110, 832), "So đúng hơn:", font=_font(34, bold=True), fill=(15, 23, 42))
    draw.text((110, 884), "tách đất nền và nhà đất, rồi mới nhìn giá trung vị.", font=_font(27, bold=True), fill=(31, 41, 55))
    draw.text((110, 928), "Giá rao chỉ để lọc ban đầu — vẫn cần kiểm tra thực tế.", font=_font(25, bold=True), fill=(15, 128, 112))

    im.save(out, quality=94, optimize=True)
    return str(out)


def _make_visual(slug: str, page: dict[str, Any], now: dt.datetime) -> str:
    """Create a compact 1080x1080 visual with per-post-type styles.

    The Facebook publisher only attaches media when the queue contains
    content.visual_path/image. Keep generation deterministic and local so the
    daily auto-post path never silently falls back to text-only.
    """
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    out = ASSET_DIR / f"{now.date().isoformat()}-{slug}.png"
    if out.exists():
        return str(out)

    kind = _visual_kind(slug, page)
    if kind == "ward_price":
        return _make_classic_ward_price_visual(slug, page, now)
    preset = VISUAL_STYLES[kind]
    headline = _visual_headline(kind, page)
    ward = _extract_ward(page, _article_cards(page))
    metrics = _visual_metrics(kind, page)

    width = height = 1080
    im = Image.new("RGB", (width, height), preset["bg1"])
    draw = ImageDraw.Draw(im)
    _draw_gradient(draw, width, height, preset["bg1"], preset["bg2"])

    accent = preset["accent"]
    accent2 = preset["accent2"]
    draw.ellipse((710, -160, 1160, 300), fill=_lerp(preset["bg2"], accent, 0.22))
    draw.ellipse((-180, 760, 280, 1220), fill=_lerp(preset["bg1"], accent2, 0.20))
    draw.rounded_rectangle((66, 60, 330, 124), 24, fill=(255, 255, 255), outline=accent, width=0)
    draw.ellipse((91, 80, 123, 112), fill=accent2)
    draw.text((140, 78), "RADAR BĐS", font=_font(29, bold=True), fill=(15, 23, 42))

    label = str(preset["label"])
    label_w = draw.textbbox((0, 0), label, font=_font(26, bold=True))[2]
    draw.rounded_rectangle((70, 168, 112 + label_w, 220), 18, fill=_lerp(preset["bg2"], accent, 0.34), outline=accent, width=2)
    draw.text((92, 181), label, font=_font(26, bold=True), fill=(236, 253, 245))

    draw.ellipse((846, 140, 988, 282), fill=accent)
    icon_font = _font(74, bold=True)
    icon = str(preset["icon"])
    ib = draw.textbbox((0, 0), icon, font=icon_font)
    draw.text((917 - (ib[2] - ib[0]) / 2, 207 - (ib[3] - ib[1]) / 2), icon, font=icon_font, fill=(15, 23, 42))

    y = 258
    title_font = _font(68, bold=True)
    for line in _wrap(draw, headline, title_font, 820)[:3]:
        draw.text((72, y), line, font=title_font, fill="white")
        y += 82

    subline = f"{ward} · giá rao tham khảo" if ward and ward != "khu vực này" else "Dữ liệu giá rao Radar BDS"
    draw.text((76, min(y + 8, 520)), subline, font=_font(28, bold=True), fill=(213, 234, 245))

    card_top = 570
    if len(metrics) == 1:
        _draw_metric_card(draw, (70, card_top, 1010, card_top + 168), metrics[0][0], metrics[0][1], accent)
    else:
        _draw_metric_card(draw, (70, card_top, 525, card_top + 190), metrics[0][0], metrics[0][1], accent)
        _draw_metric_card(draw, (555, card_top, 1010, card_top + 190), metrics[1][0], metrics[1][1], accent2)

    note = str(preset["note"])
    note_top = 815
    draw.rounded_rectangle((70, note_top, 1010, note_top + 82), 24, fill=(255, 255, 255))
    yy = note_top + 22
    for line in _wrap(draw, note, _font(27, bold=True), 850)[:2]:
        draw.text((104, yy), line, font=_font(27, bold=True), fill=(30, 41, 59))
        yy += 34

    draw.rounded_rectangle((70, 958, 1010, 1014), 18, fill=_lerp(preset["bg1"], accent, 0.24), outline=accent, width=2)
    draw.text((104, 973), "radarbds.vn • Lọc tin trước, kiểm tra thực tế sau", font=_font(24, bold=True), fill=(226, 245, 255))
    im.save(out, quality=94, optimize=True)
    return str(out)

def _hashtags_for_page(page: dict[str, Any]) -> list[str]:
    ward = _extract_ward(page, _article_cards(page))
    ward_tag = _slug_hashtag(ward)
    if ward_tag and ward_tag != "ThuDauMot":
        return ["RadarBDS", "BinhDuong", ward_tag]
    return ["RadarBDS", "BinhDuong", "ThuDauMot"]


def _utm_url(url: str, slug: str, *, campaign: str = "page_article") -> str:
    parsed = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({
        "utm_source": "facebook",
        "utm_medium": "organic_social",
        "utm_campaign": campaign,
        "utm_content": slug,
    })
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))


def _ward_filter_url(page: dict[str, Any], ward: str, slug: str) -> str:
    """Return a radarbds.vn URL that lands readers on a ward-filtered view.

    Prefer the article's configured dashboard CTA because daily articles often
    carry a hand-tuned filter path. Fall back to the public signals tab with the
    ward query parameter.
    """
    href = _plain(page.get("primary_href") or "")
    if not href:
        href = "/?tab=signals&ward=" + urllib.parse.quote(ward)
    return _utm_url(_absolute_url(href), f"{slug}-ward-filter", campaign="ward_filter")


def _ward_filter_cta(ward: str, filter_url: str, article_url: str) -> str:
    return (
        f"Vào radarbds.vn → lọc phường {ward} để xem từng tin đang rao:\n"
        f"{filter_url}\n\n"
        f"Bài phân tích dữ liệu:\n{article_url}"
    )


def _variant_for_slug(slug: str, signal_card: dict[str, str]) -> str:
    signal_value = signal_card.get("value") or "0"
    has_signal = bool(re.search(r"[1-9]", signal_value))
    bucket = int(hashlib.sha1(slug.encode("utf-8")).hexdigest(), 16) % 3
    if has_signal and bucket == 0:
        return "signal_first"
    if bucket == 1:
        return "problem_first"
    return "data_first"


def _build_message(page: dict[str, Any], url: str, style: str = "data_post", slug: str = "") -> str:
    cards = _article_cards(page)
    ward = _extract_ward(page, cards)
    listing = _find_card(cards, "tin")
    land = _find_card(cards, "đất nền")
    house = _find_card(cards, "nhà đất")
    signal = _find_card(cards, "dấu hiệu")
    window = "14 ngày"
    listing_count = _value(listing, "nhiều")
    land_price = _value(land)
    house_price = _value(house)
    signal_text = _signal_phrase(signal)
    tracked_line = f"Giá rao {ward} {window} qua có {listing_count} tin Radar đang theo dõi."
    slug_key = slug or _plain(page.get("path") or "daily_article")
    final_url = _utm_url(url, slug_key)
    filter_url = _ward_filter_url(page, ward, slug_key)
    ward_cta = _ward_filter_cta(ward, filter_url, final_url)
    # Keep f-string body indentation consistent so textwrap.dedent can remove it.
    ward_cta_block = ward_cta.replace("\n", "\n        ")
    ward_hashtag = _slug_hashtag(ward)
    hashtags = f"#RadarBDS #BinhDuong #{ward_hashtag if ward_hashtag != 'ThuDauMot' else 'ThuDauMot'}"
    variant = _variant_for_slug(slug or _short_title(page), signal)
    if style == "market_pulse":
        variant = "data_first"

    if variant == "signal_first":
        body = f"""
        {signal_text.capitalize()} tại {ward} trên Radar BDS.

        Bối cảnh: {listing_count} tin trong {window}; đất nền giá rao trung vị {land_price}, nhà đất giá rao trung vị {house_price}.

        {ward_cta_block}

        {hashtags}
        """
    elif variant == "problem_first":
        body = f"""
        Đang so giá {ward}? Một con số chung dễ làm bạn so sai.

        {window.capitalize()} gần nhất: {listing_count} tin rao.
        Đất nền: giá rao trung vị {land_price}.
        Nhà đất: giá rao trung vị {house_price}.

        Radar BDS tách dữ liệu theo loại hình để bạn kiểm tra từng tin trước khi gọi môi giới.

        {ward_cta_block}

        {hashtags}
        """
    else:
        body = f"""
        {tracked_line}

        • Đất nền: giá rao trung vị {land_price}
        • Nhà đất: giá rao trung vị {house_price}
        • {signal_text}

        Đừng gộp 2 loại hình khi so giá.

        {ward_cta_block}

        {hashtags}
        """
    return _scrub_marketing_copy(textwrap.dedent(body).strip())


def _scrub_marketing_copy(text: str) -> str:
    forbidden = [
        "deal ngon",
        "lời chắc",
        "cam kết lợi nhuận",
        "sinh lời",
        "cơ hội vàng",
        "rẻ nhất",
        "dưới giá thị trường",
        "hot nhất",
        "sốt đất",
    ]
    lowered = text.casefold()
    hits = [word for word in forbidden if word.casefold() in lowered]
    if hits:
        raise ValueError(f"Forbidden marketing claim(s) in social copy: {', '.join(hits)}")
    return text


def _check_url(url: str, timeout: int = 12) -> int | None:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "RadarBDS-SocialQueue/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - first-party URL verification
            return int(resp.status)
    except Exception:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
                return int(resp.status)
        except Exception:
            return None


def create(args: argparse.Namespace) -> dict[str, Any]:
    slug, page = _choose_article(args.slug)
    url = _absolute_url(str(page.get("path", "")))
    status = _check_url(url) if not args.skip_verify else None
    if status is not None and status >= 400:
        raise SystemExit(f"Source URL is not healthy: {url} => {status}")
    now = dt.datetime.now(dt.timezone.utc).astimezone()
    item = {
        "schema": "radar_social_queue.v1",
        "created_at": now.isoformat(timespec="seconds"),
        "source": {
            "slug": slug,
            "url": url,
            "title": _short_title(page),
            "path": page.get("path"),
            "article_date": _article_date(page),
            "http_status": status,
        },
        "target": {
            "platform": args.platform,
            "surface": args.surface,
            "page_url": args.page_url,
            "mode": args.mode,
            "requires_review": args.mode != "publish",
        },
        "content": {
            "style": args.style,
            "message": _build_message(page, url, args.style, slug),
            "link": _utm_url(url, slug),
            "ward_filter_link": _ward_filter_url(page, _extract_ward(page, _article_cards(page)), slug),
            "hashtags": _hashtags_for_page(page),
            "visual_style": _visual_kind(slug, page),
            "visual_prompt": _visual_design_prompt(_visual_kind(slug, page), page),
            "visual_path": _make_visual(slug, page, now),
        },
        "status": "queued",
        "guards": {
            "no_password_storage": True,
            "stop_on_checkpoint": True,
            "no_group_spam": True,
            "verify_before_publish": True,
        },
    }
    return item


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Radar BDS social queue items from /tin-tuc article configs.")
    parser.add_argument("--slug", default="latest", help="Article slug, or 'latest' (default).")
    parser.add_argument("--platform", default="facebook", choices=["facebook", "zalo", "telegram"])
    parser.add_argument("--surface", default="page", choices=["page", "group", "draft"])
    parser.add_argument("--page-url", default="https://www.facebook.com/radarbdsvn/")
    parser.add_argument("--mode", default="review", choices=["review", "draft", "publish"])
    parser.add_argument("--style", default="data_post", choices=["data_post", "market_pulse"])
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--dry-run", action="store_true", help="Print JSON to stdout; do not write queue file.")
    parser.add_argument("--skip-verify", action="store_true", help="Skip HTTP status check for source article URL.")
    args = parser.parse_args()

    item = create(args)
    if args.dry_run:
        print(json.dumps(item, ensure_ascii=False, indent=2))
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", item["source"]["slug"]).strip("-")
    date = dt.datetime.now().strftime("%Y-%m-%d")
    out = out_dir / f"{date}-{safe_slug}-{args.surface}-{args.mode}.json"
    out.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(out))
    print(item["content"]["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
