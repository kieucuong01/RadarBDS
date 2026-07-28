# Thu Dau Mot PayOS Commerce Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sell the validated Thu Dau Mot map bundle for exactly 99,000 VND through PayOS VietQR, then grant an anonymous buyer a protected 24-hour download without collecting email, phone, or account data.

**Architecture:** PostgreSQL stores immutable order terms and an append-only event trail. A thin PayOS adapter creates and verifies payment requests, while one idempotent settlement function is shared by webhook handling and explicit reconciliation. A high-entropy recovery token travels only in the URL fragment, is exchanged once for a signed HttpOnly order-scoped cookie, and never appears in query strings, analytics, or application logs.

**Tech Stack:** Flask 3.1.3, PostgreSQL via psycopg 3.2.10, PayOS Python SDK 1.1.0, qrcode 8.2, itsdangerous through Flask, vanilla JavaScript, pytest 8.4.2

## Global Constraints

- Server-side product price is fixed at exactly `99000` VND; browser input never sets price, slug, or version.
- PayOS payment links expire 15 minutes after creation.
- Download access expires exactly 24 hours after confirmed payment.
- The checkout collects no account, email, or phone number.
- The recovery URL is `/ban-do-thu-dau-mot/don-hang/<public_id>#token=<recovery_token>`; the token must never be placed in a query string.
- PostgreSQL stores only the SHA-256 hash of the recovery token.
- The PayOS return/cancel redirect never proves payment.
- Settlement accepts only a verified order whose paid amount is at least the immutable expected amount; underpayment becomes `payment_review`.
- Webhook delivery, retries, and reconciliation are idempotent.
- The paid ZIP is stored outside `static/`, outside the Git repository, and outside the release directory replaced by deployment.
- `DIGITAL_PRODUCT_SALES_ENABLED` defaults to `0`; checkout remains disabled until the exact ZIP and manifest pass the release validator.
- Automated tests mock PayOS and never create a real transaction.
- PayOS has no separate sandbox; the production payment proof is a deliberate manual gate after deployment.
- No recovery token, cookie, raw order code, PayOS signature, bank reference, or transfer content is sent to analytics.
- Do not add refund automation, customer accounts, an admin order UI, a cart, coupons, invoices, or additional digital products in this release.

---

## Planned File Structure

- Modify `requirements.txt` — pin the PayOS SDK and QR encoder used at runtime.
- Modify `.env.example` — document non-secret runtime variable names and safe defaults.
- Modify `config/settings.py` — parse and validate commerce configuration.
- Modify `db/schema.py` — create order/event tables and forward-only migrations.
- Modify `db/connection.py` — return generated IDs for the two new tables.
- Create `services/digital_product_orders.py` — order lifecycle, token hashing, settlement, expiry, and reconciliation.
- Create `services/payos_client.py` — typed wrapper around PayOS create/get/webhook operations.
- Modify `services/digital_products.py` — resolve the protected ZIP and fail closed when availability changes.
- Modify `routes/digital_products.py` — checkout, order page, authorization, status, webhook, and download endpoints.
- Modify `routes/__init__.py` — register the digital-products blueprint exactly once.
- Modify `templates/thu_dau_mot_map_product.html` — enable the purchase form only when the server says the product is sellable.
- Create `templates/thu_dau_mot_map_order.html` — anonymous VietQR/order/download state page.
- Create `static/js/thu_dau_mot_map_checkout.js` — fragment exchange, QR display, countdown, polling, and recovery-link copy.
- Modify `static/css/thu_dau_mot_map_product.css` — responsive checkout/order states and 44 px controls.
- Modify `app.py` — tracking allowlist and response-header integration only.
- Create `scripts/reconcile_digital_product_order.py` — explicit production reconciliation command.
- Modify `docs/operations.md` — protected storage, environment, webhook, enable/disable, and recovery runbook.
- Modify `deployment/ubuntu24/README.md` — persistent directory and systemd environment checklist.
- Create `tests/test_digital_product_order_schema.py` — schema and migration contracts.
- Create `tests/test_digital_product_orders.py` — pure order lifecycle and idempotency tests.
- Create `tests/test_payos_client.py` — mocked SDK adapter and webhook verification tests.
- Create `tests/test_digital_product_checkout.py` — route/security/download integration tests.
- Create `tests/test_thu_dau_mot_map_checkout_js.py` — static JS contract and privacy assertions.
- Modify `tests/test_thu_dau_mot_map_product_page.py` — sales-gate and Product Offer assertions.

---

### Task 1: Add Runtime Configuration and Durable Order Schema

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `config/settings.py`
- Modify: `db/schema.py:1-760`
- Modify: `db/connection.py:34-55`
- Create: `tests/test_digital_product_order_schema.py`

**Interfaces:**
- Produces: `DigitalProductCommerceSettings`
- Produces: `get_digital_product_commerce_settings() -> DigitalProductCommerceSettings`
- Produces PostgreSQL tables `digital_product_orders` and `digital_product_order_events`.
- Later tasks rely on `digital_product_orders.id` and `digital_product_order_events.id` being returned by the existing DB adapter.

- [ ] **Step 1: Pin runtime dependencies and write the failing settings tests**

Add these exact lines to `requirements.txt`:

```text
payos==1.1.0
qrcode==8.2
```

Create tests:

```python
def test_commerce_settings_default_to_sales_disabled(monkeypatch):
    for key in (
        "PAYOS_CLIENT_ID",
        "PAYOS_API_KEY",
        "PAYOS_CHECKSUM_KEY",
        "DIGITAL_PRODUCT_COOKIE_SECRET",
        "DIGITAL_PRODUCT_STORAGE_DIR",
        "DIGITAL_PRODUCT_SALES_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = get_digital_product_commerce_settings()
    assert settings.sales_enabled is False
    assert settings.ready_for_checkout is False


def test_enabled_sales_require_all_secrets_and_absolute_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("DIGITAL_PRODUCT_SALES_ENABLED", "1")
    monkeypatch.setenv("DIGITAL_PRODUCT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("PAYOS_CLIENT_ID", "client")
    monkeypatch.setenv("PAYOS_API_KEY", "api")
    monkeypatch.setenv("PAYOS_CHECKSUM_KEY", "checksum")
    monkeypatch.setenv("DIGITAL_PRODUCT_COOKIE_SECRET", "x" * 64)
    assert get_digital_product_commerce_settings().ready_for_checkout is True
```

- [ ] **Step 2: Run settings tests and confirm RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_digital_product_order_schema.py -q
```

Expected: import failure for `DigitalProductCommerceSettings`.

- [ ] **Step 3: Implement typed, fail-closed configuration**

Add:

```python
@dataclass(frozen=True)
class DigitalProductCommerceSettings:
    sales_enabled: bool
    storage_dir: Path | None
    payos_client_id: str
    payos_api_key: str
    payos_checksum_key: str
    cookie_secret: str

    @property
    def ready_for_checkout(self) -> bool:
        return bool(
            self.sales_enabled
            and self.storage_dir
            and self.storage_dir.is_absolute()
            and self.payos_client_id
            and self.payos_api_key
            and self.payos_checksum_key
            and len(self.cookie_secret) >= 64
        )
```

`get_digital_product_commerce_settings()` trims values, accepts `1/true/yes/on`
for the sales flag, and never logs values. Add variable names to `.env.example`
with `DIGITAL_PRODUCT_SALES_ENABLED=0` and an example Linux storage path
`/var/lib/radar-bds/products`.

- [ ] **Step 4: Write failing schema assertions**

```python
def test_order_schema_contains_security_and_expiry_fields(schema_sql):
    for column in (
        "public_id",
        "recovery_token_hash",
        "expected_amount",
        "payos_order_code",
        "payment_expires_at",
        "download_expires_at",
        "download_count",
    ):
        assert column in schema_sql
    assert "email" not in order_table_sql(schema_sql)
    assert "phone" not in order_table_sql(schema_sql)


def test_order_status_constraint_is_closed(schema_sql):
    assert "'pending'" in schema_sql
    assert "'paid'" in schema_sql
    assert "'expired'" in schema_sql
    assert "'cancelled'" in schema_sql
    assert "'payment_review'" in schema_sql
```

- [ ] **Step 5: Add the two tables and indexes**

Use PostgreSQL DDL:

```sql
CREATE TABLE IF NOT EXISTS digital_product_orders (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    product_slug TEXT NOT NULL,
    product_version TEXT NOT NULL,
    expected_amount INTEGER NOT NULL CHECK (expected_amount > 0),
    currency TEXT NOT NULL DEFAULT 'VND' CHECK (currency = 'VND'),
    payos_order_code BIGINT NOT NULL UNIQUE,
    payment_link_id TEXT UNIQUE,
    checkout_url TEXT,
    qr_code TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'paid', 'expired', 'cancelled', 'payment_review')),
    recovery_token_hash TEXT,
    paid_amount INTEGER,
    payment_reference TEXT,
    status_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    payment_expires_at TIMESTAMPTZ NOT NULL,
    paid_at TIMESTAMPTZ,
    download_expires_at TIMESTAMPTZ,
    download_count INTEGER NOT NULL DEFAULT 0 CHECK (download_count >= 0),
    last_download_at TIMESTAMPTZ,
    last_checked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_digital_product_orders_status_expiry
ON digital_product_orders(status, payment_expires_at);

CREATE TABLE IF NOT EXISTS digital_product_order_events (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES digital_product_orders(id),
    event_type TEXT NOT NULL,
    external_reference TEXT NOT NULL DEFAULT '',
    payload_hash TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(order_id, event_type, external_reference)
);
```

Add forward-only `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements in
`_run_migrations()` for installations that partially created the table. Add
both table names to `ID_TABLES`.

- [ ] **Step 6: Verify schema and commit**

```powershell
& $py -X utf8 -m py_compile config\settings.py db\schema.py db\connection.py
& $py -X utf8 -m pytest tests\test_digital_product_order_schema.py -q
git diff --check
git add requirements.txt .env.example config/settings.py db/schema.py db/connection.py tests/test_digital_product_order_schema.py
git commit -m "feat: add digital product order schema"
```

---

### Task 2: Implement Order Lifecycle, Recovery Tokens, and Settlement

**Files:**
- Create: `services/digital_product_orders.py`
- Create: `tests/test_digital_product_orders.py`

**Interfaces:**
- Consumes: `DigitalProduct` from `services.digital_products`.
- Produces: `PendingOrderSecret`, `DigitalProductOrder`, `SettlementResult`.
- Produces: `create_pending_order(product: DigitalProduct, now: datetime) -> DigitalProductOrder`
- Produces: `attach_payment_link(public_id: str, payment_link: PayOSPaymentLink) -> PendingOrderSecret`
- Produces: `verify_recovery_token(public_id: str, raw_token: str) -> DigitalProductOrder | None`
- Produces: `get_order(public_id: str) -> DigitalProductOrder | None`
- Produces: `settle_verified_payment(order_code: int, amount: int, reference: str, paid_at: datetime, payload_hash: str) -> SettlementResult`
- Produces: `expire_pending_order(public_id: str, now: datetime) -> DigitalProductOrder`
- Produces: `record_download(order_id: int, now: datetime) -> None`

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_pending_order_uses_server_product_terms(product, frozen_now, order_repo):
    order = create_pending_order(product, frozen_now, repo=order_repo)
    assert order.expected_amount == 99000
    assert order.product_slug == "thu-dau-mot-map-bundle"
    assert order.product_version == "1.0"
    assert order.payment_expires_at == frozen_now + timedelta(minutes=15)
    assert order.recovery_token_hash is None


def test_attaching_link_returns_secret_but_persists_only_hash(pending_order, payment_link, order_repo):
    result = attach_payment_link(
        pending_order.public_id,
        payment_link,
        repo=order_repo,
    )
    assert len(result.raw_recovery_token) >= 43
    assert result.order.recovery_token_hash
    assert result.raw_recovery_token not in order_repo.serialized_rows()


def test_exact_payment_settles_once_and_opens_24_hours(pending_order, frozen_now, order_repo):
    first = settle_verified_payment(
        pending_order.payos_order_code,
        99000,
        "BANK-REF-1",
        frozen_now,
        "sha256-payload",
        repo=order_repo,
    )
    second = settle_verified_payment(
        pending_order.payos_order_code,
        99000,
        "BANK-REF-1",
        frozen_now,
        "sha256-payload",
        repo=order_repo,
    )
    assert first.changed is True
    assert second.changed is False
    assert first.order.download_expires_at == frozen_now + timedelta(hours=24)


def test_underpayment_never_grants_download(pending_order, frozen_now, order_repo):
    result = settle_verified_payment(
        pending_order.payos_order_code,
        98000,
        "BANK-REF-2",
        frozen_now,
        "sha256-underpaid",
        repo=order_repo,
    )
    assert result.order.status == "payment_review"
    assert result.order.download_expires_at is None
```

- [ ] **Step 2: Run lifecycle tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_digital_product_orders.py -q
```

- [ ] **Step 3: Define immutable records and token rules**

```python
@dataclass(frozen=True)
class PendingOrderSecret:
    order: DigitalProductOrder
    raw_recovery_token: str


@dataclass(frozen=True)
class DigitalProductOrder:
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


@dataclass(frozen=True)
class SettlementResult:
    order: DigitalProductOrder
    changed: bool
    reason: str
```

Generate `public_id` with `uuid.uuid4().hex`. `create_pending_order` leaves
`recovery_token_hash` null because a failed PayOS request must not strand an
unrecoverable token. `attach_payment_link` generates the token with
`secrets.token_urlsafe(32)`, stores
`sha256(raw_token.encode("utf-8")).hexdigest()`, and returns the raw token once.
Calling it again for the same still-pending order reuses the PayOS link but
rotates the recovery token and its hash. Compare hashes using
`hmac.compare_digest`.

Generate PayOS order codes as `720000000 + order.id`; reject an ID that would
produce a value above `2147483647`. Insert the order and assign the order code
inside one transaction.

- [ ] **Step 4: Implement atomic, idempotent settlement**

Lock by PayOS order code:

```sql
SELECT * FROM digital_product_orders
WHERE payos_order_code = ?
FOR UPDATE
```

Rules:

- missing order: return a typed `SettlementNotFound` error;
- `amount < expected_amount`: set `payment_review`, do not set a download expiry;
- first valid payment: set `paid`, `paid_amount`, `paid_at`, and
  `download_expires_at = paid_at + interval '24 hours'`;
- already paid: leave `paid_at` and expiry unchanged;
- duplicate `(order_id, event_type, external_reference)`: no second mutation;
- store only SHA-256 of the verified webhook payload, never its body.

- [ ] **Step 5: Add expiry and download eligibility tests**

```python
@pytest.mark.parametrize(
    ("status", "seconds_after_expiry", "allowed"),
    [("pending", -1, False), ("paid", -1, True), ("paid", 1, False), ("payment_review", -1, False)],
)
def test_can_download_requires_paid_and_unexpired(order_factory, status, seconds_after_expiry, allowed):
    order = order_factory(status=status)
    now = order.download_expires_at + timedelta(seconds=seconds_after_expiry)
    assert can_download(order, now) is allowed
```

`expire_pending_order` may only change `pending` to `expired` after
`payment_expires_at`; it must not expire a paid order.

- [ ] **Step 6: Verify and commit**

```powershell
& $py -X utf8 -m py_compile services\digital_product_orders.py
& $py -X utf8 -m pytest tests\test_digital_product_orders.py -q
git diff --check
git add services/digital_product_orders.py tests/test_digital_product_orders.py
git commit -m "feat: add digital product order lifecycle"
```

---

### Task 3: Wrap PayOS Creation, Verification, and Status Lookups

**Files:**
- Create: `services/payos_client.py`
- Create: `tests/test_payos_client.py`

**Interfaces:**
- Consumes: `DigitalProductOrder`.
- Produces: `PayOSPaymentLink`, `VerifiedPayOSPayment`, `PayOSPaymentStatus`.
- Produces: `PayOSClient.create_payment_link(order, return_url: str, cancel_url: str) -> PayOSPaymentLink`
- Produces: `PayOSClient.verify_webhook(raw_body: bytes) -> VerifiedPayOSPayment`
- Produces: `PayOSClient.get_payment(order_code: int) -> PayOSPaymentStatus`

- [ ] **Step 1: Write mocked SDK contract tests**

```python
def test_create_link_uses_server_amount_and_15_minute_expiry(fake_sdk, pending_order):
    client = PayOSClient(fake_sdk)
    link = client.create_payment_link(
        pending_order,
        "https://radarbds.vn/ban-do-thu-dau-mot/don-hang/public",
        "https://radarbds.vn/ban-do-thu-dau-mot/don-hang/public",
    )
    request = fake_sdk.payment_requests.created[0]
    assert request.amount == 99000
    assert request.order_code == pending_order.payos_order_code
    assert request.expired_at == int(pending_order.payment_expires_at.timestamp())
    assert link.qr_payload == "000201..."


def test_verify_webhook_uses_raw_body_and_maps_verified_data(fake_sdk):
    client = PayOSClient(fake_sdk)
    payment = client.verify_webhook(b'{"code":"00","data":{},"signature":"signed"}')
    assert fake_sdk.webhooks.raw_inputs == [b'{"code":"00","data":{},"signature":"signed"}']
    assert payment.order_code == 720000123
    assert payment.amount == 99000
```

- [ ] **Step 2: Run adapter tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_payos_client.py -q
```

- [ ] **Step 3: Implement typed mappings around SDK 1.1.0**

```python
@dataclass(frozen=True)
class PayOSPaymentLink:
    payment_link_id: str
    checkout_url: str
    qr_payload: str


@dataclass(frozen=True)
class VerifiedPayOSPayment:
    order_code: int
    amount: int
    reference: str
    paid_at: datetime
    success: bool
    payload_hash: str


@dataclass(frozen=True)
class PayOSPaymentStatus:
    order_code: int
    status: Literal["PENDING", "PAID", "CANCELLED", "EXPIRED", "UNKNOWN"]
    amount_paid: int
    reference: str
    paid_at: datetime | None
```

Construct the SDK once from environment-backed settings. The payment
description is ASCII and no more than nine characters: `BD{order_code}`.
Return and cancel URLs contain only `public_id`; they never contain the
recovery token.

- [ ] **Step 4: Fail closed on malformed or unverified webhook data**

Map SDK signature errors, absent order codes, non-integer amounts, and
unsuccessful events to `PayOSWebhookRejected`. Hash the raw body before parsing,
but never log or persist the raw bytes. Do not catch the rejection in a way that
returns a success acknowledgement.

- [ ] **Step 5: Verify and commit**

```powershell
& $py -X utf8 -m py_compile services\payos_client.py
& $py -X utf8 -m pytest tests\test_payos_client.py -q
git diff --check
git add services/payos_client.py tests/test_payos_client.py
git commit -m "feat: add PayOS digital product client"
```

---

### Task 4: Add Anonymous Checkout, Fragment Authorization, and Webhook Routes

**Files:**
- Modify: `services/digital_products.py`
- Modify: `routes/digital_products.py`
- Modify: `routes/__init__.py`
- Modify: `app.py:1329-1360`
- Modify: `templates/thu_dau_mot_map_product.html`
- Create: `templates/thu_dau_mot_map_order.html`
- Create: `tests/test_digital_product_checkout.py`

**Interfaces:**
- Consumes all Task 1-3 interfaces.
- Produces: `POST /ban-do-thu-dau-mot/checkout`
- Produces: `GET /ban-do-thu-dau-mot/don-hang/<public_id>`
- Produces: `POST /api/digital-products/orders/<public_id>/authorize`
- Produces: `GET /api/digital-products/orders/<public_id>/status`
- Produces: `POST /api/webhooks/payos/digital-products`
- Produces: signed cookie `radar_product_order`.

- [ ] **Step 1: Write failing route and security tests**

```python
def test_checkout_is_unavailable_until_package_and_sales_gate_pass(client):
    response = client.post("/ban-do-thu-dau-mot/checkout")
    assert response.status_code == 503
    assert response.get_json()["code"] == "product_unavailable"


def test_checkout_redirect_uses_fragment_token(client, sellable_product, fake_payos):
    response = client.post("/ban-do-thu-dau-mot/checkout")
    assert response.status_code == 303
    location = response.headers["Location"]
    assert "/ban-do-thu-dau-mot/don-hang/" in location
    assert "#token=" in location
    assert "?token=" not in location


def test_return_page_without_cookie_does_not_expose_order(client, pending_order):
    response = client.get(f"/ban-do-thu-dau-mot/don-hang/{pending_order.public_id}")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert pending_order.qr_code not in html
    assert pending_order.payos_order_code.__str__() not in html
```

- [ ] **Step 2: Run route tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_digital_product_checkout.py -q
```

- [ ] **Step 3: Implement checkout with a hard availability gate**

Order of operations:

1. load the immutable product registry entry;
2. require `settings.ready_for_checkout`;
3. require `get_release_availability(...).can_sell`;
4. create or recover one pending order through a five-minute signed retry cookie;
5. create the PayOS link;
6. attach/reuse link metadata and rotate a recovery token;
7. return `303` to
   `/ban-do-thu-dau-mot/don-hang/<public_id>#token=<urlencoded-token>`.

If PayOS fails before a link is attached, mark the order event
`payment_link_failed` and return a generic retry message. A retry key stored in
a signed, HttpOnly, SameSite=Lax, five-minute cookie contains only `public_id`
and prevents a double-click from creating another order. A retry reuses the
pending order and existing link, then rotates the recovery token before
redirecting. Clear the retry cookie after the redirect response is built.

Apply:

```python
@rate_limit("digital_product_checkout", limits={"guest": 10, "free": 10, "vip": 10, "admin": 30})
```

- [ ] **Step 4: Implement one-time fragment authorization**

Use:

```python
serializer = URLSafeTimedSerializer(
    settings.cookie_secret,
    salt="radar-digital-product-order-v1",
)
```

`POST /api/digital-products/orders/<public_id>/authorize` accepts only JSON
`{"token": "<raw-token>"}`. On a constant-time match it sets:

```python
response.set_cookie(
    "radar_product_order",
    serializer.dumps({"public_id": public_id}),
    max_age=90000,
    httponly=True,
    secure=public_base_url.startswith("https://"),
    samesite="Lax",
    path=f"/api/digital-products/orders/{public_id}",
)
```

The server never echoes the raw token. Invalid token and unknown order both
return the same `404 {"code": "order_not_found"}` response. Authorization is
also rejected when a pending order is past `payment_expires_at` or a paid order
is past `download_expires_at`; the 25-hour cookie ceiling never extends the
server-side 24-hour download right.

Apply a 30/hour guest rate limit.

- [ ] **Step 5: Implement cookie-authorized status**

Status JSON contains only:

```json
{
  "status": "pending",
  "amount_vnd": 99000,
  "payment_expires_at": "ISO-8601",
  "download_expires_at": null,
  "qr_svg_data_uri": "data:image/svg+xml;base64,...",
  "order_label": "BD720000123",
  "download_url": null
}
```

Generate the QR SVG server-side from PayOS `qr_code` using qrcode's SVG image
factory. Never return PayOS raw transfer content separately. Before responding,
expire stale pending orders; polling never marks an order paid. Apply a
240/hour guest rate limit and `Cache-Control: private, no-store`.

- [ ] **Step 6: Implement the verified webhook**

Read `request.get_data(cache=False)` once. Call
`PayOSClient.verify_webhook(raw_body)`, then
`settle_verified_payment(...)`. A verified duplicate returns HTTP 200 with
`{"success": true}`. A signature or data rejection returns HTTP 400. An unknown
order returns HTTP 404 and creates no row. Do not apply the browser/session rate
limiter to PayOS; signature verification is the boundary.

- [ ] **Step 7: Add route hardening assertions**

```python
def test_authorize_sets_scoped_http_only_cookie_and_never_echoes_token(client, pending_order):
    token = pending_order.raw_recovery_token
    response = client.post(
        f"/api/digital-products/orders/{pending_order.public_id}/authorize",
        json={"token": token},
    )
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert f"Path=/api/digital-products/orders/{pending_order.public_id}" in cookie
    assert token not in response.get_data(as_text=True)


def test_redirect_and_cancel_never_set_paid(client, pending_order):
    client.get(f"/ban-do-thu-dau-mot/don-hang/{pending_order.public_id}?status=success")
    assert load_order(pending_order.public_id).status == "pending"


def test_verified_underpayment_is_review_not_paid(client, payos_webhook, pending_order):
    response = client.post(
        "/api/webhooks/payos/digital-products",
        data=payos_webhook(amount=98000),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert load_order(pending_order.public_id).status == "payment_review"
```

- [ ] **Step 8: Verify and commit**

```powershell
& $py -X utf8 -m py_compile app.py routes\digital_products.py services\digital_products.py
& $py -X utf8 -m pytest tests\test_digital_product_checkout.py tests\test_digital_product_orders.py tests\test_payos_client.py -q
git diff --check
git add services/digital_products.py routes/digital_products.py routes/__init__.py app.py templates/thu_dau_mot_map_product.html templates/thu_dau_mot_map_order.html tests/test_digital_product_checkout.py
git commit -m "feat: add anonymous PayOS map checkout"
```

---

### Task 5: Add Protected Download Streaming

**Files:**
- Modify: `services/digital_products.py`
- Modify: `services/digital_product_orders.py`
- Modify: `routes/digital_products.py`
- Modify: `tests/test_digital_product_checkout.py`

**Interfaces:**
- Consumes: signed order cookie and `can_download(order, now)`.
- Produces: `resolve_protected_package(product, storage_root: Path) -> Path`
- Produces: `GET /api/digital-products/orders/<public_id>/download`

- [ ] **Step 1: Write failing download tests**

```python
def test_paid_order_downloads_exact_validated_zip(client, paid_order, protected_release):
    authorize(client, paid_order)
    response = client.get(f"/api/digital-products/orders/{paid_order.public_id}/download")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/zip"
    assert "attachment;" in response.headers["Content-Disposition"]
    assert response.data == protected_release.zip_bytes


@pytest.mark.parametrize("case", ("no_cookie", "pending", "expired", "wrong_order_cookie"))
def test_download_is_denied_without_current_paid_authorization(client, order_case, case):
    response = request_download_for_case(client, order_case, case)
    assert response.status_code in (403, 410)


def test_missing_package_after_payment_never_streams_partial_file(client, paid_order):
    authorize(client, paid_order)
    response = client.get(f"/api/digital-products/orders/{paid_order.public_id}/download")
    assert response.status_code == 503
    assert response.get_json()["code"] == "download_temporarily_unavailable"
```

- [ ] **Step 2: Run download tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_digital_product_checkout.py -k download -q
```

- [ ] **Step 3: Resolve only the immutable package version**

The package path is:

```text
<DIGITAL_PRODUCT_STORAGE_DIR>/thu-dau-mot-map-bundle/1.0/radarbds-thu-dau-mot-map-v1.0.zip
```

`resolve_protected_package` must:

- resolve the storage root and candidate to absolute paths;
- require `candidate.is_relative_to(storage_root)`;
- require the file name from `DigitalProduct.package_filename`;
- verify size and SHA-256 against the sibling release manifest;
- reject symlinks;
- never accept a request path or filename from the browser.

- [ ] **Step 4: Stream only after authorization, payment, and expiry checks**

Use Flask `send_file` with:

```python
send_file(
    package_path,
    mimetype="application/zip",
    as_attachment=True,
    download_name=product.download_filename,
    conditional=True,
    etag=package_sha256,
    max_age=0,
)
```

Set `Cache-Control: private, no-store` and `X-Content-Type-Options: nosniff`.
Increment `download_count` and `last_download_at` only after the response is
successfully constructed. Apply a 30/hour guest rate limit.

- [ ] **Step 5: Verify and commit**

```powershell
& $py -X utf8 -m pytest tests\test_digital_product_checkout.py -k "download or authorize" -q
& $py -X utf8 -m py_compile services\digital_products.py services\digital_product_orders.py routes\digital_products.py
git diff --check
git add services/digital_products.py services/digital_product_orders.py routes/digital_products.py tests/test_digital_product_checkout.py
git commit -m "feat: protect Thu Dau Mot map downloads"
```

---

### Task 6: Build the VietQR and 24-Hour Download UX

**Files:**
- Modify: `templates/thu_dau_mot_map_product.html`
- Modify: `templates/thu_dau_mot_map_order.html`
- Create: `static/js/thu_dau_mot_map_checkout.js`
- Modify: `static/css/thu_dau_mot_map_product.css`
- Modify: `app.py:1329-1360`
- Create: `tests/test_thu_dau_mot_map_checkout_js.py`
- Modify: `tests/test_thu_dau_mot_map_product_page.py`

**Interfaces:**
- Consumes authorize/status/download routes from Tasks 4-5.
- Produces browser functions `readRecoveryToken`, `authorizeOrder`,
  `pollOrder`, `renderOrderState`, and `copyRecoveryLink`.

- [ ] **Step 1: Write failing static privacy and behavior tests**

```python
def test_checkout_js_reads_fragment_then_clears_it(js_source):
    assert "window.location.hash" in js_source
    assert "history.replaceState" in js_source
    assert "?token=" not in js_source
    assert "localStorage" not in js_source


def test_order_template_has_accessible_live_region(client):
    html = client.get("/ban-do-thu-dau-mot/don-hang/public-id").get_data(as_text=True)
    assert 'aria-live="polite"' in html
    assert 'data-order-qr' in html
    assert 'data-order-download' in html


def test_tracking_context_excludes_order_identifiers(app_source, js_source):
    forbidden = ("recovery_token", "raw_order_code", "payment_reference", "payos_signature")
    assert all(name not in js_source for name in forbidden)
```

- [ ] **Step 2: Run UI contract tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_thu_dau_mot_map_checkout_js.py tests\test_thu_dau_mot_map_product_page.py -q
```

- [ ] **Step 3: Implement fragment exchange before analytics**

On the order page, load the checkout module before the common tracking partial.
The module:

1. reads `token` from `new URLSearchParams(location.hash.slice(1))`;
2. stores the full recovery URL in `sessionStorage` only for the current tab;
3. POSTs the token in a JSON body;
4. immediately calls `history.replaceState(null, "", location.pathname)`;
5. starts status polling only after authorization succeeds;
6. loads common analytics only after the fragment has been cleared.

Do not use `localStorage`, cookies readable by JavaScript, or DOM attributes to
retain the token.

- [ ] **Step 4: Implement the state renderer**

Render:

- `pending`: VietQR SVG, `99.000đ`, order label, 15-minute countdown, and copy
  recovery-link button;
- `paid`: success message, download button, and exact 24-hour expiry;
- `expired`: expired message and link to create a new order;
- `cancelled`: cancelled message and new-order link;
- `payment_review`: support message with public ID only.

Poll at 2 seconds for the first minute, then 5 seconds until the payment
deadline. Stop on any terminal state or when the document has been hidden for
five minutes; resume on `visibilitychange`.

- [ ] **Step 5: Implement responsive and accessible styles**

At 375 px the QR is at most `min(78vw, 296px)`. All buttons and links used as
controls have a minimum block size of 44 px. Focus is visible, status is
announced through one `aria-live="polite"` region, and motion is disabled under
`prefers-reduced-motion`.

- [ ] **Step 6: Add privacy-safe tracking**

Allowlist:

- `thu_dau_mot_map_checkout_created`
- `thu_dau_mot_map_qr_displayed`
- `thu_dau_mot_map_payment_confirmed`
- `thu_dau_mot_map_download_clicked`

Context contains only `product_slug`, `product_version`, `amount_vnd`, and
coarse `order_status`. Page-view tracking for the order page is disabled.

- [ ] **Step 7: Verify JS and commit**

```powershell
node --check static\js\thu_dau_mot_map_checkout.js
& $py -X utf8 -m pytest tests\test_thu_dau_mot_map_checkout_js.py tests\test_thu_dau_mot_map_product_page.py tests\test_digital_product_checkout.py -q
git diff --check
git add templates/thu_dau_mot_map_product.html templates/thu_dau_mot_map_order.html static/js/thu_dau_mot_map_checkout.js static/css/thu_dau_mot_map_product.css app.py tests/test_thu_dau_mot_map_checkout_js.py tests/test_thu_dau_mot_map_product_page.py
git commit -m "feat: add VietQR map checkout experience"
```

---

### Task 7: Add Reconciliation and Production Runbooks

**Files:**
- Modify: `services/digital_product_orders.py`
- Create: `scripts/reconcile_digital_product_order.py`
- Create: `tests/test_digital_product_reconciliation.py`
- Modify: `docs/operations.md`
- Modify: `deployment/ubuntu24/README.md`

**Interfaces:**
- Consumes: `PayOSClient.get_payment` and `settle_verified_payment`.
- Produces: `reconcile_order(public_id: str, payos_client: PayOSClient, now: datetime) -> SettlementResult`
- Produces CLI:
  `python scripts/reconcile_digital_product_order.py --public-id <public_id>`

- [ ] **Step 1: Write failing reconciliation tests**

```python
def test_reconcile_paid_order_uses_shared_settlement(pending_order, fake_payos, order_repo):
    fake_payos.status = PayOSPaymentStatus(
        order_code=pending_order.payos_order_code,
        status="PAID",
        amount_paid=99000,
        reference="API-REF-1",
        paid_at=FROZEN_NOW,
    )
    result = reconcile_order(pending_order.public_id, fake_payos, FROZEN_NOW, repo=order_repo)
    assert result.order.status == "paid"
    assert result.order.download_expires_at == FROZEN_NOW + timedelta(hours=24)


def test_reconcile_does_not_trust_pending_or_underpaid_status(pending_order, fake_payos, order_repo):
    fake_payos.status = replace(fake_payos.status, status="PAID", amount_paid=98000)
    result = reconcile_order(pending_order.public_id, fake_payos, FROZEN_NOW, repo=order_repo)
    assert result.order.status == "payment_review"
```

- [ ] **Step 2: Run reconciliation tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_digital_product_reconciliation.py -q
```

- [ ] **Step 3: Implement reconciliation through the settlement seam**

Only query PayOS for an existing `pending`, `payment_review`, or newly expired
order. A PayOS `PAID` response calls `settle_verified_payment`; no other path
sets `paid`. Record `last_checked_at`. The CLI prints public ID, local status,
remote status, changed flag, and expiry; it never prints QR content, tokens,
signatures, credentials, or bank transfer payloads.

- [ ] **Step 4: Document exact production setup**

Add the protected directory:

```text
/var/lib/radar-bds/products/thu-dau-mot-map-bundle/1.0/
```

Document:

1. copy the validated ZIP and manifest as the service user;
2. set owner to the application service account and mode `0750` directory,
   `0640` files;
3. set `PAYOS_CLIENT_ID`, `PAYOS_API_KEY`, `PAYOS_CHECKSUM_KEY`,
   `DIGITAL_PRODUCT_COOKIE_SECRET`, and `DIGITAL_PRODUCT_STORAGE_DIR`;
4. keep `DIGITAL_PRODUCT_SALES_ENABLED=0`;
5. run `from db.schema import init_schema; init_schema()`;
6. restart the service and verify product page shows `Sắp mở bán`;
7. register and confirm
   `https://radarbds.vn/api/webhooks/payos/digital-products` in PayOS;
8. run release validation against the protected copy;
9. set `DIGITAL_PRODUCT_SALES_ENABLED=1` and restart;
10. run one deliberate 99,000 VND payment, download once, and verify the order,
    event, and expiry;
11. if proof fails, immediately set the sales flag back to `0` without deleting
    the paid order or package.

- [ ] **Step 5: Verify and commit**

```powershell
& $py -X utf8 -m pytest tests\test_digital_product_reconciliation.py tests\test_digital_product_orders.py tests\test_payos_client.py -q
& $py -X utf8 -m py_compile scripts\reconcile_digital_product_order.py services\digital_product_orders.py
git diff --check
git add services/digital_product_orders.py scripts/reconcile_digital_product_order.py tests/test_digital_product_reconciliation.py docs/operations.md deployment/ubuntu24/README.md
git commit -m "ops: add digital product reconciliation"
```

---

### Task 8: Run the Release Gate and Enable Sales Deliberately

**Files:**
- Modify only files whose verification exposes a defect.
- Runtime-only: protected ZIP, manifest, production environment, and PayOS webhook configuration.

**Interfaces:**
- Produces a production product page that is `InStock` only while all sales
  gates pass.
- Produces one reconciled test order with a 24-hour protected download.

- [ ] **Step 1: Run focused static and unit verification**

```powershell
& $py -X utf8 -m py_compile app.py config\settings.py db\schema.py db\connection.py services\digital_products.py services\digital_product_orders.py services\payos_client.py routes\digital_products.py scripts\reconcile_digital_product_order.py
node --check static\js\thu_dau_mot_map_product.js
node --check static\js\thu_dau_mot_map_checkout.js
& $py -X utf8 -m pytest tests\test_digital_product_order_schema.py tests\test_digital_product_orders.py tests\test_payos_client.py tests\test_digital_product_checkout.py tests\test_digital_product_reconciliation.py tests\test_thu_dau_mot_map_checkout_js.py tests\test_thu_dau_mot_map_product_page.py -q
```

- [ ] **Step 2: Run public SEO and regression tests**

```powershell
& $py -X utf8 -m pytest tests\test_binh_duong_map_page.py tests\test_planning_pages.py tests\test_public_content_hubs.py tests\test_public_seo.py -q
& $py -X utf8 -m pytest -q
git diff --check
```

- [ ] **Step 3: Verify locally with checkout disabled**

At 375, 768, 1024, and 1440 px verify:

- product page has no horizontal overflow;
- the checkout button is disabled with a clear reason;
- Product Offer schema is `OutOfStock`;
- no paid source URL appears in HTML or network;
- controls are at least 44 px;
- keyboard focus and preview switch work;
- there are no console errors.

- [ ] **Step 4: Commit any verification corrections**

Stage only files named in this plan. Confirm no PDF, SVG, KML, ZIP, font binary,
secret, `.env`, or unrelated dirty file is staged.

- [ ] **Step 5: Push and deploy only after the asset plan also passes**

Use the repository's normal release chain:

```powershell
git status --short --branch
git push origin main
.\scripts\deploy_production.ps1
```

The deploy is incomplete until the deployed commit, service health, product
page, webhook route, Product schema, and protected storage gate are verified on
`https://radarbds.vn`.

- [ ] **Step 6: Keep sales disabled until user-authorized live proof**

Because PayOS does not provide a separate sandbox, automated testing ends with
mocked SDK calls. Do not create or pay a real 99,000 VND order without the
user's explicit authorization at this gate.

- [ ] **Step 7: Perform the deliberate production proof**

After authorization:

1. create one production order;
2. scan VietQR and pay exactly 99,000 VND;
3. verify webhook settlement;
4. verify the order page changes to `paid`;
5. download the exact ZIP and match SHA-256 with the protected release;
6. verify the download expiry is 24 hours after `paid_at`;
7. replay the webhook and confirm no duplicate grant or expiry change;
8. verify no token/order reference appears in analytics, Nginx query logs, or
   application logs;
9. leave `DIGITAL_PRODUCT_SALES_ENABLED=1` only if all checks pass.
