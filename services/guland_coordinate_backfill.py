"""Dry-run-first Guland source-coordinate backfill orchestration."""
from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from crawler.base_crawler import _normalize_playwright_browser_path_env
from crawler.guland_pw import GulandCrawler
from db.guland_coordinates import (
    GulandCoordinateTarget,
    GulandCoordinateUpdate,
    load_active_guland_coordinate_targets,
    merge_raw_coordinate_updates,
    restore_raw_coordinate_snapshot,
    snapshot_raw_coordinate_fields,
)
from services.guland_coordinates import (
    evaluate_guland_coordinate_url,
    guland_identity_matches,
    normalize_guland_post_url,
    raw_coordinate_fields,
)
from services.listing_location_backfill import backfill_listing_locations


_MANIFEST_KEYS = (
    "raw_id",
    "listing_id",
    "source_lat",
    "source_lng",
    "source_coordinate_url",
    "source_coordinate_provider",
    "source_coordinate_captured_at",
)
_MAX_MANIFEST_BYTES = 5 * 1024 * 1024
_RUN_ID_RE = re.compile(r"\d{8}T\d{6}Z")


def _collect_cards(
    targets: Sequence[GulandCoordinateTarget],
) -> list[dict]:
    _normalize_playwright_browser_path_env()
    from playwright.sync_api import sync_playwright

    crawler = GulandCrawler()
    target_urls = {
        normalized[0]
        for target in targets
        if (normalized := normalize_guland_post_url(target.url)) is not None
    }
    if not target_urls:
        return []
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
                    incremental=False,
                )
                for card in cards:
                    normalized = normalize_guland_post_url(
                        card.get("url", "")
                    )
                    if normalized is not None:
                        cards_by_url.setdefault(normalized[0], card)
                if target_urls.issubset(cards_by_url):
                    break
        finally:
            browser.close()
    return list(cards_by_url.values())


def _empty_stats(eligible: int) -> dict[str, object]:
    return {
        "eligible": eligible,
        "cards_scanned": 0,
        "matched": 0,
        "coordinate_links": 0,
        "valid": 0,
        "invalid": 0,
        "outside_ward": 0,
        "missing": 0,
        "errors": 0,
        "would_update": 0,
        "would_upgrade_to_exact": 0,
        "raw_updated": 0,
        "map_exact_updated": 0,
        "map_unchanged": 0,
        "run_id": "",
    }


def _build_update_plan(
    targets: Sequence[GulandCoordinateTarget],
    cards: Sequence[Mapping[str, object]],
    *,
    captured_at: str,
) -> tuple[list[GulandCoordinateUpdate], dict[str, object]]:
    stats = _empty_stats(len(targets))
    cards_by_url: dict[str, Mapping[str, object]] = {}
    for card in cards:
        normalized = normalize_guland_post_url(str(card.get("url") or ""))
        if normalized is not None:
            cards_by_url.setdefault(normalized[0], card)
    stats["cards_scanned"] = len(cards_by_url)

    updates: list[GulandCoordinateUpdate] = []
    for target in targets:
        if not target.raw_json_valid:
            stats["invalid"] += 1
            stats["errors"] += 1
            continue
        normalized_target = normalize_guland_post_url(target.url)
        if normalized_target is None:
            stats["invalid"] += 1
            stats["errors"] += 1
            continue
        card = cards_by_url.get(normalized_target[0])
        if card is None:
            stats["missing"] += 1
            continue
        if not guland_identity_matches(
            str(card.get("url") or ""),
            target.url,
            str(card.get("post_id") or ""),
            target.source_id,
        ):
            stats["invalid"] += 1
            stats["errors"] += 1
            continue
        stats["matched"] += 1
        source_coordinate_url = str(
            card.get("source_coordinate_url") or ""
        ).strip()
        if source_coordinate_url:
            stats["coordinate_links"] += 1
        decision = evaluate_guland_coordinate_url(
            source_coordinate_url,
            city=target.city,
            ward=target.ward,
            context_text=target.context_text,
        )
        if decision.status == "missing":
            stats["missing"] += 1
            continue
        if decision.status == "invalid":
            stats["invalid"] += 1
            if decision.reason == "outside_canonical_ward":
                stats["outside_ward"] += 1
            continue
        stats["valid"] += 1
        fields = raw_coordinate_fields(decision, captured_at)
        stable_keys = {
            key
            for key in fields
            if key != "source_coordinate_captured_at"
        }
        needs_update = any(
            target.existing_coordinate_fields.get(key) != fields[key]
            for key in stable_keys
        )
        if not needs_update:
            continue
        updates.append(GulandCoordinateUpdate(
            raw_id=target.raw_id,
            listing_id=target.listing_id,
            fields=fields,
        ))
        stats["would_update"] += 1
        if target.existing_map_precision != "exact":
            stats["would_upgrade_to_exact"] += 1
    return updates, stats


def _manifest_row(row: Mapping[str, object]) -> dict[str, object]:
    unknown = set(row) - set(_MANIFEST_KEYS)
    if unknown:
        raise ValueError("manifest row contains unsupported keys")
    missing = set(_MANIFEST_KEYS) - set(row)
    if missing:
        raise ValueError("manifest row is missing required keys")
    return {key: row.get(key) for key in _MANIFEST_KEYS}


def _atomic_write_manifest(
    path: Path,
    rows: Sequence[Mapping[str, object]],
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"rollback manifest already exists: {path.name}")
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(
                    _manifest_row(row),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ))
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


def _load_manifest(
    manifest_root: Path,
    rollback_run: str,
) -> list[dict[str, object]]:
    if _RUN_ID_RE.fullmatch(str(rollback_run or "")) is None:
        raise ValueError("invalid rollback run id")
    root = Path(manifest_root).resolve()
    path = (root / f"{rollback_run}-before.jsonl").resolve()
    if path.parent != root:
        raise ValueError("invalid rollback manifest path")
    if path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("rollback manifest is too large")
    rows: list[dict[str, object]] = []
    raw_ids: set[int] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("rollback manifest is not valid UTF-8") from exc
    for line in lines:
        if not line.strip():
            raise ValueError("rollback manifest contains an empty line")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("rollback manifest contains invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("rollback manifest row is not an object")
        row = _manifest_row(value)
        try:
            raw_id = int(row["raw_id"])
            listing_id = int(row["listing_id"])
        except (TypeError, ValueError) as exc:
            raise ValueError("rollback manifest has invalid IDs") from exc
        if raw_id <= 0 or listing_id <= 0:
            raise ValueError("rollback manifest has invalid IDs")
        if raw_id in raw_ids:
            raise ValueError("rollback manifest has duplicate raw IDs")
        raw_ids.add(raw_id)
        row["raw_id"] = raw_id
        row["listing_id"] = listing_id
        rows.append(row)
    return rows


def _rollback(
    *,
    rollback_run: str,
    manifest_root: Path,
) -> dict[str, object]:
    rows = _load_manifest(manifest_root, rollback_run)
    restored_listing_ids = restore_raw_coordinate_snapshot(rows)
    map_stats = (
        backfill_listing_locations(listing_ids=restored_listing_ids)
        if restored_listing_ids
        else {}
    )
    return {
        "run_id": rollback_run,
        "rollback_restored": len(restored_listing_ids),
        "map_exact": int(map_stats.get("exact", 0)),
        "map_updated": (
            int(map_stats.get("inserted", 0))
            + int(map_stats.get("updated", 0))
        ),
        "errors": 0,
    }


def run_guland_coordinate_backfill(
    *,
    apply: bool = False,
    rollback_run: str = "",
    manifest_root: Path = Path(".local/guland-coordinate-backfill"),
    now: datetime | None = None,
) -> dict[str, object]:
    if apply and rollback_run:
        raise ValueError("apply and rollback are mutually exclusive")
    if rollback_run:
        return _rollback(
            rollback_run=rollback_run,
            manifest_root=manifest_root,
        )

    run_at = now or datetime.now(timezone.utc)
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=timezone.utc)
    run_id = run_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    captured_at = run_at.astimezone(
        ZoneInfo("Asia/Ho_Chi_Minh")
    ).isoformat()

    targets = load_active_guland_coordinate_targets()
    cards = _collect_cards(targets)
    updates, stats = _build_update_plan(
        targets,
        cards,
        captured_at=captured_at,
    )
    if not apply or not updates:
        return stats

    snapshots = snapshot_raw_coordinate_fields(
        [update.raw_id for update in updates]
    )
    expected_raw_ids = {update.raw_id for update in updates}
    if (
        len(snapshots) != len(expected_raw_ids)
        or {int(row["raw_id"]) for row in snapshots} != expected_raw_ids
    ):
        raise ValueError("coordinate snapshot does not match update plan")
    manifest_path = (
        Path(manifest_root) / f"{run_id}-before.jsonl"
    )
    _atomic_write_manifest(manifest_path, snapshots)

    changed_ids = merge_raw_coordinate_updates(updates)
    map_stats = (
        backfill_listing_locations(listing_ids=changed_ids)
        if changed_ids
        else {"inserted": 0, "updated": 0, "unchanged": 0, "exact": 0}
    )
    if int(map_stats.get("exact", 0)) != len(changed_ids):
        raise RuntimeError(
            "map exact count does not match changed Guland listings"
        )
    stats["raw_updated"] = len(changed_ids)
    stats["map_exact_updated"] = (
        int(map_stats.get("inserted", 0))
        + int(map_stats.get("updated", 0))
    )
    stats["map_unchanged"] = int(map_stats.get("unchanged", 0))
    stats["run_id"] = run_id
    return stats
