#!/usr/bin/env python3
"""Reader-first Facebook editorial engine for Radar BDS.

This module turns a Radar article config page into a six-pillar Page editorial
item. It deliberately keeps raw metrics in evidence metadata and writes the
caption as useful Vietnamese buyer guidance that stands on its own.
"""

from __future__ import annotations

import datetime as dt
import re
import textwrap
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

SITE = "https://radarbds.vn"
DEFAULT_ASSET_DIR = Path("/opt/radar-bds/var/social_assets")
EDITORIAL_VERSION = "1.0"
SCHEMA = "rb_social_editorial.v1"

PILLARS: dict[str, dict[str, Any]] = {
    "news_explainer": {
        "label": "Tin mới, hiểu đúng",
        "layout": "source_timeline",
        "palette": ("#172554", "#2563eb", "#f8fafc"),
        "headline": "Đọc tin cho đúng",
    },
    "radar_insight": {
        "label": "Giá rao nói gì?",
        "layout": "local_question",
        "palette": ("#064e3b", "#14b8a6", "#ecfeff"),
        "headline": "Đừng so vội",
    },
    "map_guide": {
        "label": "Bản đồ cho người mua",
        "layout": "map_steps",
        "palette": ("#3b2605", "#f59e0b", "#fffbeb"),
        "headline": "Gần đường chưa đủ",
    },
    "buyer_checklist": {
        "label": "Mua nhà đất, hỏi cho đúng",
        "layout": "call_checklist",
        "palette": ("#581c87", "#a855f7", "#faf5ff"),
        "headline": "Hỏi trước khi xem",
    },
    "listing_breakdown": {
        "label": "Mổ xẻ một tin rao",
        "layout": "case_split",
        "palette": ("#7f1d1d", "#ef4444", "#fff1f2"),
        "headline": "Mổ xẻ một tin",
    },
    "radar_howto": {
        "label": "Dùng Radar làm được việc",
        "layout": "tool_walkthrough",
        "palette": ("#1e1b4b", "#6366f1", "#eef2ff"),
        "headline": "Hai loại giá, đừng lẫn",
    },
}

# Authored editorial overrides. Keyed by article slug so the visual headline and
# pillar match what the article actually says, instead of a generic pillar default.
CURATED_HEADLINES: dict[str, str] = {
    "bang-gia-dat-va-gia-rao-khac-nhau-the-nao": "Bảng giá đất ≠ giá chủ phải bán",
    "mua-dat-ben-cat-my-phuoc-hoa-loi-hay-thoi-hoa": "Đừng gộp 3 khu vào một giá",
    "phu-hoa-hay-chanh-my-nen-xem-khu-nao-truoc": "Phú Hòa hay Chánh Mỹ?",
    "ty-le-cat-mau-nha-dat-thu-dau-mot-phuong-nao-can-kiem-tra": "Giảm giá chưa chắc rẻ",
}

TDM_WARDS = {
    "Tân An",
    "Hiệp An",
    "Tương Bình Hiệp",
    "Định Hòa",
    "Chánh Mỹ",
    "Phú Mỹ",
    "Phú Cường",
    "Phú Hòa",
    "Phú Lợi",
    "Hiệp Thành",
    "Chánh Nghĩa",
    "Phú Tân",
    "Hòa Phú",
}
BEN_CAT_AREAS = {"Mỹ Phước", "Tân Định", "An Điền", "An Tây", "Thới Hòa", "Hòa Lợi", "Phú An", "Chánh Phú Hòa"}
REAL_AREAS = TDM_WARDS | BEN_CAT_AREAS

RAW_RATIO_RE = re.compile(r"\b\d[\d.,]*\s*/\s*\d[\d.,]*\b")
PRICE_UNIT_RE = re.compile(r"\b\d[\d.,–-]*\s*(?:tr(?:iệu)?\s*/\s*m|tr/m²|tr/m2|tỷ\b)", re.I)
FORBIDDEN_CAPTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("median-jargon", re.compile(r"trung vị", re.I)),
    ("mos-jargon", re.compile(r"\bMOS\b", re.I)),
    ("signal-jargon", re.compile(r"tín hiệu", re.I)),
    ("valid-sample-jargon", re.compile(r"mẫu hợp lệ", re.I)),
    ("pipeline-label", re.compile(r"property_type|Số liệu đang ghi nhận", re.I)),
    ("raw-ratio", RAW_RATIO_RE),
    ("naked-price", PRICE_UNIT_RE),
)


def _plain(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def absolute_url(path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    if not path_or_url.startswith("/"):
        path_or_url = "/" + path_or_url
    return SITE + path_or_url


def utm_url(url: str, slug: str, *, campaign: str = "rb_editorial", medium: str = "pinned_comment") -> str:
    parsed = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update(
        {
            "utm_source": "facebook",
            "utm_medium": medium,
            "utm_campaign": campaign,
            "utm_content": slug,
        }
    )
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))


def article_date(page: dict[str, Any]) -> str:
    editorial = page.get("social_editorial") if isinstance(page.get("social_editorial"), dict) else {}
    article = page.get("article") if isinstance(page.get("article"), dict) else {}
    for value in (
        editorial.get("source_date"),
        editorial.get("date"),
        article.get("modified_at"),
        article.get("published_at"),
        page.get("published_at"),
    ):
        text = _plain(value)
        if text:
            return text[:10]
    return "unknown-date"


def short_title(page: dict[str, Any]) -> str:
    title = _plain(page.get("hero_title") or page.get("title") or "Radar BDS")
    return title.replace(" | Radar BDS", "").strip()


def article_cards(page: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    article = page.get("article") if isinstance(page.get("article"), dict) else {}
    for container in (article, page):
        if not isinstance(container, dict):
            continue
        for key in ("summary_cards", "data_cards", "metrics", "value_cards"):
            value = container.get(key)
            if isinstance(value, list):
                cards.extend([item for item in value if isinstance(item, dict)])
    return cards


def evidence_from_page(page: dict[str, Any]) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    for card in article_cards(page):
        label = _plain(card.get("label") or card.get("title"))
        value = _plain(card.get("value") or card.get("body"))
        note = _plain(card.get("note"))
        if label or value or note:
            evidence.append({"label": label, "value": value, "note": note})
    editorial = page.get("social_editorial") if isinstance(page.get("social_editorial"), dict) else {}
    for item in editorial.get("evidence") or []:
        if isinstance(item, dict):
            evidence.append({str(k): _plain(v) for k, v in item.items()})
        elif item:
            evidence.append({"note": _plain(item)})
    return evidence


def caption_quality_issues(caption: str) -> list[str]:
    text = _plain(caption)
    issues = [name for name, pattern in FORBIDDEN_CAPTION_PATTERNS if pattern.search(text)]
    if re.search(r"\b0\s+tin\s+(?:có|nổi bật|đáng)", text, re.I):
        issues.append("missing-as-zero")
    return issues


def _strip_accents(value: str) -> str:
    text = unicodedata.normalize("NFD", value)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("Đ", "D").replace("đ", "d")


def slug_hashtag(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "", _strip_accents(value).title())
    return text or "RadarBDS"


def is_real_area(name: str) -> bool:
    return _plain(name) in REAL_AREAS


def extract_area(page: dict[str, Any]) -> str:
    haystack = " ".join(
        [
            short_title(page),
            _plain(page.get("scope_label")),
            _plain(page.get("map_label")),
            _plain(page.get("path")),
        ]
    )
    for area in sorted(REAL_AREAS, key=len, reverse=True):
        if area in haystack:
            return area
        if _strip_accents(area).casefold() in _strip_accents(haystack).casefold():
            return area
    return "khu vực này"


def source_metadata(page: dict[str, Any], url: str, http_status: int | None = None) -> dict[str, Any]:
    editorial = page.get("social_editorial") if isinstance(page.get("social_editorial"), dict) else {}
    source_url = _plain(editorial.get("source_url") or editorial.get("url") or url)
    return {
        "url": source_url,
        "date": article_date(page),
        "status": _plain(editorial.get("source_status") or editorial.get("status") or "bài Radar"),
        "scope": _plain(editorial.get("source_scope") or page.get("scope_label") or page.get("map_label") or extract_area(page)),
        "http_status": http_status,
    }


def pillar_for_page(page: dict[str, Any], slug: str = "") -> str:
    editorial = page.get("social_editorial") if isinstance(page.get("social_editorial"), dict) else {}
    explicit = _plain(editorial.get("pillar"))
    if explicit in PILLARS:
        return explicit
    text = " ".join([slug, short_title(page), _plain(page.get("description")), _plain(page.get("path"))]).casefold()

    # Order matters. Most specific reader intent first; the generic price-reading
    # fallback (radar_insight) must stay last or every price article collapses
    # into one pillar and the Page repeats itself.
    if any(key in text for key in ("bảng giá đất", "gia rao khac nhau", "giá rao khác nhau", "gia-rao-khac-gia-giao-dich", "giá rao khác giá giao dịch")):
        return "radar_insight"
    if any(key in text for key in ("mổ xẻ", "mo-xe", "giảm sâu", "lịch sử giá", "tin ghi", "tin rẻ", "tin-re")):
        return "listing_breakdown"
    # "Cắt máu" is market-wide language (a share of tracked listings dropped
    # price), not one listing being dissected. Dissecting a single listing also
    # requires verified rights, which a market aggregate does not have.
    if any(key in text for key in ("cắt máu", "cat-mau")):
        return "radar_insight"
    if any(key in text for key in ("đặt cọc", "đặt tiền", "giấy tờ", "sổ", "kiểm tra gì", "hoi-gi", "hỏi gì", "kiem-tra-gi", "rủi ro")):
        return "buyer_checklist"
    if any(key in text for key in ("vành đai", "quy hoạch", "bản đồ", "ban-do", "gan-vanh", "gần vành", "hạ tầng", "cao tốc")):
        return "map_guide"
    if any(key in text for key in ("cao tốc", "chính sách", "thủ tục", "dự án", "de-xuat", "đề xuất", "báo cáo", "bao-cao")):
        return "radar_insight"
    if any(key in text for key in ("công cụ", "cong-cu", "cách dùng", "cach-dung", "dùng radar", "dinh-gia", "định giá", "lọc tin", "loc-tin")):
        # "X là gì" articles explain a term; they are not tool walkthroughs even
        # when the term is itself a filter name (e.g. MOS).
        if any(key in text for key in (" là gì", "-la-gi", "la-gi-", "nghĩa là", "hiểu đúng")):
            return "radar_insight"
        return "radar_howto"
    if any(key in text for key in ("nên xem khu nào", "nen-xem-khu-nao", "hay ", "khác nhau", "khac-nhau", "so sánh", "so-sanh")):
        return "radar_insight"
    if "hiện bao nhiêu" in text or "hien-bao-nhieu" in text or "giá đất" in text or "gia-dat" in text:
        return "buyer_checklist"
    return "radar_insight"


def _news_blocking_reasons(page: dict[str, Any]) -> list[str]:
    editorial = page.get("social_editorial") if isinstance(page.get("social_editorial"), dict) else {}
    required = {
        "primary-source-url": editorial.get("source_url"),
        "primary-source-date": editorial.get("source_date") or editorial.get("date"),
        "source-status": editorial.get("source_status") or editorial.get("status"),
        "source-scope": editorial.get("source_scope"),
        "source-verified": editorial.get("source_verified"),
    }
    return [f"missing-{name}" for name, value in required.items() if not value]


def _listing_blocking_reasons(page: dict[str, Any]) -> list[str]:
    editorial = page.get("social_editorial") if isinstance(page.get("social_editorial"), dict) else {}
    if editorial.get("hypothetical"):
        return []
    if editorial.get("listing_verified") and editorial.get("privacy_rights_verified"):
        return []
    return ["missing-listing-rights-or-verified-data"]


def _default_topic(page: dict[str, Any], pillar: str) -> str:
    editorial = page.get("social_editorial") if isinstance(page.get("social_editorial"), dict) else {}
    return _plain(editorial.get("topic") or PILLARS[pillar]["label"])


def _caption_for_pillar(page: dict[str, Any], pillar: str) -> str:
    editorial = page.get("social_editorial") if isinstance(page.get("social_editorial"), dict) else {}
    authored = _plain(editorial.get("caption"))
    if authored:
        return authored

    area = extract_area(page)
    area_phrase = area if area != "khu vực này" else "khu đang xem"

    if pillar == "news_explainer":
        return (
            "Tin hạ tầng hoặc chính sách chỉ hữu ích khi biết rõ nó đang ở bước nào. "
            "Người mua nên kiểm nguồn công bố, ngày văn bản và phạm vi áp dụng trước khi dùng tin đó để trả giá."
        )
    if pillar == "map_guide":
        return (
            "Tin ghi “gần đường lớn” chưa nói được lối đi có thuận tiện hay không.\n\n"
            "Trước khi hẹn xem, hãy nhờ người bán gửi vị trí và chỉ đường ra tuyến kết nối. "
            "Bản đồ chỉ giúp hình dung khu vực; riêng từng lô vẫn cần kiểm hồ sơ và thực địa."
        )
    if pillar == "buyer_checklist":
        return (
            "Trước khi hẹn xem nhà đất, hỏi vài câu cơ bản sẽ đỡ mất thời gian.\n\n"
            "Vị trí có gửi được không, đường vào thực tế thế nào, giấy tờ đứng tên ai và diện tích trên mô tả có khớp hồ sơ không? "
            "Có câu trả lời rõ rồi hãy so giá tiếp."
        )
    if pillar == "listing_breakdown":
        if editorial.get("hypothetical"):
            return (
                "Ví dụ giả định: một tin ghi đã giảm giá vẫn chưa đủ để gọi là rẻ.\n\n"
                "Cần đặt cạnh các tin giống hơn về vị trí, diện tích, đường vào và giấy tờ. "
                "Nếu một trong các điểm đó chưa rõ, tạm dừng so giá rồi hỏi lại trước."
            )
        return (
            "Một tin rao chỉ nên được mổ xẻ khi đã kiểm được dữ liệu và quyền sử dụng thông tin. "
            "Thiếu nguồn hoặc chưa ẩn thông tin riêng thì chưa nên biến thành case công khai."
        )
    if pillar == "radar_howto":
        title_low = short_title(page).casefold()
        if "bảng giá đất" in title_low and "giá rao" in title_low:
            return (
                "Tra bảng giá đất thấy thấp hơn giá chủ đang chào, chưa thể kết luận chủ bán đắt.\n\n"
                "Bảng giá do Nhà nước ban hành có mục đích riêng. Giá rao là mức người bán đang chào, không phải giá đã giao dịch. "
                "Nếu muốn thương lượng, hãy tìm thêm các tin gần giống quanh khu đó; nếu làm hồ sơ, phải đọc đúng văn bản áp dụng cho trường hợp của mình."
            )
        return (
            "Muốn hỏi “bớt được bao nhiêu”, nên chuẩn bị vài tin gần đó trước.\n\n"
            "Trên Radar, hãy chọn đúng khu vực, loại nhà đất và diện tích rồi mở các tin được gợi ý để đọc kỹ. "
            "Tin nào khác đường vào hoặc giấy tờ chưa rõ thì đừng dùng làm căn cứ thương lượng."
        )

    title_low = short_title(page).casefold()
    if "mỹ phước 1" in title_low or "mỹ phước 1, 2, 3" in title_low:
        return (
            "Cùng gọi là Mỹ Phước nhưng không nên xem như một khu giống hệt nhau.\n\n"
            "Khi đọc tin, hãy hỏi rõ Mỹ Phước mấy, gần trục đường nào và lối vào thực tế ra sao. "
            "Tên khu giúp khoanh phạm vi ban đầu; giá chào của từng tin vẫn phải so lại theo diện tích, đường và giấy tờ."
        )
    if "bến cát có những khu nào" in title_low:
        return (
            "Tìm đất Bến Cát mà chỉ gõ một chữ “Bến Cát” thì rất dễ gom lẫn nhiều khu khác nhau.\n\n"
            "Mỹ Phước, Hòa Lợi hay Thới Hòa có cách đi lại và nhóm tin rao không giống nhau. "
            "Nên chọn khu trước, rồi mới lọc loại đất và diện tích để tránh so sai ngay từ đầu."
        )
    if "mỹ phước, hòa lợi hay thới hòa" in title_low:
        return (
            "Đang phân vân Mỹ Phước, Hòa Lợi hay Thới Hòa thì đừng bắt đầu bằng một mức giá chung.\n\n"
            "Hãy chọn khu phù hợp đường đi và ngân sách tổng, sau đó mới mở những tin cùng loại nhà đất để so. "
            "Tin rao giúp lọc ban đầu; lô cụ thể vẫn cần hỏi vị trí, đường vào và giấy tờ."
        )
    if "cắt máu" in title_low or "giảm giá" in title_low:
        return (
            "Thấy một tin ghi giảm giá chưa đủ để kết luận là rẻ.\n\n"
            "Người mua nên đặt tin đó cạnh những tin gần giống về loại nhà đất, diện tích và đường vào. "
            "Một dòng “đã giảm” chỉ cho biết giá chào đã đổi so với lần trước, chưa nói lô đó hợp để xuống tiền.\n\n"
            "Việc cần làm là đọc ngày cập nhật, hỏi lại giấy tờ và vị trí rồi mới so tiếp."
        )
    return (
        f"Khi xem nhà đất ở {area_phrase}, đừng dùng một con số chung cho mọi tin.\n\n"
        "Hãy tách loại nhà đất, diện tích và đường vào trước khi so. "
        "Dữ liệu Radar giúp lọc ban đầu; quyết định cuối vẫn cần kiểm vị trí, giấy tờ và tình trạng thực tế."
    )


def _reader_benefit(page: dict[str, Any], pillar: str) -> str:
    editorial = page.get("social_editorial") if isinstance(page.get("social_editorial"), dict) else {}
    explicit = _plain(editorial.get("reader_benefit"))
    if explicit:
        return explicit
    return {
        "news_explainer": "Biết tin đang ở bước nào trước khi dùng làm căn cứ mua bán.",
        "radar_insight": "Biết cách so giá rao mà không nhầm giữa loại nhà đất và từng điều kiện của tin.",
        "map_guide": "Biết cần hỏi lối vào, hồ sơ và phạm vi bản đồ trước khi đi xem.",
        "buyer_checklist": "Có câu hỏi cụ thể để sàng lọc tin trước cuộc gọi hoặc lịch hẹn.",
        "listing_breakdown": "Biết điểm nào cần xác minh trước khi tin vào một case rao bán.",
        "radar_howto": "Biết dùng Radar để chuẩn bị nhóm tin đối chiếu trước khi thương lượng.",
    }[pillar]


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu/" + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")),
        Path("/usr/share/fonts/truetype/liberation2/" + ("LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf")),
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    raise RuntimeError("No supported TrueType font found for editorial visual")


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _visual_notes(pillar: str) -> list[str]:
    return {
        "news_explainer": ["Nguồn", "Ngày", "Trạng thái"],
        "radar_insight": ["Tách loại nhà đất", "Đọc ngày cập nhật", "So tin gần giống"],
        "map_guide": ["Vị trí lô", "Lối vào", "Hồ sơ riêng"],
        "buyer_checklist": ["Giấy tờ", "Đường vào", "Diện tích"],
        "listing_breakdown": ["Mốc giá", "Điểm chưa rõ", "Quyền riêng tư"],
        "radar_howto": ["Chọn khu", "Nhập diện tích", "Mở tin so sánh"],
    }[pillar]


def render_visual(
    page: dict[str, Any],
    slug: str,
    pillar: str,
    *,
    asset_dir: str | Path = DEFAULT_ASSET_DIR,
) -> dict[str, str]:
    cfg = PILLARS[pillar]
    source_date = article_date(page)
    out_dir = Path(asset_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", slug).strip("-") or "editorial"
    out = out_dir / f"{source_date}-{safe_slug}-rbedit-v{EDITORIAL_VERSION}-{pillar}.png"

    width, height = (1080, 1350) if pillar in {"map_guide", "buyer_checklist", "radar_howto"} else (1080, 1080)
    bg, accent, panel = (_hex_to_rgb(value) for value in cfg["palette"])
    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, height), fill=bg)
    draw.ellipse((760, -170, 1240, 310), fill=accent)
    draw.ellipse((-180, height - 310, 280, height + 140), fill=tuple(max(0, c - 35) for c in accent))

    draw.rounded_rectangle((72, 64, 328, 128), 24, fill=(255, 255, 255))
    draw.text((102, 82), "Radar BDS", font=_font(28, bold=True), fill=bg)

    label = str(cfg["label"])
    draw.rounded_rectangle((72, 174, 72 + min(650, 34 + len(label) * 18), 228), 18, fill=panel)
    draw.text((96, 188), label.upper(), font=_font(25, bold=True), fill=bg)

    headline = CURATED_HEADLINES.get(slug) or str(cfg["headline"])
    y = 282
    for line in _wrap(draw, headline, _font(76, bold=True), 790)[:2]:
        draw.text((72, y), line, font=_font(76, bold=True), fill=(255, 255, 255))
        y += 88

    topic = _default_topic(page, pillar)
    for line in _wrap(draw, topic, _font(34, bold=True), 880)[:3]:
        draw.text((76, y + 24), line, font=_font(34, bold=True), fill=(226, 232, 240))
        y += 44

    card_top = 600 if height == 1080 else 690
    draw.rounded_rectangle((72, card_top, 1008, card_top + 300), 34, fill=(255, 255, 255))
    draw.text((112, card_top + 36), "Đọc nhanh", font=_font(38, bold=True), fill=bg)
    yy = card_top + 104
    for note in _visual_notes(pillar):
        draw.ellipse((116, yy + 9, 138, yy + 31), fill=accent)
        draw.text((158, yy), note, font=_font(33, bold=True), fill=(15, 23, 42))
        yy += 58

    footer_y = height - 152
    draw.rounded_rectangle((72, footer_y, 1008, footer_y + 76), 24, fill=panel)
    draw.text((108, footer_y + 19), f"Minh họa biên tập • nguồn/ngày: {source_date}", font=_font(25, bold=True), fill=bg)
    draw.text((108, height - 54), "Không phải bản đồ, ảnh dự án hay hồ sơ pháp lý thật", font=_font(22), fill=(226, 232, 240))

    image.save(out, quality=94, optimize=True)
    return {
        "path": str(out),
        "layout": str(cfg["layout"]),
        "palette": ",".join(cfg["palette"]),
        "headline": headline,
        "source_date": source_date,
        "prompt": (
            f"Radar BDS Facebook editorial visual, pillar={pillar}, layout={cfg['layout']}; "
            "illustration only, no fake map/document/listing evidence, maximum 2 key metrics, no long paragraph."
        ),
    }


# Reader links must not expose internal filter params or internal tab names.
INTERNAL_QUERY_PARAMS = {"mos_min", "mos_max", "tb_min", "tb_max", "tab", "ward"}


def _strip_internal_params(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.query:
        return url
    kept = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key not in INTERNAL_QUERY_PARAMS
    ]
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(kept))._replace(fragment=""))


def build_self_comment(page: dict[str, Any], url: str, slug: str) -> str:
    editorial = page.get("social_editorial") if isinstance(page.get("social_editorial"), dict) else {}
    destination = _plain(editorial.get("radar_url") or editorial.get("cta_url") or page.get("primary_href") or url)
    # Internal filter params (mos_min, tab=signals...) must never reach a reader
    # link. Strip them so the pinned comment opens a clean Radar page.
    destination_url = _strip_internal_params(absolute_url(destination))
    area = extract_area(page)
    article_link = utm_url(absolute_url(url), slug, campaign="rb_editorial_article", medium="pinned_comment")
    main_link = utm_url(destination_url, slug, campaign="rb_editorial", medium="pinned_comment")
    if is_real_area(area) and destination_url == absolute_url(url):
        # Ward filter deep-link also stays free of internal params/tab names.
        filter_link = utm_url(
            _strip_internal_params(f"{SITE}/?tab=signals&ward={urllib.parse.quote_plus(area)}"),
            f"{slug}-{slug_hashtag(area)}",
            campaign="ward_filter",
            medium="pinned_comment",
        )
        return (
            f"Muốn tự đối chiếu thêm, anh chị có thể mở nhóm tin {area}: {filter_link}\n\n"
            f"Bài Radar liên quan: {article_link}\n\n"
            "Radar BDS dùng dữ liệu giá rao để lọc ban đầu; trước khi quyết định mua vẫn cần kiểm tra thực tế, vị trí và giấy tờ."
        )
    return (
        f"Xem bài/công cụ Radar liên quan ở đây: {main_link}\n\n"
        "Radar BDS dùng dữ liệu giá rao để lọc ban đầu; trước khi quyết định mua vẫn cần kiểm tra thực tế, vị trí và giấy tờ."
    )


def enforce_source_gate(*, mode: str, skip_verify: bool, http_status: int | None, source_url: str) -> None:
    if mode == "publish" and skip_verify:
        raise ValueError("skip-verify chỉ dùng cho review; publish cần kiểm nguồn HTTP")
    if mode == "publish" and http_status != 200:
        raise ValueError(f"publish requires healthy source URL before queueing: {source_url} => {http_status}")


def build_editorial(
    page: dict[str, Any],
    url: str,
    slug: str,
    *,
    mode: str = "review",
    skip_verify: bool = False,
    source_http_status: int | None = None,
    asset_dir: str | Path = DEFAULT_ASSET_DIR,
    make_visual: bool = True,
) -> dict[str, Any]:
    enforce_source_gate(mode=mode, skip_verify=skip_verify, http_status=source_http_status, source_url=url)

    pillar = pillar_for_page(page, slug)
    blocking_reasons: list[str] = []
    if pillar == "news_explainer":
        blocking_reasons.extend(_news_blocking_reasons(page))
    if pillar == "listing_breakdown":
        blocking_reasons.extend(_listing_blocking_reasons(page))

    caption = _caption_for_pillar(page, pillar)
    quality_issues = caption_quality_issues(caption)
    if quality_issues:
        blocking_reasons.extend(f"caption-{issue}" for issue in quality_issues)

    visual = render_visual(page, slug, pillar, asset_dir=asset_dir) if make_visual else {}
    metadata = {
        "pillar": pillar,
        "topic": _default_topic(page, pillar),
        "source": source_metadata(page, url, source_http_status),
        "source_date": article_date(page),
        "evidence": evidence_from_page(page),
        "reader_benefit": _reader_benefit(page, pillar),
        "quality_issues": quality_issues,
    }
    status = "blocked" if blocking_reasons else "ready"
    if status == "blocked" and mode == "publish":
        raise ValueError("editorial draft is blocked: " + "; ".join(blocking_reasons))

    return {
        "schema": SCHEMA,
        "version": EDITORIAL_VERSION,
        "status": status,
        "pillar": pillar,
        "caption": caption if status == "ready" else "",
        "blocking_reasons": blocking_reasons,
        "metadata": metadata,
        "self_comment": build_self_comment(page, url, slug),
        "visual": visual,
    }


def build_message(page: dict[str, Any], url: str, style: str = "data_post", slug: str = "") -> str:
    del style  # legacy compatibility; style no longer controls the Page voice.
    draft = build_editorial(page, url, slug or _plain(page.get("path") or "daily_article"), make_visual=False, source_http_status=200)
    if draft["status"] != "ready":
        return ""
    return textwrap.dedent(draft["caption"]).strip()
