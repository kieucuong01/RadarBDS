#!/usr/bin/env python3
"""Reviewed Radar BDS Facebook Page news workflow.

This module is intentionally separate from the legacy no-agent Page-care path.
It prepares review-only news queue items, records a human/LLM review stamp, and
only then adapts the existing browser publisher for a fail-closed publish.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path("/opt/radar-bds/current")
DEFAULT_OUT_DIR = Path("/opt/radar-bds/var/social_preview/news")
DEFAULT_LOCK = Path("/opt/radar-bds/var/social_queue/rb_page_news_workflow.lock")
PAGE_URL = "https://www.facebook.com/radarbdsvn/"
QUEUE_SCHEMA = "radar_social_queue.v1"
REPORT_SCHEMA = "rb_page_news_discovery.v1"
DRAFT_SCHEMA = "rb_page_news_draft.v1"
TRUSTED_NEWS_DOMAINS = {"cafeland.vn", "vnexpress.net", "tuoitre.vn", "baochinhphu.vn"}
PRODUCT_REFERENCE_HOST = "radarbds.vn"
LOCAL_TZ = dt.timezone(dt.timedelta(hours=7))
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MATERIAL_KINDS = {"policy", "infrastructure", "financing", "law", "legal", "planning"}
# Wording that would state or imply an official action/rule. Kept deliberately
# narrower than a general topic vocabulary: ordinary buyer comparisons about
# roads/bridges/legal due diligence/loans are not official-material claims.
# Explicit material kinds are strict, and material assertion wording remains
# strict even if a draft labels the claim as a buyer tip.
MATERIAL_RE = re.compile(
    r"\b("
    r"(?:phê duyệt|đã\s+phê duyệt|đã\s+được\s+phê duyệt|được\s+phê duyệt)|"
    r"(?:khởi công|đã\s+khởi công|chính thức\s+khởi công)|"
    r"(?:luật|nghị định|thông tư|quy định).{0,40}(?:có hiệu lực|ban hành|áp dụng)|"
    r"(?:có hiệu lực)|"
    r"(?:lãi suất\s*(?:\d|[0-9]+[,.]?[0-9]*\s*%))|"
    r"(?:(?:cao tốc|metro|vành đai|cầu|đường).{0,50}(?:phê duyệt|khởi công|mở rộng|nâng cấp))"
    r")\b",
    re.I,
)
TREND_RE = re.compile(r"\b(xu hướng|tăng|giảm|sốt|nóng|trend|bùng nổ|dẫn sóng)\b", re.I)
FORBIDDEN_COPY_RE = re.compile(
    r"\b(trung vị|\bMOS\b|sample|mẫu hợp lệ|snapshot|ROI|cam kết sinh lời|đảm bảo lợi nhuận|"
    r"chắc chắn lời|sốt nóng|lướt sóng chắc thắng)\b",
    re.I,
)


def _load_py_module(name: str, path: Path):
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


radar_auto = _load_py_module("radar_social_auto_post", REPO / "scripts" / "radar_social_auto_post.py")


def now_local() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).astimezone()


def parse_dt(value: Any, *, field: str) -> dt.datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"missing {field}")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return parsed.astimezone(LOCAL_TZ)


def parse_source_date(value: Any, *, field: str) -> dt.date:
    """Parse source publication metadata without manufacturing a time."""
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"missing {field}")
    if DATE_ONLY_RE.match(text):
        try:
            return dt.date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value}") from exc
    return parse_dt(text, field=field).date()


def _local_day(value: dt.datetime) -> dt.date:
    if value.tzinfo is None:
        raise ValueError("now must include timezone")
    return value.astimezone(LOCAL_TZ).date()


def _plain(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _safe_slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-").lower()
    return text or "item"


def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def is_trusted_source(candidate: dict[str, Any]) -> bool:
    url = str(candidate.get("url") or "")
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    if host in TRUSTED_NEWS_DOMAINS or any(host.endswith("." + d) for d in TRUSTED_NEWS_DOMAINS):
        return True
    if host.endswith(".gov.vn") or host == "gov.vn":
        return bool(candidate.get("is_primary"))
    return False


def is_radar_product_reference(candidate: dict[str, Any]) -> bool:
    url = str(candidate.get("url") or "")
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == PRODUCT_REFERENCE_HOST


def _radar_article_paths() -> set[str]:
    try:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from config.seo_articles import SEO_ARTICLES  # pylint: disable=import-error
    except Exception:
        return set()
    paths = set()
    for page in SEO_ARTICLES.values():
        if isinstance(page, dict) and str(page.get("path", "")).startswith("/tin-tuc/"):
            paths.add(str(page["path"]))
    return paths


def validate_radar_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(str(url or ""))
    if parsed.scheme != "https" or parsed.hostname != "radarbds.vn" or not parsed.path.startswith("/tin-tuc/"):
        raise ValueError("radar_url must be an existing https://radarbds.vn/tin-tuc/... URL")
    paths = _radar_article_paths()
    if paths and parsed.path.rstrip("/") not in paths:
        raise ValueError("radar_url path is not a known Radar tin-tuc article")
    return urllib.parse.urlunsplit(parsed._replace(query="", fragment=""))


def utm_url(url: str, slug: str, *, medium: str = "social", campaign: str = "rb_content_v2") -> str:
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


def recommended_lane(posted: dict[str, Any]) -> str:
    """Recommend radar/news with about 3 news per 10 real posts, never consecutive news.

    Historical entries without a lane are labeled as ``radar`` so old state does
    not force a synthetic news quota.
    """
    entries: list[dict[str, Any]] = []
    for entry in (posted or {}).values():
        if not isinstance(entry, dict) or not entry.get("posted_at"):
            continue
        lane = str(entry.get("lane") or "radar").casefold()
        entries.append({"posted_at": str(entry.get("posted_at")), "lane": "news" if lane == "news" else "radar"})
    entries.sort(key=lambda item: item["posted_at"], reverse=True)
    if entries and entries[0]["lane"] == "news":
        return "radar"
    recent = entries[:10]
    return "news" if sum(1 for item in recent if item["lane"] == "news") < 3 else "radar"


def validate_source_report(report: dict[str, Any], *, now: dt.datetime | None = None) -> dict[str, dict[str, Any]]:
    now = now or now_local()
    if report.get("schema") != REPORT_SCHEMA:
        raise ValueError(f"unsupported report schema: {report.get('schema')}")
    parse_dt(report.get("generated_at"), field="generated_at")
    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("report candidates must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be an object")
        cid = _plain(candidate.get("id"))
        if not cid:
            raise ValueError("candidate missing id")
        if cid in by_id:
            raise ValueError(f"duplicate candidate id: {cid}")
        classification = str(candidate.get("classification") or "")
        if classification not in {"news_candidate", "product_reference"}:
            raise ValueError(f"candidate {cid} classification must be news_candidate or product_reference")
        if classification == "news_candidate":
            if not is_trusted_source(candidate):
                raise ValueError(f"candidate {cid} is not from a trusted HTTPS source domain")
        elif not is_radar_product_reference(candidate):
            raise ValueError(f"candidate {cid} product_reference must be from https://radarbds.vn")
        text = str(candidate.get("text") or "")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if candidate.get("content_sha256") != digest:
            raise ValueError(f"candidate {cid} content_sha256 mismatch")
        fetched_at = parse_dt(candidate.get("fetched_at"), field=f"{cid}.fetched_at")
        if fetched_at > now + dt.timedelta(minutes=5):
            raise ValueError(f"candidate {cid} fetched_at is in the future")
        if classification == "product_reference":
            if candidate.get("published_at") not in {None, ""}:
                published_day = parse_source_date(candidate.get("published_at"), field=f"{cid}.published_at")
                if published_day > _local_day(now):
                    raise ValueError(f"candidate {cid} published_at is in the future")
            if now - fetched_at > dt.timedelta(days=7):
                raise ValueError(f"candidate {cid} fetched_at is older than 7d")
        else:
            published_day = parse_source_date(candidate.get("published_at"), field=f"{cid}.published_at")
            if published_day > _local_day(now):
                raise ValueError(f"candidate {cid} published_at is in the future")
            if now - fetched_at > dt.timedelta(hours=24):
                raise ValueError(f"candidate {cid} fetched_at is older than 24h")
        if candidate.get("eligible") is not True:
            # Keep in map for diagnostics only; drafts may not select it.
            pass
        by_id[cid] = candidate
    return by_id


def _caption_has_attribution(caption: str, lead: dict[str, Any]) -> bool:
    publisher = _plain(lead.get("publisher"))
    try:
        date = parse_source_date(lead.get("published_at"), field="published_at")
    except ValueError:
        return False
    forms = {date.isoformat(), date.strftime("%d/%m/%Y"), date.strftime("%d-%m-%Y")}
    return bool(publisher and publisher.casefold() in caption.casefold() and any(f in caption for f in forms))


def _claim_needs_primary(claim: dict[str, Any], source: dict[str, Any]) -> bool:
    """Official primary needed only when the claim itself is material.

    ``source.requires_primary`` describes whether a *material* claim may be made
    at all about this source; it is a gate, not a trigger. Treating it as a
    trigger would force every claim to cite a government page, which is
    impossible for trusted-outlet reporting (the common case) and would make the
    news lane unusable.
    """
    if _plain(claim.get("kind")).casefold() in MATERIAL_KINDS:
        return True
    haystack = " ".join([_plain(claim.get("claim")), _plain(claim.get("quote"))])
    return bool(MATERIAL_RE.search(haystack))


def validate_report_and_draft(report: dict[str, Any], draft: dict[str, Any], *, now: dt.datetime | None = None) -> dict[str, Any]:
    now = now or now_local()
    by_id = validate_source_report(report, now=now)
    if draft.get("schema") not in {DRAFT_SCHEMA, None}:
        raise ValueError(f"unsupported draft schema: {draft.get('schema')}")
    selected = draft.get("selected_ids")
    if not isinstance(selected, list) or not selected or not all(isinstance(x, str) and x in by_id for x in selected):
        raise ValueError("draft selected_ids must reference report candidate IDs")
    selected_sources = [by_id[x] for x in selected]
    lead = selected_sources[0]
    if lead.get("eligible") is not True:
        raise ValueError("selected lead source is not eligible")
    if lead.get("classification") != "news_candidate":
        raise ValueError("lead source must be news_candidate")
    lead_published = parse_source_date(lead.get("published_at"), field="lead.published_at")
    if _local_day(now) - lead_published > dt.timedelta(days=7):
        raise ValueError("selected lead published_at is older than 7d")
    radar_url = validate_radar_url(str(draft.get("radar_url") or ""))
    caption = _plain(draft.get("caption"))
    headline = _plain(draft.get("headline"))
    reader_benefit = _plain(draft.get("reader_benefit"))
    if not caption or not headline or not reader_benefit:
        raise ValueError("draft requires caption, headline and reader_benefit")
    if draft.get("visual_mode") not in {"photoreal", "infographic"}:
        raise ValueError("visual_mode must be photoreal or infographic")
    if FORBIDDEN_COPY_RE.search("\n".join([caption, headline])):
        raise ValueError("caption/headline contains stats jargon, hype, or guaranteed ROI language")
    if not _caption_has_attribution(caption, lead):
        raise ValueError("caption must include reader-facing news attribution and source date")
    claims = draft.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("draft claims must be a non-empty list")
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("claim must be an object")
        sid = _plain(claim.get("source_id"))
        source = by_id.get(sid)
        if not source or sid not in selected:
            raise ValueError("claim source_id must reference a selected source")
        quote = _plain(claim.get("quote"))
        if not quote:
            raise ValueError("claim missing quote")
        if quote not in str(source.get("text") or ""):
            raise ValueError("claim quote is not present in source text")
        if _claim_needs_primary(claim, source) and not (source.get("is_primary") and (_host(str(source.get("url") or "")).endswith(".gov.vn") or _host(str(source.get("url") or "")) == "baochinhphu.vn")):
            raise ValueError("material law/infrastructure/financing claim requires a genuine official primary source quote")
        if TREND_RE.search(_plain(claim.get("claim"))) and not source.get("trend_evidence"):
            raise ValueError("unsupported trend claim without measured trend_evidence")
    if not isinstance(draft.get("known_unknowns"), list):
        raise ValueError("known_unknowns must be a list")
    return {"sources": selected_sources, "lead": lead, "radar_url": radar_url, "claims": claims}


def make_placeholder_image(out_dir: Path, slug: str, headline: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{slug}-concept.png"
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (1200, 675), "#0f172a")
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
        draw.rectangle((60, 60, 1140, 615), outline="#38bdf8", width=5)
        draw.text((95, 120), "Radar BDS · Tin mới, hiểu đúng", fill="#bae6fd", font=small)
        words = headline.split()
        lines: list[str] = []
        cur = ""
        for word in words:
            test = (cur + " " + word).strip()
            if draw.textbbox((0, 0), test, font=font)[2] <= 980:
                cur = test
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        for idx, line in enumerate(lines[:4]):
            draw.text((95, 220 + idx * 62), line, fill="white", font=font)
        draw.text((95, 560), "Minh họa AI khái niệm — không phải ảnh tiến độ hoặc bản đồ pháp lý", fill="#cbd5e1", font=small)
        img.save(path)
    except Exception:
        path.write_bytes(b"RB NEWS CONCEPT IMAGE PLACEHOLDER")
    return path


def build_news_queue(report: dict[str, Any], draft: dict[str, Any], *, out_dir: Path, now: dt.datetime | None = None) -> Path:
    now = now or now_local()
    validated = validate_report_and_draft(report, draft, now=now)
    lead = validated["lead"]
    sources = validated["sources"]
    lead_id = str(lead["id"])
    slug = f"news-{_safe_slug(lead_id)}-{now.date().isoformat()}"
    radar_url = validated["radar_url"]
    radar_utm = utm_url(radar_url, slug)
    source_urls = [str(s["url"]) for s in sources]
    headline = _plain(draft["headline"])[:90]
    visual_path = make_placeholder_image(out_dir, slug, headline)
    claims = [
        {
            "source_id": _plain(c.get("source_id")),
            "quote": _plain(c.get("quote")),
            "kind": _plain(c.get("kind")),
            "claim": _plain(c.get("claim")),
        }
        for c in validated["claims"]
    ]
    self_comment = (
        "Nguồn gốc tin để tự kiểm tra:\n"
        + "\n".join(f"- {url}" for url in source_urls)
        + f"\n\nGóc đọc thêm trên Radar BDS: {radar_utm}"
    )
    topic = _plain(lead.get("topic_key")) or _safe_slug(headline)
    event_fingerprint = hashlib.sha256((topic + "|" + "|".join(source_urls)).encode("utf-8")).hexdigest()[:16]
    item = {
        "schema": QUEUE_SCHEMA,
        "created_at": now.isoformat(timespec="seconds"),
        "lane": "news",
        "source": {
            "slug": slug,
            "url": str(lead["url"]),
            "title": headline,
            "path": urllib.parse.urlsplit(radar_url).path,
            "article_date": parse_source_date(lead["published_at"], field="lead.published_at").isoformat(),
            "http_status": None,
            "news_source_urls": source_urls,
            "news_topic_key": topic,
        },
        "target": {
            "platform": "facebook",
            "surface": "page",
            "page_url": PAGE_URL,
            "mode": "review",
            "requires_review": True,
        },
        "content": {
            "style": "news_explainer",
            "message": _plain(draft["caption"]),
            "caption": _plain(draft["caption"]),
            "link": radar_utm,
            "self_comment": self_comment,
            "hashtags": ["#RadarBDS", "#TinBatDongSan", "#BinhDuong"],
            "visual_style": "news_explainer",
            "visual_headline": headline,
            "visual_mode": draft["visual_mode"],
            "visual_prompt": (
                "Conceptual AI illustration only. Do not depict actual project progress, construction status, "
                "real cadastral/legal map boundaries, route alignments, or false maps. Use abstract newsroom + "
                f"real-estate due-diligence symbols with this short approved headline: {headline}"
            ),
            "visual_path": str(visual_path),
            "image_path": str(visual_path),
            "generated_by": "rb_page_news_workflow",
            "editorial": {
                "schema": "rb_social_editorial.v1",
                "status": "ready",
                "pillar": "news_explainer",
                "topic": topic,
                "source": str(lead["url"]),
                "source_date": parse_source_date(lead["published_at"], field="lead.published_at").isoformat(),
                "evidence": claims,
                "reader_benefit": _plain(draft["reader_benefit"]),
                "caption": _plain(draft["caption"]),
            },
        },
        "editorial": {"metadata": {"pillar": "news_explainer", "topic": topic}},
        "news": {
            "draft_schema": draft.get("schema") or DRAFT_SCHEMA,
            "selected_ids": list(draft["selected_ids"]),
            "headline": headline,
            "reader_benefit": _plain(draft["reader_benefit"]),
            "radar_url": radar_url,
            "source_urls": source_urls,
            "lead_source_id": lead_id,
            "topic_key": topic,
            "event_status": _plain(draft.get("event_status")),
            "event_fingerprint": event_fingerprint,
            "known_unknowns": draft.get("known_unknowns") or [],
            "evidence": claims,
            "sources": [
                {
                    "id": str(s["id"]),
                    "url": str(s["url"]),
                    "publisher": _plain(s.get("publisher")),
                    "title": _plain(s.get("title")),
                    "classification": str(s.get("classification") or ""),
                    "published_at": s.get("published_at"),
                    "fetched_at": s.get("fetched_at"),
                    "content_sha256": str(s.get("content_sha256")),
                    "is_primary": bool(s.get("is_primary")),
                    "requires_primary": bool(s.get("requires_primary")),
                    "topic_key": _plain(s.get("topic_key")),
                }
                for s in sources
            ],
        },
        "status": "queued",
        "guards": {"requires_review_stamp": True, "verify_before_publish": True, "no_browser_in_prepare": True},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{now.date().isoformat()}-{slug}-page-review.json"
    out.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def prepare_news(report_path: Path, draft_path: Path, out_dir: Path, *, now: dt.datetime | None = None) -> Path:
    queue_path = build_news_queue(load_json(report_path), load_json(draft_path), out_dir=out_dir, now=now)
    radar_auto.upgrade_queue_image(queue_path)
    return queue_path


def _image_path(data: dict[str, Any]) -> Path:
    content = data.get("content") or {}
    path = content.get("visual_path") or content.get("image_path")
    if not path:
        raise ValueError("queue missing visual_path/image_path")
    return Path(path)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def review_payload(data: dict[str, Any], image_sha256: str) -> dict[str, Any]:
    return {
        "schema": data.get("schema"),
        "source": data.get("source"),
        "headline": (data.get("news") or {}).get("headline") or (data.get("content") or {}).get("visual_headline"),
        "caption": (data.get("content") or {}).get("message"),
        "comment": (data.get("content") or {}).get("self_comment"),
        "evidence": (data.get("news") or {}).get("evidence") or ((data.get("content") or {}).get("editorial") or {}).get("evidence"),
        "image_sha256": image_sha256,
    }


def review_hash(data: dict[str, Any], image_sha256: str) -> str:
    blob = json.dumps(review_payload(data, image_sha256), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def approve_queue(queue_path: Path, *, note: str) -> dict[str, Any]:
    note = _plain(note)
    if not note:
        raise SystemExit("approval note is required")
    data = load_json(queue_path)
    image = _image_path(data)
    if not image.exists():
        raise SystemExit(f"approval image not found: {image}")
    image_sha = _sha256_file(image)
    stamp = {
        "approved_at": now_local().isoformat(timespec="seconds"),
        "note": note,
        "image_sha256": image_sha,
        "stamp_hash": review_hash(data, image_sha),
        "stamp_algorithm": "sha256(review_payload.v1)",
        "meaning": "LLM/human review acknowledgment of caption, sources and visual QA; not automated visual understanding.",
    }
    data["review"] = stamp
    queue_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def validate_review_stamp(data: dict[str, Any]) -> None:
    stamp = data.get("review") if isinstance(data.get("review"), dict) else None
    if not stamp or not stamp.get("stamp_hash"):
        raise ValueError("missing approval review stamp")
    image = _image_path(data)
    if not image.exists():
        raise ValueError("review stamp image is missing")
    image_sha = _sha256_file(image)
    if image_sha != stamp.get("image_sha256"):
        raise ValueError("review stamp image hash mismatch")
    expected = review_hash(data, image_sha)
    if expected != stamp.get("stamp_hash"):
        raise ValueError("review stamp no longer matches queue content")


def effective_lane(data: dict[str, Any]) -> str:
    lane = str(data.get("lane") or "").strip().casefold()
    if lane == "news":
        return "news"
    if lane == "radar":
        return "radar"
    if lane:
        raise ValueError(f"unsupported queue lane: {lane}")
    source_raw = data.get("source")
    source = source_raw if isinstance(source_raw, dict) else {}
    source_url = str(source.get("url") or "")
    if urllib.parse.urlsplit(source_url).hostname == PRODUCT_REFERENCE_HOST and not data.get("news"):
        return "radar"
    raise ValueError("queue lane is missing or unsupported")


def validate_reader_cta_destination(comment: str) -> None:
    """Reject Radar homepage links masquerading as filtered deep links."""
    for raw_url in re.findall(r"https?://[^\s<>()]+", comment):
        parsed = urllib.parse.urlsplit(raw_url.rstrip(".,;"))
        host = (parsed.hostname or "").casefold()
        if (host == PRODUCT_REFERENCE_HOST or host.endswith("." + PRODUCT_REFERENCE_HOST)) and parsed.path in {"", "/"}:
            raise ValueError("Radar CTA points to the homepage; use a matching article or stable feature route")


def validate_publishable_reviewed_queue(data: dict[str, Any], *, lane: str) -> None:
    if data.get("schema") != QUEUE_SCHEMA:
        raise ValueError(f"unsupported queue schema: {data.get('schema')}")
    status = str(data.get("status") or "")
    if status not in {"queued", "ready"}:
        raise ValueError(f"queue status is blocked from publishing: {status}")
    target = data.get("target") if isinstance(data.get("target"), dict) else {}
    if target.get("platform") != "facebook" or target.get("surface") != "page":
        raise ValueError("queue target must be the Facebook Page")
    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    self_comment = str(content.get("self_comment") or "")
    validate_reader_cta_destination(self_comment)
    if lane == "radar":
        if content.get("generated_by") != "rb_social_editorial":
            raise ValueError("radar queue must be generated_by=rb_social_editorial")
        if "radarbds.vn" not in self_comment:
            raise ValueError("radar queue missing Radar BDS self-comment link")


def validate_news_queue_freshness(data: dict[str, Any], *, now: dt.datetime) -> None:
    news = data.get("news") if isinstance(data.get("news"), dict) else {}
    sources = news.get("sources") if isinstance(news.get("sources"), list) else []
    if not sources:
        raise ValueError("news queue missing sources")
    lead_id = news.get("lead_source_id")
    lead = next((s for s in sources if s.get("id") == lead_id), sources[0])
    fetched = parse_dt(lead.get("fetched_at"), field="lead.fetched_at")
    published = parse_source_date(lead.get("published_at"), field="lead.published_at")
    if now - fetched > dt.timedelta(hours=24):
        raise ValueError("lead source is older than 24h")
    if _local_day(now) - published > dt.timedelta(days=7):
        raise ValueError("lead source is older than 7d")


def validate_radar_queue_freshness(data: dict[str, Any], *, now: dt.datetime) -> None:
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    validate_radar_url(str(source.get("url") or ""))
    if source.get("http_status") != 200:
        raise ValueError("radar queue source is not verified HTTP 200")
    article_date = parse_source_date(source.get("article_date"), field="source.article_date")
    age = _local_day(now) - article_date
    if age < dt.timedelta(0):
        raise ValueError("radar source article_date is in the future")
    if age > dt.timedelta(days=7):
        raise ValueError("radar source is older than 7d")


def validate_queue_freshness(data: dict[str, Any], *, now: dt.datetime, lane: str | None = None) -> None:
    lane = lane or effective_lane(data)
    if lane == "news":
        validate_news_queue_freshness(data, now=now)
    elif lane == "radar":
        validate_radar_queue_freshness(data, now=now)
    else:
        raise ValueError(f"unsupported queue lane: {lane}")


def _publish_dispatch_queue(queue_path: Path, data: dict[str, Any], *, lane: str, source_http_ok: bool = False) -> Path:
    dispatch = json.loads(json.dumps(data))
    dispatch["lane"] = lane
    target = dict(dispatch.get("target") or {})
    target["mode"] = "publish"
    target["requires_review"] = False
    dispatch["target"] = target
    if source_http_ok:
        source = dict(dispatch.get("source") or {})
        source["http_status"] = 200
        dispatch["source"] = source
    out = queue_path.with_name(f"{queue_path.stem}-publish{queue_path.suffix}")
    out.write_text(json.dumps(dispatch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def verify_lead_source_http(data: dict[str, Any], *, timeout: int = 10) -> bool:
    source_url = str((data.get("source") or {}).get("url") or "")
    if not source_url:
        raise SystemExit("news queue missing lead source URL")
    req = urllib.request.Request(source_url, method="HEAD", headers={"User-Agent": "RadarBDS-NewsWorkflow/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - explicit trusted source URL validation already done
            final_url = resp.geturl()
            status = resp.status
    except Exception:
        req = urllib.request.Request(source_url, method="GET", headers={"User-Agent": "RadarBDS-NewsWorkflow/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            final_url = resp.geturl()
            status = resp.status
    if status >= 400:
        raise SystemExit(f"lead source returned HTTP {status}")
    if _host(final_url) != _host(source_url):
        raise SystemExit(f"lead source canonical host changed: {final_url}")
    return True


def queue_key(data: dict[str, Any]) -> tuple[str, str, str]:
    source = data.get("source") or {}
    slug = str(source.get("slug") or "news")
    article_date = str(source.get("article_date") or "unknown-date")
    return f"{slug}:{article_date}", slug, str(source.get("url") or "")


def _write_marker(marker: Path, payload: dict[str, Any]) -> None:
    marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _lock_handle(lock_path: Path):
    """Open a writable lock handle, degrading to a private temp file if the
    shared queue dir is not writable by the current process user.

    The lock still guarantees mutual exclusion for this user's publisher; it
    never silently skips locking.
    """
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        return lock_path.open("w", encoding="utf-8")
    except OSError:
        fallback = Path(tempfile.gettempdir()) / f"{lock_path.name}.{os.getuid()}"
        return fallback.open("w", encoding="utf-8")


def publish_queue(queue_path: Path, *, now: dt.datetime | None = None, lock_path: Path | None = None, manual_authorization: str = "") -> dict[str, Any]:
    now = now or now_local()
    lock_path = lock_path or DEFAULT_LOCK
    with _lock_handle(lock_path) as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        data = load_json(queue_path)
        lane = effective_lane(data)
        validate_review_stamp(data)
        validate_publishable_reviewed_queue(data, lane=lane)
        validate_queue_freshness(data, now=now, lane=lane)
        state = radar_auto.load_state()
        posted = state.setdefault("posted", {})
        already, item = radar_auto.posted_today(posted, today=now.astimezone().date())
        if manual_authorization and (data.get("manual_authorization") or {}).get("request") != manual_authorization:
            raise SystemExit("manual authorization must match this queue's recorded user request")
        if already and not manual_authorization:
            post_url = (item or {}).get("post_url") or (((item or {}).get("browser_result") or {}).get("permalink"))
            raise SystemExit(f"already posted today: {post_url}")
        key, slug, url = queue_key(data)
        if key in posted and posted[key].get("posted_at"):
            raise SystemExit(f"queue already published: {key}")
        marker = queue_path.with_suffix(".in-flight.json")
        if marker.exists():
            raise SystemExit(f"in-flight marker exists; manual reconciliation required: {marker}")
        source_http_ok = False
        if lane == "news":
            verify_lead_source_http(data)
            source_http_ok = True
        dispatch_path = _publish_dispatch_queue(queue_path, data, lane=lane, source_http_ok=source_http_ok)
        _write_marker(marker, {"status": "in_flight", "queue": str(queue_path), "started_at": now.isoformat(timespec="seconds"), "key": key})
        try:
            result = radar_auto.publish(dispatch_path)
        except BaseException as exc:
            _write_marker(
                marker,
                {
                    "status": "requires_reconciliation",
                    "queue": str(queue_path),
                    "dispatch_queue": str(dispatch_path),
                    "failed_at": now_local().isoformat(timespec="seconds"),
                    "key": key,
                    "error": str(exc),
                },
            )
            raise SystemExit(f"publish ambiguous; fail-closed marker requires reconciliation before retry: {marker}") from exc
        browser_result = result.get("browser_result") or {}
        content = data.get("content") or {}
        news = data.get("news") or {}
        content_editorial = content.get("editorial") if isinstance(content.get("editorial"), dict) else {}
        top_editorial = data.get("editorial") if isinstance(data.get("editorial"), dict) else {}
        metadata = top_editorial.get("metadata") if isinstance(top_editorial.get("metadata"), dict) else {}
        posted[key] = {
            "slug": slug,
            "url": url,
            "queue": str(queue_path),
            "style": content.get("style"),
            "visual_style": content.get("visual_style"),
            "editorial_pillar": "news_explainer" if lane == "news" else (content_editorial.get("pillar") or metadata.get("pillar")),
            "editorial_topic": news.get("topic_key") if lane == "news" else (content_editorial.get("topic") or metadata.get("topic")),
            "posted_at": now.astimezone(LOCAL_TZ).isoformat(timespec="seconds"),
            "post_url": result.get("post_url"),
            "photo_url": browser_result.get("photo_permalink"),
            "verified_text": bool(browser_result.get("verified_text")),
            "verified_visual": bool(browser_result.get("verified_visual")),
            "verified_comment": bool(browser_result.get("verified_comment")),
            "comment_needle": browser_result.get("comment_needle"),
            "screenshot": result.get("screenshot"),
            "browser_result": browser_result,
            "result": result,
            "lane": lane,
            "news_source_urls": news.get("source_urls") or (data.get("source") or {}).get("news_source_urls") or [],
            "news_topic_key": news.get("topic_key"),
            "news_event_fingerprint": news.get("event_fingerprint"),
            "manual_authorization": data.get("manual_authorization") if manual_authorization else None,
        }
        radar_auto.save_state(state)
        try:
            marker.unlink()
        except FileNotFoundError:
            pass
        try:
            dispatch_path.unlink()
        except FileNotFoundError:
            pass
        return result


def plan(report_path: Path) -> None:
    report = load_json(report_path)
    state = radar_auto.load_state()
    posted = state.setdefault("posted", {})
    already, _ = radar_auto.posted_today(posted)
    print(f"recommended_lane: {recommended_lane(posted)}")
    print(f"already_today: {str(bool(already)).lower()}")
    print("eligible_source_candidates:")
    for candidate in report.get("candidates") or []:
        if candidate.get("eligible") is True and candidate.get("classification") == "news_candidate":
            print(
                f"- {candidate.get('id')} · {candidate.get('publisher')} · {candidate.get('published_at')} · "
                f"score={candidate.get('score')} · {candidate.get('title')}"
            )
    rows = radar_auto.editorial_candidates(posted)
    slugs = [str(row.get("slug")) for row in rows if isinstance(row, dict) and row.get("slug")]
    print("editorial_candidates: " + (", ".join(slugs) if slugs else "none"))


def prepare_radar(slug: str) -> Path:
    return radar_auto.create_queue(slug, preview=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Radar BDS reviewed Page news workflow")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="Print lane and candidate plan; no browser/images/publishing")
    p_plan.add_argument("--report", required=True, type=Path)

    p_news = sub.add_parser("prepare-news", help="Create reviewed-news queue then run Gemini image upgrade")
    p_news.add_argument("--report", required=True, type=Path)
    p_news.add_argument("--draft", required=True, type=Path)
    p_news.add_argument("--out-dir", required=True, type=Path)

    p_radar = sub.add_parser("prepare-radar", help="Create normal Radar review queue via existing adapter")
    p_radar.add_argument("--slug", default="latest")

    p_approve = sub.add_parser("approve", help="Stamp queue after caption/source/visual QA")
    p_approve.add_argument("--queue", required=True, type=Path)
    p_approve.add_argument("--note", required=True)

    p_publish = sub.add_parser("publish", help="Publish an approved queue fail-closed")
    p_publish.add_argument("--queue", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.command == "plan":
        plan(args.report)
        return 0
    if args.command == "prepare-news":
        print(prepare_news(args.report, args.draft, args.out_dir))
        return 0
    if args.command == "prepare-radar":
        print(prepare_radar(args.slug))
        return 0
    if args.command == "approve":
        data = approve_queue(args.queue, note=args.note)
        print(json.dumps({"queue": str(args.queue), "stamp_hash": data["review"]["stamp_hash"], "approved_at": data["review"]["approved_at"]}, ensure_ascii=False))
        return 0
    if args.command == "publish":
        result = publish_queue(args.queue)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
