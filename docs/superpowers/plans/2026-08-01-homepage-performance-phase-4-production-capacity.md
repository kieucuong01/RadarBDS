# Homepage Performance Phase 4 Production Capacity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure the current 2-vCPU/4-GB Ubuntu host so 1,000-5,000 simultaneous public homepage requests are absorbed by Nginx and Redis without creating an equivalent number of Flask or PostgreSQL operations.

**Architecture:** Nginx is the public concurrency absorber and caches only explicitly marked guest responses for 15 seconds. Redis is a cache-only, loopback-bound dependency with a hard memory cap. Gunicorn remains deliberately small and PostgreSQL connections remain bounded by Phase 2. A staged external k6 test validates cache collapse, latency, privacy, saturation, and rollback before the 5,000-client target is accepted.

**Tech Stack:** Ubuntu Server 24.04, Nginx, Redis 7, systemd, Gunicorn, Flask, PostgreSQL, PowerShell deployment tooling, pytest, k6.

## Global Constraints

- Start only after the Phase 1, Phase 2, and Phase 3 release gates pass in production.
- This target means 1,000-5,000 concurrent in-flight public requests, not 5,000 sustained cache-miss requests per second.
- Preserve the live HTTPS and Certbot configuration. Never replace the live site file from the repository without first reconciling and diffing it.
- Cache only `GET` and `HEAD` for `/`, `/api/signals`, `/api/counts`, and `/api/dashboard` when the request has no `radar_session` cookie or `Authorization` header and the application explicitly emits `X-Radar-Public-Cache: 1` before storage.
- Never edge-cache admin, authenticated, redirect, error, `Set-Cookie`, phone, or original-source responses.
- Nginx cache TTL is 15 seconds. Redis's durable dataset version changes after publication, so application-cache invalidation is immediate and edge staleness is at most 15 seconds under normal operation, below the approved 60-second budget.
- Redis is disposable cache state: loopback only, persistence off, 256 MB maximum, `allkeys-lru` eviction.
- Do not increase PostgreSQL `max_connections`. Phase 2 caps the web tier at 3 workers x 4 pooled connections = 12.
- Do not add speculative kernel tuning beyond the accept queue values named in this plan.
- Apply one capacity stage at a time: 100, 500, 1,000, then 5,000 clients. Stop on an abort threshold; do not continue to the next stage.
- Run the default-key scenario through 5,000 clients. Run the approved 50-key mixed scenario only through 1,000 clients, after prewarming the fixed corpus.
- Every configuration mutation requires a dated backup, syntax validation before reload, a health check afterward, and an exact rollback command.
- Every task uses tests first and ends in a focused commit.

---

## Measured Production Snapshot (2026-08-01)

| Resource | Observed value | Planned bound |
|---|---:|---:|
| CPU | 2 vCPU | 3 Gunicorn workers, 4 threads each |
| RAM | 3,915 MB total; 2,582 MB available at sample | Redis maxmemory 256 MB |
| Swap | 4,095 MB total; 1,029 MB used | Load-test abort if active swap-in/out persists |
| Disk | 38 GB total; 11 GB free | Nginx cache max 512 MB |
| Gunicorn | 2 workers x 4 threads, timeout 180 s | 3 x 4, timeout 30 s, recycled workers |
| PostgreSQL | `max_connections=100`; 8 idle app sessions at sample | max 12 web pool connections |
| Nginx | 2 auto workers, `worker_connections=768` | 4,096 per worker |
| Kernel | `net.core.somaxconn=4096` | 8,192 accept/SYN queues |
| Redis | not installed | loopback cache-only service |
| File limits | service and Nginx 524,288 | explicit app limit 65,536 |

## File Structure

| File | Responsibility |
|---|---|
| `deployment/ubuntu24/redis-radar-bds.conf` | Radar-specific, cache-only Redis settings |
| `deployment/ubuntu24/nginx-radar-bds-cache.conf` | Nginx `http`-context maps and shared proxy-cache zone |
| `deployment/ubuntu24/nginx-radar-public-cache.inc` | Reusable safe public proxy/cache directives |
| `deployment/ubuntu24/nginx-radar-bds.conf` | Reconciled HTTPS site, static assets, four public cache locations, generic private proxy |
| `deployment/ubuntu24/nginx-events-performance.patch` | Exact reviewed global `events` block change |
| `deployment/ubuntu24/60-radar-bds-connections.conf` | Accept and SYN queue sysctls |
| `deployment/ubuntu24/radar-bds.service` | Bounded Gunicorn capacity and lifecycle controls |
| `scripts/install_performance_infra.sh` | Idempotent root-side backup, install, validate, activate, and rollback workflow |
| `scripts/deploy_production.ps1` | Explicit opt-in for performance infrastructure and post-deploy cache smoke |
| `scripts/verify_public_cache.ps1` | Guest hit, cookie bypass, privacy, and freshness checks |
| `scripts/load/radar_public_load.js` | Staged public homepage and filter load scenarios |
| `tests/test_deployment_units.py` | Static safety assertions for service, Nginx, Redis, sysctl, and deployment scripts |
| `docs/operations.md` | Capacity model, install, observability, abort, and rollback runbook |
| `docs/dev_commands.md` | Exact local and production validation commands |
| `docs/architecture.md` | Nginx -> Redis/app -> read-model request topology |
| `AGENTS.md` | Token-light routing and hard cache/privacy rules for later agents |

## Task 1: Add Tested Redis and Gunicorn Capacity Configuration

**Files:**
- Create: `deployment/ubuntu24/redis-radar-bds.conf`
- Modify: `deployment/ubuntu24/radar-bds.service`
- Modify: `tests/test_deployment_units.py`

**Interfaces:**
- Redis listens only on `127.0.0.1:6379` and IPv6 loopback when available.
- Gunicorn exposes only `127.0.0.1:5000` and has at most 12 request threads/12 DB pool connections.
- Redis outage must remain a degraded cache mode, not an authentication or source-of-truth outage.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_redis_profile_is_loopback_cache_only_and_memory_bounded():
    text = Path("deployment/ubuntu24/redis-radar-bds.conf").read_text("utf-8")
    assert "bind 127.0.0.1 -::1" in text
    assert "protected-mode yes" in text
    assert 'save ""' in text
    assert "appendonly no" in text
    assert "maxmemory 256mb" in text
    assert "maxmemory-policy allkeys-lru" in text
    assert "maxclients 256" in text
    assert "tcp-keepalive 60" in text


def test_web_service_has_bounded_gunicorn_capacity():
    text = Path("deployment/ubuntu24/radar-bds.service").read_text("utf-8")
    assert "After=network-online.target postgresql.service redis-server.service" in text
    assert "--workers 3" in text
    assert "--threads 4" in text
    assert "--timeout 30" in text
    assert "--graceful-timeout 30" in text
    assert "--keep-alive 5" in text
    assert "--max-requests 2000" in text
    assert "--max-requests-jitter 200" in text
    assert "LimitNOFILE=65536" in text
```

- [ ] **Step 2: Run the tests and prove they fail because the new profile and flags are absent**

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_deployment_units.py -q
```

- [ ] **Step 3: Create the Redis cache-only profile exactly**

```conf
bind 127.0.0.1 -::1
protected-mode yes
save ""
appendonly no
maxmemory 256mb
maxmemory-policy allkeys-lru
maxclients 256
tcp-keepalive 60
timeout 0
loglevel notice
```

- [ ] **Step 4: Change the service unit to the bounded command**

Keep the current user, group, working directory, environment file, logs, restart policy, and signal behavior. Change only dependency/capacity lines:

```ini
After=network-online.target postgresql.service redis-server.service

[Service]
LimitNOFILE=65536
ExecStart=/opt/radar-bds/.venv/bin/gunicorn --bind 127.0.0.1:5000 --workers 3 --threads 4 --timeout 30 --graceful-timeout 30 --keep-alive 5 --max-requests 2000 --max-requests-jitter 200 --access-logfile - --error-logfile - app:app
```

- [ ] **Step 5: Run focused verification**

```powershell
& $py -X utf8 -m pytest tests\test_deployment_units.py -q
git diff --check
```

- [ ] **Step 6: Commit**

```powershell
git add deployment/ubuntu24/redis-radar-bds.conf deployment/ubuntu24/radar-bds.service tests/test_deployment_units.py
git commit -m "perf: bound Redis and Gunicorn production capacity"
```

## Task 2: Add Guest-Only Nginx Cache and Connection Capacity

**Files:**
- Create: `deployment/ubuntu24/nginx-radar-bds-cache.conf`
- Create: `deployment/ubuntu24/nginx-radar-public-cache.inc`
- Modify: `deployment/ubuntu24/nginx-radar-bds.conf`
- Create: `deployment/ubuntu24/nginx-events-performance.patch`
- Create: `deployment/ubuntu24/60-radar-bds-connections.conf`
- Modify: `tests/test_deployment_units.py`

**Interfaces:**
- `nginx-radar-bds-cache.conf` is installed at `/etc/nginx/conf.d/radar-bds-cache.conf`, inside the global `http` context.
- `nginx-radar-public-cache.inc` is installed at `/etc/nginx/snippets/radar-bds-public-cache.inc`, inside each exact public `location`.
- `nginx-radar-bds.conf` remains the full site file and must retain all live Certbot `listen`, certificate, and challenge lines.
- The application header `X-Radar-Public-Cache` is consumed and hidden by Nginx; operators see only `X-Radar-Edge-Cache`.

- [ ] **Step 1: Write failing Nginx and sysctl tests**

```python
def test_nginx_public_cache_requires_no_session_and_app_opt_in():
    global_cache = Path("deployment/ubuntu24/nginx-radar-bds-cache.conf").read_text("utf-8")
    include = Path("deployment/ubuntu24/nginx-radar-public-cache.inc").read_text("utf-8")
    site = Path("deployment/ubuntu24/nginx-radar-bds.conf").read_text("utf-8")

    assert 'map $http_cookie $radar_has_session' in global_cache
    assert '~*(^|;\\s*)radar_session=' in global_cache
    assert 'map $upstream_http_x_radar_public_cache $radar_app_public' in global_cache
    assert "proxy_cache radar_public;" in include
    assert "proxy_cache_bypass $radar_has_session $http_authorization;" in include
    assert "proxy_no_cache $radar_has_session $http_authorization $radar_not_app_public $upstream_http_set_cookie;" in include
    assert "proxy_cache_valid 200 15s;" in include
    assert "proxy_cache_lock on;" in include
    assert "proxy_hide_header X-Radar-Public-Cache;" in include
    assert "add_header X-Radar-Edge-Cache $upstream_cache_status always;" in site
    assert "add_header X-Content-Type-Options \"nosniff\" always;" in site
    for route in ("= /", "= /api/signals", "= /api/counts", "= /api/dashboard"):
        assert f"location {route}" in site
    assert "ssl_certificate" in site


def test_connection_queue_profile_is_narrow_and_explicit():
    text = Path("deployment/ubuntu24/60-radar-bds-connections.conf").read_text("utf-8")
    assert text.splitlines() == [
        "net.core.somaxconn=8192",
        "net.ipv4.tcp_max_syn_backlog=8192",
    ]
```

- [ ] **Step 2: Run tests and prove the files are missing**

```powershell
& $py -X utf8 -m pytest tests\test_deployment_units.py -q
```

- [ ] **Step 3: Create the `http`-context cache zone and maps**

```nginx
proxy_cache_path /var/cache/nginx/radar-bds levels=1:2 keys_zone=radar_public:32m max_size=512m inactive=10m use_temp_path=off;

map $http_cookie $radar_has_session {
    default 0;
    ~*(^|;\s*)radar_session= 1;
}

map $upstream_http_x_radar_public_cache $radar_app_public {
    default 0;
    "1" 1;
}

map $radar_app_public $radar_not_app_public {
    default 1;
    1 0;
}
```

- [ ] **Step 4: Create the exact public-location include**

```nginx
proxy_pass http://radar_bds_app;
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header Connection "";

proxy_cache radar_public;
proxy_cache_methods GET HEAD;
proxy_cache_key "$scheme$request_method$host$request_uri";
proxy_cache_bypass $radar_has_session $http_authorization;
proxy_no_cache $radar_has_session $http_authorization $radar_not_app_public $upstream_http_set_cookie;
proxy_cache_valid 200 15s;
proxy_cache_lock on;
proxy_cache_lock_timeout 10s;
proxy_cache_lock_age 10s;
proxy_cache_background_update on;
proxy_cache_use_stale updating;

proxy_connect_timeout 2s;
proxy_read_timeout 10s;
proxy_send_timeout 10s;
proxy_hide_header X-Radar-Public-Cache;
```

The exact URI, including the Phase 3 canonical query string, is the edge key. Do not use cookies, authorization headers, or effective tier in an edge key; those requests bypass the edge cache entirely. `X-Radar-Public-Cache` controls storage through `proxy_no_cache`; it cannot participate in `proxy_cache_bypass` because an upstream response header is not known during cache lookup.

- [ ] **Step 5: Reconcile the repository site with the live HTTPS site**

Before editing, copy the live file into a temporary review path and diff it against the repository. Preserve every Certbot-owned certificate/listen/challenge line and security header. Then add:

- exact cache locations for `/`, `/api/signals`, `/api/counts`, `/api/dashboard`, each using the public include;
- one server-level `add_header X-Radar-Edge-Cache $upstream_cache_status always;` beside the existing security headers; do not put `add_header` in the public include because that would suppress inherited security headers;
- the current `/static/`, `/data/images/thumbs/`, and `/data/images/` aliases with `30d` immutable caching;
- generic `location /` with the existing 180-second timeout for out-of-scope private/admin/crawl routes;
- `gzip on`, `gzip_vary on`, `gzip_proxied any`, `gzip_comp_level 5`, `gzip_min_length 1024`, and types `application/json application/javascript text/css text/xml image/svg+xml`.
- the live server's version-compatible HTTP/2 form (`listen 443 ssl http2` for Nginx 1.24), existing TLS session settings, and upstream keepalive behavior.

The exact-match locations prevent cache directives from leaking to admin or arbitrary API routes.

- [ ] **Step 6: Add a reviewable global events patch and narrow sysctls**

`nginx-events-performance.patch` must show only this global change:

```diff
 events {
-    worker_connections 768;
+    worker_connections 4096;
+    multi_accept on;
 }
```

`60-radar-bds-connections.conf` must contain exactly:

```conf
net.core.somaxconn=8192
net.ipv4.tcp_max_syn_backlog=8192
```

- [ ] **Step 7: Run configuration tests and a disposable Nginx syntax check**

```powershell
& $py -X utf8 -m pytest tests\test_deployment_units.py -q
git diff --check
```

On Ubuntu with Nginx installed, assemble a temporary `/tmp/radar-nginx-test.conf` that includes the global cache file and a test server using the snippet, then run:

```bash
sudo nginx -t -c /tmp/radar-nginx-test.conf
```

- [ ] **Step 8: Commit**

```powershell
git add deployment/ubuntu24/nginx-radar-bds-cache.conf deployment/ubuntu24/nginx-radar-public-cache.inc deployment/ubuntu24/nginx-radar-bds.conf deployment/ubuntu24/nginx-events-performance.patch deployment/ubuntu24/60-radar-bds-connections.conf tests/test_deployment_units.py
git commit -m "perf: add guest-only Nginx response cache"
```

## Task 3: Build an Idempotent Install and Rollback Workflow

**Files:**
- Create: `scripts/install_performance_infra.sh`
- Modify: `scripts/deploy_production.ps1`
- Modify: `tests/test_deployment_units.py`

**Interfaces:**
- `scripts/install_performance_infra.sh install` requires root and creates one dated backup directory printed to stdout.
- `scripts/install_performance_infra.sh rollback /var/backups/radar-bds-performance/<stamp>` restores the exact backed-up files and service state.
- Normal application deploys do not modify Nginx, Redis, sysctl, or systemd unless `-InstallPerformanceInfra` is explicitly passed.

- [ ] **Step 1: Write failing installer/deployer safety tests**

```python
def test_performance_installer_validates_before_activation_and_has_rollback():
    text = Path("scripts/install_performance_infra.sh").read_text("utf-8")
    assert 'case "$1" in' in text
    assert "install)" in text
    assert "rollback)" in text
    assert "/var/backups/radar-bds-performance" in text
    assert "nginx -t" in text
    assert "systemd-analyze verify" in text
    assert "redis-server --test-memory 2" in text
    assert "systemctl reload nginx" in text
    assert "systemctl restart radar-bds.service" in text


def test_normal_deploy_requires_explicit_performance_infra_opt_in():
    text = Path("scripts/deploy_production.ps1").read_text("utf-8")
    assert "[switch] $InstallPerformanceInfra = $false" in text
    assert 'install_performance_infra="$InstallPerformanceInfraFlag"' in text
    assert 'scripts/install_performance_infra.sh install' in text
    assert 'if [ "$install_performance_infra" = "1" ]' in text
```

- [ ] **Step 2: Run the focused tests and confirm failure**

```powershell
& $py -X utf8 -m pytest tests\test_deployment_units.py -q
```

- [ ] **Step 3: Implement root-side preflight and backup**

The install mode must:

1. require effective UID 0;
2. require `/opt/radar-bds/current` and each source file;
3. create `/var/backups/radar-bds-performance/YYYYMMDD-HHMMSS` with mode `0700`;
4. record `systemctl is-enabled/is-active` for Nginx, Redis, and Radar;
5. copy `/etc/nginx/nginx.conf`, the resolved live site, `/etc/redis/redis.conf`, `/etc/systemd/system/radar-bds.service`, and `/etc/sysctl.d/60-radar-bds-connections.conf` when present;
6. record `nginx -T`, `sysctl net.core.somaxconn net.ipv4.tcp_max_syn_backlog`, and `systemctl cat radar-bds.service` without secrets;
7. install `redis-server` only after backup metadata is complete.

Do not copy `/etc/radar-bds/radar.env` into the backup because it contains secrets and is not changed by this workflow.

- [ ] **Step 4: Implement exact installation and pre-activation validation**

The installer must:

1. install the Redis profile as `/etc/redis/radar-bds.conf` and add `include /etc/redis/radar-bds.conf` to `/etc/redis/redis.conf` exactly once;
2. create `/var/cache/nginx/radar-bds` owned by `www-data:www-data`;
3. install the Nginx global cache file, include, and reconciled site;
4. apply the reviewed `events` edit only when the existing block contains `worker_connections 768;`; otherwise stop for manual review;
5. install the sysctl and service unit;
6. run `redis-server --test-memory 2`, `redis-server /etc/redis/redis.conf --test-memory 2`, `nginx -t`, and `systemd-analyze verify /etc/systemd/system/radar-bds.service` before reload/restart;
7. run `sysctl --system`, `systemctl daemon-reload`, `systemctl enable --now redis-server`, `systemctl restart radar-bds.service`, and only then `systemctl reload nginx`;
8. assert `redis-cli -h 127.0.0.1 ping` returns `PONG` and both services are active.

- [ ] **Step 5: Implement rollback mode**

Rollback accepts one resolved path strictly below `/var/backups/radar-bds-performance/`, refuses symlinks/out-of-tree paths, restores only files named in the backup manifest, then runs:

```bash
nginx -t
systemctl daemon-reload
sysctl --system
systemctl restart radar-bds.service
systemctl reload nginx
```

It restores the recorded Redis enabled/active state and leaves the dated backup intact.

- [ ] **Step 6: Add explicit PowerShell deploy opt-in**

Add `[switch] $InstallPerformanceInfra = $false`, pass a `0/1` flag into the uploaded shell, and call the installer after `git pull` but before the application restart only when the flag is `1`. A normal `scripts/deploy_production.ps1` invocation must behave exactly as before.

- [ ] **Step 7: Run shell syntax and focused tests**

```powershell
& $py -X utf8 -m pytest tests\test_deployment_units.py -q
$bash = "C:\Program Files\Git\bin\bash.exe"
& $bash -n scripts/install_performance_infra.sh
git diff --check
```

- [ ] **Step 8: Commit**

```powershell
git add scripts/install_performance_infra.sh scripts/deploy_production.ps1 tests/test_deployment_units.py
git commit -m "ops: add reversible performance infrastructure install"
```

## Task 4: Add Public Cache and Privacy Verification

**Files:**
- Create: `scripts/verify_public_cache.ps1`
- Modify: `tests/test_deployment_units.py`

**Interfaces:**
- Accepts `-BaseUrl`, default `https://radarbds.vn`.
- Uses a random non-secret test cookie value and no real account session.
- Fails if public responses set a cookie, private probes report `HIT`, sensitive fields appear, or a dataset publication remains stale beyond 60 seconds.

- [ ] **Step 1: Write a failing static contract test**

```python
def test_public_cache_verifier_checks_hit_bypass_and_redaction():
    text = Path("scripts/verify_public_cache.ps1").read_text("utf-8")
    assert "X-Radar-Edge-Cache" in text
    assert "radar_session=cache-bypass-probe" in text
    assert "Bearer cache-bypass-probe" in text
    assert '"source_url"' in text
    assert '"phone"' in text
    assert "Set-Cookie" in text
    assert "Cache HIT was not observed" in text
```

- [ ] **Step 2: Implement deterministic probes**

For each of `/`, `/api/signals?page=1&limit=20`, `/api/counts`, and `/api/dashboard`:

1. send one guest request;
2. repeat up to five times within 10 seconds until `X-Radar-Edge-Cache: HIT` appears;
3. fail if any guest response contains `Set-Cookie`;
4. send the same request with `Cookie: radar_session=cache-bypass-probe` and require status 200 plus cache status absent or `BYPASS`, never `HIT`;
5. repeat with `Authorization: Bearer cache-bypass-probe` and require the same private bypass behavior;
6. for JSON, recursively reject non-null `phone`, `phone_number`, `source_url`, `original_url`, or `contact_phone` keys;
7. require `Cache-Control: private, no-store` for cookie/authorization requests and public cache headers for the guest response.

The fake cookie is intentionally invalid. It exercises the Nginx cookie bypass before Flask resolves a session and does not authenticate a user.

- [ ] **Step 3: Add an operator-only freshness probe**

Accept optional `-ExpectedDatasetVersion`. Poll `/api/signals?page=1&limit=1` every five seconds for up to 60 seconds and require the public diagnostic version header from Phase 2 to equal the expected version. Do not trigger crawl, reprocess, or a database write inside the verifier.

- [ ] **Step 4: Run tests and local syntax parsing**

```powershell
& $py -X utf8 -m pytest tests\test_deployment_units.py -q
$null = [scriptblock]::Create((Get-Content -LiteralPath scripts\verify_public_cache.ps1 -Raw -Encoding utf8))
git diff --check
```

- [ ] **Step 5: Commit**

```powershell
git add scripts/verify_public_cache.ps1 tests/test_deployment_units.py
git commit -m "test: verify public cache isolation and freshness"
```

## Task 5: Build the Staged External k6 Load Test

**Files:**
- Create: `scripts/load/radar_public_load.js`
- Modify: `tests/test_deployment_units.py`
- Modify: `docs/dev_commands.md`

**Interfaces:**
- Required environment: `BASE_URL`.
- Optional environment: `SCENARIO=default|mixed`, `VUS`, `DURATION`, `RUN_ID`.
- Sends no authorization and no session cookie.
- `default` tests shared homepage/default-signal keys. `mixed` chooses from a fixed 50-key canonical filter corpus.

- [ ] **Step 1: Write failing script contract tests**

```python
def test_k6_public_load_script_has_safe_scenarios_and_thresholds():
    text = Path("scripts/load/radar_public_load.js").read_text("utf-8")
    assert "SCENARIO" in text
    assert "default" in text and "mixed" in text
    assert "http.batch" in text
    assert "http_req_failed" in text
    assert "p(95)<1000" in text
    assert "p(99)<2000" in text
    assert "X-Radar-Edge-Cache" in text
    assert "radar_session" not in text
    assert "Authorization" not in text
```

- [ ] **Step 2: Implement the default scenario**

Each iteration performs one `http.batch` with:

- `GET ${BASE_URL}/?load_run=${RUN_ID}`;
- `GET ${BASE_URL}/api/signals?page=1&limit=20&load_run=${RUN_ID}`.

`RUN_ID` is shared by the whole run, so the test creates one cold edge key per route rather than bypassing the cache for every virtual user. Validate status 200, public cache header presence, and body shape. Sleep one second between iterations.

- [ ] **Step 3: Implement the mixed-filter scenario**

Build exactly 50 stable canonical query strings by combining approved ward/source/property/MOS values and sorting keys/multi-values with the same rules as Phase 3. Select by `(__VU + __ITER) % 50`. Send `/api/signals` plus `/api/counts` in a batch. Do not use random UUIDs, unbounded pages, invalid filters, authentication, mutations, admin routes, or source URLs.

In `setup()`, request every one of the 50 signal/count pairs once, retry cacheable 200 responses once, and fail setup unless the second probe is `HIT`. This keeps the mixed test focused on the approved warm/common-key capacity target. Cold-cardinality behavior is covered separately by Phase 2's bounded-loader and `503 Retry-After` tests.

- [ ] **Step 4: Set thresholds and run metadata**

For `default` require:

```javascript
thresholds: {
  http_req_failed: ["rate<0.005"],
  http_req_duration: ["p(95)<1000", "p(99)<2000"],
  checks: ["rate>0.995"],
}
```

For `mixed`, override duration with `p(95)<1500` and retain the other limits. Emit counters for edge `HIT`, `MISS`, `STALE`, and `BYPASS` so the report proves request collapse rather than latency alone.

- [ ] **Step 5: Validate the script without generating load**

```powershell
k6 inspect scripts/load/radar_public_load.js
& $py -X utf8 -m pytest tests\test_deployment_units.py -q
git diff --check
```

- [ ] **Step 6: Document exact staged commands**

```powershell
$env:BASE_URL = "https://radarbds.vn"
$env:SCENARIO = "default"
$env:RUN_ID = "stage-100"
$env:VUS = "100"
$env:DURATION = "2m"
k6 run scripts\load\radar_public_load.js
```

Repeat only after the previous stage passes, with a unique shared `RUN_ID` per stage. Run `default` at 100, 500, 1,000, and 5,000 VUs. Run `mixed` at 100, 500, and 1,000 VUs. Do not run stages or scenarios in parallel.

- [ ] **Step 7: Commit**

```powershell
git add scripts/load/radar_public_load.js tests/test_deployment_units.py docs/dev_commands.md
git commit -m "test: add staged public homepage load profile"
```

## Task 6: Production Rollout, Observation, and Rollback Drill

**Files:**
- Modify: `docs/operations.md`
- Modify: `docs/architecture.md`
- Modify: `AGENTS.md`
- Test: live system, browser, cache, database, and external load evidence

**Interfaces:**
- Produces one dated evidence directory outside git on the operator machine.
- Does not declare success from HTTP 200 alone; requires cache isolation, bounded DB sessions, resource stability, and browser correctness.

- [ ] **Step 1: Record a fresh read-only preflight**

Record commit, dirty state, active service files, CPU/RAM/swap/disk, open sockets, Nginx worker count/connections, `somaxconn`, PostgreSQL connections/settings/table stats, Redis presence, and current live latency. Abort before mutation if the production checkout is unexpectedly dirty, disk free space is below 5 GB, available RAM is below 1 GB at idle, or the live configuration differs materially from the plan.

- [ ] **Step 2: Deploy application phases before infrastructure**

Pull/rebase and push `main`, run the normal deployment, initialize schema, then verify Phases 1-3 through localhost and public HTTPS. Do not install Phase 4 while any parity, redaction, pool, Redis fallback, browser, or cache-header test is failing.

- [ ] **Step 3: Install Phase 4 with the explicit opt-in**

```powershell
.\scripts\deploy_production.ps1 -InstallPerformanceInfra
.\scripts\verify_public_cache.ps1 -BaseUrl "https://radarbds.vn"
```

Capture the printed backup directory. Confirm guest `MISS` then `HIT`, fake-cookie `BYPASS`, Redis `PONG`, Nginx syntax, active services, three Gunicorn workers, and no sensitive JSON fields.

- [ ] **Step 4: Run the 100-client canary while observing the host**

From a machine outside the VPS, run `default` 100 VUs for two minutes. During the run sample every 10 seconds:

```bash
systemctl is-active nginx redis-server radar-bds.service postgresql
ss -s
redis-cli info memory
redis-cli info stats
sudo -u postgres psql -d radar_bds -Atc "select state,count(*) from pg_stat_activity group by state order by state"
journalctl -u radar-bds.service --since "2 minutes ago" --no-pager
tail -n 100 /var/log/nginx/radar-bds.error.log
vmstat 1 5
```

- [ ] **Step 5: Apply abort thresholds at every stage**

Stop and rollback or diagnose before continuing if any condition occurs:

- 5xx or network failure rate >= 0.5%;
- default p95 > 1,000 ms or p99 > 2,000 ms;
- mixed-filter p95 > 1,500 ms;
- PostgreSQL app connections exceed 12 or active DB loaders scale with VUs;
- Redis memory exceeds 256 MB, evictions cause correctness errors, or Redis becomes externally reachable;
- swap-in/swap-out remains nonzero across three consecutive samples;
- Nginx/Gunicorn/Redis/PostgreSQL restarts, OOM events, file-descriptor errors, connection-queue overflows, or sustained CPU > 90% for 60 seconds;
- any cookie request reports edge `HIT`, any authenticated response becomes public, or any phone/source URL leaks;
- homepage/filter browser behavior regresses.

- [ ] **Step 6: Advance serially and prove cache collapse**

Run default then mixed at 500 and 1,000 VUs; run only default at 5,000 VUs. For each stage preserve the k6 summary plus host samples and report:

- total requests and peak VUs;
- p50/p95/p99 and failure rate;
- edge HIT/MISS/STALE/BYPASS counts;
- Redis hits/misses/evictions/memory;
- maximum Gunicorn busy requests and PostgreSQL connections;
- CPU, memory, swap, sockets, and Nginx errors.

Acceptance requires the upstream request/DB query count to remain tied to the bounded number of cache keys, not to the number of clients.

- [ ] **Step 7: Perform one controlled failure drill below peak load**

At 100 VUs only, stop Redis for no more than 30 seconds. Confirm Phase 2 serves stale/local cache or controlled `503 Retry-After` without DB connection explosion; restart Redis and confirm automatic recovery/prewarm. Do not stop PostgreSQL in production. If the Redis drill violates an abort threshold, roll back Phase 4 and fix before any new peak test.

- [ ] **Step 8: Exercise rollback once**

Use the printed backup path:

```bash
sudo /opt/radar-bds/current/scripts/install_performance_infra.sh rollback /var/backups/radar-bds-performance/YYYYMMDD-HHMMSS
```

Verify old services/configuration and public smoke, then reinstall and repeat the 100-VU canary. This proves recovery before relying on it during an incident.

- [ ] **Step 9: Update durable docs for future agents**

Document in the routed files:

- capacity model and why 5,000 concurrency depends on cache collapse;
- exact app/Redis/Nginx/PostgreSQL ownership boundaries;
- guest-only cache classification and internal/public headers;
- 60-second freshness contract and 15-second edge bound;
- install, deploy, verification, load-test, observability, abort, and rollback commands;
- measured production results and evidence location;
- known limits: one 2-vCPU host cannot promise 5,000 unique cold uncached queries or high availability.

- [ ] **Step 10: Run final repository verification**

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest `
  tests\test_deployment_units.py `
  tests\test_postgres_connection.py `
  tests\test_public_cache_keys.py `
  tests\test_public_cache.py `
  tests\test_public_cache_headers.py `
  tests\test_market_data_performance.py `
  tests\test_guest_visibility.py `
  tests\test_source_policy.py `
  tests\test_security_hardening.py -q
node --test tests\js\filter_runtime.test.cjs tests\js\web_vitals.test.cjs
node --check static\js\main\filter_runtime.js
node --check static\js\main\web_vitals.js
$bash = "C:\Program Files\Git\bin\bash.exe"
& $bash -n scripts/install_performance_infra.sh
k6 inspect scripts/load/radar_public_load.js
git diff --check
```

- [ ] **Step 11: Commit the final operational knowledge**

```powershell
git add AGENTS.md docs/architecture.md docs/operations.md docs/dev_commands.md
git commit -m "docs: record production performance capacity runbook"
```

## Phase 4 Release Gate

Phase 4 is complete only when all of the following are evidenced:

- guest default traffic meets the approved latency/error thresholds at 5,000 concurrent VUs, and the canonical 50-key mixed-filter traffic meets them at 1,000 concurrent VUs;
- edge HIT/MISS metrics and database sessions prove load collapse;
- authenticated/cookie requests bypass every edge cache and retain private headers/redaction;
- Redis failure remains bounded and recovers without manual data repair;
- system services remain stable with no OOM, restart loop, sustained swap pressure, or connection explosion;
- the dated backup and rollback drill both work;
- the browser homepage/filter flow remains correct after the infrastructure change;
- `AGENTS.md` and routed docs contain the current capacity facts and exact operator commands.

If 5,000 clients fail only because the single host saturates after cache collapse is proven, stop at the highest passing stage and open a separately approved horizontal-scaling design. Do not raise workers, DB connections, timeouts, or Redis memory blindly.
