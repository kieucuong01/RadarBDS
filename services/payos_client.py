"""Narrow PayOS SDK adapter for the anonymous digital-product checkout."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit

from payos import PayOS as _PayOSSDK
from payos.types import CreatePaymentLinkRequest

from config.settings import get_digital_product_commerce_settings
from services.digital_product_orders import (
    DigitalProductOrder,
    MAX_PAYOS_ORDER_CODE,
    ORDER_CODE_BASE,
)


_BASE36_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_PAYOS_TIMEZONE = timezone(timedelta(hours=7))
_MISSING = object()
_PUBLIC_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_PAYMENT_DATETIME_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$"
)
_MAX_VND_AMOUNT = 9_223_372_036_854_775_807
_MAX_URL_LENGTH = 2_048
_MAX_QR_PAYLOAD_LENGTH = 4_096
_MAX_WEBHOOK_BODY_LENGTH = 64 * 1_024
_SDK_TIMEOUT_SECONDS = 10.0
_SDK_MAX_RETRIES = 1


class _ImmutablePaymentRecord:
    __slots__ = ("__values",)
    _field_names: tuple[str, ...] = ()
    _repr_field_names: tuple[str, ...] = ()

    def __init__(self, **values: object):
        if set(values) != set(self._field_names):
            raise TypeError("payment record fields do not match the contract")
        object.__setattr__(
            self,
            "_ImmutablePaymentRecord__values",
            MappingProxyType(dict(values)),
        )

    def __getattr__(self, name: str) -> object:
        values = object.__getattribute__(
            self,
            "_ImmutablePaymentRecord__values",
        )
        try:
            return values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("immutable payment record")

    def __delattr__(self, name: str) -> None:
        del name
        raise AttributeError("immutable payment record")

    def __repr__(self) -> str:
        values = object.__getattribute__(
            self,
            "_ImmutablePaymentRecord__values",
        )
        fields = ", ".join(
            f"{name}={values[name]!r}" for name in self._repr_field_names
        )
        return f"{type(self).__name__}({fields})"


class PayOSPaymentLink(_ImmutablePaymentRecord):
    __slots__ = ()
    _field_names = ("payment_link_id", "checkout_url", "qr_payload")

    payment_link_id: str
    checkout_url: str
    qr_payload: str


class VerifiedPayOSPayment(_ImmutablePaymentRecord):
    __slots__ = ()
    _field_names = (
        "order_code",
        "amount",
        "reference",
        "paid_at",
        "success",
        "payload_hash",
    )
    _repr_field_names = ("amount", "paid_at", "success", "payload_hash")

    order_code: int
    amount: int
    reference: str
    paid_at: datetime
    success: bool
    payload_hash: str


class PayOSClientError(RuntimeError):
    """Base type for deliberately non-leaking PayOS adapter failures."""


class PayOSConfigurationError(PayOSClientError):
    def __init__(self) -> None:
        super().__init__("PayOS client configuration failed")


class PayOSPaymentLinkCreationError(PayOSClientError):
    def __init__(self) -> None:
        super().__init__("PayOS payment link creation failed")


class PayOSWebhookRejected(PayOSClientError):
    def __init__(self) -> None:
        super().__init__("PayOS webhook rejected")


class PayOSPaymentStatus(_ImmutablePaymentRecord):
    __slots__ = ()
    _field_names = (
        "order_code",
        "status",
        "amount_paid",
        "reference",
        "paid_at",
    )
    _repr_field_names = ("status", "amount_paid", "paid_at")

    order_code: int
    status: Literal["PENDING", "PAID", "CANCELLED", "EXPIRED", "UNKNOWN"]
    amount_paid: int
    reference: str
    paid_at: datetime | None


class PayOSPaymentLookupError(PayOSClientError):
    def __init__(self) -> None:
        super().__init__("PayOS payment lookup failed")


class PayOSClient:
    def __init__(self, sdk: object | None = None):
        self._sdk = sdk if sdk is not None else _create_sdk()

    def create_payment_link(
        self,
        order: DigitalProductOrder,
        return_url: str,
        cancel_url: str,
    ) -> PayOSPaymentLink:
        try:
            _validate_pending_order(order)
            _validate_order_url(return_url, order.public_id)
            _validate_order_url(cancel_url, order.public_id)
            if return_url != cancel_url:
                raise PayOSPaymentLinkCreationError()

            expires_at = _normalize_server_datetime(order.payment_expires_at)
            if expires_at is None:
                raise PayOSPaymentLinkCreationError()
            payment_data = CreatePaymentLinkRequest(
                order_code=order.payos_order_code,
                amount=order.expected_amount,
                description=_payment_description(order.payos_order_code),
                cancel_url=cancel_url,
                return_url=return_url,
                expired_at=int(expires_at.timestamp()),
            )
            response = self._sdk.payment_requests.create(
                payment_data=payment_data,
            )
            response_order_code = _field(
                response,
                "order_code",
                "orderCode",
            )
            response_amount = _field(response, "amount")
            payment_link_id = _field(
                response,
                "payment_link_id",
                "paymentLinkId",
            )
            checkout_url = _field(
                response,
                "checkout_url",
                "checkoutUrl",
            )
            qr_payload = _field(response, "qr_code", "qrCode")
            if (
                not _valid_order_code(response_order_code)
                or response_order_code != order.payos_order_code
                or not _valid_positive_int(response_amount)
                or response_amount != order.expected_amount
                or not _valid_safe_string(payment_link_id, maximum=128)
                or not _valid_checkout_url(checkout_url)
                or not _valid_safe_string(
                    qr_payload,
                    maximum=_MAX_QR_PAYLOAD_LENGTH,
                )
            ):
                raise PayOSPaymentLinkCreationError()
            return PayOSPaymentLink(
                payment_link_id=payment_link_id.strip(),
                checkout_url=checkout_url,
                qr_payload=qr_payload,
            )
        except PayOSPaymentLinkCreationError:
            raise
        except Exception:
            raise PayOSPaymentLinkCreationError() from None

    def verify_webhook(self, raw_body: bytes) -> VerifiedPayOSPayment:
        if (
            type(raw_body) is not bytes
            or not raw_body
            or len(raw_body) > _MAX_WEBHOOK_BODY_LENGTH
        ):
            raise PayOSWebhookRejected()
        payload_hash = hashlib.sha256(raw_body).hexdigest()
        try:
            verified = self._sdk.webhooks.verify(raw_body)
        except Exception:
            raise PayOSWebhookRejected() from None

        try:
            payload = json.loads(raw_body)
        except Exception:
            raise PayOSWebhookRejected() from None
        if (
            not isinstance(payload, dict)
            or payload.get("success") is not True
            or payload.get("code") != "00"
            or not _valid_safe_string(
                payload.get("signature"),
                maximum=512,
            )
        ):
            raise PayOSWebhookRejected()
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("code") != "00":
            raise PayOSWebhookRejected()

        order_code = data.get("orderCode", _MISSING)
        amount = data.get("amount", _MISSING)
        reference = data.get("reference", _MISSING)
        paid_at_value = data.get("transactionDateTime", _MISSING)
        if (
            not _valid_order_code(order_code)
            or not _valid_positive_int(amount)
            or not _valid_reference(reference)
        ):
            raise PayOSWebhookRejected()
        paid_at = _parse_payment_datetime(paid_at_value)
        if paid_at is None:
            raise PayOSWebhookRejected()

        verified_order_code = _field(verified, "order_code", "orderCode")
        verified_amount = _field(verified, "amount")
        verified_reference = _field(verified, "reference")
        verified_paid_at = _parse_payment_datetime(
            _field(
                verified,
                "transaction_date_time",
                "transactionDateTime",
            )
        )
        verified_code = _field(verified, "code")
        if (
            verified_order_code != order_code
            or verified_amount != amount
            or verified_reference != reference
            or verified_paid_at != paid_at
            or verified_code != "00"
        ):
            raise PayOSWebhookRejected()

        return VerifiedPayOSPayment(
            order_code=order_code,
            amount=amount,
            reference=reference.strip(),
            paid_at=paid_at,
            success=True,
            payload_hash=payload_hash,
        )

    def get_payment(self, order_code: int) -> PayOSPaymentStatus:
        if not _valid_order_code(order_code):
            raise PayOSPaymentLookupError()
        try:
            response = self._sdk.payment_requests.get(order_code)
        except Exception:
            raise PayOSPaymentLookupError() from None

        try:
            response_order_code = _field(
                response,
                "order_code",
                "orderCode",
            )
            amount_paid = _field(response, "amount_paid", "amountPaid")
            raw_status = _field(response, "status")
            if (
                not _valid_order_code(response_order_code)
                or response_order_code != order_code
                or not _valid_nonnegative_int(amount_paid)
                or not isinstance(raw_status, str)
            ):
                raise PayOSPaymentLookupError()

            status = (
                raw_status
                if raw_status in {"PENDING", "PAID", "CANCELLED", "EXPIRED"}
                else "UNKNOWN"
            )
            reference = ""
            paid_at = None
            if status == "PAID":
                if amount_paid <= 0:
                    raise PayOSPaymentLookupError()
                transactions = _field(response, "transactions")
                if not isinstance(transactions, (list, tuple)) or not transactions:
                    raise PayOSPaymentLookupError()
                safe_transactions: list[tuple[datetime, str]] = []
                for transaction in transactions:
                    transaction_reference = _field(transaction, "reference")
                    transaction_paid_at = _parse_payment_datetime(
                        _field(
                            transaction,
                            "transaction_date_time",
                            "transactionDateTime",
                        )
                    )
                    if (
                        not _valid_reference(transaction_reference)
                        or transaction_paid_at is None
                    ):
                        raise PayOSPaymentLookupError()
                    safe_transactions.append(
                        (
                            transaction_paid_at,
                            transaction_reference.strip(),
                        )
                    )
                paid_at, reference = max(safe_transactions, key=lambda item: item[0])

            return PayOSPaymentStatus(
                order_code=order_code,
                status=status,
                amount_paid=amount_paid,
                reference=reference,
                paid_at=paid_at,
            )
        except PayOSPaymentLookupError:
            raise
        except Exception:
            raise PayOSPaymentLookupError() from None


def _payment_description(order_code: int) -> str:
    value = order_code
    digits = ""
    while value:
        value, remainder = divmod(value, 36)
        digits = _BASE36_ALPHABET[remainder] + digits
    return "BD" + (digits or "0")


def _create_sdk() -> object:
    try:
        settings = get_digital_product_commerce_settings()
        credentials = (
            settings.payos_client_id,
            settings.payos_api_key,
            settings.payos_checksum_key,
        )
        if any(
            not isinstance(value, str) or not value.strip()
            for value in credentials
        ):
            raise PayOSConfigurationError()
        return _PayOSSDK(
            client_id=settings.payos_client_id,
            api_key=settings.payos_api_key,
            checksum_key=settings.payos_checksum_key,
            timeout=_SDK_TIMEOUT_SECONDS,
            max_retries=_SDK_MAX_RETRIES,
        )
    except PayOSConfigurationError:
        raise
    except Exception:
        raise PayOSConfigurationError() from None


def _validate_pending_order(order: object) -> None:
    if (
        not isinstance(order, DigitalProductOrder)
        or order.status != "pending"
        or order.currency != "VND"
        or not _valid_order_code(order.payos_order_code)
        or not _valid_positive_int(order.expected_amount)
        or not isinstance(order.public_id, str)
        or _PUBLIC_ID_PATTERN.fullmatch(order.public_id) is None
        or not isinstance(order.payment_expires_at, datetime)
    ):
        raise PayOSPaymentLinkCreationError()


def _validate_order_url(value: object, public_id: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_URL_LENGTH
    ):
        raise PayOSPaymentLinkCreationError()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise PayOSPaymentLinkCreationError() from None
    expected_path = f"/ban-do-thu-dau-mot/don-hang/{public_id}"
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != expected_path
        or (port is not None and not 1 <= port <= 65_535)
    ):
        raise PayOSPaymentLinkCreationError()


def _valid_checkout_url(value: object) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_URL_LENGTH
    ):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and (port is None or 1 <= port <= 65_535)
    )


def _field(value: object, *names: str) -> object:
    try:
        if isinstance(value, Mapping):
            for name in names:
                if name in value:
                    return value[name]
            return _MISSING
        for name in names:
            try:
                return getattr(value, name)
            except (AttributeError, TypeError):
                continue
    except Exception:
        return _MISSING
    return _MISSING


def _valid_order_code(value: object) -> bool:
    return bool(
        not isinstance(value, bool)
        and isinstance(value, int)
        and ORDER_CODE_BASE < value <= MAX_PAYOS_ORDER_CODE
    )


def _valid_positive_int(value: object) -> bool:
    return bool(
        not isinstance(value, bool)
        and isinstance(value, int)
        and 0 < value <= _MAX_VND_AMOUNT
    )


def _valid_nonnegative_int(value: object) -> bool:
    return bool(
        not isinstance(value, bool)
        and isinstance(value, int)
        and 0 <= value <= _MAX_VND_AMOUNT
    )


def _valid_reference(value: object) -> bool:
    return _valid_safe_string(value, maximum=128)


def _valid_safe_string(value: object, *, maximum: int) -> bool:
    return bool(
        isinstance(value, str)
        and value.strip()
        and len(value) <= maximum
        and value.isprintable()
    )


def _normalize_server_datetime(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    try:
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None


def _parse_payment_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif (
        isinstance(value, str)
        and value.strip()
        and _PAYMENT_DATETIME_PATTERN.fullmatch(value.strip()) is not None
    ):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_PAYOS_TIMEZONE)
    try:
        return parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None
