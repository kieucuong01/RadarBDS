import json
from contextlib import contextmanager

from db.guland_coordinates import (
    GulandCoordinateUpdate,
    load_active_guland_coordinate_targets,
    merge_raw_coordinate_updates,
    restore_raw_coordinate_snapshot,
    snapshot_raw_coordinate_fields,
)


class Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.rowcount = len(self.rows)

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        rows = self.responses.pop(0) if self.responses else []
        return Cursor(rows)


@contextmanager
def connection_factory(connection):
    yield connection


def test_target_query_uses_exact_maps_visibility_gate():
    connection = Connection([[]])

    result = load_active_guland_coordinate_targets(
        conn_factory=lambda: connection_factory(connection)
    )

    assert result == []
    sql = " ".join(connection.executed[0][0].split())
    assert "l.source = 'guland'" in sql
    assert "COALESCE(l.probably_sold, 0) = 0" in sql
    assert "COALESCE(l.is_blacklisted, 0) = 0" in sql
    assert "COALESCE(l.review_hidden, 0) = 0" in sql
    assert "COALESCE(l.possibly_duplicate, 0) = 0" in sql


def test_raw_merge_preserves_existing_keys_and_is_idempotent():
    existing = {
        "title": "Bán đất Tân An",
        "price_ty": 2.0,
    }
    updated = {
        **existing,
        "source_lat": 11.0280996,
        "source_lng": 106.6206725,
        "source_coordinate_url": (
            "https://www.google.com/maps/search/"
            "?api=1&query=11.0280996%2C106.6206725"
        ),
        "source_coordinate_provider": "guland_directions",
        "source_coordinate_captured_at": "2026-07-30T12:34:56+07:00",
    }
    connection = Connection([
        [{"id": 7, "raw_json": json.dumps(existing)}],
        [],
        [{"id": 7, "raw_json": json.dumps(updated)}],
    ])
    update = GulandCoordinateUpdate(
        raw_id=7,
        listing_id=70,
        fields={key: updated[key] for key in updated if key.startswith("source_")},
    )

    first = merge_raw_coordinate_updates(
        [update],
        conn_factory=lambda: connection_factory(connection),
    )
    second = merge_raw_coordinate_updates(
        [update],
        conn_factory=lambda: connection_factory(connection),
    )

    assert first == [70]
    assert second == []
    update_sql, update_params = next(
        item for item in connection.executed if item[0].lstrip().startswith("UPDATE")
    )
    merged = json.loads(update_params[0])
    assert merged["title"] == "Bán đất Tân An"
    assert merged["price_ty"] == 2.0
    assert merged["source_lat"] == 11.0280996


def test_raw_merge_ignores_a_later_capture_time_for_same_coordinate():
    existing = {
        "source_lat": 11.0280996,
        "source_lng": 106.6206725,
        "source_coordinate_url": (
            "https://www.google.com/maps/search/"
            "?api=1&query=11.0280996%2C106.6206725"
        ),
        "source_coordinate_provider": "guland_directions",
        "source_coordinate_captured_at": "2026-07-30T12:34:56+07:00",
    }
    connection = Connection([[
        {"id": 7, "raw_json": json.dumps(existing)}
    ]])
    update = GulandCoordinateUpdate(
        raw_id=7,
        listing_id=70,
        fields={
            **existing,
            "source_coordinate_captured_at": "2026-07-31T12:34:56+07:00",
        },
    )

    changed = merge_raw_coordinate_updates(
        [update],
        conn_factory=lambda: connection_factory(connection),
    )

    assert changed == []
    assert not any(
        sql.lstrip().startswith("UPDATE")
        for sql, _params in connection.executed
    )


def test_snapshot_contains_only_ids_and_five_coordinate_fields():
    raw = {
        "title": "Bán đất",
        "contact_phone": "0900000000",
        "source_lat": 11.0280996,
        "source_lng": 106.6206725,
        "source_coordinate_url": (
            "https://www.google.com/maps/search/"
            "?api=1&query=11.0280996%2C106.6206725"
        ),
        "source_coordinate_provider": "guland_directions",
        "source_coordinate_captured_at": "2026-07-30T12:34:56+07:00",
    }
    connection = Connection([[
        {"raw_id": 7, "listing_id": 70, "raw_json": json.dumps(raw)}
    ]])

    rows = snapshot_raw_coordinate_fields(
        [7],
        conn_factory=lambda: connection_factory(connection),
    )

    assert rows == [{
        "raw_id": 7,
        "listing_id": 70,
        "source_lat": 11.0280996,
        "source_lng": 106.6206725,
        "source_coordinate_url": raw["source_coordinate_url"],
        "source_coordinate_provider": "guland_directions",
        "source_coordinate_captured_at": "2026-07-30T12:34:56+07:00",
    }]
    assert "title" not in rows[0]
    assert "contact_phone" not in rows[0]


def test_restore_removes_only_coordinate_fields_and_preserves_raw_content():
    current = {
        "title": "Bán đất",
        "price_ty": 2.0,
        "source_lat": 11.0280996,
        "source_lng": 106.6206725,
    }
    connection = Connection([
        [{"id": 7, "raw_json": json.dumps(current)}],
        [],
    ])
    snapshot = [{
        "raw_id": 7,
        "listing_id": 70,
        "source_lat": None,
        "source_lng": None,
        "source_coordinate_url": None,
        "source_coordinate_provider": None,
        "source_coordinate_captured_at": None,
    }]

    restored = restore_raw_coordinate_snapshot(
        snapshot,
        conn_factory=lambda: connection_factory(connection),
    )

    assert restored == [70]
    update_params = next(
        params
        for sql, params in connection.executed
        if sql.lstrip().startswith("UPDATE")
    )
    merged = json.loads(update_params[0])
    assert merged == {"title": "Bán đất", "price_ty": 2.0}


def test_restore_recovers_the_manifest_capture_time_exactly():
    current = {
        "title": "Bán đất",
        "source_lat": 11.0280996,
        "source_lng": 106.6206725,
        "source_coordinate_url": "https://www.google.com/maps/search/?api=1",
        "source_coordinate_provider": "guland_directions",
        "source_coordinate_captured_at": "2026-07-31T12:00:00+07:00",
    }
    snapshot = [{
        "raw_id": 7,
        "listing_id": 70,
        "source_lat": 11.0280996,
        "source_lng": 106.6206725,
        "source_coordinate_url": "https://www.google.com/maps/search/?api=1",
        "source_coordinate_provider": "guland_directions",
        "source_coordinate_captured_at": "2026-07-30T12:00:00+07:00",
    }]
    connection = Connection([
        [{"id": 7, "raw_json": json.dumps(current)}],
        [],
    ])

    restored = restore_raw_coordinate_snapshot(
        snapshot,
        conn_factory=lambda: connection_factory(connection),
    )

    assert restored == [70]
    update_params = next(
        params
        for sql, params in connection.executed
        if sql.lstrip().startswith("UPDATE")
    )
    merged = json.loads(update_params[0])
    assert (
        merged["source_coordinate_captured_at"]
        == "2026-07-30T12:00:00+07:00"
    )


def test_map_candidate_loader_reads_validated_coordinates_from_raw(monkeypatch):
    from db import listing_map_locations

    row = {
        "id": 70,
        "title": "Bán đất",
        "description": "",
        "ward": "Tân An",
        "road_name": "",
        "source": "guland",
        "raw_json": json.dumps({
            "source_lat": 11.0280996,
            "source_lng": 106.6206725,
        }),
        "existing_resolver_version": None,
        "existing_signature": None,
    }
    connection = Connection([[row]])
    monkeypatch.setattr(
        listing_map_locations,
        "get_conn",
        lambda: connection_factory(connection),
    )

    candidates = listing_map_locations.iter_location_candidates([70])

    assert candidates[0]["source_lat"] == 11.0280996
    assert candidates[0]["source_lng"] == 106.6206725
