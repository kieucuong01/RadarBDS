from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import connect
from db.listings import save_llm_extraction_override, upsert_listing


REVIEW_FIELDS = (
    "price_ty",
    "price_per_m2",
    "area_m2",
    "ward",
    "road_type",
    "road_tier",
    "road_name",
    "property_type",
    "tho_cu_m2",
    "tho_cu_ratio",
    "frontage_m",
    "depth_m",
    "has_so",
)
NUMERIC_FIELDS = {
    "price_ty",
    "price_per_m2",
    "area_m2",
    "tho_cu_m2",
    "tho_cu_ratio",
    "frontage_m",
    "depth_m",
}
INT_FIELDS = {"road_tier", "has_so"}
APPLY_STATUSES = {"override", "mismatch", "override_fixed"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Apply manual LLM signal extraction JSONL results as explicit listing overrides. "
            "Dry-run by default; use --apply to write DB changes."
        )
    )
    parser.add_argument("input", type=Path, help="Structured LLM result .jsonl or .json file.")
    parser.add_argument("--apply", action="store_true", help="Write override markers and refresh affected listing rows.")
    parser.add_argument("--actor", default="codex", help="Override actor marker.")
    parser.add_argument("--model", default="manual-llm-signal-qc", help="Override model/workflow marker.")
    parser.add_argument(
        "--numeric-tolerance",
        type=float,
        default=0.000001,
        help="Tolerance when comparing numeric LLM values to stored values.",
    )
    args = parser.parse_args()

    entries = load_entries(args.input)
    summary: dict[str, Any] = {
        "input": str(args.input),
        "apply": bool(args.apply),
        "entries": len(entries),
        "status_counts": Counter(),
        "override_rows": 0,
        "override_field_counts": Counter(),
        "admin_review_rows": 0,
        "missing_listing_ids": [],
        "applied_listing_ids": [],
        "dry_run_overrides": [],
    }

    for entry in entries:
        listing_id = int(entry.get("listing_id") or entry.get("id") or 0)
        status = str(entry.get("status") or "ok").strip().lower()
        summary["status_counts"][status] += 1
        if not listing_id:
            continue

        if status == "admin_review" or entry.get("admin_review") is True:
            summary["admin_review_rows"] += 1
            continue
        if status not in APPLY_STATUSES:
            continue

        listing = load_listing(listing_id)
        if not listing:
            summary["missing_listing_ids"].append(listing_id)
            continue

        override_fields = resolve_override_fields(
            entry,
            listing,
            numeric_tolerance=args.numeric_tolerance,
        )
        if not override_fields:
            continue

        summary["override_rows"] += 1
        summary["override_field_counts"].update(override_fields.keys())
        summary["dry_run_overrides"].append(
            {
                "listing_id": listing_id,
                "fields": override_fields,
                "reason": entry.get("reason") or entry.get("note") or "",
            }
        )

        if args.apply:
            save_llm_extraction_override(
                listing_id,
                override_fields,
                actor=args.actor,
                model=args.model,
                note=str(entry.get("reason") or entry.get("note") or "manual LLM extraction QC"),
            )
            refreshed = listing_to_upsert_record(load_listing(listing_id) or listing)
            upsert_listing(refreshed)
            summary["applied_listing_ids"].append(listing_id)

    printable = dict(summary)
    printable["status_counts"] = dict(summary["status_counts"])
    printable["override_field_counts"] = dict(summary["override_field_counts"])
    print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def load_entries(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        entries: list[dict[str, Any]] = []
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSONL at line {line_no}: {exc}") from exc
            if isinstance(item, dict):
                entries.append(item)
        return entries

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [item for item in data["items"] if isinstance(item, dict)]
    raise SystemExit("Input JSON must be a list or an object with an items list")


def load_listing(listing_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
    if row is None:
        return None
    return dict(row.items()) if hasattr(row, "items") else dict(row)


def resolve_override_fields(
    entry: dict[str, Any],
    listing: dict[str, Any],
    *,
    numeric_tolerance: float,
) -> dict[str, Any]:
    explicit = entry.get("override_fields")
    if not isinstance(explicit, dict):
        explicit = entry.get("fields") if isinstance(entry.get("fields"), dict) else None
    if isinstance(explicit, dict) and explicit:
        return clean_fields(explicit)

    llm_extract = entry.get("llm_extract") or entry.get("manual_extract")
    if not isinstance(llm_extract, dict):
        return {}

    diff: dict[str, Any] = {}
    for field, value in clean_fields(llm_extract).items():
        if not values_equal(field, value, listing.get(field), numeric_tolerance=numeric_tolerance):
            diff[field] = value
    return diff


def clean_fields(fields: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for field, value in fields.items():
        if field not in REVIEW_FIELDS:
            continue
        cleaned[field] = coerce_value(field, value)
    return cleaned


def coerce_value(field: str, value: Any) -> Any:
    if value in ("", "unknown", "null"):
        return None
    if field in NUMERIC_FIELDS:
        return float_or_none(value)
    if field in INT_FIELDS:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def values_equal(field: str, left: Any, right: Any, *, numeric_tolerance: float) -> bool:
    if field in NUMERIC_FIELDS:
        a = float_or_none(left)
        b = float_or_none(right)
        if a is None or b is None:
            return a is None and b is None
        return abs(a - b) <= numeric_tolerance
    if field in INT_FIELDS:
        return coerce_value(field, left) == coerce_value(field, right)
    return normalize_text(left) == normalize_text(right)


def float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split()).casefold()


def listing_to_upsert_record(listing: dict[str, Any]) -> dict[str, Any]:
    rec = dict(listing)
    rec["post_date"] = listing.get("posted_at")
    rec.setdefault("area", listing.get("ward") or "")
    rec.setdefault("raw_area_text", "")
    rec.setdefault("tx_type", "ban")
    rec.setdefault("is_hot", False)
    return rec


if __name__ == "__main__":
    raise SystemExit(main())
