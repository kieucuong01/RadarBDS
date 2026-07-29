from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

import app as radar_app
from services.listing_reports import (
    ListingReportError,
    REPORT_REASONS,
    submit_listing_report,
)


ROOT = Path(__file__).resolve().parent.parent


class _Cursor:
    def __init__(self, row=None, rows=None, lastrowid=None):
        self._row = row
        self._rows = rows or []
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, *, visible=True, duplicate=False, reporter_count=0, ip_count=0):
        self.visible = visible
        self.duplicate = duplicate
        self.reporter_count = reporter_count
        self.ip_count = ip_count
        self.executed = []
        self.insert_params = None

    def execute(self, sql, params=()):
        compact = " ".join(sql.split())
        self.executed.append((compact, params))
        if "FROM listings" in compact:
            return _Cursor({"id": 42} if self.visible else None)
        if "listing_id=? AND reporter_key_hash=?" in compact:
            return _Cursor({"id": 7} if self.duplicate else None)
        if "reporter_key_hash=?" in compact and "COUNT(*)" in compact:
            return _Cursor({"count": self.reporter_count})
        if "ip_hash=?" in compact and "COUNT(*)" in compact:
            return _Cursor({"count": self.ip_count})
        if compact.startswith("INSERT INTO listing_reports"):
            self.insert_params = params
            return _Cursor(lastrowid=99)
        raise AssertionError(compact)


def _submit(conn, **overrides):
    kwargs = {
        "listing_id": 42,
        "payload": {"reason": "wrong_location", "note": " Sai phường "},
        "actor": None,
        "request_meta": {"ip": "203.0.113.5", "user_agent": "Browser/1"},
        "secret": "test-secret",
        "now": datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc),
    }
    kwargs.update(overrides)
    return submit_listing_report(conn, **kwargs)


def test_schema_has_isolated_listing_report_table_and_indexes():
    schema = (ROOT / "db" / "schema.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS listing_reports" in schema
    assert "REFERENCES listings(id)" in schema
    assert "CHECK (reason IN" in schema
    assert "CHECK (status IN" in schema
    assert "idx_listing_reports_pending" in schema
    assert "idx_listing_reports_reporter_created" in schema
    assert "idx_listing_reports_ip_created" in schema


def test_valid_guest_report_hashes_identity_and_never_stores_raw_ip():
    conn = _FakeConn()
    result = _submit(conn)

    assert result.created is True
    assert result.duplicate is False
    assert conn.insert_params[0] == 42
    assert conn.insert_params[1] == "wrong_location"
    assert conn.insert_params[2] == "Sai phường"
    assert "203.0.113.5" not in str(conn.insert_params)
    assert "Browser/1" not in str(conn.insert_params)
    assert len(conn.insert_params[3]) == 64
    assert len(conn.insert_params[4]) == 64
    assert all("ai_training_feedback" not in sql for sql, _ in conn.executed)


def test_repeat_is_idempotent_and_limits_are_enforced():
    duplicate = _submit(_FakeConn(duplicate=True))
    assert duplicate.duplicate is True
    assert duplicate.created is False

    with pytest.raises(ListingReportError) as reporter_error:
        _submit(_FakeConn(reporter_count=5))
    assert reporter_error.value.code == "rate_limited"
    assert reporter_error.value.status == 429

    with pytest.raises(ListingReportError) as ip_error:
        _submit(_FakeConn(ip_count=20))
    assert ip_error.value.status == 429


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"reason": "invalid"}, "invalid_reason"),
        ({"reason": "other", "note": "x" * 501}, "invalid_note"),
        ([], "invalid_payload"),
    ],
)
def test_payload_validation(payload, code):
    with pytest.raises(ListingReportError) as error:
        _submit(_FakeConn(), payload=payload)
    assert error.value.code == code
    assert error.value.status == 400


def test_hidden_or_missing_listing_is_not_reportable():
    with pytest.raises(ListingReportError) as error:
        _submit(_FakeConn(visible=False))
    assert error.value.code == "listing_not_found"
    assert error.value.status == 404


def test_reason_contract_is_exact():
    assert REPORT_REASONS == frozenset(
        {
            "sold_or_unavailable",
            "wrong_price_or_area",
            "duplicate",
            "wrong_location",
            "spam_or_scam",
            "other",
        }
    )


def test_public_report_route_bounds_json_and_returns_generic_response(monkeypatch):
    calls = []

    @contextmanager
    def fake_conn():
        yield object()

    def fake_submit(_conn, **kwargs):
        calls.append(kwargs)
        return type("Result", (), {"created": True, "duplicate": False, "report_id": 99})()

    monkeypatch.setattr(radar_app, "get_conn", fake_conn)
    monkeypatch.setattr(radar_app, "submit_listing_report", fake_submit)
    monkeypatch.setattr(radar_app, "current_user", lambda: None)
    monkeypatch.setattr(radar_app, "current_tier", lambda: "guest")
    client = radar_app.app.test_client()

    response = client.post(
        "/api/listings/42/report",
        json={"reason": "wrong_location", "note": "Sai vị trí"},
    )
    assert response.status_code == 201
    assert response.get_json() == {"ok": True, "duplicate": False}
    assert calls[0]["listing_id"] == 42
    assert set(calls[0]["request_meta"]) == {"ip", "user_agent"}

    assert client.post("/api/listings/42/report", data="[]", content_type="application/json").status_code == 400
    assert client.post(
        "/api/listings/42/report",
        data="x" * 4097,
        content_type="application/json",
    ).status_code == 413


def test_admin_report_route_requires_admin(monkeypatch):
    monkeypatch.setattr(radar_app, "_admin_request_authorized", lambda: False)
    response = radar_app.app.test_client().get("/admin/api/listing-reports")
    assert response.status_code == 403
