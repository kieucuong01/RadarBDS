# Security Hardening and Performance Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden Radar BDS shared trust boundaries, remove the measured cold signal-query regression, and release the verified changes to production.

**Architecture:** Keep auth controls in `auth/core.py`, register one global Flask request guard from `app.py`, and keep production response policy in the existing Nginx site configuration. Preserve the existing signal query shape while materializing the repeatedly executed price-drop aggregate and narrowing the shadow valuation CTE to columns its consumers use.

**Tech Stack:** Python 3.12, Flask 3.1, PostgreSQL 18/Ubuntu PostgreSQL, psycopg 3, pytest, Gunicorn, Nginx 1.24, PowerShell deployment.

## Global Constraints

- Add no application framework, custom security package, cache service, or benchmark framework.
- Keep HttpOnly and SameSite=Lax session-cookie behavior.
- Do not expose phone, original URL, or source URL to Guest, Free, or VIP.
- Do not weaken the materialized latest-valuation CTEs.
- Do not change production SQL to satisfy a SQLite-only test fixture.
- Do not print, stage, or commit `.env` or credential values.
- Do not deploy with an unresolved critical/high dependency finding.
- Cold `/api/signals` target is below 1 second.
- Warm p95 must not regress more than 15 percent from the recorded baseline.
- Release sequence is test, commit, push `main`, deploy, readiness poll, and live verification.

## File Map

- `auth/core.py`: shared client-IP resolution and same-origin session guard.
- `app.py`: register the guard, fail closed on production cookie security, reuse shared client-IP resolution, and use constant-time Basic Auth comparison.
- `tests/test_security_hardening.py`: focused application and Nginx security regression checks.
- `deployment/ubuntu24/nginx-radar-bds.conf`: production response headers and version hiding.
- `services/market_data.py`: materialized price-drop aggregate and lean shadow valuation CTE.
- `tests/test_market_data_performance.py`: SQL-shape regression checks.
- `tests/test_market_data_images.py`: decouple gallery-order coverage from PostgreSQL-only valuation CTE syntax.

---

### Task 1: Shared application security boundaries

**Files:**
- Modify: `auth/core.py:10-20,369-393`
- Modify: `app.py:1-20,55-100,155-162,663-686,774,796`
- Create: `tests/test_security_hardening.py`

**Interfaces:**
- Produces: `client_ip_from_request() -> str`
- Produces: `reject_cross_site_session_request() -> tuple | None`
- Consumes: `SESSION_COOKIE_NAME`, `PUBLIC_BASE_URL`, Flask `request`

- [ ] **Step 1: Add failing trust-boundary tests**

Create `tests/test_security_hardening.py`:

```python
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
```

- [ ] **Step 2: Run the tests and confirm the missing interfaces**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_security_hardening.py -q
```

Expected: collection fails because `client_ip_from_request` and
`reject_cross_site_session_request` do not exist.

- [ ] **Step 3: Implement the shared helpers**

In `auth/core.py`, add imports:

```python
from urllib.parse import urlsplit

from config.settings import PUBLIC_BASE_URL
```

Replace `_client_ip_from_request()` with:

```python
def client_ip_from_request() -> str:
    try:
        return (
            request.headers.get("X-Real-IP")
            or request.remote_addr
            or "0.0.0.0"
        ).strip()
    except Exception:
        return "0.0.0.0"
```

Update `rate_limit()` to call `client_ip_from_request()`.

Add:

```python
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _origin(value: str | None) -> str:
    parsed = urlsplit(value or "")
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def reject_cross_site_session_request():
    if (
        request.method not in _UNSAFE_METHODS
        or not request.cookies.get(SESSION_COOKIE_NAME)
    ):
        return None

    supplied = request.headers.get("Origin") or request.headers.get("Referer")
    host = request.host.split(":", 1)[0].strip("[]").lower()
    if not supplied and host in _LOCAL_HOSTS:
        return None

    allowed = {_origin(request.host_url), _origin(PUBLIC_BASE_URL)}
    if not supplied or _origin(supplied) not in allowed:
        return jsonify({"error": "cross_site_request"}), 403
    return None
```

In `app.py`, import `hmac`, `client_ip_from_request`, and
`reject_cross_site_session_request`. Register the guard immediately after the
Flask app is created:

```python
app = Flask(__name__)
app.before_request(reject_cross_site_session_request)
```

Replace `_basic_admin_authorized()` with:

```python
def _basic_admin_authorized():
    auth = request.authorization
    user, pwd = _admin_credentials()
    return bool(
        auth
        and user
        and pwd
        and hmac.compare_digest(auth.username or "", user)
        and hmac.compare_digest(auth.password or "", pwd)
    )
```

Change `_cookie_kwargs()`:

```python
secure=request.is_secure or PUBLIC_BASE_URL.lower().startswith("https://"),
```

Delete the duplicate `app.py::_client_ip()` helper and replace its two callers
with `client_ip_from_request()`.

- [ ] **Step 4: Run focused security and existing auth-dependent tests**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_security_hardening.py tests\test_admin_control_room.py tests\test_favorite_listings.py tests\test_radar_assistant.py tests\test_valuation_tool.py -q
```

Expected: all pass. Existing localhost mutation tests remain valid because the
guard permits missing Origin only on loopback hosts.

- [ ] **Step 5: Commit the application security boundary**

```powershell
git add -- auth/core.py app.py tests/test_security_hardening.py
git commit -m "Harden session request boundaries"
```

### Task 2: Production Nginx response policy

**Files:**
- Modify: `deployment/ubuntu24/nginx-radar-bds.conf`
- Modify: `tests/test_security_hardening.py`

**Interfaces:**
- Consumes: existing Nginx canonical server and three static asset locations.
- Produces: security headers on HTML, API, static, and Nginx error responses.

- [ ] **Step 1: Add a failing Nginx configuration test**

Append to `tests/test_security_hardening.py`:

```python
def test_nginx_config_hides_version_and_covers_dynamic_and_static_responses():
    text = Path("deployment/ubuntu24/nginx-radar-bds.conf").read_text(
        encoding="utf-8"
    )

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
```

- [ ] **Step 2: Confirm the test fails against the current Nginx template**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_security_hardening.py::test_nginx_config_hides_version_and_covers_dynamic_and_static_responses -q
```

Expected: fail because `server_tokens off` and the security headers are absent.

- [ ] **Step 3: Add the production headers**

Add `server_tokens off;` inside both existing `server` blocks.

Insert this identical block once at canonical server scope and once inside each
of the three existing static/image `location` blocks:

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com https://www.googletagmanager.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://unpkg.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob: https:; connect-src 'self' https://www.google-analytics.com https://region1.google-analytics.com https://www.googletagmanager.com; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'" always;
```

Repeating this block is intentional: Nginx 1.24 stops inheriting parent
`add_header` directives inside a location that already defines Cache-Control.

- [ ] **Step 4: Run the configuration regression test**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_security_hardening.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit the Nginx policy**

```powershell
git add -- deployment/ubuntu24/nginx-radar-bds.conf tests/test_security_hardening.py
git commit -m "Add production security headers"
```

### Task 3: Remove the measured repeated price-drop aggregate

**Files:**
- Modify: `services/market_data.py:14-20,423-443,1120-1170`
- Modify: `tests/test_market_data_performance.py:156-173`

**Interfaces:**
- Produces: `RELATED_PRICE_DROP_CTE` SQL constant.
- Produces: `related_price_drop_join_sql(alias, join_alias)` as a cheap join to
  the materialized CTE.
- Preserves: `load_signals(...) -> dict`.

- [ ] **Step 1: Strengthen the SQL-shape regression tests**

Replace the current CTE/join tests with:

```python
def test_signal_feed_materializes_compact_valuation_ctes():
    import services.market_data as market_data

    assert "latest_valuation AS MATERIALIZED (" in market_data.LATEST_VALUATION_CTE
    assert (
        "latest_shadow_valuation AS MATERIALIZED ("
        in market_data.LATEST_SHADOW_VALUATION_CTE
    )
    assert "vsr.*" not in market_data.LATEST_SHADOW_VALUATION_CTE
    for column in (
        "vsr.listing_id",
        "vsr.is_signal",
        "vsr.actual_ppm2",
        "vsr.fair_ppm2",
        "vsr.mos_pct",
        "vsr.signal_score",
        "vsr.trust_tier",
        "vsr.trust_score",
        "vsr.legal_status",
        "vsr.legal_flags",
        "vsr.source_quality_flags",
        "vsr.source_quality_recheck",
    ):
        assert column in market_data.LATEST_SHADOW_VALUATION_CTE


def test_related_price_drop_rows_are_materialized_once():
    from services.market_data import (
        RELATED_PRICE_DROP_CTE,
        related_price_drop_join_sql,
    )

    assert "related_price_drops AS MATERIALIZED (" in RELATED_PRICE_DROP_CTE
    assert "GROUP BY drop_child.duplicate_of_id" in RELATED_PRICE_DROP_CTE
    join_sql = related_price_drop_join_sql("l", "related_drop")
    assert "LEFT JOIN related_price_drops related_drop" in join_sql
    assert "GROUP BY" not in join_sql
```

- [ ] **Step 2: Run the two tests and confirm the old SQL shape fails**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_market_data_performance.py::test_signal_feed_materializes_compact_valuation_ctes tests\test_market_data_performance.py::test_related_price_drop_rows_are_materialized_once -q
```

Expected: fail because the shadow CTE uses `vsr.*` and the aggregate is still
inside the join.

- [ ] **Step 3: Narrow the shadow CTE**

Replace `LATEST_SHADOW_VALUATION_CTE` with:

```python
LATEST_SHADOW_VALUATION_CTE = """
latest_shadow_valuation AS MATERIALIZED (
    SELECT DISTINCT ON (vsr.listing_id)
           vsr.listing_id, vsr.is_signal, vsr.actual_ppm2,
           vsr.fair_ppm2, vsr.mos_pct, vsr.signal_score,
           vsr.trust_tier, vsr.trust_score,
           vsr.legal_status, vsr.legal_flags,
           vsr.source_quality_flags, vsr.source_quality_recheck
    FROM valuation_shadow_results vsr
    ORDER BY vsr.listing_id, vsr.computed_at DESC, vsr.id DESC
)
"""
```

- [ ] **Step 4: Materialize the price-drop aggregate once**

Add:

```python
RELATED_PRICE_DROP_CTE = """
related_price_drops AS MATERIALIZED (
    SELECT drop_child.duplicate_of_id AS listing_id,
           MAX(drop_child.price_ty) AS first_price
    FROM listings drop_child
    JOIN listings drop_parent ON drop_parent.id = drop_child.duplicate_of_id
    WHERE drop_child.duplicate_of_id IS NOT NULL
      AND COALESCE(drop_child.probably_sold,0)=0
      AND COALESCE(drop_child.is_blacklisted,0)=0
      AND COALESCE(drop_child.review_hidden,0)=0
      AND drop_child.price_ty IS NOT NULL
      AND drop_parent.price_ty IS NOT NULL
      AND drop_child.price_ty > drop_parent.price_ty * 1.01
      AND drop_parent.price_ty >= drop_child.price_ty * 0.60
    GROUP BY drop_child.duplicate_of_id
)
"""
```

Replace `related_price_drop_join_sql()` with:

```python
def related_price_drop_join_sql(alias="l", join_alias="related_drop"):
    return (
        f"LEFT JOIN related_price_drops {join_alias} "
        f"ON {join_alias}.listing_id = {alias}.id"
    )
```

Add `RELATED_PRICE_DROP_CTE` to the `load_signals()` `WITH` list:

```python
WITH {LATEST_VALUATION_CTE},
     {LATEST_SHADOW_VALUATION_CTE},
     {RELATED_PRICE_DROP_CTE}
```

- [ ] **Step 5: Run the market-data regression suite**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_market_data_performance.py tests\test_market_data_trust.py -q
```

Expected: all pass.

- [ ] **Step 6: Re-run local PostgreSQL evidence**

Run the established local Flask timing and `EXPLAIN (ANALYZE, BUFFERS)` probes.
Expected:

- query plan contains one materialized `related_price_drops` CTE;
- the price-drop aggregate has one loop, not 561 loops;
- no shadow CTE temp spill;
- execution time improves from the recorded 410.608 ms baseline;
- local uncached signal-filter requests remain below 1 second.

- [ ] **Step 7: Commit the measured query fix**

```powershell
git add -- services/market_data.py tests/test_market_data_performance.py
git commit -m "Materialize signal price drop aggregates"
```

### Task 4: Repair the stale SQLite gallery fixture

**Files:**
- Modify: `tests/test_market_data_images.py:106-125`

**Interfaces:**
- Preserves gallery-order coverage.
- Does not execute or alter PostgreSQL valuation CTE syntax.

- [ ] **Step 1: Replace the fixture connection for the detail test**

In
`test_listing_detail_gallery_keeps_original_order_while_legal_image_feature_disabled`,
replace `fake_read_conn` with a small wrapper that returns the listing row
without asking SQLite to parse PostgreSQL CTEs:

```python
        @contextmanager
        def fake_read_conn(_db_path=None):
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row

            class StaticCursor:
                def fetchone(self):
                    row = dict(conn.execute(
                        "SELECT * FROM listings WHERE id=1"
                    ).fetchone())
                    row.update({
                        "is_signal": 1,
                        "mos_pct": 0,
                        "fair_ppm2": 0,
                        "signal_score": 0,
                        "trust_tier": "candidate_signal",
                        "trust_score": 0,
                        "legal_status": "unverified",
                        "legal_flags": "",
                        "is_fresh_locked": 0,
                    })
                    return row

            class DetailConnection:
                def execute(self, sql, params=None):
                    if "FROM listings l" in sql:
                        return StaticCursor()
                    return conn.execute(sql, params or ())

                def close(self):
                    conn.close()

            try:
                yield DetailConnection()
            finally:
                conn.close()
```

- [ ] **Step 2: Run the previously failing image test**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_market_data_images.py::MarketDataImageOrderingTest::test_listing_detail_gallery_keeps_original_order_while_legal_image_feature_disabled -q
```

Expected: pass, with the image order unchanged.

- [ ] **Step 3: Run all market-data image tests**

```powershell
& $py -X utf8 -m pytest tests\test_market_data_images.py -q
```

Expected: all pass.

- [ ] **Step 4: Commit the fixture repair**

```powershell
git add -- tests/test_market_data_images.py
git commit -m "Decouple image fixture from Postgres CTE syntax"
```

### Task 5: Dependency and credential release gates

**Files:**
- Modify: `requirements.txt`

**Interfaces:**
- Consumes package names and pinned versions from `requirements.txt`.
- Produces a release gate; no runtime audit dependency is added.

- [ ] **Step 1: Obtain explicit permission for the external advisory lookup**

Explain that `pip-audit` sends package names and versions from
`requirements.txt` to an external vulnerability service. Do not run the lookup
until the user explicitly permits that metadata transfer.

- [ ] **Step 2: Run the dependency audit after permission**

```powershell
& $py -X utf8 -m pip_audit -r requirements.txt --progress-spinner off
```

Observed before implementation:

- Pillow 10.4.0 has known advisories fixed by 12.3.0.
- python-dotenv 1.2.1 has a known advisory, but the project uses its own
  standard-library `.env` loader and does not import this package.
- requests 2.32.5 has a known advisory. `alerts/telegram.py` imports it for
  Telegram delivery, so it must be upgraded rather than removed.

- [ ] **Step 3: Remove the unused dependency and upgrade vulnerable packages**

Change `requirements.txt`:

```text
Pillow==12.3.0
requests==2.33.0
```

Delete only the unused `python-dotenv` line.

Install and verify the changed image stack:

```powershell
& $py -X utf8 -m pip install -r requirements.txt
& $py -X utf8 -m pytest tests\test_image_assets.py tests\test_image_cleanup.py tests\test_legal_image_classifier.py tests\test_download_images.py -q
& $py -X utf8 -m pip_audit -r requirements.txt --progress-spinner off
```

Expected: all image tests pass and pip-audit reports
`No known vulnerabilities found`.

- [ ] **Step 4: Commit the dependency cleanup**

```powershell
git add -- requirements.txt docs/superpowers/plans/2026-07-24-security-performance-baseline.md
git commit -m "Remove vulnerable unused dependencies"
```

- [ ] **Step 5: Scan tracked files without printing secret values**

```powershell
git grep -Il -E "(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})" --
git log --all --format="%H" --name-only -G "(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})" --
```

Expected: no confirmed credential. These commands print only file names and
commit IDs, not matching values.

### Task 6: Full local verification

**Files:**
- No new files.

**Interfaces:**
- Consumes every implementation commit.
- Produces the final local release decision.

- [ ] **Step 1: Run syntax checks**

```powershell
& $py -X utf8 -m py_compile app.py auth\core.py services\market_data.py
node --check static\js\main.js
node --check static\js\auth.js
```

Expected: all exit 0.

- [ ] **Step 2: Run focused security, RBAC, and performance tests**

```powershell
& $py -X utf8 -m pytest tests\test_security_hardening.py tests\test_market_data_performance.py tests\test_market_data_trust.py tests\test_market_data_images.py tests\test_guest_visibility.py tests\test_admin_control_room.py tests\test_favorite_listings.py tests\test_radar_assistant.py tests\test_valuation_tool.py -q
```

Expected: all pass.

- [ ] **Step 3: Run the full local test suite**

```powershell
& $py -X utf8 -m pytest tests -q
```

Expected: all non-integration tests pass. If a test contacts a live external
service, classify it using `docs/dev_commands.md`; do not change unrelated
production code to silence it.

- [ ] **Step 4: Review repository scope**

```powershell
git diff --check
git status --short
git log -6 --oneline
```

Expected: no unstaged implementation files and only the intended commits ahead
of `origin/main`.

### Task 7: Push, deploy, and verify production

**Files:**
- Production configuration target:
  `/etc/nginx/sites-available/radar-bds.conf`

**Interfaces:**
- Consumes verified `main`.
- Produces deployed commit and live security/performance evidence.

- [ ] **Step 1: Push verified commits**

```powershell
git push origin main
```

Expected: `origin/main` advances to the local verified commit.

- [ ] **Step 2: Deploy the application**

```powershell
.\scripts\deploy_production.ps1
```

Expected: remote fast-forward, dependency install, syntax checks, service
restart, readiness polling, and dashboard/signal smoke checks all succeed.

- [ ] **Step 3: Install the versioned Nginx template safely**

Upload the repository template to `/tmp/nginx-radar-bds.conf`, then run:

```bash
set -e
backup=/tmp/radar-bds-nginx-before-security.conf
sudo cp /etc/nginx/sites-available/radar-bds.conf "$backup"
sudo install -m 0644 /tmp/nginx-radar-bds.conf /etc/nginx/sites-available/radar-bds.conf
if ! sudo nginx -t; then
  sudo cp "$backup" /etc/nginx/sites-available/radar-bds.conf
  sudo nginx -t
  exit 1
fi
sudo systemctl reload nginx
```

Expected: `nginx -t` succeeds before reload. On validation failure, the previous
configuration is restored and the release stops.

- [ ] **Step 4: Verify live security behavior**

Probe homepage, one static asset, one 404, `/api/signals`, and
`/api/dashboard`.

Expected:

- `Server` does not include a version;
- all six configured security headers are present;
- Guest payload contains no phone, original URL, or source URL;
- Guest receives 403 from VIP/admin-only endpoints;
- a cookie-authenticated mutation with
  `Origin: https://attacker.example` returns 403 without changing state.

- [ ] **Step 5: Verify live performance**

Collect at least ten warm samples and distinct uncached filter samples for:

```text
https://radarbds.vn/
https://radarbds.vn/api/dashboard
https://radarbds.vn/api/signals?page=1&limit=30&include_total=0
```

Also measure production localhost from the VPS.

Expected:

- cold `/api/signals` below 1 second;
- warm p95 no more than 15 percent slower than the pre-change baseline;
- status and payload sizes remain stable;
- localhost `EXPLAIN` shows one price-drop aggregate loop and no shadow CTE
  temp spill.

- [ ] **Step 6: Record the production commit and keep the broader goal active**

Run:

```powershell
git status --short --branch
git rev-parse --short HEAD
```

Expected: local `main` matches `origin/main` and production reports the same
commit. Start the separate codebase-decomposition phase only after this release
is stable.
