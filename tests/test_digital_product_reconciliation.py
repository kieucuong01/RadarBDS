from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from services import digital_product_orders as order_service
from services.digital_product_orders import (
    DigitalProductOrder,
    OrderNotFound,
)
from services.payos_client import PayOSPaymentStatus


FROZEN_NOW = datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)


class InMemoryReconciliationRepository:
    def __init__(self, order: DigitalProductOrder):
        self.order = order
        self.events: set[tuple[int, str, str]] = set()

    @contextmanager
    def transaction(self):
        yield self

    def get_by_public_id(self, public_id, *, for_update=False):
        del for_update
        return self.order if self.order.public_id == public_id else None

    def get_by_order_code(self, order_code, *, for_update=False):
        del for_update
        return self.order if self.order.payos_order_code == order_code else None

    def insert_event_if_absent(
        self,
        *,
        order_id,
        event_type,
        external_reference,
        payload_hash,
        created_at,
    ):
        assert len(payload_hash) == 64
        assert created_at.tzinfo is not None
        key = (order_id, event_type, external_reference)
        if key in self.events:
            return False
        self.events.add(key)
        return True

    def mark_payment_review(self, order_id, *, amount, reference):
        assert self.order.id == order_id
        self.order = self.order.with_updates(
            status="payment_review",
            paid_amount=amount,
            payment_reference=reference,
            paid_at=None,
            download_expires_at=None,
        )
        return self.order

    def mark_paid(
        self,
        order_id,
        *,
        amount,
        reference,
        paid_at,
        download_expires_at,
    ):
        assert self.order.id == order_id
        self.order = self.order.with_updates(
            status="paid",
            paid_amount=amount,
            payment_reference=reference,
            paid_at=paid_at,
            download_expires_at=download_expires_at,
        )
        return self.order

    def mark_expired(self, order_id):
        assert self.order.id == order_id
        self.order = self.order.with_updates(status="expired")
        return self.order

    def mark_last_checked(self, order_id, *, checked_at):
        assert self.order.id == order_id
        self.order = self.order.with_updates(last_checked_at=checked_at)
        return self.order


class FakePayOS:
    def __init__(self, status: PayOSPaymentStatus):
        self.status = status
        self.requested_order_codes: list[int] = []

    def get_payment(self, order_code: int) -> PayOSPaymentStatus:
        self.requested_order_codes.append(order_code)
        return self.status


def make_order(
    *,
    status: str = "pending",
    payment_expires_at: datetime | None = None,
) -> DigitalProductOrder:
    return DigitalProductOrder(
        id=21,
        public_id="0123456789abcdef0123456789abcdef",
        product_slug="thu-dau-mot-map-bundle",
        product_version="1.0",
        expected_amount=99_000,
        currency="VND",
        payos_order_code=720_000_021,
        payment_link_id="pay-link-21",
        checkout_url="https://pay.payos.vn/web/pay-link-21",
        qr_code="0002010102123854",
        status=status,
        recovery_token_hash=hashlib.sha256(b"recovery").hexdigest(),
        paid_amount=None,
        payment_reference=None,
        created_at=FROZEN_NOW - timedelta(minutes=5),
        payment_expires_at=payment_expires_at
        or FROZEN_NOW + timedelta(minutes=10),
        paid_at=None,
        download_expires_at=None,
        download_count=0,
        last_download_at=None,
        last_checked_at=None,
    )


def paid_status(order: DigitalProductOrder, *, amount: int = 99_000):
    return PayOSPaymentStatus(
        order_code=order.payos_order_code,
        status="PAID",
        amount_paid=amount,
        reference="API-REF-1",
        paid_at=FROZEN_NOW,
    )


def test_reconcile_paid_order_uses_shared_settlement_and_records_check():
    order = make_order()
    repo = InMemoryReconciliationRepository(order)
    fake_payos = FakePayOS(paid_status(order))

    result = order_service.reconcile_order(
        order.public_id,
        fake_payos,
        FROZEN_NOW,
        repo=repo,
    )

    assert result.order.status == "paid"
    assert result.order.download_expires_at == FROZEN_NOW + timedelta(hours=24)
    assert result.order.last_checked_at == FROZEN_NOW
    assert result.changed is True
    assert repo.events == {(order.id, "payment_verified", "API-REF-1")}


def test_reconcile_paid_but_underpaid_order_goes_to_payment_review():
    order = make_order()
    repo = InMemoryReconciliationRepository(order)
    fake_payos = FakePayOS(paid_status(order, amount=98_000))

    result = order_service.reconcile_order(
        order.public_id,
        fake_payos,
        FROZEN_NOW,
        repo=repo,
    )

    assert result.order.status == "payment_review"
    assert result.order.paid_amount == 98_000
    assert result.order.download_expires_at is None
    assert result.order.last_checked_at == FROZEN_NOW
    assert repo.events == {(order.id, "payment_underpaid", "API-REF-1")}


def test_reconcile_pending_remote_status_only_records_check():
    order = make_order()
    repo = InMemoryReconciliationRepository(order)
    fake_payos = FakePayOS(
        PayOSPaymentStatus(
            order_code=order.payos_order_code,
            status="PENDING",
            amount_paid=0,
            reference="",
            paid_at=None,
        )
    )

    result = order_service.reconcile_order(
        order.public_id,
        fake_payos,
        FROZEN_NOW,
        repo=repo,
    )

    assert result.order.status == "pending"
    assert result.order.last_checked_at == FROZEN_NOW
    assert result.changed is False
    assert result.reason == "remote_pending"
    assert not repo.events


def test_reconcile_newly_expired_order_still_checks_provider_and_can_settle():
    order = make_order(payment_expires_at=FROZEN_NOW)
    repo = InMemoryReconciliationRepository(order)
    fake_payos = FakePayOS(paid_status(order))

    result = order_service.reconcile_order(
        order.public_id,
        fake_payos,
        FROZEN_NOW,
        repo=repo,
    )

    assert fake_payos.requested_order_codes == [order.payos_order_code]
    assert result.order.status == "paid"
    assert result.order.last_checked_at == FROZEN_NOW


@pytest.mark.parametrize("terminal_status", ["paid", "cancelled", "expired"])
def test_reconcile_does_not_query_terminal_order(terminal_status: str):
    order = make_order(status=terminal_status)
    repo = InMemoryReconciliationRepository(order)
    fake_payos = FakePayOS(paid_status(order))

    result = order_service.reconcile_order(
        order.public_id,
        fake_payos,
        FROZEN_NOW,
        repo=repo,
    )

    assert fake_payos.requested_order_codes == []
    assert result.order is order
    assert result.changed is False
    assert result.reason == f"not_reconcilable_{terminal_status}"


def test_reconcile_missing_order_fails_before_provider_lookup():
    order = make_order()
    repo = InMemoryReconciliationRepository(order)
    fake_payos = FakePayOS(paid_status(order))

    with pytest.raises(OrderNotFound):
        order_service.reconcile_order(
            "ffffffffffffffffffffffffffffffff",
            fake_payos,
            FROZEN_NOW,
            repo=repo,
        )

    assert fake_payos.requested_order_codes == []


def test_reconciliation_cli_prints_only_safe_operational_fields(
    monkeypatch,
    capsys,
):
    from scripts import reconcile_digital_product_order as cli

    order = make_order().with_updates(
        status="paid",
        paid_amount=99_000,
        payment_reference="BANK-SECRET-REFERENCE",
        paid_at=FROZEN_NOW,
        download_expires_at=FROZEN_NOW + timedelta(hours=24),
        last_checked_at=FROZEN_NOW,
        qr_code="SECRET-QR-PAYLOAD",
        recovery_token_hash=hashlib.sha256(b"SECRET-TOKEN").hexdigest(),
    )

    class FakeClient:
        def get_payment(self, order_code):
            return paid_status(order)

    def fake_reconcile(public_id, tracking_client, now):
        assert public_id == order.public_id
        assert now.tzinfo is not None
        tracking_client.get_payment(order.payos_order_code)
        return order_service.SettlementResult(
            order=order,
            changed=True,
            reason="paid",
        )

    monkeypatch.setattr(cli, "PayOSClient", FakeClient)
    monkeypatch.setattr(cli, "reconcile_order", fake_reconcile)

    exit_code = cli.main(["--public-id", order.public_id])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"public_id={order.public_id}" in output
    assert "local_status=paid" in output
    assert "remote_status=PAID" in output
    assert "changed=true" in output
    assert "expiry=2026-07-30T09:30:00+00:00" in output
    assert "SECRET" not in output
    assert "BANK-SECRET-REFERENCE" not in output
    assert order.recovery_token_hash not in output
