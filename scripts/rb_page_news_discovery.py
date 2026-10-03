"""Read-only fresh property-news discovery for Radar BDS Page care.

The module intentionally uses only public HTTPS sources, no credentials, and no
third-party parser dependencies. It returns source material for human/LLM review;
it does not publish anything and never labels feed volume as a trend.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import requests

SCHEMA = "rb_page_news_discovery.v1"
VN_TZ = timezone(timedelta(hours=7))
MAX_TEXT_CHARS = 18_000
TIMEOUT = (5, 15)
MAX_RETRIES = 2
USER_AGENT = "RadarBDSNewsDiscovery/1.0 (+https://radarbds.vn; read-only)"

SOURCES: list[dict[str, str]] = [
    {"publisher": "CafeLand", "url": "https://cafeland.vn/tin-tuc/", "kind": "html"},
    {"publisher": "VnExpress", "url": "https://vnexpress.net/rss/bat-dong-san.rss", "kind": "rss"},
    {"publisher": "Tuổi Trẻ", "url": "https://tuoitre.vn/rss/nha-dat.rss", "kind": "rss"},
    {"publisher": "Báo Chính phủ", "url": "https://baochinhphu.vn/bat-dong-san.htm", "kind": "html"},
]

ALLOWED_HOSTS = {
    "cafeland.vn",
    "www.cafeland.vn",
    "vnexpress.net",
    "www.vnexpress.net",
    "tuoitre.vn",
    "www.tuoitre.vn",
    "baochinhphu.vn",
    "www.baochinhphu.vn",
    "chinhphu.vn",
    "www.chinhphu.vn",
    "binhduong.gov.vn",
    "www.binhduong.gov.vn",
    "tphcm.gov.vn",
    "www.tphcm.gov.vn",
    "hochiminhcity.gov.vn",
    "www.hochiminhcity.gov.vn",
    "moc.gov.vn",
    "www.moc.gov.vn",
    "monre.gov.vn",
    "www.monre.gov.vn",
    "vbpl.vn",
    "www.vbpl.vn",
}

PRIMARY_HOSTS = {
    "baochinhphu.vn",
    "www.baochinhphu.vn",
    "chinhphu.vn",
    "www.chinhphu.vn",
    "binhduong.gov.vn",
    "www.binhduong.gov.vn",
    "tphcm.gov.vn",
    "www.tphcm.gov.vn",
    "hochiminhcity.gov.vn",
    "www.hochiminhcity.gov.vn",
    "moc.gov.vn",
    "www.moc.gov.vn",
    "monre.gov.vn",
    "www.monre.gov.vn",
    "vbpl.vn",
    "www.vbpl.vn",
}

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "zarsrc", "mibextid", "mc_cid", "mc_eid"}
SPONSORED_WORDS = ("tài trợ", "quảng cáo", "advertorial", "sponsored")

LOCAL_KEYWORDS = {
    "binh duong": "Bình Dương",
    "bình dương": "Bình Dương",
    "thu dau mot": "Thủ Dầu Một",
    "thủ dầu một": "Thủ Dầu Một",
    "tdm": "Thủ Dầu Một",
    "di an": "Dĩ An",
    "dĩ an": "Dĩ An",
    "thuan an": "Thuận An",
    "thuận an": "Thuận An",
    "ben cat": "Bến Cát",
    "bến cát": "Bến Cát",
    "tan uyen": "Tân Uyên",
    "tân uyên": "Tân Uyên",
}

HCMC_EAST_KEYWORDS = (
    "tp.hcm phía đông",
    "tphcm phía đông",
    "phía đông tp.hcm",
    "thủ đức",
    "thu duc",
    "metro số 1",
    "metro ben thanh suoi tien",
    "metro bến thành suối tiên",
    "vành đai 3",
    "vanh dai 3",
)

NATIONAL_POLICY_KEYWORDS = (
    "nhà ở xã hội",
    "nha o xa hoi",
    "luật đất đai",
    "luat dat dai",
    "bảng giá đất",
    "bang gia dat",
    "tín dụng nhà ở",
    "tin dung nha o",
    "chính sách nhà ở",
    "chinh sach nha o",
)


@dataclass(frozen=True)
class DiscoveryItem:
    publisher: str
    url: str
    title: str
    published_at: datetime | None


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn").replace("đ", "d").replace("Đ", "D")


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _search_text(value: str) -> str:
    return _strip_accents(_norm_text(value)).casefold()


def canonicalize_url(url: str, base: str | None = None) -> str:
    absolute = urljoin(base or "", html.unescape((url or "").strip()))
    parts = urlsplit(absolute)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        return absolute
    scheme = "https"
    host = (parts.hostname or "").lower()
    if not host:
        return absolute
    netloc = host
    if parts.port and parts.port != 443:
        netloc = f"{host}:{parts.port}"
    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        low = key.lower()
        if low in TRACKING_QUERY_KEYS or any(low.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query_pairs.append((key, value))
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, urlencode(query_pairs, doseq=True), ""))


def _is_private_host(host: str) -> bool:
    if not host:
        return True
    if host in {"localhost", "0", "0.0.0.0"} or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
    except ValueError:
        pass
    return False


def _resolve_public_host(host: str) -> None:
    if _is_private_host(host):
        raise ValueError(f"blocked private/localhost host: {host}")
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve host: {host}") from exc
    for info in infos:
        ip = info[4][0]
        if _is_private_host(ip):
            raise ValueError(f"blocked host resolving to private address: {host}")


def validate_public_https_url(url: str) -> str:
    original = (url or "").strip()
    original_scheme = urlsplit(urljoin("", html.unescape(original))).scheme.lower()
    if original_scheme != "https":
        raise ValueError("only https URLs are allowed")
    clean = canonicalize_url(original)
    parts = urlsplit(clean)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise ValueError("only https URLs are allowed")
    if "@" in parts.netloc:
        raise ValueError("credentials in URL are not allowed")
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"host not allowlisted: {host}")
    _resolve_public_host(host)
    return clean


def _decode_body(response: requests.Response) -> str:
    """Decode a response, honoring an XML/HTML declared charset.

    Tuổi Trẻ serves ``text/xml`` without a charset, so ``requests`` falls back to
    ISO-8859-1 and the Vietnamese titles become mojibake. The XML declaration is
    the authoritative metadata, so prefer it when present.
    """
    raw = response.content or b""
    declared = None
    head = raw[:200].decode("ascii", errors="ignore")
    match = re.search(r'encoding=["\']([\w-]+)["\']', head)
    if match:
        declared = match.group(1)
    elif re.search(r'charset=["\']?([\w-]+)', head, re.I):
        declared = re.search(r'charset=["\']?([\w-]+)', head, re.I).group(1)
    for candidate in (declared, response.encoding, "utf-8"):
        if not candidate:
            continue
        try:
            return raw.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return response.text


def _fetch_url(url: str, *, session: requests.Session | None = None) -> requests.Response:
    clean = validate_public_https_url(url)
    sess = session or requests.Session()
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = sess.get(clean, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
            validate_public_https_url(response.url)
            for redirect in response.history:
                validate_public_https_url(redirect.url)
            response.raise_for_status()
            return response
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            if attempt >= MAX_RETRIES:
                break
            time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"fetch failed for {clean}: {last_exc}")


def parse_date(value: str | None) -> datetime | None:
    raw = _norm_text(value or "")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        iso = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            # Common Vietnamese metadata sometimes includes only yyyy-mm-dd.
            try:
                dt = datetime.strptime(raw[:10], "%Y-%m-%d")
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return dt.astimezone(VN_TZ)


def _rss_child_text(element: ET.Element, local_name: str) -> str:
    for child in list(element):
        if child.tag.rsplit("}", 1)[-1] == local_name:
            return _norm_text(child.text or "")
    return ""


def _parse_rss(text: str, publisher: str) -> list[DiscoveryItem]:
    root = ET.fromstring(text.encode("utf-8"))
    items: list[DiscoveryItem] = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        title = _rss_child_text(item, "title")
        link = _rss_child_text(item, "link") or _rss_child_text(item, "guid")
        published = (
            _rss_child_text(item, "pubDate")
            or _rss_child_text(item, "date")
            or _rss_child_text(item, "published")
            or _rss_child_text(item, "updated")
        )
        if title and link:
            items.append(DiscoveryItem(publisher=publisher, url=canonicalize_url(link), title=title, published_at=parse_date(published)))
    return items


class ListingLinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._href_stack: list[str] = []
        self._text_stack: list[list[str]] = []
        self.items: list[DiscoveryItem] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr = {k.lower(): v or "" for k, v in attrs}
        href = attr.get("href", "")
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            return
        self._href_stack.append(canonicalize_url(href, self.base_url))
        self._text_stack.append([])

    def handle_data(self, data: str) -> None:
        if self._text_stack:
            self._text_stack[-1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href_stack:
            return
        href = self._href_stack.pop()
        text = _norm_text(" ".join(self._text_stack.pop()))
        if len(text) >= 12:
            self.items.append(DiscoveryItem(publisher="", url=href, title=text, published_at=None))


def _parse_listing_html(text: str, source: dict[str, str]) -> list[DiscoveryItem]:
    parser = ListingLinkParser(source["url"])
    parser.feed(text)
    items = []
    source_host = urlsplit(source["url"]).hostname or ""
    source_path = urlsplit(source["url"]).path.rstrip("/").lower()
    for item in parser.items:
        host = urlsplit(item.url).hostname or ""
        if host != source_host:
            continue
        parts = urlsplit(item.url)
        path = parts.path.lower()
        if not path.endswith(".html"):
            # Article links on news hubs end in .html; section/category links do not.
            continue
        if not any(token in path for token in ("tin-tuc", "bat-dong-san", "nha-dat")):
            continue
        items.append(DiscoveryItem(publisher=source["publisher"], url=item.url, title=item.title, published_at=None))
    return items


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None
        self._stack: list[str] = []
        self._capture_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self._skip_depth = 0
        self._article_depth = 0
        self._body_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {k.lower(): v or "" for k, v in attrs}
        self._stack.append(tag)
        if tag in {"script", "style", "nav", "footer", "aside", "form", "noscript"}:
            self._skip_depth += 1
        if tag in {"article", "main"}:
            self._article_depth += 1
        if tag == "body":
            self._body_depth += 1
        if tag == "h1":
            self._capture_title = True
        if tag == "meta":
            key = (attr.get("property") or attr.get("name") or attr.get("itemprop") or "").lower()
            content = attr.get("content", "")
            if key and content:
                self.meta[key] = html.unescape(content)
        if tag == "link" and attr.get("rel", "").lower() == "canonical" and attr.get("href"):
            self.canonical = attr["href"]

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = _norm_text(data)
        if not text:
            return
        if self._capture_title:
            self._title_parts.append(text)
        if self._article_depth or (self._body_depth and self._stack and self._stack[-1] in {"p", "h1", "h2", "li"}):
            self._text_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "h1":
            self._capture_title = False
        if tag in {"script", "style", "nav", "footer", "aside", "form", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"article", "main"} and self._article_depth:
            self._article_depth -= 1
        if tag == "body" and self._body_depth:
            self._body_depth -= 1
        for idx in range(len(self._stack) - 1, -1, -1):
            if self._stack[idx] == tag:
                del self._stack[idx:]
                break

    @property
    def title(self) -> str:
        return _norm_text(" ".join(self._title_parts))

    @property
    def text(self) -> str:
        cleaned: list[str] = []
        previous = ""
        for part in self._text_parts:
            if part != previous:
                cleaned.append(part)
                previous = part
        return _norm_text("\n".join(cleaned))[:MAX_TEXT_CHARS]


TITLE_SUFFIXES = (" - cafeland.vn", " - vnexpress.net", " - tuoitre.vn", " - bao chinh phu", " | cafeland.vn")


def _clean_title(title: str) -> str:
    value = _norm_text(title)
    lowered = value.casefold()
    for suffix in TITLE_SUFFIXES:
        if lowered.endswith(suffix):
            value = value[: -len(suffix)].strip()
            lowered = value.casefold()
    return re.sub(r"\s+[-|]\s*$", "", value).strip()


def _json_ld_published(text: str) -> str | None:
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', text, re.S | re.I):
        # The published date is realistically findable without a full JSON parse.
        match = re.search(r'"(?:datePublished|dateCreated|uploadDate)"\s*:\s*"([^"]+)"', block)
        if match:
            return match.group(1)
    return None


VISIBLE_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})(?:\s*[-–]?\s*(\d{1,2}):(\d{2}))?")


def _visible_published(text: str) -> str | None:
    match = VISIBLE_DATE_RE.search(re.sub(r"<[^>]+>", " ", text))
    if not match:
        return None
    day, month, year, hour, minute = match.groups()
    try:
        stamp = f"{int(year):04d}-{int(month):02d}-{int(day):02d}T{int(hour or 0):02d}:{int(minute or 0):02d}:00+07:00"
        datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return stamp


def _parse_article(text: str, url: str) -> dict[str, Any]:
    parser = ArticleParser()
    parser.feed(text)
    meta = parser.meta
    title = (
        meta.get("og:title")
        or meta.get("twitter:title")
        or meta.get("title")
        or parser.title
    )
    published_raw = (
        meta.get("article:published_time")
        or meta.get("pubdate")
        or meta.get("publishdate")
        or meta.get("date")
        or meta.get("datepublished")
        or meta.get("dc.date")
        or _json_ld_published(text)
        or _visible_published(text)
    )
    canonical = canonicalize_url(parser.canonical or url, url)
    return {
        "url": canonical,
        "title": _clean_title(title),
        "published_at": parse_date(published_raw),
        "text": parser.text,
    }


def make_topic_key(title: str) -> str:
    value = _search_text(title)
    value = re.sub(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", " ", value)
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    tokens = [t for t in value.split() if t not in {"va", "ve", "cua", "cho", "tai", "tu", "den", "mot"}]
    return "-".join(tokens[:12]) or hashlib.sha256(value.encode()).hexdigest()[:12]


def _location_for(title: str, text: str) -> tuple[str, bool]:
    haystack_raw = f"{title}\n{text[:4000]}"
    haystack = _search_text(haystack_raw)
    for key, label in LOCAL_KEYWORDS.items():
        if _strip_accents(key).casefold() in haystack:
            return label, True
    if any(_strip_accents(k).casefold() in haystack for k in HCMC_EAST_KEYWORDS):
        return "TP.HCM east / metro-linked", True
    if any(_strip_accents(k).casefold() in haystack for k in NATIONAL_POLICY_KEYWORDS):
        return "national_policy", True
    return "", False


def _is_primary_url(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() in PRIMARY_HOSTS


def _rejection_reasons(
    *,
    title: str,
    text: str,
    published_at: datetime | None,
    now: datetime,
    relevant: bool,
) -> list[str]:
    reasons: list[str] = []
    combined = f"{title} {text[:500]}".casefold()
    if any(word in combined for word in SPONSORED_WORDS):
        reasons.append("sponsored_or_advertorial")
    if not published_at:
        reasons.append("unknown_published_at")
    else:
        if published_at < now - timedelta(days=7):
            reasons.append("published_older_than_7_days")
        if published_at > now + timedelta(minutes=10):
            reasons.append("published_in_future")
    if not relevant:
        reasons.append("not_relevant_location_or_policy")
    if len(text) < 40:
        reasons.append("no_clean_article_body")
    return reasons


def _score(published_at: datetime | None, now: datetime, location: str, primary: bool) -> float:
    if not published_at:
        return 0.0
    age_hours = max(0.0, (now - published_at).total_seconds() / 3600)
    freshness = max(0.0, 40.0 - age_hours / 4.0)
    local = 35.0 if location and location not in {"national_policy", "TP.HCM east / metro-linked"} else 20.0 if location else 0.0
    return round(freshness + local + (15.0 if primary else 0.0), 2)


def _candidate_from_item(item: DiscoveryItem, now: datetime, session: requests.Session | None) -> dict[str, Any]:
    response = _fetch_url(item.url, session=session)
    article = _parse_article(_decode_body(response), response.url)
    url = article["url"]
    title = article["title"] or item.title
    published = article["published_at"] or item.published_at
    text = article["text"]
    location, relevant = _location_for(title, text)
    primary = _is_primary_url(url)
    reasons = _rejection_reasons(title=title, text=text, published_at=published, now=now, relevant=relevant)
    published_iso = published.isoformat() if published else ""
    return {
        "id": hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
        "url": url,
        "publisher": item.publisher,
        "title": title,
        "published_at": published_iso,
        "fetched_at": now.isoformat(),
        "text": text,
        "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "is_primary": primary,
        "eligible": not reasons,
        "classification": "news_candidate",
        "trend_evidence": [],
        "location": location,
        "topic_key": make_topic_key(title),
        "score": _score(published, now, location, primary),
        "requires_primary": not primary,
        "rejection_reasons": reasons,
    }


def _discover_items(source: dict[str, str], session: requests.Session | None) -> list[DiscoveryItem]:
    response = _fetch_url(source["url"], session=session)
    text = _decode_body(response)
    if source.get("kind") == "rss":
        return _parse_rss(text, source["publisher"])
    return _parse_listing_html(text, source)


MAX_FETCHES_PER_RUN = 45


def collect_news(
    now: datetime | None = None,
    limit: int = 12,
    *,
    add_urls: list[str] | None = None,
    recent_urls: set[str] | list[str] | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Collect fresh public property-news candidates.

    Public API consumed by Page-care workers: ``collect_news(now=None,
    limit=12) -> report``. Keyword-only arguments are optional operational hooks
    for CLI enrichment/tests and do not change the report contract.
    """
    current = now or datetime.now(VN_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=VN_TZ)
    else:
        current = current.astimezone(VN_TZ)
    max_candidates = max(1, int(limit))
    errors: list[str] = []
    raw_items: list[DiscoveryItem] = []
    sess = session or requests.Session()

    for source in SOURCES:
        try:
            raw_items.extend(_discover_items(source, sess))
        except Exception as exc:  # keep other sources alive
            errors.append(f"{source.get('publisher', source.get('url', 'source'))}: {exc}")

    for add_url in add_urls or []:
        try:
            clean = validate_public_https_url(add_url)
            host = urlsplit(clean).hostname or ""
            raw_items.append(DiscoveryItem(publisher=host, url=clean, title="", published_at=None))
        except Exception as exc:
            errors.append(f"add-url {add_url}: {exc}")

    # Prefer items that already carry a feed timestamp, then keep source order.
    raw_items.sort(key=lambda it: it.published_at is None)

    seen_urls = {canonicalize_url(u) for u in (recent_urls or [])}
    seen_topics: set[str] = set()
    taken: list[dict[str, Any]] = []

    fetches = 0
    for item in raw_items:
        try:
            clean_item_url = validate_public_https_url(item.url)
        except Exception as exc:
            errors.append(f"{item.url}: {exc}")
            continue
        if clean_item_url in seen_urls:
            continue
        if fetches >= MAX_FETCHES_PER_RUN and len([c for c in taken if c["eligible"]]) >= max_candidates:
            break
        try:
            candidate = _candidate_from_item(
                DiscoveryItem(item.publisher, clean_item_url, item.title, item.published_at), current, sess
            )
        except Exception as exc:
            errors.append(f"{clean_item_url}: {exc}")
            continue
        fetches += 1
        if candidate["url"] in seen_urls:
            continue
        if candidate["topic_key"] in seen_topics:
            continue
        seen_urls.add(candidate["url"])
        seen_topics.add(candidate["topic_key"])
        taken.append(candidate)

    taken.sort(key=lambda c: (bool(c["eligible"]), float(c["score"]), c["published_at"]), reverse=True)
    return {"schema": SCHEMA, "generated_at": current.isoformat(), "candidates": taken[:max_candidates], "errors": errors}


def atomic_write_json(path: str | os.PathLike[str], report: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, output)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect read-only property-news candidates for Radar BDS Page care")
    parser.add_argument("--out", help="Write JSON report atomically to this path")
    parser.add_argument("--limit", type=int, default=12, help="Maximum candidates to include")
    parser.add_argument("--add-url", action="append", default=[], help="Official allowlisted URL to fetch as an extra candidate")
    args = parser.parse_args(argv)

    report = collect_news(limit=args.limit, add_urls=args.add_url)
    if args.out:
        atomic_write_json(args.out, report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
