"""Reconcile one existing digital-product order with PayOS."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.digital_product_orders import reconcile_order
from services.payos_client import PayOSClient


_PUBLIC_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class _TrackingPayOSClient:
    def __init__(self, client: PayOSClient):
        self._client = client
        self.remote_status = "NOT_QUERIED"

    def get_payment(self, order_code: int):
        payment = self._client.get_payment(order_code)
        self.remote_status = payment.status
        return payment


def _public_id(value: str) -> str:
    if _PUBLIC_ID_PATTERN.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "public ID must be 32 lowercase hexadecimal characters"
        )
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile one Radar BDS digital-product order with PayOS."
    )
    parser.add_argument("--public-id", required=True, type=_public_id)
    args = parser.parse_args(argv)

    try:
        client = _TrackingPayOSClient(PayOSClient())
        result = reconcile_order(
            args.public_id,
            client,
            datetime.now(timezone.utc),
        )
    except Exception as exc:
        print(
            f"public_id={args.public_id} "
            f"reconciliation_failed={type(exc).__name__}",
            file=sys.stderr,
        )
        return 1

    expiry = result.order.download_expires_at or result.order.payment_expires_at
    expiry_text = expiry.isoformat() if expiry is not None else "none"
    print(
        f"public_id={result.order.public_id} "
        f"local_status={result.order.status} "
        f"remote_status={client.remote_status} "
        f"changed={str(result.changed).lower()} "
        f"expiry={expiry_text}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
