"""Bounded, dry-run-first reconciliation for existing Guland listings."""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from typing import Any

from analytics.lifecycle import SourceCheckResult, record_source_check
from cleansing.reprocess import run_targeted_reprocess
from crawler.guland_pw import (
    GulandCrawler,
    classify_detail_result,
)
from db.connection import get_conn
from db.raw_listings import refresh_raw_listing
from services.guland_reconciliation import canonical_price_vnd


MAX_RECONCILIATION_LIMIT = 200
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HistoricalGulandCandidate:
    raw_id: int
    listing_id: int
    url: str
    source_id: str
    price_ty: float | None
    first_seen_at: Any
    source_status: str
    consecutive_missing: int
    raw_data: dict


def _decode_raw_json(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def load_guland_candidates(limit: int) -> list[HistoricalGulandCandidate]:
    """Load only product-displayable Guland rows, unknown/stale first."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT r.id AS raw_id, l.id AS listing_id, l.url, l.source_id,
                   l.price_ty, l.first_seen_at,
                   COALESCE(l.source_status, 'unknown') AS source_status,
                   COALESCE(l.consecutive_missing, 0) AS consecutive_missing,
                   r.raw_json
            FROM listings l
            JOIN raw_listings r ON r.id=l.raw_id
            WHERE l.source='guland'
              AND COALESCE(l.source_status, 'unknown') <> 'inactive'
              AND COALESCE(l.probably_sold, 0)=0
              AND COALESCE(l.is_blacklisted, 0)=0
              AND COALESCE(l.review_hidden, 0)=0
              AND COALESCE(l.possibly_duplicate, 0)=0
              AND l.price_ty > 0
              AND l.area_m2 > 0
            ORDER BY
              CASE COALESCE(l.source_status,'unknown')
                WHEN 'unknown' THEN 0 ELSE 1
              END,
              l.last_source_check_at NULLS FIRST,
              l.id
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [
        HistoricalGulandCandidate(
            raw_id=int(row["raw_id"]),
            listing_id=int(row["listing_id"]),
            url=str(row["url"] or ""),
            source_id=str(row["source_id"] or ""),
            price_ty=row["price_ty"],
            first_seen_at=row["first_seen_at"],
            source_status=str(row["source_status"] or "unknown"),
            consecutive_missing=int(row["consecutive_missing"] or 0),
            raw_data=_decode_raw_json(row["raw_json"]),
        )
        for row in rows
    ]


def fetch_guland_details(
    candidates: list[HistoricalGulandCandidate],
) -> dict[str, dict]:
    """Fetch bounded detail pages in the same browser context as the crawler."""
    if not candidates:
        return {}
    from playwright.sync_api import sync_playwright

    crawler = GulandCrawler()
    with sync_playwright() as playwright:
        browser, context = crawler._launch(playwright, headless=True)
        try:
            page = context.new_page()
            page.goto(
                "https://guland.vn/",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            return crawler._fetch_details_batch(
                page,
                [candidate.url for candidate in candidates],
            )
        finally:
            context.close()
            browser.close()


def apply_source_check(
    candidate: HistoricalGulandCandidate,
    outcome: str,
    reason: str,
) -> SourceCheckResult:
    with get_conn() as conn:
        return record_source_check(
            conn,
            candidate.listing_id,
            outcome,
            reason,
        )


def _updated_raw_record(
    candidate: HistoricalGulandCandidate,
    detail: dict,
    price_ty: float,
) -> dict:
    record = dict(candidate.raw_data)
    record["url"] = candidate.url
    record["price_ty"] = price_ty
    for key in (
        "description",
        "address",
        "property_type_raw",
        "road_type_raw",
        "road_width_raw",
        "location_type_raw",
        "legal_raw",
        "contact_phone",
        "detail_imgs",
    ):
        value = detail.get(key)
        if value not in (None, "", []):
            record["imgs" if key == "detail_imgs" else key] = value
    return record


def _valid_history_price(value: Any) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def backfill_guland_history_metadata() -> dict[str, int]:
    """Backfill only deterministic timestamps; never invent historical prices."""
    with get_conn() as conn:
        first_seen = conn.execute(
            """
            UPDATE listings
            SET first_seen_at=crawled_at
            WHERE source='guland'
              AND (first_seen_at IS NULL OR TRIM(first_seen_at)='')
              AND crawled_at IS NOT NULL
            """
        ).rowcount or 0
        source_status = conn.execute(
            """
            UPDATE listings
            SET source_status='unknown'
            WHERE source='guland'
              AND (
                source_status IS NULL
                OR source_status NOT IN ('unknown','active','inactive','unreachable')
              )
            """
        ).rowcount or 0
        rows = conn.execute(
            """
            SELECT l.id AS listing_id, l.price_updated_at,
                   ph.price_ty, ph.recorded_at
            FROM listings l
            JOIN price_history ph ON ph.listing_id=l.id
            WHERE l.source='guland'
            ORDER BY l.id, ph.recorded_at, ph.id
            """
        ).fetchall()

        latest_changes: dict[int, Any] = {}
        previous: dict[int, float] = {}
        already_set: set[int] = set()
        for row in rows:
            listing_id = int(row["listing_id"])
            if row["price_updated_at"]:
                already_set.add(listing_id)
            price = _valid_history_price(row["price_ty"])
            if price is None:
                continue
            prior = previous.get(listing_id)
            if prior is not None and canonical_price_vnd(prior) != canonical_price_vnd(price):
                if row["recorded_at"]:
                    latest_changes[listing_id] = row["recorded_at"]
            previous[listing_id] = price

        price_updated = 0
        for listing_id, recorded_at in latest_changes.items():
            if listing_id in already_set:
                continue
            cur = conn.execute(
                """
                UPDATE listings
                SET price_updated_at=CAST(? AS TIMESTAMPTZ)
                WHERE id=? AND price_updated_at IS NULL
                """,
                (recorded_at, listing_id),
            )
            price_updated += cur.rowcount or 0
    return {
        "first_seen": int(first_seen),
        "price_updated": int(price_updated),
        "source_status": int(source_status),
    }


def reconcile_guland_candidates(limit: int, apply: bool) -> dict:
    """Inspect a bounded candidate set; mutate only when ``apply`` is true."""
    limit = int(limit)
    if limit < 1 or limit > MAX_RECONCILIATION_LIMIT:
        raise ValueError(
            f"limit must be between 1 and {MAX_RECONCILIATION_LIMIT}"
        )

    candidates = load_guland_candidates(limit)
    stats = {
        "apply": bool(apply),
        "scanned": len(candidates),
        "active": 0,
        "inactive_first_confirmation": 0,
        "inactive_confirmed": 0,
        "unreachable": 0,
        "price_changes": 0,
        "invalid_prices": 0,
        "errors": 0,
        "changed_listing_ids": [],
    }
    refreshed_raw_ids: list[int] = []

    if apply:
        backfill_guland_history_metadata()
    details = fetch_guland_details(candidates)

    for candidate in candidates:
        try:
            detail = details.get(candidate.url, {})
            classification = classify_detail_result(detail)

            if classification.outcome == "removed":
                would_be_inactive = candidate.consecutive_missing + 1 >= 2
                if apply:
                    result = apply_source_check(
                        candidate,
                        classification.outcome,
                        classification.reason,
                    )
                    would_be_inactive = result.source_status == "inactive"
                key = (
                    "inactive_confirmed"
                    if would_be_inactive
                    else "inactive_first_confirmation"
                )
                stats[key] += 1
                continue

            if classification.outcome == "unreachable":
                stats["unreachable"] += 1
                if apply:
                    apply_source_check(
                        candidate,
                        classification.outcome,
                        classification.reason,
                    )
                continue

            stats["active"] += 1
            if apply:
                apply_source_check(
                    candidate,
                    classification.outcome,
                    classification.reason,
                )

            price_ty = GulandCrawler.parse_price_ty(
                detail.get("detail_price_raw", "")
            )
            canonical_price = canonical_price_vnd(price_ty)
            if canonical_price is None:
                stats["invalid_prices"] += 1
                continue
            if canonical_price == canonical_price_vnd(candidate.price_ty):
                continue

            stats["price_changes"] += 1
            stats["changed_listing_ids"].append(candidate.listing_id)
            if apply:
                raw_id = refresh_raw_listing(
                    "guland",
                    candidate.url,
                    _updated_raw_record(candidate, detail, price_ty),
                )
                refreshed_raw_ids.append(int(raw_id))
        except Exception:
            logger.exception(
                "Guland reconciliation failed for listing_id=%s",
                candidate.listing_id,
            )
            stats["errors"] += 1

    if apply and refreshed_raw_ids:
        try:
            run_targeted_reprocess(refreshed_raw_ids)
        except Exception:
            logger.exception("Guland targeted reprocess failed")
            stats["errors"] += 1

    stats["changed_listing_ids"] = stats["changed_listing_ids"][:limit]
    return stats
