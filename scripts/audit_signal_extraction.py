from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import connect
from services.extraction_audit import audit_listing_extraction
from services.signal_quality import (
    LATEST_VALUATION_CTE,
    actionable_listing_sql,
    actionable_signal_sql,
)


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".local" / "extraction-audit"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit current actionable signal extraction fields.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max rows to audit.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    rows = load_signal_rows(args.limit)
    audited = []
    fields = Counter()
    sources = Counter()

    for row in rows:
        item = dict(row.items()) if hasattr(row, "items") else dict(row)
        audit = audit_listing_extraction(item)
        sources[item.get("source") or "unknown"] += 1
        if audit["findings"]:
            for finding in audit["findings"]:
                fields[finding["field"]] += 1
            audited.append({
                "id": item.get("id"),
                "source": item.get("source"),
                "source_id": item.get("source_id"),
                "url": item.get("url"),
                "title": item.get("title"),
                "description": item.get("description"),
                "stored": {
                    "price_ty": item.get("price_ty"),
                    "area_m2": item.get("area_m2"),
                    "ward": item.get("ward"),
                    "property_type": item.get("property_type"),
                    "road_tier": item.get("road_tier"),
                    "road_type": item.get("road_type"),
                    "road_name": item.get("road_name"),
                    "tho_cu_m2": item.get("tho_cu_m2"),
                    "tho_cu_ratio": item.get("tho_cu_ratio"),
                },
                "mos_pct": item.get("mos_pct"),
                "signal_score": item.get("signal_score"),
                "audit": audit,
            })

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_signals": len(rows),
        "flagged_count": len(audited),
        "sources": dict(sorted(sources.items())),
        "fields": dict(sorted(fields.items())),
        "items": audited,
    }

    output = args.output or default_output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Audited signals: {payload['total_signals']}")
    print(f"Flagged listings: {payload['flagged_count']}")
    print(f"Fields: {payload['fields']}")
    print(f"Report: {output}")
    return 0


def default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"signal-extraction-audit-{stamp}.json"


def load_signal_rows(limit: int = 0):
    signal_condition = actionable_signal_sql("v")
    listing_condition = actionable_listing_sql("l")
    limit_sql = "LIMIT ?" if limit and limit > 0 else ""
    params = [limit] if limit and limit > 0 else []
    with connect() as conn:
        return conn.execute(f"""
            WITH {LATEST_VALUATION_CTE}
            SELECT l.id, l.source, l.source_id, l.url, l.title, l.description,
                   l.price_ty, l.price_per_m2, l.area_m2, l.ward, l.property_type,
                   l.road_tier, l.road_type, l.road_name, l.tho_cu_m2, l.tho_cu_ratio,
                   l.frontage_m, l.depth_m, l.has_so,
                   v.mos_pct, v.signal_score, v.source_quality_flags, v.source_quality_recheck
            FROM listings l
            JOIN latest_valuation v ON v.listing_id = l.id
            WHERE {signal_condition}
              AND {listing_condition}
            ORDER BY COALESCE(v.mos_pct, 0) DESC, COALESCE(v.signal_score, 0) DESC, l.id DESC
            {limit_sql}
        """, params).fetchall()


if __name__ == "__main__":
    raise SystemExit(main())
