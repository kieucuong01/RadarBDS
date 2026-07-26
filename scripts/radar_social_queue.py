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

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = Path("/opt/radar-bds/var/social_queue")
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




def _hashtags_for_page(page: dict[str, Any]) -> list[str]:
    ward = _extract_ward(page, _article_cards(page))
    ward_tag = _slug_hashtag(ward)
    if ward_tag and ward_tag != "ThuDauMot":
        return ["RadarBDS", "BinhDuong", ward_tag]
    return ["RadarBDS", "BinhDuong", "ThuDauMot"]


def _utm_url(url: str, slug: str, *, campaign: str = "daily_article") -> str:
    parsed = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({
        "utm_source": "facebook",
        "utm_medium": "organic",
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
