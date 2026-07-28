from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

import pytest
from werkzeug.test import EnvironBuilder

from config.settings import DigitalProductCommerceSettings
from services.digital_product_orders import (
    DigitalProductOrder,
    MAX_ORDER_ID,
    OrderCodeRangeError,
)
from services.digital_products import ProductAvailability
from services.payos_client import (
    PayOSPaymentLinkCreationError,
    PayOSWebhookRejected,
    VerifiedPayOSPayment,
)


NOW = datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FakePaymentLink:
    payment_link_id: str = "pay-link-1"
    checkout_url: str = "https://pay.payos.vn/web/pay-link-1"
    qr_payload: str = "0002010102123854"


class InMemoryOrderRepository:
    def __init__(self, *, next_id: int = 1):
        self.next_id = next_id
        self.orders: dict[int, DigitalProductOrder] = {}
        self.events: set[tuple[int, str, str]] = set()
        self.event_payload_hashes: list[str] = []
        self._lock = threading.RLock()

    @contextmanager
    def transaction(self):
        with self._lock:
            yield self

    def insert_pending(
        self,
        *,
        public_id,
        product_slug,
        product_version,
        expected_amount,
        currency,
        created_at,
        payment_expires_at,
    ):
        order_id = self.next_id
        self.next_id += 1
        if order_id > MAX_ORDER_ID:
            raise OrderCodeRangeError(order_id)
        order = DigitalProductOrder(
            id=order_id,
            public_id=public_id,
            product_slug=product_slug,
            product_version=product_version,
            expected_amount=expected_amount,
            currency=currency,
            payos_order_code=720_000_000 + order_id,
            payment_link_id=None,
            checkout_url=None,
            qr_code=None,
            status="pending",
            recovery_token_hash=None,
            paid_amount=None,
            payment_reference=None,
            created_at=created_at,
            payment_expires_at=payment_expires_at,
            paid_at=None,
            download_expires_at=None,
            download_count=0,
            last_download_at=None,
        )
        self.orders[order_id] = order
        return order

    def get_by_public_id(self, public_id, *, for_update=False):
        del for_update
        return next(
            (order for order in self.orders.values() if order.public_id == public_id),
            None,
        )

    def get_by_order_code(self, order_code, *, for_update=False):
        del for_update
        return next(
            (
                order
                for order in self.orders.values()
                if order.payos_order_code == order_code
            ),
            None,
        )

    def attach_payment_link(
        self,
        order_id,
        *,
        payment_link_id,
        checkout_url,
        qr_code,
        recovery_token_hash,
    ):
        order = self.orders[order_id].with_updates(
            payment_link_id=payment_link_id,
            checkout_url=checkout_url,
            qr_code=qr_code,
            recovery_token_hash=recovery_token_hash,
        )
        self.orders[order_id] = order
        return order

    def insert_event_if_absent(
        self,
        *,
        order_id,
        event_type,
        external_reference,
        payload_hash,
        created_at,
    ):
        del created_at
        key = (order_id, event_type, external_reference)
        if key in self.events:
            return False
        self.events.add(key)
        self.event_payload_hashes.append(payload_hash)
        return True

    def mark_payment_review(self, order_id, *, amount, reference):
        order = self.orders[order_id].with_updates(
            status="payment_review",
            paid_amount=amount,
            payment_reference=reference,
            paid_at=None,
            download_expires_at=None,
        )
        self.orders[order_id] = order
        return order

    def mark_paid(
        self,
        order_id,
        *,
        amount,
        reference,
        paid_at,
        download_expires_at,
    ):
        order = self.orders[order_id].with_updates(
            status="paid",
            paid_amount=amount,
            payment_reference=reference,
            paid_at=paid_at,
            download_expires_at=download_expires_at,
        )
        self.orders[order_id] = order
        return order

    def mark_expired(self, order_id):
        order = self.orders[order_id].with_updates(status="expired")
        self.orders[order_id] = order
        return order

    def increment_download(self, order_id, *, downloaded_at):
        del order_id, downloaded_at
        raise AssertionError("Task 4 must not implement downloads")


class FakePayOS:
    def __init__(self):
        self.create_calls: list[tuple[DigitalProductOrder, str, str]] = []
        self.webhook_calls: list[bytes] = []
        self.create_error: Exception | None = None
        self.verified_payment: VerifiedPayOSPayment | None = None

    def create_payment_link(self, order, return_url, cancel_url):
        self.create_calls.append((order, return_url, cancel_url))
        if self.create_error:
            raise self.create_error
        return FakePaymentLink()

    def verify_webhook(self, raw_body):
        self.webhook_calls.append(raw_body)
        if self.verified_payment is None:
            raise PayOSWebhookRejected()
        return self.verified_payment


class FakeCheckoutLocks:
    def __init__(self):
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.Lock()
        self.acquisitions: list[str] = []

    @contextmanager
    def acquire(self, public_id: str):
        with self._guard:
            lock = self._locks.setdefault(public_id, threading.RLock())
        if not lock.acquire(blocking=False):
            raise RuntimeError("checkout lock busy")
        try:
            self.acquisitions.append(public_id)
            yield
        finally:
            lock.release()


@pytest.fixture
def route_env(monkeypatch, tmp_path):
    import app as radar_app
    from auth import core as auth_core
    from routes import digital_products as routes_module

    repo = InMemoryOrderRepository()
    payos = FakePayOS()
    checkout_locks = FakeCheckoutLocks()
    settings = DigitalProductCommerceSettings(
        sales_enabled=True,
        storage_dir=tmp_path.resolve(),
        payos_client_id="client",
        payos_api_key="api",
        payos_checksum_key="checksum",
        cookie_secret="c" * 64,
    )
    monkeypatch.setattr(auth_core, "current_tier", lambda: "test")
    monkeypatch.setattr(
        routes_module,
        "_repository_factory",
        lambda: repo,
        raising=False,
    )
    monkeypatch.setattr(
        routes_module,
        "_payos_client_factory",
        lambda: payos,
        raising=False,
    )
    monkeypatch.setattr(routes_module, "_utcnow", lambda: NOW, raising=False)

    @contextmanager
    def checkout_lock(public_id):
        stack = ExitStack()
        try:
            stack.enter_context(checkout_locks.acquire(public_id))
        except RuntimeError:
            stack.close()
            raise routes_module._CheckoutBusy() from None
        with stack:
            yield

    monkeypatch.setattr(
        routes_module,
        "_checkout_lock_factory",
        checkout_lock,
        raising=False,
    )
    monkeypatch.setattr(
        routes_module,
        "get_digital_product_commerce_settings",
        lambda: settings,
        raising=False,
    )
    monkeypatch.setattr(
        routes_module,
        "get_release_availability",
        lambda product, storage_root, sales_enabled: ProductAvailability(
            package_valid=True,
            sales_enabled=True,
            can_sell=True,
            reason="available",
        ),
        raising=False,
    )
    return radar_app, routes_module, repo, payos, settings


def _checkout(client):
    return client.post("/ban-do-thu-dau-mot/checkout")


def _public_id_from_redirect(response) -> str:
    location = response.headers["Location"]
    return location.split("/don-hang/", 1)[1].split("#", 1)[0]


def _token_from_redirect(response) -> str:
    return unquote(response.headers["Location"].split("#token=", 1)[1])


def _cookie_value(response, name: str) -> str:
    for header in response.headers.getlist("Set-Cookie"):
        parsed = SimpleCookie()
        parsed.load(header)
        if name in parsed:
            return parsed[name].value
    raise AssertionError(f"missing cookie {name}")


def _authorize(client, public_id: str, token: str):
    return client.post(
        f"/api/digital-products/orders/{public_id}/authorize",
        json={"token": token},
    )


def _authorized_order(route_env):
    radar_app, _routes, repo, _payos, _settings = route_env
    client = radar_app.app.test_client()
    checkout = _checkout(client)
    public_id = _public_id_from_redirect(checkout)
    token = _token_from_redirect(checkout)
    authorized = _authorize(client, public_id, token)
    assert authorized.status_code == 204
    return client, repo.orders[1], token


def _sales_disabled_settings(settings):
    return DigitalProductCommerceSettings(
        sales_enabled=False,
        storage_dir=settings.storage_dir,
        payos_client_id="",
        payos_api_key="",
        payos_checksum_key="",
        cookie_secret=settings.cookie_secret,
    )


def test_checkout_is_unavailable_until_settings_and_release_gate_pass(
    route_env,
    monkeypatch,
):
    radar_app, routes_module, _repo, payos, settings = route_env
    monkeypatch.setattr(
        routes_module,
        "get_digital_product_commerce_settings",
        lambda: DigitalProductCommerceSettings(
            sales_enabled=False,
            storage_dir=settings.storage_dir,
            payos_client_id=settings.payos_client_id,
            payos_api_key=settings.payos_api_key,
            payos_checksum_key=settings.payos_checksum_key,
            cookie_secret=settings.cookie_secret,
        ),
    )

    response = _checkout(radar_app.app.test_client())

    assert response.status_code == 503
    assert response.get_json() == {"code": "product_unavailable"}
    assert payos.create_calls == []


def test_checkout_redirect_uses_fragment_token_and_server_product_terms(route_env):
    radar_app, _routes, repo, payos, _settings = route_env

    response = _checkout(radar_app.app.test_client())

    assert response.status_code == 303
    location = response.headers["Location"]
    assert "/ban-do-thu-dau-mot/don-hang/" in location
    assert "#token=" in location
    assert "?token=" not in location
    assert len(_token_from_redirect(response)) >= 43
    order = repo.orders[1]
    assert order.expected_amount == 99_000
    assert order.product_slug == "thu-dau-mot-map-bundle"
    assert order.product_version == "1.0"
    assert len(payos.create_calls) == 1
    assert all(
        url
        == f"https://radarbds.vn/ban-do-thu-dau-mot/don-hang/{order.public_id}"
        for url in payos.create_calls[0][1:]
    )


def test_failed_payment_link_records_event_and_retry_reuses_pending_order(
    route_env,
):
    radar_app, _routes, repo, payos, _settings = route_env
    client = radar_app.app.test_client()
    payos.create_error = PayOSPaymentLinkCreationError()

    failed = _checkout(client)

    assert failed.status_code == 502
    assert failed.get_json() == {"code": "checkout_temporarily_unavailable"}
    assert len(repo.orders) == 1
    assert (1, "payment_link_failed", "") in repo.events
    assert "HttpOnly" in failed.headers["Set-Cookie"]
    assert "Max-Age=300" in failed.headers["Set-Cookie"]

    payos.create_error = None
    retried = _checkout(client)

    assert retried.status_code == 303
    assert len(repo.orders) == 1
    assert len(payos.create_calls) == 2
    assert "Max-Age=300" in retried.headers["Set-Cookie"]


def test_product_page_seed_makes_successive_checkout_idempotent(route_env):
    radar_app, routes_module, repo, payos, _settings = route_env
    client = radar_app.app.test_client()

    product_page = client.get("/ban-do-thu-dau-mot")
    seed_cookie = _cookie_value(
        product_page,
        "radar_product_checkout_retry",
    )
    seed_payload = routes_module._retry_serializer("c" * 64).loads(
        seed_cookie,
        max_age=300,
    )
    first = _checkout(client)
    second = _checkout(client)

    assert seed_payload == {
        "public_id": _public_id_from_redirect(first),
        "phase": "seed",
    }
    assert first.status_code == second.status_code == 303
    assert _public_id_from_redirect(first) == _public_id_from_redirect(second)
    assert _token_from_redirect(first) != _token_from_redirect(second)
    assert len(repo.orders) == 1
    assert len(payos.create_calls) == 1


def test_stale_concurrent_seed_does_not_duplicate_or_rotate_winner_token(
    route_env,
):
    radar_app, routes_module, repo, payos, _settings = route_env
    seed_client = radar_app.app.test_client()
    seed_response = seed_client.get("/ban-do-thu-dau-mot")
    seed_value = _cookie_value(
        seed_response,
        "radar_product_checkout_retry",
    )
    seed_payload = routes_module._retry_serializer("c" * 64).loads(
        seed_value,
        max_age=300,
    )
    winner_client = radar_app.app.test_client()
    stale_client = radar_app.app.test_client()
    for client in (winner_client, stale_client):
        client.set_cookie(
            "radar_product_checkout_retry",
            seed_value,
            path="/ban-do-thu-dau-mot",
        )

    winner = _checkout(winner_client)
    winner_token = _token_from_redirect(winner)
    stale = _checkout(stale_client)
    public_id = seed_payload["public_id"]

    assert winner.status_code == 303
    assert stale.status_code == 409
    assert stale.get_json() == {"code": "checkout_in_progress"}
    assert len(repo.orders) == 1
    assert len(payos.create_calls) == 1
    assert (
        routes_module.verify_recovery_token(
            public_id,
            winner_token,
            now=NOW,
            repo=repo,
        )
        is not None
    )
    stale_linked = routes_module._retry_serializer("c" * 64).loads(
        _cookie_value(stale, "radar_product_checkout_retry"),
        max_age=300,
    )
    assert stale_linked == {"public_id": public_id, "phase": "linked"}


def test_advisory_lock_serializes_requests_while_payos_is_in_flight(route_env):
    radar_app, routes_module, repo, payos, _settings = route_env
    seed_client = radar_app.app.test_client()
    seed_value = _cookie_value(
        seed_client.get("/ban-do-thu-dau-mot"),
        "radar_product_checkout_retry",
    )
    public_id = routes_module._retry_serializer("c" * 64).loads(
        seed_value,
        max_age=300,
    )["public_id"]
    winner_client = radar_app.app.test_client()
    stale_client = radar_app.app.test_client()
    for client in (winner_client, stale_client):
        client.set_cookie(
            "radar_product_checkout_retry",
            seed_value,
            path="/ban-do-thu-dau-mot",
        )

    payos_entered = threading.Event()
    release_payos = threading.Event()

    def blocked_create(order, return_url, cancel_url):
        payos.create_calls.append((order, return_url, cancel_url))
        payos_entered.set()
        assert release_payos.wait(timeout=5)
        return FakePaymentLink()

    payos.create_payment_link = blocked_create
    with ThreadPoolExecutor(max_workers=2) as pool:
        winner_future = pool.submit(_checkout, winner_client)
        assert payos_entered.wait(timeout=5)
        stale_future = pool.submit(_checkout, stale_client)
        done, _not_done = wait([stale_future], timeout=5)
        assert stale_future in done
        stale = stale_future.result(timeout=5)
        release_payos.set()
        winner = winner_future.result(timeout=5)

    assert winner.status_code == 303
    assert stale.status_code == 409
    assert len(repo.orders) == 1
    assert len(payos.create_calls) == 1
    assert (
        routes_module.verify_recovery_token(
            public_id,
            _token_from_redirect(winner),
            now=NOW,
            repo=repo,
        )
        is not None
    )


def test_busy_advisory_lock_returns_retry_without_order_or_payos(
    route_env,
    monkeypatch,
):
    radar_app, routes_module, repo, payos, _settings = route_env
    client = radar_app.app.test_client()
    seed = client.get("/ban-do-thu-dau-mot")
    seed_value = _cookie_value(seed, "radar_product_checkout_retry")
    seed_payload = routes_module._retry_serializer("c" * 64).loads(
        seed_value,
        max_age=300,
    )

    @contextmanager
    def busy_lock(_public_id):
        raise routes_module._CheckoutBusy()
        yield

    monkeypatch.setattr(routes_module, "_checkout_lock_factory", busy_lock)

    response = _checkout(client)

    assert response.status_code == 409
    assert response.get_json() == {"code": "checkout_in_progress"}
    assert repo.orders == {}
    assert payos.create_calls == []
    retry_payload = routes_module._retry_serializer("c" * 64).loads(
        _cookie_value(response, "radar_product_checkout_retry"),
        max_age=300,
    )
    assert retry_payload == seed_payload


def test_runtime_error_inside_checkout_body_is_not_misreported_as_lock_busy(
    route_env,
):
    radar_app, _routes, repo, payos, _settings = route_env
    client = radar_app.app.test_client()
    client.get("/ban-do-thu-dau-mot")
    payos.create_error = RuntimeError("internal body failure")

    response = _checkout(client)

    assert response.status_code == 503
    assert response.get_json() == {
        "code": "checkout_temporarily_unavailable"
    }
    assert len(repo.orders) == 1
    assert len(payos.create_calls) == 1


def test_order_page_without_cookie_never_exposes_payment_data(route_env):
    radar_app, _routes, repo, _payos, _settings = route_env
    client = radar_app.app.test_client()
    checkout = _checkout(client)
    order = repo.orders[1]

    response = client.get(
        f"/ban-do-thu-dau-mot/don-hang/{order.public_id}?status=success"
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert order.qr_code not in html
    assert str(order.payos_order_code) not in html
    assert order.checkout_url not in html
    assert _token_from_redirect(checkout) not in html
    assert repo.orders[1].status == "pending"


def test_order_page_never_loads_analytics_that_could_receive_order_url(route_env):
    radar_app, _routes, repo, _payos, _settings = route_env
    client = radar_app.app.test_client()
    _checkout(client)
    order = repo.orders[1]

    response = client.get(
        f"/ban-do-thu-dau-mot/don-hang/{order.public_id}",
        base_url="https://radarbds.vn",
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "googletagmanager.com" not in html
    assert "/api/track" not in html


def test_authorize_sets_scoped_http_only_cookie_and_never_echoes_token(route_env):
    radar_app, _routes, _repo, _payos, _settings = route_env
    client = radar_app.app.test_client()
    checkout = _checkout(client)
    public_id = _public_id_from_redirect(checkout)
    token = _token_from_redirect(checkout)

    response = _authorize(client, public_id, token)

    assert response.status_code == 204
    cookie = response.headers["Set-Cookie"]
    assert "radar_product_order=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=Lax" in cookie
    assert f"Path=/api/digital-products/orders/{public_id}" in cookie
    assert "Max-Age=90000" in cookie
    assert token not in response.get_data(as_text=True)
    assert token not in cookie


def test_recovery_token_is_reusable_until_server_side_expiry(route_env):
    radar_app, _routes, _repo, _payos, _settings = route_env
    checkout = _checkout(radar_app.app.test_client())
    public_id = _public_id_from_redirect(checkout)
    token = _token_from_redirect(checkout)

    first = _authorize(radar_app.app.test_client(), public_id, token)
    second = _authorize(radar_app.app.test_client(), public_id, token)

    assert first.status_code == 204
    assert second.status_code == 204


@pytest.mark.parametrize("order_status", ["pending", "paid"])
def test_existing_order_authorize_and_status_survive_sales_being_disabled(
    route_env,
    monkeypatch,
    order_status,
):
    radar_app, routes_module, repo, _payos, settings = route_env
    client = radar_app.app.test_client()
    checkout = _checkout(client)
    public_id = _public_id_from_redirect(checkout)
    token = _token_from_redirect(checkout)
    if order_status == "paid":
        repo.orders[1] = repo.orders[1].with_updates(
            status="paid",
            paid_amount=99_000,
            paid_at=NOW,
            download_expires_at=NOW + timedelta(hours=24),
        )
    monkeypatch.setattr(
        routes_module,
        "get_digital_product_commerce_settings",
        lambda: _sales_disabled_settings(settings),
    )

    authorized = _authorize(client, public_id, token)
    status = client.get(
        f"/api/digital-products/orders/{public_id}/status"
    )

    assert authorized.status_code == 204
    assert status.status_code == 200
    assert status.get_json()["status"] == order_status


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"token": ""},
        {"token": 123},
        {"token": "wrong"},
        {"token": "wrong", "extra": True},
    ],
)
def test_invalid_authorize_payload_and_unknown_order_are_indistinguishable(
    route_env,
    payload,
):
    radar_app, _routes, _repo, _payos, _settings = route_env
    client = radar_app.app.test_client()
    checkout = _checkout(client)
    public_id = _public_id_from_redirect(checkout)

    if payload is None:
        invalid = client.post(
            f"/api/digital-products/orders/{public_id}/authorize",
            data=b"not-json",
            content_type="text/plain",
        )
    else:
        invalid = client.post(
            f"/api/digital-products/orders/{public_id}/authorize",
            json=payload,
        )
    unknown = client.post(
        "/api/digital-products/orders/ffffffffffffffffffffffffffffffff/authorize",
        json={"token": "wrong"},
    )

    assert invalid.status_code == unknown.status_code == 404
    assert invalid.get_json() == unknown.get_json() == {
        "code": "order_not_found"
    }


def test_authorize_rejects_expired_pending_order_without_cookie(
    route_env,
    monkeypatch,
):
    radar_app, routes_module, _repo, _payos, _settings = route_env
    client = radar_app.app.test_client()
    checkout = _checkout(client)
    public_id = _public_id_from_redirect(checkout)
    token = _token_from_redirect(checkout)
    monkeypatch.setattr(
        routes_module,
        "_utcnow",
        lambda: NOW + timedelta(minutes=15),
    )

    response = _authorize(client, public_id, token)

    assert response.status_code == 404
    assert response.get_json() == {"code": "order_not_found"}
    assert "radar_product_order=" not in response.headers.get("Set-Cookie", "")


def test_authorize_rejects_oversized_body_before_token_verification(route_env):
    radar_app, _routes, repo, _payos, _settings = route_env
    client = radar_app.app.test_client()
    checkout = _checkout(client)
    public_id = _public_id_from_redirect(checkout)
    token = _token_from_redirect(checkout)
    oversized = (" " * 2_048) + json.dumps({"token": token})

    response = client.post(
        f"/api/digital-products/orders/{public_id}/authorize",
        data=oversized,
        content_type="application/json",
    )

    assert response.status_code == 404
    assert response.get_json() == {"code": "order_not_found"}
    assert repo.orders[1].status == "pending"
    assert "radar_product_order=" not in response.headers.get("Set-Cookie", "")


def test_status_requires_order_scoped_cookie_and_returns_only_safe_fields(route_env):
    client, order, _token = _authorized_order(route_env)

    response = client.get(
        f"/api/digital-products/orders/{order.public_id}/status"
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    payload = response.get_json()
    assert payload == {
        "status": "pending",
        "amount_vnd": 99_000,
        "payment_expires_at": "2026-07-29T09:45:00+00:00",
        "download_expires_at": None,
        "qr_svg_data_uri": payload["qr_svg_data_uri"],
        "order_label": "BDBWO3K1",
        "download_url": None,
    }
    assert payload["qr_svg_data_uri"].startswith(
        "data:image/svg+xml;base64,"
    )
    rendered = json.dumps(payload, sort_keys=True)
    for sensitive in (
        str(order.payos_order_code),
        order.payment_link_id,
        order.checkout_url,
        order.qr_code,
        order.recovery_token_hash,
    ):
        assert sensitive not in rendered


def test_status_cookie_cannot_authorize_a_different_order(route_env):
    radar_app, _routes, repo, _payos, _settings = route_env
    client = radar_app.app.test_client()
    first = _checkout(client)
    first_id = _public_id_from_redirect(first)
    _authorize(client, first_id, _token_from_redirect(first))

    second = _checkout(radar_app.app.test_client())
    second_id = _public_id_from_redirect(second)
    assert len(repo.orders) == 2

    response = client.get(
        f"/api/digital-products/orders/{second_id}/status"
    )

    assert response.status_code == 404
    assert response.get_json() == {"code": "order_not_found"}


def test_status_expires_stale_pending_order_without_polling_payos(
    route_env,
    monkeypatch,
):
    radar_app, routes_module, repo, payos, _settings = route_env
    client = radar_app.app.test_client()
    checkout = _checkout(client)
    public_id = _public_id_from_redirect(checkout)
    token = _token_from_redirect(checkout)
    _authorize(client, public_id, token)
    monkeypatch.setattr(
        routes_module,
        "_utcnow",
        lambda: NOW + timedelta(minutes=15),
    )

    response = client.get(
        f"/api/digital-products/orders/{public_id}/status"
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "expired"
    assert response.get_json()["qr_svg_data_uri"] is None
    assert response.get_json()["download_url"] is None
    assert repo.orders[1].status == "expired"
    assert len(payos.create_calls) == 1
    assert payos.webhook_calls == []


@pytest.mark.parametrize(
    "terminal_status",
    ["expired", "cancelled", "payment_review"],
)
def test_cookie_authorized_terminal_order_returns_safe_status_without_qr(
    route_env,
    terminal_status,
):
    client, order, _token = _authorized_order(route_env)
    _radar_app, _routes, repo, _payos, _settings = route_env
    repo.orders[1] = order.with_updates(
        status=terminal_status,
        paid_amount=98_000 if terminal_status == "payment_review" else None,
        payment_reference=(
            "UNDERPAYMENT" if terminal_status == "payment_review" else None
        ),
    )

    response = client.get(
        f"/api/digital-products/orders/{order.public_id}/status"
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["status"] == terminal_status
    assert payload["qr_svg_data_uri"] is None
    assert payload["download_url"] is None
    rendered = json.dumps(payload, sort_keys=True)
    assert order.qr_code not in rendered
    assert "UNDERPAYMENT" not in rendered


def test_return_and_cancel_query_never_set_paid(route_env):
    radar_app, _routes, repo, _payos, _settings = route_env
    client = radar_app.app.test_client()
    checkout = _checkout(client)
    public_id = _public_id_from_redirect(checkout)

    for query in ("status=success", "cancel=true", "code=00"):
        response = client.get(
            f"/ban-do-thu-dau-mot/don-hang/{public_id}?{query}"
        )
        assert response.status_code == 200

    assert repo.orders[1].status == "pending"


def test_verified_underpayment_is_review_and_duplicate_is_idempotent(route_env):
    radar_app, _routes, repo, payos, _settings = route_env
    _checkout(radar_app.app.test_client())
    order = repo.orders[1]
    raw = b'{"code":"00","success":true}'
    payos.verified_payment = VerifiedPayOSPayment(
        order_code=order.payos_order_code,
        amount=98_000,
        reference="BANK-REF-UNDER",
        paid_at=NOW,
        success=True,
        payload_hash=hashlib.sha256(raw).hexdigest(),
    )
    client = radar_app.app.test_client()

    first = client.post(
        "/api/webhooks/payos/digital-products",
        data=raw,
        content_type="application/json",
    )
    duplicate = client.post(
        "/api/webhooks/payos/digital-products",
        data=raw,
        content_type="application/json",
    )

    assert first.status_code == duplicate.status_code == 200
    assert first.get_json() == duplicate.get_json() == {"success": True}
    assert repo.orders[1].status == "payment_review"
    assert repo.orders[1].download_expires_at is None
    assert payos.webhook_calls == [raw, raw]


def test_webhook_rejection_and_unknown_order_have_closed_responses(route_env):
    radar_app, _routes, repo, payos, _settings = route_env
    raw = b'{"code":"00"}'
    client = radar_app.app.test_client()

    rejected = client.post(
        "/api/webhooks/payos/digital-products",
        data=raw,
        content_type="application/json",
    )
    assert rejected.status_code == 400
    assert rejected.get_json() == {"success": False}

    payos.verified_payment = VerifiedPayOSPayment(
        order_code=720_000_123,
        amount=99_000,
        reference="UNKNOWN",
        paid_at=NOW,
        success=True,
        payload_hash=hashlib.sha256(raw).hexdigest(),
    )
    unknown = client.post(
        "/api/webhooks/payos/digital-products",
        data=raw,
        content_type="application/json",
    )

    assert unknown.status_code == 404
    assert unknown.get_json() == {"success": False}
    assert repo.orders == {}


def test_webhook_rejects_oversized_body_before_payos_verification(route_env):
    radar_app, _routes, _repo, payos, _settings = route_env

    response = radar_app.app.test_client().post(
        "/api/webhooks/payos/digital-products",
        data=b"x" * (64 * 1_024 + 1),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json() == {"success": False}
    assert payos.webhook_calls == []


def test_webhook_without_content_length_reads_only_bounded_stream(route_env):
    radar_app, routes_module, _repo, payos, _settings = route_env
    raw = b"x" * (64 * 1_024 + 2_048)

    class GuardedStream(BytesIO):
        def __init__(self, data):
            super().__init__(data)
            self.read_sizes = []

        def read(self, size=-1):
            self.read_sizes.append(size)
            if size < 0 or size > 64 * 1_024 + 1:
                raise AssertionError("webhook performed an unbounded stream read")
            return super().read(size)

    builder = EnvironBuilder(
        path="/api/webhooks/payos/digital-products",
        method="POST",
        input_stream=BytesIO(b""),
        content_type="application/json",
    )
    environ = builder.get_environ()
    guarded_stream = GuardedStream(raw)
    environ["wsgi.input"] = guarded_stream
    environ.pop("CONTENT_LENGTH", None)
    environ["wsgi.input_terminated"] = True

    with radar_app.app.request_context(environ):
        response = radar_app.app.make_response(
            routes_module.payos_digital_products_webhook()
        )

    assert response.status_code == 400
    assert response.get_json() == {"success": False}
    assert guarded_stream.read_sizes == [64 * 1_024 + 1]
    assert payos.webhook_calls == []


def test_sellable_product_page_uses_post_forms_without_client_price(
    route_env,
    monkeypatch,
):
    radar_app, _routes, _repo, _payos, settings = route_env
    monkeypatch.setattr(
        radar_app,
        "get_digital_product_commerce_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        radar_app,
        "get_release_availability",
        lambda product, storage_root, sales_enabled: ProductAvailability(
            package_valid=True,
            sales_enabled=True,
            can_sell=True,
            reason="available",
        ),
    )

    response = radar_app.app.test_client().get("/ban-do-thu-dau-mot")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert html.count('action="/ban-do-thu-dau-mot/checkout"') == 2
    assert html.count('method="post"') >= 2
    assert 'name="price"' not in html
    assert 'name="slug"' not in html
    assert 'name="version"' not in html
    assert "Mua và thanh toán 99.000đ" in html
