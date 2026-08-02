from contextlib import contextmanager
import json

import pytest

from services import public_prewarm


class FakeResponse:
    def __init__(self, status=200, body=b"ok"):
        self.status = status
        self.body = body
        self.read_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        self.read_sizes.append(size)
        return self.body[:size] if size >= 0 else self.body


def test_prewarm_never_sends_cookies_or_authorization(monkeypatch):
    captured = []

    def fake_urlopen(request, timeout):
        captured.append((request, timeout))
        return FakeResponse(200)

    monkeypatch.setattr(public_prewarm, "urlopen", fake_urlopen)

    result = public_prewarm.prewarm_public_routes(
        "http://127.0.0.1:5000",
        ["/api/signals?include_total=0"],
    )

    headers = dict(captured[0][0].header_items())
    assert "Cookie" not in headers
    assert "Authorization" not in headers
    assert headers["User-agent"] == "RadarBDS-Prewarm/1.0"
    assert captured[0][1] == 5.0
    assert result["attempted"] == result["succeeded"] == 1
    assert result["failed"] == 0


@pytest.mark.parametrize(
    "route",
    (
        "api/signals",
        "https://radarbds.vn/api/signals",
        "//attacker.example/api/signals",
        "/api/signals#fragment",
        "/api/private",
        "/admin",
    ),
)
def test_prewarm_rejects_unbounded_or_non_public_routes(route):
    with pytest.raises(ValueError, match="route"):
        public_prewarm.prewarm_public_routes(
            "http://127.0.0.1:5000", [route]
        )


def test_prewarm_rejects_credentials_and_more_than_twenty_routes():
    with pytest.raises(ValueError, match="base URL"):
        public_prewarm.prewarm_public_routes(
            "http://user:secret@127.0.0.1:5000", ["/"]
        )

    routes = [f"/api/signals?page={index}" for index in range(21)]
    with pytest.raises(ValueError, match="20"):
        public_prewarm.prewarm_public_routes(
            "http://127.0.0.1:5000", routes
        )


def test_prewarm_caps_response_body_read_at_two_megabytes(monkeypatch):
    response = FakeResponse(200, body=b"x" * (2 * 1024 * 1024 + 1))
    monkeypatch.setattr(
        public_prewarm, "urlopen", lambda request, timeout: response
    )

    result = public_prewarm.prewarm_public_routes(
        "http://127.0.0.1:5000", ["/api/counts"]
    )

    assert response.read_sizes == [2 * 1024 * 1024 + 1]
    assert result["failed"] == 1
    assert result["routes"][0]["status"] == "body_too_large"


def test_listings_is_an_allowlisted_prewarm_path():
    routes = public_prewarm._validated_routes(
        [
            "/api/listings?date_range=3m&sort_by=date&sort_dir=desc"
            "&page=1&limit=50"
        ]
    )

    assert routes == (
        "/api/listings?date_range=3m&sort_by=date&sort_dir=desc"
        "&page=1&limit=50",
    )


def test_configured_prewarm_skips_listings_until_durable_version_is_ready(
    monkeypatch, tmp_path
):
    config = tmp_path / "routes.json"
    config.write_text(
        json.dumps(["/api/dashboard", "/api/listings?page=1&limit=50"]),
        encoding="utf-8",
    )
    captured = []
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setattr(
        public_prewarm,
        "prewarm_public_routes",
        lambda base_url, routes: captured.extend(routes) or {},
    )

    public_prewarm.prewarm_configured_routes(config, listings_version=0)

    assert captured == ["/api/dashboard"]


def test_configured_prewarm_includes_listings_after_committed_version(
    monkeypatch, tmp_path
):
    config = tmp_path / "routes.json"
    listing_route = "/api/listings?page=1&limit=50"
    config.write_text(
        json.dumps(["/api/dashboard", listing_route]),
        encoding="utf-8",
    )
    captured = []
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setattr(
        public_prewarm,
        "prewarm_public_routes",
        lambda base_url, routes: captured.extend(routes) or {},
    )

    public_prewarm.prewarm_configured_routes(config, listings_version=7)

    assert captured == ["/api/dashboard", listing_route]


def test_standalone_configured_prewarm_reads_durable_listing_version(
    monkeypatch, tmp_path
):
    config = tmp_path / "routes.json"
    listing_route = "/api/listings?page=1&limit=50"
    config.write_text(json.dumps([listing_route]), encoding="utf-8")
    captured = []
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setattr(
        public_prewarm,
        "_durable_listing_version",
        lambda: 5,
        raising=False,
    )
    monkeypatch.setattr(
        public_prewarm,
        "prewarm_public_routes",
        lambda base_url, routes: captured.extend(routes) or {},
    )

    public_prewarm.prewarm_configured_routes(config)

    assert captured == [listing_route]
