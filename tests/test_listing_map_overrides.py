from __future__ import annotations

from contextlib import contextmanager

import pytest


def test_coordinate_input_accepts_lat_lng_and_google_maps_urls():
    from services.listing_map_overrides import parse_coordinate_input

    assert parse_coordinate_input("11.052345, 106.666789") == (
        11.052345,
        106.666789,
    )
    assert parse_coordinate_input(
        "https://www.google.com/maps/place/Test/@11.061234,106.671234,17z"
    ) == (11.061234, 106.671234)
    assert parse_coordinate_input(
        "https://maps.google.com/?query=11.071234%2C106.681234"
    ) == (11.071234, 106.681234)


@pytest.mark.parametrize(
    "value",
    (
        "https://maps.app.goo.gl/short-code",
        "https://example.com/@11.05,106.66,17z",
        "not-a-coordinate",
    ),
)
def test_coordinate_input_rejects_short_or_non_google_links(value):
    from services.listing_map_overrides import MapLocationOverrideError
    from services.listing_map_overrides import parse_coordinate_input

    with pytest.raises(MapLocationOverrideError) as exc_info:
        parse_coordinate_input(value)

    assert exc_info.value.code == "coordinate_not_found"


def test_override_payload_is_bounded_and_requires_verification_note():
    from services.listing_map_overrides import MapLocationOverrideError
    from services.listing_map_overrides import validate_override_payload

    payload = validate_override_payload({
        "lat": 11.052345,
        "lng": 106.666789,
        "coordinate_input": "11.052345,106.666789",
        "verification_source": "seller_confirmed",
        "note": "Chủ đất đã gửi vị trí qua Zalo.",
        "evidence_url": "https://maps.google.com/?q=11.052345,106.666789",
    })

    assert payload == {
        "lat": 11.052345,
        "lng": 106.666789,
        "verification_source": "seller_confirmed",
        "note": "Chủ đất đã gửi vị trí qua Zalo.",
        "evidence_url": "https://maps.google.com/?q=11.052345,106.666789",
    }

    for bad, code in (
        ({"lat": 9, "lng": 106.6, "verification_source": "seller_confirmed", "note": "x"}, "coordinate_out_of_bounds"),
        ({"lat": 11.05, "lng": 106.6, "verification_source": "unknown", "note": "x"}, "invalid_verification_source"),
        ({"lat": 11.05, "lng": 106.6, "verification_source": "other", "note": ""}, "note_required"),
        ({"lat": 11.05, "lng": 106.6, "verification_source": "other", "note": "x", "evidence_url": "javascript:alert(1)"}, "invalid_evidence_url"),
    ):
        with pytest.raises(MapLocationOverrideError) as exc_info:
            validate_override_payload(bad)
        assert exc_info.value.code == code


class _Cursor:
    def __init__(self, row=None, rows=None, rowcount=0):
        self._row = row
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _OverrideConnection:
    def __init__(self):
        self.group = None
        self.listing = None

    def execute(self, sql, params=None):
        params = list(params or [])
        normalized = " ".join(sql.split()).lower()
        if "from listing_map_locations" in normalized and "location_key = ?" in normalized:
            return _Cursor(row={
                "location_key": params[0],
                "location_precision": "road",
                "location_label": "Theo tên đường ĐX 43, Phú Lợi",
            })
        if "from listings" in normalized and "where id = ?" in normalized:
            return _Cursor(row={
                "id": params[0],
                "title": "Lô đất Phú Lợi",
                "ward": "Phú Lợi",
                "road_name": "ĐX 43",
            })
        if normalized.startswith("select") and "listing_map_group_overrides" in normalized:
            return _Cursor(row=self.group)
        if normalized.startswith("select") and "listing_map_listing_overrides" in normalized:
            return _Cursor(row=self.listing)
        if "insert into listing_map_group_overrides" in normalized:
            self.group = {
                "location_key": params[0],
                "lat": params[1],
                "lng": params[2],
                "verification_source": params[3],
                "note": params[4],
                "evidence_url": params[5],
                "updated_by": params[6],
                "active": True,
                "created_at": "2026-08-14T10:00:00+07:00",
                "updated_at": "2026-08-14T10:00:00+07:00",
            }
            return _Cursor(rowcount=1)
        if "insert into listing_map_listing_overrides" in normalized:
            self.listing = {
                "listing_id": params[0],
                "lat": params[1],
                "lng": params[2],
                "verification_source": params[3],
                "note": params[4],
                "evidence_url": params[5],
                "updated_by": params[6],
                "active": True,
                "created_at": "2026-08-14T10:00:00+07:00",
                "updated_at": "2026-08-14T10:00:00+07:00",
            }
            return _Cursor(rowcount=1)
        if normalized.startswith("update listing_map_group_overrides"):
            if self.group:
                self.group = {**self.group, "active": False, "updated_by": params[0]}
                return _Cursor(rowcount=1)
            return _Cursor(rowcount=0)
        if normalized.startswith("update listing_map_listing_overrides"):
            if self.listing:
                self.listing = {**self.listing, "active": False, "updated_by": params[0]}
                return _Cursor(rowcount=1)
            return _Cursor(rowcount=0)
        raise AssertionError(sql)


def _payload():
    return {
        "lat": 11.052345,
        "lng": 106.666789,
        "verification_source": "seller_confirmed",
        "note": "Chủ đất xác nhận vị trí.",
        "evidence_url": "",
    }


def test_group_and_listing_overrides_are_audited_and_reversible(monkeypatch):
    import services.listing_map_overrides as overrides

    connection = _OverrideConnection()
    audits = []

    @contextmanager
    def fake_get_conn():
        yield connection

    monkeypatch.setattr(overrides, "get_conn", fake_get_conn)

    group = overrides.save_group_override(
        "road:thu-dau-mot:phu-loi:dx-43",
        _payload(),
        actor="admin@example.com",
        audit_writer=lambda *args, **kwargs: audits.append((args, kwargs)),
    )
    listing = overrides.save_listing_override(
        42,
        _payload(),
        actor="admin@example.com",
        audit_writer=lambda *args, **kwargs: audits.append((args, kwargs)),
    )

    assert group["active"] is True
    assert listing["active"] is True
    assert len(audits) == 2
    assert audits[0][0][1:4] == (
        "map_location_group_override_upsert",
        "listing_map_group_override",
        None,
    )
    assert audits[1][0][1:4] == (
        "map_location_listing_override_upsert",
        "listing_map_listing_override",
        42,
    )

    reset_group = overrides.reset_group_override(
        "road:thu-dau-mot:phu-loi:dx-43",
        actor="admin@example.com",
        audit_writer=lambda *args, **kwargs: audits.append((args, kwargs)),
    )
    reset_listing = overrides.reset_listing_override(
        42,
        actor="admin@example.com",
        audit_writer=lambda *args, **kwargs: audits.append((args, kwargs)),
    )
    assert reset_group["active"] is False
    assert reset_listing["active"] is False
    assert len(audits) == 4


def test_group_override_rejects_exact_and_unknown_location_keys(monkeypatch):
    import services.listing_map_overrides as overrides

    class BadTargetConnection(_OverrideConnection):
        def execute(self, sql, params=None):
            if "FROM listing_map_locations" in sql:
                return _Cursor(row={
                    "location_key": "exact:42",
                    "location_precision": "exact",
                    "location_label": "Vị trí chính xác",
                })
            return super().execute(sql, params)

    @contextmanager
    def fake_get_conn():
        yield BadTargetConnection()

    monkeypatch.setattr(overrides, "get_conn", fake_get_conn)
    with pytest.raises(overrides.MapLocationOverrideError) as exc_info:
        overrides.save_group_override(
            "exact:42",
            _payload(),
            actor="admin",
            audit_writer=lambda *_args, **_kwargs: None,
        )
    assert exc_info.value.code == "invalid_group_precision"


def test_map_location_migration_creates_durable_override_tables():
    from db.schema import _migrate_listing_map_locations

    class SchemaConnection:
        def __init__(self):
            self.statements = []

        def execute(self, sql, params=None):
            self.statements.append(" ".join(sql.split()).lower())
            return _Cursor()

    connection = SchemaConnection()
    _migrate_listing_map_locations(connection)
    ddl = "\n".join(connection.statements)

    assert "create table if not exists listing_map_group_overrides" in ddl
    assert "location_key text primary key" in ddl
    assert "create table if not exists listing_map_listing_overrides" in ddl
    assert "listing_id bigint primary key references listings(id) on delete cascade" in ddl
    assert "active boolean not null default true" in ddl
    assert "verification_source text not null" in ddl
