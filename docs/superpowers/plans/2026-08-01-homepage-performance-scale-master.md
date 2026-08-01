# Homepage Performance Scaling Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a fast, security-safe Radar BDS homepage and filter feed that survives bursts of up to 5,000 concurrent public requests without exhausting Gunicorn or PostgreSQL.

**Architecture:** Execute four independently reversible phases: first remove the SQL regression and introduce a PostgreSQL signal-card read model; then add bounded PostgreSQL pooling plus Redis shared cache/single-flight; then reduce browser request fan-out and canonicalize filters; finally install production Redis/Nginx/runtime capacity controls and prove them with staged load tests. Every phase keeps the prior path behind a feature flag until parity and live smoke pass.

**Tech Stack:** Python 3.12, Flask 3.1, PostgreSQL, psycopg 3, Redis, Gunicorn gthread, Nginx, vanilla JavaScript, pytest, Node's built-in test runner, Playwright/browser trace, and k6 from an external load generator.

## Global Constraints

- Capacity means a burst of up to 5,000 concurrent in-flight requests on the public homepage and common signal-filter paths, not 5,000 sustained requests per second.
- Normal public data freshness must remain within 60 seconds; Redis fresh TTL is 60 seconds and initial Nginx microcache TTL is 15 seconds.
- The bounded failure-only stale window is an additional 180 seconds; after it expires, return controlled `503 Retry-After` rather than indefinitely old data.
- Mobile LCP <= 2.5 s, INP <= 200 ms, CLS <= 0.1.
- Guest homepage cache-hit p95 TTFB <= 200 ms; `/api/signals` cache-hit p95 <= 250 ms; normal cold read-model p95 <= 500 ms.
- Default-key 5,000-concurrency burst: >= 99.5% success, p95 <= 1 s, p99 <= 2 s, no DB exhaustion, and one DB computation per cold key.
- Mixed 1,000-concurrency burst across <= 50 representative filter keys: p95 <= 1.5 s.
- `/api/dashboard` remains lightweight; `/api/signals` remains paginated, compact, and thumbnail-first.
- Guest/Free/VIP APIs never expose original listing URLs or phone numbers; only admin may receive them.
- Anonymous Nginx caching is bypassed by the `radar_session` cookie; Free/VIP/admin variants are never stored at the edge.
- User-facing signal eligibility continues to use latest valuation plus `services.signal_quality.actionable_signal_sql()`; `low_segment_confidence` remains a warning only.
- Guland publisher visibility and ranking remain tier-aware; no external LLM enters crawl, reprocess, or the public request path.
- Schema changes are additive, current query behavior remains available for rollback, and production load testing requires a controlled window.
- Never commit secrets, Redis credentials, database dumps, cache contents, logs, or raw load-test result blobs.

---

## 1. Approved Plan Set

Execute these plans in order. Each phase ends with a deploy/no-deploy gate and can be rolled back without reverting later source data.

| Phase | Plan | Working deliverable |
|---|---|---|
| 1 | `2026-08-01-homepage-performance-phase-1-read-model.md` | Set-based publisher SQL, durable dataset versions, signal-card read model, parity tooling, and read-model feature flag |
| 2 | `2026-08-01-homepage-performance-phase-2-shared-cache.md` | Bounded PostgreSQL pool, canonical Redis cache keys, single-flight/stale fallback, safe HTTP caching headers, invalidation/prewarm |
| 3 | `2026-08-01-homepage-performance-phase-3-frontend.md` | Canonical browser queries, signals-first filter flow, obsolete-request cancellation, and browser-level regression proof |
| 4 | `2026-08-01-homepage-performance-phase-4-production-capacity.md` | Redis/Nginx/Gunicorn/OS configuration, deployment safety, observability, progressive load tests, production verification, and final docs |

Do not begin a later phase until the preceding phase's tests and rollback gate pass. Phase 3 may be developed after Phase 2's interfaces are stable, but it must not deploy ahead of the response/cache contract it tests.

## 2. Measured Production Capacity Snapshot

Read-only preflight captured on 2026-08-01:

| Resource | Current production fact | Planning decision |
|---|---:|---|
| CPU | 2 vCPU | 3 Gunicorn workers x 4 threads; edge/cache absorbs client concurrency |
| RAM | 3,915 MB total, 2,582 MB available at sample time | Redis cache-only budget 256 MB; Nginx disk cache 512 MB |
| Swap | 4,095 MB total, 1,029 MB used | Watch swap during load; abort on sustained growth |
| Disk | 11 GB free on `/` | Nginx public cache capped at 512 MB |
| PostgreSQL | `max_connections=100`, `shared_buffers=128MB`, `work_mem=4MB` | App pool max 4 per worker; 12 app connections after worker change; preserve >=20 connections for jobs/admin/safety |
| Current Radar DB sessions | 8 idle | Existing 2 x 4 thread-local behavior confirmed |
| Redis | not installed | Install local-only Redis; persistence disabled because it is cache, not source of truth |
| Nginx | 2 auto workers on this host, `worker_connections=768`, gzip types commented | Raise to 4,096 connections/worker and enable JSON/JS/CSS compression |
| Service file limit | 524,288 for Nginx and Radar systemd services | Sufficient; set explicit Radar limit for reproducibility |
| Kernel `somaxconn` | 4,096 | Raise reversibly to 8,192 before the 5,000 stage |

These values must be re-read immediately before production changes. If CPU, RAM, PostgreSQL limits, other hosted sites, or connection usage materially differ, stop and amend this plan rather than copying the snapshot blindly.

## 3. Dependency and Runtime Decisions

Pin the following when their owning phase begins:

```text
psycopg[binary,pool]==3.3.4
redis==5.2.1
```

`psycopg` 3.3.4 supplies the pool extra for Python 3.12. `redis` 5.2.1 is intentionally selected for the Ubuntu 24.04 Redis 7.0 family instead of the newest client, whose current documented server floor is Redis 7.2. Phase 4 installs the Ubuntu security-maintained `redis-server` package and verifies the actual server/client pair before enabling the cache.

No npm dependency is added. Frontend pure-function tests use `node --test`. k6 remains an external load-generator binary and must not run on the production VPS.

## 4. Stable Interfaces Across Phases

Later phase plans rely on these names; do not rename them without updating all four plan documents.

- `db.public_dataset_versions.DATASET_SIGNALS = "signals"`
- `db.public_dataset_versions.DATASET_MARKET = "market"`
- `get_dataset_versions(conn, names: tuple[str, ...]) -> dict[str, int]`
- `bump_dataset_versions(conn, names: tuple[str, ...]) -> dict[str, int]`
- `SignalReadModelRefresh(mode: str, affected_rows: int, versions: dict[str, int], duration_ms: float)`
- `refresh_signal_card_read_model(conn, *, listing_ids: tuple[int, ...] | None, market_changed: bool = False) -> SignalReadModelRefresh`
- `load_signals_from_read_model()` uses the complete current `load_signals()` signature and returns the same dictionary contract.
- `CacheResult(payload: dict, status: str, load_ms: float)`, where status is one of `hit`, `miss`, `stale`, `bypass`, or `local_fallback`.
- `get_or_load_public_payload(*, endpoint: str, tier: str, versions: dict[str, int], query: dict, loader: Callable[[], dict], force_refresh: bool = False) -> CacheResult`
- `publish_dataset_versions(versions: dict[str, int]) -> None`

The application cache-key contract is:

```text
radar:public:v1:<endpoint>:<tier>:<version-tuple>:<sha256(canonical-json-query)>
```

The canonical query includes only response-changing parsed values. It sorts/deduplicates multi-value filters and ignores client-only `sigv`, unknown parameters, and raw parameter order.

## 5. Feature Flags and Configuration

Add these documented environment variables with safe-disabled defaults:

```dotenv
RADAR_SIGNAL_READ_MODEL_ENABLED=0
RADAR_PUBLIC_CACHE_ENABLED=0
RADAR_REDIS_URL=redis://127.0.0.1:6379/0
RADAR_CACHE_SCHEMA_VERSION=1
RADAR_PUBLIC_CACHE_FRESH_SECONDS=60
RADAR_PUBLIC_CACHE_STALE_SECONDS=180
RADAR_PUBLIC_CACHE_LOCK_SECONDS=5
RADAR_PUBLIC_CACHE_WAIT_SECONDS=0.25
RADAR_PUBLIC_DB_SLOTS=2
RADAR_PUBLIC_STATEMENT_TIMEOUT_MS=1500
RADAR_DB_POOL_MIN=1
RADAR_DB_POOL_MAX=4
RADAR_DB_POOL_TIMEOUT_SECONDS=1.0
```

Rollout order:

1. Deploy code with both feature flags `0`.
2. Create/backfill the read model and pass parity.
3. Enable `RADAR_SIGNAL_READ_MODEL_ENABLED=1`; soak and measure.
4. Install/start Redis and prove local health.
5. Enable `RADAR_PUBLIC_CACHE_ENABLED=1`; soak and failure-test.
6. Deploy frontend request reduction.
7. Enable Nginx microcache only after guest/private bypass tests.

Rollback order is the reverse; disabling Nginx cache is always the first response to any privacy concern.

## 6. Commit and Review Boundaries

Use one focused commit per task in the phase plans. Expected high-level series:

```text
perf: use set-based publisher joins in signal feed
feat: add public dataset versions
feat: add signal card read model
feat: switch signal reads behind feature flag
feat: publish read model after data changes
perf: add bounded postgres connection pool
feat: add canonical public cache keys
feat: add redis single-flight response cache
feat: cache safe public endpoints by tier
feat: invalidate and prewarm public caches
perf: make signal filters load cards first
ops: add redis and nginx cache configuration
test: add public burst load profiles
docs: document production performance operations
```

Before every commit:

```powershell
git diff --check
git status --short
```

Before every push/deploy, pull/rebase current `origin/main`, preserve unrelated work, and rerun the phase's focused plus full relevant tests.

## 7. Cross-Phase Release Gates

### Gate A: SQL hotfix

- Existing feed/redaction/source-policy tests pass.
- Production `ANALYZE` timestamps are fresh on the hot tables.
- Public cold `/api/signals?limit=30&include_total=0` returns to sub-second or the release stops for new `EXPLAIN (ANALYZE, BUFFERS)` evidence.

### Gate B: read model

- Full and representative filtered parity reports contain zero unexplained differences.
- Feature-off behavior is unchanged.
- Feature-on cold p95 is <= 500 ms locally and on VPS-localhost.
- Refresh failure leaves the previous version readable.

### Gate C: Redis/application cache

- Two Gunicorn workers share a cache entry and distributed lock.
- 100 identical cold requests perform one loader call.
- Redis-stop drill yields bounded DB work plus stale/controlled 503, not a stampede.
- Guest/Free/VIP/admin cache separation and redaction tests pass.

### Gate D: frontend

- One settled signal filter makes one high-priority signal request.
- Counts occur only after cards are unblocked; dashboard metadata is not refetched on the signal tab.
- Old responses cannot overwrite newer filter results.
- Browser trace shows faster useful cards with no visual/filter regression.

### Gate E: origin capacity

- `nginx -t`, systemd verification, Redis health, schema/read-model parity, and public/private cache smoke all pass.
- 100 -> 500 -> 1,000 stages pass before 5,000 is attempted.
- Load comes from outside the production VPS.
- Abort thresholds from the approved spec remain active.

## 8. Final Completion Evidence

The work is complete only when the final report separates:

1. local unit/integration results;
2. local PostgreSQL query plans and cold/warm timings;
3. VPS-local service/DB/cache evidence;
4. external load-generator percentiles and errors;
5. rendered public browser/Core Web Vitals evidence;
6. commit, push, deployed commit, systemd, Redis, Nginx, and rollback state.

An HTTP 200, local test pass, or pushed commit alone is not production completion.
