#!/usr/bin/env python3
"""Create token-light social post queue items for Radar BDS.

This script intentionally does not use an LLM. It converts an existing
production `/tin-tuc` article config entry into a structured social post JSON.
The browser-use worker can later publish or prepare this queue item.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import textwrap
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


def _extract_data_point(page: dict[str, Any]) -> str:
    cards: list[dict[str, Any]] = []
    article = page.get("article") or {}
    for key in ("summary_cards", "data_cards", "metrics"):
        value = article.get(key) or page.get(key)
        if isinstance(value, list):
            cards.extend([x for x in value if isinstance(x, dict)])
    parts: list[str] = []
    for card in cards[:3]:
        label = _plain(card.get("label") or card.get("title") or "")
        value = _plain(card.get("value") or card.get("body") or card.get("note") or "")
        if label and value:
            parts.append(f"{label}: {value}")
        elif label:
            parts.append(label)
    if parts:
        return "; ".join(parts)
    desc = _plain(page.get("description") or page.get("hero_text") or "")
    return desc[:260].rstrip(" ,.;")


def _build_message(page: dict[str, Any], url: str, style: str = "data_post") -> str:
    title = _short_title(page)
    data = _extract_data_point(page)
    if style == "market_pulse":
        hook = f"Một góc nhìn nhanh từ dữ liệu Radar BDS: {title}."
    else:
        hook = f"Bài mới trên Radar BDS: {title}."
    interpretation = (
        "Khi xem giá rao, nên tách đất nền và nhà đất, đồng thời mở dashboard để kiểm tra từng tin trước khi gọi môi giới."
    )
    body = f"""
    {hook}

    {data}

    {interpretation}

    Xem bài phân tích + mở dashboard Radar BDS:
    {url}

    #RadarBDS #BinhDuong #ThuDauMot #NhaDatBinhDuong
    """
    return textwrap.dedent(body).strip()


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
            "message": _build_message(page, url, args.style),
            "link": url,
            "hashtags": ["RadarBDS", "BinhDuong", "ThuDauMot", "NhaDatBinhDuong"],
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
