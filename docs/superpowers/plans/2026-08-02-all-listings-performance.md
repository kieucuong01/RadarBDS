# All-Listings Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the homepage `Tin rao` tab return the existing `/api/listings` contract in sub-second cold time, share the versioned public-cache architecture used by `Săn Deal`, and remain safe under a large burst of repeated anonymous requests.

**Architecture:** Broaden the existing transactional `signal_card_read_model` into the shared public card projection while preserving `is_actionable` as the signal-only gate. Add an independent `listings` dataset version, a focused all-listings service with a legacy fallback and exact parity tooling, then put `/api/listings` behind canonical Redis single-flight/stale caching and the existing Nginx anonymous microcache. Keep the route handler limited to parsing, bounded cache-key construction, and response headers.

**Tech Stack:** Python 3.12, Flask, PostgreSQL 17/18, psycopg pooled connections, Redis, Nginx, pytest, PowerShell verification, k6, existing idempotent `db.schema` migrations.

## Global Constraints

- Preserve `/api/listings` response keys, listing fields, full `imgs` arrays, legal-first image order, pagination, filters, sorts, modal behavior, and table/grid rendering.
- Preserve Guest/Free/VIP redaction. Original URLs, seller/contact data, and phone numbers embedded in text must be absent before a shared payload can be cached.
- Preserve admin behavior, but keep admin and any cookie/Authorization request private and edge-cache bypassed.
- Do not change crawler, normalization, deduplication, valuation, signal-scoring, URL, sitemap, or SEO behavior.
- Broaden `signal_card_read_model` only to stable public-base listings. `/api/signals` must still require both the current completeness gate and `actionable_signal_sql()`. The separate `listing_is_signal` field preserves only the legacy `Tin rao` badge and must not drive signal feeds or counts.
- Keep `signal_card_read_model` and `public_dataset_versions` additive and transactional. A failed refresh must leave the old rows and versions live.
- The new route is ready only when `RADAR_LISTING_READ_MODEL_ENABLED` is not `0`, `RADAR_SIGNAL_READ_MODEL_ENABLED=1`, and durable `public_dataset_versions.listings > 0`.
- Keep `_load_listing_feed_legacy()` callable for route-specific rollback and deterministic parity checks.
- Clamp page to `1..2000`, limit to `1..100`, keyword to 80 characters, and multi-value filters to the existing public bounds before building a query or cache key.
- Do not respond to a performance miss by increasing Gunicorn workers, PostgreSQL pool size, statement timeouts, Redis memory, or Nginx timeouts.
- Release latency gates are VPS-local cold p95 <= 500 ms, public guest cache-hit p95 <= 250 ms, and first 50 browser rows/cards visible <= 1.5 s on the production desktop test connection.
- The 1,000-5,000 target applies to controlled, mostly repeated/cacheable anonymous traffic. Stop at the existing abort thresholds; do not claim 5,000 unique cold database queries are safe.
- Write a failing test before every implementation change, run it to confirm RED, make the smallest implementation, run it GREEN, and create one focused commit per task.

---

## File Structure

| File | Responsibility |
|---|---|
| `db/public_dataset_versions.py` | Add and validate the durable `listings` version |
| `db/schema.py` | Add listing-specific projection fields, version row, and all-listings indexes |
| `services/signal_read_model.py` | Refresh all stable public-base rows and bump `signals` plus `listings` atomically |
| `services/listing_feed.py` | Own legacy/read-model selection, all-listings filters, sorting, images, formatting, and parity-stable payloads |
| `app.py` | Parse and bound `/api/listings`, build canonical cache input, invoke the service, and emit safe headers |
| `services/public_cache_keys.py` | Allow the `listings` endpoint and `complete` response-changing field |
| `cli/system.py`, `radar.py` | Compare legacy and read-model listing payloads without logging sensitive content |
| `services/public_prewarm.py`, `config/public_cache_warm_routes.json` | Prewarm the default all-listings first page without credentials |
| `deployment/ubuntu24/nginx-radar-bds.conf` | Add exact anonymous microcache coverage for `/api/listings` |
| `scripts/verify_public_cache.ps1` | Verify listings HIT, version, redaction, and cookie/auth bypass |
| `scripts/benchmark_public_read_path.py` | Include the default listings route in cold/warm measurements |
| `scripts/load/radar_public_load.js` | Exercise the tab path in controlled default and mixed-key capacity tests |
| `tests/test_listing_feed.py` | Query shape, filters, sorts, image enrichment, readiness, and payload parity |
| `tests/test_signal_read_model.py` | Expanded projection, completeness, versioning, and refresh atomicity |
| `tests/test_public_cache_keys.py`, `tests/test_public_cache_headers.py` | Canonical key and privacy/cache behavior |
| `tests/test_public_prewarm.py`, `tests/test_deployment_units.py` | Prewarm, Nginx, verifier, benchmark, and load-harness contracts |
| `tests/test_refactor_structure.py` | Keep one guarded paginated all-listings request and append/reset behavior |
| `.env.example`, `AGENTS.md`, `docs/architecture.md`, `docs/operations.md`, `docs/dev_commands.md` | Durable handoff, flags, commands, rollout, evidence, and rollback |

## Task 1: Broaden the Shared Projection and Add the Listings Version

**Files:**
- Modify: `db/public_dataset_versions.py`
- Modify: `db/schema.py:1390-1510`
- Modify: `services/signal_read_model.py`
- Modify: `tests/test_signal_read_model.py`

**Interfaces:**
- Produces: `DATASET_LISTINGS = "listings"`
- Adds: `signal_card_read_model.listing_price_per_m2 DOUBLE PRECISION`
- Adds: `signal_card_read_model.listing_is_signal BOOLEAN NOT NULL DEFAULT FALSE`
- Preserves: `actual_ppm2` as the valuation/display expression used by signals
- Changes: every non-noop projection refresh bumps `signals` and `listings`; `market` is added only when `market_changed=True`

- [ ] **Step 1: Write failing schema, base-row, actionability, and version tests**

Update the schema assertion and add an integration test that inserts an incomplete but public-base row:

```python
def test_signal_read_model_schema_and_indexes_exist():
    with connection.get_conn() as conn:
        columns = {
            row["column_name"]
            for row in conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name='signal_card_read_model'
                """
            ).fetchall()
        }
        indexes = {
            row["indexname"]
            for row in conn.execute(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname='public'
                  AND tablename='signal_card_read_model'
                """
            ).fetchall()
        }
        versions = get_dataset_versions(
            conn, ("signals", "listings", "market")
        )

    assert {"listing_price_per_m2", "listing_is_signal"} <= columns
    assert {
        "idx_signal_card_all_public_newest",
        "idx_signal_card_all_public_filter",
        "idx_signal_card_all_public_drop",
    } <= indexes
    assert set(versions) == {"signals", "listings", "market"}


def test_refresh_keeps_incomplete_public_listing_but_not_as_signal():
    from services.signal_read_model import refresh_signal_card_read_model

    with connection.get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO listings(
                source, source_id, url, title, description,
                source_status, ward, price_ty, price_per_m2, area_m2
            )
            VALUES (
                'facebook', 'read-model-incomplete',
                'https://example.invalid/read-model-incomplete',
                'Incomplete public row', '', 'active', NULL, 2.5, 12.5, NULL
            )
            RETURNING id
            """
        ).fetchone()
        listing_id = int(row["id"])
        result = refresh_signal_card_read_model(
            conn, listing_ids=(listing_id,)
        )
        projected = conn.execute(
            """
            SELECT listing_id, listing_price_per_m2,
                   listing_is_signal, is_actionable
            FROM signal_card_read_model
            WHERE listing_id=?
            """,
            (listing_id,),
        ).fetchone()
        conn.execute("DELETE FROM listings WHERE id=?", (listing_id,))

    assert result.versions.keys() >= {"signals", "listings"}
    assert projected["listing_id"] == listing_id
    assert projected["listing_price_per_m2"] == 12.5
    assert projected["listing_is_signal"] is False
    assert projected["is_actionable"] is False
```

Change the existing mock event assertion to require:

```python
assert events.index(("insert",)) < events.index(
    ("bump", ("signals", "listings"))
)
```

- [ ] **Step 2: Run the focused tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_signal_read_model.py -q
```

Expected: FAIL because the dataset name, projection column/indexes, incomplete row, and dual-version bump do not exist.

- [ ] **Step 3: Add the durable dataset name and idempotent migration**

In `db/public_dataset_versions.py`:

```python
DATASET_SIGNALS = "signals"
DATASET_LISTINGS = "listings"
DATASET_MARKET = "market"
ALLOWED_DATASETS = frozenset(
    {DATASET_SIGNALS, DATASET_LISTINGS, DATASET_MARKET}
)
```

In `_migrate_public_read_model()`:

```sql
INSERT INTO public_dataset_versions(dataset_name, version)
VALUES ('signals', 0), ('listings', 0), ('market', 0)
ON CONFLICT (dataset_name) DO NOTHING;

ALTER TABLE signal_card_read_model
ADD COLUMN IF NOT EXISTS listing_price_per_m2 DOUBLE PRECISION;

ALTER TABLE signal_card_read_model
ADD COLUMN IF NOT EXISTS listing_is_signal BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_signal_card_all_public_newest
ON signal_card_read_model(
    publisher_rank, activity_at DESC, listing_id DESC
)
WHERE publisher_visible_public AND NOT possibly_duplicate;

CREATE INDEX IF NOT EXISTS idx_signal_card_all_public_filter
ON signal_card_read_model(
    source, ward, property_type, publisher_rank,
    activity_at DESC, listing_id DESC
)
WHERE publisher_visible_public;

CREATE INDEX IF NOT EXISTS idx_signal_card_all_public_drop
ON signal_card_read_model(
    publisher_rank, activity_at DESC, listing_id DESC
)
WHERE publisher_visible_public AND price_dropped;
```

Also place both columns in the `CREATE TABLE IF NOT EXISTS` definition so clean databases and upgraded databases converge.

- [ ] **Step 4: Broaden the refresh without broadening signal eligibility**

Add `listing_price_per_m2` after `price_ty` and `listing_is_signal` after `is_actionable` in `READ_MODEL_COLUMNS`. Select the original listing value and define the two distinct booleans in `_select_sql()`:

```python
complete_listing_expr = _signal_listing_data_sql("l")
is_actionable_expr = (
    f"(({complete_listing_expr}) AND ({actionable_expr}))"
)
listing_is_signal_expr = (
    f"(({actionable_signal_sql('v')}) "
    f"AND ({actionable_signal_sql('sv')}))"
)
```

The SELECT column order must place the listing value before the existing valuation value and must use the combined actionability expression:

```sql
l.price_ty,
l.price_per_m2 AS listing_price_per_m2,
({actual_expr}) AS actual_ppm2,
({is_actionable_expr}) AS is_actionable,
({listing_is_signal_expr}) AS listing_is_signal,
```

The base WHERE must be exactly the stable public-base predicate plus an optional ID restriction; remove the standalone completeness clause:

```sql
WHERE COALESCE(l.probably_sold, 0)=0
  AND COALESCE(l.is_blacklisted, 0)=0
  AND COALESCE(l.review_hidden, 0)=0
  AND COALESCE(l.source_status, 'unknown') <> 'inactive'
  {listing_id_clause}
```

Import `DATASET_LISTINGS` and publish versions with:

```python
datasets = (
    (DATASET_SIGNALS, DATASET_LISTINGS, DATASET_MARKET)
    if market_changed
    else (DATASET_SIGNALS, DATASET_LISTINGS)
)
```

For an empty incremental set, read and return both current versions without bumping:

```python
versions = get_dataset_versions(
    conn, (DATASET_SIGNALS, DATASET_LISTINGS)
)
return SignalReadModelRefresh("noop", 0, versions, 0.0)
```

- [ ] **Step 5: Run projection tests GREEN and commit**

```powershell
& $py -X utf8 -m pytest tests\test_signal_read_model.py -q
git diff --check
git add db/public_dataset_versions.py db/schema.py services/signal_read_model.py tests/test_signal_read_model.py
git commit -m "feat: broaden public listing card projection"
```

## Task 2: Extract a Parity-Stable All-Listings Service

**Files:**
- Create: `services/listing_feed.py`
- Create: `tests/test_listing_feed.py`
- Modify: `app.py:5104-5275`
- Modify: `tests/test_source_policy.py`
- Modify: `tests/test_drop_filter.py`

**Interfaces:**
- Produces: `load_listing_feed(db_path, *, sources=None, wards=None, prop_types=None, only_drops=False, sort_by="date", sort_dir="desc", page=1, limit=50, area_min=0, area_max=0, price_min=0, price_max=0, area_ranges=None, price_ranges=None, keyword="", tier="guest", date_range=None, complete_only=False, include_guland_high_activity=False, listings_version=0) -> dict`
- Produces: `load_listings_from_read_model` with every `load_listing_feed` listing/filter parameter and no `listings_version` parameter
- Produces: `_load_listing_feed_legacy` with every `load_listing_feed` listing/filter parameter and no `listings_version` parameter
- Produces: `build_listing_read_model_filters(*, sources=None, wards=None, prop_types=None, only_drops=False, area_min=0, area_max=0, price_min=0, price_max=0, area_ranges=None, price_ranges=None, keyword="", date_range=None, complete_only=False, allow_high_activity=False) -> tuple[str, list]`
- Produces: `listing_read_model_enabled(listings_version: int) -> bool`

- [ ] **Step 1: Write failing readiness, SQL-shape, bounds, and image tests**

Create `tests/test_listing_feed.py` with fake connections that record every statement:

```python
def test_listing_read_model_gate_requires_both_flags_and_positive_version(
    monkeypatch,
):
    from services.listing_feed import listing_read_model_enabled

    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    assert listing_read_model_enabled(1) is True
    assert listing_read_model_enabled(0) is False

    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "0")
    assert listing_read_model_enabled(1) is False

    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "1")
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "0")
    assert listing_read_model_enabled(1) is False


def test_read_model_listing_query_is_bounded_and_has_no_valuation_cte(
    monkeypatch,
):
    from services import listing_feed

    conn = RecordingListingConnection(candidate_rows=[], image_rows=[])
    monkeypatch.setattr(
        listing_feed, "_open_read_conn", lambda _db_path=None: conn
    )

    payload = listing_feed.load_listings_from_read_model(
        None,
        sources=["facebook"],
        wards=["Tan An"],
        page=99999,
        limit=999,
        tier="guest",
        date_range="3m",
    )

    page_sql, page_params = conn.queries[1]
    assert "FROM signal_card_read_model rm" in page_sql
    assert "SELECT COUNT(*) AS total_count FROM filtered" in page_sql
    assert "LEFT JOIN page_ids" in page_sql
    assert "latest_valuation" not in page_sql.lower()
    assert "valuation_results" not in page_sql.lower()
    assert page_params[-2:] == [100, 199900]
    assert payload["page"] == 2000
    assert payload["limit"] == 100
    assert conn.closed is True


def test_read_model_enriches_only_selected_ids_in_legal_image_order(
    monkeypatch,
):
    from services import listing_feed

    conn = RecordingListingConnection(
        candidate_rows=[listing_row(7, total_count=1)],
        image_rows=[
            {"listing_id": 7, "local_path": "data/images/so.jpg", "img_url": None},
            {"listing_id": 7, "local_path": "data/images/land.jpg", "img_url": None},
        ],
    )
    monkeypatch.setattr(
        listing_feed, "_open_read_conn", lambda _db_path=None: conn
    )
    monkeypatch.setattr(
        listing_feed,
        "resolve_image_url",
        lambda local, remote, prefer_thumb=False: local or remote,
    )

    payload = listing_feed.load_listings_from_read_model(None, tier="admin")

    image_sql, image_params = conn.queries[2]
    assert "WHERE listing_id IN (?)" in image_sql
    assert "ORDER BY listing_id" in image_sql
    assert image_params == [7]
    assert payload["listings"][0]["imgs"] == [
        "data/images/so.jpg",
        "data/images/land.jpg",
    ]


def test_out_of_range_page_keeps_exact_total_without_image_query(monkeypatch):
    from services import listing_feed

    conn = RecordingListingConnection(
        candidate_rows=[{"id": None, "total_count": 137}],
        image_rows=[],
    )
    monkeypatch.setattr(
        listing_feed, "_open_read_conn", lambda _db_path=None: conn
    )

    payload = listing_feed.load_listings_from_read_model(
        None, page=20, limit=50, tier="guest"
    )

    assert payload["listings"] == []
    assert payload["total"] == 137
    assert payload["pages"] == 3
    assert payload["has_more"] is False
    assert len(conn.queries) == 2
```

Add parameterized filter and sort checks:

```python
@pytest.mark.parametrize(
    ("sort_by", "sort_dir", "needle"),
    (
        ("area", "asc", "rm.area_m2 ASC NULLS LAST"),
        ("price", "desc", "rm.price_ty DESC NULLS LAST"),
        ("price_m2", "asc", "rm.listing_price_per_m2 ASC NULLS LAST"),
        ("fair", "desc", "rm.fair_ppm2 DESC NULLS LAST"),
        ("date", "desc", "rm.listing_id DESC"),
        ("ward", "asc", "rm.ward ASC NULLS LAST"),
        ("prop_type", "asc", "rm.property_type ASC NULLS LAST"),
    ),
)
def test_listing_sort_is_whitelisted_and_stable(sort_by, sort_dir, needle):
    sql = listing_sort_sql(sort_by, sort_dir, "rm")
    assert sql.startswith("rm.publisher_rank ASC")
    assert needle in sql
    assert sql.endswith("rm.listing_id DESC")
```

- [ ] **Step 2: Run the new tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_feed.py -q
```

Expected: import failure because `services/listing_feed.py` does not exist.

- [ ] **Step 3: Implement the gate, canonical filters, and stable sort**

Create `services/listing_feed.py` with these public constants and functions:

```python
VALID_LISTING_SORTS = frozenset(
    {"area", "price", "price_m2", "fair", "date", "ward", "prop_type"}
)


def listing_read_model_enabled(listings_version: int) -> bool:
    listing_flag = os.getenv(
        "RADAR_LISTING_READ_MODEL_ENABLED", "1"
    ).strip() != "0"
    signal_flag = os.getenv(
        "RADAR_SIGNAL_READ_MODEL_ENABLED", "0"
    ).strip() == "1"
    return listing_flag and signal_flag and int(listings_version or 0) > 0


def listing_sort_sql(sort_by: str, sort_dir: str, alias: str) -> str:
    selected = sort_by if sort_by in VALID_LISTING_SORTS else "date"
    direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"
    expressions = {
        "area": f"{alias}.area_m2",
        "price": f"{alias}.price_ty",
        "price_m2": f"{alias}.listing_price_per_m2",
        "fair": f"{alias}.fair_ppm2",
        "date": listing_activity_at_sql(alias),
        "ward": f"{alias}.ward",
        "prop_type": f"{alias}.property_type",
    }
    return (
        f"{alias}.publisher_rank ASC, "
        f"{expressions[selected]} {direction} NULLS LAST, "
        f"{alias}.listing_id DESC"
    )
```

`build_listing_read_model_filters()` must start with public publisher and duplicate/drop policy, then reuse the established range, keyword, and date helpers:

```python
clauses: list[str] = []
params: list = []
if not allow_high_activity:
    clauses.append("rm.publisher_visible_public")
clauses.append("rm.price_dropped" if only_drops else "NOT rm.possibly_duplicate")

if complete_only:
    clauses.append(
        "NULLIF(BTRIM(COALESCE(rm.ward, '')), '') IS NOT NULL "
        "AND COALESCE(rm.price_ty, 0) > 0 "
        "AND COALESCE(rm.area_m2, 0) > 0"
    )
```

Use `DEFAULT_VISIBLE_SOURCES` when no source is supplied. Normalize property types and bind every list value. Extend the clauses and parameters with these exact helper calls:

```python
range_clauses, range_params = _range_filters(
    area_min,
    area_max,
    price_min,
    price_max,
    "rm.",
    area_ranges=area_ranges,
    price_ranges=price_ranges,
)
clauses.extend(range_clauses)
params.extend(range_params)
search_clauses, search_params = keyword_search_filter(keyword, "rm.")
clauses.extend(search_clauses)
params.extend(search_params)
date_clauses, date_params = listing_date_range_filter(date_range, "rm.")
clauses.extend(date_clauses)
params.extend(date_params)
return " AND ".join(clauses), params
```

Do not add `is_actionable` or `mos_min` to this predicate. Emitting the publisher clause only for public traffic allows PostgreSQL to use the public partial indexes; the admin override intentionally omits it.

Both the read-model and legacy loaders must derive the override internally rather than trusting a direct caller:

```python
allow_high_activity = bool(
    tier == "admin" and include_guland_high_activity
)
```

- [ ] **Step 4: Implement the compact page query and selected-ID image enrichment**

Use one pooled connection, a local timeout, one compact filtered-ID/page query, and at most one image query. The totals-left-join shape preserves the exact total even when the requested page is beyond the final row:

```python
WITH filtered AS MATERIALIZED (
    SELECT rm.listing_id,
           rm.publisher_rank,
           rm.area_m2,
           rm.price_ty,
           rm.listing_price_per_m2,
           rm.fair_ppm2,
           rm.source,
           rm.price_updated_at,
           rm.first_seen_at,
           rm.crawled_at,
           rm.posted_at,
           rm.ward,
           rm.property_type
    FROM signal_card_read_model rm
    WHERE {where_sql}
),
page_ids AS MATERIALIZED (
    SELECT f.listing_id
    FROM filtered f
    ORDER BY {page_order_sql}
    LIMIT ? OFFSET ?
),
totals AS (
    SELECT COUNT(*) AS total_count FROM filtered
)
SELECT rm.listing_id AS id, rm.*, totals.total_count,
       rm.fair_ppm2 AS fair_ppm2_display,
       rm.mos_pct AS mos_pct_display,
       rm.listing_is_signal AS actionable_signal,
       0 AS is_fresh_locked
FROM totals
LEFT JOIN page_ids p ON TRUE
LEFT JOIN signal_card_read_model rm ON rm.listing_id=p.listing_id
ORDER BY {result_order_sql}
```

Build `page_order_sql` with `listing_sort_sql(sort_by, sort_dir, "f")` and `result_order_sql` with alias `rm`. Read `total_count` from the first returned row, then discard the synthetic row whose `id` is null before formatting and image enrichment.

Set the timeout before the page query:

```python
conn.execute(
    "SELECT set_config('statement_timeout', ?, true)",
    (f"{_statement_timeout_ms()}ms",),
)
```

For selected IDs only:

```python
SELECT listing_id, local_path, img_url
FROM listing_images
WHERE listing_id IN ({markers})
ORDER BY listing_id, {LEGAL_IMAGE_ORDER_SQL}
```

Resolve every image with `resolve_image_url(local_path, img_url)` without `prefer_thumb=True`; this preserves the existing `imgs` array rather than changing the API to thumbnail-only.

- [ ] **Step 5: Centralize exact serialization and move the legacy loader**

Move the current SQL and related-drop behavior from `app.py::api_listings()` into `_load_listing_feed_legacy()`. Move the current listing dictionary into one shared formatter used by both paths:

```python
def _valid_price_drop_values(price_ty, price_first_ty) -> bool:
    try:
        price = float(price_ty) if price_ty is not None else None
        first_price = (
            float(price_first_ty) if price_first_ty is not None else None
        )
    except (TypeError, ValueError):
        return False
    return bool(
        price
        and first_price
        and price < first_price * 0.99
        and price >= first_price * 0.60
    )
```

```python
def _format_listing_row(row, imgs: list[str], *, tier: str) -> dict:
    badge_meta = signal_badge_metadata(row)
    activity_at, card_date_reason = listing_card_activity(row)
    price_ty = _row_get(row, "price_ty")
    price_first_ty = _row_get(row, "price_first_ty")
    price_dropped = _valid_price_drop_values(price_ty, price_first_ty)
    drop_pct = _row_get(row, "price_drop_pct") if price_dropped else None
    return redact_for_tier(
        {
            "id": int(_row_get(row, "id")),
            "title": _row_get(row, "title", "") or "",
            "description": _row_get(row, "description", "") or "",
            "price_ty": price_ty,
            "area_m2": _row_get(row, "area_m2"),
            "frontage_m": _row_get(row, "frontage_m"),
            "depth_m": _row_get(row, "depth_m"),
            "price_per_m2": round(_row_get(row, "listing_price_per_m2"), 1)
            if _row_get(row, "listing_price_per_m2") else None,
            "prop_type": _row_get(row, "property_type"),
            "prop_type_label": badge_meta["property_type_label"],
            "road_tier": _row_get(row, "road_tier"),
            "road_type": _row_get(row, "road_type"),
            "road_width_m": badge_meta["road_width_m"],
            "road_label": badge_meta["road_label"],
            "street_label": badge_meta["street_label"],
            "tho_cu_m2": badge_meta["tho_cu_m2"],
            "tho_cu_ratio": badge_meta["tho_cu_ratio"],
            "tho_cu_label": badge_meta["tho_cu_label"],
            "ward": _row_get(row, "ward"),
            "url": _row_get(row, "url"),
            "is_signal": bool(_row_get(row, "actionable_signal", False)),
            "mos_pct": round(_row_get(row, "mos_pct", 0) or 0, 1),
            "fair_ppm2": round(_row_get(row, "fair_ppm2"), 1)
            if _row_get(row, "fair_ppm2") else None,
            "fair_ppm2_old": round(_row_get(row, "fair_ppm2_old"), 1)
            if _row_get(row, "fair_ppm2_old") else None,
            "fair_ppm2_new": round(_row_get(row, "fair_ppm2_new"), 1)
            if _row_get(row, "fair_ppm2_new") else None,
            "mos_pct_old": round(_row_get(row, "mos_pct_old", 0) or 0, 1),
            "mos_pct_new": round(_row_get(row, "mos_pct_new", 0) or 0, 1),
            "fair_ppm2_display": round(_row_get(row, "fair_ppm2_display"), 1)
            if _row_get(row, "fair_ppm2_display") else None,
            "mos_pct_display": round(
                _row_get(row, "mos_pct_display", 0) or 0, 1
            ),
            "days_ago": _days_ago(activity_at),
            "card_date_reason": card_date_reason,
            "is_hot": bool(_row_get(row, "is_hot", False)),
            "price_dropped": price_dropped,
            "suspicious_bait": bool(
                _row_get(row, "suspicious_bait", False)
            ),
            "drop_pct": drop_pct,
            "price_first_ty": price_first_ty,
            "duplicate_of_id": _row_get(row, "duplicate_of_id"),
            "source": _row_get(row, "source"),
            "imgs": imgs,
            "is_fresh_locked": bool(
                _row_get(row, "is_fresh_locked", False)
            ),
        },
        tier,
    )
```

Before calling the formatter from the legacy path, alias `l.price_per_m2 AS listing_price_per_m2`. Preserve the legacy related-drop override before formatting by replacing `price_first_ty`, `price_drop_pct`, and `price_dropped` in a mutable row dictionary.

The stable dispatch interface is:

```python
def load_listing_feed(
    db_path,
    *,
    sources=None,
    wards=None,
    prop_types=None,
    only_drops=False,
    sort_by="date",
    sort_dir="desc",
    page=1,
    limit=50,
    area_min=0,
    area_max=0,
    price_min=0,
    price_max=0,
    area_ranges=None,
    price_ranges=None,
    keyword="",
    tier="guest",
    date_range=None,
    complete_only=False,
    include_guland_high_activity=False,
    listings_version=0,
) -> dict:
    loader_kwargs = {
        "sources": sources,
        "wards": wards,
        "prop_types": prop_types,
        "only_drops": only_drops,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "page": page,
        "limit": limit,
        "area_min": area_min,
        "area_max": area_max,
        "price_min": price_min,
        "price_max": price_max,
        "area_ranges": area_ranges,
        "price_ranges": price_ranges,
        "keyword": keyword,
        "tier": tier,
        "date_range": date_range,
        "complete_only": complete_only,
        "include_guland_high_activity": include_guland_high_activity,
    }
    if listing_read_model_enabled(listings_version):
        return load_listings_from_read_model(db_path, **loader_kwargs)
    return _load_listing_feed_legacy(db_path, **loader_kwargs)
```

- [ ] **Step 6: Replace the route body temporarily with a direct service call**

Keep the same request parsing for this task, but remove all SQL/formatting from `app.py` and return:

```python
payload = load_listing_feed(
    _db_handle(),
    sources=sources,
    wards=wards,
    prop_types=prop_types,
    only_drops=only_drops,
    sort_by=sort_by,
    sort_dir=sort_dir,
    page=page,
    limit=limit,
    tier=tier,
    keyword=keyword,
    date_range=date_range,
    complete_only=complete_only,
    include_guland_high_activity=include_guland_high_activity,
    listings_version=0,
    **range_kwargs,
)
return jsonify(payload)
```

Passing version `0` deliberately keeps this intermediate commit on the extracted legacy loader.

- [ ] **Step 7: Run service and existing API behavior tests GREEN and commit**

```powershell
& $py -X utf8 -m pytest tests\test_listing_feed.py tests\test_source_policy.py tests\test_drop_filter.py tests\test_guest_visibility.py -q
& $py -X utf8 -m py_compile app.py services\listing_feed.py
git diff --check
git add app.py services/listing_feed.py tests/test_listing_feed.py tests/test_source_policy.py tests/test_drop_filter.py
git commit -m "refactor: extract all listings feed service"
```

## Task 3: Add Readiness-Gated Application Caching to `/api/listings`

**Files:**
- Modify: `app.py`
- Modify: `services/public_cache_keys.py`
- Modify: `tests/test_public_cache_keys.py`
- Modify: `tests/test_public_cache_headers.py`
- Modify: `tests/test_market_data_performance.py`
- Modify: `tests/test_refactor_structure.py`

**Interfaces:**
- Adds cache endpoint: `listings`
- Adds response-changing key field: `complete`
- Adds route dataset tuple: `_LISTING_DATASETS = (DATASET_LISTINGS,)`
- Emits: `X-Radar-Dataset-Version` with the resolved integer `listings` version

- [ ] **Step 1: Write failing canonical-key and route-orchestration tests**

Add to `tests/test_public_cache_keys.py`:

```python
def test_listing_cache_key_includes_complete_sort_page_and_version():
    base = build_public_cache_key(
        endpoint="listings",
        tier="guest",
        versions={"listings": 4},
        query={
            "complete": False,
            "sort": "date:desc",
            "page": 1,
            "limit": 50,
        },
    )
    for changed in (
        {"complete": True, "sort": "date:desc", "page": 1, "limit": 50},
        {"complete": False, "sort": "price:asc", "page": 1, "limit": 50},
        {"complete": False, "sort": "date:desc", "page": 2, "limit": 50},
    ):
        assert base != build_public_cache_key(
            endpoint="listings",
            tier="guest",
            versions={"listings": 4},
            query=changed,
        )


def test_unknown_listing_query_fields_do_not_change_cache_key():
    known = canonical_query(
        {"page": 1, "complete": True, "sort": "date:desc"}
    )
    unknown = canonical_query(
        {
            "page": 1,
            "complete": True,
            "sort": "date:desc",
            "load_run": "different-every-time",
        }
    )
    assert known == unknown
```

Add route tests that capture both cache arguments and loader arguments:

```python
def test_api_listings_uses_identical_bounded_values_for_cache_and_loader(
    monkeypatch, client
):
    captured = {}
    monkeypatch.setattr(
        radar_app,
        "get_current_dataset_versions",
        lambda names: {"listings": 9},
    )
    monkeypatch.setattr(
        radar_app,
        "load_listing_feed",
        lambda *_args, **kwargs: captured.setdefault("loader", kwargs) or {},
    )

    def fake_cache(**kwargs):
        captured["cache"] = kwargs
        return CacheResult(kwargs["loader"](), "miss", 1.0)

    monkeypatch.setattr(radar_app, "get_or_load_public_payload", fake_cache)
    response = client.get(
        "/api/listings?page=9000&limit=900&complete=1&"
        "sort_by=price&sort_dir=desc&unknown=changes-nothing"
    )

    assert response.status_code == 200
    assert captured["cache"]["endpoint"] == "listings"
    assert captured["cache"]["versions"] == {"listings": 9}
    assert captured["cache"]["query"]["page"] == 2000
    assert captured["cache"]["query"]["limit"] == 100
    assert captured["cache"]["query"]["complete"] is True
    assert captured["cache"]["query"]["sort"] == "price:desc"
    assert captured["loader"]["page"] == 2000
    assert captured["loader"]["limit"] == 100
    assert captured["loader"]["listings_version"] == 9
    assert response.headers["X-Radar-Dataset-Version"] == "9"
```

Mirror the existing signal privacy tests for `/api/listings`: anonymous guest is public-cache eligible; session cookie and Authorization are `private, no-store`; admin bypasses; a guest cached listing has no URL/contact/embedded phone; `PublicCacheBusy` returns the controlled 503.

Add a static regression guard for the already-correct frontend request lifecycle:

```python
def test_all_listings_runtime_uses_one_guarded_paginated_request():
    text = _read("static/js/main/listings.js")
    assert "if (listingsLoading) return;" in text
    assert text.count("fetchJSONCached('listings', `/api/listings?") == 1
    assert "&page=${page}&limit=50" in text
    assert "loadedListings = page === 1 ? items.slice() : loadedListings.concat(items);" in text
    assert "renderListingRows(items, { append: page !== 1 });" in text
    assert "renderListingCards(items, { append: page !== 1 });" in text
```

This guard is expected to be GREEN before the backend edit; the new cache/route tests in the same run provide the RED state.

- [ ] **Step 2: Run the focused tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_public_cache_keys.py tests\test_public_cache_headers.py tests\test_market_data_performance.py tests\test_refactor_structure.py -q
```

Expected: FAIL because the namespace, `complete` key field, listings version, bounded route, and cache wrapper do not exist.

- [ ] **Step 3: Extend only the canonical cache schema**

In `services/public_cache_keys.py`:

```python
ALLOWED_QUERY_FIELDS = frozenset(
    {
        "active_city", "wards", "sources", "prop_types", "only_drops",
        "trend_period", "mos_min", "area_min", "area_max", "price_min",
        "price_max", "area_ranges", "price_ranges", "keyword",
        "date_range", "include_trend", "include_guland_high_activity",
        "sort", "page", "limit", "include_total", "complete",
    }
)
VALID_ENDPOINTS = frozenset(
    {"signals", "listings", "counts", "dashboard"}
)
```

Do not allow raw query strings, `load_run`, cookies, Authorization, or user IDs into the key builder.

- [ ] **Step 4: Make the route parsing bounded and version-aware**

Import `DATASET_LISTINGS` and `load_listing_feed`. Add:

```python
_LISTING_DATASETS = (DATASET_LISTINGS,)
_VALID_LISTING_SORTS = frozenset(
    {"area", "price", "price_m2", "fair", "date", "ward", "prop_type"}
)


def _listing_dataset_versions() -> dict[str, int]:
    if _public_cache_enabled():
        return _public_dataset_versions(_LISTING_DATASETS)
    try:
        with get_conn() as conn:
            return get_dataset_versions(conn, _LISTING_DATASETS)
    except Exception:
        logger.exception("Unable to resolve listings dataset readiness")
        return {DATASET_LISTINGS: 0}
```

In `api_listings()` call `_bounded_public_filter_values()`, clamp page/limit, whitelist the sort, normalize direction, and obtain `versions = _listing_dataset_versions()` before the cache loader.

- [ ] **Step 5: Wrap the service in the existing cache and response contract**

Build only parsed response-changing state:

```python
cache_query = _public_filter_query(
    active_city=active_city,
    wards=wards,
    sources=sources,
    prop_types=prop_types,
    only_drops=only_drops,
    trend_period=trend_period,
    mos_min=0,
    range_kwargs=range_kwargs,
    keyword=keyword,
    date_range=date_range,
    include_guland_high_activity=include_guland_high_activity,
    complete=complete_only,
    sort=f"{sort_by}:{sort_dir}",
    page=page,
    limit=limit,
)
```

The route body after parsing is:

```python
def _load_listing_payload():
    return load_listing_feed(
        _db_handle(),
        sources=sources,
        wards=wards,
        prop_types=prop_types,
        only_drops=only_drops,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        limit=limit,
        tier=tier,
        keyword=keyword,
        date_range=date_range,
        complete_only=complete_only,
        include_guland_high_activity=include_guland_high_activity,
        listings_version=versions[DATASET_LISTINGS],
        **range_kwargs,
    )

try:
    result = get_or_load_public_payload(
        endpoint="listings",
        tier=tier,
        versions=versions,
        query=cache_query,
        loader=_load_listing_payload,
    )
except (PublicCacheBusy, DatabasePoolBusy) as exc:
    return _public_busy_response(exc)
return _public_json_response(
    result,
    tier=tier,
    dataset_version=versions[DATASET_LISTINGS],
)
```

- [ ] **Step 6: Run cache/route/privacy tests GREEN and commit**

```powershell
& $py -X utf8 -m pytest tests\test_public_cache_keys.py tests\test_public_cache_headers.py tests\test_market_data_performance.py tests\test_listing_feed.py tests\test_source_policy.py tests\test_drop_filter.py tests\test_guest_visibility.py tests\test_refactor_structure.py -q
& $py -X utf8 -m py_compile app.py services\public_cache_keys.py services\listing_feed.py
git diff --check
git add app.py services/public_cache_keys.py tests/test_public_cache_keys.py tests/test_public_cache_headers.py tests/test_market_data_performance.py tests/test_refactor_structure.py
git commit -m "feat: cache the all listings API"
```

## Task 4: Add Deterministic Legacy-vs-Projection Listing Parity

**Files:**
- Modify: `cli/system.py`
- Modify: `radar.py`
- Modify: `tests/test_cli_command_logging.py`
- Modify: `tests/test_listing_feed.py`

**Interfaces:**
- Adds CLI flag: `radar.py signal-read-model --compare-listings`
- Produces: `compare_listing_read_model(limit: int = 200) -> dict`
- Logs only case names, tier, counts, IDs, ordering status, and differing field names

- [ ] **Step 1: Write failing parser and parity-report tests**

```python
def test_signal_read_model_parser_accepts_listing_compare():
    parser = build_parser()
    args = parser.parse_args(
        ["signal-read-model", "--compare-listings", "--limit", "200"]
    )
    assert args.compare_listings is True


def test_listing_compare_reports_only_safe_metadata(monkeypatch):
    from cli import system

    monkeypatch.setattr(
        system,
        "_collect_listing_page",
        lambda loader, **kwargs: (
            {
                "rows": [
                    {"id": 7, "description": "private A", "url": "https://a"}
                ],
                "meta": {"total": 1, "page": 1},
            }
            if loader.__name__.endswith("legacy")
            else {
                "rows": [
                    {"id": 8, "description": "private B", "url": "https://b"}
                ],
                "meta": {"total": 1, "page": 1},
            }
        ),
    )
    report = system.compare_listing_read_model(limit=20)
    rendered = json.dumps(report, ensure_ascii=False)
    assert report["status"] == "mismatch"
    assert "private A" not in rendered
    assert "private B" not in rendered
    assert "https://a" not in rendered
    assert "https://b" not in rendered
    assert "legacy_only_ids" in rendered
    assert "read_model_only_ids" in rendered
```

- [ ] **Step 2: Run the focused tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_cli_command_logging.py tests\test_listing_feed.py -q
```

Expected: FAIL because the flag and listing comparator do not exist.

- [ ] **Step 3: Add bounded comparison cases and collection**

In `cli/system.py`:

```python
_LISTING_READ_MODEL_COMPARE_CASES = (
    ("default_3m", {"date_range": "3m"}),
    ("facebook", {"sources": ["facebook"], "date_range": "3m"}),
    ("guland", {"sources": ["guland"], "date_range": "3m"}),
    ("ward_tan_an", {"wards": ["Tan An"], "date_range": "3m"}),
    ("property_dat_nen", {"prop_types": ["dat_nen"], "date_range": "3m"}),
    ("price_drops", {"only_drops": True, "date_range": "3m"}),
    ("complete", {"complete_only": True, "date_range": "3m"}),
    ("area_range", {"area_min": 60, "area_max": 200, "date_range": "3m"}),
    ("price_range", {"price_min": 1, "price_max": 5, "date_range": "3m"}),
    ("keyword", {"keyword": "duong", "date_range": "3m"}),
    ("date_all", {"date_range": "all"}),
    ("area_asc", {"sort_by": "area", "sort_dir": "asc", "date_range": "3m"}),
    ("price_desc", {"sort_by": "price", "sort_dir": "desc", "date_range": "3m"}),
    ("price_m2_asc", {"sort_by": "price_m2", "sort_dir": "asc", "date_range": "3m"}),
    ("fair_desc", {"sort_by": "fair", "sort_dir": "desc", "date_range": "3m"}),
    ("ward_asc", {"sort_by": "ward", "sort_dir": "asc", "date_range": "3m"}),
    ("prop_type_asc", {"sort_by": "prop_type", "sort_dir": "asc", "date_range": "3m"}),
    ("page_2", {"page": 2, "limit": 50, "date_range": "3m"}),
    (
        "guland_admin_override",
        {
            "sources": ["guland"],
            "include_guland_high_activity": True,
            "date_range": "3m",
        },
    ),
)
```

Collect a bounded page sequence without duplicating a case-provided `page` or `limit`:

```python
def _collect_listing_page(loader, *, limit: int, tier: str, case: dict):
    bounded_limit = min(max(int(limit), 1), 1000)
    start_page = max(int(case.get("page", 1)), 1)
    page_size = min(max(int(case.get("limit", 100)), 1), 100)
    target_rows = page_size if "page" in case else bounded_limit
    call_case = {
        key: value for key, value in case.items()
        if key not in {"page", "limit"}
    }
    collected = []
    first_meta = None
    page = start_page
    while len(collected) < target_rows:
        payload = loader(
            None,
            tier=tier,
            page=page,
            limit=min(page_size, target_rows - len(collected)),
            **call_case,
        )
        if first_meta is None:
            first_meta = {
                key: payload.get(key)
                for key in ("total", "page", "limit", "pages", "has_more", "tier")
            }
        batch = list(payload.get("listings") or ())
        collected.extend(batch)
        if not payload.get("has_more") or not batch or "page" in case:
            break
        page += 1
    return {"rows": collected[:target_rows], "meta": first_meta or {}}
```

For every Guest/Free/VIP/admin case, call `_load_listing_feed_legacy()` and `load_listings_from_read_model()` directly. Compare ordered IDs, every common listing response field, and the metadata keys returned by `_collect_listing_page()`. Append only this safe structure:

```python
{
    "case": case_name,
    "tier": tier,
    "legacy_count": len(legacy_ids),
    "read_model_count": len(read_model_ids),
    "legacy_only_ids": sorted(set(legacy_ids) - set(read_model_ids)),
    "read_model_only_ids": sorted(set(read_model_ids) - set(legacy_ids)),
    "order_mismatch": legacy_ids != read_model_ids,
    "field_names": differing_fields,
    "metadata_fields": differing_metadata_fields,
}
```

- [ ] **Step 4: Wire the explicit CLI flag and fail closed on mismatch**

In `radar.py`:

```python
p_signal_read_model.add_argument("--compare-listings", action="store_true")
```

In `cmd_signal_read_model()`:

```python
if bool(getattr(args, "compare_listings", False)):
    output["listings_compare"] = compare_listing_read_model(
        int(getattr(args, "limit", 200))
    )
```

Exit nonzero if either `compare` or `listings_compare` has `status == "mismatch"`.

- [ ] **Step 5: Run parity tooling tests GREEN and commit**

```powershell
& $py -X utf8 -m pytest tests\test_cli_command_logging.py tests\test_listing_feed.py -q
& $py -X utf8 radar.py signal-read-model --refresh --compare --compare-listings --limit 200
git diff --check
git add cli/system.py radar.py tests/test_cli_command_logging.py tests/test_listing_feed.py
git commit -m "feat: verify all listings read model parity"
```

Expected command result: both comparisons report `status=ok` and zero differences. If not, stop and fix parity before cache/edge rollout.

## Task 5: Extend Anonymous Edge Cache, Prewarm, Benchmark, and Capacity Harnesses

**Files:**
- Modify: `services/public_prewarm.py`
- Modify: `config/public_cache_warm_routes.json`
- Modify: `deployment/ubuntu24/nginx-radar-bds.conf`
- Modify: `scripts/verify_public_cache.ps1`
- Modify: `scripts/benchmark_public_read_path.py`
- Modify: `scripts/load/radar_public_load.js`
- Modify: `tests/test_public_prewarm.py`
- Modify: `tests/test_benchmark_public_read_path.py`
- Modify: `tests/test_deployment_units.py`

- [ ] **Step 1: Write failing artifact-contract tests**

Extend `tests/test_deployment_units.py`:

```python
def test_nginx_public_cache_requires_no_session_and_app_opt_in():
    site = Path("deployment/ubuntu24/nginx-radar-bds.conf").read_text("utf-8")
    for route in (
        "= /",
        "= /api/signals",
        "= /api/listings",
        "= /api/counts",
        "= /api/dashboard",
    ):
        assert f"location {route}" in site


def test_public_cache_verifier_covers_all_listings():
    text = Path("scripts/verify_public_cache.ps1").read_text("utf-8")
    assert '"/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50"' in text


def test_k6_capacity_profile_exercises_all_listings():
    text = Path("scripts/load/radar_public_load.js").read_text("utf-8")
    assert "/api/listings?" in text
    assert "listings body shape is valid" in text
```

Extend prewarm and benchmark tests:

```python
def test_listings_is_an_allowlisted_prewarm_path():
    assert public_prewarm._validated_routes(
        [
            "/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50"
        ]
    )


def test_configured_prewarm_skips_listings_until_read_model_flags_are_ready(
    monkeypatch, tmp_path
):
    config = tmp_path / "routes.json"
    config.write_text(
        json.dumps(["/api/dashboard", "/api/listings?page=1&limit=50"]),
        encoding="utf-8",
    )
    captured = []
    monkeypatch.setenv("RADAR_LISTING_READ_MODEL_ENABLED", "0")
    monkeypatch.setenv("RADAR_SIGNAL_READ_MODEL_ENABLED", "1")
    monkeypatch.setattr(
        public_prewarm,
        "prewarm_public_routes",
        lambda base_url, routes: captured.extend(routes) or {},
    )

    public_prewarm.prewarm_configured_routes(config)

    assert captured == ["/api/dashboard"]


def test_default_benchmark_paths_include_all_listings():
    from scripts import benchmark_public_read_path as benchmark
    assert any(path.startswith("/api/listings?") for path in benchmark.DEFAULT_PATHS)
```

- [ ] **Step 2: Run artifact tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_public_prewarm.py tests\test_benchmark_public_read_path.py tests\test_deployment_units.py -q
```

Expected: FAIL because `/api/listings` is absent from the allowlist, Nginx exact locations, verifier, benchmark defaults, and k6 workload.

- [ ] **Step 3: Add bounded prewarm and Nginx exact-location coverage**

Add `"/api/listings"` to `ALLOWED_PATHS`. Add this single canonical route to `config/public_cache_warm_routes.json`:

```json
"/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50"
```

Filter only the configured listings warm route until both projection flags permit the fast path. This prevents the pre-enable publication step from launching the known 50-second legacy query:

```python
def _route_enabled_for_configured_prewarm(route: str) -> bool:
    if urlsplit(route).path != "/api/listings":
        return True
    listing_enabled = os.getenv(
        "RADAR_LISTING_READ_MODEL_ENABLED", "1"
    ).strip() != "0"
    signal_enabled = os.getenv(
        "RADAR_SIGNAL_READ_MODEL_ENABLED", "0"
    ).strip() == "1"
    return listing_enabled and signal_enabled
```

`prewarm_configured_routes()` must pass only routes accepted by this predicate to `prewarm_public_routes()`. Direct `prewarm_public_routes()` validation remains unchanged so operators can still diagnose an explicitly supplied public route.

Add to `deployment/ubuntu24/nginx-radar-bds.conf` beside the existing exact API blocks:

```nginx
location = /api/listings {
    include /etc/nginx/snippets/radar-bds-public-cache.inc;
}
```

Do not add a prefix or regex location; the exact location keeps unrelated APIs out of public edge storage.

- [ ] **Step 4: Extend cache verification and cold/warm benchmarking**

Add the same canonical listings route to `$ProbePaths` in `scripts/verify_public_cache.ps1`. The existing recursive sensitive-key assertion and cookie/Authorization probes must run unchanged against it.

Add to `DEFAULT_PATHS` in `scripts/benchmark_public_read_path.py`:

```python
"/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50",
```

- [ ] **Step 5: Exercise listings in controlled k6 traffic without increasing key cardinality**

For each `MIXED_CORPUS` item, derive a listings query from the same 50 bounded filter combinations, excluding signal-only `mos_min`:

```javascript
listings: canonicalQuery({
  load_run: RUN_ID,
  prop_type: variant.prop_type,
  source: variant.source,
  ward: [ward],
  date_range: '3m',
  limit: '50',
  page: '1',
  sort_by: 'date',
  sort_dir: 'desc',
}),
```

Return signals, counts, and listings from `mixedUrls()`. Generalize `requestPair()` to `requestBatch()` and require all three responses to reach HIT during setup. Add listings to `runDefault()` and check:

```javascript
'listings status is 200': (response) => response.status === 200,
'listings are edge classified': () => Boolean(listingsEdge),
'listings body shape is valid': (response) => /"listings"\s*:\s*\[/.test(String(response.body || '')),
'listings use public CDN cache': () => !REQUIRE_CDN || isPublicCdnStatus(listingsCdn),
```

Keep `MIXED_CORPUS.length === 50`; do not generate a cross product or per-VU cache-busting keys.

- [ ] **Step 6: Run artifact tests GREEN and commit**

```powershell
& $py -X utf8 -m pytest tests\test_public_prewarm.py tests\test_benchmark_public_read_path.py tests\test_deployment_units.py -q
node --check scripts\load\radar_public_load.js
git diff --check
git add services/public_prewarm.py config/public_cache_warm_routes.json deployment/ubuntu24/nginx-radar-bds.conf scripts/verify_public_cache.ps1 scripts/benchmark_public_read_path.py scripts/load/radar_public_load.js tests/test_public_prewarm.py tests/test_benchmark_public_read_path.py tests/test_deployment_units.py
git commit -m "ops: cover all listings in public cache checks"
```

## Task 6: Document the Contract and Run the Complete Local Gate

**Files:**
- Modify: `.env.example`
- Modify: `AGENTS.md`
- Modify: `docs/architecture.md`
- Modify: `docs/operations.md`
- Modify: `docs/dev_commands.md`
- Modify: `docs/superpowers/specs/2026-08-02-all-listings-performance-design.md` only if implementation evidence reveals an approved design correction

- [ ] **Step 1: Document the feature flag and readiness behavior**

Add to `.env.example` directly under the signal read-model flags:

```dotenv
# All-listings route over the shared card projection. Defaults enabled, but it
# stays on legacy SQL until the signal read model is enabled and the durable
# listings dataset version is > 0. Set to 0 for route-only rollback.
RADAR_LISTING_READ_MODEL_ENABLED=1
```

Update `AGENTS.md` and `docs/architecture.md` with these exact runtime facts:

- `signal_card_read_model` contains all stable public-base listing cards; `is_actionable` is the stricter signal-only subset, while `listing_is_signal` preserves only the legacy all-listings badge.
- `/api/listings` reads the projection only after both flags and positive `listings` readiness.
- `/api/listings` caches by `listings` version and keeps full ordered `imgs` arrays.
- `/api/signals`, `/api/counts`, `/api/dashboard`, and signal Maps remain governed by the `signals` version and signal predicate.

- [ ] **Step 2: Add exact operator commands, evidence fields, and rollback**

Document this pre-enable sequence in `docs/operations.md` and `docs/dev_commands.md`:

```bash
RADAR_LISTING_READ_MODEL_ENABLED=0
/opt/radar-bds/.venv/bin/python -X utf8 radar.py signal-read-model --refresh --compare --compare-listings --limit 200
/opt/radar-bds/.venv/bin/python -X utf8 -c 'from services.public_cache import get_current_dataset_versions; print(get_current_dataset_versions(("signals","listings","market")))'
```

Then document enabling `RADAR_LISTING_READ_MODEL_ENABLED=1`, restarting the service, running the configured prewarm once, measuring the canonical listings route, verifying Nginx/cache privacy, and rolling only this route back to `0`. Explicitly note that publication skips the listings prewarm while either read-model flag is disabled so it never warms the 50-second legacy path.

Record the required release evidence fields: commit SHA, service status, durable and Redis listings version, full-refresh row count/duration, parity difference count, VPS-local cold p95, public HIT p95, browser first-content time, cache headers, redaction checks, and rollback probe.

- [ ] **Step 3: Run focused tests, full tests, syntax checks, and diff hygiene**

```powershell
& $py -X utf8 -m pytest `
  tests\test_signal_read_model.py `
  tests\test_listing_feed.py `
  tests\test_market_data_performance.py `
  tests\test_public_cache_keys.py `
  tests\test_public_cache_headers.py `
  tests\test_public_prewarm.py `
  tests\test_source_policy.py `
  tests\test_drop_filter.py `
  tests\test_guest_visibility.py `
  tests\test_cli_command_logging.py `
  tests\test_benchmark_public_read_path.py `
  tests\test_deployment_units.py `
  tests\test_refactor_structure.py -q
& $py -X utf8 -m pytest -q
& $py -X utf8 -m py_compile app.py services\listing_feed.py services\signal_read_model.py services\public_cache_keys.py db\public_dataset_versions.py db\schema.py cli\system.py radar.py
node --check static\js\main\listings.js
node --check scripts\load\radar_public_load.js
git diff --check
git status --short
```

- [ ] **Step 4: Run the local parity and latency gate**

```powershell
& $py -X utf8 radar.py signal-read-model --refresh --compare --compare-listings --limit 200
& $py -X utf8 scripts\benchmark_public_read_path.py `
  --base-url http://127.0.0.1:5000 `
  --repeat 5 `
  --path "/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50"
```

Require zero parity differences. Record all five cold and warm samples; do not use one best sample as p95 evidence.

- [ ] **Step 5: Commit durable documentation**

```powershell
git add .env.example AGENTS.md docs/architecture.md docs/operations.md docs/dev_commands.md
git commit -m "docs: add all listings performance runbook"
```

## Task 7: Review, Release, and Verify Production Without a Partial-Data Window

**Files:**
- Review: every file committed in Tasks 1-6
- Update after verified release: `docs/operations.md`

- [ ] **Step 1: Run specification and code-quality review**

Use `superpowers:requesting-code-review`. Review against `docs/superpowers/specs/2026-08-02-all-listings-performance-design.md` and reject the release for any of these:

- request-time valuation CTE remains on the enabled read-model path;
- incomplete projection rows can become signals;
- any filter, sort, full image array, response field, or tier behavior differs without approval;
- application cache receives an unredacted payload;
- positive `listings` readiness is not required;
- Nginx can cache cookie, Authorization, admin, Set-Cookie, or non-opted-in responses;
- a failed refresh can publish a new version or partial row set.

- [ ] **Step 2: Rebase on current `origin/main` and rerun the full gate**

```powershell
git fetch origin
git rebase origin/main
& $py -X utf8 -m pytest -q
& $py -X utf8 radar.py signal-read-model --refresh --compare --compare-listings --limit 200
git diff --check origin/main...HEAD
git status --short
```

Resolve only files in this feature's scope. Do not overwrite or stage unrelated work.

- [ ] **Step 3: Push code with the production route disabled first**

Before deployment, ensure the VPS env has:

```bash
RADAR_LISTING_READ_MODEL_ENABLED=0
```

Then push and deploy through the repository's approved production script. Verify deployed SHA, `radar-bds.service=active`, Nginx configuration, and the legacy `/api/listings` response before refreshing.

- [ ] **Step 4: Backfill atomically and require zero production parity differences**

Run as the Radar runtime user:

```bash
/opt/radar-bds/.venv/bin/python -X utf8 radar.py signal-read-model --refresh --compare --compare-listings --limit 200
```

Require:

- full refresh status `ok`;
- expanded affected-row count is plausible against stable public-base listings;
- `signals` and `listings` both increment in PostgreSQL;
- Redis mirrors the same committed versions;
- signal and listing comparison statuses are `ok` with `difference_count=0`.

Stop before enablement if any condition fails.

- [ ] **Step 5: Enable only the all-listings path and measure origin before edge**

Set:

```bash
RADAR_LISTING_READ_MODEL_ENABLED=1
```

Restart `radar-bds.service`, then run the no-credential configured prewarm once:

```bash
sudo -u radar bash -lc 'set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 -c "from services.public_prewarm import prewarm_configured_routes; print(prewarm_configured_routes())"'
```

Measure at least five canonical first-page requests against `http://127.0.0.1:5000`, including an application-cache miss on a legitimate alternate bounded key such as page 2. Require cold p95 <= 500 ms and exact total/payload parity.

- [ ] **Step 6: Verify public cache, UI, and privacy**

Run:

```powershell
.\scripts\verify_public_cache.ps1 -BaseUrl "https://radarbds.vn" -RequireCdn
& $py -X utf8 scripts\benchmark_public_read_path.py `
  --base-url https://radarbds.vn `
  --repeat 5 `
  --path "/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50"
```

In the browser, verify desktop and mobile:

1. Open the homepage and select `Tin rao`.
2. Confirm one first-page request, skeleton replacement <= 1.5 s, 50 or fewer unique rows/cards, and correct total.
3. Apply source, ward, property, range, keyword, date, complete-only, drop, and each sort; confirm no duplicate infinite-scroll rows.
4. Open a listing modal and confirm all expected ordered images render.
5. Confirm no console error and no Guest/Free/VIP source URL/contact/phone leakage.
6. Confirm admin remains private and retains authorized source fields.

- [ ] **Step 7: Run capacity stages serially and stop at the first abort threshold**

First run `k6 inspect`. Then use the approved default `100 -> 500 -> 1000 -> 5000` and mixed `100 -> 500 -> 1000` sequence from `docs/dev_commands.md`, with one stable `RUN_ID` per stage and browser gzip enabled. Observe Nginx, Gunicorn, Redis, PostgreSQL sessions/active queries, CPU, memory, network, and 5xx simultaneously.

Do not advance after a failed latency, error-rate, host-health, or cache-HIT gate. A pass proves only the exact cacheable corpus and environment tested.

- [ ] **Step 8: Record evidence and validate route-only rollback**

Append the measured production evidence to `docs/operations.md`. Then validate the documented rollback without dropping data:

1. Set `RADAR_LISTING_READ_MODEL_ENABLED=0`.
2. Restart the application.
3. Confirm `/api/listings` returns the legacy contract and Săn Deal/counts/dashboard/signal Maps remain on the read model.
4. Restore the flag to `1` only after the rollback probe passes.

Commit and push the evidence-only documentation update after production verification.

## Final Self-Review Checklist

- [ ] Every requirement in the approved design maps to at least one implementation task and one verification gate.
- [ ] No task contains `TODO`, `TBD`, placeholder code, unbounded query input, or a request to invent behavior during implementation.
- [ ] Function names, flag names, dataset names, cache namespaces, CLI flags, and response fields are consistent across code, tests, docs, and commands.
- [ ] The plan never treats an HTTP 200, a local test pass, or a warm cache sample as production completion.
- [ ] The plan preserves unrelated work, existing database data, full image arrays, and tier redaction.
- [ ] The plan has a route-specific, data-preserving rollback that does not disable `Săn Deal`.
