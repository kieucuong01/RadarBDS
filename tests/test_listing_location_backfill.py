from unittest import mock

from services.listing_location_resolver import (
    LocationRegistry,
    listing_location_signature,
)


def _registry():
    return LocationRegistry(
        resolver_version="test-v1",
        roads={
            ("THỦ DẦU MỘT", "phu loi", "dx 43"): {
                "lat": 10.981,
                "lng": 106.689,
                "label": "Theo tên đường ĐX 43, Phú Lợi",
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


def _candidate(listing_id, *, ward="Phú Lợi", road_name="", **extra):
    return {
        "id": listing_id,
        "ward": ward,
        "road_name": road_name,
        "source_lat": None,
        "source_lng": None,
        "existing_resolver_version": None,
        "existing_signature": None,
        **extra,
    }


@mock.patch(
    "services.listing_location_backfill.load_location_registry",
    side_effect=_registry,
)
@mock.patch(
    "services.listing_location_backfill.delete_stale_listing_map_locations",
    return_value=0,
)
@mock.patch(
    "services.listing_location_backfill.delete_listing_map_locations",
    return_value=0,
)
@mock.patch(
    "services.listing_location_backfill.upsert_listing_map_locations",
    side_effect=lambda rows: len(rows),
)
@mock.patch("services.listing_location_backfill.iter_location_candidates")
def test_backfill_reports_exact_road_ward_and_unmapped(
    iter_candidates,
    upsert_rows,
    delete_rows,
    delete_stale,
    _load_registry,
):
    from services.listing_location_backfill import backfill_listing_locations

    iter_candidates.return_value = [
        _candidate(
            1,
            source_lat=10.99,
            source_lng=106.67,
        ),
        _candidate(2, road_name="ĐX-43"),
        _candidate(3, road_name="Đường không khớp"),
        _candidate(4, ward="Phường không rõ"),
    ]

    stats = backfill_listing_locations()

    assert stats == {
        "scanned": 4,
        "exact": 1,
        "road": 1,
        "ward": 1,
        "unmapped": 1,
        "inserted": 3,
        "updated": 0,
        "unchanged": 0,
        "deleted": 0,
    }
    assert len(upsert_rows.call_args.args[0]) == 3
    delete_rows.assert_not_called()
    delete_stale.assert_not_called()


@mock.patch(
    "services.listing_location_backfill.load_location_registry",
    side_effect=_registry,
)
@mock.patch(
    "services.listing_location_backfill.delete_stale_listing_map_locations",
    return_value=0,
)
@mock.patch(
    "services.listing_location_backfill.delete_listing_map_locations",
    return_value=1,
)
@mock.patch(
    "services.listing_location_backfill.upsert_listing_map_locations",
    side_effect=lambda rows: len(rows),
)
@mock.patch("services.listing_location_backfill.iter_location_candidates")
def test_backfill_skips_unchanged_updates_changed_and_deletes_unmapped(
    iter_candidates,
    upsert_rows,
    delete_rows,
    _delete_stale,
    _load_registry,
):
    from services.listing_location_backfill import backfill_listing_locations

    unchanged = _candidate(10, road_name="ĐX 43")
    unchanged["existing_resolver_version"] = "test-v1"
    unchanged["existing_signature"] = listing_location_signature(
        {**unchanged, "city": "THỦ DẦU MỘT"}
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
        existing_resolver_version="test-v1",
        existing_signature="old-signature",
    )
    iter_candidates.return_value = [unchanged, changed, unmapped]

    stats = backfill_listing_locations()

    assert stats["unchanged"] == 1
    assert stats["updated"] == 1
    assert stats["unmapped"] == 1
    assert stats["deleted"] == 1
    assert [row.listing_id for row in upsert_rows.call_args.args[0]] == [11]
    delete_rows.assert_called_once_with([12])


@mock.patch(
    "services.listing_location_backfill.load_location_registry",
    side_effect=_registry,
)
@mock.patch(
    "services.listing_location_backfill.delete_stale_listing_map_locations",
    return_value=2,
)
@mock.patch(
    "services.listing_location_backfill.delete_listing_map_locations",
    return_value=0,
)
@mock.patch("services.listing_location_backfill.upsert_listing_map_locations")
@mock.patch("services.listing_location_backfill.iter_location_candidates")
def test_full_dry_run_is_read_only_and_reports_prospective_changes(
    iter_candidates,
    upsert_rows,
    delete_rows,
    delete_stale,
    _load_registry,
):
    from services.listing_location_backfill import backfill_listing_locations

    iter_candidates.return_value = [_candidate(20, road_name="ĐX 43")]

    stats = backfill_listing_locations(full=True, dry_run=True)

    assert stats["inserted"] == 1
    assert stats["deleted"] == 0
    upsert_rows.assert_not_called()
    delete_rows.assert_not_called()
    delete_stale.assert_not_called()


@mock.patch(
    "services.listing_location_backfill.load_location_registry",
    side_effect=_registry,
)
@mock.patch(
    "services.listing_location_backfill.delete_stale_listing_map_locations",
    return_value=2,
)
@mock.patch(
    "services.listing_location_backfill.delete_listing_map_locations",
    return_value=0,
)
@mock.patch(
    "services.listing_location_backfill.upsert_listing_map_locations",
    side_effect=lambda rows: len(rows),
)
@mock.patch("services.listing_location_backfill.iter_location_candidates")
def test_full_backfill_prunes_rows_for_missing_listings(
    iter_candidates,
    _upsert_rows,
    _delete_rows,
    delete_stale,
    _load_registry,
):
    from services.listing_location_backfill import backfill_listing_locations

    iter_candidates.return_value = [_candidate(30, road_name="ĐX 43")]

    stats = backfill_listing_locations(full=True)

    assert stats["deleted"] == 2
    delete_stale.assert_called_once_with([30])
