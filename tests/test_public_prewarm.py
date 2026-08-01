from contextlib import contextmanager

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
