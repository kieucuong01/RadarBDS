from unittest import mock

from services.listing_location_resolver import (
    LocationRegistry,
    listing_location_signature,
)
from services.listing_map_context import extract_map_location_context


def _registry():
    road = {
        "lat": 10.981,
        "lng": 106.689,
        "label": "Theo tên đường ĐX 43, Phú Lợi",
        "source": "OpenStreetMap",
    }
    return LocationRegistry(
        resolver_version="test-v2",
        roads={
            ("THỦ DẦU MỘT", "phu loi", "dx 43"): (road,),
            ("THỦ DẦU MỘT", "phu loi", "duong so 35"): (
                {**road, "landmark_keys": ["tdc phu chanh b"]},
                {
                    **road,
                    "lat": 10.982,
                    "landmark_keys": ["tdc phu chanh d"],
                },
            ),
        },
        landmarks={
            ("THỦ DẦU MỘT", "phu loi", "tdc phu chanh d"): {
                "lat": 10.982,
                "lng": 106.690,
                "label": "Theo địa danh TĐC Phú Chánh D",
                "source": "OpenStreetMap",
            }
        },
        wards={
            ("THỦ DẦU MỘT", "phu loi"): {
                "lat": 10.984,
                "lng": 106.684,
                "label": "Theo trung tâm Phú Lợi",
                "source": "Verified ward source",
            }
        },
    )


def _candidate(
    listing_id,
    *,
    ward="Phú Lợi",
    road_name="",
    title="",
    description="",
    **extra,
):
    return {
        "id": listing_id,
        "title": title,
        "description": description,
        "ward": ward,
        "road_name": road_name,
        "source_lat": None,
        "source_lng": None,
        "existing_resolver_version": None,
        "existing_signature": None,
        **extra,
    }


def _patch_backfill():
    return (
        mock.patch(
            "services.listing_location_backfill.load_location_registry",
            side_effect=_registry,
        ),
        mock.patch(
            "services.listing_location_backfill.delete_stale_listing_map_locations",
            return_value=0,
        ),
        mock.patch(
            "services.listing_location_backfill.delete_listing_map_locations",
            return_value=0,
        ),
        mock.patch(
            "services.listing_location_backfill.upsert_listing_map_locations",
            side_effect=lambda rows: len(rows),
        ),
        mock.patch(
            "services.listing_location_backfill.upsert_listing_location_coverage",
            side_effect=lambda rows: len(rows),
        ),
        mock.patch(
            "services.listing_location_backfill.delete_stale_listing_location_coverage",
            return_value=0,
        ),
        mock.patch("services.listing_location_backfill.iter_location_candidates"),
    )


def test_backfill_reports_all_precisions_and_persists_aggregated_issues():
    patches = _patch_backfill()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3] as upsert_rows,
        patches[4] as upsert_coverage,
        patches[5],
        patches[6] as iter_candidates,
    ):
        from services.listing_location_backfill import backfill_listing_locations

        iter_candidates.return_value = [
            _candidate(1, source_lat=10.99, source_lng=106.67),
            _candidate(2, title="Mặt tiền ĐX43"),
            _candidate(3, title="TĐC Phú Chánh D"),
            _candidate(4, description="Cách đường ĐX43 khoảng 100m"),
            _candidate(5, title="Mặt tiền Đường số 35"),
            _candidate(6, ward="Phường không rõ"),
        ]

        stats = backfill_listing_locations()

    assert stats == {
        "scanned": 6,
        "exact": 1,
        "road": 2,
        "landmark": 1,
        "nearby": 0,
        "ward": 1,
        "unmapped": 1,
        "ambiguous": 1,
        "not_found": 1,
        "invalid": 0,
        "inserted": 5,
        "updated": 0,
        "unchanged": 0,
        "deleted": 0,
    }
    assert len(upsert_rows.call_args.args[0]) == 5
    coverage_rows = upsert_coverage.call_args.args[0]
    assert {(row.status, row.affected_listing_count) for row in coverage_rows} == {
        ("ambiguous", 1),
        ("not_found", 1),
    }


def test_backfill_rewrites_legacy_nearby_row_as_road():
    patches = _patch_backfill()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3] as upsert_rows,
        patches[4],
        patches[5],
        patches[6] as iter_candidates,
    ):
        from services.listing_location_backfill import backfill_listing_locations

        iter_candidates.return_value = [
            _candidate(
                7,
                description="Cách đường ĐX43 khoảng 100m",
                existing_resolver_version="old-v1",
                existing_signature="legacy-nearby-signature",
            )
        ]

        stats = backfill_listing_locations()

    assert stats["road"] == 1
    assert stats["nearby"] == 0
    assert stats["updated"] == 1
    written = upsert_rows.call_args.args[0]
    assert written[0].precision == "road"
    assert written[0].location_key == "road:thu-dau-mot:phu-loi:dx-43"
    assert written[0].relation == "near"


def test_raw_sourced_coordinate_upgrades_existing_ward_marker_to_exact():
    patches = _patch_backfill()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3] as upsert_rows,
        patches[4],
        patches[5],
        patches[6] as iter_candidates,
    ):
        from services.listing_location_backfill import backfill_listing_locations

        iter_candidates.return_value = [
            _candidate(
                80,
                source_lat=11.0280996,
                source_lng=106.6206725,
                existing_resolver_version="old-v1",
                existing_signature="ward-signature",
            )
        ]
        stats = backfill_listing_locations(listing_ids=[80])

    assert stats["exact"] == 1
    assert stats["updated"] == 1
    written = upsert_rows.call_args.args[0]
    assert written[0].listing_id == 80
    assert written[0].precision == "exact"


def test_backfill_skips_unchanged_updates_changed_and_deletes_unmapped():
    patches = _patch_backfill()
    with (
        patches[0],
        patches[1],
        patches[2] as delete_rows,
        patches[3] as upsert_rows,
        patches[4],
        patches[5],
        patches[6] as iter_candidates,
    ):
        from services.listing_location_backfill import backfill_listing_locations

        unchanged = _candidate(10, road_name="ĐX 43")
        unchanged_context = extract_map_location_context("", "", "ĐX 43")
        unchanged["existing_resolver_version"] = "test-v2"
        unchanged["existing_signature"] = listing_location_signature(
            {**unchanged, "city": "THỦ DẦU MỘT"},
            unchanged_context,
            "test-v2",
        )
        changed = _candidate(
            11,
            road_name="ĐX 43",
            existing_resolver_version="old-v1",
            existing_signature="old-signature",
        )
        unmapped = _candidate(
            12,
            ward="Không rõ",
            existing_resolver_version="test-v2",
            existing_signature="old-signature",
        )
        iter_candidates.return_value = [unchanged, changed, unmapped]

        stats = backfill_listing_locations()

    assert stats["unchanged"] == 1
    assert stats["updated"] == 1
    assert stats["unmapped"] == 1
    assert stats["deleted"] == 0
    assert [row.listing_id for row in upsert_rows.call_args.args[0]] == [11]
    delete_rows.assert_called_once_with([12])


def test_full_dry_run_is_read_only():
    patches = _patch_backfill()
    with (
        patches[0],
        patches[1] as delete_stale,
        patches[2] as delete_rows,
        patches[3] as upsert_rows,
        patches[4] as upsert_coverage,
        patches[5] as delete_stale_coverage,
        patches[6] as iter_candidates,
    ):
        from services.listing_location_backfill import backfill_listing_locations

        iter_candidates.return_value = [_candidate(20, road_name="ĐX 43")]
        stats = backfill_listing_locations(full=True, dry_run=True)

    assert stats["inserted"] == 1
    upsert_rows.assert_not_called()
    upsert_coverage.assert_not_called()
    delete_rows.assert_not_called()
    delete_stale.assert_not_called()
    delete_stale_coverage.assert_not_called()


def test_full_backfill_prunes_stale_location_and_coverage_rows():
    patches = _patch_backfill()
    with (
        patches[0],
        mock.patch(
            "services.listing_location_backfill.delete_stale_listing_map_locations",
            return_value=2,
        ) as delete_stale,
        patches[2],
        patches[3],
        patches[4],
        mock.patch(
            "services.listing_location_backfill.delete_stale_listing_location_coverage",
            return_value=3,
        ) as delete_stale_coverage,
        patches[6] as iter_candidates,
    ):
        from services.listing_location_backfill import backfill_listing_locations

        iter_candidates.return_value = [_candidate(30, road_name="ĐX 43")]
        stats = backfill_listing_locations(full=True)

    assert stats["deleted"] == 2
    delete_stale.assert_called_once_with([30])
    delete_stale_coverage.assert_called_once_with([])


def test_incremental_backfill_rebuilds_global_coverage_counts():
    patches = _patch_backfill()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4] as upsert_coverage,
        patches[5] as delete_stale_coverage,
        patches[6] as iter_candidates,
    ):
        from services.listing_location_backfill import backfill_listing_locations

        batch = [_candidate(40, title="Mặt tiền DX120")]
        complete = [
            _candidate(40, title="Mặt tiền DX120"),
            _candidate(41, title="Mặt tiền ĐX-120"),
        ]
        iter_candidates.side_effect = [batch, complete]

        stats = backfill_listing_locations(listing_ids=[40])

    assert stats["scanned"] == 1
    coverage_rows = upsert_coverage.call_args.args[0]
    assert len(coverage_rows) == 1
    assert coverage_rows[0].affected_listing_count == 2
    assert coverage_rows[0].sample_listing_ids == (40, 41)
    delete_stale_coverage.assert_called_once_with(
        [coverage_rows[0].candidate_key]
    )
