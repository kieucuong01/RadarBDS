from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import connect
from services.signal_quality import (
    LATEST_VALUATION_CTE,
    actionable_listing_sql,
    actionable_signal_sql,
)


DEFAULT_STATE_PATH = PROJECT_ROOT / ".local" / "llm-review" / "state.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".local" / "llm-review" / "daily"
DEFAULT_RAW_OUTPUT_DIR = PROJECT_ROOT / ".local" / "llm-review" / "raw"
REVIEW_FIELDS = (
    "price_ty",
    "area_m2",
    "ward",
    "road_type",
    "road_tier",
    "road_name",
    "property_type",
    "tho_cu_m2",
    "frontage_m",
    "depth_m",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export actionable signal listings to a queue for manual Codex/LLM "
            "extraction review. This script prepares raw context only; it does not judge correctness."
        )
    )
    parser.add_argument("--since", default=None, help="ISO timestamp/date lower bound for new signals.")
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Fallback lookback window when no state or --since is available.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional max rows to export.")
    parser.add_argument("--output", type=Path, default=None, help="Optional output path.")
    parser.add_argument(
        "--format",
        choices=("markdown", "jsonl", "json"),
        default="markdown",
        help="Queue format. JSONL/JSON are better for LLM structured extraction batches.",
    )
    parser.add_argument(
        "--sort",
        choices=("review_at_asc", "signal_desc"),
        default="review_at_asc",
        help="review_at_asc keeps daily state order; signal_desc reviews strongest deals first.",
    )
    parser.add_argument(
        "--missing-review-only",
        action="store_true",
        help="Limit the queue to actionable signals that still lack a saved advisory memo in ai_deal_review.",
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH, help="Review state JSON path.")
    parser.add_argument(
        "--commit-state",
        action="store_true",
        help="Advance review state to the newest exported signal date after manual review is saved.",
    )
    args = parser.parse_args()

    state = load_state(args.state)
    since = resolve_since(args.since, state, args.days, missing_review_only=args.missing_review_only)
    rows = load_new_signals(
        since,
        args.limit,
        sort=args.sort,
        missing_review_only=args.missing_review_only,
    )
    generated_at = datetime.now().astimezone()
    output = args.output or default_output_path(generated_at, args.format)
    output.parent.mkdir(parents=True, exist_ok=True)

    max_seen = max((str(row.get("review_sort_at") or "") for row in rows), default="")
    if args.format == "jsonl":
        output.write_text(
            render_jsonl(
                rows,
                since=since,
                generated_at=generated_at,
                max_seen=max_seen,
                missing_review_only=args.missing_review_only,
            ),
            encoding="utf-8",
        )
    elif args.format == "json":
        output.write_text(
            render_json(
                rows,
                since=since,
                generated_at=generated_at,
                max_seen=max_seen,
                missing_review_only=args.missing_review_only,
            ),
            encoding="utf-8",
        )
    else:
        output.write_text(
            render_markdown(
                rows,
                since=since,
                generated_at=generated_at,
                max_seen=max_seen,
                missing_review_only=args.missing_review_only,
            ),
            encoding="utf-8",
        )

    if args.commit_state:
        if max_seen:
            state.update(
                {
                    "last_reviewed_signal_at": max_seen,
                    "last_review_queue_path": str(output.relative_to(PROJECT_ROOT)),
                    "last_reviewed_count": len(rows),
                    "updated_at": generated_at.isoformat(timespec="seconds"),
                }
            )
        else:
            state.update(
                {
                    "last_empty_review_at": generated_at.isoformat(timespec="seconds"),
                    "last_review_queue_path": str(output.relative_to(PROJECT_ROOT)),
                }
            )
        save_state(args.state, state)

    scope_label = format_scope_label(since, args.missing_review_only)
    print(f"Since: {scope_label}")
    print(f"Exported signals: {len(rows)}")
    print(f"Newest signal timestamp: {max_seen or 'n/a'}")
    print(f"Queue: {output}")
    if args.commit_state:
        print(f"State updated: {args.state}")
    else:
        print("State not updated; rerun with the same --since plus --commit-state after manual LLM review is saved.")
    return 0


def load_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_since(
    raw_since: str | None,
    state: dict[str, Any],
    days: int,
    *,
    missing_review_only: bool = False,
) -> str | None:
    if raw_since:
        return raw_since
    if missing_review_only:
        return None
    state_since = str(state.get("last_reviewed_signal_at") or "").strip()
    if state_since:
        return state_since
    since = datetime.now().astimezone() - timedelta(days=max(days, 1))
    return since.isoformat(timespec="seconds")


def default_output_path(generated_at: datetime, output_format: str = "markdown") -> Path:
    stamp = generated_at.strftime("%Y%m%d-%H%M%S")
    if output_format == "jsonl":
        return DEFAULT_RAW_OUTPUT_DIR / f"signal-llm-qc-{stamp}.jsonl"
    if output_format == "json":
        return DEFAULT_RAW_OUTPUT_DIR / f"signal-llm-qc-{stamp}.json"
    return DEFAULT_OUTPUT_DIR / f"signal-llm-qc-{stamp}.md"


def load_new_signals(
    since: str | None,
    limit: int = 0,
    *,
    sort: str = "review_at_asc",
    missing_review_only: bool = False,
) -> list[dict[str, Any]]:
    signal_condition = actionable_signal_sql("v")
    listing_condition = actionable_listing_sql("l")
    date_expr = "COALESCE(l.first_seen_at, l.crawled_at, l.updated_at, l.posted_at)"
    limit_sql = "LIMIT ?" if limit and limit > 0 else ""
    order_sql = (
        "ORDER BY COALESCE(v.mos_pct, 0) DESC, COALESCE(v.signal_score, 0) DESC, l.id DESC"
        if sort == "signal_desc"
        else f"ORDER BY {date_expr} ASC, l.id ASC"
    )
    params: list[Any] = []
    extra_filters: list[str] = []
    if since:
        extra_filters.append(f"{date_expr} >= ?")
        params.append(since)
    if missing_review_only:
        extra_filters.append("memo.id IS NULL")
    if limit and limit > 0:
        params.append(limit)
    extra_where = ""
    if extra_filters:
        extra_where = "\n              AND " + "\n              AND ".join(extra_filters)

    with connect() as conn:
        rows = conn.execute(
            f"""
            WITH {LATEST_VALUATION_CTE}
            SELECT l.id, l.raw_id, l.source, l.source_id, l.url,
                   l.title, l.description, l.price_ty, l.price_per_m2, l.area_m2,
                   l.frontage_m, l.depth_m, l.ward, l.property_type,
                   l.road_type, l.road_tier, l.road_name, l.tho_cu_m2, l.tho_cu_ratio,
                   l.has_so, l.first_seen_at, l.posted_at, l.crawled_at, l.updated_at,
                   {date_expr} AS review_sort_at,
                   v.mos_pct, v.signal_score, v.actual_ppm2, v.fair_ppm2,
                   v.source_quality_flags, v.source_quality_recheck,
                   r.raw_json
            FROM listings l
            JOIN latest_valuation v ON v.listing_id = l.id
            LEFT JOIN ai_deal_review memo
                   ON memo.id = (
                        SELECT id
                          FROM ai_deal_review
                         WHERE listing_id = l.id
                           AND NULLIF(TRIM(COALESCE(memo_markdown, '')), '') IS NOT NULL
                         ORDER BY created_at DESC, id DESC
                         LIMIT 1
                   )
            LEFT JOIN raw_listings r ON r.id = l.raw_id
            WHERE {signal_condition}
              AND {listing_condition}
            {extra_where}
            {order_sql}
            {limit_sql}
            """,
            params,
        ).fetchall()
    return [dict(row.items()) if hasattr(row, "items") else dict(row) for row in rows]


def render_jsonl(
    rows: list[dict[str, Any]],
    *,
    since: str | None,
    generated_at: datetime,
    max_seen: str,
    missing_review_only: bool,
) -> str:
    lines = [
        json.dumps(
            build_review_item(
                index,
                row,
                since=since,
                generated_at=generated_at,
                max_seen=max_seen,
                missing_review_only=missing_review_only,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
        for index, row in enumerate(rows, start=1)
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def render_json(
    rows: list[dict[str, Any]],
    *,
    since: str | None,
    generated_at: datetime,
    max_seen: str,
    missing_review_only: bool,
) -> str:
    payload = {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "scope": {
            "since": since,
            "missing_review_only": missing_review_only,
            "exported_signals": len(rows),
            "newest_exported_timestamp": max_seen or None,
        },
        "review_fields": list(REVIEW_FIELDS),
        "items": [
            build_review_item(
                index,
                row,
                since=since,
                generated_at=generated_at,
                max_seen=max_seen,
                missing_review_only=missing_review_only,
            )
            for index, row in enumerate(rows, start=1)
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def build_review_item(
    index: int,
    row: dict[str, Any],
    *,
    since: str | None,
    generated_at: datetime,
    max_seen: str,
    missing_review_only: bool,
) -> dict[str, Any]:
    return {
        "review_index": index,
        "listing_id": row.get("id"),
        "source": row.get("source"),
        "source_id": row.get("source_id"),
        "url": row.get("url"),
        "raw_id": row.get("raw_id"),
        "review_sort_at": row.get("review_sort_at"),
        "export_meta": {
            "generated_at": generated_at.isoformat(timespec="seconds"),
            "since": since,
            "missing_review_only": missing_review_only,
            "newest_exported_timestamp": max_seen or None,
        },
        "valuation": {
            "mos_pct": row.get("mos_pct"),
            "signal_score": row.get("signal_score"),
            "actual_ppm2": row.get("actual_ppm2"),
            "fair_ppm2": row.get("fair_ppm2"),
            "source_quality_flags": parse_json_value(row.get("source_quality_flags")),
            "source_quality_recheck": row.get("source_quality_recheck"),
        },
        "stored_extraction": {field: row.get(field) for field in REVIEW_FIELDS},
        "listing_text": {
            "title": clean_text(row.get("title")),
            "description": clean_text(row.get("description")),
        },
        "raw_facts": extract_raw_facts(row.get("raw_json")),
    }


def extract_raw_facts(raw_json: Any) -> dict[str, Any]:
    raw = parse_json_value(raw_json)
    if not isinstance(raw, dict):
        return {}
    facts: dict[str, Any] = {}
    for key in (
        "address",
        "area_m2",
        "price_ty",
        "price_per_m2",
        "area_name",
        "ward",
        "property_type_raw",
        "road_type_raw",
        "road_width_raw",
        "location_type_raw",
        "legal_raw",
        "default_area",
        "tx_type",
    ):
        value = raw.get(key)
        if value not in (None, "", [], {}):
            facts[key] = value
    return facts


def parse_json_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def render_markdown(
    rows: list[dict[str, Any]],
    *,
    since: str | None,
    generated_at: datetime,
    max_seen: str,
    missing_review_only: bool,
) -> str:
    scope_text = (
        "actionable signals still missing advisory memo coverage in `ai_deal_review`"
        if missing_review_only and not since
        else (
            f"actionable signals missing advisory memo coverage with first-seen/crawl timestamp >= `{since}`"
            if missing_review_only
            else f"actionable signals with first-seen/crawl timestamp >= `{since}`"
        )
    )
    lines: list[str] = [
        "# Signal Extraction LLM QC Queue",
        "",
        f"- Generated at: {generated_at.isoformat(timespec='seconds')}",
        f"- Scope: {scope_text}",
        f"- Exported signals: {len(rows)}",
        f"- Newest exported timestamp: `{max_seen or 'n/a'}`",
        "",
        "## Review Rules",
        "",
        "- Read each listing text manually as the LLM reviewer. Do not let regex/script guesses replace your own reading.",
        "- Compare only these fields: price, area, ward, road type/tier/name, property type, tho cu, frontage/depth.",
        "- If text is ambiguous, send the item to admin review instead of changing parser logic from a weak case.",
        "- Save findings to `.local/llm-review/manual_findings.md`, then run `scripts/audit_signal_extraction.py` for support evidence.",
        "- Only rerun this exporter with the same `--since` plus `--commit-state` after the manual findings/report have been saved.",
        "",
        "## Finding Template",
        "",
        "| listing_id | fields | manual_expected | why_system_was_wrong | action |",
        "|---|---|---|---|---|",
        "|  |  |  |  | admin_review/parser_fix/test_needed |",
        "",
    ]
    if not rows:
        lines.extend(["## Listings", "", "No new actionable signals in this window.", ""])
        return "\n".join(lines)

    lines.extend(["## Listings", ""])
    for idx, row in enumerate(rows, start=1):
        lines.extend(render_listing(idx, row))
    return "\n".join(lines)


def format_scope_label(since: str | None, missing_review_only: bool) -> str:
    if missing_review_only and not since:
        return "all actionable signals missing ai_deal_review memo coverage"
    if missing_review_only and since:
        return f"{since} (missing ai_deal_review memo coverage only)"
    return since or "n/a"


def render_listing(index: int, row: dict[str, Any]) -> list[str]:
    title = clean_text(row.get("title")) or "(không tiêu đề)"
    description = clean_text(row.get("description")) or "(không có mô tả)"
    heading_title = one_line(title)
    lines = [
        f"### {index}. Listing #{row.get('id')} - {heading_title}",
        "",
        f"- Source: {fmt(row.get('source'))} / {fmt(row.get('source_id'))}",
        f"- URL: {fmt(row.get('url'))}",
        f"- Raw ID: {fmt(row.get('raw_id'))}",
        f"- Review timestamp: {fmt(row.get('review_sort_at'))}",
        f"- MOS/score: {fmt(row.get('mos_pct'))}% / {fmt(row.get('signal_score'))}",
        f"- PPM2 actual/fair: {fmt(row.get('actual_ppm2'))} / {fmt(row.get('fair_ppm2'))}",
        f"- Quality flags: {fmt(row.get('source_quality_flags'))}",
        "",
        "Stored extraction:",
        "",
        "| field | stored_value |",
        "|---|---|",
    ]
    for field in REVIEW_FIELDS:
        lines.append(f"| {field} | {fmt(row.get(field))} |")
    lines.extend(
        [
            "",
            "Listing text:",
            "",
            "```text",
            f"Title: {title}",
            "",
            description,
            "```",
            "",
            "Manual LLM review notes:",
            "",
            "- price_ty:",
            "- area_m2:",
            "- ward:",
            "- road_type / road_tier / road_name:",
            "- property_type:",
            "- tho_cu_m2:",
            "- frontage_m / depth_m:",
            "- verdict: ok / mismatch / admin_review",
            "",
        ]
    )
    return lines


def clean_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def one_line(value: str) -> str:
    return " ".join(value.split())


def fmt(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value).replace("\n", " ").strip()


if __name__ == "__main__":
    raise SystemExit(main())
