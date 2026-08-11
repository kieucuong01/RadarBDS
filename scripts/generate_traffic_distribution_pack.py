"""Generate deterministic, review-only traffic distribution assets."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.traffic_priority import active_traffic_priority_pages


PUBLIC_ORIGIN = "https://radarbds.vn"
CHANNELS = ("facebook", "broker", "local_media", "community")
CHANNEL_META = {
    "facebook": {"source": "facebook", "medium": "social"},
    "broker": {"source": "broker", "medium": "outreach"},
    "local_media": {"source": "local_media", "medium": "outreach"},
    "community": {"source": "community", "medium": "referral"},
}
CHANNEL_HEADINGS = {
    "facebook": "Facebook",
    "broker": "Broker",
    "local_media": "Local media",
    "community": "Community",
}
UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
REQUIRED_ITEM_KEYS = (
    "queue_id",
    "path",
    "canonical_url",
    "utm_url",
    "channel",
    "angle",
    "copy",
    "status",
)
RESTRICTED_HOSTS = ("facebook.com", "guland.vn", "batdongsan.com.vn")
RESTRICTED_PATH_PREFIXES = ("/admin", "/auth", "/api/admin")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?84|0)\d{8,10}(?!\d)")
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_") or "item"


def _canonical_url(path: str) -> str:
    return f"{PUBLIC_ORIGIN}{path if path != '/' else '/'}"


def _utm_url(
    path: str,
    *,
    source: str,
    medium: str,
    campaign: str,
    content: str,
) -> str:
    query = urlencode(
        (
            ("utm_source", _slugify(source)),
            ("utm_medium", _slugify(medium)),
            ("utm_campaign", _slugify(campaign)),
            ("utm_content", _slugify(content)),
        )
    )
    return f"{_canonical_url(path)}?{query}"


def _queue_id(path: str, channel: str, campaign: str, content: str) -> str:
    payload = f"{path}|{channel}|{campaign}|{content}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_distribution_item(item: dict[str, str]) -> None:
    if tuple(item) != REQUIRED_ITEM_KEYS:
        raise ValueError("distribution item keys or ordering are invalid")
    if item["status"] != "review_required":
        raise ValueError("distribution items must remain review_required")
    if item["channel"] not in CHANNELS:
        raise ValueError("unsupported distribution channel")

    joined = "\n".join(str(value) for value in item.values())
    if PHONE_PATTERN.search(joined) or EMAIL_PATTERN.search(joined):
        raise ValueError("distribution item contains personal contact data")
    if any(host in joined.casefold() for host in RESTRICTED_HOSTS):
        raise ValueError("distribution item contains a non-public source URL")

    canonical = urlsplit(item["canonical_url"])
    tracked = urlsplit(item["utm_url"])
    expected_path = str(item["path"] or "")
    for parsed in (canonical, tracked):
        if f"{parsed.scheme}://{parsed.netloc}" != PUBLIC_ORIGIN:
            raise ValueError("distribution URLs must use the public Radar BDS origin")
        if parsed.path != expected_path or parsed.fragment:
            raise ValueError("distribution URLs must retain the canonical priority path")
        if any(parsed.path.startswith(prefix) for prefix in RESTRICTED_PATH_PREFIXES):
            raise ValueError("restricted path in distribution item")
    if canonical.query:
        raise ValueError("canonical_url must not contain tracking parameters")

    pairs = parse_qsl(tracked.query, keep_blank_values=True)
    if tuple(key for key, _value in pairs) != UTM_KEYS:
        raise ValueError("utm_url must contain only the ordered UTM allowlist")
    for _key, value in pairs:
        if not value or not value.isascii() or value != value.casefold():
            raise ValueError("UTM values must be non-empty lowercase ASCII")
        if any(not (character.isalnum() or character == "_") for character in value):
            raise ValueError("UTM values must use lowercase slug characters")


def build_distribution_items(
    run_date: date,
    channel: str,
) -> tuple[dict[str, str], ...]:
    if channel != "all" and channel not in CHANNELS:
        raise ValueError("channel must be facebook, broker, local_media, community, or all")
    selected_channels = CHANNELS if channel == "all" else (channel,)
    campaign = f"traffic_p1_p3_{run_date:%Y%m%d}"
    items: list[dict[str, str]] = []

    for selected_channel in selected_channels:
        meta = CHANNEL_META[selected_channel]
        for index, entry in enumerate(active_traffic_priority_pages(), start=1):
            content = _slugify(f"{entry.cluster}_{entry.buyer_stage}_{index:02d}")
            tracked_url = _utm_url(
                entry.path,
                source=meta["source"],
                medium=meta["medium"],
                campaign=campaign,
                content=content,
            )
            item = {
                "queue_id": _queue_id(entry.path, selected_channel, campaign, content),
                "path": entry.path,
                "canonical_url": _canonical_url(entry.path),
                "utm_url": tracked_url,
                "channel": selected_channel,
                "angle": entry.distribution_angle,
                "copy": (
                    f"{entry.distribution_angle} Xem phạm vi, nguồn và giới hạn tại "
                    f"{tracked_url}. Giá rao là dữ liệu tham khảo; cần kiểm tra thực địa, "
                    "quy hoạch và pháp lý trước khi quyết định."
                ),
                "status": "review_required",
            }
            validate_distribution_item(item)
            items.append(item)
    return tuple(items)


def _load_existing_items(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    original = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(original)
    except json.JSONDecodeError as exc:
        raise ValueError("existing distribution JSON is malformed") from exc
    raw_items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        raise ValueError("existing distribution JSON has no items list")
    existing: list[dict[str, str]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ValueError("existing distribution JSON contains a non-object item")
        item = {key: str(raw.get(key) or "") for key in REQUIRED_ITEM_KEYS}
        validate_distribution_item(item)
        existing.append(item)
    return existing


def _deduplicate_items(
    existing: list[dict[str, str]],
    incoming: tuple[dict[str, str], ...],
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in (*existing, *incoming):
        validate_distribution_item(item)
        if item["queue_id"] in seen:
            continue
        seen.add(item["queue_id"])
        merged.append(item)
    return merged


def _render_markdown(items: list[dict[str, str]], run_date: date) -> str:
    lines = [
        f"# Traffic Distribution Review Pack — {run_date.isoformat()}",
        "",
        "Mọi mục đều ở trạng thái `review_required`. Đây là bản nháp để duyệt, không phải bằng chứng đã đăng hoặc đã gửi.",
        "",
        "Giá rao không phải giá chốt giao dịch; luôn kiểm tra thực địa, quy hoạch và pháp lý trước khi quyết định.",
    ]
    for channel in CHANNELS:
        lines.extend(("", f"## {CHANNEL_HEADINGS[channel]}", ""))
        channel_items = [item for item in items if item["channel"] == channel]
        if not channel_items:
            lines.append("Chưa có mục cho kênh này.")
            continue
        for item in channel_items:
            lines.extend(
                (
                    f"### {item['path']}",
                    "",
                    f"- Status: `{item['status']}`",
                    f"- Queue ID: `{item['queue_id']}`",
                    f"- Angle: {item['angle']}",
                    f"- URL: {item['utm_url']}",
                    "",
                    item["copy"],
                    "",
                )
            )
    return "\n".join(lines).rstrip() + "\n"


def write_distribution_pack(
    items: tuple[dict[str, str], ...],
    output_dir: Path,
    format: str,
    *,
    run_date: date,
) -> tuple[Path, ...]:
    if format not in {"markdown", "json", "both"}:
        raise ValueError("format must be markdown, json, or both")
    for item in items:
        validate_distribution_item(item)

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    basename = f"traffic-distribution-{run_date.isoformat()}"
    json_path = destination / f"{basename}.json"
    markdown_path = destination / f"{basename}.md"
    existing = _load_existing_items(json_path) if format in {"json", "both"} else []
    merged = _deduplicate_items(existing, items)
    written: list[Path] = []

    if format in {"json", "both"}:
        payload = {
            "generated_for": run_date.isoformat(),
            "status": "review_required",
            "items": merged,
        }
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(json_path)
    if format in {"markdown", "both"}:
        markdown_path.write_text(_render_markdown(merged or list(items), run_date), encoding="utf-8")
        written.append(markdown_path)
    return tuple(written)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate review-only Radar BDS traffic packs")
    parser.add_argument("--date", required=True, dest="run_date")
    parser.add_argument("--channel", choices=(*CHANNELS, "all"), default="all")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--format", choices=("markdown", "json", "both"), default="both")
    args = parser.parse_args(argv)

    try:
        parsed_date = date.fromisoformat(args.run_date)
    except ValueError as exc:
        parser.error(f"--date must be YYYY-MM-DD: {exc}")
    items = build_distribution_items(parsed_date, args.channel)
    paths = write_distribution_pack(
        items,
        args.output_dir,
        args.format,
        run_date=parsed_date,
    )
    print(f"Review items: {len(items)}")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
