"""PostgreSQL repository for Guland publisher identity and activity."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from services.guland_publisher_activity import (
    PublisherClassification,
    PublisherMetrics,
    classify_publisher,
    effective_publisher_class,
    validated_raw_publisher_fields,
)


_VALID_OVERRIDES = frozenset({"", "allow_manual", "hide_high_activity"})
_VALID_IDENTITY_STATUSES = frozenset({"identified", "unknown", "unreachable"})
_VALID_CONFIDENCE = frozenset({"low", "medium", "high"})
_VALID_EVIDENCE_TYPES = frozenset(
    {"member_id", "profile_url", "listing_phone", "description_phone", "unknown"}
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validated_repository_fields(
    raw_data: Mapping[str, object],
) -> dict[str, object]:
    status = str(raw_data.get("publisher_identity_status") or "").strip()
    publisher_key = str(raw_data.get("publisher_key") or "").strip()
    identity_type = str(
        raw_data.get("publisher_identity_type")
        or raw_data.get("publisher_evidence_type")
        or ""
    ).strip()
    confidence = str(
        raw_data.get("publisher_identity_confidence") or ""
    ).strip()
    if (
        status in _VALID_IDENTITY_STATUSES
        and identity_type in _VALID_EVIDENCE_TYPES
        and confidence in _VALID_CONFIDENCE
        and (
            status != "identified"
            or (
                len(publisher_key) == 64
                and all(ch in "0123456789abcdef" for ch in publisher_key.lower())
            )
        )
    ):
        return {
            "status": status,
            "publisher_key": publisher_key.lower(),
            "identity_type": identity_type,
            "confidence": confidence,
            "display_name": str(raw_data.get("publisher_name") or "").strip()[:240],
        }

    validated = validated_raw_publisher_fields(raw_data)
    return {
        "status": str(validated["publisher_identity_status"]),
        "publisher_key": str(validated["publisher_key"]),
        "identity_type": str(validated["publisher_identity_type"]),
        "confidence": str(validated["publisher_identity_confidence"]),
        "display_name": str(validated["publisher_name"])[:240],
    }


def sync_listing_publisher(
    conn,
    listing_id: int,
    raw_data: Mapping[str, object],
    observed_at: datetime | None = None,
) -> int | None:
    """Idempotently link one Guland listing to validated publisher evidence."""
    listing = conn.execute(
        "SELECT source FROM listings WHERE id=?",
        (listing_id,),
    ).fetchone()
    if not listing or listing["source"] != "guland":
        return None

    observed_at = observed_at or _utc_now()
    fields = _validated_repository_fields(raw_data)
    if fields["status"] != "identified" or not fields["publisher_key"]:
        identity_status = (
            fields["status"]
            if fields["status"] in {"unknown", "unreachable"}
            else "unknown"
        )
        conn.execute(
            """
            INSERT INTO listing_publishers (
                listing_id, publisher_id, identity_status, evidence_type,
                identity_confidence, checked_at, updated_at
            )
            VALUES (?, NULL, ?, ?, ?, ?, ?)
            ON CONFLICT (listing_id) DO UPDATE SET
                publisher_id=NULL,
                identity_status=EXCLUDED.identity_status,
                evidence_type=EXCLUDED.evidence_type,
                identity_confidence=EXCLUDED.identity_confidence,
                checked_at=EXCLUDED.checked_at,
                updated_at=EXCLUDED.updated_at
            """,
            (
                listing_id,
                identity_status,
                fields["identity_type"],
                fields["confidence"],
                observed_at,
                observed_at,
            ),
        )
        return None

    cur = conn.execute(
        """
        INSERT INTO source_publishers (
            source, publisher_key, identity_type, identity_confidence,
            display_name, first_seen_at, last_seen_at
        )
        VALUES ('guland', ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source, publisher_key) DO UPDATE SET
            identity_type=EXCLUDED.identity_type,
            identity_confidence=EXCLUDED.identity_confidence,
            display_name=CASE
                WHEN EXCLUDED.display_name <> '' THEN EXCLUDED.display_name
                ELSE source_publishers.display_name
            END,
            last_seen_at=GREATEST(
                source_publishers.last_seen_at,
                EXCLUDED.last_seen_at
            )
        """,
        (
            fields["publisher_key"],
            fields["identity_type"],
            fields["confidence"],
            fields["display_name"],
            observed_at,
            observed_at,
        ),
    )
    publisher_id = cur.lastrowid
    if publisher_id is None:
        row = conn.execute(
            """
            SELECT id FROM source_publishers
            WHERE source='guland' AND publisher_key=?
            """,
            (fields["publisher_key"],),
        ).fetchone()
        publisher_id = row["id"]

    conn.execute(
        """
        INSERT INTO listing_publishers (
            listing_id, publisher_id, identity_status, evidence_type,
            identity_confidence, checked_at, updated_at
        )
        VALUES (?, ?, 'identified', ?, ?, ?, ?)
        ON CONFLICT (listing_id) DO UPDATE SET
            publisher_id=EXCLUDED.publisher_id,
            identity_status='identified',
            evidence_type=EXCLUDED.evidence_type,
            identity_confidence=EXCLUDED.identity_confidence,
            checked_at=EXCLUDED.checked_at,
            updated_at=EXCLUDED.updated_at
        """,
        (
            listing_id,
            publisher_id,
            fields["identity_type"],
            fields["confidence"],
            observed_at,
            observed_at,
        ),
    )
    return int(publisher_id)


def record_listing_observation(
    conn,
    listing_id: int,
    observed_on: date,
    *,
    is_new: bool,
    source_date_changed: bool,
    near_duplicate_count: int = 0,
    repeated_template: bool = False,
) -> None:
    """Monotonically record one listing/day and rebuild its daily aggregate."""
    link = conn.execute(
        """
        SELECT publisher_id
        FROM listing_publishers
        WHERE listing_id=? AND identity_status='identified'
        """,
        (listing_id,),
    ).fetchone()
    if not link or not link["publisher_id"]:
        return
    publisher_id = int(link["publisher_id"])
    conn.execute(
        """
        INSERT INTO publisher_listing_observations (
            publisher_id, listing_id, activity_date, was_new, was_seen,
            was_bumped, near_duplicate_count, repeated_template
        )
        VALUES (?, ?, ?, ?, TRUE, ?, ?, ?)
        ON CONFLICT (publisher_id, listing_id, activity_date) DO UPDATE SET
            was_new=(
                publisher_listing_observations.was_new OR EXCLUDED.was_new
            ),
            was_seen=TRUE,
            was_bumped=(
                publisher_listing_observations.was_bumped OR EXCLUDED.was_bumped
            ),
            near_duplicate_count=GREATEST(
                publisher_listing_observations.near_duplicate_count,
                EXCLUDED.near_duplicate_count
            ),
            repeated_template=(
                publisher_listing_observations.repeated_template
                OR EXCLUDED.repeated_template
            ),
            observed_at=NOW()
        """,
        (
            publisher_id,
            listing_id,
            observed_on,
            bool(is_new),
            bool(source_date_changed),
            max(0, int(near_duplicate_count or 0)),
            bool(repeated_template),
        ),
    )
    conn.execute(
        """
        INSERT INTO publisher_activity_daily (
            publisher_id, activity_date, new_listing_count,
            seen_listing_count, bump_count, near_duplicate_count,
            repeated_template_count
        )
        SELECT
            publisher_id,
            activity_date,
            COUNT(*) FILTER (WHERE was_new),
            COUNT(*) FILTER (WHERE was_seen),
            COUNT(*) FILTER (WHERE was_bumped),
            COALESCE(SUM(near_duplicate_count), 0),
            COUNT(*) FILTER (WHERE repeated_template)
        FROM publisher_listing_observations
        WHERE publisher_id=? AND activity_date=?
        GROUP BY publisher_id, activity_date
        ON CONFLICT (publisher_id, activity_date) DO UPDATE SET
            new_listing_count=EXCLUDED.new_listing_count,
            seen_listing_count=EXCLUDED.seen_listing_count,
            bump_count=EXCLUDED.bump_count,
            near_duplicate_count=EXCLUDED.near_duplicate_count,
            repeated_template_count=EXCLUDED.repeated_template_count
        """,
        (publisher_id, observed_on),
    )


def record_seen_guland_cards(
    conn,
    cards,
    observed_at: datetime,
) -> dict[str, Any]:
    """Record current Guland cards and preserve source-date bumps in raw history."""
    from db.raw_listings import update_raw_listing_payload

    card_by_url = {
        str(card.get("url") or "").strip(): card
        for card in cards or []
        if str(card.get("url") or "").strip()
    }
    stats: dict[str, Any] = {
        "seen": 0,
        "bumps": 0,
        "changed_raw_ids": [],
    }
    if not card_by_url:
        return stats

    rows = []
    urls = list(card_by_url)
    for start in range(0, len(urls), 500):
        chunk = urls[start:start + 500]
        placeholders = ",".join("?" * len(chunk))
        rows.extend(
            conn.execute(
                f"""
                SELECT r.id AS raw_id, r.url, r.raw_json, l.id AS listing_id
                FROM raw_listings r
                JOIN listings l ON l.raw_id=r.id
                WHERE r.source='guland' AND r.url IN ({placeholders})
                """,
                chunk,
            ).fetchall()
        )

    observed_on = observed_at.date()
    affected_publishers: set[int] = set()
    for row in rows:
        try:
            raw_data = json.loads(row["raw_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            raw_data = {}
        card = card_by_url.get(str(row["url"] or ""))
        if card is None:
            continue

        old_date_raw = str(raw_data.get("date_raw") or "").strip()
        new_date_raw = str(card.get("date_raw") or "").strip()
        source_date_changed = bool(
            new_date_raw and new_date_raw != old_date_raw
        )
        if source_date_changed:
            updated_raw = dict(raw_data)
            updated_raw["date_raw"] = new_date_raw
            if update_raw_listing_payload(
                int(row["raw_id"]),
                updated_raw,
                change_kind="guland_source_bump",
                conn=conn,
            ):
                stats["changed_raw_ids"].append(int(row["raw_id"]))

        record_listing_observation(
            conn,
            int(row["listing_id"]),
            observed_on,
            is_new=False,
            source_date_changed=source_date_changed,
        )
        link = conn.execute(
            """
            SELECT publisher_id FROM listing_publishers
            WHERE listing_id=? AND publisher_id IS NOT NULL
            """,
            (row["listing_id"],),
        ).fetchone()
        if link:
            affected_publishers.add(int(link["publisher_id"]))
            stats["seen"] += 1
            if source_date_changed:
                stats["bumps"] += 1

    for publisher_id in affected_publishers:
        recompute_publisher(conn, publisher_id, observed_on)
    return stats


def recompute_publisher(
    conn,
    publisher_id: int,
    as_of: date | None = None,
) -> PublisherClassification:
    """Recompute rolling metrics and persist the deterministic activity class."""
    as_of = as_of or date.today()
    start = as_of - timedelta(days=29)
    rows = conn.execute(
        """
        SELECT activity_date, new_listing_count, seen_listing_count,
               bump_count, near_duplicate_count, repeated_template_count
        FROM publisher_activity_daily
        WHERE publisher_id=? AND activity_date BETWEEN ? AND ?
        ORDER BY activity_date
        """,
        (publisher_id, start, as_of),
    ).fetchall()
    publisher = conn.execute(
        """
        SELECT identity_confidence
        FROM source_publishers WHERE id=?
        """,
        (publisher_id,),
    ).fetchone()
    if not publisher:
        raise ValueError("publisher not found")

    def within(day_value: date, days: int) -> bool:
        return day_value >= as_of - timedelta(days=days - 1)

    metrics = PublisherMetrics(
        new_1d=sum(
            int(row["new_listing_count"]) for row in rows
            if row["activity_date"] == as_of
        ),
        new_7d=sum(
            int(row["new_listing_count"]) for row in rows
            if within(row["activity_date"], 7)
        ),
        new_30d=sum(int(row["new_listing_count"]) for row in rows),
        max_new_on_day=max(
            (int(row["new_listing_count"]) for row in rows),
            default=0,
        ),
        active_days_30d=sum(
            1 for row in rows if int(row["seen_listing_count"]) > 0
        ),
        bumps_7d=sum(
            int(row["bump_count"]) for row in rows
            if within(row["activity_date"], 7)
        ),
        bumps_30d=sum(int(row["bump_count"]) for row in rows),
        near_duplicates_max_day=max(
            (int(row["near_duplicate_count"]) for row in rows),
            default=0,
        ),
        days_ge_15_with_templates_14d=sum(
            1
            for row in rows
            if within(row["activity_date"], 14)
            and int(row["new_listing_count"]) >= 15
            and int(row["repeated_template_count"]) > 0
        ),
    )
    classification = classify_publisher(
        metrics,
        str(publisher["identity_confidence"]),
    )
    conn.execute(
        """
        UPDATE source_publishers
        SET activity_class=?, activity_reason=?, metrics_json=?,
            last_classified_at=NOW()
        WHERE id=?
        """,
        (
            classification.activity_class,
            classification.reason,
            json.dumps(metrics.__dict__, ensure_ascii=False, sort_keys=True),
            publisher_id,
        ),
    )
    return classification


def set_publisher_override(
    conn,
    publisher_id: int,
    override: str,
    actor: str,
) -> dict[str, Any]:
    """Set/clear an admin override and append an audit record."""
    if override not in _VALID_OVERRIDES:
        raise ValueError("invalid publisher override")
    row = conn.execute(
        """
        SELECT activity_class, activity_reason, manual_override
        FROM source_publishers WHERE id=?
        """,
        (publisher_id,),
    ).fetchone()
    if not row:
        raise ValueError("publisher not found")
    before = {
        "activity_class": row["activity_class"],
        "manual_override": row["manual_override"],
    }
    conn.execute(
        """
        UPDATE source_publishers
        SET manual_override=?, last_classified_at=NOW()
        WHERE id=?
        """,
        (override, publisher_id),
    )
    after = {
        "activity_class": row["activity_class"],
        "manual_override": override,
    }
    conn.execute(
        """
        INSERT INTO admin_audit_log (
            actor, action, entity_type, entity_id,
            before_json, after_json, reason
        )
        VALUES (?, 'guland_publisher_override', 'guland_publisher', ?, ?, ?, ?)
        """,
        (
            str(actor or "admin"),
            publisher_id,
            json.dumps(before, ensure_ascii=False, sort_keys=True),
            json.dumps(after, ensure_ascii=False, sort_keys=True),
            row["activity_reason"],
        ),
    )
    return {
        **after,
        "publisher_id": publisher_id,
        "effective_class": effective_publisher_class(
            str(row["activity_class"]),
            override,
        ),
    }


def list_publishers(
    conn,
    *,
    activity_class: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return an admin-safe publisher QC page without identity material."""
    valid_classes = {
        "",
        "unknown",
        "low_manual",
        "high_activity",
        "automated_repost",
    }
    if activity_class not in valid_classes:
        raise ValueError("invalid publisher activity class")

    effective_class_sql = """
        CASE sp.manual_override
          WHEN 'allow_manual' THEN 'low_manual'
          WHEN 'hide_high_activity' THEN 'high_activity'
          ELSE sp.activity_class
        END
    """
    where_sql = "WHERE sp.source='guland'"
    params: list[Any] = []
    if activity_class:
        where_sql += f" AND ({effective_class_sql})=?"
        params.append(activity_class)

    total_row = conn.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM source_publishers sp
        {where_sql}
        """,
        params,
    ).fetchone()
    rows = conn.execute(
        f"""
        SELECT
            sp.id,
            sp.display_name,
            sp.activity_class,
            ({effective_class_sql}) AS effective_class,
            sp.identity_confidence,
            sp.activity_reason,
            sp.manual_override,
            sp.metrics_json,
            sp.last_seen_at,
            (
                SELECT COUNT(*)
                FROM listing_publishers lp
                WHERE lp.publisher_id=sp.id
            ) AS linked_listing_count
        FROM source_publishers sp
        {where_sql}
        ORDER BY
            CASE ({effective_class_sql})
              WHEN 'automated_repost' THEN 0
              WHEN 'high_activity' THEN 1
              WHEN 'unknown' THEN 2
              WHEN 'low_manual' THEN 3
              ELSE 2
            END,
            sp.last_seen_at DESC,
            sp.id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        metrics = row["metrics_json"] or {}
        if isinstance(metrics, str):
            try:
                metrics = json.loads(metrics)
            except (TypeError, ValueError):
                metrics = {}
        if not isinstance(metrics, dict):
            metrics = {}
        last_seen = row["last_seen_at"]
        items.append(
            {
                "id": int(row["id"]),
                "display_name": str(row["display_name"] or ""),
                "activity_class": str(row["activity_class"] or "unknown"),
                "effective_class": str(
                    row["effective_class"] or "unknown"
                ),
                "identity_confidence": str(
                    row["identity_confidence"] or "low"
                ),
                "activity_reason": str(row["activity_reason"] or ""),
                "manual_override": str(row["manual_override"] or ""),
                "metrics": metrics,
                "linked_listing_count": int(
                    row["linked_listing_count"] or 0
                ),
                "last_seen_at": (
                    last_seen.isoformat()
                    if hasattr(last_seen, "isoformat")
                    else str(last_seen or "")
                ),
            }
        )
    return {
        "items": items,
        "total": int(total_row["total"] or 0),
        "limit": int(limit),
        "offset": int(offset),
    }


def publisher_visibility_sql(
    alias: str = "l",
    include_high_activity: bool = False,
) -> str:
    """Return the shared public fail-open Guland publisher predicate."""
    if include_high_activity:
        return "1=1"
    return f"""
    (
      {alias}.source <> 'guland'
      OR NOT EXISTS (
          SELECT 1
          FROM listing_publishers lp
          JOIN source_publishers sp ON sp.id = lp.publisher_id
          WHERE lp.listing_id = {alias}.id
            AND CASE sp.manual_override
                  WHEN 'allow_manual' THEN 'low_manual'
                  WHEN 'hide_high_activity' THEN 'automated_repost'
                  ELSE sp.activity_class
                END IN ('high_activity', 'automated_repost')
      )
    )
    """.strip()


def publisher_sort_rank_sql(alias: str = "l") -> str:
    """Return the shared publisher-class rank without exposing identity."""
    return f"""
    CASE
      WHEN {alias}.source <> 'guland' THEN 0
      ELSE COALESCE((
        SELECT CASE
          WHEN sp.manual_override = 'allow_manual' THEN 0
          WHEN sp.manual_override = 'hide_high_activity' THEN 3
          WHEN sp.activity_class = 'low_manual' THEN 0
          WHEN sp.activity_class = 'unknown' THEN 1
          WHEN sp.activity_class = 'high_activity' THEN 2
          WHEN sp.activity_class = 'automated_repost' THEN 3
          ELSE 1
        END
        FROM listing_publishers lp
        JOIN source_publishers sp ON sp.id = lp.publisher_id
        WHERE lp.listing_id = {alias}.id
      ), 1)
    END
    """.strip()
