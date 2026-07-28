from __future__ import annotations

import json
import inspect
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import payos
import pytest
from flask import Flask, jsonify
from payos import PayOS
from payos.resources.v2.payment_requests import PaymentRequests
from payos.resources.webhooks import Webhooks
from payos.types import (
    CreatePaymentLinkRequest,
    CreatePaymentLinkResponse,
    PaymentLink,
    Transaction,
    WebhookData,
)

import services.payos_client as payos_client_module
from config.settings import DigitalProductCommerceSettings
from services.digital_product_orders import DigitalProductOrder
from services.payos_client import (
    PayOSClient,
    PayOSConfigurationError,
    PayOSPaymentLink,
    PayOSPaymentLinkCreationError,
    PayOSPaymentLookupError,
    PayOSPaymentStatus,
    PayOSWebhookRejected,
    VerifiedPayOSPayment,
)


FROZEN_NOW = datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)
ORDER_URL = (
    "https://radarbds.vn/ban-do-thu-dau-mot/don-hang/"
    "0123456789abcdef0123456789abcdef"
)
RAW_WEBHOOK = (
    b'{"code":"00","desc":"success","success":true,"data":{'
    b'"orderCode":720000123,"amount":99000,"description":"BDBWO3NF",'
    b'"accountNumber":"secret-account","reference":"BANK-REF-1",'
    b'"transactionDateTime":"2026-07-29 16:30:00","currency":"VND",'
    b'"paymentLinkId":"link_0123456789abcdef","code":"00","desc":"success",'
    b'"counterAccountBankId":"","counterAccountBankName":"",'
    b'"counterAccountName":"","counterAccountNumber":"",'
    b'"virtualAccountName":"","virtualAccountNumber":""},'
    b'"signature":"secret-signature"}'
)


def _pending_order(
    *,
    order_code: int = 720_000_123,
    payment_expires_at: datetime = FROZEN_NOW + timedelta(minutes=15),
) -> DigitalProductOrder:
    return DigitalProductOrder(
        id=123,
        public_id="0123456789abcdef0123456789abcdef",
        product_slug="thu-dau-mot-map-bundle",
        product_version="1.0",
        expected_amount=99_000,
        currency="VND",
        payos_order_code=order_code,
        payment_link_id=None,
        checkout_url=None,
        qr_code=None,
        status="pending",
        recovery_token_hash=None,
        paid_amount=None,
        payment_reference=None,
        created_at=FROZEN_NOW,
        payment_expires_at=payment_expires_at,
        paid_at=None,
        download_expires_at=None,
        download_count=0,
        last_download_at=None,
    )


class _FakePaymentRequests:
    def __init__(self) -> None:
        self.created: list[CreatePaymentLinkRequest] = []
        self.create_error: Exception | None = None
        self.create_result: object | None = None
        self.get_calls: list[int] = []
        self.get_error: Exception | None = None
        self.get_result: object = PaymentLink(
            id="link_0123456789abcdef",
            order_code=720_000_123,
            amount=99_000,
            amount_paid=99_000,
            amount_remaining=0,
            status="PAID",
            created_at="2026-07-29T09:30:00+00:00",
            transactions=[
                Transaction(
                    reference="BANK-REF-EARLY",
                    amount=49_000,
                    account_number="secret-account",
                    description="BDBWO3NF",
                    transaction_date_time="2026-07-29 16:29:00",
                    virtual_account_name=None,
                    virtual_account_number=None,
                    counter_account_bank_id=None,
                    counter_account_bank_name=None,
                    counter_account_name=None,
                    counter_account_number=None,
                ),
                Transaction(
                    reference="BANK-REF-1",
                    amount=50_000,
                    account_number="secret-account",
                    description="BDBWO3NF",
                    transaction_date_time="2026-07-29 16:30:00",
                    virtual_account_name=None,
                    virtual_account_number=None,
                    counter_account_bank_id=None,
                    counter_account_bank_name=None,
                    counter_account_name=None,
                    counter_account_number=None,
                ),
            ],
            cancellation_reason=None,
            canceled_at=None,
        )

    def create(
        self,
        *,
        payment_data: CreatePaymentLinkRequest,
    ) -> object:
        self.created.append(payment_data)
        if self.create_error is not None:
            raise self.create_error
        if self.create_result is not None:
            return self.create_result
        return CreatePaymentLinkResponse(
            bin="970422",
            account_number="123456789",
            account_name="RADAR BDS",
            amount=payment_data.amount,
            description=payment_data.description,
            order_code=payment_data.order_code,
            currency="VND",
            payment_link_id="link_0123456789abcdef",
            status="PENDING",
            expired_at=payment_data.expired_at,
            checkout_url="https://pay.payos.vn/web/link_0123456789abcdef",
            qr_code="00020101021238570010A000000727012700069704220113123456789",
        )

    def get(self, order_code: int) -> object:
        self.get_calls.append(order_code)
        if self.get_error is not None:
            raise self.get_error
        return self.get_result


class _FakeWebhooks:
    def __init__(self) -> None:
        self.raw_inputs: list[bytes] = []
        self.error: Exception | None = None
        self.result: object = WebhookData(
            order_code=720_000_123,
            amount=99_000,
            description="BDBWO3NF",
            account_number="secret-account",
            reference="BANK-REF-1",
            transaction_date_time="2026-07-29 16:30:00",
            currency="VND",
            payment_link_id="link_0123456789abcdef",
            code="00",
            desc="success",
            counter_account_bank_id="",
            counter_account_bank_name="",
            counter_account_name="",
            counter_account_number="",
            virtual_account_name="",
            virtual_account_number="",
        )

    def verify(self, raw_body: bytes) -> object:
        self.raw_inputs.append(raw_body)
        if self.error is not None:
            raise self.error
        return self.result


class _FakeSDK:
    def __init__(self) -> None:
        self.payment_requests = _FakePaymentRequests()
        self.webhooks = _FakeWebhooks()


def test_create_link_uses_immutable_server_terms_and_official_request_type():
    sdk = _FakeSDK()
    order = _pending_order()

    link = PayOSClient(sdk).create_payment_link(order, ORDER_URL, ORDER_URL)

    assert len(sdk.payment_requests.created) == 1
    request = sdk.payment_requests.created[0]
    assert isinstance(request, CreatePaymentLinkRequest)
    assert request.amount == 99_000
    assert request.order_code == 720_000_123
    assert request.description == "BDBWO3NF"
    assert request.description.isascii()
    assert len(request.description) <= 9
    assert request.return_url == ORDER_URL
    assert request.cancel_url == ORDER_URL
    assert request.expired_at == 1_785_318_300
    assert request.items is None
    assert request.buyer_email is None
    assert request.buyer_phone is None
    assert link.payment_link_id == "link_0123456789abcdef"
    assert link.checkout_url == "https://pay.payos.vn/web/link_0123456789abcdef"
    assert link.qr_payload.startswith("000201")


@pytest.mark.parametrize(
    ("order_code", "expected_description"),
    [
        (720_000_001, "BDBWO3K1"),
        (2_147_483_647, "BDZIK0ZJ"),
    ],
)
def test_create_link_base36_description_is_unique_reversible_and_bounded(
    order_code: int,
    expected_description: str,
):
    sdk = _FakeSDK()
    order = _pending_order(order_code=order_code)

    PayOSClient(sdk).create_payment_link(order, ORDER_URL, ORDER_URL)

    request = sdk.payment_requests.created[0]
    assert request.description == expected_description
    assert request.description.startswith("BD")
    assert request.description.isascii()
    assert len(request.description) <= 9
    assert int(request.description[2:], 36) == order_code


@pytest.mark.parametrize(
    "bad_order_code",
    [True, -1, 0, 720_000_000, 2_147_483_648, "720000123", None],
)
def test_create_link_rejects_invalid_order_codes_before_sdk_call(
    bad_order_code: object,
):
    sdk = _FakeSDK()
    order = _pending_order().with_updates(payos_order_code=bad_order_code)

    with pytest.raises(
        PayOSPaymentLinkCreationError,
        match=r"^PayOS payment link creation failed$",
    ):
        PayOSClient(sdk).create_payment_link(order, ORDER_URL, ORDER_URL)

    assert sdk.payment_requests.created == []


@pytest.mark.parametrize("bad_amount", [True, -1, 0, "99000", None])
def test_create_link_rejects_invalid_server_amount_before_sdk_call(
    bad_amount: object,
):
    sdk = _FakeSDK()
    order = _pending_order().with_updates(expected_amount=bad_amount)

    with pytest.raises(PayOSPaymentLinkCreationError):
        PayOSClient(sdk).create_payment_link(order, ORDER_URL, ORDER_URL)

    assert sdk.payment_requests.created == []


@pytest.mark.parametrize(
    "order_change",
    [
        {"currency": "USD"},
        {"status": "paid"},
        {"public_id": ""},
        {"public_id": "not-a-public-id"},
        {"payment_expires_at": "2026-07-29T09:45:00Z"},
    ],
)
def test_create_link_rejects_invalid_order_state_and_identity(
    order_change: dict[str, object],
):
    sdk = _FakeSDK()
    order = _pending_order().with_updates(**order_change)

    with pytest.raises(PayOSPaymentLinkCreationError):
        PayOSClient(sdk).create_payment_link(order, ORDER_URL, ORDER_URL)

    assert sdk.payment_requests.created == []


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://radarbds.vn/ban-do-thu-dau-mot/don-hang/"
        "0123456789abcdef0123456789abcdef",
        ORDER_URL + "?token=recovery-secret",
        ORDER_URL + "#token=recovery-secret",
        "https://user:pass@radarbds.vn/ban-do-thu-dau-mot/don-hang/"
        "0123456789abcdef0123456789abcdef",
        "https://radarbds.vn/ban-do-thu-dau-mot/don-hang/wrong-public-id",
        "javascript:alert(1)",
    ],
)
def test_create_link_rejects_non_public_id_return_and_cancel_urls(
    bad_url: str,
):
    sdk = _FakeSDK()

    with pytest.raises(PayOSPaymentLinkCreationError):
        PayOSClient(sdk).create_payment_link(
            _pending_order(),
            bad_url,
            bad_url,
        )

    assert sdk.payment_requests.created == []


def test_create_link_requires_return_and_cancel_to_be_same_order_url():
    sdk = _FakeSDK()
    other_origin = ORDER_URL.replace("radarbds.vn", "example.test")

    with pytest.raises(PayOSPaymentLinkCreationError):
        PayOSClient(sdk).create_payment_link(
            _pending_order(),
            ORDER_URL,
            other_origin,
        )

    assert sdk.payment_requests.created == []


@pytest.mark.parametrize(
    "attacker_url",
    [
        ORDER_URL.replace("radarbds.vn", "attacker.example"),
        ORDER_URL.replace("https://", "https://user@"),
        ORDER_URL + "?recovery=secret",
        ORDER_URL + "#recovery-secret",
        ORDER_URL.replace("radarbds.vn", "radarbds.vn:444"),
        ORDER_URL.replace("/don-hang/", "/don-hang%2F"),
        ORDER_URL.replace("/don-hang/", "/don-hang/%2e%2e/"),
    ],
)
def test_create_link_rejects_urls_outside_configured_trusted_origin(
    attacker_url: str,
):
    sdk = _FakeSDK()
    client = PayOSClient(sdk, trusted_origin="https://radarbds.vn")

    with pytest.raises(PayOSPaymentLinkCreationError):
        client.create_payment_link(
            _pending_order(),
            attacker_url,
            attacker_url,
        )

    assert sdk.payment_requests.created == []


@pytest.mark.parametrize(
    "trusted_origin",
    [
        "",
        "radarbds.vn",
        "http://radarbds.vn",
        "https://user@radarbds.vn",
        "https://radarbds.vn/path",
        "https://radarbds.vn?query=1",
        "https://radarbds.vn#fragment",
    ],
)
def test_client_rejects_missing_or_malformed_trusted_origin(
    trusted_origin: str,
):
    with pytest.raises(
        PayOSConfigurationError,
        match=r"^PayOS client configuration failed$",
    ):
        PayOSClient(_FakeSDK(), trusted_origin=trusted_origin)


def test_create_link_allows_canonical_https_effective_default_port():
    sdk = _FakeSDK()
    client = PayOSClient(sdk, trusted_origin="https://RADARBDS.VN:443")
    default_port_url = ORDER_URL.replace(
        "https://radarbds.vn",
        "https://RADARBDS.VN:443",
    )

    link = client.create_payment_link(
        _pending_order(),
        default_port_url,
        default_port_url,
    )

    assert link.payment_link_id == "link_0123456789abcdef"
    assert sdk.payment_requests.created[0].return_url == default_port_url


def test_default_client_fails_closed_when_public_base_url_is_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(payos_client_module, "PUBLIC_BASE_URL", "")

    with pytest.raises(PayOSConfigurationError):
        PayOSClient(_FakeSDK())


@pytest.mark.parametrize(
    "payment_expires_at",
    [
        datetime(2026, 7, 29, 9, 45),
        datetime(
            2026,
            7,
            29,
            16,
            45,
            tzinfo=timezone(timedelta(hours=7)),
        ),
    ],
)
def test_create_link_normalizes_naive_utc_and_aware_expiry(
    payment_expires_at: datetime,
):
    sdk = _FakeSDK()
    order = _pending_order(payment_expires_at=payment_expires_at)

    PayOSClient(sdk).create_payment_link(order, ORDER_URL, ORDER_URL)

    assert sdk.payment_requests.created[0].expired_at == 1_785_318_300


def test_create_link_maps_camel_case_dict_response():
    sdk = _FakeSDK()
    sdk.payment_requests.create_result = {
        "bin": "970422",
        "accountNumber": "secret-account",
        "accountName": "RADAR BDS",
        "amount": 99_000,
        "description": "BDBWO3NF",
        "orderCode": 720_000_123,
        "currency": "VND",
        "paymentLinkId": "link_0123456789abcdef",
        "status": "PENDING",
        "expiredAt": 1_785_318_300,
        "checkoutUrl": "https://pay.payos.vn/web/link_0123456789abcdef",
        "qrCode": "00020101021238570010A000000727",
    }

    link = PayOSClient(sdk).create_payment_link(
        _pending_order(),
        ORDER_URL,
        ORDER_URL,
    )

    assert link.payment_link_id == "link_0123456789abcdef"
    assert link.checkout_url == "https://pay.payos.vn/web/link_0123456789abcdef"
    assert link.qr_payload == "00020101021238570010A000000727"


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("orderCode", True),
        ("orderCode", 720_000_124),
        ("amount", True),
        ("amount", 98_999),
        ("paymentLinkId", ""),
        ("checkoutUrl", "http://pay.payos.vn/web/link"),
        ("checkoutUrl", "javascript:alert(1)"),
        ("qrCode", ""),
    ],
)
def test_create_link_rejects_malformed_or_mismatched_sdk_response(
    field: str,
    bad_value: object,
):
    sdk = _FakeSDK()
    response = {
        "orderCode": 720_000_123,
        "amount": 99_000,
        "paymentLinkId": "link_0123456789abcdef",
        "checkoutUrl": "https://pay.payos.vn/web/link_0123456789abcdef",
        "qrCode": "00020101021238570010A000000727",
    }
    response[field] = bad_value
    sdk.payment_requests.create_result = response

    with pytest.raises(PayOSPaymentLinkCreationError):
        PayOSClient(sdk).create_payment_link(
            _pending_order(),
            ORDER_URL,
            ORDER_URL,
        )


def test_create_link_maps_sdk_errors_without_leaking_credentials_or_payload():
    sdk = _FakeSDK()
    sdk.payment_requests.create_error = RuntimeError(
        "credential-marker secret-account 000201010212"
    )

    with pytest.raises(
        PayOSPaymentLinkCreationError,
        match=r"^PayOS payment link creation failed$",
    ) as caught:
        PayOSClient(sdk).create_payment_link(
            _pending_order(),
            ORDER_URL,
            ORDER_URL,
        )

    assert caught.value.__cause__ is None
    assert "credential-marker" not in repr(caught.value)
    assert "000201" not in str(caught.value)


def test_verify_webhook_passes_exact_raw_bytes_once_and_maps_official_model():
    sdk = _FakeSDK()

    payment = PayOSClient(sdk).verify_webhook(RAW_WEBHOOK)

    assert isinstance(payment, VerifiedPayOSPayment)
    assert sdk.webhooks.raw_inputs == [RAW_WEBHOOK]
    assert payment.order_code == 720_000_123
    assert payment.amount == 99_000
    assert payment.reference == "BANK-REF-1"
    assert payment.paid_at == datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)
    assert payment.success is True
    assert (
        payment.payload_hash
        == "3ab11a2d2a89218cdb768974d827b69c28f1cc306c4c6d5af2f96ae0397d5843"
    )


def test_verify_webhook_maps_camel_case_dict_and_aware_timestamp():
    sdk = _FakeSDK()
    payload = _webhook_payload()
    payload["data"]["transactionDateTime"] = "2026-07-29T09:30:00+00:00"
    raw_body = _encode_webhook(payload)
    sdk.webhooks.result = dict(payload["data"])

    payment = PayOSClient(sdk).verify_webhook(raw_body)

    assert payment.paid_at == datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)
    assert payment.reference == "BANK-REF-1"


def test_verify_webhook_maps_sdk_errors_to_non_leaking_rejection():
    sdk = _FakeSDK()
    sdk.webhooks.error = RuntimeError(
        "secret-signature secret-account " + RAW_WEBHOOK.decode("utf-8")
    )

    with pytest.raises(
        PayOSWebhookRejected,
        match=r"^PayOS webhook rejected$",
    ) as caught:
        PayOSClient(sdk).verify_webhook(RAW_WEBHOOK)

    assert sdk.webhooks.raw_inputs == [RAW_WEBHOOK]
    assert caught.value.__cause__ is None
    assert "secret" not in repr(caught.value).lower()
    assert RAW_WEBHOOK.decode("utf-8") not in str(caught.value)


def test_verify_webhook_maps_hostile_verified_object_errors_to_rejection():
    sdk = _FakeSDK()

    class _HostileVerifiedObject:
        @property
        def order_code(self) -> int:
            raise RuntimeError("credential-marker secret-signature")

    sdk.webhooks.result = _HostileVerifiedObject()

    with pytest.raises(
        PayOSWebhookRejected,
        match=r"^PayOS webhook rejected$",
    ) as caught:
        PayOSClient(sdk).verify_webhook(RAW_WEBHOOK)

    assert "credential-marker" not in repr(caught.value)
    assert "secret-signature" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("field", "hostile_value"),
    [
        ("order_code", "hostile_int"),
        ("amount", "hostile_int"),
        ("reference", "hostile_string"),
        ("transaction_date_time", "hostile_string"),
        ("code", "hostile_string"),
    ],
)
def test_verify_webhook_rejects_hostile_verified_primitive_subclasses(
    field: str,
    hostile_value: str,
):
    sdk = _FakeSDK()

    class _HostileInt(int):
        def __eq__(self, other: object) -> bool:
            del other
            raise RuntimeError("primitive-marker secret-signature")

        def __ne__(self, other: object) -> bool:
            del other
            raise RuntimeError("primitive-marker secret-signature")

    class _HostileString(str):
        def __eq__(self, other: object) -> bool:
            del other
            raise RuntimeError("primitive-marker secret-signature")

        def __ne__(self, other: object) -> bool:
            del other
            raise RuntimeError("primitive-marker secret-signature")

        def strip(self, chars: str | None = None) -> str:
            del chars
            raise RuntimeError("primitive-marker secret-signature")

    values: dict[str, object] = {
        "order_code": 720_000_123,
        "amount": 99_000,
        "reference": "BANK-REF-1",
        "transaction_date_time": "2026-07-29 16:30:00",
        "code": "00",
    }
    original = values[field]
    values[field] = (
        _HostileInt(original)
        if hostile_value == "hostile_int"
        else _HostileString(original)
    )
    sdk.webhooks.result = values

    with pytest.raises(
        PayOSWebhookRejected,
        match=r"^PayOS webhook rejected$",
    ) as caught:
        PayOSClient(sdk).verify_webhook(RAW_WEBHOOK)

    assert caught.value.__cause__ is None
    assert "primitive-marker" not in repr(caught.value)
    assert "secret-signature" not in str(caught.value)


def test_verify_webhook_rejects_verified_mapping_with_throwing_iteration():
    sdk = _FakeSDK()

    class _HostileMapping(Mapping[str, object]):
        def __getitem__(self, key: str) -> object:
            del key
            raise RuntimeError("iteration-marker secret-signature")

        def __iter__(self):
            raise RuntimeError("iteration-marker secret-signature")

        def __len__(self) -> int:
            raise RuntimeError("iteration-marker secret-signature")

    sdk.webhooks.result = _HostileMapping()

    with pytest.raises(
        PayOSWebhookRejected,
        match=r"^PayOS webhook rejected$",
    ) as caught:
        PayOSClient(sdk).verify_webhook(RAW_WEBHOOK)

    assert caught.value.__cause__ is None
    assert "iteration-marker" not in repr(caught.value)
    assert "secret-signature" not in str(caught.value)


def test_verify_webhook_rejects_missing_signature_even_if_fake_sdk_accepts():
    sdk = _FakeSDK()
    payload = _webhook_payload()
    del payload["signature"]
    raw_body = _encode_webhook(payload)

    with pytest.raises(PayOSWebhookRejected):
        PayOSClient(sdk).verify_webhook(raw_body)

    assert sdk.webhooks.raw_inputs == [raw_body]


def test_verify_webhook_rejects_oversized_body_before_sdk_parsing():
    sdk = _FakeSDK()
    raw_body = RAW_WEBHOOK + (b" " * 65_536)

    with pytest.raises(PayOSWebhookRejected):
        PayOSClient(sdk).verify_webhook(raw_body)

    assert sdk.webhooks.raw_inputs == []


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("orderCode", True),
        ("orderCode", "720000123"),
        ("orderCode", 0),
        ("amount", True),
        ("amount", "99000"),
        ("amount", 0),
    ],
)
def test_verify_webhook_rejects_boolean_non_integer_and_nonpositive_numbers(
    field: str,
    bad_value: object,
):
    sdk = _FakeSDK()
    payload = _webhook_payload()
    payload["data"][field] = bad_value
    raw_body = _encode_webhook(payload)

    with pytest.raises(PayOSWebhookRejected):
        PayOSClient(sdk).verify_webhook(raw_body)

    assert sdk.webhooks.raw_inputs == [raw_body]


@pytest.mark.parametrize("missing_field", ["orderCode", "amount"])
def test_verify_webhook_rejects_missing_numeric_fields(missing_field: str):
    sdk = _FakeSDK()
    payload = _webhook_payload()
    del payload["data"][missing_field]
    raw_body = _encode_webhook(payload)

    with pytest.raises(PayOSWebhookRejected):
        PayOSClient(sdk).verify_webhook(raw_body)


@pytest.mark.parametrize(
    "root_change",
    [
        {"success": False},
        {"success": None},
        {"code": "01"},
    ],
)
def test_verify_webhook_rejects_unsuccessful_events(
    root_change: dict[str, object],
):
    sdk = _FakeSDK()
    payload = _webhook_payload()
    payload.update(root_change)
    raw_body = _encode_webhook(payload)

    with pytest.raises(PayOSWebhookRejected):
        PayOSClient(sdk).verify_webhook(raw_body)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("reference", ""),
        ("reference", True),
        ("reference", "BANK-\nREF"),
        ("transactionDateTime", ""),
        ("transactionDateTime", True),
        ("transactionDateTime", "29/07/2026 16:30"),
        ("code", "01"),
    ],
)
def test_verify_webhook_rejects_invalid_reference_date_and_data_status(
    field: str,
    bad_value: object,
):
    sdk = _FakeSDK()
    payload = _webhook_payload()
    payload["data"][field] = bad_value
    raw_body = _encode_webhook(payload)

    with pytest.raises(PayOSWebhookRejected):
        PayOSClient(sdk).verify_webhook(raw_body)


@pytest.mark.parametrize(
    "raw_body",
    [
        b"",
        b"not-json",
        b"[]",
        b'{"code":"00"}',
    ],
)
def test_verify_webhook_rejects_malformed_raw_payload(raw_body: bytes):
    sdk = _FakeSDK()

    with pytest.raises(PayOSWebhookRejected):
        PayOSClient(sdk).verify_webhook(raw_body)


def test_get_payment_maps_official_paid_response_and_latest_transaction():
    sdk = _FakeSDK()

    status = PayOSClient(sdk).get_payment(720_000_123)

    assert isinstance(status, PayOSPaymentStatus)
    assert sdk.payment_requests.get_calls == [720_000_123]
    assert status.order_code == 720_000_123
    assert status.status == "PAID"
    assert status.amount_paid == 99_000
    assert status.reference == "BANK-REF-1"
    assert status.paid_at == datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)


def test_get_payment_maps_camel_case_dict_and_aware_transaction_time():
    sdk = _FakeSDK()
    sdk.payment_requests.get_result = {
        "id": "link_0123456789abcdef",
        "orderCode": 720_000_123,
        "amount": 99_000,
        "amountPaid": 99_000,
        "amountRemaining": 0,
        "status": "PAID",
        "createdAt": "2026-07-29T09:15:00+00:00",
        "transactions": [
            {
                "reference": "BANK-REF-1",
                "amount": 99_000,
                "accountNumber": "secret-account",
                "description": "BDBWO3NF",
                "transactionDateTime": "2026-07-29T09:30:00Z",
                "virtualAccountName": None,
                "virtualAccountNumber": None,
                "counterAccountBankId": None,
                "counterAccountBankName": None,
                "counterAccountName": None,
                "counterAccountNumber": None,
            }
        ],
        "cancellationReason": None,
        "canceledAt": None,
    }

    status = PayOSClient(sdk).get_payment(720_000_123)

    assert status.status == "PAID"
    assert status.reference == "BANK-REF-1"
    assert status.paid_at == datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)


def test_get_payment_uses_first_transaction_that_crosses_expected_amount():
    sdk = _FakeSDK()
    current = sdk.payment_requests.get_result
    assert isinstance(current, PaymentLink)
    sdk.payment_requests.get_result = current.model_copy(
        update={
            "amount": 99_000,
            "amount_paid": 99_001,
            "transactions": [
                _transaction(
                    reference="THRESHOLD",
                    amount=99_000,
                    paid_at="2026-07-29 16:29:00",
                ),
                _transaction(
                    reference="LATER-ONE-DONG",
                    amount=1,
                    paid_at="2026-07-29 16:30:00",
                ),
            ],
        }
    )

    status = PayOSClient(sdk).get_payment(720_000_123)

    assert status.amount_paid == 99_001
    assert status.reference == "THRESHOLD"
    assert status.paid_at == datetime(2026, 7, 29, 9, 29, tzinfo=timezone.utc)


def test_get_payment_sorts_split_transactions_before_finding_threshold():
    sdk = _FakeSDK()
    current = sdk.payment_requests.get_result
    assert isinstance(current, PaymentLink)
    sdk.payment_requests.get_result = current.model_copy(
        update={
            "transactions": [
                _transaction(
                    reference="SECOND",
                    amount=50_000,
                    paid_at="2026-07-29 16:30:00",
                ),
                _transaction(
                    reference="FIRST",
                    amount=49_000,
                    paid_at="2026-07-29 16:29:00",
                ),
            ]
        }
    )

    status = PayOSClient(sdk).get_payment(720_000_123)

    assert status.reference == "SECOND"
    assert status.paid_at == datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("reverse_input", [False, True])
def test_get_payment_equal_timestamps_have_deterministic_reference_tiebreak(
    reverse_input: bool,
):
    sdk = _FakeSDK()
    current = sdk.payment_requests.get_result
    assert isinstance(current, PaymentLink)
    transactions = [
        _transaction(
            reference="A-FIRST",
            amount=49_000,
            paid_at="2026-07-29 16:30:00",
        ),
        _transaction(
            reference="B-THRESHOLD",
            amount=50_000,
            paid_at="2026-07-29 16:30:00",
        ),
    ]
    sdk.payment_requests.get_result = current.model_copy(
        update={
            "transactions": (
                list(reversed(transactions))
                if reverse_input
                else transactions
            )
        }
    )

    status = PayOSClient(sdk).get_payment(720_000_123)

    assert status.reference == "B-THRESHOLD"
    assert status.paid_at == datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)


def test_get_payment_preserves_underpaid_paid_evidence_for_payment_review():
    sdk = _FakeSDK()
    current = sdk.payment_requests.get_result
    assert isinstance(current, PaymentLink)
    sdk.payment_requests.get_result = current.model_copy(
        update={
            "amount_paid": 50_000,
            "amount_remaining": 49_000,
            "transactions": [
                _transaction(
                    reference="UNDERPAID",
                    amount=50_000,
                    paid_at="2026-07-29 16:29:00",
                )
            ],
        }
    )

    status = PayOSClient(sdk).get_payment(720_000_123)

    assert status.status == "PAID"
    assert status.amount_paid == 50_000
    assert status.reference == "UNDERPAID"
    assert status.paid_at == datetime(2026, 7, 29, 9, 29, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("amount_paid", "transaction_amount"),
    [
        (99_000, 98_999),
        (99_000, 99_001),
        (1, 2),
    ],
)
def test_get_payment_rejects_transaction_sum_mismatch(
    amount_paid: int,
    transaction_amount: int,
):
    sdk = _FakeSDK()
    current = sdk.payment_requests.get_result
    assert isinstance(current, PaymentLink)
    sdk.payment_requests.get_result = current.model_copy(
        update={
            "amount_paid": amount_paid,
            "transactions": [
                _transaction(
                    reference="MISMATCH",
                    amount=transaction_amount,
                    paid_at="2026-07-29 16:30:00",
                )
            ],
        }
    )

    with pytest.raises(PayOSPaymentLookupError):
        PayOSClient(sdk).get_payment(720_000_123)


@pytest.mark.parametrize("bad_amount", [True, False, 0, -1, "99000"])
def test_get_payment_rejects_malformed_expected_amount(bad_amount: object):
    sdk = _FakeSDK()
    current = sdk.payment_requests.get_result
    assert isinstance(current, PaymentLink)
    sdk.payment_requests.get_result = current.model_copy(
        update={"amount": bad_amount}
    )

    with pytest.raises(PayOSPaymentLookupError):
        PayOSClient(sdk).get_payment(720_000_123)


@pytest.mark.parametrize("bad_amount", [True, False, 0, -1, "99000"])
def test_get_payment_rejects_malformed_transaction_amount(bad_amount: object):
    sdk = _FakeSDK()
    current = sdk.payment_requests.get_result
    assert isinstance(current, PaymentLink)
    sdk.payment_requests.get_result = current.model_copy(
        update={
            "transactions": [
                _transaction(
                    reference="BAD-AMOUNT",
                    amount=bad_amount,
                    paid_at="2026-07-29 16:30:00",
                )
            ]
        }
    )

    with pytest.raises(PayOSPaymentLookupError):
        PayOSClient(sdk).get_payment(720_000_123)


@pytest.mark.parametrize(
    ("response_field", "transaction_field"),
    [
        ("amount", None),
        (None, "amount"),
        (None, "reference"),
        (None, "transaction_date_time"),
    ],
)
def test_get_payment_rejects_non_builtin_official_model_primitives(
    response_field: str | None,
    transaction_field: str | None,
):
    sdk = _FakeSDK()
    current = sdk.payment_requests.get_result
    assert isinstance(current, PaymentLink)

    class _IntSubclass(int):
        pass

    class _StringSubclass(str):
        pass

    transaction_updates: dict[str, object] = {}
    if transaction_field == "amount":
        transaction_updates[transaction_field] = _IntSubclass(99_000)
    elif transaction_field == "reference":
        transaction_updates[transaction_field] = _StringSubclass("REFERENCE")
    elif transaction_field == "transaction_date_time":
        transaction_updates[transaction_field] = _StringSubclass(
            "2026-07-29 16:30:00"
        )
    transaction = _transaction(
        reference="REFERENCE",
        amount=99_000,
        paid_at="2026-07-29 16:30:00",
    ).model_copy(update=transaction_updates)
    response_updates: dict[str, object] = {"transactions": [transaction]}
    if response_field == "amount":
        response_updates[response_field] = _IntSubclass(99_000)
    sdk.payment_requests.get_result = current.model_copy(
        update=response_updates
    )

    with pytest.raises(PayOSPaymentLookupError):
        PayOSClient(sdk).get_payment(720_000_123)


@pytest.mark.parametrize(
    ("sdk_status", "expected"),
    [
        ("PENDING", "PENDING"),
        ("PAID", "PAID"),
        ("CANCELLED", "CANCELLED"),
        ("EXPIRED", "EXPIRED"),
        ("UNDERPAID", "UNKNOWN"),
        ("PROCESSING", "UNKNOWN"),
        ("FAILED", "UNKNOWN"),
    ],
)
def test_get_payment_uses_strict_status_allowlist(
    sdk_status: str,
    expected: str,
):
    sdk = _FakeSDK()
    current = sdk.payment_requests.get_result
    assert isinstance(current, PaymentLink)
    sdk.payment_requests.get_result = current.model_copy(
        update={
            "status": sdk_status,
            "amount_paid": 99_000 if sdk_status == "PAID" else 0,
            "transactions": current.transactions if sdk_status == "PAID" else [],
        }
    )

    status = PayOSClient(sdk).get_payment(720_000_123)

    assert status.status == expected
    if sdk_status != "PAID":
        assert status.reference == ""
        assert status.paid_at is None


@pytest.mark.parametrize(
    "bad_order_code",
    [True, 0, 720_000_000, 2_147_483_648, "720000123", None],
)
def test_get_payment_rejects_invalid_requested_order_codes(
    bad_order_code: object,
):
    sdk = _FakeSDK()

    with pytest.raises(
        PayOSPaymentLookupError,
        match=r"^PayOS payment lookup failed$",
    ):
        PayOSClient(sdk).get_payment(bad_order_code)

    assert sdk.payment_requests.get_calls == []


def test_get_payment_maps_sdk_errors_without_leaking_response_data():
    sdk = _FakeSDK()
    sdk.payment_requests.get_error = RuntimeError(
        "secret-account BANK-REF-1 secret-api-key"
    )

    with pytest.raises(
        PayOSPaymentLookupError,
        match=r"^PayOS payment lookup failed$",
    ) as caught:
        PayOSClient(sdk).get_payment(720_000_123)

    assert caught.value.__cause__ is None
    assert "secret" not in repr(caught.value).lower()
    assert "BANK-REF-1" not in str(caught.value)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("orderCode", True),
        ("orderCode", 720_000_124),
        ("amountPaid", True),
        ("amountPaid", "99000"),
        ("amountPaid", -1),
        ("status", True),
    ],
)
def test_get_payment_rejects_malformed_response_fields(
    field: str,
    bad_value: object,
):
    sdk = _FakeSDK()
    response = {
        "orderCode": 720_000_123,
        "amount": 99_000,
        "amountPaid": 99_000,
        "status": "PAID",
        "transactions": [
            {
                "reference": "BANK-REF-1",
                "amount": 99_000,
                "transactionDateTime": "2026-07-29 16:30:00",
            }
        ],
    }
    response[field] = bad_value
    sdk.payment_requests.get_result = response

    with pytest.raises(PayOSPaymentLookupError):
        PayOSClient(sdk).get_payment(720_000_123)


@pytest.mark.parametrize(
    "transactions",
    [
        [],
        [{"reference": "", "transactionDateTime": "2026-07-29 16:30:00"}],
        [{"reference": "BANK-REF-1", "transactionDateTime": "bad-date"}],
        [{"reference": True, "transactionDateTime": "2026-07-29 16:30:00"}],
    ],
)
def test_get_payment_rejects_paid_status_without_safe_transaction(
    transactions: list[dict[str, object]],
):
    sdk = _FakeSDK()
    sdk.payment_requests.get_result = {
        "orderCode": 720_000_123,
        "amount": 99_000,
        "amountPaid": 99_000,
        "status": "PAID",
        "transactions": transactions,
    }

    with pytest.raises(PayOSPaymentLookupError):
        PayOSClient(sdk).get_payment(720_000_123)


def test_default_client_constructs_official_sdk_once_with_bounded_network_policy(
    monkeypatch: pytest.MonkeyPatch,
):
    settings = DigitalProductCommerceSettings(
        sales_enabled=True,
        storage_dir=Path("C:/protected-products"),
        payos_client_id="client-id-placeholder",
        payos_api_key="api-key-placeholder",
        payos_checksum_key="checksum-key-placeholder",
        cookie_secret="c" * 64,
    )
    constructed: list[dict[str, object]] = []

    class _CapturingPayOS(_FakeSDK):
        def __init__(self, **kwargs: object) -> None:
            constructed.append(kwargs)
            super().__init__()

    monkeypatch.setattr(
        payos_client_module,
        "get_digital_product_commerce_settings",
        lambda: settings,
    )
    monkeypatch.setattr(payos_client_module, "_PayOSSDK", _CapturingPayOS)

    client = PayOSClient()

    assert len(constructed) == 1
    assert constructed[0] == {
        "client_id": "client-id-placeholder",
        "api_key": "api-key-placeholder",
        "checksum_key": "checksum-key-placeholder",
        "timeout": 10.0,
        "max_retries": 1,
    }
    assert "placeholder" not in repr(client)


@pytest.mark.parametrize(
    "missing_field",
    ["payos_client_id", "payos_api_key", "payos_checksum_key"],
)
def test_default_client_fails_closed_when_one_sdk_credential_is_missing(
    missing_field: str,
    monkeypatch: pytest.MonkeyPatch,
):
    values = {
        "payos_client_id": "client-id-placeholder",
        "payos_api_key": "api-key-placeholder",
        "payos_checksum_key": "checksum-key-placeholder",
    }
    values[missing_field] = ""
    settings = DigitalProductCommerceSettings(
        sales_enabled=True,
        storage_dir=Path("C:/protected-products"),
        cookie_secret="c" * 64,
        **values,
    )

    class _MustNotConstruct:
        def __init__(self, **kwargs: object) -> None:
            raise AssertionError(f"unexpected SDK construction: {kwargs!r}")

    monkeypatch.setattr(
        payos_client_module,
        "get_digital_product_commerce_settings",
        lambda: settings,
    )
    monkeypatch.setattr(payos_client_module, "_PayOSSDK", _MustNotConstruct)

    with pytest.raises(
        PayOSConfigurationError,
        match=r"^PayOS client configuration failed$",
    ):
        PayOSClient()


def test_default_client_hides_sdk_constructor_errors(
    monkeypatch: pytest.MonkeyPatch,
):
    settings = DigitalProductCommerceSettings(
        sales_enabled=True,
        storage_dir=Path("C:/protected-products"),
        payos_client_id="client-id-placeholder",
        payos_api_key="api-key-placeholder",
        payos_checksum_key="checksum-key-placeholder",
        cookie_secret="c" * 64,
    )

    class _FailingPayOS:
        def __init__(self, **kwargs: object) -> None:
            raise RuntimeError("credential-marker " + repr(kwargs))

    monkeypatch.setattr(
        payos_client_module,
        "get_digital_product_commerce_settings",
        lambda: settings,
    )
    monkeypatch.setattr(payos_client_module, "_PayOSSDK", _FailingPayOS)

    with pytest.raises(
        PayOSConfigurationError,
        match=r"^PayOS client configuration failed$",
    ) as caught:
        PayOSClient()

    assert caught.value.__cause__ is None
    assert "credential-marker" not in repr(caught.value)
    assert "placeholder" not in str(caught.value)


def test_payment_records_are_immutable_non_dataclass_and_not_flask_serializable():
    sdk = _FakeSDK()
    client = PayOSClient(sdk)
    link = client.create_payment_link(_pending_order(), ORDER_URL, ORDER_URL)
    verified = client.verify_webhook(RAW_WEBHOOK)
    status = client.get_payment(720_000_123)
    app = Flask(__name__)

    for record, field_name in [
        (link, "qr_payload"),
        (verified, "reference"),
        (status, "status"),
    ]:
        assert is_dataclass(record) is False
        assert not hasattr(record, "__dict__")
        with pytest.raises(AttributeError):
            setattr(record, field_name, "tampered")
        with pytest.raises(AttributeError):
            object.__setattr__(record, field_name, "tampered")
        with pytest.raises(TypeError):
            asdict(record)
        with app.app_context():
            with pytest.raises(TypeError):
                app.json.dumps(record)
            with pytest.raises(TypeError):
                jsonify(record)


def test_payment_record_repr_omits_sensitive_sdk_and_order_fields():
    sdk = _FakeSDK()
    client = PayOSClient(sdk)
    link = client.create_payment_link(_pending_order(), ORDER_URL, ORDER_URL)
    verified = client.verify_webhook(RAW_WEBHOOK)
    status = client.get_payment(720_000_123)

    rendered = "\n".join([repr(link), repr(verified), repr(status)])

    for sensitive in [
        "720000123",
        "link_0123456789abcdef",
        "pay.payos.vn",
        "000201",
        "BANK-REF-1",
        "secret-account",
        "secret-signature",
    ]:
        assert sensitive not in rendered


def test_exact_payos_110_surface_matches_adapter_contract_without_network():
    assert payos.__version__ == "1.1.0"
    client_parameters = inspect.signature(PayOS).parameters
    assert {"client_id", "api_key", "checksum_key", "timeout", "max_retries"} <= set(
        client_parameters
    )
    create_parameters = inspect.signature(PaymentRequests.create).parameters
    assert "payment_data" in create_parameters
    assert "payload" in inspect.signature(Webhooks.verify).parameters
    assert list(CreatePaymentLinkRequest.model_fields) == [
        "order_code",
        "amount",
        "description",
        "cancel_url",
        "return_url",
        "signature",
        "items",
        "buyer_name",
        "buyer_company_name",
        "buyer_tax_code",
        "buyer_email",
        "buyer_phone",
        "buyer_address",
        "invoice",
        "expired_at",
    ]
    assert {
        "payment_link_id",
        "checkout_url",
        "qr_code",
    } <= set(CreatePaymentLinkResponse.model_fields)
    assert {
        "order_code",
        "amount",
        "reference",
        "transaction_date_time",
        "code",
    } <= set(WebhookData.model_fields)
    assert {
        "order_code",
        "amount_paid",
        "status",
        "transactions",
    } <= set(PaymentLink.model_fields)


def _webhook_payload() -> dict[str, object]:
    return {
        "code": "00",
        "desc": "success",
        "success": True,
        "data": {
            "orderCode": 720_000_123,
            "amount": 99_000,
            "description": "BDBWO3NF",
            "accountNumber": "secret-account",
            "reference": "BANK-REF-1",
            "transactionDateTime": "2026-07-29 16:30:00",
            "currency": "VND",
            "paymentLinkId": "link_0123456789abcdef",
            "code": "00",
            "desc": "success",
            "counterAccountBankId": "",
            "counterAccountBankName": "",
            "counterAccountName": "",
            "counterAccountNumber": "",
            "virtualAccountName": "",
            "virtualAccountNumber": "",
        },
        "signature": "secret-signature",
    }


def _transaction(
    *,
    reference: object,
    amount: object,
    paid_at: object,
) -> Transaction:
    transaction = Transaction(
        reference="SAFE-REFERENCE",
        amount=1,
        account_number="secret-account",
        description="BDBWO3NF",
        transaction_date_time="2026-07-29 16:30:00",
        virtual_account_name=None,
        virtual_account_number=None,
        counter_account_bank_id=None,
        counter_account_bank_name=None,
        counter_account_name=None,
        counter_account_number=None,
    )
    return transaction.model_copy(
        update={
            "reference": reference,
            "amount": amount,
            "transaction_date_time": paid_at,
        }
    )


def _encode_webhook(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")
