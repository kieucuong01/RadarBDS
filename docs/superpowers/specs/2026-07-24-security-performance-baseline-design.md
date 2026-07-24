# Security Hardening and Performance Baseline

Date: 2026-07-24

## Objective

Ship the smallest evidence-backed security hardening for Radar BDS, establish
repeatable local and production performance baselines, and release only after
all security, regression, and production gates pass.

This is phase 1 of the broader speed, codebase, and security goal. Codebase
decomposition follows in a separate phase after this release identifies the
real hot paths and security boundaries.

## Current Evidence

- The worktree was clean on `main` before design work.
- Production samples on 2026-07-24:
  - homepage median TTFB about 110 ms;
  - `/api/dashboard` median TTFB about 84 ms;
  - warm `/api/signals` median TTFB about 104 ms;
  - cold `/api/signals` samples reached 1.40-1.80 seconds.
- Production responses expose `nginx/1.24.0` and do not currently send CSP,
  HSTS, frame, MIME-sniffing, referrer, or permissions-policy headers.
- Session cookies already use HttpOnly and SameSite=Lax. `Secure` currently
  depends only on `request.is_secure`.
- Cookie-authenticated unsafe requests have no shared Origin/Referer guard.
- `_client_ip()` trusts the first `X-Forwarded-For` value, allowing a client
  supplied value to weaken rate limiting when a proxy appends to that header.
- The targeted market-data baseline has 21 passing tests and one existing
  SQLite fixture failure around the PostgreSQL valuation CTE shape.
- `pip-audit` is not installed in the selected Python 3.12 environment.

## Chosen Approach

Use an evidence-first security gate:

1. Record current local and production behavior.
2. Add focused regression tests for each confirmed application-layer risk.
3. Fix each risk once at its shared boundary.
4. Profile the cold signal query and change it only when the measured cause is
   identified.
5. Run targeted and full verification.
6. Commit, push `main`, deploy, poll readiness, and re-run live security and
   performance probes.

No application framework, custom security package, cache service, benchmark
framework, or broad `app.py` refactor is introduced in this phase.

## Application Security Design

### Client IP and rate limits

Use the Nginx-controlled `X-Real-IP` value instead of the client-controlled
first `X-Forwarded-For` value. Nginx already overwrites `X-Real-IP` with
`$remote_addr`. Fall back to `request.remote_addr` when the header is absent.

This fixes the shared source used by existing rate-limit scopes without
changing each endpoint.

### Cookie security

Keep HttpOnly and SameSite=Lax. Set `Secure` when either the current request is
HTTPS or the configured public base URL uses HTTPS. This fails closed in
production even if proxy scheme forwarding is temporarily misconfigured.

### Cross-site unsafe requests

Add one shared guard for `POST`, `PUT`, `PATCH`, and `DELETE` requests that
carry the Radar session cookie:

- accept an Origin matching the current host or configured public base URL;
- otherwise accept a same-origin Referer;
- reject missing or cross-origin evidence with HTTP 403;
- do not apply the cookie guard to requests without a session cookie, so
  anonymous lead capture, login/register, Telegram webhooks, and Basic Auth
  compatibility calls keep their existing behavior.

This uses browser-native Origin/Referer signals and avoids a new CSRF package
or token protocol.

### Admin compatibility authentication

Keep the existing Basic Auth fallback, but compare configured credentials with
`hmac.compare_digest()` from the standard library. App-session admin remains
the primary path.

### Response and proxy headers

Harden the production Nginx configuration with:

- `server_tokens off`;
- HSTS on HTTPS responses;
- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- `Referrer-Policy: strict-origin-when-cross-origin`;
- a restrictive Permissions Policy for unused browser capabilities;
- an enforceable minimal CSP containing at least `default-src`, `object-src`,
  `base-uri`, and `frame-ancestors`, expanded only with origins already used by
  the current frontend.

The CSP must be derived from current templates and verified in a rendered
browser before deployment. It must not silently disable analytics, maps,
images, fonts, or existing inline behavior.

## Dependency and Secret Audit

- Run `pip-audit` as temporary audit tooling; do not add it to runtime
  requirements.
- Fix confirmed critical/high findings with the narrowest compatible version
  pin and rerun affected tests.
- Scan tracked files and Git history for credential patterns without printing
  secret values to output.
- Do not read, print, stage, or commit `.env` or runtime credentials.
- A finding that cannot safely be upgraded in this release must have a
  concrete exposure analysis and mitigation before deployment.

## Performance Design

Measure instead of adding a speculative cache:

- public HTTPS: homepage, `/api/dashboard`, and `/api/signals`;
- at least ten warm samples plus distinct uncached filter variants;
- response status, TTFB, total time, and payload size;
- production localhost timing to separate network/Nginx cost from Flask/SQL;
- PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` for the confirmed slow signal shape.

Preserve the existing materialized valuation CTEs and aggregate duplicate-drop
join. Make a performance code or index change only if the query plan identifies
the cause. Lock any change with the existing
`tests/test_market_data_performance.py` suite.

The existing SQLite image-order fixture failure is repaired only as a test
compatibility issue; production SQL is not weakened to satisfy SQLite.

## Error Handling and Rollback

- Origin failures return a compact 403 response and do not mutate state.
- Security headers apply to error responses as well as successful responses.
- Dependency upgrades are isolated by package and reverted if compatibility
  tests fail.
- Deployment stops before restart when tests, dependency audit, secret scan,
  or Nginx validation fails.
- Deployment uses the existing production script and readiness polling.
- If live security or smoke checks fail, restore the previous production
  commit using the documented deployment rollback path.

## Verification Gates

### Application

- Python syntax checks for touched modules.
- Focused tests for client IP, cookie flags, Origin/Referer rejection, admin
  authentication, RBAC, redaction, and performance query shape.
- Existing dashboard, signal, image, and trust tests.
- Full `pytest tests` run, with integration tests that contact external
  services excluded unless explicitly required by their documented contract.

### Dependencies and repository

- No unresolved critical/high dependency finding without a documented
  mitigation.
- No confirmed committed credential.
- `git diff --check`.
- Only intended files staged.

### Production

- Nginx configuration validation succeeds.
- Service becomes ready after restart.
- Homepage and core APIs return expected status and payload shape.
- Guest/free/VIP responses do not expose phone, original URL, or source URL.
- Guest/free remain forbidden from VIP/admin endpoints.
- Security headers are present on HTML, API, static, and error responses.
- Server version is not exposed.
- Cold `/api/signals` target is below 1 second; warm p95 must not regress more
  than 15 percent from the recorded baseline.

## Release Sequence

1. Capture final pre-change evidence.
2. Add failing regression checks.
3. Apply the minimum shared-boundary fixes.
4. Run targeted checks, full tests, audits, and diff review.
5. Commit the scoped implementation.
6. Push `main`.
7. Deploy with `scripts/deploy_production.ps1`.
8. Poll readiness and run live security/performance probes.
9. Record exact production results and keep the broader goal active for the
   subsequent codebase-refactor phase.
