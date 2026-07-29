from __future__ import annotations

import hashlib
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask, jsonify

from services.digital_product_orders import (
    MAX_ORDER_ID,
    DigitalProductOrder,
    InvalidSettlement,
    OrderCodeRangeError,
    OrderLifecycleError,
    OrderNotFound,
    PostgresOrderRepository,
    SettlementNotFound,
    attach_payment_link,
    can_download,
    create_pending_order,
    expire_pending_order,
    get_order,
    record_download,
    settle_verified_payment,
    verify_recovery_token,
)
from services.digital_products import DigitalProduct, get_digital_product


@pytest.mark.parametrize(
    "slug,filename",
    (
        (
            "thu-dau-mot-map-bundle",
            "radarbds-thu-dau-mot-map-v1.0.zip",
        ),
        ("thuan-an-map-bundle", "radarbds-thuan-an-map-v1.0.zip"),
        ("di-an-map-bundle", "radarbds-di-an-map-v1.0.zip"),
        ("ben-cat-map-bundle", "radarbds-ben-cat-map-v1.0.zip"),
    ),
)
def test_city_map_products_are_registered_at_server_terms(
    slug: str,
    filename: str,
) -> None:
    product = get_digital_product(slug)

    assert product.price_vnd == 99_000
    assert product.version == "1.0"
    assert product.package_filename == filename
    assert product.download_filename == filename
    assert len(product.package_sha256) == 64
    assert len(product.manifest_sha256) == 64


@dataclass(frozen=True)
class FakePaymentLink:
    payment_link_id: str
    checkout_url: str
    qr_payload: str


class InMemoryOrderRepository:
    """Deterministic transaction fake; the lock models one DB transaction."""

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
        public_id: str,
        product_slug: str,
        product_version: str,
        expected_amount: int,
        currency: str,
        created_at: datetime,
        payment_expires_at: datetime,
    ) -> DigitalProductOrder:
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

    def get_by_public_id(
        self,
        public_id: str,
        *,
        for_update: bool = False,
    ) -> DigitalProductOrder | None:
        del for_update
        return next(
            (order for order in self.orders.values() if order.public_id == public_id),
            None,
        )

    def get_by_order_code(
        self,
        order_code: int,
        *,
        for_update: bool = False,
    ) -> DigitalProductOrder | None:
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
        order_id: int,
        *,
        payment_link_id: str,
        checkout_url: str,
        qr_code: str,
        recovery_token_hash: str,
    ) -> DigitalProductOrder:
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
        order_id: int,
        event_type: str,
        external_reference: str,
        payload_hash: str,
        created_at: datetime,
    ) -> bool:
        del created_at
        key = (order_id, event_type, external_reference)
        if key in self.events:
            return False
        self.events.add(key)
        self.event_payload_hashes.append(payload_hash)
        return True

    def mark_payment_review(
        self,
        order_id: int,
        *,
        amount: int,
        reference: str,
    ) -> DigitalProductOrder:
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
        order_id: int,
        *,
        amount: int,
        reference: str,
        paid_at: datetime,
        download_expires_at: datetime,
    ) -> DigitalProductOrder:
        order = self.orders[order_id].with_updates(
            status="paid",
            paid_amount=amount,
            payment_reference=reference,
            paid_at=paid_at,
            download_expires_at=download_expires_at,
        )
        self.orders[order_id] = order
        return order

    def mark_expired(self, order_id: int) -> DigitalProductOrder:
        order = self.orders[order_id].with_updates(status="expired")
        self.orders[order_id] = order
        return order

    def increment_download(self, order_id: int, *, downloaded_at: datetime) -> bool:
        order = self.orders.get(order_id)
        if order is None:
            return False
        last_download_at = (
            downloaded_at
            if order.last_download_at is None
            else max(order.last_download_at, downloaded_at)
        )
        self.orders[order_id] = order.with_updates(
            download_count=order.download_count + 1,
            last_download_at=last_download_at,
        )
        return True

    def serialized_rows(self) -> str:
        return json.dumps(
            [
                {
                    "id": order.id,
                    "public_id": order.public_id,
                    "product_slug": order.product_slug,
                    "product_version": order.product_version,
                    "expected_amount": order.expected_amount,
                    "currency": order.currency,
                    "payos_order_code": order.payos_order_code,
                    "payment_link_id": order.payment_link_id,
                    "checkout_url": order.checkout_url,
                    "qr_code": order.qr_code,
                    "status": order.status,
                    "recovery_token_hash": order.recovery_token_hash,
                    "paid_amount": order.paid_amount,
                    "payment_reference": order.payment_reference,
                    "created_at": order.created_at,
                    "payment_expires_at": order.payment_expires_at,
                    "paid_at": order.paid_at,
                    "download_expires_at": order.download_expires_at,
                    "download_count": order.download_count,
                    "last_download_at": order.last_download_at,
                }
                for order in self.orders.values()
            ],
            default=str,
            sort_keys=True,
        )


@pytest.fixture
def frozen_now() -> datetime:
    return datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)


@pytest.fixture
def product() -> DigitalProduct:
    return get_digital_product("thu-dau-mot-map-bundle")


@pytest.fixture
def order_repo() -> InMemoryOrderRepository:
    return InMemoryOrderRepository()


@pytest.fixture
def pending_order(
    product: DigitalProduct,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
) -> DigitalProductOrder:
    return create_pending_order(product, frozen_now, repo=order_repo)


@pytest.fixture
def payment_link() -> FakePaymentLink:
    return FakePaymentLink(
        payment_link_id="pay-link-1",
        checkout_url="https://pay.payos.vn/web/pay-link-1",
        qr_payload="0002010102123854",
    )


def _payload_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def test_pending_order_uses_only_canonical_server_product_terms(
    product: DigitalProduct,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    forged = replace(product, version="forged", price_vnd=1)

    order = create_pending_order(forged, frozen_now, repo=order_repo)

    assert order.expected_amount == 99_000
    assert order.product_slug == "thu-dau-mot-map-bundle"
    assert order.product_version == "1.0"
    assert order.currency == "VND"
    assert order.payment_expires_at == frozen_now + timedelta(minutes=15)
    assert order.recovery_token_hash is None
    assert len(order.public_id) == 32
    assert uuid.UUID(hex=order.public_id).version == 4
    assert order.payos_order_code == 720_000_000 + order.id


def test_pending_order_accepts_valid_controller_public_id(
    product: DigitalProduct,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    controller_public_id = "0123456789abcdef0123456789abcdef"

    order = create_pending_order(
        product,
        frozen_now,
        public_id=controller_public_id,
        repo=order_repo,
    )

    assert order.public_id == controller_public_id


@pytest.mark.parametrize(
    "invalid_public_id",
    [
        "",
        "short",
        "0123456789ABCDEF0123456789ABCDEF",
        "g" * 32,
        "0" * 31,
        "0" * 33,
        123,
        True,
    ],
)
def test_pending_order_rejects_invalid_controller_public_id_before_insert(
    product: DigitalProduct,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
    invalid_public_id,
):
    with pytest.raises(OrderLifecycleError):
        create_pending_order(
            product,
            frozen_now,
            public_id=invalid_public_id,
            repo=order_repo,
        )

    assert order_repo.orders == {}


def test_order_code_rejects_ids_outside_signed_32_bit_range(
    product: DigitalProduct,
    frozen_now: datetime,
):
    repo = InMemoryOrderRepository(next_id=MAX_ORDER_ID + 1)

    with pytest.raises(OrderCodeRangeError):
        create_pending_order(product, frozen_now, repo=repo)

    assert repo.orders == {}


def test_attaching_link_returns_secret_but_persists_only_sha256_hash(
    pending_order: DigitalProductOrder,
    payment_link: FakePaymentLink,
    order_repo: InMemoryOrderRepository,
):
    result = attach_payment_link(
        pending_order.public_id,
        payment_link,
        repo=order_repo,
    )

    assert len(result.raw_recovery_token) >= 43
    assert result.order.recovery_token_hash == hashlib.sha256(
        result.raw_recovery_token.encode("utf-8")
    ).hexdigest()
    assert result.order.payment_link_id == payment_link.payment_link_id
    assert result.order.checkout_url == payment_link.checkout_url
    assert result.order.qr_code == payment_link.qr_payload
    assert result.raw_recovery_token not in order_repo.serialized_rows()
    assert result.raw_recovery_token not in repr(result)
    assert result.order.recovery_token_hash not in repr(result.order)


def test_retry_rotates_token_while_reusing_existing_payment_link(
    pending_order: DigitalProductOrder,
    payment_link: FakePaymentLink,
    order_repo: InMemoryOrderRepository,
):
    first = attach_payment_link(
        pending_order.public_id,
        payment_link,
        repo=order_repo,
    )
    replacement_link = FakePaymentLink(
        payment_link_id="must-not-replace",
        checkout_url="https://malicious.invalid/replacement",
        qr_payload="replacement-qr",
    )

    second = attach_payment_link(
        pending_order.public_id,
        replacement_link,
        repo=order_repo,
    )

    assert second.raw_recovery_token != first.raw_recovery_token
    assert verify_recovery_token(
        pending_order.public_id,
        first.raw_recovery_token,
        now=pending_order.created_at,
        repo=order_repo,
    ) is None
    assert verify_recovery_token(
        pending_order.public_id,
        second.raw_recovery_token,
        now=pending_order.created_at,
        repo=order_repo,
    ) == second.order
    assert second.order.payment_link_id == payment_link.payment_link_id
    assert second.order.checkout_url == payment_link.checkout_url
    assert second.order.qr_code == payment_link.qr_payload


def test_recovery_token_can_be_verified_repeatedly_until_rotation(
    pending_order: DigitalProductOrder,
    payment_link: FakePaymentLink,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    first = attach_payment_link(
        pending_order.public_id,
        payment_link,
        repo=order_repo,
    )

    assert verify_recovery_token(
        pending_order.public_id,
        first.raw_recovery_token,
        now=frozen_now,
        repo=order_repo,
    ) == first.order
    assert verify_recovery_token(
        pending_order.public_id,
        first.raw_recovery_token,
        now=frozen_now + timedelta(minutes=1),
        repo=order_repo,
    ) == first.order

    second = attach_payment_link(
        pending_order.public_id,
        payment_link,
        repo=order_repo,
    )
    assert verify_recovery_token(
        pending_order.public_id,
        first.raw_recovery_token,
        now=frozen_now + timedelta(minutes=1),
        repo=order_repo,
    ) is None
    assert verify_recovery_token(
        pending_order.public_id,
        second.raw_recovery_token,
        now=frozen_now + timedelta(minutes=1),
        repo=order_repo,
    ) == second.order


def test_recovery_token_expires_with_paid_download_window(
    pending_order: DigitalProductOrder,
    payment_link: FakePaymentLink,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    secret = attach_payment_link(
        pending_order.public_id,
        payment_link,
        repo=order_repo,
    )
    paid = settle_verified_payment(
        pending_order.payos_order_code,
        99_000,
        "BANK-REF-RECOVERY",
        frozen_now,
        _payload_hash("recovery-expiry"),
        repo=order_repo,
    ).order

    assert verify_recovery_token(
        paid.public_id,
        secret.raw_recovery_token,
        now=paid.download_expires_at - timedelta(microseconds=1),
        repo=order_repo,
    ) == paid
    assert verify_recovery_token(
        paid.public_id,
        secret.raw_recovery_token,
        now=paid.download_expires_at,
        repo=order_repo,
    ) is None


def test_concurrent_token_rotation_leaves_exactly_one_secret_valid(
    pending_order: DigitalProductOrder,
    payment_link: FakePaymentLink,
    order_repo: InMemoryOrderRepository,
):
    barrier = threading.Barrier(2)

    def attach():
        barrier.wait()
        return attach_payment_link(
            pending_order.public_id,
            payment_link,
            repo=order_repo,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        secrets_returned = list(pool.map(lambda _: attach(), range(2)))

    assert len({secret.raw_recovery_token for secret in secrets_returned}) == 2
    valid = [
        verify_recovery_token(
            pending_order.public_id,
            secret.raw_recovery_token,
            now=pending_order.created_at,
            repo=order_repo,
        )
        is not None
        for secret in secrets_returned
    ]
    assert sorted(valid) == [False, True]


def test_token_verification_uses_constant_time_digest_comparison(
    monkeypatch: pytest.MonkeyPatch,
    pending_order: DigitalProductOrder,
    payment_link: FakePaymentLink,
    order_repo: InMemoryOrderRepository,
):
    secret = attach_payment_link(
        pending_order.public_id,
        payment_link,
        repo=order_repo,
    )
    comparisons: list[tuple[str, str]] = []

    def recording_compare(left: str, right: str) -> bool:
        comparisons.append((left, right))
        return left == right

    monkeypatch.setattr(
        "services.digital_product_orders.hmac.compare_digest",
        recording_compare,
    )

    assert verify_recovery_token(
        pending_order.public_id,
        secret.raw_recovery_token,
        now=pending_order.created_at,
        repo=order_repo,
    ) == secret.order
    assert comparisons == [
        (
            secret.order.recovery_token_hash,
            hashlib.sha256(secret.raw_recovery_token.encode("utf-8")).hexdigest(),
        )
    ]


def test_unknown_public_id_performs_dummy_hash_and_constant_time_compare(
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
    monkeypatch: pytest.MonkeyPatch,
):
    from services import digital_product_orders as order_module

    real_sha256 = hashlib.sha256
    real_compare_digest = order_module.hmac.compare_digest
    hashed_inputs: list[bytes] = []
    compared: list[tuple[str, str]] = []

    def tracked_sha256(value: bytes):
        hashed_inputs.append(value)
        return real_sha256(value)

    def tracked_compare_digest(left: str, right: str):
        compared.append((left, right))
        return real_compare_digest(left, right)

    monkeypatch.setattr(order_module.hashlib, "sha256", tracked_sha256)
    monkeypatch.setattr(order_module.hmac, "compare_digest", tracked_compare_digest)

    result = verify_recovery_token(
        "f" * 32,
        "unknown-order-token",
        now=frozen_now,
        repo=order_repo,
    )

    assert result is None
    assert hashed_inputs == [b"unknown-order-token"]
    assert len(compared) == 1
    assert compared[0][0] == "0" * 64
    assert compared[0][1] == real_sha256(b"unknown-order-token").hexdigest()


def test_exact_payment_settles_once_and_opens_exactly_24_hours(
    pending_order: DigitalProductOrder,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    payment_hash = _payload_hash("exact")

    first = settle_verified_payment(
        pending_order.payos_order_code,
        99_000,
        "BANK-REF-1",
        frozen_now,
        payment_hash,
        repo=order_repo,
    )
    second = settle_verified_payment(
        pending_order.payos_order_code,
        99_000,
        "BANK-REF-1",
        frozen_now + timedelta(minutes=5),
        payment_hash,
        repo=order_repo,
    )

    assert first.changed is True
    assert first.reason == "paid"
    assert second.changed is False
    assert second.reason == "duplicate_event"
    assert first.order.paid_at == frozen_now
    assert first.order.download_expires_at == frozen_now + timedelta(hours=24)
    assert second.order.paid_at == first.order.paid_at
    assert second.order.download_expires_at == first.order.download_expires_at
    assert second.order.payment_reference == "BANK-REF-1"


def test_overpayment_is_accepted_without_changing_expected_amount(
    pending_order: DigitalProductOrder,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    result = settle_verified_payment(
        pending_order.payos_order_code,
        100_000,
        "BANK-REF-OVER",
        frozen_now,
        _payload_hash("over"),
        repo=order_repo,
    )

    assert result.changed is True
    assert result.order.status == "paid"
    assert result.order.expected_amount == 99_000
    assert result.order.paid_amount == 100_000


def test_underpayment_moves_to_review_and_never_grants_download(
    pending_order: DigitalProductOrder,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    result = settle_verified_payment(
        pending_order.payos_order_code,
        98_000,
        "BANK-REF-UNDER",
        frozen_now,
        _payload_hash("under"),
        repo=order_repo,
    )

    assert result.changed is True
    assert result.reason == "underpayment"
    assert result.order.status == "payment_review"
    assert result.order.download_expires_at is None
    assert can_download(result.order, frozen_now) is False


def test_paid_replay_with_different_reference_never_mutates_paid_terms(
    pending_order: DigitalProductOrder,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    first = settle_verified_payment(
        pending_order.payos_order_code,
        99_000,
        "BANK-REF-FIRST",
        frozen_now,
        _payload_hash("first"),
        repo=order_repo,
    )

    replay = settle_verified_payment(
        pending_order.payos_order_code,
        120_000,
        "BANK-REF-REPLAY",
        frozen_now + timedelta(hours=1),
        _payload_hash("replay"),
        repo=order_repo,
    )

    assert replay.changed is False
    assert replay.reason == "already_paid"
    assert replay.order.paid_amount == first.order.paid_amount
    assert replay.order.payment_reference == first.order.payment_reference
    assert replay.order.paid_at == first.order.paid_at
    assert replay.order.download_expires_at == first.order.download_expires_at


def test_order_repr_excludes_qr_token_hash_and_bank_reference(
    pending_order: DigitalProductOrder,
    payment_link: FakePaymentLink,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    secret = attach_payment_link(
        pending_order.public_id,
        payment_link,
        repo=order_repo,
    )
    settled = settle_verified_payment(
        pending_order.payos_order_code,
        99_000,
        "BANK-REF-SENSITIVE",
        frozen_now,
        _payload_hash("sensitive"),
        repo=order_repo,
    )

    rendered = repr(settled.order)
    assert secret.order.recovery_token_hash not in rendered
    assert payment_link.qr_payload not in rendered
    assert "BANK-REF-SENSITIVE" not in rendered


def test_sensitive_domain_records_fail_closed_for_flask_and_asdict(
    pending_order: DigitalProductOrder,
    payment_link: FakePaymentLink,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    secret = attach_payment_link(
        pending_order.public_id,
        payment_link,
        repo=order_repo,
    )
    settlement = settle_verified_payment(
        pending_order.payos_order_code,
        99_000,
        "BANK-REF-JSON",
        frozen_now,
        _payload_hash("json"),
        repo=order_repo,
    )
    app = Flask(__name__)

    with app.app_context():
        for domain_record in (secret, settlement.order, settlement):
            with pytest.raises(TypeError):
                app.json.dumps(domain_record)
            with pytest.raises(TypeError):
                jsonify(domain_record)
            with pytest.raises(TypeError):
                asdict(domain_record)


def test_sensitive_domain_records_remain_immutable(
    pending_order: DigitalProductOrder,
    payment_link: FakePaymentLink,
    order_repo: InMemoryOrderRepository,
):
    secret = attach_payment_link(
        pending_order.public_id,
        payment_link,
        repo=order_repo,
    )

    with pytest.raises(AttributeError):
        secret.raw_recovery_token = "replacement"
    with pytest.raises(AttributeError):
        secret.order.status = "paid"


def test_sensitive_concrete_wrappers_have_no_dict_or_shadow_fields(
    pending_order: DigitalProductOrder,
    payment_link: FakePaymentLink,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    secret = attach_payment_link(
        pending_order.public_id,
        payment_link,
        repo=order_repo,
    )
    settlement = settle_verified_payment(
        pending_order.payos_order_code,
        99_000,
        "BANK-REF-SLOTS",
        frozen_now,
        _payload_hash("slots"),
        repo=order_repo,
    )

    for record, field_name, replacement in (
        (settlement.order, "status", "pending"),
        (secret, "raw_recovery_token", "replacement"),
        (settlement, "changed", False),
    ):
        assert type(record).__slots__ == ()
        assert not hasattr(record, "__dict__")
        with pytest.raises(AttributeError):
            getattr(record, "__dict__")
        with pytest.raises(AttributeError):
            setattr(record, field_name, replacement)
        with pytest.raises(AttributeError):
            object.__setattr__(record, field_name, replacement)
    assert DigitalProductOrder.__mro__[1].__slots__ == ("__values",)


def test_shadow_state_cannot_change_download_eligibility(
    pending_order: DigitalProductOrder,
    frozen_now: datetime,
):
    with pytest.raises(AttributeError):
        pending_order.__dict__["status"] = "paid"
    with pytest.raises(AttributeError):
        object.__setattr__(pending_order, "status", "paid")
    with pytest.raises(AttributeError):
        object.__setattr__(
            pending_order,
            "download_expires_at",
            frozen_now + timedelta(days=1),
        )

    assert can_download(pending_order, frozen_now) is False


def test_order_constructor_keeps_legacy_optional_last_download_timestamp(
    frozen_now: datetime,
):
    kwargs = {
        "id": 41,
        "public_id": "a" * 32,
        "product_slug": "thu-dau-mot-map-bundle",
        "product_version": "1.0",
        "expected_amount": 99_000,
        "currency": "VND",
        "payos_order_code": 720_000_041,
        "payment_link_id": None,
        "checkout_url": None,
        "qr_code": None,
        "status": "pending",
        "recovery_token_hash": None,
        "paid_amount": None,
        "payment_reference": None,
        "created_at": frozen_now,
        "payment_expires_at": frozen_now + timedelta(minutes=15),
        "paid_at": None,
        "download_expires_at": None,
        "download_count": 0,
    }

    keyword_order = DigitalProductOrder(**kwargs)
    positional_order = DigitalProductOrder(*kwargs.values())

    assert keyword_order.last_download_at is None
    assert positional_order == keyword_order
    assert positional_order.download_count == 0


def test_order_constructor_does_not_shift_missing_nontrailing_fields(
    frozen_now: datetime,
):
    values_through_download_expiry = (
        41,
        "a" * 32,
        "thu-dau-mot-map-bundle",
        "1.0",
        99_000,
        "VND",
        720_000_041,
        None,
        None,
        None,
        "pending",
        None,
        None,
        None,
        frozen_now,
        frozen_now + timedelta(minutes=15),
        None,
        None,
    )

    with pytest.raises(TypeError):
        DigitalProductOrder(
            *values_through_download_expiry,
            last_download_at=frozen_now,
        )


def test_logging_domain_records_never_renders_sensitive_values(
    caplog: pytest.LogCaptureFixture,
    pending_order: DigitalProductOrder,
    payment_link: FakePaymentLink,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    secret = attach_payment_link(
        pending_order.public_id,
        payment_link,
        repo=order_repo,
    )
    settlement = settle_verified_payment(
        pending_order.payos_order_code,
        99_000,
        "BANK-REF-LOG",
        frozen_now,
        _payload_hash("log"),
        repo=order_repo,
    )

    caplog.set_level("INFO")
    caplog.get_records("call")
    import logging

    logging.getLogger("test.digital-product").info(
        "secret=%r order=%r settlement=%r",
        secret,
        settlement.order,
        settlement,
    )

    for sensitive_value in (
        secret.raw_recovery_token,
        secret.order.recovery_token_hash,
        payment_link.qr_payload,
        payment_link.payment_link_id,
        payment_link.checkout_url,
        "BANK-REF-LOG",
        str(pending_order.payos_order_code),
    ):
        assert sensitive_value not in caplog.text


def test_duplicate_settlement_calls_are_serialized_to_one_state_change(
    pending_order: DigitalProductOrder,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    barrier = threading.Barrier(2)

    def settle():
        barrier.wait()
        return settle_verified_payment(
            pending_order.payos_order_code,
            99_000,
            "BANK-REF-RACE",
            frozen_now,
            _payload_hash("race"),
            repo=order_repo,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: settle(), range(2)))

    assert sorted(result.changed for result in results) == [False, True]
    assert {result.order.download_expires_at for result in results} == {
        frozen_now + timedelta(hours=24)
    }
    assert order_repo.events == {
        (pending_order.id, "payment_verified", "BANK-REF-RACE")
    }


def test_settlement_missing_order_raises_typed_error(
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    with pytest.raises(SettlementNotFound) as caught:
        settle_verified_payment(
            720_999_999,
            99_000,
            "BANK-REF-MISSING",
            frozen_now,
            _payload_hash("missing"),
            repo=order_repo,
        )

    assert caught.value.order_code == 720_999_999


def test_settlement_rejects_non_hash_payload_without_persisting_it(
    pending_order: DigitalProductOrder,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    raw_payload = '{"signature":"secret"}'

    with pytest.raises(InvalidSettlement):
        settle_verified_payment(
            pending_order.payos_order_code,
            99_000,
            "BANK-REF-RAW",
            frozen_now,
            raw_payload,
            repo=order_repo,
        )

    assert raw_payload not in order_repo.serialized_rows()
    assert order_repo.event_payload_hashes == []


@pytest.mark.parametrize(
    ("status", "seconds_after_expiry", "allowed"),
    [
        ("pending", -1, False),
        ("paid", -1, True),
        ("paid", 0, False),
        ("paid", 1, False),
        ("payment_review", -1, False),
    ],
)
def test_can_download_requires_paid_and_strictly_unexpired(
    status: str,
    seconds_after_expiry: int,
    allowed: bool,
    product: DigitalProduct,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    order = create_pending_order(product, frozen_now, repo=order_repo)
    expiry = frozen_now + timedelta(hours=24)
    order_repo.orders[order.id] = order.with_updates(
        status=status,
        paid_at=frozen_now if status == "paid" else None,
        download_expires_at=expiry,
    )

    assert can_download(
        order_repo.orders[order.id],
        expiry + timedelta(seconds=seconds_after_expiry),
    ) is allowed


def test_expiry_changes_only_pending_orders_at_or_after_deadline(
    product: DigitalProduct,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    pending = create_pending_order(product, frozen_now, repo=order_repo)

    before = expire_pending_order(
        pending.public_id,
        pending.payment_expires_at - timedelta(microseconds=1),
        repo=order_repo,
    )
    expired = expire_pending_order(
        pending.public_id,
        pending.payment_expires_at,
        repo=order_repo,
    )
    paid = expired.with_updates(
        status="paid",
        paid_at=frozen_now,
        download_expires_at=frozen_now + timedelta(hours=24),
    )
    order_repo.orders[paid.id] = paid
    still_paid = expire_pending_order(
        paid.public_id,
        paid.payment_expires_at + timedelta(days=1),
        repo=order_repo,
    )

    assert before.status == "pending"
    assert expired.status == "expired"
    assert still_paid == paid


def test_record_download_atomically_counts_and_timestamps(
    pending_order: DigitalProductOrder,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    times = [frozen_now + timedelta(seconds=offset) for offset in range(20)]

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(
            pool.map(
                lambda downloaded_at: record_download(
                    pending_order.id,
                    downloaded_at,
                    repo=order_repo,
                ),
                times,
            )
        )

    order = get_order(pending_order.public_id, repo=order_repo)
    assert order is not None
    assert order.download_count == 20
    assert order.last_download_at in times


def test_out_of_order_download_commits_never_move_timestamp_backward(
    pending_order: DigitalProductOrder,
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    newer = frozen_now + timedelta(minutes=5)
    older = frozen_now + timedelta(minutes=1)
    newer_committed = threading.Event()

    def commit_newer():
        record_download(pending_order.id, newer, repo=order_repo)
        newer_committed.set()

    def commit_older_after_newer():
        assert newer_committed.wait(timeout=2)
        record_download(pending_order.id, older, repo=order_repo)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(commit_newer),
            pool.submit(commit_older_after_newer),
        ]
        for future in futures:
            future.result()

    order = get_order(pending_order.public_id, repo=order_repo)
    assert order is not None
    assert order.download_count == 2
    assert order.last_download_at == newer


def test_record_download_missing_order_raises_typed_error(
    frozen_now: datetime,
    order_repo: InMemoryOrderRepository,
):
    with pytest.raises(OrderNotFound):
        record_download(404, frozen_now, repo=order_repo)


class _ContractCursor:
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        lastrowid: int | None = None,
        rowcount: int = 1,
    ):
        self._row = row
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        return self._row


class _ContractConnection:
    def __init__(self):
        self.statements: list[tuple[str, tuple[object, ...]]] = []
        self.order_row: dict[str, object] | None = None
        self.next_id = 17
        self.event_inserted = False

    def execute(self, sql: str, params: tuple[object, ...] = ()):
        normalized = " ".join(sql.split())
        bound = tuple(params or ())
        self.statements.append((normalized, bound))
        if normalized.startswith("WITH generated_order AS"):
            (
                public_id,
                product_slug,
                product_version,
                expected_amount,
                currency,
                code_base,
                created_at,
                _updated_at,
                payment_expires_at,
                _max_order_id,
            ) = bound
            self.order_row = {
                "id": self.next_id,
                "public_id": public_id,
                "product_slug": product_slug,
                "product_version": product_version,
                "expected_amount": expected_amount,
                "currency": currency,
                "payos_order_code": code_base + self.next_id,
                "payment_link_id": None,
                "checkout_url": None,
                "qr_code": None,
                "status": "pending",
                "recovery_token_hash": None,
                "paid_amount": None,
                "payment_reference": None,
                "created_at": created_at,
                "payment_expires_at": payment_expires_at,
                "paid_at": None,
                "download_expires_at": None,
                "download_count": 0,
                "last_download_at": None,
            }
            return _ContractCursor(lastrowid=self.next_id)
        if normalized.startswith("INSERT INTO digital_product_order_events"):
            if self.event_inserted:
                return _ContractCursor(lastrowid=None, rowcount=0)
            self.event_inserted = True
            return _ContractCursor(lastrowid=1)
        if normalized.startswith("UPDATE digital_product_orders SET status = 'paid'"):
            assert self.order_row is not None
            amount, reference, paid_at, download_expires_at, _order_id = bound
            self.order_row.update(
                status="paid",
                paid_amount=amount,
                payment_reference=reference,
                paid_at=paid_at,
                download_expires_at=download_expires_at,
            )
            return _ContractCursor()
        if normalized.startswith(
            "UPDATE digital_product_orders SET download_count = download_count + 1"
        ):
            assert self.order_row is not None
            first_timestamp, second_timestamp, _order_id = bound
            assert first_timestamp == second_timestamp
            current_timestamp = self.order_row["last_download_at"]
            self.order_row["download_count"] += 1
            self.order_row["last_download_at"] = (
                first_timestamp
                if current_timestamp is None
                else max(current_timestamp, first_timestamp)
            )
            return _ContractCursor()
        if normalized.startswith("SELECT"):
            return _ContractCursor(row=self.order_row)
        raise AssertionError(f"unexpected SQL: {normalized}")


def test_postgres_repository_derives_order_code_from_inserted_id_atomically(
    product: DigitalProduct,
    frozen_now: datetime,
):
    conn = _ContractConnection()

    @contextmanager
    def connection_scope():
        yield conn

    repo = PostgresOrderRepository(connection_scope)
    order = create_pending_order(product, frozen_now, repo=repo)

    insert_sql, params = conn.statements[0]
    assert "nextval(" in insert_sql
    assert "? + id" in insert_sql
    assert "WHERE id <= ?" in insert_sql
    assert "RETURNING id" in insert_sql
    assert order.id == conn.next_id
    assert order.payos_order_code == 720_000_000 + conn.next_id
    assert params[5] == 720_000_000
    assert params[-1] == MAX_ORDER_ID
    assert order.public_id not in insert_sql


def test_postgres_settlement_locks_order_and_uses_unique_event_seam(
    product: DigitalProduct,
    frozen_now: datetime,
):
    conn = _ContractConnection()

    @contextmanager
    def connection_scope():
        yield conn

    repo = PostgresOrderRepository(connection_scope)
    pending = create_pending_order(product, frozen_now, repo=repo)
    result = settle_verified_payment(
        pending.payos_order_code,
        99_000,
        "BANK-REF-CONTRACT",
        frozen_now,
        _payload_hash("contract"),
        repo=repo,
    )

    lock_sql, lock_params = next(
        (sql, params)
        for sql, params in conn.statements
        if "WHERE payos_order_code = ?" in sql
    )
    event_sql, event_params = next(
        (sql, params)
        for sql, params in conn.statements
        if sql.startswith("INSERT INTO digital_product_order_events")
    )
    assert lock_sql.endswith("FOR UPDATE")
    assert lock_params == (pending.payos_order_code,)
    assert (
        "ON CONFLICT (order_id, event_type, external_reference) DO NOTHING"
        in event_sql
    )
    assert event_params[3] == _payload_hash("contract")
    assert "contract" not in event_sql
    assert result.order.status == "paid"


def test_postgres_download_update_keeps_count_atomic_and_timestamp_monotonic(
    product: DigitalProduct,
    frozen_now: datetime,
):
    conn = _ContractConnection()

    @contextmanager
    def connection_scope():
        yield conn

    repo = PostgresOrderRepository(connection_scope)
    pending = create_pending_order(product, frozen_now, repo=repo)
    newer = frozen_now + timedelta(minutes=5)
    older = frozen_now + timedelta(minutes=1)

    record_download(pending.id, newer, repo=repo)
    record_download(pending.id, older, repo=repo)

    order = get_order(pending.public_id, repo=repo)
    assert order is not None
    assert order.download_count == 2
    assert order.last_download_at == newer
    download_updates = [
        (sql, params)
        for sql, params in conn.statements
        if "SET download_count = download_count + 1" in sql
    ]
    assert len(download_updates) == 2
    assert all(
        "last_download_at = CASE" in sql
        and "last_download_at < ?" in sql
        and params[0] == params[1]
        for sql, params in download_updates
    )
