# Homepage Performance Phase 1 Read Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the cold signal query to sub-second performance and add a durable, parity-tested PostgreSQL signal-card read model behind a disabled-by-default feature flag.

**Architecture:** First replace correlated Guland publisher checks in the legacy feed with one set-based join. Then add durable dataset version rows and a `signal_card_read_model` table refreshed transactionally from the existing deterministic listing/valuation data. Keep `load_signals()` as the stable public interface and select legacy versus read-model SQL with `RADAR_SIGNAL_READ_MODEL_ENABLED`.

**Tech Stack:** Python 3.12, Flask, PostgreSQL, psycopg, pytest, existing `db.schema` idempotent migrations, existing valuation/signal-quality SQL helpers.

## Global Constraints

- Preserve the exact guest/Free/VIP/admin feed, ordering, masking, publisher visibility, actionable-signal gate, badges, pagination, and API shape.
- `/api/signals` remains compact and thumbnail-first; do not add descriptions or image arrays beyond the existing contract.
- Normal freshness <= 60 seconds; a failed refresh keeps the previous complete read-model version active.
- `signal_card_read_model` and `public_dataset_versions` are additive. The legacy query remains available for rollback.
- `public_dataset_versions.signals` increments only in the transaction that publishes a complete read-model refresh.
- Use set-based publisher joins; do not add external LLM work or per-row database calls.
- Cold read-model p95 target <= 500 ms under normal load.
- Write a failing test before each implementation change and make one focused commit per task.

---

## File Structure

| File | Responsibility |
|---|---|
| `db/guland_publishers.py` | Set-based publisher join, effective class, public visibility, and rank SQL fragments |
| `db/public_dataset_versions.py` | Read and atomically bump durable public dataset counters |
| `db/schema.py` | Additive `public_dataset_versions` and `signal_card_read_model` schema/indexes/autovacuum settings |
| `services/signal_read_model.py` | Refresh/reconcile read model and query compact signal pages |
| `services/market_data.py` | Stable `load_signals()` switch, legacy loader, formatting/filter helpers |
| `services/public_data_publish.py` | Publish read-model changes after deterministic pipelines without importing Flask |
| `cleansing/reprocess.py` | Invoke publication after valuation/dedup/market work completes |
| `app.py` | Use durable signal version and refresh publisher-linked read-model rows on override |
| `cli/system.py`, `radar.py` | Explicit refresh/compare command for deployment and repair |
| `scripts/benchmark_public_read_path.py` | Safe cold/warm local or VPS-local endpoint timing; never logs response bodies |
| `tests/test_market_data_performance.py` | Legacy SQL regression and API switch tests |
| `tests/test_public_dataset_versions.py` | Counter migration and transaction tests |
| `tests/test_signal_read_model.py` | Refresh atomicity, query behavior, parity, and failure retention tests |
| `.env.example` | Safe-disabled feature flag and statement-timeout documentation |

## Task 1: Replace Correlated Publisher Work in the Legacy Signal Query

**Files:**
- Modify: `db/guland_publishers.py:659-705`
- Modify: `services/market_data.py:503-760`
- Modify: `services/market_data.py:1172-1301`
- Test: `tests/test_market_data_performance.py`
- Test: `tests/test_source_policy.py`
- Test: `tests/test_guest_visibility.py`

**Interfaces:**
- Produces: `publisher_feed_join_sql(listing_alias, link_alias, publisher_alias) -> str`
- Produces: `publisher_visibility_from_join_sql(listing_alias, publisher_alias, include_high_activity=False) -> str`
- Produces: `publisher_sort_rank_from_join_sql(listing_alias, publisher_alias) -> str`
- Preserves: existing `publisher_visibility_sql()` and `publisher_sort_rank_sql()` for callers not yet migrated

- [ ] **Step 1: Write failing SQL-shape and fail-open tests**

Add tests that require exactly one set-based publisher join and prohibit correlated subqueries in the signal query:

```python
def test_load_signals_joins_publisher_activity_once(monkeypatch):
    import services.market_data as market_data

    conn = _FakeReadConnection()

    @contextmanager
    def fake_read_conn(_db_path=None):
        yield conn

    monkeypatch.setattr(market_data, "_read_conn", fake_read_conn)
    market_data.load_signals(
        None,
        sources=["facebook", "guland"],
        wards=["Tan An"],
        tier="guest",
        include_total=False,
    )

    sql = conn.queries[0][0]
    assert sql.count("LEFT JOIN listing_publishers feed_lp") == 1
    assert sql.count("LEFT JOIN source_publishers feed_sp") == 1
    assert "NOT EXISTS" not in sql
    assert "SELECT CASE" not in sql
```

In `tests/test_guland_publisher_repository.py`, add direct fragment checks:

```python
def test_joined_publisher_visibility_is_fail_open_for_unknown_identity():
    from db.guland_publishers import publisher_visibility_from_join_sql

    sql = publisher_visibility_from_join_sql("l", "feed_sp")
    assert "COALESCE" in sql
    assert "'unknown'" in sql
    assert "NOT IN ('high_activity', 'automated_repost')" in sql
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_market_data_performance.py tests\test_guland_publisher_repository.py -q
```

Expected: FAIL because the joined SQL helpers and aliases do not exist.

- [ ] **Step 3: Add the set-based SQL helpers**

Implement in `db/guland_publishers.py`:

```python
def publisher_feed_join_sql(
    listing_alias: str = "l",
    link_alias: str = "feed_lp",
    publisher_alias: str = "feed_sp",
) -> str:
    return f"""
    LEFT JOIN listing_publishers {link_alias}
      ON {link_alias}.listing_id = {listing_alias}.id
    LEFT JOIN source_publishers {publisher_alias}
      ON {publisher_alias}.id = {link_alias}.publisher_id
    """.strip()


def publisher_effective_class_from_join_sql(publisher_alias: str) -> str:
    return f"""
    COALESCE(
      CASE {publisher_alias}.manual_override
        WHEN 'allow_manual' THEN 'low_manual'
        WHEN 'hide_high_activity' THEN 'automated_repost'
        ELSE {publisher_alias}.activity_class
      END,
      'unknown'
    )
    """.strip()


def publisher_visibility_from_join_sql(
    listing_alias: str = "l",
    publisher_alias: str = "feed_sp",
    *,
    include_high_activity: bool = False,
) -> str:
    if include_high_activity:
        return "1=1"
    effective = publisher_effective_class_from_join_sql(publisher_alias)
    return (
        f"({listing_alias}.source <> 'guland' OR "
        f"({effective}) NOT IN ('high_activity', 'automated_repost'))"
    )


def publisher_sort_rank_from_join_sql(
    listing_alias: str = "l",
    publisher_alias: str = "feed_sp",
) -> str:
    effective = publisher_effective_class_from_join_sql(publisher_alias)
    return f"""
    CASE
      WHEN {listing_alias}.source <> 'guland' THEN 0
      WHEN ({effective}) = 'low_manual' THEN 0
      WHEN ({effective}) = 'unknown' THEN 1
      WHEN ({effective}) = 'high_activity' THEN 2
      WHEN ({effective}) = 'automated_repost' THEN 3
      ELSE 1
    END
    """.strip()
```

- [ ] **Step 4: Wire only the legacy signal feed to the joined fragments**

Extend `build_listing_filters()` with an optional `publisher_alias: str | None = None`. When present, use `publisher_visibility_from_join_sql()`; otherwise retain the old helper for unchanged callers.

In the signal SQL:

```python
where_sql, params = build_listing_filters(
    sources,
    wards,
    prop_types,
    only_drops,
    prefix="l.",
    area_min=area_min,
    area_max=area_max,
    price_min=price_min,
    price_max=price_max,
    area_ranges=area_ranges,
    price_ranges=price_ranges,
    keyword=keyword,
    date_range=date_range,
    publisher_alias="feed_sp",
    include_guland_high_activity=include_guland_high_activity,
)
order_sql = (
    f"{publisher_sort_rank_from_join_sql('l', 'feed_sp')} ASC, "
    f"{order_sql}"
)
```

Insert the join once after `FROM listings l` and before valuation/image joins:

```python
{publisher_feed_join_sql('l', 'feed_lp', 'feed_sp')}
```

- [ ] **Step 5: Run correctness and SQL-shape tests**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_market_data_performance.py `
  tests\test_guland_publisher_repository.py `
  tests\test_source_policy.py `
  tests\test_guest_visibility.py -q
```

Expected: PASS, including public fail-open unknown publishers and admin override behavior.

- [ ] **Step 6: Measure local cold/warm query before committing**

Run the same default, Facebook, Guland, ward, and MOS queries used in the approved design. Record command, database row counts, cold, and warm timings in the commit notes; do not place runtime output in git.

- [ ] **Step 7: Commit**

```powershell
git add db/guland_publishers.py services/market_data.py tests/test_market_data_performance.py tests/test_guland_publisher_repository.py
git commit -m "perf: use set-based publisher joins in signal feed"
```

## Task 2: Add Durable Public Dataset Versions

**Files:**
- Create: `db/public_dataset_versions.py`
- Modify: `db/schema.py`
- Modify: `app.py:4025-4048`
- Test: `tests/test_public_dataset_versions.py`
- Test: `tests/test_market_data_performance.py`

**Interfaces:**
- Produces: `DATASET_SIGNALS`, `DATASET_MARKET`
- Produces: `get_dataset_versions(conn, names) -> dict[str, int]`
- Produces: `bump_dataset_versions(conn, names) -> dict[str, int]`
- Replaces: the hot-path `_get_signals_version()` aggregate scan with one primary-key lookup

- [ ] **Step 1: Write failing migration and counter tests**

```python
def test_public_dataset_version_bump_is_monotonic():
    from db.connection import get_conn
    from db.public_dataset_versions import bump_dataset_versions, get_dataset_versions

    with get_conn() as conn:
        before = get_dataset_versions(conn, ("signals",))["signals"]
        bumped = bump_dataset_versions(conn, ("signals",))["signals"]
        after = get_dataset_versions(conn, ("signals",))["signals"]

    assert bumped == before + 1
    assert after == bumped


def test_public_dataset_version_bump_rolls_back_on_error():
    from db.connection import get_conn
    from db.public_dataset_versions import bump_dataset_versions, get_dataset_versions

    with get_conn() as conn:
        before = get_dataset_versions(conn, ("signals",))["signals"]
        try:
            bump_dataset_versions(conn, ("signals",))
            raise RuntimeError("force rollback")
        except RuntimeError:
            conn.rollback()

    with get_conn() as conn:
        assert get_dataset_versions(conn, ("signals",))["signals"] == before
```

- [ ] **Step 2: Run and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_public_dataset_versions.py -q
```

Expected: FAIL because the module/table does not exist.

- [ ] **Step 3: Add the idempotent schema**

Add `_migrate_public_read_model(conn)` and call it from `_run_migrations()`:

```sql
CREATE TABLE IF NOT EXISTS public_dataset_versions (
    dataset_name TEXT PRIMARY KEY,
    version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public_dataset_versions(dataset_name, version)
VALUES ('signals', 0), ('market', 0)
ON CONFLICT (dataset_name) DO NOTHING;
```

- [ ] **Step 4: Implement exact counter access**

```python
from typing import Iterable

DATASET_SIGNALS = "signals"
DATASET_MARKET = "market"
ALLOWED_DATASETS = frozenset({DATASET_SIGNALS, DATASET_MARKET})


def _validated(names: Iterable[str]) -> tuple[str, ...]:
    result = tuple(dict.fromkeys(str(name) for name in names))
    if not result or any(name not in ALLOWED_DATASETS for name in result):
        raise ValueError("invalid public dataset name")
    return result


def get_dataset_versions(conn, names: tuple[str, ...]) -> dict[str, int]:
    names = _validated(names)
    placeholders = ",".join("?" for _ in names)
    rows = conn.execute(
        f"SELECT dataset_name, version FROM public_dataset_versions "
        f"WHERE dataset_name IN ({placeholders})",
        names,
    ).fetchall()
    found = {str(row["dataset_name"]): int(row["version"]) for row in rows}
    return {name: found.get(name, 0) for name in names}


def bump_dataset_versions(conn, names: tuple[str, ...]) -> dict[str, int]:
    names = _validated(names)
    versions: dict[str, int] = {}
    for name in names:
        row = conn.execute(
            """
            INSERT INTO public_dataset_versions(dataset_name, version, updated_at)
            VALUES (?, 1, NOW())
            ON CONFLICT (dataset_name) DO UPDATE SET
                version=public_dataset_versions.version + 1,
                updated_at=NOW()
            RETURNING version
            """,
            (name,),
        ).fetchone()
        versions[name] = int(row["version"])
    return versions
```

- [ ] **Step 5: Replace `_get_signals_version()`**

Keep the function name temporarily for API compatibility, but make it a primary-key lookup:

```python
def _get_signals_version(_db_path: str) -> str:
    with get_conn() as conn:
        versions = get_dataset_versions(conn, (DATASET_SIGNALS,))
    return str(versions[DATASET_SIGNALS])
```

- [ ] **Step 6: Run focused and schema-permission tests**

```powershell
& $py -X utf8 -m pytest `
  tests\test_public_dataset_versions.py `
  tests\test_market_data_performance.py `
  tests\test_schema_init_permissions.py -q
```

Expected: PASS. Limited-DDL fallback must continue to report missing required new tables instead of silently enabling the read-model feature.

- [ ] **Step 7: Commit**

```powershell
git add db/public_dataset_versions.py db/schema.py app.py tests/test_public_dataset_versions.py tests/test_market_data_performance.py
git commit -m "feat: add public dataset versions"
```

## Task 3: Add the Transactional Signal-Card Read Model

**Files:**
- Create: `services/signal_read_model.py`
- Modify: `db/schema.py`
- Test: `tests/test_signal_read_model.py`
- Test: `tests/test_schema_init_permissions.py`

**Interfaces:**
- Produces: `SignalReadModelRefresh`
- Produces: `refresh_signal_card_read_model(conn, listing_ids, market_changed=False)`
- Produces: `analyze_public_read_tables(conn)`
- Consumes: existing valuation CTEs, signal-quality SQL, publisher joined SQL, image ordering SQL, and price-drop CTE

- [ ] **Step 1: Write failing schema and atomic-publication tests**

The schema test must assert the table, public-newest index, filter index, MOS index, and both version rows. Add a fake-connection test that requires `bump_dataset_versions()` to occur after the final read-model insert, plus an integration rollback test:

```python
def test_failed_full_refresh_keeps_previous_rows_and_version(monkeypatch):
    from db.connection import get_conn
    from db.public_dataset_versions import get_dataset_versions
    from services import signal_read_model

    with get_conn() as conn:
        before_rows = conn.execute(
            "SELECT listing_id FROM signal_card_read_model ORDER BY listing_id"
        ).fetchall()
        before_version = get_dataset_versions(conn, ("signals",))["signals"]

    monkeypatch.setattr(
        signal_read_model,
        "_insert_staged_rows",
        lambda _conn: (_ for _ in ()).throw(RuntimeError("refresh failed")),
    )
    with pytest.raises(RuntimeError, match="refresh failed"):
        with get_conn() as conn:
            signal_read_model.refresh_signal_card_read_model(
                conn,
                listing_ids=None,
            )

    with get_conn() as conn:
        after_rows = conn.execute(
            "SELECT listing_id FROM signal_card_read_model ORDER BY listing_id"
        ).fetchall()
        after_version = get_dataset_versions(conn, ("signals",))["signals"]

    assert after_rows == before_rows
    assert after_version == before_version
```

- [ ] **Step 2: Run and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_signal_read_model.py tests\test_schema_init_permissions.py -q
```

Expected: FAIL because the schema and service do not exist.

- [ ] **Step 3: Add the read-model table and measured indexes**

Add this table in `_migrate_public_read_model(conn)`:

```sql
CREATE TABLE IF NOT EXISTS signal_card_read_model (
    listing_id BIGINT PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    source_status TEXT NOT NULL DEFAULT 'unknown',
    url TEXT NOT NULL DEFAULT '',
    ward TEXT,
    property_type TEXT,
    area_m2 DOUBLE PRECISION,
    frontage_m DOUBLE PRECISION,
    depth_m DOUBLE PRECISION,
    price_ty DOUBLE PRECISION,
    actual_ppm2 DOUBLE PRECISION,
    fair_ppm2 DOUBLE PRECISION,
    fair_ppm2_old DOUBLE PRECISION,
    fair_ppm2_new DOUBLE PRECISION,
    mos_pct DOUBLE PRECISION,
    mos_pct_old DOUBLE PRECISION,
    mos_pct_new DOUBLE PRECISION,
    signal_score INTEGER NOT NULL DEFAULT 0,
    is_actionable BOOLEAN NOT NULL DEFAULT FALSE,
    is_hot BOOLEAN NOT NULL DEFAULT FALSE,
    possibly_duplicate BOOLEAN NOT NULL DEFAULT FALSE,
    price_dropped BOOLEAN NOT NULL DEFAULT FALSE,
    price_drop_pct DOUBLE PRECISION,
    price_first_ty DOUBLE PRECISION,
    suspicious_bait BOOLEAN NOT NULL DEFAULT FALSE,
    duplicate_of_id BIGINT,
    activity_at TIMESTAMPTZ,
    crawled_at TEXT,
    posted_at TEXT,
    first_seen_at TEXT,
    price_updated_at TEXT,
    road_name TEXT,
    road_type TEXT,
    road_width_m DOUBLE PRECISION,
    road_tier INTEGER NOT NULL DEFAULT 0,
    tho_cu_m2 DOUBLE PRECISION,
    tho_cu_ratio DOUBLE PRECISION,
    has_so BOOLEAN,
    trust_tier TEXT NOT NULL DEFAULT 'candidate_signal',
    trust_score INTEGER NOT NULL DEFAULT 0,
    legal_status TEXT NOT NULL DEFAULT 'unverified',
    legal_flags TEXT NOT NULL DEFAULT '',
    source_quality_flags TEXT NOT NULL DEFAULT '',
    source_quality_recheck BOOLEAN NOT NULL DEFAULT FALSE,
    has_legal_doc_image BOOLEAN NOT NULL DEFAULT FALSE,
    publisher_visible_public BOOLEAN NOT NULL DEFAULT TRUE,
    publisher_rank SMALLINT NOT NULL DEFAULT 1,
    primary_image_id BIGINT REFERENCES listing_images(id) ON DELETE SET NULL,
    image_count INTEGER NOT NULL DEFAULT 0,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signal_card_public_newest
ON signal_card_read_model(publisher_rank, activity_at DESC, listing_id DESC)
WHERE is_actionable AND publisher_visible_public;

CREATE INDEX IF NOT EXISTS idx_signal_card_public_filter
ON signal_card_read_model(source, ward, property_type, publisher_rank, activity_at DESC, listing_id DESC)
WHERE is_actionable AND publisher_visible_public;

CREATE INDEX IF NOT EXISTS idx_signal_card_public_mos
ON signal_card_read_model(mos_pct DESC, listing_id DESC)
WHERE is_actionable AND publisher_visible_public;
```

Apply low-threshold planner maintenance to the hot derived table and source tables:

```sql
ALTER TABLE signal_card_read_model SET (
    autovacuum_analyze_scale_factor = 0.02,
    autovacuum_analyze_threshold = 100
);
```

Apply the same analyze settings to `listings`, `valuation_results`, `valuation_shadow_results`, `listing_images`, `listing_publishers`, and `source_publishers`; do not change vacuum scale factors in this task.

- [ ] **Step 4: Implement the refresh SQL from existing deterministic helpers**

Build `SIGNAL_CARD_SELECT_SQL` from the existing CTEs and helpers. It must:

```python
deal = build_deal_sql(0)
actual_expr = deal.actual_expr
fair_expr = deal.fair_expr
mos_expr = deal.mos_expr
actionable_expr = actionable_signal_sql("v")
score_expr = _max_sql("COALESCE(v.signal_score, 0)", "COALESCE(sv.signal_score, 0)")
complete_listing_expr = _signal_listing_data_sql("l")
public_visibility_expr = publisher_visibility_from_join_sql("l", "feed_sp")
publisher_rank_expr = publisher_sort_rank_from_join_sql("l", "feed_sp")
primary_image_order_sql = LEGAL_IMAGE_ORDER_SQL.replace(
    "img_type", "li.img_type"
).replace("img_order", "li.img_order").replace(", id", ", li.id")

SIGNAL_CARD_SELECT_SQL = f"""
WITH {LATEST_VALUATION_CTE},
     {LATEST_SHADOW_VALUATION_CTE},
     {RELATED_PRICE_DROP_CTE}
SELECT
    l.id AS listing_id,
    l.title,
    l.description,
    l.source,
    COALESCE(l.source_status, 'unknown') AS source_status,
    l.url,
    l.ward,
    l.property_type,
    l.area_m2,
    l.frontage_m,
    l.depth_m,
    l.price_ty,
    ({actual_expr}) AS actual_ppm2,
    ({fair_expr}) AS fair_ppm2,
    v.fair_ppm2 AS fair_ppm2_old,
    sv.fair_ppm2 AS fair_ppm2_new,
    ({mos_expr}) AS mos_pct,
    v.mos_pct AS mos_pct_old,
    sv.mos_pct AS mos_pct_new,
    {score_expr} AS signal_score,
    ({actionable_expr}) AS is_actionable,
    COALESCE(l.is_hot, 0)::boolean AS is_hot,
    COALESCE(l.possibly_duplicate, 0)::boolean AS possibly_duplicate,
    {effective_price_drop_select_sql('l', 'related_drop')},
    COALESCE(l.suspicious_bait, 0)::boolean AS suspicious_bait,
    l.duplicate_of_id,
    {listing_activity_at_sql('l')} AS activity_at,
    l.crawled_at,
    l.posted_at,
    l.first_seen_at,
    l.price_updated_at,
    l.road_name,
    l.road_type,
    l.road_width_m,
    COALESCE(l.road_tier, 0) AS road_tier,
    l.tho_cu_m2,
    l.tho_cu_ratio,
    l.has_so,
    COALESCE(v.trust_tier, sv.trust_tier, 'candidate_signal') AS trust_tier,
    COALESCE(v.trust_score, sv.trust_score, 0) AS trust_score,
    COALESCE(v.legal_status, sv.legal_status, 'unverified') AS legal_status,
    COALESCE(v.legal_flags, sv.legal_flags, '') AS legal_flags,
    COALESCE(v.source_quality_flags, sv.source_quality_flags, '') AS source_quality_flags,
    COALESCE(v.source_quality_recheck, sv.source_quality_recheck, 0)::boolean AS source_quality_recheck,
    ({LEGAL_DOC_IMAGE_SELECT_SQL})::boolean AS has_legal_doc_image,
    ({public_visibility_expr}) AS publisher_visible_public,
    ({publisher_rank_expr}) AS publisher_rank,
    primary_img.id AS primary_image_id,
    COALESCE(img_count.image_count, 0)::integer AS image_count,
    NOW() AS refreshed_at
FROM listings l
LEFT JOIN latest_valuation v ON v.listing_id=l.id
LEFT JOIN latest_shadow_valuation sv ON sv.listing_id=l.id
{publisher_feed_join_sql('l', 'feed_lp', 'feed_sp')}
{related_price_drop_join_sql('l', 'related_drop')}
LEFT JOIN LATERAL (
    SELECT li.id
    FROM listing_images li
    WHERE li.listing_id=l.id
    ORDER BY {primary_image_order_sql}
    LIMIT 1
) primary_img ON TRUE
LEFT JOIN LATERAL (
    SELECT COUNT(*)::integer AS image_count
    FROM listing_images li
    WHERE li.listing_id=l.id
) img_count ON TRUE
WHERE COALESCE(l.probably_sold, 0)=0
  AND COALESCE(l.is_blacklisted, 0)=0
  AND COALESCE(l.review_hidden, 0)=0
  AND COALESCE(l.source_status, 'unknown') <> 'inactive'
  AND {complete_listing_expr}
  {listing_id_clause}
"""
```

Build `listing_id_clause` as an empty string for full refresh or an `AND l.id IN (...)` clause containing exactly one bound `?` marker per ID for incremental refresh. `_select_sql()` returns SQL and parameters separately; do not interpolate ID values.

Use a temp-stage/swap for full refresh and delete/reinsert for bounded IDs:

```python
@dataclass(frozen=True)
class SignalReadModelRefresh:
    mode: str
    affected_rows: int
    versions: dict[str, int]
    duration_ms: float


def refresh_signal_card_read_model(
    conn,
    *,
    listing_ids: tuple[int, ...] | None,
    market_changed: bool = False,
) -> SignalReadModelRefresh:
    started = time.perf_counter()
    ids = None if listing_ids is None else tuple(dict.fromkeys(int(x) for x in listing_ids if int(x) > 0))
    if ids is not None and not ids:
        versions = get_dataset_versions(conn, (DATASET_SIGNALS,))
        return SignalReadModelRefresh("noop", 0, versions, 0.0)
    if ids is not None and len(ids) > 500:
        ids = None

    if ids is None:
        conn.execute("DROP TABLE IF EXISTS signal_card_read_model_stage")
        select_sql, select_params = _select_sql(None)
        conn.execute(
            "CREATE TEMP TABLE signal_card_read_model_stage "
            "ON COMMIT DROP AS " + select_sql,
            select_params,
        )
        conn.execute("LOCK TABLE signal_card_read_model IN ACCESS EXCLUSIVE MODE")
        conn.execute("DELETE FROM signal_card_read_model")
        affected = _insert_staged_rows(conn)
        mode = "full"
    else:
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"DELETE FROM signal_card_read_model WHERE listing_id IN ({placeholders})",
            ids,
        )
        affected = _insert_selected_rows(conn, ids)
        mode = "incremental"

    datasets = (DATASET_SIGNALS, DATASET_MARKET) if market_changed else (DATASET_SIGNALS,)
    versions = bump_dataset_versions(conn, datasets)
    return SignalReadModelRefresh(
        mode,
        int(affected),
        versions,
        round((time.perf_counter() - started) * 1000, 2),
    )
```

- [ ] **Step 5: Add deterministic planner maintenance**

```python
PUBLIC_READ_TABLES = (
    "listings",
    "valuation_results",
    "valuation_shadow_results",
    "listing_images",
    "listing_publishers",
    "source_publishers",
    "signal_card_read_model",
)


def analyze_public_read_tables(conn) -> None:
    conn.execute("ANALYZE " + ", ".join(PUBLIC_READ_TABLES))
```

At most 500 IDs use the incremental path; 501 or more switches to the full stage/swap path. Call planner maintenance after a full rebuild or an incremental publication affecting exactly 500 listing IDs, never on every tiny request or per listing.

- [ ] **Step 6: Run schema, atomicity, and refresh tests**

```powershell
& $py -X utf8 -m pytest `
  tests\test_signal_read_model.py `
  tests\test_public_dataset_versions.py `
  tests\test_schema_init_permissions.py -q
```

Expected: PASS, with the rollback test proving old rows/version survive a failed refresh.

- [ ] **Step 7: Commit**

```powershell
git add db/schema.py services/signal_read_model.py tests/test_signal_read_model.py tests/test_schema_init_permissions.py
git commit -m "feat: add signal card read model"
```

## Task 4: Query the Read Model Behind a Feature Flag and Prove Parity

**Files:**
- Modify: `services/signal_read_model.py`
- Modify: `services/market_data.py:1172-1301`
- Modify: `app.py:4619-4694`
- Modify: `.env.example`
- Create: `scripts/benchmark_public_read_path.py`
- Modify: `tests/test_signal_read_model.py`
- Modify: `tests/test_market_data_performance.py`
- Modify: `tests/test_guest_visibility.py`
- Modify: `tests/test_source_policy.py`

**Interfaces:**
- Produces: `load_signals_from_read_model()` with the same arguments/return shape as `load_signals()`
- Produces: `_load_signals_legacy()` as the preserved rollback implementation
- Preserves: public `load_signals()` name for all callers

- [ ] **Step 1: Write failing feature-off/on and payload-parity tests**

```python
def test_load_signals_feature_flag_selects_read_model(monkeypatch):
    import services.market_data as market_data

    calls = []
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setattr(
        market_data,
        "load_signals_from_read_model",
        lambda *args, **kwargs: calls.append(kwargs) or {"signals": [], "page": 1, "limit": 30, "has_more": False, "sort": "newest", "tier": "guest"},
    )

    payload = market_data.load_signals(None, include_total=False)
    assert payload["signals"] == []
    assert len(calls) == 1


def test_load_signals_feature_off_keeps_legacy_query(monkeypatch):
    import services.market_data as market_data

    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "0")
    called = {"legacy": 0}
    monkeypatch.setattr(
        market_data,
        "_load_signals_legacy",
        lambda *args, **kwargs: called.__setitem__("legacy", called["legacy"] + 1) or {"signals": []},
    )
    market_data.load_signals(None)
    assert called["legacy"] == 1
```

Add database-backed parameterized parity over:

```python
PARITY_CASES = (
    {},
    {"sources": ["facebook"]},
    {"sources": ["guland"]},
    {"wards": ["Tan An"]},
    {"prop_types": ["dat_nen"]},
    {"mos_min": 20},
    {"only_drops": True, "tier": "free"},
    {"sort": "mos_desc"},
    {"sort": "score_desc"},
    {"page": 2, "limit": 12, "include_total": False},
)
```

For each case and tier `guest/free/vip/admin`, compare listing IDs, order, page metadata, publisher visibility, URL/phone redaction, badge fields, primary image, and image count.

- [ ] **Step 2: Run and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_signal_read_model.py tests\test_market_data_performance.py -q
```

- [ ] **Step 3: Split the stable loader without changing callers**

Rename the current implementation to `_load_signals_legacy()` and add:

```python
def _signal_read_model_enabled() -> bool:
    return os.getenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }


def load_signals(*args, **kwargs):
    if _signal_read_model_enabled():
        return load_signals_from_read_model(*args, **kwargs)
    return _load_signals_legacy(*args, **kwargs)
```

Import `os` and `load_signals_from_read_model` explicitly. Do not cache the flag at import time; tests and controlled rollback must observe the process environment at startup and monkeypatches in unit tests.

- [ ] **Step 4: Implement a bounded read-model page query**

`load_signals_from_read_model()` must clamp page/limit exactly like legacy, apply guest MOS/drop behavior, use deterministic sorts, filter public publisher visibility unless admin explicitly requests high activity, and join the already selected primary image by primary key:

```sql
WITH candidates AS MATERIALIZED (
    SELECT rm.*,
           COUNT(*) OVER() AS total_count
    FROM signal_card_read_model rm
    WHERE rm.is_actionable
      AND (? OR rm.publisher_visible_public)
      AND (? OR NOT rm.possibly_duplicate)
      AND rm.mos_pct >= ?
      /* validated source/ward/type/range/keyword/date predicates */
    ORDER BY /* publisher_rank plus stable requested sort */
    LIMIT ? OFFSET ?
)
SELECT c.*,
       li.local_path AS primary_local_path,
       li.img_url AS primary_img_url,
       0 AS is_fresh_locked
FROM candidates c
LEFT JOIN listing_images li ON li.id=c.primary_image_id
ORDER BY /* same deterministic candidate order */;
```

When `include_total=False`, omit `COUNT(*) OVER()` and request `limit + 1` exactly as legacy. Before the SELECT, apply only to this transaction:

```python
conn.execute(
    "SELECT set_config('statement_timeout', ?, true)",
    (f"{statement_timeout_ms}ms",),
)
```

Feed each row through the existing `_format_signal_row()` and `redact_for_tier()` path. Do not fork serialization rules.

- [ ] **Step 5: Add a safe benchmark utility**

The script accepts `--base-url`, `--repeat`, and multiple `--path`, defaults to localhost, records status/TTFB/total bytes, and never prints bodies or cookies:

```python
DEFAULT_PATHS = (
    "/",
    "/api/signals?limit=30&include_total=0",
    "/api/signals?source=facebook&limit=30&include_total=0",
    "/api/signals?source=guland&limit=30&include_total=0",
    "/api/counts",
    "/api/dashboard",
)
```

Use `http.client` or `urllib.request` with a new connection for cold samples and an explicit reusable `HTTPSConnection` for warm samples. Exit nonzero on non-2xx or timeout.

- [ ] **Step 6: Run parity, redaction, source-policy, and syntax tests**

```powershell
& $py -X utf8 -m pytest `
  tests\test_signal_read_model.py `
  tests\test_market_data_performance.py `
  tests\test_guest_visibility.py `
  tests\test_source_policy.py -q
& $py -X utf8 -m py_compile services\signal_read_model.py services\market_data.py app.py scripts\benchmark_public_read_path.py
```

Expected: PASS with zero unexplained parity differences.

- [ ] **Step 7: Commit**

```powershell
git add services/signal_read_model.py services/market_data.py app.py .env.example scripts/benchmark_public_read_path.py tests/test_signal_read_model.py tests/test_market_data_performance.py tests/test_guest_visibility.py tests/test_source_policy.py
git commit -m "feat: switch signal reads behind feature flag"
```

## Task 5: Publish the Read Model from Reprocess and Publisher Overrides

**Files:**
- Create: `services/public_data_publish.py`
- Modify: `cleansing/reprocess.py:585-700`
- Modify: `db/guland_publishers.py:483-541`
- Modify: `app.py:6357-6389`
- Modify: `cli/system.py`
- Modify: `radar.py`
- Test: `tests/test_signal_read_model.py`
- Test: `tests/test_guland_targeted_reprocess.py`
- Test: `tests/test_guland_publisher_repository.py`

**Interfaces:**
- Produces: `publish_public_data(listing_ids=None, market_changed=False, strict=False) -> dict`
- Produces CLI: `python radar.py signal-read-model --refresh --compare`
- Consumes later: Phase 2 hooks Redis version publication and prewarming into the same service

- [ ] **Step 1: Write failing pipeline publication tests**

```python
def test_full_reprocess_publishes_after_dedup_and_market(monkeypatch):
    events = []
    monkeypatch.setattr(reprocess, "reprocess_listings", lambda **_: {"processed_ids": [11], "new": 1, "updated": 0, "skipped": 0})
    monkeypatch.setattr(reprocess, "reprocess_valuation", lambda **_: events.append("valuation") or {"total": 1, "signals": 1, "outliers": 0})
    monkeypatch.setattr(reprocess, "_run_listing_map_backfill", lambda *_args, **_kwargs: {})
    # Stub lifecycle/trend/dedup helpers through their owning modules as existing tests do.
    monkeypatch.setattr(reprocess, "publish_public_data", lambda **kwargs: events.append(("publish", kwargs)) or {"status": "ok"})

    reprocess._run_full_reprocess(full=False)
    assert events[-1] == ("publish", {"listing_ids": (11,), "market_changed": True, "strict": False})
```

Add a publisher override test requiring refresh of every listing linked to that publisher before the new version is returned.

- [ ] **Step 2: Run and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_signal_read_model.py tests\test_guland_targeted_reprocess.py tests\test_guland_publisher_repository.py -q
```

- [ ] **Step 3: Implement the non-Flask publication boundary**

```python
def publish_public_data(
    *,
    listing_ids: tuple[int, ...] | None,
    market_changed: bool = False,
    strict: bool = False,
) -> dict:
    try:
        with get_conn() as conn:
            result = refresh_signal_card_read_model(
                conn,
                listing_ids=listing_ids,
                market_changed=market_changed,
            )
            if listing_ids is None or len(listing_ids) >= 500:
                analyze_public_read_tables(conn)
        return {"status": "ok", **asdict(result)}
    except Exception as exc:
        logger.exception("Public signal read-model publication failed")
        if strict:
            raise
        return {"status": "error", "error": str(exc)}
```

`strict=False` keeps the previous complete read model active and records the failure in crawl/admin job stats. The explicit CLI uses `strict=True` and exits nonzero.

- [ ] **Step 4: Wire deterministic completion points**

- At the end of `_run_full_reprocess()`, after market trends, lifecycle, and dedup, publish `listing_ids=None` for a full run and the deduplicated processed IDs plus any affected duplicate parents for an incremental run; set `market_changed=True`.
- At the end of `run_targeted_reprocess()`, publish the processed IDs with `market_changed=False`.
- For publisher override, query linked listing IDs in the same transaction, refresh those read-model rows, and commit override + refreshed rows + version atomically.
- Append publication result to returned stats under `public_read_model`; do not hide failures in a log-only path.

- [ ] **Step 5: Add explicit repair/compare CLI**

Register:

```text
radar.py signal-read-model --refresh
radar.py signal-read-model --compare --limit 200
radar.py signal-read-model --refresh --compare --limit 200
```

The compare output contains only counts, listing IDs, filter case names, and field names that differ. It must not print descriptions, phone numbers, source URLs, or full payloads.

- [ ] **Step 6: Run pipeline and CLI tests**

```powershell
& $py -X utf8 -m pytest `
  tests\test_signal_read_model.py `
  tests\test_guland_targeted_reprocess.py `
  tests\test_guland_publisher_repository.py `
  tests\test_reprocess_review_hidden.py -q
& $py -X utf8 radar.py signal-read-model --refresh --compare --limit 200
```

Expected: tests PASS and compare reports zero unexplained differences.

- [ ] **Step 7: Commit**

```powershell
git add services/public_data_publish.py cleansing/reprocess.py db/guland_publishers.py app.py cli/system.py radar.py tests/test_signal_read_model.py tests/test_guland_targeted_reprocess.py tests/test_guland_publisher_repository.py
git commit -m "feat: publish signal read model after data changes"
```

## Task 6: Phase 1 Verification, Documentation, and Controlled Rollout

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/operations.md`
- Modify: `docs/dev_commands.md`
- Modify: `AGENTS.md`
- Test: existing focused/full suites

**Interfaces:**
- Produces: an operator-visible refresh/compare/rollback runbook
- Produces: baseline and feature-on measurements separated by local, VPS-local, and public HTTPS

- [ ] **Step 1: Run the complete Phase 1 verification set**

```powershell
& $py -X utf8 -m py_compile `
  app.py `
  db\guland_publishers.py `
  db\public_dataset_versions.py `
  services\market_data.py `
  services\signal_read_model.py `
  services\public_data_publish.py `
  cleansing\reprocess.py
& $py -X utf8 -m pytest `
  tests\test_market_data_performance.py `
  tests\test_public_dataset_versions.py `
  tests\test_signal_read_model.py `
  tests\test_guest_visibility.py `
  tests\test_source_policy.py `
  tests\test_guland_publisher_repository.py `
  tests\test_guland_targeted_reprocess.py `
  tests\test_reprocess_review_hidden.py `
  tests\test_security_hardening.py `
  tests\test_schema_init_permissions.py -q
git diff --check
```

- [ ] **Step 2: Update docs with actual implementation facts**

Document:

- table/index names and ownership;
- feature flag and rollback command;
- refresh/compare command and safe output;
- when pipeline refresh is full versus incremental;
- `ANALYZE` thresholds and inspection query;
- parity and cold/warm benchmark commands;
- failure semantics that keep the old version active.

- [ ] **Step 3: Commit documentation**

```powershell
git add AGENTS.md docs/architecture.md docs/operations.md docs/dev_commands.md
git commit -m "docs: document signal read model operations"
```

- [ ] **Step 4: Deploy feature-off and verify legacy behavior**

Before push/deploy, pull/rebase current `origin/main`. Deploy with `RADAR_SIGNAL_READ_MODEL_ENABLED=0`, initialize schema, run `ANALYZE` on the hot tables, and measure legacy cold/warm endpoints. Verify service active, public redaction, and browser signal cards.

- [ ] **Step 5: Backfill, compare, then enable the read model**

On the VPS as the `radar` runtime user:

```bash
cd /opt/radar-bds/current
set -a
source /etc/radar-bds/radar.env
set +a
/opt/radar-bds/.venv/bin/python -X utf8 radar.py signal-read-model --refresh --compare --limit 200
```

Only if compare passes, set `RADAR_SIGNAL_READ_MODEL_ENABLED=1`, restart `radar-bds.service`, and rerun VPS-local plus public benchmark paths.

- [ ] **Step 6: Apply the Phase 1 release gate**

Pass only when:

- feature-off and feature-on correctness both pass;
- zero unexplained parity differences remain;
- cold read-model p95 <= 500 ms on VPS-localhost;
- public cold feed is sub-second under normal load;
- `public_dataset_versions.signals` increments after a controlled refresh;
- rollback to `RADAR_SIGNAL_READ_MODEL_ENABLED=0` is tested.

If any item fails, disable the flag, keep the additive schema/data for diagnosis, and do not begin Phase 2.
