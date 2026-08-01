"""Transactional publication boundary for public PostgreSQL read models."""

from dataclasses import asdict
import logging

from db.connection import get_conn
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
        return {"status": "ok", **asdict(result)}
    except Exception as exc:
        logger.exception("Public signal read-model publication failed")
        if strict:
            raise
        return {"status": "error", "error": str(exc)}
