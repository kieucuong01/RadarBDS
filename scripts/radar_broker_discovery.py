#!/usr/bin/env python3
"""Config-driven Facebook broker discovery scoring for Radar BDS.

This MVP does not scrape Facebook by itself. It scores already-collected public
post metadata from browser-use/manual review and outputs broker candidates for
human approval before any broker is added to production crawl config.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "config" / "broker_discovery_targets.json"
DEFAULT_VAR_DIR = Path("/opt/radar-bds/var/broker_discovery")
DOCUMENT_LABELS = {"title_book_or_document", "cadastral_map", "map_screenshot", "document_photo"}
REAL_IMAGE_LABELS = {"real_property_photo", "street_photo", "construction_photo"}
HYPE_WORDS = [
    "siêu phẩm",
    "cơ hội vàng",
    "bao lời",
    "cam kết lời",
    "lời chắc",
    "sốt đất",
    "hot nhất",
    "rẻ nhất",
]
PRICE_RE = re.compile(r"(?:giá|gia)\s*[:\-]?\s*(\d+(?:[\.,]\d+)?)\s*(?:tỷ|ty|tỉ|ti|tr|triệu|trieu|m|mỷ)", re.I)
AREA_RE = re.compile(r"(\d+(?:[\.,]\d+)?)\s*(?:m2|m²|m\^2|met|mét|m )", re.I)
PHONE_RE = re.compile(r"(?:\+?84|0)(?:[\s.\-]?\d){8,10}")


def _plain(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_text(value: Any) -> str:
    text = _plain(value).lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()




def normalize_broker_profile_url(url: str | None) -> str:
    """Return the plain Facebook profile/page URL to open for deep scans.

    Facebook group member links look like /groups/<group_id>/user/<user_id>;
    opening those can keep the browser inside the group context. For profile
    checks, always go directly to https://www.facebook.com/<username-or-id>.
    """
    raw = _plain(url)
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    if not raw.startswith(("http://", "https://")):
        raw = "https://www.facebook.com/" + raw.lstrip("/")
    parsed = urlparse(raw)
    host = parsed.netloc or "www.facebook.com"
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 3 and parts[0] == "groups" and parts[2] == "user":
        return f"https://www.facebook.com/{parts[3] if len(parts) > 3 else parts[-1]}"
    if parts and parts[0] == "profile.php":
        # profile.php?id=<id> cannot be recovered without query parsing here; keep
        # base URL so callers can mark it insufficient if no id is available.
        return "https://www.facebook.com/profile.php"
    if parts:
        return f"https://{host}/{parts[0]}"
    return f"https://{host}"

def load_target_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != "radar_broker_discovery_targets.v1":
        raise ValueError(f"Unsupported broker discovery target schema: {payload.get('schema')}")
    areas = payload.get("target_areas")
    if not isinstance(areas, list) or not areas:
        raise ValueError("target_areas must be a non-empty list")
    return payload


def _aliases_for(value: str, aliases: list[str] | None = None) -> set[str]:
    items = {value, *(aliases or [])}
    return {normalize_text(item) for item in items if normalize_text(item)}


def iter_target_wards(config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for area in config.get("target_areas", []):
        city = _plain(area.get("city"))
        city_aliases = _aliases_for(city, area.get("aliases") or [])
        for ward in area.get("priority_wards", []):
            if isinstance(ward, str):
                ward_name = ward
                ward_aliases: list[str] = []
            else:
                ward_name = _plain(ward.get("name"))
                ward_aliases = ward.get("aliases") or []
            rows.append(
                {
                    "city": city,
                    "city_aliases": city_aliases,
                    "ward": ward_name,
                    "ward_aliases": _aliases_for(ward_name, ward_aliases),
                }
            )
    return rows


def match_target_area(text: str, config: dict[str, Any]) -> dict[str, Any]:
    haystack = normalize_text(text)
    best: dict[str, Any] | None = None
    for row in iter_target_wards(config):
        ward_hit = any(re.search(rf"\b{re.escape(alias)}\b", haystack) for alias in row["ward_aliases"])
        city_hit = any(re.search(rf"\b{re.escape(alias)}\b", haystack) for alias in row["city_aliases"])
        score = int(ward_hit) * 2 + int(city_hit)
        if score and (best is None or score > best["match_score"]):
            best = {
                "city": row["city"],
                "ward": row["ward"] if ward_hit else None,
                "target_hit": True,
                "match_score": score,
            }
    if best:
        return best
    return {"city": None, "ward": None, "target_hit": False, "match_score": 0}


def _has_price(text: str) -> bool:
    norm = normalize_text(text)
    # User rule for broker scoring:
    # - Missing tens of millions is acceptable: "1t5xx", "1 tỷ 5xx".
    # - Missing hundreds of millions is incomplete: "1 tỷ x", "1tx", "hơn 1 tỷ".
    vague_hundreds_patterns = [
        r"\bhon\s+\d+(?:[\.,]\d+)?\s*(?:ty|ti)\b",
        r"\b\d+(?:[\.,]\d+)?\s*(?:ty|ti)\s*x+\b",
        r"\b\d+t(?:y)?x+\b",
    ]
    if any(re.search(pattern, norm) for pattern in vague_hundreds_patterns):
        return False

    acceptable_tens_missing_patterns = [
        r"\b\d+(?:t|ty|ti)\d+(?:x{1,2})?\b",
        r"\b\d+\s*(?:ty|ti)\s+\d+(?:x{1,2})?\b",
    ]
    if any(re.search(pattern, norm) for pattern in acceptable_tens_missing_patterns):
        return True

    return bool(PRICE_RE.search(text) or re.search(r"\b\d+(?:[\.,]\d+)?\s*(?:ty|ti|trieu|tr)\b", norm))


def _has_area(text: str) -> bool:
    return bool(AREA_RE.search(text))


def _property_type(text: str) -> str | None:
    norm = normalize_text(text)
    if re.search(r"\b(dat nen|ban dat|lo dat|nen)\b", norm):
        return "đất nền"
    if re.search(r"\b(nha dat|nha pho|can nha|ban nha)\b", norm):
        return "nhà đất"
    if re.search(r"\b(nha tro|phong tro|day tro)\b", norm):
        return "nhà trọ"
    if re.search(r"\b(kho|xuong|nha xuong)\b", norm):
        return "kho xưởng"
    return None


def _has_legal_text(text: str) -> bool:
    norm = normalize_text(text)
    return bool(re.search(r"\b(so rieng|so hong|so do|tho cu|cong chung|phap ly|quy hoach|trich luc)\b", norm))


def _has_location_detail(text: str) -> bool:
    norm = normalize_text(text)
    return bool(re.search(r"\b(duong|mat tien|hem|kdc|khu dan cu|lo gioi|ngang|dai|huong|gan)\b", norm))


def _is_share_or_repost(text: str) -> bool:
    norm = normalize_text(text)
    return bool(
        re.search(r"\b(shared a post|shared .* post|reposted|shared)\b", str(text or ""), re.I)
        or re.search(r"\b(da chia se|chia se bai viet|da share|share bai|shared)\b", norm)
    )


def _listing_fingerprint(post: dict[str, Any]) -> str:
    text = normalize_text(post.get("text"))
    # Drop common Facebook UI words and volatile counts. Keep listing content.
    text = re.sub(r"\b(follow|join|see more|xem them|see translation|xem ban dich|like|comment|share)\b", " ", text)
    text = re.sub(r"\b\d+\s*(?:comments?|binh luan|shares?|luot chia se|likes?)\b", " ", text)
    text = re.sub(r"\b\d{1,2}\s*(?:hours?|gio|days?|ngay|minutes?|phut)\s*ago\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:320]


def unique_original_listing_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return unique, non-share listing posts from noisy Facebook DOM blocks."""
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for post in posts:
        extract = post.get("extract", {})
        if extract.get("share_or_repost_present") or _is_share_or_repost(_plain(post.get("text"))):
            continue
        fingerprint = _listing_fingerprint(post)
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(post)
    return unique


def extract_post_features(post: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    text = _plain(post.get("text"))
    labels = {normalize_text(label).replace(" ", "_") for label in (post.get("image_labels") or [])}
    prop_type = _property_type(text)
    return {
        "price_present": _has_price(text),
        "area_present": _has_area(text),
        "property_type": prop_type,
        "property_type_present": prop_type is not None,
        "location_detail_present": _has_location_detail(text),
        "phone_present": bool(PHONE_RE.search(text)),
        "legal_text_present": _has_legal_text(text),
        "real_image_present": bool(labels & REAL_IMAGE_LABELS),
        "document_image_present": bool(labels & DOCUMENT_LABELS),
        "hype_hits": [word for word in HYPE_WORDS if normalize_text(word) in normalize_text(text)],
        "share_or_repost_present": _is_share_or_repost(text),
        "area_match": match_target_area(text, config),
    }


def score_post(post: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    features = extract_post_features(post, config)
    area = features["area_match"]
    score = 0
    breakdown: dict[str, int] = {}

    def add(name: str, points: int, condition: bool) -> None:
        nonlocal score
        gained = points if condition else 0
        breakdown[name] = gained
        score += gained

    add("price", 15, features["price_present"])
    add("area", 12, features["area_present"])
    add("target_ward_or_city", 15, area["target_hit"])
    add("property_type", 8, features["property_type_present"])
    add("price_per_m2_possible", 8, features["price_present"] and features["area_present"])
    add("location_detail", 8, features["location_detail_present"])
    add("real_image", 8, features["real_image_present"])
    add("document_image", 10, features["document_image_present"] or features["legal_text_present"])
    add("target_priority", 10, area["target_hit"])
    add("contact", 4, features["phone_present"])
    add("not_empty", 2, len(_plain(post.get("text"))) >= 40)

    penalty = 0
    norm = normalize_text(post.get("text"))
    if "inbox" in norm and not features["price_present"]:
        penalty += 12
    if features["hype_hits"]:
        penalty += min(20, 5 * len(features["hype_hits"]))
    if not features["area_present"] and not features["price_present"]:
        penalty += 10
    score = max(0, min(100, score - penalty))

    result = dict(post)
    result.update(
        {
            "score": score,
            "score_breakdown": breakdown,
            "penalty_score": penalty,
            "extract": {k: v for k, v in features.items() if k != "area_match"},
            "area_match": area,
            "requires_manual_review": features["document_image_present"],
        }
    )
    return result


def _parse_date(value: Any) -> dt.date | None:
    if not value:
        return None
    text = str(value)
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return dt.date.fromisoformat(text[:10])
        except ValueError:
            return None


def _rate(total: int, count: int) -> float:
    return round(count / total, 4) if total else 0.0


def _tier(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def score_brokers(scored_posts: list[dict[str, Any]], config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    del config  # config is intentionally accepted for CLI/API symmetry.
    by_author: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for post in scored_posts:
        raw_author_url = _plain(post.get("author_url") or post.get("profile_url") or post.get("author_name") or "unknown")
        author_url = normalize_broker_profile_url(raw_author_url) or raw_author_url
        normalized_post = dict(post)
        normalized_post["author_url"] = author_url
        if raw_author_url != author_url:
            normalized_post["source_author_url"] = raw_author_url
        by_author[author_url].append(normalized_post)

    brokers: list[dict[str, Any]] = []
    for author_url, posts in by_author.items():
        total = len(posts)
        price_count = sum(1 for p in posts if p.get("extract", {}).get("price_present"))
        area_count = sum(1 for p in posts if p.get("extract", {}).get("area_present"))
        ward_count = sum(1 for p in posts if p.get("area_match", {}).get("ward"))
        type_count = sum(1 for p in posts if p.get("extract", {}).get("property_type_present"))
        document_count = sum(1 for p in posts if p.get("extract", {}).get("document_image_present"))
        target_posts = [p for p in posts if p.get("area_match", {}).get("target_hit")]
        city_counter = Counter(p.get("area_match", {}).get("city") for p in target_posts if p.get("area_match", {}).get("city"))
        ward_counter = Counter(p.get("area_match", {}).get("ward") for p in target_posts if p.get("area_match", {}).get("ward"))
        dates = sorted({d for d in (_parse_date(p.get("posted_at")) for p in posts) if d})
        weeks_active = len({d.isocalendar()[:2] for d in dates})
        median_post_score = statistics.median([float(p.get("score", 0)) for p in posts]) if posts else 0.0
        target_fit_ratio = _rate(total, len(target_posts))
        main_city_ratio = _rate(len(target_posts), city_counter.most_common(1)[0][1] if city_counter else 0)

        completeness = (_rate(total, price_count) + _rate(total, area_count) + _rate(total, ward_count) + _rate(total, type_count)) / 4
        cadence_score = min(1.0, weeks_active / 4) if total else 0
        duplicate_penalty = 0.0
        texts = [normalize_text(p.get("text")) for p in posts]
        if total >= 3:
            duplicate_penalty = 1 - (len(set(texts)) / total)

        final_score = (
            0.40 * median_post_score
            + 20 * target_fit_ratio
            + 15 * completeness
            + 10 * min(1.0, document_count / max(1, total))
            + 10 * cadence_score
            + 5 * main_city_ratio
            - 15 * duplicate_penalty
        )
        final_score = round(max(0, min(100, final_score)), 1)
        labels: list[str] = []
        if target_fit_ratio >= 0.6:
            labels.append("target_area_specialist")
        if completeness >= 0.7:
            labels.append("data_rich_poster")
        if document_count:
            labels.append("document_signal_poster")
        if duplicate_penalty >= 0.4:
            labels.append("high_duplicate_risk")
        if final_score >= 55 or document_count:
            labels.append("needs_manual_review")

        brokers.append(
            {
                "broker_name": _plain(posts[0].get("author_name") or posts[0].get("broker_name") or author_url),
                "broker_url": author_url,
                "final_score": final_score,
                "tier": _tier(final_score),
                "labels": labels,
                "area_focus": {
                    "primary_city": city_counter.most_common(1)[0][0] if city_counter else None,
                    "top_wards": [ward for ward, _ in ward_counter.most_common(5)],
                    "target_fit_ratio": target_fit_ratio,
                    "main_city_ratio": main_city_ratio,
                },
                "metrics": {
                    "posts_sampled": total,
                    "target_posts": len(target_posts),
                    "median_post_quality_score": round(float(median_post_score), 1),
                    "price_present_rate": _rate(total, price_count),
                    "area_present_rate": _rate(total, area_count),
                    "ward_present_rate": _rate(total, ward_count),
                    "property_type_present_rate": _rate(total, type_count),
                    "document_image_posts": document_count,
                    "target_fit_ratio": target_fit_ratio,
                    "main_city_ratio": main_city_ratio,
                    "duplicate_rate": round(duplicate_penalty, 4),
                    "weeks_active_60d": weeks_active,
                },
                "sample_post_urls": [p.get("post_url") for p in posts if p.get("post_url")][:5],
                "status": "candidate" if final_score >= 55 else "low_priority",
            }
        )
    return sorted(brokers, key=lambda item: (item["final_score"], item["metrics"]["target_posts"]), reverse=True)


def render_markdown_report(brokers: list[dict[str, Any]], campaign_name: str = "broker_discovery") -> str:
    now = dt.datetime.now(dt.timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    lines = [f"# Radar BDS Broker Discovery — {campaign_name}", "", f"Generated: {now}", ""]
    if not brokers:
        lines += ["Không có broker candidate nào trong input hiện tại."]
        return "\n".join(lines).strip() + "\n"

    city_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for broker in brokers:
        city = broker.get("area_focus", {}).get("primary_city") or "Chưa rõ khu vực"
        city_groups[city].append(broker)

    for city, items in sorted(city_groups.items()):
        lines += [f"## {city}", "", "| Tier | Score | Broker | Wards | Data rates | Labels |", "|---|---:|---|---|---|---|"]
        for item in sorted(items, key=lambda x: x.get("final_score", 0), reverse=True):
            metrics = item.get("metrics", {})
            wards = ", ".join(item.get("area_focus", {}).get("top_wards") or ["-"])
            rates = f"giá {metrics.get('price_present_rate', 0):.0%}, DT {metrics.get('area_present_rate', 0):.0%}, phường {metrics.get('ward_present_rate', 0):.0%}"
            labels = ", ".join(item.get("labels") or []) or "-"
            lines.append(
                f"| {item.get('tier')} | {item.get('final_score')} | [{item.get('broker_name')}]({item.get('broker_url')}) | {wards} | {rates} | {labels} |"
            )
        lines.append("")
    lines += [
        "## Cách dùng",
        "",
        "- Tier A/B: đưa vào manual review và cân nhắc outreach.",
        "- `document_signal_poster`: có ảnh giấy tờ/sơ đồ — chỉ dùng làm tín hiệu nội bộ, không kết luận pháp lý.",
        "- Broker chỉ thành `approved` sau khi anh/em duyệt thủ công.",
    ]
    return "\n".join(lines).strip() + "\n"


def score_posts(posts: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    return [score_post(post, config) for post in posts]


def default_config() -> dict[str, Any]:
    return {
        "schema": "radar_broker_discovery_targets.v1",
        "campaign_name": "current_priority",
        "notes": "Current areas are campaign config, not hardcoded logic. Add Dĩ An/Thuận An/Tân Uyên here when needed.",
        "target_areas": [
            {
                "city": "Thủ Dầu Một",
                "aliases": ["TDM", "Thu Dau Mot", "Thủ Dầu Một"],
                "priority_wards": [
                    {"name": "Hòa Phú", "aliases": ["Hoa Phu", "Hoà Phú", "TP mới Bình Dương", "Thành phố mới"]},
                    {"name": "Phú Cường", "aliases": ["Phu Cuong", "Phú Cường", "trung tâm Thủ Dầu Một"]},
                ],
            },
            {
                "city": "Bến Cát",
                "aliases": ["Ben Cat", "Bến Cát"],
                "priority_wards": [
                    {"name": "Mỹ Phước", "aliases": ["My Phuoc", "Mỹ Phước", "MP1", "MP2", "MP3", "MP4"]},
                    {"name": "Tân Định", "aliases": ["Tan Dinh", "Tân Định"]},
                    {"name": "An Điền", "aliases": ["An Dien", "An Điền"]},
                    {"name": "An Tây", "aliases": ["An Tay", "An Tây"]},
                    {"name": "Thới Hòa", "aliases": ["Thoi Hoa", "Thới Hòa"]},
                    {"name": "Hòa Lợi", "aliases": ["Hoa Loi", "Hoà Lợi", "Hòa Lợi"]},
                    {"name": "Phú An", "aliases": ["Phu An", "Phú An"]},
                    {"name": "Chánh Phú Hòa", "aliases": ["Chanh Phu Hoa", "Chánh Phú Hòa"]},
                ],
            },
        ],
    }


def _read_posts(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("posts"), list):
        return payload["posts"]
    raise ValueError("Posts file must be a JSON array or {'posts': [...]} object")


def cmd_init_config(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists() and not args.force:
        raise SystemExit(f"Config exists, use --force to overwrite: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(default_config(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0


def cmd_keywords(args: argparse.Namespace) -> int:
    config = load_target_config(args.config)
    for area in config.get("target_areas", []):
        city = area["city"]
        print(f"# {city}")
        print(f"mua bán nhà đất {city}")
        print(f"bất động sản {city}")
        for ward in area.get("priority_wards", []):
            name = ward if isinstance(ward, str) else ward.get("name")
            print(f"nhà đất {name} {city}")
            print(f"đất {name} {city}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    config = load_target_config(args.config)
    posts = _read_posts(Path(args.posts))
    scored = score_posts(posts, config)
    brokers = score_brokers(scored, config)
    payload = {
        "schema": "radar_broker_discovery_scores.v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "campaign_name": config.get("campaign_name") or Path(args.config).stem,
        "post_count": len(scored),
        "broker_count": len(brokers),
        "posts": scored,
        "brokers": brokers,
    }
    out = Path(args.out) if args.out else DEFAULT_VAR_DIR / f"broker_scores-{dt.date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0



def brokers_from_score_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("brokers"), list):
        return payload["brokers"]
    return []

def cmd_report(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.scores).read_text(encoding="utf-8"))
    brokers = brokers_from_score_payload(payload)
    report = render_markdown_report(brokers, payload.get("campaign_name") or Path(args.scores).stem)
    if args.out:
        out = Path(args.out)
    else:
        out = DEFAULT_VAR_DIR / f"broker-report-{dt.date.today().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(out)
    print(report)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Config-driven broker discovery scoring for Radar BDS")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init-config", help="write default target config")
    init.add_argument("--out", default=str(DEFAULT_CONFIG))
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init_config)

    keywords = sub.add_parser("keywords", help="print Facebook group search keywords from target config")
    keywords.add_argument("--config", default=str(DEFAULT_CONFIG))
    keywords.set_defaults(func=cmd_keywords)

    score = sub.add_parser("score", help="score collected public Facebook posts")
    score.add_argument("--config", default=str(DEFAULT_CONFIG))
    score.add_argument("--posts", required=True, help="JSON array or {'posts': [...]} collected posts")
    score.add_argument("--out")
    score.set_defaults(func=cmd_score)

    report = sub.add_parser("report", help="render markdown report from score JSON")
    report.add_argument("--scores", required=True)
    report.add_argument("--out")
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
