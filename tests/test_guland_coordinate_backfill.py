from datetime import datetime, timezone

import pytest

from db.guland_coordinates import GulandCoordinateTarget
from services.guland_coordinate_backfill import (
    _atomic_write_manifest,
    run_guland_coordinate_backfill,
)


def _target():
    return GulandCoordinateTarget(
        listing_id=70,
        raw_id=7,
        url="https://guland.vn/post/dat-tan-an-1231140",
        source_id="1231140",
        ward="Tân An",
        city="THỦ DẦU MỘT",
        context_text="Bán đất Tân An",
        existing_coordinate_fields={},
        existing_map_precision="ward",
        raw_json_valid=True,
    )


def _cards():
    return [{
        "url": "https://guland.vn/post/dat-tan-an-1231140",
        "post_id": "1231140",
        "source_coordinate_url": (
            "https://www.google.com/maps/search/"
            "?api=1&query=11.028099613958%2C106.6206724626"
        ),
    }]


def test_dry_run_builds_plan_without_writing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.load_active_guland_coordinate_targets",
        lambda: [_target()],
    )
    monkeypatch.setattr(
        "services.guland_coordinate_backfill._collect_cards",
        lambda targets: _cards(),
    )
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_scoped_ward",
        lambda city, ward, lat, lng: True,
    )
    merge_calls = []
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.merge_raw_coordinate_updates",
        lambda updates: merge_calls.append(updates),
    )

    result = run_guland_coordinate_backfill(
        manifest_root=tmp_path,
        now=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    assert result["eligible"] == 1
    assert result["matched"] == 1
    assert result["valid"] == 1
    assert result["would_update"] == 1
    assert result["would_upgrade_to_exact"] == 1
    assert result["raw_updated"] == 0
    assert merge_calls == []
    assert list(tmp_path.iterdir()) == []


def test_apply_writes_manifest_then_raw_then_exact_map(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.load_active_guland_coordinate_targets",
        lambda: [_target()],
    )
    monkeypatch.setattr(
        "services.guland_coordinate_backfill._collect_cards",
        lambda targets: _cards(),
    )
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_scoped_ward",
        lambda city, ward, lat, lng: True,
    )
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.snapshot_raw_coordinate_fields",
        lambda raw_ids: [{
            "raw_id": 7,
            "listing_id": 70,
            "source_lat": None,
            "source_lng": None,
            "source_coordinate_url": None,
            "source_coordinate_provider": None,
            "source_coordinate_captured_at": None,
        }],
    )
    events = []
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.merge_raw_coordinate_updates",
        lambda updates: events.append("merge") or [70],
    )
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.backfill_listing_locations",
        lambda listing_ids: events.append(("map", listing_ids))
        or {"exact": 1, "inserted": 0, "updated": 1, "unchanged": 0},
    )

    result = run_guland_coordinate_backfill(
        apply=True,
        manifest_root=tmp_path,
        now=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    manifests = list(tmp_path.glob("*-before.jsonl"))
    assert len(manifests) == 1
    assert events == ["merge", ("map", [70])]
    assert result["raw_updated"] == 1
    assert result["map_exact_updated"] == 1
    assert result["run_id"] in manifests[0].name


def test_rollback_restores_only_manifest_coordinate_fields(monkeypatch, tmp_path):
    run_id = "20260730T120000Z"
    manifest = tmp_path / f"{run_id}-before.jsonl"
    manifest.write_text(
        '{"raw_id":7,"listing_id":70,"source_lat":null,'
        '"source_lng":null,"source_coordinate_url":null,'
        '"source_coordinate_provider":null,'
        '"source_coordinate_captured_at":null}\n',
        encoding="utf-8",
    )
    events = []
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.restore_raw_coordinate_snapshot",
        lambda rows: events.append(rows) or [70],
    )
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.backfill_listing_locations",
        lambda listing_ids: events.append(listing_ids)
        or {"updated": 1, "exact": 0},
    )

    result = run_guland_coordinate_backfill(
        rollback_run=run_id,
        manifest_root=tmp_path,
    )

    assert result["rollback_restored"] == 1
    assert events[1] == [70]


def test_rollback_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="invalid rollback run id"):
        run_guland_coordinate_backfill(
            rollback_run="../secrets",
            manifest_root=tmp_path,
        )


def test_atomic_manifest_refuses_to_overwrite_an_existing_run(tmp_path):
    path = tmp_path / "20260730T120000Z-before.jsonl"
    path.write_text("original\n", encoding="utf-8")
    row = {
        "raw_id": 7,
        "listing_id": 70,
        "source_lat": None,
        "source_lng": None,
        "source_coordinate_url": None,
        "source_coordinate_provider": None,
        "source_coordinate_captured_at": None,
    }

    with pytest.raises(FileExistsError):
        _atomic_write_manifest(path, [row])

    assert path.read_text(encoding="utf-8") == "original\n"
