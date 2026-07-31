"""Dry-run-first backfill of active Guland publisher identity."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from config.settings import GULAND_PUBLISHER_KEY_SECRET
from crawler.base_crawler import _normalize_playwright_browser_path_env
from crawler.guland_pw import GulandCrawler, classify_detail_result
from db.connection import AdvisoryLockBusy, advisory_lock, get_conn
from db.guland_publishers import (
    recompute_publisher,
    record_listing_observation,
    sync_listing_publisher,
)
from db.raw_listings import update_raw_listing_payload
from services.guland_coordinates import guland_identity_matches
from services.guland_publisher_activity import (
    PublisherMetrics,
    classify_publisher,
    validated_raw_publisher_fields,
)


@dataclass(frozen=True)
class GulandPublisherBackfillTarget:
    listing_id: int
    raw_id: int
    url: str
    source_id: str
    source_status: str
    publisher_status: str
    raw_data: Mapping[str, object]


def validate_backfill_limit(value: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("backfill limit must be between 1 and 500") from exc
    if not 1 <= limit <= 500:
        raise ValueError("backfill limit must be between 1 and 500")
    return limit


def _parse_raw_json(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_targets(
    limit: int,
    *,
    current_urls: Sequence[str] = (),
) -> list[GulandPublisherBackfillTarget]:
    limit = validate_backfill_limit(limit)
    current = list(dict.fromkeys(str(url or "").strip() for url in current_urls))
    current = [url for url in current if url]
    current_clause = ""
    params: list[object] = []
    if current:
        placeholders = ",".join("?" * len(current))
        current_clause = f" OR r.url IN ({placeholders})"
        params.extend(current)
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT l.id AS listing_id, r.id AS raw_id, r.url, r.source_id,
                   r.raw_json, COALESCE(l.source_status, 'unknown') AS source_status,
                   COALESCE(lp.identity_status, 'unchecked') AS publisher_status
            FROM listings l
            JOIN raw_listings r ON r.id=l.raw_id
            LEFT JOIN listing_publishers lp ON lp.listing_id=l.id
            WHERE l.source='guland'
              AND COALESCE(l.is_active, 1) <> 0
              AND COALESCE(l.probably_sold, 0)=0
              AND COALESCE(l.review_hidden, 0)=0
              AND COALESCE(l.possibly_duplicate, 0)=0
              AND COALESCE(l.source_status, 'unknown') <> 'inactive'
              AND (
                    COALESCE(l.source_status, 'unknown')='active'
                 OR (
                        COALESCE(l.source_status, 'unknown')
                        IN ('unknown', 'unreachable')
                    AND lp.listing_id IS NULL
                 )
                 {current_clause}
              )
            ORDER BY
              CASE COALESCE(l.source_status, 'unknown')
                WHEN 'active' THEN 0
                WHEN 'unknown' THEN 1
                WHEN 'unreachable' THEN 2
                ELSE 3
              END,
              l.id
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [
        GulandPublisherBackfillTarget(
            listing_id=int(row["listing_id"]),
            raw_id=int(row["raw_id"]),
            url=str(row["url"]),
            source_id=str(row["source_id"] or ""),
            source_status=str(row["source_status"] or "unknown"),
            publisher_status=str(row["publisher_status"] or "unchecked"),
            raw_data=_parse_raw_json(row["raw_json"]),
        )
        for row in rows
    ]


def load_guland_publisher_backfill_targets(
    limit: int,
) -> list[GulandPublisherBackfillTarget]:
    """Load active listings plus one never-checked unknown/unreachable retry."""
    return _load_targets(limit)


def _collect_targets_and_details(
    limit: int,
) -> tuple[list[GulandPublisherBackfillTarget], dict[str, dict], int]:
    """Discover configured cards and fetch every bounded detail in one browser."""
    _normalize_playwright_browser_path_env()
    from playwright.sync_api import sync_playwright

    crawler = GulandCrawler()
    cards_by_url: dict[str, dict] = {}
    with sync_playwright() as playwright:
        browser, context = crawler._launch(playwright, headless=True)
        try:
            page = context.new_page()
            page.set_default_timeout(30_000)
            for base_url in crawler.TARGET_URLS:
                cards = crawler._scroll_all_cards(
                    page,
                    base_url,
                    incremental=True,
                )
                for card in cards or []:
                    url = str(card.get("url") or "").strip()
                    if url:
                        cards_by_url.setdefault(url, card)
            targets = _load_targets(
                limit,
                current_urls=list(cards_by_url),
            )
            details = crawler._fetch_details_batch(
                page,
                [target.url for target in targets],
            )
        finally:
            browser.close()
    return targets, details, len(cards_by_url)


def _empty_stats(mode: str) -> dict[str, object]:
    return {
        "mode": mode,
        "candidates_by_status": {},
        "cards_scanned": 0,
        "pages_fetched": 0,
        "live": 0,
        "removed": 0,
        "unreachable": 0,
        "identity_by_type": {},
        "estimated_classes": {},
        "would_identify": 0,
        "would_remain_unknown": 0,
        "raw_updated": 0,
        "publisher_links_updated": 0,
        "errors": 0,
        "run_id": "",
    }


def _verified_detail(
    target: GulandPublisherBackfillTarget,
    detail: Mapping[str, object],
) -> tuple[str, dict[str, object]]:
    classification = classify_detail_result(dict(detail))
    if classification.outcome != "active":
        return classification.outcome, {}
    if not guland_identity_matches(
        str(detail.get("url") or ""),
        target.url,
        "",
        target.source_id,
    ):
        return "unreachable", {}
    fields = validated_raw_publisher_fields(
        detail,
        secret=GULAND_PUBLISHER_KEY_SECRET,
    )
    return "live", fields


def _build_plan(
    targets: Sequence[GulandPublisherBackfillTarget],
    details: Mapping[str, Mapping[str, object]],
    *,
    cards_scanned: int,
    mode: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    stats = _empty_stats(mode)
    stats["cards_scanned"] = int(cards_scanned)
    stats["pages_fetched"] = len(details)
    stats["candidates_by_status"] = dict(
        sorted(Counter(target.source_status for target in targets).items())
    )
    identity_types: Counter[str] = Counter()
    estimated_classes: Counter[str] = Counter()
    plan: list[dict[str, object]] = []
    for target in targets:
        outcome, fields = _verified_detail(
            target,
            details.get(target.url, {}),
        )
        if outcome not in {"live", "removed", "unreachable"}:
            outcome = "unreachable"
        stats[outcome] = int(stats[outcome]) + 1
        identity_type = "unknown"
        if outcome == "live":
            identity_type = str(
                fields.get("publisher_identity_type") or "unknown"
            )
            status = str(
                fields.get("publisher_identity_status") or "unknown"
            )
            confidence = str(
                fields.get("publisher_identity_confidence") or "low"
            )
            if status == "identified":
                stats["would_identify"] = int(stats["would_identify"]) + 1
            else:
                stats["would_remain_unknown"] = (
                    int(stats["would_remain_unknown"]) + 1
                )
            estimated = classify_publisher(
                PublisherMetrics(),
                confidence,
            ).activity_class
            estimated_classes[estimated] += 1
            identity_types[identity_type] += 1
        elif outcome == "unreachable":
            stats["would_remain_unknown"] = (
                int(stats["would_remain_unknown"]) + 1
            )
            identity_types["unknown"] += 1
            estimated_classes["unknown"] += 1
        plan.append(
            {
                "target": target,
                "outcome": outcome,
                "fields": fields,
                "identity_type": identity_type,
            }
        )
    stats["identity_by_type"] = dict(sorted(identity_types.items()))
    stats["estimated_classes"] = dict(sorted(estimated_classes.items()))
    return plan, stats


def _checkpoint_payload(
    *,
    run_id: str,
    plan: Sequence[Mapping[str, object]],
    applied_ids: set[int],
    complete: bool,
) -> dict[str, object]:
    rows = []
    for item in plan:
        target = item["target"]
        assert isinstance(target, GulandPublisherBackfillTarget)
        rows.append(
            {
                "listing_id": target.listing_id,
                "raw_id": target.raw_id,
                "outcome": item["outcome"],
                "state": (
                    "applied"
                    if target.listing_id in applied_ids
                    else "pending"
                ),
            }
        )
    return {
        "run_id": run_id,
        "complete": bool(complete),
        "rows": rows,
    }


def _write_checkpoint(path: Path, payload: Mapping[str, object]) -> None:
    """Atomically persist only non-sensitive progress identifiers and outcomes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                dict(payload),
                stream,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _load_incomplete_checkpoint(root: Path) -> tuple[Path | None, set[int]]:
    root = Path(root)
    if not root.exists():
        return None, set()
    for path in sorted(root.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("complete") is True:
            continue
        rows = payload.get("rows")
        if not isinstance(rows, list):
            continue
        applied = {
            int(row["listing_id"])
            for row in rows
            if isinstance(row, dict)
            and row.get("state") == "applied"
            and str(row.get("listing_id") or "").isdigit()
        }
        return path, applied
    return None, set()


def _merged_live_raw(
    target: GulandPublisherBackfillTarget,
    fields: Mapping[str, object],
    checked_at: str,
) -> dict[str, object]:
    merged = dict(target.raw_data)
    stable_keys = {
        "publisher_identity_status",
        "publisher_identity_type",
        "publisher_identity_confidence",
        "publisher_identity_reason",
        "publisher_key",
        "publisher_source_id",
        "publisher_profile_url",
        "publisher_name",
        "publisher_phone",
    }
    changed = any(merged.get(key) != fields.get(key) for key in stable_keys)
    for key in stable_keys:
        if key in fields:
            merged[key] = fields[key]
        else:
            merged.pop(key, None)
    if changed or not merged.get("publisher_identity_checked_at"):
        merged["publisher_identity_checked_at"] = checked_at
    merged["_publisher_contact_checked"] = True
    merged["contact_phone"] = fields.get("publisher_phone", "")
    if fields.get("publisher_name"):
        merged["seller_name"] = fields["publisher_name"]
    return merged


def _reprocess_changed_raw_ids(raw_ids: Sequence[int]) -> dict[str, object]:
    """Normalize only changed rows; publisher evidence must not rewrite valuation."""
    if not raw_ids:
        return {"processed_ids": []}
    from cleansing.reprocess import reprocess_listings

    return reprocess_listings(raw_ids=list(dict.fromkeys(raw_ids)))


def _apply_plan(
    plan: Sequence[Mapping[str, object]],
    stats: dict[str, object],
    *,
    checkpoint_path: Path,
    run_id: str,
    applied_ids: set[int],
) -> None:
    checked_at_dt = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    checked_at = checked_at_dt.isoformat()
    changed_raw_ids: list[int] = []
    _write_checkpoint(
        checkpoint_path,
        _checkpoint_payload(
            run_id=run_id,
            plan=plan,
            applied_ids=applied_ids,
            complete=False,
        ),
    )
    for item in plan:
        target = item["target"]
        assert isinstance(target, GulandPublisherBackfillTarget)
        if target.listing_id in applied_ids:
            continue
        outcome = str(item["outcome"])
        fields = dict(item.get("fields") or {})
        if outcome == "removed":
            applied_ids.add(target.listing_id)
        else:
            if outcome == "live":
                raw_data = _merged_live_raw(target, fields, checked_at)
                if update_raw_listing_payload(
                    target.raw_id,
                    raw_data,
                    change_kind="guland_publisher_backfill",
                ):
                    changed_raw_ids.append(target.raw_id)
                    stats["raw_updated"] = int(stats["raw_updated"]) + 1
            else:
                raw_data = {
                    "publisher_identity_status": "unreachable",
                    "publisher_identity_type": "unknown",
                    "publisher_identity_confidence": "low",
                    "publisher_identity_reason": "source_unreachable",
                }
            with get_conn() as conn:
                publisher_id = sync_listing_publisher(
                    conn,
                    target.listing_id,
                    raw_data,
                    observed_at=checked_at_dt,
                )
                if publisher_id:
                    record_listing_observation(
                        conn,
                        target.listing_id,
                        checked_at_dt.date(),
                        is_new=False,
                        source_date_changed=False,
                    )
                    recompute_publisher(
                        conn,
                        publisher_id,
                        checked_at_dt.date(),
                    )
            stats["publisher_links_updated"] = (
                int(stats["publisher_links_updated"]) + 1
            )
            applied_ids.add(target.listing_id)
        _write_checkpoint(
            checkpoint_path,
            _checkpoint_payload(
                run_id=run_id,
                plan=plan,
                applied_ids=applied_ids,
                complete=False,
            ),
        )
    _reprocess_changed_raw_ids(changed_raw_ids)
    _write_checkpoint(
        checkpoint_path,
        _checkpoint_payload(
            run_id=run_id,
            plan=plan,
            applied_ids=applied_ids,
            complete=True,
        ),
    )


def run_guland_publisher_backfill(
    *,
    apply: bool,
    limit: int,
    resume: bool = True,
    manifest_root: Path = Path(".local/guland-publisher-backfill"),
) -> dict[str, object]:
    """Plan or apply publisher identity only for live/displayable Guland rows."""
    limit = validate_backfill_limit(limit)
    mode = "apply" if apply else "dry_run"
    try:
        with advisory_lock("crawl-guland"):
            targets, details, cards_scanned = _collect_targets_and_details(limit)
            plan, stats = _build_plan(
                targets,
                details,
                cards_scanned=cards_scanned,
                mode=mode,
            )
            if not apply:
                return stats

            root = Path(manifest_root)
            checkpoint_path = None
            applied_ids: set[int] = set()
            if resume:
                checkpoint_path, applied_ids = _load_incomplete_checkpoint(root)
            if checkpoint_path is None:
                run_id = datetime.now(timezone.utc).strftime(
                    "%Y%m%dT%H%M%S%fZ"
                )
                checkpoint_path = root / f"{run_id}.json"
            else:
                run_id = checkpoint_path.stem
            stats["run_id"] = run_id
            _apply_plan(
                plan,
                stats,
                checkpoint_path=checkpoint_path,
                run_id=run_id,
                applied_ids=applied_ids,
            )
            return stats
    except AdvisoryLockBusy:
        stats = _empty_stats(mode)
        stats["errors"] = 1
        stats["error"] = "guland_crawl_lock_busy"
        return stats
