import json
import uuid
from unittest import mock

from cleansing.reprocess import run_targeted_reprocess
from db.connection import get_conn
from db.listings import upsert_listing
from db.schema import init_schema


def _raw_record(url: str, source_id: str, price_ty: float) -> dict:
    return {
        "url": url,
        "post_id": source_id,
        "source_id": source_id,
        "title": "Guland targeted reprocess",
        "description": "Ban dat Phu Loi Thu Dau Mot",
        "area_name": "Phu Loi",
        "ward": "Phu Loi",
        "price_ty": price_ty,
        "price_per_m2": price_ty * 10,
        "area_m2": 100.0,
        "property_type": "dat_nen",
        "tx_type": "ban",
        "source": "guland",
    }


def _seed_targeted_pair() -> dict:
    init_schema()
    token = uuid.uuid4().hex
    seeded = {}
    with get_conn() as conn:
        for label, price in (("changed", 2.7), ("untouched", 2.1)):
            url = f"https://guland.vn/post/targeted-{label}-{token}"
            source_id = f"{label}-{token}"
            raw = conn.execute(
                """
                INSERT INTO raw_listings
                    (source, source_id, url, raw_json, crawled_at)
                VALUES ('guland', ?, ?, ?, '2026-07-30T10:00:00+07:00')
                """,
                (
                    source_id,
                    url,
                    json.dumps(_raw_record(url, source_id, price)),
                ),
            )
            listing_id, _ = upsert_listing(
                {
                    **_raw_record(url, source_id, 2.5 if label == "changed" else price),
                    "raw_id": raw.lastrowid,
                    "source": "guland",
                },
                crawl_run_id=1,
            )
            seeded[f"{label}_raw_id"] = raw.lastrowid
            seeded[f"{label}_listing_id"] = listing_id
        conn.execute(
            """
            UPDATE listings
            SET updated_at='2026-01-01T00:00:00+07:00'
            WHERE id=?
            """,
            (seeded["untouched_listing_id"],),
        )
    seeded["untouched_updated_at"] = "2026-01-01T00:00:00+07:00"
    return seeded


def _cleanup(seeded: dict) -> None:
    listing_ids = [
        seeded["changed_listing_id"],
        seeded["untouched_listing_id"],
    ]
    raw_ids = [seeded["changed_raw_id"], seeded["untouched_raw_id"]]
    with get_conn() as conn:
        placeholders = ",".join("?" * len(listing_ids))
        for table in (
            "valuation_results",
            "valuation_shadow_results",
            "listing_map_locations",
            "listing_images",
            "price_history",
        ):
            conn.execute(
                f"DELETE FROM {table} WHERE listing_id IN ({placeholders})",
                listing_ids,
            )
        conn.execute(
            f"DELETE FROM listings WHERE id IN ({placeholders})",
            listing_ids,
        )
        raw_placeholders = ",".join("?" * len(raw_ids))
        conn.execute(
            f"DELETE FROM raw_listings WHERE id IN ({raw_placeholders})",
            raw_ids,
        )


def test_targeted_reprocess_only_touches_requested_raw_ids():
    seeded = _seed_targeted_pair()
    try:
        with mock.patch(
            "cleansing.reprocess.reprocess_valuation",
            side_effect=lambda incremental_ids: {
                "total": len(incremental_ids),
                "signals": 0,
                "outliers": 0,
            },
        ), mock.patch(
            "cleansing.reprocess._run_listing_map_backfill",
            return_value={"processed": 1},
        ):
            result = run_targeted_reprocess([seeded["changed_raw_id"]])

        assert result["listings"]["processed_ids"] == [
            seeded["changed_listing_id"]
        ]
        assert result["valuation"]["total"] == 1
        with get_conn() as conn:
            untouched = conn.execute(
                "SELECT updated_at FROM listings WHERE id=?",
                (seeded["untouched_listing_id"],),
            ).fetchone()
        assert untouched["updated_at"] == seeded["untouched_updated_at"]
    finally:
        _cleanup(seeded)
