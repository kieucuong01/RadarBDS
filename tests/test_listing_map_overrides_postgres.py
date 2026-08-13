from __future__ import annotations

import uuid

from db import connection
from db.schema import init_schema
from services.listing_map import MapFilters


def _audit_writer(conn, action, entity_type, entity_id, **kwargs):
    import json

    conn.execute(
        """
        INSERT INTO admin_audit_log (
            actor, action, entity_type, entity_id,
            before_json, after_json, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "integration-admin",
            action,
            entity_type,
            entity_id,
            json.dumps(kwargs.get("before"), ensure_ascii=False),
            json.dumps(kwargs.get("after"), ensure_ascii=False),
            kwargs.get("reason"),
        ),
    )


def _payload(lat, lng):
    return {
        "lat": lat,
        "lng": lng,
        "verification_source": "seller_confirmed",
        "note": "PostgreSQL integration verification.",
        "evidence_url": "",
    }


def test_postgres_effective_location_precedence_and_reset(monkeypatch):
    from services import listing_map
    from services import listing_map_overrides

    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "0")
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "0")
    connection.close_all()
    init_schema()
    token = uuid.uuid4().hex
    location_key = f"road:thu-dau-mot:phu-loi:test-{token}"
    listing_id = None
    future_listing_id = None
    unmapped_listing_id = None

    try:
        with connection.get_conn() as conn:
            listing_id = int(conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, description,
                    source_status, ward, road_name,
                    price_ty, price_per_m2, area_m2
                ) VALUES (?, ?, ?, ?, '', 'active', 'Phú Lợi', 'ĐX 43', 2.0, 20.0, 100.0)
                RETURNING id
                """,
                (
                    "facebook",
                    f"map-override-{token}",
                    f"https://example.invalid/map-override-{token}",
                    f"Map override integration {token}",
                ),
            ).lastrowid)
            conn.execute(
                """
                INSERT INTO listing_map_locations (
                    listing_id, lat, lng, location_precision,
                    location_key, location_label, source,
                    resolver_version, listing_location_signature,
                    accuracy_radius_m, relation
                ) VALUES (?, 11.0101, 106.6101, 'road', ?, ?, 'OpenStreetMap', 'test-v1', ?, 90, 'on')
                """,
                (
                    listing_id,
                    location_key,
                    "Theo tên đường ĐX 43, Phú Lợi",
                    f"signature-{token}",
                ),
            )

        filters = MapFilters(
            sources=("facebook",),
            keyword=token,
            date_range="3m",
        )
        listing_map_overrides.save_group_override(
            location_key,
            _payload(11.0202, 106.6202),
            actor="integration-admin",
            audit_writer=_audit_writer,
        )
        listing_map.clear_listing_map_cache()
        group_payload = listing_map.load_listing_map_summary(
            mode="all",
            tier="admin",
            filters=filters,
        )
        group = group_payload["locations"][0]
        assert (group["lat"], group["lng"]) == (11.0202, 106.6202)
        assert group["manual_override"] == "group"

        with connection.get_conn() as conn:
            future_listing_id = int(conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, description,
                    source_status, ward, road_name,
                    price_ty, price_per_m2, area_m2
                ) VALUES (?, ?, ?, ?, '', 'active', 'Phú Lợi', 'ĐX 43', 2.1, 21.0, 100.0)
                RETURNING id
                """,
                (
                    "facebook",
                    f"map-override-future-{token}",
                    f"https://example.invalid/map-override-future-{token}",
                    f"Map override future {token}",
                ),
            ).lastrowid)
            conn.execute(
                """
                INSERT INTO listing_map_locations (
                    listing_id, lat, lng, location_precision,
                    location_key, location_label, source,
                    resolver_version, listing_location_signature,
                    accuracy_radius_m, relation
                ) VALUES (?, 11.0101, 106.6101, 'road', ?, ?, 'OpenStreetMap', 'test-v1', ?, 90, 'on')
                """,
                (
                    future_listing_id,
                    location_key,
                    "Theo tên đường ĐX 43, Phú Lợi",
                    f"signature-future-{token}",
                ),
            )
        listing_map.clear_listing_map_cache()
        inherited_payload = listing_map.load_listing_map_summary(
            mode="all", tier="admin", filters=filters
        )
        inherited = inherited_payload["locations"][0]
        assert inherited["listing_count"] == 2
        assert (inherited["lat"], inherited["lng"]) == (11.0202, 106.6202)

        listing_map_overrides.save_listing_override(
            listing_id,
            _payload(11.0303, 106.6303),
            actor="integration-admin",
            audit_writer=_audit_writer,
        )
        listing_map.clear_listing_map_cache()
        exact_payload = listing_map.load_listing_map_summary(
            mode="all",
            tier="admin",
            filters=filters,
        )
        exact = exact_payload["locations"][0]
        assert exact["location_key"] == f"exact:{listing_id}"
        assert (exact["lat"], exact["lng"]) == (11.0303, 106.6303)
        assert exact["manual_override"] == "listing"

        listing_map_overrides.reset_listing_override(
            listing_id,
            actor="integration-admin",
            audit_writer=_audit_writer,
        )
        listing_map.clear_listing_map_cache()
        restored_payload = listing_map.load_listing_map_summary(
            mode="all",
            tier="admin",
            filters=filters,
        )
        restored = restored_payload["locations"][0]
        assert restored["location_key"] == location_key
        assert (restored["lat"], restored["lng"]) == (11.0202, 106.6202)
        assert restored["manual_override"] == "group"

        with connection.get_conn() as conn:
            conn.execute(
                """
                UPDATE listing_map_locations
                SET lat=11.0404, lng=106.6404, updated_at=NOW()
                WHERE listing_id=?
                """,
                (listing_id,),
            )
        listing_map.clear_listing_map_cache()
        after_backfill = listing_map.load_listing_map_summary(
            mode="all", tier="admin", filters=filters
        )["locations"][0]
        assert (after_backfill["lat"], after_backfill["lng"]) == (
            11.0202,
            106.6202,
        )

        unmapped_token = f"unmapped-{token}"
        with connection.get_conn() as conn:
            unmapped_listing_id = int(conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, description,
                    source_status, ward, price_ty, price_per_m2, area_m2
                ) VALUES (?, ?, ?, ?, '', 'active', 'Phú Lợi', 1.9, 19.0, 100.0)
                RETURNING id
                """,
                (
                    "facebook",
                    f"map-override-{unmapped_token}",
                    f"https://example.invalid/map-override-{unmapped_token}",
                    f"Map override {unmapped_token}",
                ),
            ).lastrowid)
        listing_map_overrides.save_listing_override(
            unmapped_listing_id,
            _payload(11.0505, 106.6505),
            actor="integration-admin",
            audit_writer=_audit_writer,
        )
        listing_map.clear_listing_map_cache()
        unmapped_payload = listing_map.load_listing_map_summary(
            mode="all",
            tier="admin",
            filters=MapFilters(sources=("facebook",), keyword=unmapped_token),
        )
        unmapped_exact = unmapped_payload["locations"][0]
        assert unmapped_exact["location_key"] == f"exact:{unmapped_listing_id}"
        assert (unmapped_exact["lat"], unmapped_exact["lng"]) == (
            11.0505,
            106.6505,
        )

        with connection.get_conn() as conn:
            audit_rows = conn.execute(
                """
                SELECT action, before_json, after_json
                FROM admin_audit_log
                WHERE actor='integration-admin'
                  AND action LIKE 'map_location_%'
                """
            ).fetchall()
        assert len(audit_rows) >= 4
        assert all(row["after_json"] for row in audit_rows)
    finally:
        if any(
            item is not None
            for item in (listing_id, future_listing_id, unmapped_listing_id)
        ):
            with connection.get_conn() as conn:
                conn.execute(
                    """
                    DELETE FROM admin_audit_log
                    WHERE actor='integration-admin'
                      AND action LIKE 'map_location_%'
                    """
                )
                for cleanup_id in (
                    listing_id,
                    future_listing_id,
                    unmapped_listing_id,
                ):
                    if cleanup_id is not None:
                        conn.execute("DELETE FROM listings WHERE id=?", (cleanup_id,))
        connection.close_all()
