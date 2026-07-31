import json
import uuid
from dataclasses import replace

import pytest

from db import connection
from db.schema import init_schema
from services import guland_publisher_backfill as service
from services.guland_publisher_backfill import (
    GulandPublisherBackfillTarget,
    load_guland_publisher_backfill_targets,
    run_guland_publisher_backfill,
    validate_backfill_limit,
)


@pytest.fixture()
def scoped_targets():
    init_schema()
    token = uuid.uuid4().hex
    seeded: dict[str, int] = {}
    raw_ids: list[int] = []
    listing_ids: list[int] = []
    with connection.get_conn() as conn:
        for index, status in enumerate(
            ("active", "inactive", "unknown", "unreachable", "unknown_checked"),
            start=1,
        ):
            source_status = status.replace("_checked", "")
            source_id = str(880000 + index)
            url = f"https://guland.vn/post/scope-{token}-{source_id}"
            raw_data = {
                "url": url,
                "source": "guland",
                "post_id": source_id,
                "source_id": source_id,
                "title": f"Scope {status}",
            }
            raw_id = conn.execute(
                """
                INSERT INTO raw_listings (source, source_id, url, raw_json)
                VALUES ('guland', ?, ?, ?)
                """,
                (source_id, url, json.dumps(raw_data)),
            ).lastrowid
            listing_id = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, source_status,
                    is_active, probably_sold, review_hidden
                )
                VALUES (?, 'guland', ?, ?, ?, ?, ?, 0, 0)
                """,
                (
                    raw_id,
                    source_id,
                    url,
                    f"Scope {status}",
                    source_status,
                    int(source_status != "inactive"),
                ),
            ).lastrowid
            if status == "unknown_checked":
                conn.execute(
                    """
                    INSERT INTO listing_publishers (
                        listing_id, publisher_id, identity_status,
                        evidence_type, identity_confidence, checked_at
                    )
                    VALUES (?, NULL, 'unknown', 'unknown', 'low', NOW())
                    """,
                    (listing_id,),
                )
            seeded[status] = listing_id
            raw_ids.append(raw_id)
            listing_ids.append(listing_id)
    try:
        yield seeded
    finally:
        with connection.get_conn() as conn:
            placeholders = ",".join("?" * len(listing_ids))
            conn.execute(
                f"DELETE FROM listings WHERE id IN ({placeholders})",
                listing_ids,
            )
            raw_placeholders = ",".join("?" * len(raw_ids))
            conn.execute(
                f"DELETE FROM raw_listings WHERE id IN ({raw_placeholders})",
                raw_ids,
            )


def test_target_loader_includes_only_active_and_never_checked_retry(
    scoped_targets,
):
    targets = load_guland_publisher_backfill_targets(limit=10)
    ids = [target.listing_id for target in targets]

    assert ids == [
        scoped_targets["active"],
        scoped_targets["unknown"],
        scoped_targets["unreachable"],
    ]
    assert scoped_targets["inactive"] not in ids
    assert scoped_targets["unknown_checked"] not in ids


@pytest.mark.parametrize("value", [0, -1, 501])
def test_backfill_limit_rejects_unbounded_values(value):
    with pytest.raises(ValueError, match="between 1 and 500"):
        validate_backfill_limit(value)


def test_dry_run_never_calls_mutation_functions(monkeypatch):
    identified = GulandPublisherBackfillTarget(
        listing_id=101,
        raw_id=201,
        url="https://guland.vn/post/dry-900101",
        source_id="900101",
        source_status="active",
        publisher_status="unchecked",
        raw_data={"title": "Identified target"},
    )
    unknown = replace(
        identified,
        listing_id=102,
        raw_id=202,
        url="https://guland.vn/post/dry-900102",
        source_id="900102",
        raw_data={"title": "Unknown target"},
    )
    details = {
        identified.url: {
            "url": identified.url,
            "http_status": 200,
            "page_status": "live",
            "publisher_source_id": "member-identified",
            "description": "",
        },
        unknown.url: {
            "url": unknown.url,
            "http_status": 200,
            "page_status": "live",
            "description": "Không có thông tin liên hệ",
        },
    }
    monkeypatch.setattr(
        service,
        "_collect_targets_and_details",
        lambda limit: ([identified, unknown], details, 2),
    )
    monkeypatch.setattr(
        service,
        "GULAND_PUBLISHER_KEY_SECRET",
        "dry-run-test-secret-" + ("x" * 40),
    )

    def mutation_forbidden(*_args, **_kwargs):
        raise AssertionError("dry-run attempted mutation")

    for name in (
        "update_raw_listing_payload",
        "sync_listing_publisher",
        "_reprocess_changed_raw_ids",
        "_write_checkpoint",
    ):
        monkeypatch.setattr(service, name, mutation_forbidden, raising=False)

    stats = run_guland_publisher_backfill(apply=False, limit=10)

    assert stats["mode"] == "dry_run"
    assert stats["would_identify"] == 1
    assert stats["would_remain_unknown"] == 1
    assert stats["raw_updated"] == 0
    assert stats["publisher_links_updated"] == 0
    assert stats["identity_by_type"] == {"member_id": 1, "unknown": 1}


def test_apply_preserves_listing_assets_price_and_valuation(
    monkeypatch,
    tmp_path,
):
    init_schema()
    token = uuid.uuid4().hex
    source_id = "990101"
    url = f"https://guland.vn/post/apply-{token}-{source_id}"
    raw_id = listing_id = publisher_id = None
    raw_data = {
        "url": url,
        "post_id": source_id,
        "source_id": source_id,
        "source": "guland",
        "title": "Backfill preservation",
        "description": "Bán đất Tân An",
        "area_name": "Tân An",
        "ward": "Tân An",
        "price_ty": 2.0,
        "price_per_m2": 20.0,
        "area_m2": 100.0,
        "property_type": "dat_nen",
        "date_raw": "Hôm nay",
    }
    try:
        with connection.get_conn() as conn:
            raw_id = conn.execute(
                """
                INSERT INTO raw_listings (source, source_id, url, raw_json)
                VALUES ('guland', ?, ?, ?)
                """,
                (source_id, url, json.dumps(raw_data)),
            ).lastrowid
            listing_id = conn.execute(
                """
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description,
                    ward, area, area_m2, price_ty, price_per_m2,
                    property_type, first_seen_at, posted_at,
                    price_updated_at, source_status, is_active
                )
                VALUES (
                    ?, 'guland', ?, ?, ?, ?, 'Tân An', 'Tân An',
                    100, 2, 20, 'dat_nen',
                    '2026-07-01T08:00:00+07:00', '2026-07-01',
                    '2026-07-15T09:00:00+07:00', 'active', 1
                )
                """,
                (
                    raw_id,
                    source_id,
                    url,
                    raw_data["title"],
                    raw_data["description"],
                ),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO price_history (listing_id, price_ty, price_per_m2)
                VALUES (?, 2, 20)
                """,
                (listing_id,),
            )
            conn.execute(
                """
                INSERT INTO listing_images (listing_id, img_url, img_order)
                VALUES (?, ?, 0)
                """,
                (listing_id, f"https://images.test/{token}.jpg"),
            )
            conn.execute(
                """
                INSERT INTO valuation_results (
                    listing_id, fair_ppm2, actual_ppm2, mos_pct, is_signal
                )
                VALUES (?, 25, 20, 20, 1)
                """,
                (listing_id,),
            )
            conn.execute(
                """
                INSERT INTO listing_map_locations (
                    listing_id, lat, lng, location_precision, location_key,
                    location_label, source, resolver_version,
                    listing_location_signature, resolution_status
                )
                VALUES (
                    ?, 11.01, 106.65, 'exact', ?, 'Tân An',
                    'guland', 'test-v1', ?, 'resolved'
                )
                """,
                (listing_id, f"apply:{token}", f"sig:{token}"),
            )

        detail = {
            "url": url,
            "http_status": 200,
            "page_status": "live",
            "publisher_source_id": f"member-{token}",
            "publisher_name": "Publisher Backfill",
            "description": raw_data["description"],
        }

        def collect(_limit):
            with connection.get_conn() as conn:
                row = conn.execute(
                    """
                    SELECT r.raw_json, l.source_status
                    FROM raw_listings r
                    JOIN listings l ON l.raw_id=r.id
                    WHERE r.id=?
                    """,
                    (raw_id,),
                ).fetchone()
            target = GulandPublisherBackfillTarget(
                listing_id=listing_id,
                raw_id=raw_id,
                url=url,
                source_id=source_id,
                source_status=row["source_status"],
                publisher_status="unchecked",
                raw_data=json.loads(row["raw_json"]),
            )
            return [target], {url: detail}, 1

        monkeypatch.setattr(service, "_collect_targets_and_details", collect)
        monkeypatch.setattr(
            service,
            "GULAND_PUBLISHER_KEY_SECRET",
            "apply-test-secret-" + ("x" * 48),
        )

        with connection.get_conn() as conn:
            before = dict(
                conn.execute(
                    """
                    SELECT first_seen_at, posted_at, price_ty,
                           price_updated_at, source_id
                    FROM listings WHERE id=?
                    """,
                    (listing_id,),
                ).fetchone().items()
            )
            before_counts = {
                table: conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE listing_id=?",
                    (listing_id,),
                ).fetchone()["n"]
                for table in (
                    "price_history",
                    "listing_images",
                    "listing_map_locations",
                    "valuation_results",
                )
            }

        first = run_guland_publisher_backfill(
            apply=True,
            limit=10,
            manifest_root=tmp_path,
        )
        second = run_guland_publisher_backfill(
            apply=True,
            limit=10,
            manifest_root=tmp_path,
        )

        with connection.get_conn() as conn:
            after = dict(
                conn.execute(
                    """
                    SELECT first_seen_at, posted_at, price_ty,
                           price_updated_at, source_id
                    FROM listings WHERE id=?
                    """,
                    (listing_id,),
                ).fetchone().items()
            )
            after_counts = {
                table: conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE listing_id=?",
                    (listing_id,),
                ).fetchone()["n"]
                for table in (
                    "price_history",
                    "listing_images",
                    "listing_map_locations",
                    "valuation_results",
                )
            }
            link = conn.execute(
                """
                SELECT publisher_id FROM listing_publishers WHERE listing_id=?
                """,
                (listing_id,),
            ).fetchone()
            publisher_id = link["publisher_id"]
            observation_count = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM publisher_listing_observations
                WHERE publisher_id=? AND listing_id=?
                """,
                (publisher_id, listing_id),
            ).fetchone()["n"]

        assert first["raw_updated"] == 1
        assert second["raw_updated"] == 0
        assert after == before
        assert after_counts == before_counts
        assert observation_count == 1
        checkpoint_text = " ".join(
            path.read_text(encoding="utf-8")
            for path in tmp_path.glob("*.json")
        )
        assert "member-" not in checkpoint_text
        assert "publisher_key" not in checkpoint_text
        assert "apply-test-secret" not in checkpoint_text
    finally:
        with connection.get_conn() as conn:
            if listing_id:
                conn.execute("DELETE FROM listings WHERE id=?", (listing_id,))
            if raw_id:
                conn.execute("DELETE FROM raw_listings WHERE id=?", (raw_id,))
            if publisher_id:
                conn.execute(
                    "DELETE FROM source_publishers WHERE id=?",
                    (publisher_id,),
                )
