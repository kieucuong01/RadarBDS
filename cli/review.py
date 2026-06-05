"""Claude pre-review CLI (CO VAN).

`review-queue` lists actionable signals that do not yet have a Claude-authored
investment memo. It prints raw context so the memo can be written by the agent.
`review-save` appends the verdict and optional memo markdown to ai_deal_review.

Anti-bias boundary:
- Never write Claude/AI output to ai_training_feedback.
- Never touch listings.review_hidden.
- Always INSERT; do not update/upsert previous Claude reviews.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from db.connection import get_conn
from db.schema import init_schema
from services.signal_quality import (
    LATEST_VALUATION_CTE,
    actionable_listing_sql,
    actionable_signal_sql,
)

CLAUDE_VERDICTS = {"cheap_real", "suspect", "not_cheap", "insufficient_info"}
_MODEL = "claude-code-interactive"


def _json_list(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return [part.strip() for part in str(value).split(",") if part.strip()]
    return parsed if isinstance(parsed, list) else []


def _price_history(conn, listing_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT recorded_at, price_ty, price_per_m2
          FROM price_history
         WHERE listing_id = ?
         ORDER BY recorded_at ASC, id ASC
         LIMIT 20
        """,
        (listing_id,),
    ).fetchall()
    return [dict(row.items()) for row in rows]


def _lot_history(conn, listing_id: int) -> list[dict]:
    listing = conn.execute(
        "SELECT id, duplicate_of_id FROM listings WHERE id=?",
        (listing_id,),
    ).fetchone()
    if not listing:
        return []
    canonical_id = listing["duplicate_of_id"] or listing["id"]
    rows = conn.execute(
        """
        SELECT id, title, url, source, price_ty, area_m2,
               COALESCE(posted_at, crawled_at, updated_at) AS date,
               price_dropped, price_drop_pct
          FROM listings
         WHERE id = ? OR duplicate_of_id = ?
         ORDER BY COALESCE(posted_at, crawled_at, updated_at) ASC, id ASC
         LIMIT 20
        """,
        (canonical_id, canonical_id),
    ).fetchall()
    return [dict(row.items()) for row in rows]


def _review_context(conn, row) -> dict:
    listing_id = row["id"]
    latest_unmemoed_review = None
    if row["ai_verdict"]:
        latest_unmemoed_review = {
            "verdict": row["ai_verdict"],
            "confidence": row["ai_confidence"],
            "reasoning": row["ai_reasoning"],
            "red_flags": _json_list(row["ai_red_flags"]),
            "needs_map_check": bool(row["ai_needs_map_check"]),
        }

    return {
        "listing": {
            "id": listing_id,
            "title": row["title"],
            "description": row["description"],
            "url": row["url"],
            "source": row["source"],
            "ward": row["ward"],
            "property_type": row["property_type"],
            "price_ty": row["price_ty"],
            "area_m2": row["area_m2"],
            "price_per_m2": row["price_per_m2"],
            "frontage_m": row["frontage_m"],
            "depth_m": row["depth_m"],
            "road_tier": row["road_tier"],
            "road_type": row["road_type"],
            "has_so": row["has_so"],
            "posted_at": row["posted_display"],
        },
        "valuation": {
            "mos_pct": row["mos_pct"],
            "signal_score": row["signal_score"],
            "fair_ppm2": row["fair_ppm2"],
            "actual_ppm2": row["actual_ppm2"],
            "n_segment": row["n_segment"],
            "source_quality_flags": row["source_quality_flags"],
            "source_quality_recheck": bool(row["source_quality_recheck"]),
            "legal_status": row["legal_status"],
            "trust_tier": row["trust_tier"],
            "trust_score": row["trust_score"],
            "legal_flags": row["legal_flags"],
        },
        "price_history": _price_history(conn, listing_id),
        "lot_history": _lot_history(conn, listing_id),
        "latest_unmemoed_review": latest_unmemoed_review,
    }


def cmd_review_queue(args):
    """Print JSON: actionable signals without a saved Claude memo."""
    init_schema()
    top = getattr(args, "top", None) or 5
    ward = getattr(args, "ward", None)
    signal_condition = actionable_signal_sql("v")
    listing_condition = actionable_listing_sql("l")

    sql = f"""
        WITH {LATEST_VALUATION_CTE}
        SELECT l.id, l.title, l.description, l.url, l.source, l.ward,
               l.property_type, l.price_ty, l.price_per_m2, l.area_m2,
               l.frontage_m, l.depth_m, l.road_tier, l.road_type, l.has_so,
               COALESCE(l.posted_at, l.first_seen_at, l.crawled_at) AS posted_display,
               v.mos_pct, v.signal_score, v.fair_ppm2, v.actual_ppm2,
               v.n_segment, COALESCE(v.source_quality_flags,'') AS source_quality_flags,
               COALESCE(v.source_quality_recheck,0) AS source_quality_recheck,
               COALESCE(v.legal_status, 'unverified') AS legal_status,
               COALESCE(v.trust_tier, 'candidate_signal') AS trust_tier,
               COALESCE(v.trust_score, 0) AS trust_score,
               COALESCE(v.legal_flags, '') AS legal_flags,
               r.verdict AS ai_verdict, r.confidence AS ai_confidence,
               r.reasoning AS ai_reasoning, r.red_flags AS ai_red_flags,
               r.needs_map_check AS ai_needs_map_check
        FROM listings l
        JOIN latest_valuation v ON v.listing_id = l.id
        LEFT JOIN ai_deal_review r
               ON r.id = (SELECT id FROM ai_deal_review
                          WHERE listing_id = l.id
                          ORDER BY created_at DESC, id DESC LIMIT 1)
        LEFT JOIN ai_deal_review memo
               ON memo.id = (SELECT id FROM ai_deal_review
                             WHERE listing_id = l.id
                               AND NULLIF(TRIM(COALESCE(memo_markdown,'')), '') IS NOT NULL
                               AND COALESCE(model,'') NOT LIKE 'claude-code-advisory-%'
                             ORDER BY created_at DESC, id DESC LIMIT 1)
        WHERE {signal_condition} AND {listing_condition} AND v.signal_score IS NOT NULL
          AND memo.id IS NULL
    """
    params = []
    if ward:
        sql += " AND l.ward = ?"
        params.append(ward)
    sql += " ORDER BY v.signal_score DESC, v.mos_pct DESC LIMIT ?"
    params.append(top)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        items = [
            {
                "listing_id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "ward": row["ward"],
                "price_ty": row["price_ty"],
                "area_m2": row["area_m2"],
                "mos_pct": row["mos_pct"],
                "signal_score": row["signal_score"],
                "context": _review_context(conn, row),
            }
            for row in rows
        ]

    out = {
        "count": len(items),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


def _read_memo_file(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    try:
        memo = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR cannot read --memo-file: {exc}", file=sys.stderr)
        sys.exit(2)
    if not memo.strip():
        print("ERROR --memo-file is empty", file=sys.stderr)
        sys.exit(2)
    return memo


def cmd_review_save(args):
    """Append a Claude verdict and optional memo markdown to ai_deal_review."""
    init_schema()

    verdict = (getattr(args, "verdict", "") or "").strip()
    if verdict not in CLAUDE_VERDICTS:
        print(f"ERROR invalid verdict '{verdict}'. Valid: {sorted(CLAUDE_VERDICTS)}", file=sys.stderr)
        sys.exit(2)

    confidence = getattr(args, "confidence", None)
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            print("ERROR confidence must be a number in [0,1]", file=sys.stderr)
            sys.exit(2)
        if not (0.0 <= confidence <= 1.0):
            print("ERROR confidence out of range [0,1]", file=sys.stderr)
            sys.exit(2)

    reasoning = (getattr(args, "reasoning", "") or "").strip()[:2000]
    if not reasoning:
        print("ERROR --reasoning is required", file=sys.stderr)
        sys.exit(2)

    raw_flags = getattr(args, "red_flags", None) or ""
    flags = [f.strip() for f in raw_flags.split(";") if f.strip()]
    red_flags_json = json.dumps(flags, ensure_ascii=False) if flags else None

    memo_markdown = _read_memo_file(getattr(args, "memo_file", None))
    needs_map = 1 if getattr(args, "needs_map_check", False) else 0
    listing_id = getattr(args, "id", None)

    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM listings WHERE id=?", (listing_id,)
        ).fetchone()
        if not exists:
            print(f"ERROR listing {listing_id} does not exist", file=sys.stderr)
            sys.exit(2)
        conn.execute(
            """
            INSERT INTO ai_deal_review
              (listing_id, actor, verdict, confidence, reasoning,
               red_flags, memo_markdown, needs_map_check, model, updated_at)
            VALUES (?, 'claude', ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                listing_id,
                verdict,
                confidence,
                reasoning,
                red_flags_json,
                memo_markdown,
                needs_map,
                _MODEL,
            ),
        )

    print(f"OK review saved listing={listing_id} verdict={verdict} conf={confidence}")
