from dataclasses import dataclass
import json
import uuid

import pytest

from db.connection import get_conn
from db.schema import init_schema


@dataclass
class SnapshotCase:
    listing_ids: list[int]
    target_id: int
    previous_max_run_id: int

    def read_state(self, conn=None):
        if conn is None:
            with get_conn() as opened:
                return self.read_state(opened)
        placeholders = ",".join("?" for _ in self.listing_ids)
        params = list(self.listing_ids)
        main = [tuple(row) for row in conn.execute(
            f"""
            SELECT listing_id, model_run_id, crawl_run_id, fair_ppm2,
                   actual_ppm2, mos_pct, is_signal
            FROM valuation_results
            WHERE listing_id IN ({placeholders})
            ORDER BY listing_id, id
            """,
            params,
        ).fetchall()]
        shadow = [tuple(row) for row in conn.execute(
            f"""
            SELECT listing_id, model_run_id, fair_ppm2, actual_ppm2,
                   mos_pct, is_signal
            FROM valuation_shadow_results
            WHERE listing_id IN ({placeholders})
            ORDER BY listing_id, id
            """,
            params,
        ).fetchall()]
        listings = [tuple(row) for row in conn.execute(
            f"""
            SELECT id, is_outlier, outlier_direction, outlier_sigma
            FROM listings WHERE id IN ({placeholders}) ORDER BY id
            """,
            params,
        ).fetchall()]
        return {"main": main, "shadow": shadow, "listings": listings}


@pytest.fixture
def valuation_case():
    init_schema()
    token = uuid.uuid4().hex
    listing_ids = []
    with get_conn() as conn:
        max_run_row = conn.execute(
            "SELECT COALESCE(MAX(id),0) AS max_id FROM valuation_model_runs"
        ).fetchone()
        previous_max_run_id = int(max_run_row["max_id"])
        for index in range(20):
            ppm2 = 15.0 + (index % 2)
            crawl_run_id = 717 if index == 0 else 800 + index
            listing_id = conn.execute(
                """
                INSERT INTO listings (
                    source, source_id, url, title, description, area, ward,
                    property_type, tx_type, price_per_m2, price_ty, area_m2,
                    road_type, road_tier, has_so, crawled_at, crawl_run_id
                ) VALUES (
                    'facebook', ?, ?, 'Tin dau tu', 'Dien tich 100m2',
                    'Tan An', 'Tan An', 'dat_nen', 'ban', ?, ?, 100,
                    'duong_nhua', 2, 1, '2026-08-03T00:00:00', ?
                )
                """,
                (
                    f"{token}-{index}",
                    f"https://t.test/{token}/{index}",
                    ppm2,
                    ppm2 / 10,
                    crawl_run_id,
                ),
            ).lastrowid
            listing_ids.append(listing_id)
    case = SnapshotCase(listing_ids, listing_ids[0], previous_max_run_id)
    yield case
    with get_conn() as conn:
        placeholders = ",".join("?" for _ in listing_ids)
        conn.execute(
            f"DELETE FROM listings WHERE id IN ({placeholders})",
            listing_ids,
        )
        conn.execute(
            "DELETE FROM valuation_model_runs WHERE id > ?",
            (previous_max_run_id,),
        )


@pytest.fixture
def seeded_snapshot(valuation_case):
    from cleansing.reprocess import reprocess_valuation

    reprocess_valuation(
        incremental_ids=valuation_case.listing_ids,
        training_ids=valuation_case.listing_ids,
    )
    return valuation_case


def test_main_valuation_rows_store_model_and_crawl_run_provenance(valuation_case):
    from cleansing.reprocess import reprocess_valuation

    reprocess_valuation(
        incremental_ids=valuation_case.listing_ids,
        training_ids=valuation_case.listing_ids,
    )

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT v.crawl_run_id, v.fair_ppm2, v.valuation_trace,
                   r.model_name, r.model_version, r.metrics_json
            FROM valuation_results v
            JOIN valuation_model_runs r ON r.id=v.model_run_id
            WHERE v.listing_id=?
            """,
            (valuation_case.target_id,),
        ).fetchone()
    assert row["crawl_run_id"] == 717
    assert row["model_name"] == "road_tier_hierarchical"
    assert row["model_version"] == "road_tier_hierarchical_v1"
    trace = row["valuation_trace"]
    assert trace["trace_version"] == 1
    assert trace["final_fair_ppm2"] == pytest.approx(row["fair_ppm2"], abs=0.01)
    assert trace["sample_count"] == 20
    assert valuation_case.target_id not in trace["comparable_listing_ids"]
    metrics = json.loads(row["metrics_json"])
    assert metrics["training_count"] == 20
    assert metrics["valuation_count"] == 20
    assert metrics["rejected_conversion_count"] == 0
    assert metrics["integrity_flag_counts"] == {}


def test_shadow_insert_failure_rolls_back_main_and_listing_outliers(
    monkeypatch,
    seeded_snapshot,
):
    from cleansing import reprocess

    before = seeded_snapshot.read_state()

    def fail_shadow(*_args, **_kwargs):
        raise RuntimeError("forced shadow insert failure")

    monkeypatch.setattr(reprocess, "_insert_shadow_results", fail_shadow)
    with pytest.raises(RuntimeError, match="forced shadow insert failure"):
        reprocess.reprocess_valuation(
            incremental_ids=seeded_snapshot.listing_ids,
            training_ids=seeded_snapshot.listing_ids,
        )

    with get_conn() as conn:
        after = seeded_snapshot.read_state(conn)
    assert after == before


def test_valuation_row_conversion_failure_identifies_listing():
    from cleansing.reprocess import _convert_valuation_rows

    row = {"id": 4242}

    with pytest.raises(
        ValueError,
        match="valuation input conversion failed listing_id=4242",
    ):
        _convert_valuation_rows([row], lambda _row: 1 / 0)
