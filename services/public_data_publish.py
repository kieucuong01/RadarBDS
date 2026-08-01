"""Transactional publication boundary for public PostgreSQL read models."""

from dataclasses import asdict
import logging
import os

from db.connection import get_conn
from services.public_cache import publish_dataset_versions
from services.public_prewarm import prewarm_configured_routes
from services.signal_read_model import (
    analyze_public_read_tables,
    refresh_signal_card_read_model,
)


logger = logging.getLogger(__name__)


def _with_duplicate_parents(conn, listing_ids):
    if listing_ids is None:
        return None
    ids = tuple(
        dict.fromkeys(int(value) for value in listing_ids if int(value) > 0)
    )
    if not ids:
        return ()
    markers = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT duplicate_of_id
        FROM listings
        WHERE id IN ({markers})
          AND duplicate_of_id IS NOT NULL
        """,
        ids,
    ).fetchall()
    parents = tuple(
        int(row["duplicate_of_id"])
        for row in rows
        if row["duplicate_of_id"]
    )
    return tuple(dict.fromkeys((*ids, *parents)))


def publish_public_data(
    *,
    listing_ids: tuple[int, ...] | None,
    market_changed: bool = False,
    strict: bool = False,
) -> dict:
    try:
        with get_conn() as conn:
            expanded_ids = _with_duplicate_parents(conn, listing_ids)
            result = refresh_signal_card_read_model(
                conn,
                listing_ids=expanded_ids,
                market_changed=market_changed,
            )
            if expanded_ids is None or len(expanded_ids) >= 500:
                analyze_public_read_tables(conn)
    except Exception as exc:
        logger.exception("Public signal read-model publication failed")
        if strict:
            raise
        return {"status": "error", "error": str(exc)}

    cache_report = {
        "version_mirror": {"status": "pending"},
        "prewarm": {"status": "disabled"},
    }
    try:
        publish_dataset_versions(result.versions)
        cache_report["version_mirror"] = {"status": "ok"}
    except Exception as exc:
        logger.exception("Public dataset version mirror failed after commit")
        cache_report["version_mirror"] = {
            "status": "error",
            "error": str(exc),
        }

    if os.getenv("RADAR_PUBLIC_CACHE_ENABLED", "0").strip() == "1":
        try:
            prewarm_result = prewarm_configured_routes()
            cache_report["prewarm"] = {
                "status": (
                    "ok" if prewarm_result.get("failed", 0) == 0 else "partial"
                ),
                **prewarm_result,
            }
        except Exception as exc:
            logger.exception("Public route prewarm failed after commit")
            cache_report["prewarm"] = {
                "status": "error",
                "error": str(exc),
            }

    return {"status": "ok", **asdict(result), "cache": cache_report}
