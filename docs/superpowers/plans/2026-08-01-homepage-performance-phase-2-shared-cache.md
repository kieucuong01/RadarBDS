# Homepage Performance Phase 2 Shared Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound PostgreSQL connections and add a shared, tier-safe Redis response cache that collapses identical cold requests into one database computation and serves bounded stale data during dependency failures.

**Architecture:** Replace per-thread permanent connections with one lazy psycopg pool per process, capped at four connections. Build deterministic cache keys from parsed filter state and durable dataset versions. Redis stores fresh/stale JSON plus token-owned locks across Gunicorn workers; a small per-process fallback and semaphore bound work when Redis is unavailable.

**Tech Stack:** Python 3.12, Flask, `psycopg[binary,pool]==3.3.4`, `redis==5.2.1`, PostgreSQL dataset versions/read model from Phase 1, pytest, fake Redis unit tests, optional real Redis integration test.

## Global Constraints

- Phase 1 release gate must pass before this plan starts.
- PostgreSQL is the source of truth for dataset versions; Redis mirrors them and may be discarded at any time.
- Pool defaults are min 1, max 4, acquire timeout 1.0 seconds per process. With Phase 4's 3 workers, the web app may use at most 12 PostgreSQL connections.
- Fresh TTL is 60 seconds; failure-only stale retention is an additional 180 seconds.
- Lock TTL is 5 seconds and waiter budget is 250 ms after the read model has proven p95 <= 500 ms.
- A Redis miss may create one loader computation per canonical key across all workers.
- Redis failure admits at most two DB fallback loaders per process; excess work returns stale or controlled `503 Retry-After`.
- Guest/Free/VIP cache values are separated by effective tier. Admin bypasses response caching.
- Anonymous public responses may be edge-cacheable; any `radar_session` request remains `private, no-store`.
- Never cache an exception, non-2xx response, `Set-Cookie` response, phone number, or original source URL in the guest namespace.
- Every task uses TDD and ends in a focused commit.

---

## File Structure

| File | Responsibility |
|---|---|
| `requirements.txt` | Pin psycopg pool and Redis client dependencies |
| `db/connection.py` | Lazy bounded pool, acquire timeout, connection configuration, shutdown |
| `services/public_cache_keys.py` | Canonical parsed-query JSON and versioned Redis keys |
| `services/public_cache.py` | Redis/local fresh+stale reads, single-flight lock, bounded fallback, metrics result |
| `services/public_data_publish.py` | Publish committed version pointers and request prewarming |
| `services/public_prewarm.py` | Safe no-cookie warm requests for a small configured route set |
| `config/public_cache_warm_routes.json` | Default/popular public routes only; no secrets or user identifiers |
| `app.py` | Endpoint cache wiring, HTTP cache classification, controlled 503, timing headers |
| `auth/core.py` | Preserve rate-limit behavior; no Redis dependency added to authentication in this phase |
| `.env.example` | Cache/pool settings with safe-disabled cache default |
| `tests/test_postgres_connection.py` | Pool caps, acquire timeout, commit/rollback/return tests |
| `tests/test_public_cache_keys.py` | Canonical equivalence, bounds, tier/version separation |
| `tests/test_public_cache.py` | Fresh/stale/single-flight/failure/backpressure tests |
| `tests/test_public_cache_headers.py` | Guest cacheability and authenticated/private bypass tests |
| `tests/test_public_cache_redis_integration.py` | Opt-in real Redis cross-instance lock/version tests |

## Task 1: Add a Bounded PostgreSQL Connection Pool

**Files:**
- Modify: `requirements.txt`
- Modify: `db/connection.py:12-285`
- Modify: `tests/test_postgres_connection.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `DatabasePoolBusy`
- Produces: lazy `_get_pool() -> psycopg_pool.ConnectionPool`
- Preserves: `connect()` as an explicit fresh connection for legacy callers
- Preserves: `get_conn()` context-manager commit/rollback semantics
- Changes: `close_all()` closes/resets the process pool instead of one thread-local connection

- [ ] **Step 1: Write failing pool lifecycle tests**

```python
def test_get_conn_returns_connection_to_pool_after_commit(monkeypatch):
    from db import connection

    fake_pool = FakePool()
    monkeypatch.setattr(connection, "_get_pool", lambda: fake_pool)

    with connection.get_conn() as conn:
        conn.execute("SELECT 1")

    assert fake_pool.raw.commit_calls == 1
    assert fake_pool.raw.rollback_calls == 0
    assert fake_pool.returned == [fake_pool.raw]


def test_get_conn_rolls_back_and_returns_connection_on_error(monkeypatch):
    from db import connection

    fake_pool = FakePool()
    monkeypatch.setattr(connection, "_get_pool", lambda: fake_pool)

    with pytest.raises(RuntimeError, match="boom"):
        with connection.get_conn():
            raise RuntimeError("boom")

    assert fake_pool.raw.rollback_calls == 1
    assert fake_pool.returned == [fake_pool.raw]


def test_pool_timeout_becomes_database_pool_busy(monkeypatch):
    from db import connection

    monkeypatch.setattr(connection, "_get_pool", lambda: TimeoutPool())
    with pytest.raises(connection.DatabasePoolBusy):
        with connection.get_conn():
            pass
```

The fake pool must expose `getconn` with a numeric `timeout` keyword, `putconn(raw)`, and `close()` so tests prove the exact lifecycle without opening PostgreSQL.

- [ ] **Step 2: Run and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_postgres_connection.py -q
```

Expected: FAIL because no pool or `DatabasePoolBusy` exists.

- [ ] **Step 3: Pin the compatible pool dependency**

Replace the existing psycopg line with:

```text
psycopg[binary,pool]==3.3.4
```

Do not add Redis to this commit; dependency ownership stays with Task 3.

- [ ] **Step 4: Implement a lazy process-local pool**

Remove `_local = threading.local()` and add:

```python
import atexit
from psycopg_pool import ConnectionPool, PoolTimeout

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


class DatabasePoolBusy(RuntimeError):
    """Raised when the bounded PostgreSQL pool cannot admit work in time."""


def _pool_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _pool_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _configure_pooled_connection(raw) -> None:
    raw.execute("SET TIME ZONE 'Asia/Bangkok'")
    raw.commit()


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            minimum = _pool_int("RADAR_DB_POOL_MIN", 1, 0, 4)
            maximum = _pool_int("RADAR_DB_POOL_MAX", 4, 1, 12)
            if minimum > maximum:
                minimum = maximum
            _pool = ConnectionPool(
                conninfo=_database_url(),
                min_size=minimum,
                max_size=maximum,
                timeout=_pool_float("RADAR_DB_POOL_TIMEOUT_SECONDS", 1.0, 0.1, 10.0),
                max_idle=300.0,
                max_lifetime=1800.0,
                configure=_configure_pooled_connection,
                open=False,
                name="radar-bds",
            )
            _pool.open(wait=False)
    return _pool
```

Implement `get_conn()` with explicit ownership:

```python
@contextmanager
def get_conn():
    pool = _get_pool()
    timeout = _pool_float("RADAR_DB_POOL_TIMEOUT_SECONDS", 1.0, 0.1, 10.0)
    try:
        raw = pool.getconn(timeout=timeout)
    except PoolTimeout as exc:
        raise DatabasePoolBusy("PostgreSQL connection pool is saturated") from exc

    conn = PgConnection(raw)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(raw)
```

Implement safe shutdown:

```python
def close_all() -> None:
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.close(timeout=5.0)


atexit.register(close_all)
```

Keep `connect()` as a direct `psycopg.connect()` wrapper for callers that explicitly own/close a fresh connection.

- [ ] **Step 5: Document pool environment values**

Add to `.env.example`:

```dotenv
RADAR_DB_POOL_MIN=1
RADAR_DB_POOL_MAX=4
RADAR_DB_POOL_TIMEOUT_SECONDS=1.0
```

- [ ] **Step 6: Run pool and PostgreSQL integration tests**

```powershell
& $py -X utf8 -m pytest `
  tests\test_postgres_connection.py `
  tests\test_market_data_performance.py `
  tests\test_price_history.py -q
```

Expected: PASS. During a threaded test, observed checked-out connections never exceed `RADAR_DB_POOL_MAX`.

- [ ] **Step 7: Commit**

```powershell
git add requirements.txt db/connection.py tests/test_postgres_connection.py .env.example
git commit -m "perf: add bounded postgres connection pool"
```

## Task 2: Add Canonical Public Cache Keys

**Files:**
- Create: `services/public_cache_keys.py`
- Create: `tests/test_public_cache_keys.py`

**Interfaces:**
- Produces: `canonical_query(query: Mapping[str, object]) -> dict[str, object]`
- Produces: `build_public_cache_key(endpoint, tier, versions, query, schema_version=1) -> str`
- Consumes: parsed/clamped endpoint values, never raw cookies or raw query strings

- [ ] **Step 1: Write failing equivalence and separation tests**

```python
def test_equivalent_multi_value_filters_share_one_key():
    a = build_public_cache_key(
        endpoint="signals",
        tier="guest",
        versions={"signals": 7},
        query={"wards": ["Tan An", "Hiep An", "Tan An"], "sources": ["guland", "facebook"], "page": 1},
    )
    b = build_public_cache_key(
        endpoint="signals",
        tier="guest",
        versions={"signals": 7},
        query={"page": 1, "sources": ["facebook", "guland"], "wards": ["Hiep An", "Tan An"]},
    )
    assert a == b


@pytest.mark.parametrize(
    "change",
    (
        {"tier": "free"},
        {"versions": {"signals": 8}},
        {"query": {"wards": ["Tan An"], "page": 2}},
    ),
)
def test_tier_version_and_page_change_the_key(change):
    base = {"endpoint": "signals", "tier": "guest", "versions": {"signals": 7}, "query": {"wards": ["Tan An"], "page": 1}}
    changed = {**base, **change}
    assert build_public_cache_key(**base) != build_public_cache_key(**changed)


def test_client_only_and_unknown_fields_are_not_passed_to_key_builder():
    canonical = canonical_query({"page": 1, "sigv": "client-only", "unknown": "x"})
    assert canonical == {"page": 1}
```

- [ ] **Step 2: Run and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_public_cache_keys.py -q
```

- [ ] **Step 3: Implement deterministic canonical JSON**

```python
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

ALLOWED_QUERY_FIELDS = frozenset({
    "active_city", "wards", "sources", "prop_types", "only_drops",
    "trend_period", "mos_min", "area_min", "area_max", "price_min",
    "price_max", "area_ranges", "price_ranges", "keyword", "date_range",
    "include_trend", "include_guland_high_activity", "sort", "page",
    "limit", "include_total",
})
MULTI_VALUE_FIELDS = frozenset({
    "wards", "sources", "prop_types", "area_ranges", "price_ranges",
})
VALID_TIERS = frozenset({"guest", "free", "vip", "admin"})
VALID_ENDPOINTS = frozenset({"signals", "counts", "dashboard"})


def _scalar(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return float(format(value, ".12g"))
    text = str(value).strip()
    return text


def canonical_query(query: Mapping[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key in sorted(ALLOWED_QUERY_FIELDS):
        if key not in query or query[key] is None:
            continue
        value = query[key]
        if key in MULTI_VALUE_FIELDS:
            items = value if isinstance(value, (list, tuple, set, frozenset)) else (value,)
            normalized[key] = sorted({_scalar(item) for item in items if str(item).strip()})
        else:
            normalized[key] = _scalar(value)
    return normalized


def build_public_cache_key(
    *,
    endpoint: str,
    tier: str,
    versions: Mapping[str, int],
    query: Mapping[str, object],
    schema_version: int = 1,
) -> str:
    if endpoint not in VALID_ENDPOINTS or tier not in VALID_TIERS:
        raise ValueError("invalid public cache namespace")
    version_tuple = ",".join(
        f"{name}={int(versions[name])}" for name in sorted(versions)
    )
    body = json.dumps(
        canonical_query(query),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    return f"radar:public:v{int(schema_version)}:{endpoint}:{tier}:{version_tuple}:{digest}"
```

Unknown raw parameters are discarded before this boundary; callers must pass the complete parsed response-changing state so an omitted field cannot collide.

- [ ] **Step 4: Run tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_public_cache_keys.py -q
git add services/public_cache_keys.py tests/test_public_cache_keys.py
git commit -m "feat: add canonical public cache keys"
```

## Task 3: Add Redis Fresh/Stale Storage and Distributed Single-Flight

**Files:**
- Modify: `requirements.txt`
- Create: `services/public_cache.py`
- Create: `tests/test_public_cache.py`
- Create: `tests/test_public_cache_redis_integration.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `CacheResult`
- Produces: `PublicCacheBusy(retry_after: int)`
- Produces: `get_or_load_public_payload(*, endpoint: str, tier: str, versions: dict[str, int], query: dict, loader: Callable[[], dict], force_refresh: bool = False) -> CacheResult`
- Produces: `get_current_dataset_versions(names) -> dict[str, int]`
- Produces: `publish_dataset_versions(versions) -> None`

- [ ] **Step 1: Write failing fresh, stale, lock, and failure tests**

Required tests:

```python
def test_fresh_hit_does_not_call_loader(fake_redis):
    cache = PublicResponseCache(redis_client=fake_redis, clock=FakeClock(100.0))
    cache.store_for_test("key", {"signals": [1]}, stored_at=99.0)
    calls = 0

    def loader():
        nonlocal calls
        calls += 1
        return {"signals": [2]}

    result = cache.get_or_load("key", loader)
    assert result.status == "hit"
    assert result.payload == {"signals": [1]}
    assert calls == 0


def test_one_hundred_waiters_execute_one_loader(fake_redis):
    cache_a = PublicResponseCache(redis_client=fake_redis)
    cache_b = PublicResponseCache(redis_client=fake_redis)
    barrier = threading.Barrier(100)
    calls = 0
    lock = threading.Lock()

    def load():
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.05)
        return {"signals": [1]}

    def request(index):
        barrier.wait()
        cache = cache_a if index % 2 else cache_b
        return cache.get_or_load("same-key", load).payload

    with ThreadPoolExecutor(max_workers=100) as pool:
        payloads = list(pool.map(request, range(100)))

    assert calls == 1
    assert payloads == [{"signals": [1]}] * 100


def test_loader_error_serves_only_bounded_stale(fake_redis):
    clock = FakeClock(200.0)
    cache = PublicResponseCache(redis_client=fake_redis, clock=clock)
    cache.store_for_test("key", {"signals": [1]}, stored_at=100.0)
    result = cache.get_or_load("key", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert result.status == "stale"
    assert result.payload == {"signals": [1]}
    clock.value = 400.0
    with pytest.raises(RuntimeError, match="db down"):
        cache.get_or_load("key", lambda: (_ for _ in ()).throw(RuntimeError("db down")))


def test_lock_release_requires_ownership_token(fake_redis):
    cache = PublicResponseCache(redis_client=fake_redis)
    fake_redis.set("key:lock", "new-owner", px=5000)
    cache.release_lock("key:lock", "old-owner")
    assert fake_redis.get("key:lock") == b"new-owner"
```

Add Redis-down tests proving the per-process DB loader concurrency never exceeds `RADAR_PUBLIC_DB_SLOTS=2` and the third concurrent miss raises `PublicCacheBusy` when no stale value exists.

- [ ] **Step 2: Run and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_public_cache.py -q
```

- [ ] **Step 3: Pin Redis and add configuration**

Add:

```text
redis==5.2.1
```

Add safe defaults to `.env.example`:

```dotenv
RADAR_PUBLIC_CACHE_ENABLED=0
RADAR_REDIS_URL=redis://127.0.0.1:6379/0
RADAR_CACHE_SCHEMA_VERSION=1
RADAR_PUBLIC_CACHE_FRESH_SECONDS=60
RADAR_PUBLIC_CACHE_STALE_SECONDS=180
RADAR_PUBLIC_CACHE_LOCK_SECONDS=5
RADAR_PUBLIC_CACHE_WAIT_SECONDS=0.25
RADAR_PUBLIC_DB_SLOTS=2
RADAR_PUBLIC_STATEMENT_TIMEOUT_MS=1500
```

- [ ] **Step 4: Implement cache records and token-safe lock release**

Use two values per key:

```text
<key>:fresh  TTL 60 seconds
<key>:stale  TTL 240 seconds (60 fresh + 180 extra stale)
<key>:lock   TTL 5 seconds
```

Serialized value:

```json
{"stored_at": 1760000000.0, "payload": {"signals": []}}
```

Implement token release with one Lua comparison:

```python
_RELEASE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def release_lock(self, lock_key: str, token: str) -> None:
    try:
        self.redis.eval(_RELEASE_LOCK_LUA, 1, lock_key, token)
    except RedisError:
        logger.warning("Redis lock release failed", exc_info=True)
```

The loader path is exactly:

```python
def get_or_load(self, key: str, loader: Callable[[], dict]) -> CacheResult:
    fresh = self._read_json(f"{key}:fresh")
    if fresh is not None:
        return CacheResult(fresh["payload"], "hit", 0.0)

    stale = self._read_json(f"{key}:stale")
    token = secrets.token_hex(16)
    lock_key = f"{key}:lock"
    if self._acquire_lock(lock_key, token):
        started = time.perf_counter()
        try:
            payload = self._bounded_load(loader)
            self._store(key, payload)
            return CacheResult(payload, "miss", (time.perf_counter() - started) * 1000)
        except Exception:
            if stale is not None and self._stale_age_is_allowed(stale):
                return CacheResult(stale["payload"], "stale", 0.0)
            raise
        finally:
            self.release_lock(lock_key, token)

    if stale is not None and self._stale_age_is_allowed(stale):
        return CacheResult(stale["payload"], "stale", 0.0)

    deadline = self.clock() + self.wait_seconds
    while self.clock() < deadline:
        time.sleep(random.uniform(0.015, 0.035))
        fresh = self._read_json(f"{key}:fresh")
        if fresh is not None:
            return CacheResult(fresh["payload"], "hit", 0.0)
    raise PublicCacheBusy(retry_after=1)
```

`_bounded_load()` uses a module-level `threading.BoundedSemaphore(RADAR_PUBLIC_DB_SLOTS)`. It performs a non-blocking acquire; on failure it raises `PublicCacheBusy(1)`. Keep an in-process bounded LRU fresh/stale copy so Redis-down requests can reuse recently generated safe payloads, capped at 256 entries.

- [ ] **Step 5: Implement version mirror behavior**

Version lookup order:

1. Redis key `radar:dataset-version:<name>`;
2. five-second per-process version cache;
3. one PostgreSQL primary-key lookup through `get_dataset_versions()`;
4. write the result back to Redis without expiry.

`publish_dataset_versions()` updates Redis and the local mirror only after the PostgreSQL publishing transaction has committed. Redis errors are logged and do not roll back correct database data.

- [ ] **Step 6: Add an opt-in real Redis integration test**

Skip unless `RADAR_TEST_REDIS_URL` is set. Use a unique UUID key prefix, run two `PublicResponseCache` instances, verify cross-instance lock/value reuse, then delete only that prefix's keys in test cleanup.

- [ ] **Step 7: Run unit tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_public_cache.py tests\test_public_cache_redis_integration.py -q
git add requirements.txt services/public_cache.py tests/test_public_cache.py tests/test_public_cache_redis_integration.py .env.example
git commit -m "feat: add redis single-flight response cache"
```

## Task 4: Wire Safe Public Endpoints and HTTP Cache Classification

**Files:**
- Modify: `app.py:222-265`
- Modify: `app.py:3961-4048`
- Modify: `app.py:4513-4694`
- Modify: `app.py:1744-1748`
- Create: `tests/test_public_cache_headers.py`
- Modify: `tests/test_market_data_performance.py`
- Modify: `tests/test_security_hardening.py`
- Modify: `tests/test_guest_visibility.py`

**Interfaces:**
- Consumes: `get_or_load_public_payload()`, `get_current_dataset_versions()`
- Produces response headers: `X-Radar-Cache`, `Server-Timing`, internal `X-Radar-Public-Cache: 1`
- Produces controlled error: `503 {"error":"temporarily_busy","retry_after":1}` plus `Retry-After: 1`

- [ ] **Step 1: Write failing cache/header/security tests**

```python
def test_guest_signal_response_is_public_cache_candidate(client):
    response = client.get("/api/signals?include_total=0")
    assert response.status_code == 200
    assert response.headers["X-Radar-Public-Cache"] == "1"
    assert response.headers["Cache-Control"] == "public, max-age=15, s-maxage=15, stale-while-revalidate=180, stale-if-error=180"
    assert "Cookie" in response.headers["Vary"]


def test_session_cookie_forces_private_no_store(client):
    client.set_cookie(SESSION_COOKIE_NAME, "test-session")
    response = client.get("/api/signals?include_total=0")
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "X-Radar-Public-Cache" not in response.headers


def test_authorization_header_forces_private_no_store(client):
    response = client.get(
        "/api/signals?include_total=0",
        headers={"Authorization": "Bearer cache-bypass-probe"},
    )
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "X-Radar-Public-Cache" not in response.headers


def test_admin_payload_never_uses_public_cache(monkeypatch, client):
    monkeypatch.setattr(radar_app, "current_tier", lambda: "admin")
    response = client.get("/api/signals?include_total=0")
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Radar-Cache"] == "bypass"
```

Add a regression test that injects a phone and source URL in the loader result, then asserts the guest cached value contains the already-redacted serializer output only.

- [ ] **Step 2: Run and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_public_cache_headers.py tests\test_security_hardening.py -q
```

- [ ] **Step 3: Build parsed/clamped endpoint query dictionaries**

For all three endpoints, construct the cache query from the already parsed values, with these exact bounds before both key and loader:

```python
page = min(max(page, 1), 2_000)
limit = min(max(limit, 1), 100)
wards = sorted(dict.fromkeys(wards or ()))[:64]
sources = sorted(dict.fromkeys(sources or ()))[:4]
prop_types = sorted(dict.fromkeys(prop_types or ()))[:8]
area_ranges = sorted(dict.fromkeys(range_kwargs["area_ranges"]))[:12]
price_ranges = sorted(dict.fromkeys(range_kwargs["price_ranges"]))[:12]
keyword = keyword[:80]
```

Use the same bounded values for SQL; never key one value and query another.

- [ ] **Step 4: Replace per-process route caches**

Delete `_DASHBOARD_CACHE`, `_SIGNAL_CACHE`, and their mutation helpers after their tests move to the new service. Admin and explicit local/admin `cache_refresh=1` calls pass `force_refresh=True` and `tier="admin"`, which yields `status="bypass"`.

Endpoint dependency versions:

```python
SIGNAL_DATASETS = (DATASET_SIGNALS,)
DASHBOARD_DATASETS = (DATASET_SIGNALS, DATASET_MARKET)
```

Use signals for `/api/signals` and `/api/counts`; use both for `/api/dashboard`.

- [ ] **Step 5: Return safe JSON and cache diagnostics**

```python
def _public_json_response(result: CacheResult, *, tier: str):
    response = jsonify(result.payload)
    response.headers["X-Radar-Cache"] = result.status
    response.headers["Server-Timing"] = f'app_cache;desc="{result.status}", load;dur={result.load_ms:.2f}'
    is_anonymous = (
        tier == "guest"
        and not request.cookies.get(SESSION_COOKIE_NAME)
        and not request.headers.get("Authorization")
    )
    if is_anonymous and response.status_code == 200 and "Set-Cookie" not in response.headers:
        response.headers["X-Radar-Public-Cache"] = "1"
        response.headers["Cache-Control"] = "public, max-age=15, s-maxage=15, stale-while-revalidate=180, stale-if-error=180"
        response.headers["Vary"] = "Cookie"
        response.headers.pop("Pragma", None)
        response.headers.pop("Expires", None)
    else:
        response.headers["Cache-Control"] = "private, no-store"
    return response
```

Catch `PublicCacheBusy` at the route boundary:

```python
response = jsonify({"error": "temporarily_busy", "retry_after": exc.retry_after})
response.status_code = 503
response.headers["Retry-After"] = str(exc.retry_after)
response.headers["Cache-Control"] = "no-store"
return response
```

Update `add_response_headers()` so it preserves the explicitly classified allowlist responses but retains `no-store` for every other API route.

- [ ] **Step 6: Mark only anonymous homepage HTML as edge-cacheable**

In `index()`, render normally, then add `X-Radar-Public-Cache: 1`, the same public Cache-Control, and `Vary: Cookie` only when `radar_session` and `Authorization` are both absent. `/bds-da-luu`, auth routes, admin routes, checkout/order routes, and any response with `Set-Cookie` remain private/no-store.

- [ ] **Step 7: Run route, masking, and security tests**

```powershell
& $py -X utf8 -m pytest `
  tests\test_public_cache_headers.py `
  tests\test_public_cache.py `
  tests\test_market_data_performance.py `
  tests\test_security_hardening.py `
  tests\test_guest_visibility.py `
  tests\test_source_policy.py -q
```

Expected: PASS. Search cached guest JSON for known fixture phone/source URL values and assert absent.

- [ ] **Step 8: Commit**

```powershell
git add app.py tests/test_public_cache_headers.py tests/test_market_data_performance.py tests/test_security_hardening.py tests/test_guest_visibility.py
git commit -m "feat: cache safe public endpoints by tier"
```

## Task 5: Publish Versions and Prewarm Common Routes After Data Changes

**Files:**
- Modify: `services/public_data_publish.py`
- Create: `services/public_prewarm.py`
- Create: `config/public_cache_warm_routes.json`
- Create: `tests/test_public_prewarm.py`
- Modify: `tests/test_signal_read_model.py`

**Interfaces:**
- Produces: `prewarm_public_routes(base_url, routes, timeout_seconds=5.0) -> dict`
- Extends: `publish_public_data()` to mirror committed versions then prewarm
- Preserves: data transaction success when Redis/prewarm fails

- [ ] **Step 1: Write failing commit-order and safe-prewarm tests**

```python
def test_version_is_published_only_after_database_context_exits(monkeypatch):
    events = []
    monkeypatch.setattr(public_data_publish, "get_conn", lambda: FakeCommitContext(events))
    monkeypatch.setattr(public_data_publish, "refresh_signal_card_read_model", lambda *args, **kwargs: FakeRefresh({"signals": 9}))
    monkeypatch.setattr(public_data_publish, "publish_dataset_versions", lambda versions: events.append(("redis", versions)))
    monkeypatch.setattr(public_data_publish, "prewarm_configured_routes", lambda: events.append("prewarm") or {"ok": 1})

    public_data_publish.publish_public_data(listing_ids=(1,), strict=True)
    assert events == ["db-enter", "db-exit-commit", ("redis", {"signals": 9}), "prewarm"]


def test_prewarm_never_sends_cookies_or_authorization(monkeypatch):
    captured = []
    monkeypatch.setattr(public_prewarm, "urlopen", lambda request, timeout: captured.append(request) or FakeResponse(200))
    public_prewarm.prewarm_public_routes("http://127.0.0.1:5000", ["/api/signals?include_total=0"])
    headers = dict(captured[0].header_items())
    assert "Cookie" not in headers
    assert "Authorization" not in headers
```

- [ ] **Step 2: Run and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_public_prewarm.py tests\test_signal_read_model.py -q
```

- [ ] **Step 3: Add the bounded warm-route configuration**

```json
[
  "/",
  "/api/signals?include_total=0&limit=30&page=1&sort=newest",
  "/api/counts",
  "/api/dashboard",
  "/api/signals?include_total=0&limit=30&page=1&sort=newest&source=facebook",
  "/api/signals?include_total=0&limit=30&page=1&sort=newest&source=guland"
]
```

Reject non-relative paths, hosts other than the configured base URL, fragments, credentials, more than 20 routes, or any route outside `/`, `/api/signals`, `/api/counts`, and `/api/dashboard`.

- [ ] **Step 4: Implement best-effort no-cookie prewarming**

Use `urllib.request.Request` with `User-Agent: RadarBDS-Prewarm/1.0`, no cookie/auth headers, a five-second timeout, response-body cap of 2 MB, and status-only logs. Return counts for attempted/succeeded/failed plus per-path status; never return or log bodies.

Default base URL for process-local application cache warming:

```text
RADAR_PUBLIC_PREWARM_URL=http://127.0.0.1:5000
```

- [ ] **Step 5: Extend the publication order**

`publish_public_data()` must:

1. refresh read model and bump durable versions inside the DB context;
2. exit/commit the context;
3. call `publish_dataset_versions(result.versions)`;
4. call prewarm only when `RADAR_PUBLIC_CACHE_ENABLED=1`;
5. report Redis/prewarm failures separately without changing `status="ok"` for already committed source/read-model data.

- [ ] **Step 6: Run publication/prewarm tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_public_prewarm.py tests\test_signal_read_model.py tests\test_public_cache.py -q
git add services/public_data_publish.py services/public_prewarm.py config/public_cache_warm_routes.json tests/test_public_prewarm.py tests/test_signal_read_model.py
git commit -m "feat: invalidate and prewarm public caches"
```

## Task 6: Phase 2 Verification, Failure Drill, Documentation, and Gate

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/architecture.md`
- Modify: `docs/operations.md`
- Modify: `docs/dev_commands.md`
- Test: all Phase 1/2 suites plus opt-in Redis integration

**Interfaces:**
- Produces: exact Redis/pool env and failure-recovery runbook
- Produces: evidence of cross-instance request collapse and controlled Redis-down behavior

- [ ] **Step 1: Run static and focused verification**

```powershell
& $py -X utf8 -m py_compile `
  app.py `
  db\connection.py `
  services\public_cache_keys.py `
  services\public_cache.py `
  services\public_data_publish.py `
  services\public_prewarm.py
& $py -X utf8 -m pytest `
  tests\test_postgres_connection.py `
  tests\test_public_cache_keys.py `
  tests\test_public_cache.py `
  tests\test_public_cache_headers.py `
  tests\test_public_cache_redis_integration.py `
  tests\test_public_prewarm.py `
  tests\test_signal_read_model.py `
  tests\test_market_data_performance.py `
  tests\test_guest_visibility.py `
  tests\test_source_policy.py `
  tests\test_security_hardening.py -q
git diff --check
```

- [ ] **Step 2: Update architecture and operations docs**

Document exact key format, TTLs, lock/wait behavior, version source of truth, local fallback cap, pool equation, required Redis health commands, version inspection, cache status headers, prewarm output, and rollback flags.

- [ ] **Step 3: Commit docs**

```powershell
git add AGENTS.md docs/architecture.md docs/operations.md docs/dev_commands.md
git commit -m "docs: document shared public cache operations"
```

- [ ] **Step 4: Deploy code with cache disabled**

Deploy `RADAR_PUBLIC_CACHE_ENABLED=0`, verify psycopg pool status under ordinary traffic, confirm PostgreSQL Radar sessions remain <= 12, and prove legacy/read-model endpoint correctness.

- [ ] **Step 5: Enable Redis only after Phase 4 service install task**

Phase 2 application code can merge before Redis exists, but the production flag remains `0` until Phase 4 installs and validates Redis. After Redis is active, set the flag to `1`, restart the app, warm routes, and run the failure drill.

- [ ] **Step 6: Prove request collapse and Redis-down behavior**

- Against localhost with two or more Gunicorn workers, send 100 identical simultaneous cold-key requests and verify one cache miss/loader computation.
- Stop Redis only during the controlled drill; verify Nginx/app stale or at most two DB fallbacks per process, no pool exhaustion, and controlled 503 beyond the bound.
- Restart Redis, verify version bootstrap from PostgreSQL, warm routes, and confirm cache hits resume.

- [ ] **Step 7: Apply the Phase 2 gate**

Pass only when:

- the real Redis integration test passes;
- shared hit and single-flight work across process instances;
- guest/Free/VIP/admin separation and redaction pass;
- PostgreSQL connections stay within budget;
- Redis outage does not produce a DB stampede;
- both `RADAR_PUBLIC_CACHE_ENABLED=0` and `1` rollback paths are tested.

If privacy, version, lock, or failure behavior is wrong, disable the cache flag immediately and do not enable Nginx edge caching.
