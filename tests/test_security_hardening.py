from pathlib import Path

from flask import Flask

from auth.core import (
    SESSION_COOKIE_NAME,
    client_ip_from_request,
    reject_cross_site_session_request,
)


def _request(app, *, base_url="https://radarbds.vn", origin=None, referer=None):
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}=test-session"}
    if origin is not None:
        headers["Origin"] = origin
    if referer is not None:
        headers["Referer"] = referer
    return app.test_request_context(
        "/api/watchlists",
        method="POST",
        base_url=base_url,
        headers=headers,
    )


def test_client_ip_uses_proxy_controlled_real_ip():
    app = Flask(__name__)
    with app.test_request_context(
        "/",
        headers={
            "X-Real-IP": "203.0.113.9",
            "X-Forwarded-For": "198.51.100.7, 203.0.113.9",
        },
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        assert client_ip_from_request() == "203.0.113.9"


def test_session_mutation_accepts_same_origin():
    app = Flask(__name__)
    with _request(app, origin="https://radarbds.vn"):
        assert reject_cross_site_session_request() is None


def test_session_mutation_accepts_same_origin_referer():
    app = Flask(__name__)
    with _request(app, referer="https://radarbds.vn/dashboard"):
        assert reject_cross_site_session_request() is None


def test_session_mutation_rejects_cross_origin():
    app = Flask(__name__)
    with _request(app, origin="https://attacker.example"):
        response, status = reject_cross_site_session_request()
        assert status == 403
        assert response.get_json()["error"] == "cross_site_request"


def test_session_mutation_rejects_missing_origin_on_public_host():
    app = Flask(__name__)
    with _request(app):
        assert reject_cross_site_session_request()[1] == 403


def test_local_test_client_can_omit_origin():
    app = Flask(__name__)
    with _request(app, base_url="http://localhost"):
        assert reject_cross_site_session_request() is None


def test_request_without_session_cookie_is_unchanged():
    app = Flask(__name__)
    with app.test_request_context(
        "/api/auth/login",
        method="POST",
        base_url="https://radarbds.vn",
        headers={"Origin": "https://attacker.example"},
    ):
        assert reject_cross_site_session_request() is None


def test_production_public_url_forces_secure_cookie(monkeypatch):
    import app as radar_app

    monkeypatch.setattr(radar_app, "PUBLIC_BASE_URL", "https://radarbds.vn")
    with radar_app.app.test_request_context("http://localhost/api/auth/login"):
        assert radar_app._cookie_kwargs()["secure"] is True


def test_nginx_config_hides_version_and_covers_dynamic_and_static_responses():
    config_path = (
        Path(__file__).resolve().parents[1]
        / "deployment"
        / "ubuntu24"
        / "nginx-radar-bds.conf"
    )
    text = config_path.read_text(encoding="utf-8")

    assert text.count("server_tokens off;") == 2
    for header in (
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "Content-Security-Policy",
    ):
        assert text.count(f"add_header {header} ") == 4


def test_flask_adds_security_headers_to_success_api_and_error_responses():
    import app as radar_app

    test_app = Flask(__name__)
    test_app.after_request(radar_app.add_response_headers)
    test_app.add_url_rule("/", endpoint="home", view_func=lambda: "ok")
    test_app.add_url_rule("/api/ping", endpoint="ping", view_func=lambda: {"ok": True})
    expected = {
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        "Content-Security-Policy": (
            "default-src 'self'; script-src 'self' 'unsafe-inline' "
            "https://cdn.jsdelivr.net https://unpkg.com https://www.googletagmanager.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com "
            "https://cdn.jsdelivr.net https://unpkg.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self' https://www.google-analytics.com "
            "https://region1.google-analytics.com https://www.googletagmanager.com; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        ),
    }

    client = test_app.test_client()
    for path in ("/", "/api/ping", "/missing"):
        response = client.get(path)
        assert {name: response.headers.get(name) for name in expected} == expected
