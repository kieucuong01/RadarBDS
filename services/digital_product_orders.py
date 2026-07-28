"""Digital-product order lifecycle with short, atomic PostgreSQL transactions."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Callable, ContextManager, Iterator, Protocol

from db.connection import get_conn
from services.digital_products import DigitalProduct, get_digital_product


ORDER_CODE_BASE = 720_000_000
MAX_PAYOS_ORDER_CODE = 2_147_483_647
MAX_ORDER_ID = MAX_PAYOS_ORDER_CODE - ORDER_CODE_BASE
PAYMENT_WINDOW = timedelta(minutes=15)
DOWNLOAD_WINDOW = timedelta(hours=24)
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_PUBLIC_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

_ORDER_COLUMNS = """
id, public_id, product_slug, product_version, expected_amount, currency,
payos_order_code, payment_link_id, checkout_url, qr_code, status,
recovery_token_hash, paid_amount, payment_reference, created_at,
payment_expires_at, paid_at, download_expires_at, download_count,
last_download_at
""".strip()


class OrderLifecycleError(RuntimeError):
    """Base class for typed order-lifecycle failures."""


class OrderNotFound(OrderLifecycleError):
    def __init__(self, identifier: object):
        self.identifier = identifier
        super().__init__("digital product order not found")


class SettlementNotFound(OrderLifecycleError):
    def __init__(self, order_code: int):
        self.order_code = order_code
        super().__init__("settlement order not found")


class OrderCodeRangeError(OrderLifecycleError):
    def __init__(self, order_id: int):
        self.order_id = order_id
        super().__init__("PayOS order-code range exhausted")


class OrderStateError(OrderLifecycleError):
    def __init__(self, status: str):
        self.status = status
        super().__init__("order state does not allow this operation")


class InvalidSettlement(OrderLifecycleError):
    """Raised before persistence when verified payment data is malformed."""


class _ImmutableDomainRecord:
    """Immutable attribute record that generic JSON/dataclass encoders reject."""

    __slots__ = ("__values",)
    _field_names: tuple[str, ...] = ()
    _repr_field_names: tuple[str, ...] = ()
    _field_defaults: dict[str, object] = {}

    def __init__(self, *args: object, **kwargs: object):
        if len(args) > len(self._field_names):
            raise TypeError("too many positional values")
        values = dict(zip(self._field_names, args))
        duplicates = set(values).intersection(kwargs)
        if duplicates:
            raise TypeError("duplicate domain-record values")
        values.update(kwargs)
        extras = set(values).difference(self._field_names)
        if extras:
            raise TypeError("domain-record fields do not match the contract")
        for field_name, default in self._field_defaults.items():
            values.setdefault(field_name, default)
        missing = set(self._field_names).difference(values)
        if missing or extras:
            raise TypeError("domain-record fields do not match the contract")
        object.__setattr__(
            self,
            "_ImmutableDomainRecord__values",
            MappingProxyType(values),
        )

    def __getattr__(self, name: str) -> object:
        values = object.__getattribute__(
            self,
            "_ImmutableDomainRecord__values",
        )
        try:
            return values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("immutable domain record")

    def __delattr__(self, name: str) -> None:
        del name
        raise AttributeError("immutable domain record")

    def __repr__(self) -> str:
        values = object.__getattribute__(
            self,
            "_ImmutableDomainRecord__values",
        )
        fields = ", ".join(
            f"{name}={values[name]!r}" for name in self._repr_field_names
        )
        return f"{type(self).__name__}({fields})"

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return False
        own_values = object.__getattribute__(
            self,
            "_ImmutableDomainRecord__values",
        )
        other_values = object.__getattribute__(
            other,
            "_ImmutableDomainRecord__values",
        )
        return dict(own_values) == dict(other_values)

    def with_updates(self, **changes: object):
        values = dict(
            object.__getattribute__(
                self,
                "_ImmutableDomainRecord__values",
            )
        )
        extras = set(changes).difference(self._field_names)
        if extras:
            raise TypeError("unknown domain-record fields")
        values.update(changes)
        return type(self)(**values)


class DigitalProductOrder(_ImmutableDomainRecord):
    """Sensitive order domain record; routes must map explicit safe fields."""

    __slots__ = ()
    _field_names = (
        "id",
        "public_id",
        "product_slug",
        "product_version",
        "expected_amount",
        "currency",
        "payos_order_code",
        "payment_link_id",
        "checkout_url",
        "qr_code",
        "status",
        "recovery_token_hash",
        "paid_amount",
        "payment_reference",
        "created_at",
        "payment_expires_at",
        "paid_at",
        "download_expires_at",
        "download_count",
        "last_download_at",
    )
    _field_defaults = {"last_download_at": None}
    _repr_field_names = (
        "public_id",
        "product_slug",
        "product_version",
        "expected_amount",
        "currency",
        "status",
        "paid_amount",
        "created_at",
        "payment_expires_at",
        "paid_at",
        "download_expires_at",
        "download_count",
        "last_download_at",
    )

    id: int
    public_id: str
    product_slug: str
    product_version: str
    expected_amount: int
    currency: str
    payos_order_code: int
    payment_link_id: str | None
    checkout_url: str | None
    qr_code: str | None
    status: str
    recovery_token_hash: str | None
    paid_amount: int | None
    payment_reference: str | None
    created_at: datetime
    payment_expires_at: datetime
    paid_at: datetime | None
    download_expires_at: datetime | None
    download_count: int
    last_download_at: datetime | None


class PendingOrderSecret(_ImmutableDomainRecord):
    __slots__ = ()
    _field_names = ("order", "raw_recovery_token")
    _repr_field_names = ("order",)

    order: DigitalProductOrder
    raw_recovery_token: str


class SettlementResult(_ImmutableDomainRecord):
    __slots__ = ()
    _field_names = ("order", "changed", "reason")
    _repr_field_names = ("order", "changed", "reason")

    order: DigitalProductOrder
    changed: bool
    reason: str


class PaymentLinkLike(Protocol):
    payment_link_id: str
    checkout_url: str
    qr_payload: str


class OrderTransaction(Protocol):
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
    ) -> DigitalProductOrder: ...

    def get_by_public_id(
        self,
        public_id: str,
        *,
        for_update: bool = False,
    ) -> DigitalProductOrder | None: ...

    def get_by_order_code(
        self,
        order_code: int,
        *,
        for_update: bool = False,
    ) -> DigitalProductOrder | None: ...

    def attach_payment_link(
        self,
        order_id: int,
        *,
        payment_link_id: str,
        checkout_url: str,
        qr_code: str,
        recovery_token_hash: str,
    ) -> DigitalProductOrder: ...

    def insert_event_if_absent(
        self,
        *,
        order_id: int,
        event_type: str,
        external_reference: str,
        payload_hash: str,
        created_at: datetime,
    ) -> bool: ...

    def mark_payment_review(
        self,
        order_id: int,
        *,
        amount: int,
        reference: str,
    ) -> DigitalProductOrder: ...

    def mark_paid(
        self,
        order_id: int,
        *,
        amount: int,
        reference: str,
        paid_at: datetime,
        download_expires_at: datetime,
    ) -> DigitalProductOrder: ...

    def mark_expired(self, order_id: int) -> DigitalProductOrder: ...

    def increment_download(self, order_id: int, *, downloaded_at: datetime) -> bool: ...


class OrderRepository(Protocol):
    def transaction(self) -> ContextManager[OrderTransaction]: ...


ConnectionScope = Callable[[], ContextManager[object]]


class PostgresOrderRepository:
    """Production repository using the shared PostgreSQL connection scope."""

    def __init__(self, connection_scope: ConnectionScope = get_conn):
        self._connection_scope = connection_scope

    @contextmanager
    def transaction(self) -> Iterator[OrderTransaction]:
        with self._connection_scope() as conn:
            yield _PostgresOrderTransaction(conn)


class _PostgresOrderTransaction:
    def __init__(self, conn: object):
        self._conn = conn

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
        cursor = self._conn.execute(
            """
            WITH generated_order AS (
                SELECT nextval(
                    pg_get_serial_sequence('digital_product_orders', 'id')
                )::BIGINT AS id
            )
            INSERT INTO digital_product_orders (
                id, public_id, product_slug, product_version, expected_amount,
                currency, payos_order_code, status, recovery_token_hash,
                created_at, updated_at, payment_expires_at, download_count
            )
            SELECT
                id, ?, ?, ?, ?, ?, ? + id, 'pending', NULL, ?, ?, ?, 0
            FROM generated_order
            WHERE id <= ?
            RETURNING id
            """,
            (
                public_id,
                product_slug,
                product_version,
                expected_amount,
                currency,
                ORDER_CODE_BASE,
                created_at,
                created_at,
                payment_expires_at,
                MAX_ORDER_ID,
            ),
        )
        order_id = cursor.lastrowid
        if order_id is None:
            raise OrderCodeRangeError(MAX_ORDER_ID + 1)
        order = self._get_by_id(int(order_id))
        if order is None:  # pragma: no cover - same-transaction invariant
            raise OrderNotFound(order_id)
        return order

    def get_by_public_id(
        self,
        public_id: str,
        *,
        for_update: bool = False,
    ) -> DigitalProductOrder | None:
        lock = " FOR UPDATE" if for_update else ""
        row = self._conn.execute(
            f"""
            SELECT {_ORDER_COLUMNS}
            FROM digital_product_orders
            WHERE public_id = ?{lock}
            """,
            (public_id,),
        ).fetchone()
        return _order_from_row(row)

    def get_by_order_code(
        self,
        order_code: int,
        *,
        for_update: bool = False,
    ) -> DigitalProductOrder | None:
        lock = " FOR UPDATE" if for_update else ""
        row = self._conn.execute(
            f"""
            SELECT {_ORDER_COLUMNS}
            FROM digital_product_orders
            WHERE payos_order_code = ?{lock}
            """,
            (order_code,),
        ).fetchone()
        return _order_from_row(row)

    def attach_payment_link(
        self,
        order_id: int,
        *,
        payment_link_id: str,
        checkout_url: str,
        qr_code: str,
        recovery_token_hash: str,
    ) -> DigitalProductOrder:
        self._conn.execute(
            """
            UPDATE digital_product_orders
               SET payment_link_id = ?,
                   checkout_url = ?,
                   qr_code = ?,
                   recovery_token_hash = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (
                payment_link_id,
                checkout_url,
                qr_code,
                recovery_token_hash,
                order_id,
            ),
        )
        return self._required_by_id(order_id)

    def insert_event_if_absent(
        self,
        *,
        order_id: int,
        event_type: str,
        external_reference: str,
        payload_hash: str,
        created_at: datetime,
    ) -> bool:
        cursor = self._conn.execute(
            """
            INSERT INTO digital_product_order_events (
                order_id, event_type, external_reference, payload_hash, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (order_id, event_type, external_reference) DO NOTHING
            RETURNING id
            """,
            (
                order_id,
                event_type,
                external_reference,
                payload_hash,
                created_at,
            ),
        )
        return cursor.lastrowid is not None

    def mark_payment_review(
        self,
        order_id: int,
        *,
        amount: int,
        reference: str,
    ) -> DigitalProductOrder:
        self._conn.execute(
            """
            UPDATE digital_product_orders
               SET status = 'payment_review',
                   status_reason = 'underpayment',
                   paid_amount = ?,
                   payment_reference = ?,
                   paid_at = NULL,
                   download_expires_at = NULL,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (amount, reference, order_id),
        )
        return self._required_by_id(order_id)

    def mark_paid(
        self,
        order_id: int,
        *,
        amount: int,
        reference: str,
        paid_at: datetime,
        download_expires_at: datetime,
    ) -> DigitalProductOrder:
        self._conn.execute(
            """
            UPDATE digital_product_orders
               SET status = 'paid',
                   status_reason = NULL,
                   paid_amount = ?,
                   payment_reference = ?,
                   paid_at = ?,
                   download_expires_at = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
               AND status <> 'paid'
            """,
            (amount, reference, paid_at, download_expires_at, order_id),
        )
        return self._required_by_id(order_id)

    def mark_expired(self, order_id: int) -> DigitalProductOrder:
        self._conn.execute(
            """
            UPDATE digital_product_orders
               SET status = 'expired',
                   status_reason = 'payment_link_expired',
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
               AND status = 'pending'
            """,
            (order_id,),
        )
        return self._required_by_id(order_id)

    def increment_download(self, order_id: int, *, downloaded_at: datetime) -> bool:
        cursor = self._conn.execute(
            """
            UPDATE digital_product_orders
               SET download_count = download_count + 1,
                   last_download_at = CASE
                       WHEN last_download_at IS NULL OR last_download_at < ?
                       THEN ?
                       ELSE last_download_at
                   END,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (downloaded_at, downloaded_at, order_id),
        )
        return cursor.rowcount == 1

    def _get_by_id(self, order_id: int) -> DigitalProductOrder | None:
        row = self._conn.execute(
            f"""
            SELECT {_ORDER_COLUMNS}
            FROM digital_product_orders
            WHERE id = ?
            """,
            (order_id,),
        ).fetchone()
        return _order_from_row(row)

    def _required_by_id(self, order_id: int) -> DigitalProductOrder:
        order = self._get_by_id(order_id)
        if order is None:  # pragma: no cover - locked order disappeared
            raise OrderNotFound(order_id)
        return order


def create_pending_order(
    product: DigitalProduct,
    now: datetime,
    *,
    public_id: str | None = None,
    repo: OrderRepository | None = None,
) -> DigitalProductOrder:
    """Create one pending order from the trusted server-side registry."""
    trusted_product = get_digital_product(product.slug)
    if public_id is None:
        normalized_public_id = uuid.uuid4().hex
    elif (
        type(public_id) is str
        and _PUBLIC_ID_PATTERN.fullmatch(public_id) is not None
    ):
        normalized_public_id = public_id
    else:
        raise OrderLifecycleError("invalid controller public id")
    repository = _repository(repo)
    with repository.transaction() as tx:
        return tx.insert_pending(
            public_id=normalized_public_id,
            product_slug=trusted_product.slug,
            product_version=trusted_product.version,
            expected_amount=trusted_product.price_vnd,
            currency="VND",
            created_at=now,
            payment_expires_at=now + PAYMENT_WINDOW,
        )


def attach_payment_link(
    public_id: str,
    payment_link: PaymentLinkLike,
    *,
    repo: OrderRepository | None = None,
) -> PendingOrderSecret:
    """Attach PayOS output and rotate the one-time recovery-token secret."""
    repository = _repository(repo)
    with repository.transaction() as tx:
        order = tx.get_by_public_id(public_id, for_update=True)
        if order is None:
            raise OrderNotFound(public_id)
        if order.status != "pending":
            raise OrderStateError(order.status)

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        stored = tx.attach_payment_link(
            order.id,
            payment_link_id=order.payment_link_id or str(payment_link.payment_link_id),
            checkout_url=order.checkout_url or str(payment_link.checkout_url),
            qr_code=order.qr_code or str(payment_link.qr_payload),
            recovery_token_hash=token_hash,
        )
        return PendingOrderSecret(order=stored, raw_recovery_token=raw_token)


def verify_recovery_token(
    public_id: str,
    raw_token: str,
    *,
    now: datetime | None = None,
    repo: OrderRepository | None = None,
) -> DigitalProductOrder | None:
    repository = _repository(repo)
    with repository.transaction() as tx:
        order = tx.get_by_public_id(public_id)

    candidate_hash = hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()
    expected_hash = (
        order.recovery_token_hash
        if order is not None and order.recovery_token_hash is not None
        else ("0" * 64)
    )
    matches = hmac.compare_digest(expected_hash, candidate_hash)
    if (
        order is None
        or order.recovery_token_hash is None
        or not matches
    ):
        return None
    verification_time = now or datetime.now(timezone.utc)
    if not _recovery_authorization_active(order, verification_time):
        return None
    return order


def get_order(
    public_id: str,
    *,
    repo: OrderRepository | None = None,
) -> DigitalProductOrder | None:
    repository = _repository(repo)
    with repository.transaction() as tx:
        return tx.get_by_public_id(public_id)


def settle_verified_payment(
    order_code: int,
    amount: int,
    reference: str,
    paid_at: datetime,
    payload_hash: str,
    *,
    repo: OrderRepository | None = None,
) -> SettlementResult:
    """Apply one already-verified payment event under a row lock."""
    _validate_settlement(order_code, amount, reference, paid_at, payload_hash)
    normalized_reference = reference.strip()
    normalized_hash = payload_hash.lower()
    repository = _repository(repo)

    with repository.transaction() as tx:
        order = tx.get_by_order_code(order_code, for_update=True)
        if order is None:
            raise SettlementNotFound(order_code)

        event_type = (
            "payment_verified"
            if amount >= order.expected_amount
            else "payment_underpaid"
        )
        inserted = tx.insert_event_if_absent(
            order_id=order.id,
            event_type=event_type,
            external_reference=normalized_reference,
            payload_hash=normalized_hash,
            created_at=paid_at,
        )
        if not inserted:
            return SettlementResult(
                order=order,
                changed=False,
                reason="duplicate_event",
            )

        if order.status == "paid":
            return SettlementResult(
                order=order,
                changed=False,
                reason="already_paid",
            )
        if amount < order.expected_amount:
            reviewed = tx.mark_payment_review(
                order.id,
                amount=amount,
                reference=normalized_reference,
            )
            return SettlementResult(
                order=reviewed,
                changed=True,
                reason="underpayment",
            )

        paid = tx.mark_paid(
            order.id,
            amount=amount,
            reference=normalized_reference,
            paid_at=paid_at,
            download_expires_at=paid_at + DOWNLOAD_WINDOW,
        )
        return SettlementResult(order=paid, changed=True, reason="paid")


def expire_pending_order(
    public_id: str,
    now: datetime,
    *,
    repo: OrderRepository | None = None,
) -> DigitalProductOrder:
    repository = _repository(repo)
    with repository.transaction() as tx:
        order = tx.get_by_public_id(public_id, for_update=True)
        if order is None:
            raise OrderNotFound(public_id)
        if order.status == "pending" and now >= order.payment_expires_at:
            return tx.mark_expired(order.id)
        return order


def can_download(order: DigitalProductOrder, now: datetime) -> bool:
    return bool(
        order.status == "paid"
        and order.download_expires_at is not None
        and now < order.download_expires_at
    )


def record_download(
    order_id: int,
    now: datetime,
    *,
    repo: OrderRepository | None = None,
) -> None:
    repository = _repository(repo)
    with repository.transaction() as tx:
        if not tx.increment_download(order_id, downloaded_at=now):
            raise OrderNotFound(order_id)


def _validate_settlement(
    order_code: int,
    amount: int,
    reference: str,
    paid_at: datetime,
    payload_hash: str,
) -> None:
    if isinstance(order_code, bool) or not isinstance(order_code, int):
        raise InvalidSettlement("invalid order code")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise InvalidSettlement("invalid amount")
    if not isinstance(reference, str) or not reference.strip():
        raise InvalidSettlement("missing payment reference")
    if not isinstance(paid_at, datetime):
        raise InvalidSettlement("invalid paid timestamp")
    if (
        not isinstance(payload_hash, str)
        or _SHA256_PATTERN.fullmatch(payload_hash) is None
    ):
        raise InvalidSettlement("payload must be represented by a SHA-256 hash")


def _repository(repo: OrderRepository | None) -> OrderRepository:
    return repo if repo is not None else PostgresOrderRepository()


def _recovery_authorization_active(
    order: DigitalProductOrder,
    now: datetime,
) -> bool:
    if order.status == "paid":
        expires_at = order.download_expires_at
    elif order.status in {"pending", "payment_review"}:
        expires_at = order.payment_expires_at
    else:
        return False
    return expires_at is not None and now < expires_at


def _order_from_row(row: object | None) -> DigitalProductOrder | None:
    if row is None:
        return None
    return DigitalProductOrder(
        id=int(row["id"]),
        public_id=str(row["public_id"]),
        product_slug=str(row["product_slug"]),
        product_version=str(row["product_version"]),
        expected_amount=int(row["expected_amount"]),
        currency=str(row["currency"]),
        payos_order_code=int(row["payos_order_code"]),
        payment_link_id=row["payment_link_id"],
        checkout_url=row["checkout_url"],
        qr_code=row["qr_code"],
        status=str(row["status"]),
        recovery_token_hash=row["recovery_token_hash"],
        paid_amount=(
            int(row["paid_amount"]) if row["paid_amount"] is not None else None
        ),
        payment_reference=row["payment_reference"],
        created_at=row["created_at"],
        payment_expires_at=row["payment_expires_at"],
        paid_at=row["paid_at"],
        download_expires_at=row["download_expires_at"],
        download_count=int(row["download_count"]),
        last_download_at=row["last_download_at"],
    )
