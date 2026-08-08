# `/api/heatmap` SQL Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce uncached local `/api/heatmap` p95 to at most 300 ms for every representative scope while preserving the endpoint contract and market-signal semantics.

**Architecture:** Keep `api_heatmap()` and the public JSON shape unchanged. Retain the materialized listing prefilter, but replace the two materialized latest-valuation CTEs with bounded `LEFT JOIN LATERAL ... ORDER BY computed_at DESC, id DESC LIMIT 1` lookups that use the existing composite indexes.

**Tech Stack:** Python 3.12, Flask, PostgreSQL 17, psycopg-compatible database wrapper, pytest

## Global Constraints

- Work in `C:\Users\ASUS\Documents\Claude\Projects\Radar BDS\.worktrees\p0-p1-foundation` on `codex/p0-p1-foundation`.
- Follow strict TDD: write and observe the focused regression test failing before editing `services/market_data.py`.
- Keep `load_market_opportunities()`'s signature and response keys unchanged.
- Preserve all source, ward, property, range, date, keyword, publisher, tier, MOS, outlier, and actionable-signal behavior.
- Keep `filtered_listings AS MATERIALIZED` and the existing `_read_conn()` bounded pool scope.
- Do not add a schema migration, index, response cache, read model, feature flag, frontend change, or production deployment.
- `/api/heatmap` remains outside the shared public-cache allowlist and must not gain `X-Radar-Public-Cache`.
- The latency gate is p95 <= 300 ms for each scope over at least 20 uncached loader executions, including the first. Application/HTTP response caching is disabled; PostgreSQL/OS buffers are not flushed.
- A timeout or query error is unverified/failure, never an empty successful payload.
- Preserve unrelated work and the ignored `.pytest_cache/`/`.playwright-cli/` artifacts.

---

## File Structure

- Modify `tests/test_market_data_performance.py`: add one focused regression contract that fails when latest valuation is materialized and repeatedly scanned instead of retrieved through bounded indexed lateral lookups.
- Modify `services/market_data.py`: rewrite only the SQL inside `load_market_opportunities()`; do not change route parsing or Python response shaping.
- Read `docs/superpowers/specs/2026-08-09-api-heatmap-sql-optimization-design.md`: source of truth for scope, baseline, safety boundaries, and acceptance measurements.

### Task 1: Replace repeated valuation CTE scans with indexed latest-row lookups

**Files:**
- Modify: `tests/test_market_data_performance.py:1251-1341`
- Modify: `services/market_data.py:1767-1930`
- Reference: `db/schema.py:346-394`
- Reference: `docs/superpowers/specs/2026-08-09-api-heatmap-sql-optimization-design.md`

**Interfaces:**
- Consumes: `load_market_opportunities(db_path, sources=None, wards=None, prop_types=None, only_drops=False, mos_min=15.0, area_min=0, area_max=0, price_min=0, price_max=0, area_ranges=None, price_ranges=None, keyword="", tier="guest", date_range=None, include_guland_high_activity=False, limit=6) -> dict`.
- Consumes: indexes `idx_valuation_listing_computed(listing_id, computed_at DESC, id DESC)` and `idx_shadow_valuation_listing_computed(listing_id, computed_at DESC, id DESC)`.
- Produces: the same `{"rows", "all_rows", "summary", "applied_filters", "as_of"}` payload and the same ranking/rounding behavior.

- [ ] **Step 1: Add the failing query-plan regression test**

Append this test immediately before `test_schema_defines_feed_performance_indexes()` in `tests/test_market_data_performance.py`:

```python
def test_load_market_opportunities_uses_indexed_lateral_latest_rows(monkeypatch):
    import services.market_data as market_data

    captured = {}

    class _CaptureConnection:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = list(params or [])
            return _FakeCursor(rows=[])

    @contextmanager
    def fake_read_conn(_db_path=None):
        yield _CaptureConnection()

    monkeypatch.setattr(market_data, "_read_conn", fake_read_conn)

    result = market_data.load_market_opportunities(
        None,
        sources=["facebook"],
        wards=["Ward A"],
        mos_min=15,
        tier="guest",
        date_range="3m",
    )

    sql = captured["sql"]
    assert result["rows"] == []
    assert "filtered_listings AS MATERIALIZED" in sql
    assert "latest_valuation AS MATERIALIZED" not in sql
    assert "latest_shadow_valuation AS MATERIALIZED" not in sql
    assert sql.count("LEFT JOIN LATERAL") == 2
    assert "FROM valuation_results vr" in sql
    assert "WHERE vr.listing_id = l.id" in sql
    assert "ORDER BY vr.computed_at DESC, vr.id DESC" in sql
    assert "FROM valuation_shadow_results vsr" in sql
    assert "WHERE vsr.listing_id = l.id" in sql
    assert "ORDER BY vsr.computed_at DESC, vsr.id DESC" in sql
    assert sql.count("LIMIT 1") == 2
```

This test catches the production regression where latest valuation rows are
materialized into unindexed CTE result sets and scanned once per filtered
listing. It exercises the SQL emitted at the service/database boundary rather
than grepping source text.

- [ ] **Step 2: Run the new test and verify RED**

```powershell
$env:DATABASE_URL = 'postgresql://postgres@127.0.0.1:15432/radar_bds'
$env:RADAR_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:15432/radar_bds_test'
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_market_data_performance.py::test_load_market_opportunities_uses_indexed_lateral_latest_rows -q
```

Expected: FAIL because the current query contains
`latest_valuation AS MATERIALIZED`, contains no `LEFT JOIN LATERAL`, and has no
per-listing `LIMIT 1` lookups. A test collection/import/database error is not
the expected RED; fix the test setup until the assertion fails for the old SQL
shape.

- [ ] **Step 3: Implement the minimal SQL rewrite**

In `load_market_opportunities()`, retain the complete
`filtered_listings AS MATERIALIZED` CTE. Delete the
`latest_valuation AS MATERIALIZED` and
`latest_shadow_valuation AS MATERIALIZED` CTE blocks.

Replace the `FROM`/join block inside `opportunity_rows` with this exact shape:

```python
        opportunity_rows AS (
            SELECT
                l.ward,
                l.price_per_m2,
                l.price_ty,
                l.area_m2,
                {deal_sql.fair_expr} AS fair_ppm2,
                {deal_sql.mos_expr} AS mos_pct,
                CASE WHEN {signal_condition} THEN 1 ELSE 0 END AS is_signal
            FROM filtered_listings l
            LEFT JOIN LATERAL (
                SELECT vr.*
                FROM valuation_results vr
                WHERE vr.listing_id = l.id
                ORDER BY vr.computed_at DESC, vr.id DESC
                LIMIT 1
            ) v ON TRUE
            LEFT JOIN LATERAL (
                SELECT
                    vsr.listing_id,
                    vsr.is_signal,
                    vsr.actual_ppm2,
                    vsr.fair_ppm2,
                    vsr.mos_pct,
                    vsr.signal_score,
                    vsr.trust_tier,
                    vsr.trust_score,
                    vsr.legal_status,
                    vsr.legal_flags,
                    vsr.source_quality_flags,
                    vsr.source_quality_recheck
                FROM valuation_shadow_results vsr
                WHERE vsr.listing_id = l.id
                ORDER BY vsr.computed_at DESC, vsr.id DESC
                LIMIT 1
            ) sv ON TRUE
            WHERE COALESCE(v.is_outlier, 0) = 0
        )
```

Do not alter the `SELECT` list in `filtered_listings`, `signal_condition`, ward
aggregate, rank calculation, row limit, summary, applied filters, or timestamp.

- [ ] **Step 4: Run the new test and verify GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_market_data_performance.py::test_load_market_opportunities_uses_indexed_lateral_latest_rows -q
```

Expected: PASS.

- [ ] **Step 5: Run the focused market regression set**

```powershell
& $py -X utf8 -m pytest tests\test_market_data_performance.py tests\test_market_indicators.py -q
& $py -X utf8 -m py_compile services\market_data.py app.py
git diff --check
```

Expected: all pytest cases pass, compilation exits 0, and `git diff --check`
prints nothing. If an existing payload assertion fails, fix the SQL while
preserving the test; do not update expected market values to accommodate a
semantic change.

- [ ] **Step 6: Review and commit the tested SQL change**

```powershell
git diff -- services/market_data.py tests/test_market_data_performance.py
git status --short
git add services/market_data.py tests/test_market_data_performance.py
git commit -m "perf: use indexed heatmap valuation lookups"
```

Expected: the diff contains only the new regression test and the bounded SQL
rewrite. Do not stage unrelated files.

### Task 2: Prove payload parity, query-plan quality, and the latency budget

**Files:**
- Verify: `services/market_data.py`
- Verify: `tests/test_market_data_performance.py`
- Baseline source: Git object `08f1986:services/market_data.py`
- No production file changes are expected.

**Interfaces:**
- Consumes: the optimized `load_market_opportunities()` from Task 1.
- Produces: read-only evidence for five scopes, exact raw-row parity, per-scope p95 timings, and index/CTE plan diagnostics.

- [ ] **Step 1: Verify the local PostgreSQL target before measuring**

```powershell
Test-NetConnection 127.0.0.1 -Port 15432 -InformationLevel Quiet
```

Expected: `True`. If it is `False`, run
`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local_postgres.ps1 start`
and repeat the check. Do not fall back to port 5432 unless `.env.local`
explicitly points there.

- [ ] **Step 2: Run the read-only parity and performance harness**

Run the following from the worktree. It loads the pre-optimization module from
the committed Git object, captures old and new SQL without executing through
the fake capture connections, and then executes both statements in the same
repeatable-read, read-only PostgreSQL transaction. It times the optimized
loader 20 times per scope with response caching disabled.

```powershell
$env:DATABASE_URL = 'postgresql://postgres@127.0.0.1:15432/radar_bds'
$env:RADAR_PUBLIC_CACHE_ENABLED = '0'
@'
import contextlib
import json
import math
import subprocess
import sys
import time
import types

from db.connection import get_conn
import services.market_data as current

BASELINE_REF = "08f1986"


def module_from_git(ref):
    source = subprocess.run(
        [
            "git",
            "-c",
            "safe.directory=C:/Users/ASUS/Documents/Claude/Projects/Radar BDS/.worktrees/p0-p1-foundation",
            "show",
            f"{ref}:services/market_data.py",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    name = f"baseline_market_data_{ref}"
    module = types.ModuleType(name)
    module.__file__ = f"{ref}:services/market_data.py"
    sys.modules[name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


baseline = module_from_git(BASELINE_REF)


def capture_query(module, kwargs):
    captured = {}

    class EmptyCursor:
        def fetchall(self):
            return []

    class CaptureConnection:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = list(params or [])
            return EmptyCursor()

    @contextlib.contextmanager
    def factory():
        yield CaptureConnection()

    with module.use_read_connection_factory(factory):
        module.load_market_opportunities(None, **kwargs)
    return captured["sql"], captured["params"]


city_wards = list(current.CITY_MAP[next(iter(current.CITY_MAP))])
cases = [
    ("default_3m", dict(wards=city_wards, mos_min=15, tier="guest", date_range="3m")),
    ("one_ward_facebook_1m", dict(wards=[city_wards[0]], sources=["facebook"], mos_min=15, tier="guest", date_range="1m")),
    ("property_ranges", dict(wards=city_wards, prop_types=["dat_nen"], area_ranges=[(80, 120)], price_ranges=[(1, 3)], mos_min=15, tier="guest", date_range="3m")),
    ("default_guest_1y", dict(wards=city_wards, mos_min=15, tier="guest", date_range="1y")),
    ("vip_price_drops_1y", dict(wards=city_wards, only_drops=True, mos_min=15, tier="vip", date_range="1y")),
]


def percentile_95(values):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def plan_summary(conn, sql, params):
    row = conn.execute(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql,
        params,
    ).fetchone()
    value = row.get("QUERY PLAN") if hasattr(row, "get") else row[0]
    if isinstance(value, str):
        value = json.loads(value)
    document = value[0]
    indexes = set()
    repeated_valuation_cte_scans = []

    def walk(node):
        index_name = node.get("Index Name")
        if index_name:
            indexes.add(index_name)
        if node.get("Node Type") == "CTE Scan" and int(node.get("Actual Loops") or 0) > 1:
            repeated_valuation_cte_scans.append({
                "cte": node.get("CTE Name"),
                "loops": int(node.get("Actual Loops") or 0),
            })
        for child in node.get("Plans") or []:
            walk(child)

    walk(document["Plan"])
    return {
        "execution_ms": round(float(document.get("Execution Time") or 0), 2),
        "indexes": sorted(indexes),
        "repeated_cte_scans": repeated_valuation_cte_scans,
    }


results = []
with get_conn() as conn:
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")

    @contextlib.contextmanager
    def current_connection_factory():
        yield conn

    with current.use_read_connection_factory(current_connection_factory):
        for name, kwargs in cases:
            old_sql, old_params = capture_query(baseline, kwargs)
            new_sql, new_params = capture_query(current, kwargs)
            old_rows = [dict(row) for row in conn.execute(old_sql, old_params).fetchall()]
            new_rows = [dict(row) for row in conn.execute(new_sql, new_params).fetchall()]
            timings = []
            for _ in range(20):
                started = time.perf_counter()
                current.load_market_opportunities(None, **kwargs)
                timings.append((time.perf_counter() - started) * 1000)
            entry = {
                "case": name,
                "rows": len(new_rows),
                "payload_equal": old_rows == new_rows,
                "p95_ms": round(percentile_95(timings), 1),
                "min_ms": round(min(timings), 1),
                "max_ms": round(max(timings), 1),
            }
            if name in {"default_3m", "default_guest_1y"}:
                entry["plan"] = plan_summary(conn, new_sql, new_params)
            results.append(entry)

print(json.dumps(results, ensure_ascii=False, indent=2))
if not all(item["payload_equal"] and item["p95_ms"] <= 300 for item in results):
    raise SystemExit(1)
required_indexes = {
    "idx_valuation_listing_computed",
    "idx_shadow_valuation_listing_computed",
}
for item in results:
    plan = item.get("plan")
    if not plan:
        continue
    if not required_indexes.issubset(set(plan["indexes"])):
        raise SystemExit(1)
    if plan["repeated_cte_scans"]:
        raise SystemExit(1)
'@ | & "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -
```

Expected for all five objects:

- `payload_equal` is `true`;
- `p95_ms` is at most `300.0`;
- both plan objects include `idx_valuation_listing_computed` and
  `idx_shadow_valuation_listing_computed`; and
- `repeated_cte_scans` is empty.

If the command exits nonzero, treat the gate as failed. Do not loosen the
300 ms threshold or reduce the sample count. Use systematic debugging, add a
new failing regression test for the proven cause, and only then change the SQL.

- [ ] **Step 3: Run the full regression gate on the final tree**

```powershell
$env:RADAR_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:15432/radar_bds_test'
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m py_compile services\market_data.py app.py
& $py -X utf8 -m pytest tests --ignore=tests\test_guland.py --ignore=tests\sanity_test.py -q
node --check static\js\main\market.js
git diff 08f1986..HEAD --check
```

Expected: Python compilation exits 0, the complete test suite reaches 100%
with only documented skips/warnings, JavaScript syntax exits 0, and branch
diff checking prints nothing.

- [ ] **Step 4: Perform the final scope and branch review**

```powershell
git status --short
git diff 08f1986..HEAD --stat
git log -4 --oneline
```

Expected: worktree is clean; the implementation commit changes only
`services/market_data.py` and `tests/test_market_data_performance.py`; the two
earlier spec commits and this plan commit contain documentation only; no merge,
push, or deploy has occurred.
