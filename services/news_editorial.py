"""Present sourced editorial articles alongside metadata-only press links."""

from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _https_url(value, hosts=()) -> str:
    try:
        parsed = urlsplit(str(value or ""))
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            return ""
        if hosts and not any(host == allowed or host.endswith("." + allowed) for allowed in hosts):
            return ""
        return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))
    except ValueError:
        return ""


def _source_identity(value) -> str:
    parsed = urlsplit(_https_url(value))
    query = [(key, val) for key, val in parse_qsl(parsed.query) if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), urlencode(sorted(query)), ""))


def _valid_date(value) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return date.fromisoformat(str(value)[:10]) <= datetime.now(timezone(timedelta(hours=7))).date()
    except (TypeError, ValueError):
        return False


def news_metadata(article: dict) -> dict | None:
    if not isinstance(article, dict):
        return None
    news = article.get("news")
    if not isinstance(news, dict) or news.get("status") != "published":
        return None
    if not all(isinstance(news.get(key), str) and news[key].strip() for key in ("event_key", "topic", "event_status")):
        return None
    path = str(article.get("path") or "")
    if not path.startswith("/tin-tuc/") or path.count("/") != 2 or any(c in path for c in "?#\\"):
        return None
    dates = article.get("article") or {}
    if not isinstance(dates, dict):
        return None
    if not all(_valid_date(dates.get(key)) for key in ("published_at", "modified_at")):
        return None
    if not isinstance(news.get("sources"), list) or not isinstance(news.get("media", []), list):
        return None
    sources = []
    for source in news["sources"]:
        if not isinstance(source, dict):
            return None
        url = _https_url(source.get("url"))
        if not url or not str(source.get("publisher") or "").strip() or not _valid_date(source.get("published_at")):
            return None
        sources.append({**source, "url": url})
    if not sources:
        return None
    media = []
    for item in news.get("media") or []:
        if not isinstance(item, dict) or item.get("verified") is not True:
            continue
        kind = item.get("kind")
        if not isinstance(kind, str):
            continue
        hosts = {
            "facebook": ("facebook.com",),
            "video": ("youtube.com", "youtu.be", "facebook.com", "tiktok.com"),
        }.get(kind, ())
        url = _https_url(item.get("url"), hosts) if hosts else ""
        if url:
            host = urlsplit(url).hostname or ""
            if kind == "facebook":
                label = "Xem bài Facebook"
            elif host.endswith(("youtube.com", "youtu.be")):
                label = "Xem YouTube Shorts"
            elif host.endswith("facebook.com"):
                label = "Xem Facebook Reels"
            else:
                label = "Xem video ngắn"
            media.append({**item, "url": url, "label": label})
    return {**news, "sources": sources, "media": media}


def is_public_article(article: dict) -> bool:
    return isinstance(article, dict) and ("news" not in article or news_metadata(article) is not None)


def article_for_sources(articles: dict, source_urls: list[str]) -> str | None:
    identities = {_source_identity(url) for url in source_urls}
    candidates = [(article, news_metadata(article)) for article in articles.values()]
    candidates = [(article, news) for article, news in candidates if news]
    for article, news in sorted(candidates, key=lambda pair: str(pair[0]["article"]["modified_at"]), reverse=True):
        if news and any(_source_identity(source["url"]) in identities for source in news["sources"]):
            return article["path"]
    return None


def merge_hot_topic_items(articles: dict, external_items: list[dict]) -> list[dict]:
    cards = []
    seen_events = set()
    covered_sources = set()
    candidates = [(slug, article, news_metadata(article)) for slug, article in articles.items()]
    ordered = sorted((row for row in candidates if row[2]), key=lambda row: str(row[1]["article"]["modified_at"]), reverse=True)
    for slug, article, news in ordered:
        covered_sources.update(_source_identity(source["url"]) for source in news["sources"])
        if news["event_key"] in seen_events:
            continue
        seen_events.add(news["event_key"])
        cards.append({
            "slug": slug, "item_type": "hot_topic", "title": article.get("hero_title"),
            "summary": article.get("description"), "source_name": news["sources"][0]["publisher"],
            "source_url": news["sources"][0]["url"], "sources": news["sources"],
            "topic": news["topic"], "published_at": article["article"]["published_at"],
            "updated_at": article["article"]["modified_at"], "url": article["path"],
            "is_external": False, "news": news,
            "illustration": (article.get("article") or {}).get("illustration"),
        })
    seen_sources = set(covered_sources)
    for item in external_items:
        identity = _source_identity(item.get("canonical_url") or item.get("source_url"))
        if identity and identity in seen_sources:
            continue
        seen_sources.add(identity)
        cards.append({**item, "url": item.get("source_url"), "is_external": True})
    return sorted(cards, key=lambda item: str(item.get("updated_at") if not item["is_external"] else item.get("published_at") or ""), reverse=True)
