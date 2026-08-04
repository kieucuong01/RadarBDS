import pytest

import auth.core as auth_core
import app as radar_app
from auth.core import SESSION_COOKIE_NAME
from services.public_cache import CacheResult, PublicCacheBusy


PUBLIC_CACHE_CONTROL = (
    "public, max-age=15, stale-while-revalidate=180, "
    "stale-if-error=180"
)


@pytest.fixture
def client(monkeypatch):
    auth_core.clear_rate_limit_cache()
    monkeypatch.setattr(radar_app, "_public_cache_enabled", lambda: True)
    monkeypatch.setattr(radar_app, "current_tier", lambda: "guest")
    monkeypatch.setattr(radar_app, "current_user", lambda: None)
    monkeypatch.setattr(auth_core, "current_tier", lambda: "guest")
    monkeypatch.setattr(
        radar_app,
        "get_current_dataset_versions",
        lambda names: {name: 1 for name in names},
        raising=False,
    )
    monkeypatch.setattr(
        radar_app,
        "get_durable_dataset_versions",
        lambda names: {name: 1 for name in names},
        raising=False,
    )
    monkeypatch.setattr(
        radar_app,
        "load_signals",
        lambda *_args, **kwargs: {
            "signals": [],
            "page": kwargs["page"],
            "limit": kwargs["limit"],
            "has_more": False,
            "sort": kwargs["sort"],
            "tier": kwargs["tier"],
        },
    )
    monkeypatch.setattr(
        radar_app,
        "load_listing_feed",
        lambda *_args, **kwargs: {
            "listings": [],
            "page": kwargs["page"],
            "limit": kwargs["limit"],
            "total": 0,
            "pages": 0,
        },
    )

    def fake_cache(**kwargs):
        payload = kwargs["loader"]()
        status = "bypass" if kwargs["tier"] == "admin" else "miss"
        return CacheResult(payload=payload, status=status, load_ms=1.25)

    monkeypatch.setattr(
        radar_app, "get_or_load_public_payload", fake_cache, raising=False
    )
    return radar_app.app.test_client()


def test_guest_signal_response_is_public_cache_candidate(client):
    response = client.get("/api/signals?include_total=0")

    assert response.status_code == 200
    assert response.headers["X-Radar-Public-Cache"] == "1"
    assert response.headers["Cache-Control"] == PUBLIC_CACHE_CONTROL
    assert "Cookie" in response.headers["Vary"]
    assert response.headers["X-Radar-Cache"] == "miss"
    assert response.headers["X-Radar-Dataset-Version"] == "1"
    assert "load;dur=1.25" in response.headers["Server-Timing"]


def test_guest_listing_response_is_public_cache_candidate(client):
    response = client.get("/api/listings?page=1&limit=50")

    assert response.status_code == 200
    assert response.headers["X-Radar-Public-Cache"] == "1"
    assert response.headers["Cache-Control"] == PUBLIC_CACHE_CONTROL
    assert "Cookie" in response.headers["Vary"]
    assert response.headers["X-Radar-Cache"] == "miss"
    assert response.headers["X-Radar-Dataset-Version"] == "1"


def test_session_cookie_forces_private_no_store(client):
    client.set_cookie(SESSION_COOKIE_NAME, "test-session")

    response = client.get("/api/signals?include_total=0")

    assert response.headers["Cache-Control"] == "private, no-store"
    assert "X-Radar-Public-Cache" not in response.headers


def test_authorization_header_forces_private_no_store(client):
    response = client.get(
        "/api/signals?include_total=0",
        headers={"Authorization": "Bearer cache-bypass-probe"},
    )

    assert response.headers["Cache-Control"] == "private, no-store"
    assert "X-Radar-Public-Cache" not in response.headers


@pytest.mark.parametrize(
    ("headers", "set_session"),
    (({}, True), ({"Authorization": "Bearer cache-bypass-probe"}, False)),
)
def test_listing_auth_context_forces_private_no_store(
    headers, set_session, client
):
    if set_session:
        client.set_cookie(SESSION_COOKIE_NAME, "test-session")

    response = client.get("/api/listings", headers=headers)

    assert response.headers["Cache-Control"] == "private, no-store"
    assert "X-Radar-Public-Cache" not in response.headers


def test_admin_payload_never_uses_public_cache(monkeypatch, client):
    monkeypatch.setattr(radar_app, "current_tier", lambda: "admin")
    monkeypatch.setattr(auth_core, "current_tier", lambda: "admin")

    response = client.get("/api/signals?include_total=0")

    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Radar-Cache"] == "bypass"


def test_admin_listing_payload_never_uses_public_cache(monkeypatch, client):
    monkeypatch.setattr(radar_app, "current_tier", lambda: "admin")
    monkeypatch.setattr(auth_core, "current_tier", lambda: "admin")

    response = client.get("/api/listings")

    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Radar-Cache"] == "bypass"


def test_guest_cache_receives_only_redacted_signal_payload(monkeypatch, client):
    captured = []
    monkeypatch.setattr(
        radar_app,
        "load_signals",
        lambda *_args, **_kwargs: {
            "signals": [
                {
                    "id": 1,
                    "title": "Gọi 0912345678",
                    "contact_phone": "0912345678",
                    "seller_name": "Broker",
                    "url": "https://source.test/listing",
                    "source_url": "https://source.test/original",
                }
            ],
            "page": 1,
            "limit": 30,
            "has_more": False,
            "sort": "newest",
            "tier": "guest",
        },
    )

    def capture_cache(**kwargs):
        payload = kwargs["loader"]()
        captured.append(payload)
        return CacheResult(payload, "miss", 1.0)

    monkeypatch.setattr(radar_app, "get_or_load_public_payload", capture_cache)

    response = client.get("/api/signals?include_total=0")

    signal = captured[0]["signals"][0]
    assert signal["contact_phone"] is None
    assert signal["seller_name"] is None
    assert signal["url"] is None
    assert signal["source_url"] is None
    assert "0912345678" not in signal["title"]
    assert response.get_json()["signals"] == captured[0]["signals"]


def test_guest_cache_receives_only_redacted_listing_payload(monkeypatch, client):
    captured = []
    monkeypatch.setattr(
        radar_app,
        "load_listing_feed",
        lambda *_args, **_kwargs: {
            "listings": [
                {
                    "id": 11,
                    "title": "Liên hệ 0912345678",
                    "description": "Zalo 0912345678",
                    "contact_phone": "0912345678",
                    "seller_name": "Broker",
                    "url": "https://source.test/listing",
                    "source_url": "https://source.test/original",
                }
            ],
            "page": 1,
            "limit": 50,
            "total": 1,
            "pages": 1,
        },
    )

    def capture_cache(**kwargs):
        payload = kwargs["loader"]()
        captured.append(payload)
        return CacheResult(payload, "miss", 1.0)

    monkeypatch.setattr(radar_app, "get_or_load_public_payload", capture_cache)

    response = client.get("/api/listings")

    listing = captured[0]["listings"][0]
    assert listing["contact_phone"] is None
    assert listing["seller_name"] is None
    assert listing["url"] is None
    assert listing["source_url"] is None
    assert "0912345678" not in listing["title"]
    assert "0912345678" not in listing["description"]
    assert response.get_json()["listings"] == captured[0]["listings"]


def test_cache_backpressure_returns_controlled_503(monkeypatch, client):
    def busy(**_kwargs):
        raise PublicCacheBusy(retry_after=1)

    monkeypatch.setattr(radar_app, "get_or_load_public_payload", busy)

    response = client.get("/api/signals?include_total=0")

    assert response.status_code == 503
    assert response.get_json() == {
        "error": "temporarily_busy",
        "retry_after": 1,
    }
    assert response.headers["Retry-After"] == "1"
    assert response.headers["Cache-Control"] == "no-store"


def test_listing_cache_backpressure_returns_controlled_503(monkeypatch, client):
    def busy(**_kwargs):
        raise PublicCacheBusy(retry_after=2)

    monkeypatch.setattr(radar_app, "get_or_load_public_payload", busy)

    response = client.get("/api/listings")

    assert response.status_code == 503
    assert response.get_json() == {
        "error": "temporarily_busy",
        "retry_after": 2,
    }
    assert response.headers["Retry-After"] == "2"
    assert response.headers["Cache-Control"] == "no-store"


def test_only_anonymous_homepage_is_edge_cache_candidate(client):
    anonymous = client.get("/")
    assert anonymous.headers["X-Radar-Public-Cache"] == "1"
    assert anonymous.headers["Cache-Control"] == PUBLIC_CACHE_CONTROL

    client.set_cookie(SESSION_COOKIE_NAME, "test-session")
    session = client.get("/")
    assert "X-Radar-Public-Cache" not in session.headers
    assert session.headers["Cache-Control"] == "private, no-store"

    authorization = radar_app.app.test_client().get(
        "/", headers={"Authorization": "Bearer probe"}
    )
    assert "X-Radar-Public-Cache" not in authorization.headers
    assert authorization.headers["Cache-Control"] == "private, no-store"


def test_radar_ask_routes_are_always_private_and_never_public_cache_candidates(client, monkeypatch):
    monkeypatch.setenv("RADAR_ASK_ENABLED", "1")

    response = client.get("/api/radar-ask/sessions")

    assert response.headers["Cache-Control"] == "private, no-store"
    assert "X-Radar-Public-Cache" not in response.headers
