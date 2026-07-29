# Listing Map Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a filter-parity map for every matching result in the `Săn Deal` and `Tin rao` tabs, launched by a fixed bottom-center `Xem trên Maps` button and backed by deterministic exact/road/ward locations.

**Architecture:** Store derived locations outside `listings`, resolve them from versioned offline OpenStreetMap registries, and expose grouped summary plus lazy group-item APIs. Load the Leaflet workspace only after the launcher is activated, preserve the dashboard state in place, and share listing/signal SQL scopes so the map cannot drift from the two feeds.

**Tech Stack:** PostgreSQL 18, Flask 3.1, Python 3.12, Jinja, vanilla JavaScript, Leaflet 1.9.4, OpenStreetMap/Esri tile layers, pytest 8.4, Node contract tests, Python Playwright.

## Global Constraints

- Implement the approved specification at `docs/superpowers/specs/2026-07-29-listing-maps-planning-layers-design.md`.
- Use Leaflet 1.9.4 with OpenStreetMap street tiles and Esri World Imagery; do not add Google Maps Platform, a Google API key, or billing.
- The launcher label is exactly `Xem trên Maps` and it is fixed at the bottom center only for active `signals` and `all` tabs.
- Desktop launcher offset is 28 CSS pixels; mobile offset is the bottom-navigation height plus 12 CSS pixels plus `env(safe-area-inset-bottom)`.
- The map represents every result matching the active filter snapshot, not only cards already loaded in the browser.
- Location precedence is exact source coordinate, then `(city, ward, road_name)`, then canonical ward center, then unmapped.
- Road and ward coordinates remain visibly approximate; never add deterministic or random coordinate jitter.
- Derived coordinates are stored only in `listing_map_locations`; do not write them into `listings`.
- `mode=signals` uses latest valuation, `actionable_signal_sql("v")`, and the displayed MOS threshold.
- `mode=all` uses the same visibility, date, completeness, source, ward, property, price, area, keyword, and drop filters as `/api/listings`.
- Guest/Free/VIP payloads never expose original URLs, source URLs, phone numbers, contact text, long descriptions, or full image arrays.
- `/api/dashboard`, `/api/signals`, and `/api/listings` keep their existing payload boundaries; map data goes only through the two new map endpoints.
- Map JavaScript, Leaflet, and map workspace CSS do not load before launcher activation.
- One summary request is allowed per open/filter snapshot; group items load only after selection.
- Default-filter budgets are warm p95 at most 1.0 second, cold response at most 2.5 seconds, and compressed summary at most 750 KB.
- Accessibility is a release gate: semantic names/status, keyboard-only operation,
  visible focus, focus trapping/restoration, reduced motion, and 44-pixel mobile
  targets must pass at both viewports.
- Analytics events are allowlisted and contain only coarse mode, precision,
  counts, layer IDs, and close/retry reasons; never send coordinates, listing
  IDs, keywords, labels, contact data, or raw error text.
- No external LLM calls are allowed in the resolver, backfill, map service, crawl, or reprocess.
- Plan 1 stops after a locally verified core implementation. Production push/deploy occurs only after the four planning artifacts in Plan 2 pass their release gate.

## Execution Preflight

The planning checkout was `ahead 3, behind 59` relative to `origin/main` on
2026-07-29. Before Task 1, use `superpowers:using-git-worktrees` to create an
isolated feature branch from freshly fetched `origin/main`. Bring the approved
specification commit `eb99634` and the commit containing both implementation
plans into that worktree with non-destructive cherry-picks. Do not rebase or
reset the user's current checkout.

Verify:

```powershell
git fetch origin
git status --short --branch
git log -1 --oneline origin/main
```

Expected: the implementation worktree is clean and based on the current
`origin/main`; the original checkout remains unchanged.

---

## File Map

| File | Responsibility |
|---|---|
| `services/market_data.py` | Public shared listing filters and actionable deal SQL used by feeds and map |
| `db/schema.py` | Idempotent `listing_map_locations` table and indexes |
| `config/listing_map.py` | Resolver version, bounds, registry paths, accepted precisions |
| `config/listing_map_location_sources.json` | Curated OSM element mapping for canonical wards and roads |
| `static/maps/listing-locations/manifest.json` | Source snapshot and mapping hashes |
| `static/maps/listing-locations/ward-centers.json` | Complete canonical ward-center registry |
| `static/maps/listing-locations/road-centers.json` | Curated road-center registry |
| `scripts/build_listing_location_registry.py` | Offline OSM snapshot validator and deterministic registry builder |
| `services/listing_location_resolver.py` | Pure normalization, signature, and exact/road/ward resolution |
| `db/listing_map_locations.py` | Candidate reads and batched derived-location upserts/deletes |
| `services/listing_location_backfill.py` | Idempotent backfill orchestration and statistics |
| `cli/map_locations.py` | Explicit `radar.py map-locations` operator command |
| `cleansing/reprocess.py` | Best-effort incremental location refresh after listing processing |
| `services/listing_map.py` | Grouped summary/items queries, compact shaping, and short-lived cache |
| `routes/market_api.py` | Thin route delegates for the two map endpoints |
| `app.py` | Request validation, tier/filter parsing, rate limits, and service calls |
| `auth/core.py` | In-memory guest rate-limit scope for read-only map requests |
| `templates/partials/listing_map_workspace.html` | Launcher and full-screen workspace semantics |
| `templates/index.html` | Partial include plus lazy asset configuration |
| `static/css/main/layout.css` | Initial launcher positioning and tab bottom clearance |
| `static/css/main/listing_map.css` | Lazy workspace, panel, marker, and responsive styling |
| `static/js/main/core.js` | Lazy launcher proxy and tab visibility synchronization |
| `static/js/main/listing_map.js` | Leaflet lifecycle, history/focus/scroll restoration, API requests, and rendering |
| `static/js/main/listings.js` | Expose Tin rao completeness state to the map query |
| `docs/dev_commands.md` | Local backfill, API smoke, and focused verification commands |

---

### Task 1: Shared feed and signal scopes

**Files:**
- Modify: `services/market_data.py` at `_build_filters`, `_deal_mos_signal_sql`, and `load_signals`
- Modify: `app.py` inside `api_listings`
- Create: `tests/test_listing_map_query_scope.py`
- Modify: `tests/test_market_data_trust.py`

**Interfaces:**
- Produces: `build_listing_filters(**filters: object) -> tuple[str, list]`;
  `filters` includes `require_complete: bool = False` and the named arguments
  already accepted by `_build_filters`.
- Produces: `build_deal_sql(mos_min: float) -> DealSql`.
- `DealSql` fields are `actual_expr`, `fair_expr`, `mos_expr`, and `condition`.
- Consumes: `LATEST_VALUATION_CTE`, `LATEST_SHADOW_VALUATION_CTE`, and `actionable_signal_sql("v")`.

- [ ] **Step 1: Capture the current feed timing and default result IDs**

Start the local app with the documented Python 3.12 interpreter, then run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$base = "http://127.0.0.1:5000"
1..5 | ForEach-Object {
  $elapsed = Measure-Command {
    Invoke-RestMethod "$base/api/signals?page=1&limit=100&include_total=1" | Out-Null
  }
  [Math]::Round($elapsed.TotalMilliseconds, 1)
}
Invoke-RestMethod "$base/api/signals?page=1&limit=100&include_total=1" |
  ConvertTo-Json -Depth 4 |
  Set-Content -LiteralPath ".local\listing-map-signals-baseline.json" -Encoding UTF8
```

Expected: five timing samples and an ignored baseline file. Do not treat a DB
connection failure as a passing baseline.

- [ ] **Step 2: Write failing shared-scope tests**

Add assertions that exercise real SQL builders:

```python
from services.market_data import build_deal_sql, build_listing_filters


def test_deal_scope_requires_actionable_latest_valuation_and_display_mos():
    deal = build_deal_sql(15)
    assert "source_quality_recheck" in deal.condition
    assert "low_segment_confidence" in deal.condition
    assert "COALESCE(v.is_signal,0)=1" in deal.condition
    assert ">= 15.0" in deal.condition


def test_complete_listing_scope_reuses_all_filters():
    sql, params = build_listing_filters(
        sources=["facebook"],
        wards=["Phú Lợi"],
        prop_types=["dat_nen"],
        keyword="ĐX 43",
        date_range="1m",
        require_complete=True,
        prefix="l.",
    )
    assert "l.source IN (?)" in sql
    assert "l.ward IN (?)" in sql
    assert "l.property_type IN (?)" in sql
    assert "l.price_ty IS NOT NULL AND l.price_ty > 0" in sql
    assert params[:3] == ["Phú Lợi", "facebook", "dat_nen"]
```

Extend the trust test with a fatal quality flag fixture and a
`low_segment_confidence` fixture. Assert fatal is absent from `load_signals`
while low-confidence remains visible.

- [ ] **Step 3: Run the tests and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_query_scope.py tests\test_market_data_trust.py -q
```

Expected: import failures for `build_deal_sql` and `build_listing_filters`, or
the fatal-quality parity assertion fails against the current query.

- [ ] **Step 4: Implement the public scope builders**

Add this immutable contract and rename `_build_filters` without changing its
existing parameter order:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class DealSql:
    actual_expr: str
    fair_expr: str
    mos_expr: str
    condition: str


def build_deal_sql(mos_min: float) -> DealSql:
    actual = "COALESCE(v.actual_ppm2, sv.actual_ppm2, l.price_per_m2)"
    fair = _display_fair_sql("v", "sv")
    mos = _display_mos_sql("v", "sv", actual)
    minimum = float(mos_min if mos_min is not None else 10)
    condition = (
        f"({actionable_signal_sql('v')}) AND "
        f"({_deal_mos_signal_sql(mos, minimum)})"
    )
    return DealSql(actual, fair, mos, condition)
```

Rename `_build_filters` to `build_listing_filters`, add
`require_complete=False`, and append these clauses when it is true:

```python
where_parts.extend([
    f"NULLIF(TRIM(COALESCE({col('ward')},'')), '') IS NOT NULL",
    f"{col('price_ty')} IS NOT NULL AND {col('price_ty')} > 0",
    f"{col('area_m2')} IS NOT NULL AND {col('area_m2')} > 0",
])
```

Replace internal `_build_filters` calls and the duplicated `api_listings`
filter construction with the public builder. Keep sorting, pagination, image
loading, and response shape unchanged.

- [ ] **Step 5: Apply the shared actionable scope to `load_signals`**

Use one `DealSql` instance:

```python
deal = build_deal_sql(mos_min)
actual_expr = deal.actual_expr
display_fair_expr = deal.fair_expr
display_mos_expr = deal.mos_expr
signal_condition = deal.condition
```

The SQL `WHERE` must contain both `signal_condition` and the existing complete
signal-data predicate. Do not use shadow valuation actionability as an
authorization substitute for the latest canonical valuation.

- [ ] **Step 6: Run focused tests and verify GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_query_scope.py tests\test_market_data_trust.py tests\test_market_data_performance.py -q
```

Expected: shared-scope, trust, and hot-path tests pass with no `/api/signals`
payload expansion.

- [ ] **Step 7: Commit the scope change**

```powershell
git add services/market_data.py app.py tests/test_listing_map_query_scope.py tests/test_market_data_trust.py
git diff --cached --check
git commit -m "refactor: share listing map query scopes"
```

---

### Task 2: Derived-location schema

**Files:**
- Modify: `db/schema.py` in `SCHEMA_SQL`, `init_schema`, and `_run_migrations`
- Create: `tests/test_listing_map_schema.py`

**Interfaces:**
- Produces: table `listing_map_locations`.
- Produces: `_migrate_listing_map_locations(conn) -> None`.
- The API field `precision` maps from database column `location_precision`.

- [ ] **Step 1: Write failing schema contract tests**

Use a recording fake connection and assert the executed DDL includes:

```python
required_fragments = [
    "listing_id BIGINT PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE",
    "lat DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90)",
    "lng DOUBLE PRECISION NOT NULL CHECK (lng BETWEEN -180 AND 180)",
    "location_precision TEXT NOT NULL",
    "location_key TEXT NOT NULL",
    "resolver_version TEXT NOT NULL",
    "listing_location_signature TEXT NOT NULL",
    "idx_listing_map_locations_precision",
    "idx_listing_map_locations_point",
    "idx_listing_map_locations_key",
]
```

Test that calling `_migrate_listing_map_locations` twice is idempotent and does
not issue `DROP`, `TRUNCATE`, or an update to `listings`.

- [ ] **Step 2: Run the schema test and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_schema.py -q
```

Expected: import failure because `_migrate_listing_map_locations` does not
exist.

- [ ] **Step 3: Add the table and migration helper**

Add the exact table contract:

```sql
CREATE TABLE IF NOT EXISTS listing_map_locations (
    listing_id BIGINT PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
    lat DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lng DOUBLE PRECISION NOT NULL CHECK (lng BETWEEN -180 AND 180),
    location_precision TEXT NOT NULL
        CHECK (location_precision IN ('exact', 'road', 'ward')),
    location_key TEXT NOT NULL,
    location_label TEXT NOT NULL,
    source TEXT NOT NULL,
    resolver_version TEXT NOT NULL,
    listing_location_signature TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_listing_map_locations_precision
    ON listing_map_locations(location_precision);
CREATE INDEX IF NOT EXISTS idx_listing_map_locations_point
    ON listing_map_locations(lat, lng);
CREATE INDEX IF NOT EXISTS idx_listing_map_locations_key
    ON listing_map_locations(location_key);
```

Call `_migrate_listing_map_locations(conn)` from both the normal migration
path and the limited-DDL recovery path. A missing derived table is not accepted
as a successful schema initialization.

- [ ] **Step 4: Run schema verification and verify GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_schema.py tests\test_schema_init_permissions.py -q
& $py -X utf8 -m py_compile db\schema.py
```

Expected: both schema test files pass.

- [ ] **Step 5: Commit the schema**

```powershell
git add db/schema.py tests/test_listing_map_schema.py
git diff --cached --check
git commit -m "feat: add derived listing map locations"
```

---

### Task 3: Offline OSM registries and pure resolver

**Files:**
- Create: `config/listing_map.py`
- Create: `config/listing_map_overpass.ql`
- Create: `config/listing_map_location_sources.json`
- Create: `scripts/build_listing_location_registry.py`
- Create: `services/listing_location_resolver.py`
- Create: `static/maps/listing-locations/manifest.json`
- Create: `static/maps/listing-locations/ward-centers.json`
- Create: `static/maps/listing-locations/road-centers.json`
- Create: `tests/fixtures/listing-map/osm-roads.json`
- Create: `tests/fixtures/listing-map/location-sources.json`
- Create: `tests/test_listing_location_registry.py`
- Create: `tests/test_listing_location_resolver.py`

**Interfaces:**
- Produces: `LISTING_MAP_RESOLVER_VERSION`, `LISTING_MAP_BOUNDS`, and registry paths.
- Produces: `LocationRegistry(resolver_version, roads, wards)`.
- Produces: `normalize_location_token(value: str) -> str`.
- Produces: `listing_location_signature(listing: Mapping) -> str`.
- Produces: `resolve_listing_location(listing: Mapping, registry: LocationRegistry) -> ResolvedLocation | None`.
- Produces: `build_location_registries(osm_payload, sources, output_dir) -> tuple[Path, Path, Path]`.

- [ ] **Step 1: Write failing resolver tests**

Use in-memory registries and explicit fixture points:

```python
road_registry = {
    ("THỦ DẦU MỘT", "phu loi", "dx 43"): {
        "lat": 10.981,
        "lng": 106.689,
        "label": "Theo tên đường ĐX 43, Phú Lợi",
        "source": "OpenStreetMap",
    }
}
ward_registry = {
    ("THỦ DẦU MỘT", "phu loi"): {
        "lat": 10.984,
        "lng": 106.684,
        "label": "Theo trung tâm Phú Lợi",
        "source": "OpenStreetMap",
    }
}
```

Assert:

- validated `source_lat/source_lng` wins and yields `exact:<listing_id>`;
- `ĐX-43`, `ĐX 43`, and `đx.43` resolve to the same road key;
- the same road text in a different ward does not match;
- an unknown road falls back to `ward:thu-dau-mot:phu-loi`;
- an unknown ward returns `None`;
- two identical inputs produce identical coordinates and signature;
- neither the resolver nor key builder imports `random`.

- [ ] **Step 2: Write failing registry-builder tests**

The test OSM fixture contains named highway ways and named place nodes with
pinned IDs. The curated source fixture maps exact OSM IDs:

```json
{
  "resolver_version": "osm-test-v1",
  "wards": [
    {
      "city": "THỦ DẦU MỘT",
      "ward": "Phú Lợi",
      "osm_type": "node",
      "osm_id": 1001
    }
  ],
  "roads": [
    {
      "city": "THỦ DẦU MỘT",
      "ward": "Phú Lợi",
      "road_name": "ĐX 43",
      "osm_way_ids": [2001, 2002]
    }
  ]
}
```

Assert missing IDs, duplicate normalized keys, out-of-bounds geometry,
non-highway ways, missing canonical wards, and partial writes all raise
`ValueError`. Successful output is byte-stable across two runs and includes
SHA-256 hashes for the OSM snapshot and curated mapping.

- [ ] **Step 3: Run both test files and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_location_registry.py tests\test_listing_location_resolver.py -q
```

Expected: imports fail because builder and resolver modules do not exist.

- [ ] **Step 4: Implement the resolver**

Use Unicode NFD folding, lowercase, punctuation-to-space replacement, and
collapsed whitespace. Preserve numeric road codes. Define:

```python
@dataclass(frozen=True)
class LocationRegistry:
    resolver_version: str
    roads: Mapping[tuple[str, str, str], Mapping[str, object]]
    wards: Mapping[tuple[str, str], Mapping[str, object]]


@dataclass(frozen=True)
class ResolvedLocation:
    listing_id: int
    lat: float
    lng: float
    precision: str
    location_key: str
    location_label: str
    source: str
    resolver_version: str
    signature: str
```

Validate exact coordinates against both world bounds and
`LISTING_MAP_BOUNDS`. Build signatures from validated source coordinates when
present; otherwise hash normalized `city|ward|road_name` with SHA-256.

- [ ] **Step 5: Implement the deterministic builder**

The committed Overpass query is:

```text
[out:json][timeout:180];
(
  way["highway"]["name"](10.75,106.25,11.65,107.10);
  nwr["place"]["name"](10.75,106.25,11.65,107.10);
);
out tags center geom;
```

The builder reads an already-downloaded OSM JSON snapshot, never calls a
geocoder, validates every curated OSM ID, computes a length-weighted center for
multi-way roads, and writes compact UTF-8 JSON through temporary files followed
by atomic replacement only after all validation passes.

- [ ] **Step 6: Run fixture tests and verify GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_listing_location_registry.py tests\test_listing_location_resolver.py -q
```

Expected: all precedence, normalization, validation, and determinism tests pass.

- [ ] **Step 7: Curate and generate production registries**

Download the offline snapshot without printing credentials:

```powershell
New-Item -ItemType Directory -Force -Path ".local\listing-map" | Out-Null
$query = Get-Content -LiteralPath "config\listing_map_overpass.ql" -Raw -Encoding UTF8
Invoke-WebRequest `
  -Method Post `
  -Uri "https://overpass-api.de/api/interpreter" `
  -Body @{ data = $query } `
  -OutFile ".local\listing-map\osm-roads.json"
& $py -X utf8 scripts\build_listing_location_registry.py `
  --osm-json ".local\listing-map\osm-roads.json" `
  --sources "config\listing_map_location_sources.json" `
  --output-dir "static\maps\listing-locations"
```

Curate `config/listing_map_location_sources.json` so every canonical ward in
`services.market_data.CITY_MAP` has one verified ward source. Add road mappings
for every distinct normalized `road_name` that can be matched unambiguously in
the offline snapshot; unmatched roads intentionally use ward fallback. Record
ambiguous or rejected road names in the manifest counts, not as invented
coordinates.

- [ ] **Step 8: Validate real output**

```powershell
& $py -X utf8 -m json.tool static\maps\listing-locations\manifest.json > $null
& $py -X utf8 -m json.tool static\maps\listing-locations\ward-centers.json > $null
& $py -X utf8 -m json.tool static\maps\listing-locations\road-centers.json > $null
& $py -X utf8 -m pytest tests\test_listing_location_registry.py tests\test_listing_location_resolver.py -q
```

Expected: all `CITY_MAP` wards exist exactly once, all points are inside former
Bình Dương bounds, hashes match, and output regeneration is byte-identical.

- [ ] **Step 9: Commit registry and resolver**

```powershell
git add config/listing_map.py config/listing_map_overpass.ql config/listing_map_location_sources.json scripts/build_listing_location_registry.py services/listing_location_resolver.py static/maps/listing-locations tests/fixtures/listing-map tests/test_listing_location_registry.py tests/test_listing_location_resolver.py
git diff --cached --check
git commit -m "feat: resolve listing map locations offline"
```

---

### Task 4: Idempotent backfill and reprocess integration

**Files:**
- Create: `db/listing_map_locations.py`
- Create: `services/listing_location_backfill.py`
- Create: `cli/map_locations.py`
- Modify: `radar.py`
- Modify: `cleansing/reprocess.py` inside `_run_full_reprocess`
- Modify: `docs/dev_commands.md`
- Create: `tests/test_listing_location_backfill.py`
- Modify: `tests/test_reprocess_review_hidden.py`

**Interfaces:**
- Produces: `iter_location_candidates(listing_ids: Sequence[int] | None) -> list[dict]`.
- Produces: `upsert_listing_map_locations(rows: Sequence[ResolvedLocation]) -> int`.
- Produces: `delete_stale_listing_map_locations(active_listing_ids: Sequence[int]) -> int`.
- Produces: `backfill_listing_locations(listing_ids=None, *, full=False, dry_run=False) -> dict[str, int]`.
- Produces: CLI `radar.py map-locations [--full] [--dry-run]`.

- [ ] **Step 1: Write failing backfill tests**

Use fake repository functions and assert:

```python
assert stats == {
    "scanned": 4,
    "exact": 1,
    "road": 1,
    "ward": 1,
    "unmapped": 1,
    "inserted": 3,
    "updated": 0,
    "unchanged": 0,
    "deleted": 0,
}
```

Cover unchanged signature/version skips, changed road updates, missing ward
deletes an old derived row, dry-run performs no writes, and a full run prunes
rows whose listing no longer exists.

- [ ] **Step 2: Run the backfill test and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_location_backfill.py -q
```

Expected: import failures for repository and backfill modules.

- [ ] **Step 3: Implement the repository and service**

Candidate rows select only location inputs:

```sql
SELECT l.id,
       l.ward,
       l.road_name,
       NULL::DOUBLE PRECISION AS source_lat,
       NULL::DOUBLE PRECISION AS source_lng
FROM listings l
```

Derive `city` with `get_city_for_ward`. Upsert changed rows in one transaction:

```sql
INSERT INTO listing_map_locations (
    listing_id, lat, lng, location_precision, location_key, location_label,
    source, resolver_version, listing_location_signature, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NOW())
ON CONFLICT (listing_id) DO UPDATE SET
    lat=EXCLUDED.lat,
    lng=EXCLUDED.lng,
    location_precision=EXCLUDED.location_precision,
    location_key=EXCLUDED.location_key,
    location_label=EXCLUDED.location_label,
    source=EXCLUDED.source,
    resolver_version=EXCLUDED.resolver_version,
    listing_location_signature=EXCLUDED.listing_location_signature,
    updated_at=NOW()
```

Do not rewrite unchanged rows. Delete an existing derived row when a listing
becomes unmapped.

- [ ] **Step 4: Add CLI and reprocess integration**

Add the parser:

```python
p_map = sub.add_parser(
    "map-locations",
    help="Backfill deterministic listing map locations",
)
p_map.add_argument("--full", action="store_true")
p_map.add_argument("--dry-run", action="store_true")
```

After listing reprocessing, call incremental backfill with `processed_ids`.
For a full reprocess, call a full location backfill. A location-backfill
exception is logged and returned as `{"status": "error"}` without discarding
successful listing/valuation work; the explicit CLI still exits nonzero on the
same error.

- [ ] **Step 5: Add focused operator documentation**

Document:

```powershell
& $py -X utf8 radar.py map-locations --dry-run
& $py -X utf8 radar.py map-locations --full
```

Include the expected exact/road/ward/unmapped/inserted/updated/unchanged/deleted
counts and state that the command never updates `listings`.

- [ ] **Step 6: Run backfill and reprocess tests**

```powershell
& $py -X utf8 -m pytest tests\test_listing_location_backfill.py tests\test_reprocess_review_hidden.py -q
& $py -X utf8 -m py_compile db\listing_map_locations.py services\listing_location_backfill.py cli\map_locations.py radar.py cleansing\reprocess.py
```

Expected: tests pass and the failure-isolation behavior is explicit.

- [ ] **Step 7: Run a local dry-run, then write the local derived rows**

```powershell
& $py -X utf8 radar.py map-locations --dry-run
& $py -X utf8 radar.py map-locations --full
```

Expected: the write run reports a nonzero scanned count, invariants hold, and a
second run reports only unchanged rows.

- [ ] **Step 8: Commit backfill integration**

```powershell
git add db/listing_map_locations.py services/listing_location_backfill.py cli/map_locations.py radar.py cleansing/reprocess.py docs/dev_commands.md tests/test_listing_location_backfill.py tests/test_reprocess_review_hidden.py
git diff --cached --check
git commit -m "feat: backfill listing map locations"
```

---

### Task 5: Grouped map APIs, parity, cache, and redaction

**Files:**
- Create: `services/listing_map.py`
- Modify: `services/listing_location_backfill.py`
- Modify: `app.py` near `api_signals` and `api_listings`
- Modify: `routes/market_api.py`
- Modify: `auth/core.py` at `MEMORY_RATE_LIMIT_SCOPES`
- Create: `tests/test_listing_map_service.py`
- Create: `tests/test_listing_map_api.py`
- Modify: `tests/test_market_data_performance.py`
- Modify: `docs/dev_commands.md`

**Interfaces:**
- Produces: `load_listing_map_summary(*, mode: str, tier: str, filters: MapFilters) -> dict`.
- Produces: `load_listing_map_items(*, mode: str, tier: str, filters: MapFilters, location_key: str, page: int, limit: int) -> dict`.
- Produces: `clear_listing_map_cache() -> None`.
- Produces: `get_listing_map_data_version(conn) -> str`.
- Produces: `GET /api/map-listings`.
- Produces: `GET /api/map-listing-items`.

- [ ] **Step 1: Write failing service tests**

Use a recording fake PostgreSQL connection. Assert the summary:

```python
summary = payload["summary"]
assert summary["mapped"] + summary["unmapped_count"] == summary["total"]
assert (
    summary["exact_count"]
    + summary["road_count"]
    + summary["ward_count"]
    == summary["mapped"]
)
assert sum(group["listing_count"] for group in payload["locations"]) == summary["mapped"]
```

Assert the summary query selects no description, URL, contact, seller, or image
array; exact points have one listing per location key; road/ward groups aggregate
counts and best MOS; and cache keys include tier, mode, normalized filters, and
resolver version. Freeze the clock and data-version loader to prove that two
requests with the same version hit the query once, while a newer listing,
valuation, review-hiding, or derived-location timestamp forces a query miss
even before the 60-second TTL expires.

- [ ] **Step 2: Write failing endpoint tests**

Patch service loaders and assert:

- `mode=signals` and `mode=all` return 200;
- missing/unknown mode returns 400;
- invalid location keys, page, and limit return 400;
- group limit is bounded to 50;
- non-admin source selection remains Facebook-only;
- `complete=1` reaches only `mode=all`;
- every supported filter reaches `MapFilters`;
- two identical guest requests hit the loader once;
- changing only the mocked database data version misses the service cache;
- backfill cache invalidation forces the next loader call;
- response text for guest/free/vip contains no `"url"`, `"phone"`,
  `"contact_phone"`, or `"description"`.

- [ ] **Step 3: Run service/API tests and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_service.py tests\test_listing_map_api.py -q
```

Expected: module and route imports fail.

- [ ] **Step 4: Implement typed filters and compact queries**

Define:

```python
@dataclass(frozen=True)
class MapFilters:
    city: str
    wards: tuple[str, ...]
    sources: tuple[str, ...]
    prop_types: tuple[str, ...]
    only_drops: bool
    mos_min: int
    area_min: float
    area_max: float
    price_min: float
    price_max: float
    area_ranges: tuple[tuple[float, float], ...]
    price_ranges: tuple[tuple[float, float], ...]
    keyword: str
    date_range: str
    complete_only: bool
```

Build the filtered listing CTE from Task 1. Left join
`listing_map_locations` so unmapped rows remain in totals. Group mapped rows by
`location_key`, coordinates, precision, and label. Return only compact
aggregates.

The group-item query reapplies the complete filter CTE and then adds
`ml.location_key = ?`; it does not authorize from `location_key` alone.

- [ ] **Step 5: Implement cache and endpoint handlers**

Use a 60-second, 128-entry in-process cache with defensive deep copies. Include
`get_listing_map_data_version(conn)` in the key; it returns the greatest
timestamp across visible listing updates/review hiding, latest valuation
computation, shadow valuation computation, and derived-location updates. This
makes a different crawl, reprocess, QC process, or backfill invalidate the web
process cache without shared memory.

After a successful local backfill commit, also call
`clear_listing_map_cache()` so the current process drops old values
immediately. Add `listing_map` to `MEMORY_RATE_LIMIT_SCOPES` and decorate both
endpoints:

```python
@rate_limit(
    "listing_map",
    limits={"guest": 300, "free": 600, "vip": None, "admin": None},
)
def api_map_listings():
    return jsonify(load_listing_map_summary(
        mode=mode,
        tier=current_tier(),
        filters=filters,
    ))
```

Use the same limits for items. Validate `location_key` with a maximum length of
240 and the allowlist pattern `^(exact|road|ward):[a-z0-9:-]+$`.

- [ ] **Step 6: Add parity tests against feed scopes**

For isolated fixture rows, compare the set/count represented by the summary
with:

- `load_signals` paginated until its reported total for `signals`;
- `/api/listings?limit=100` for `all`;
- both modes under ward, source, property type, area, price, date, keyword,
  drop, MOS, and completeness filters.

Include fatal quality and `low_segment_confidence` fixtures so actionability
cannot drift.

- [ ] **Step 7: Run focused tests and query-plan checks**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_service.py tests\test_listing_map_api.py tests\test_market_data_performance.py tests\test_market_data_trust.py -q
& $py -X utf8 -m py_compile services\listing_map.py app.py routes\market_api.py auth\core.py
```

Run `EXPLAIN (ANALYZE, BUFFERS)` for the real default summary query through a
small read-only script or `psql`. Confirm no per-row connection opens and no
sequential scan is introduced on `listing_map_locations`.

- [ ] **Step 8: Add API smoke commands**

Document and run:

```powershell
Invoke-RestMethod "http://127.0.0.1:5000/api/map-listings?mode=signals"
Invoke-RestMethod "http://127.0.0.1:5000/api/map-listings?mode=all&complete=1"
Invoke-RestMethod "http://127.0.0.1:5000/api/map-listing-items?mode=signals&location_key=ward:thu-dau-mot:phu-loi&page=1&limit=20"
```

Expected: valid invariants, no sensitive fields, and bounded items.

- [ ] **Step 9: Commit the API**

```powershell
git add services/listing_map.py services/listing_location_backfill.py app.py routes/market_api.py auth/core.py tests/test_listing_map_service.py tests/test_listing_map_api.py tests/test_market_data_performance.py docs/dev_commands.md
git diff --cached --check
git commit -m "feat: add filtered listing map APIs"
```

---

### Task 6: Fixed bottom-center launcher and lazy shell

**Files:**
- Create: `templates/partials/listing_map_workspace.html`
- Modify: `templates/index.html` in lazy asset configuration and before modal markup
- Modify: `static/js/main/core.js` at lazy proxies and `switchTab`
- Modify: `static/js/main/listings.js` at completeness toggle
- Modify: `static/css/main/layout.css`
- Create: `tests/test_listing_map_ui.py`

**Interfaces:**
- Produces: `window.openListingMap()` lazy proxy.
- Produces: `window.getListingMapFilterSnapshot() -> {mode, query}`.
- Produces: `syncListingMapLauncher(tabId) -> None`.
- DOM IDs: `listingMapLauncher`, `listingMapWorkspace`,
  `listingMapCanvas`, `listingMapPanel`, `listingMapStatus`.

- [ ] **Step 1: Write failing server-rendered UI tests**

Assert dashboard HTML contains:

```html
<button id="listingMapLauncher" type="button" aria-controls="listingMapWorkspace">
```

Also assert:

- visible text `Xem trên Maps`;
- an inline map-pin SVG marked `aria-hidden="true"`;
- workspace `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, and
  `aria-describedby`;
- close button with an accessible name and status region with
  `role="status"`, `aria-live="polite"`, and toggled `aria-busy`;
- close button, live status, canvas, side panel, and mobile sheet hooks;
- no eager Leaflet `<script>` or `<link>` tag;
- lazy `listingMap` script/style URLs exist in asset config;
- saved-listings route does not render the launcher.

- [ ] **Step 2: Run UI tests and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_ui.py -q
```

Expected: launcher and workspace assertions fail.

- [ ] **Step 3: Add semantic partial and lazy config**

Render the partial only when `saved_page` is false. Add:

```javascript
window.RADAR_ASSETS.listingMap =
  "{{ url_for('static', filename='js/main/listing_map.js') }}?v=listing-map-core-20260729";
window.RADAR_STYLES.listingMap =
  "{{ url_for('static', filename='css/main/listing_map.css') }}?v=listing-map-core-20260729";
window.RADAR_MAP_VENDOR = {
  leafletScript: {
    url: "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
    integrity: "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
  },
  leafletStyle: {
    url: "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
    integrity: "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
  }
};
```

- [ ] **Step 4: Implement launcher proxy and tab synchronization**

Add:

```javascript
function syncListingMapLauncher(tabId = activeTabId()) {
  const launcher = document.getElementById('listingMapLauncher');
  if (!launcher) return;
  const supported = tabId === 'signals' || tabId === 'all';
  launcher.hidden = !supported;
  document.body.classList.toggle('listing-map-launcher-visible', supported);
}

async function lazyOpenListingMap() {
  await ensureDashboardStyle('listingMap');
  await ensureDashboardScript('listingMap');
  return window.RadarListingMap.open(getListingMapFilterSnapshot());
}

window.openListingMap = lazyOpenListingMap;
```

Call `syncListingMapLauncher` on initial boot and after every successful
`switchTab`.

`getListingMapFilterSnapshot` uses `currentFilters`; for `mode=all`, append
`complete=1` when `completeListingsOnly` is true. Export that state from
`listings.js` through `window.RadarListingsState.isCompleteOnly()`.

- [ ] **Step 5: Style the fixed launcher and clearance**

In initial `layout.css`, use:

```css
.listing-map-launcher {
  position: fixed;
  left: 50%;
  bottom: 28px;
  z-index: 70;
  transform: translateX(-50%);
  min-height: 48px;
}

@media (max-width: 1024px) {
  .listing-map-launcher {
    bottom: calc(82px + env(safe-area-inset-bottom));
  }
}
```

Hide it when `sidebar-open`, `tools-sheet-open`, `signal-modal-open`,
`chat-open`, or `listing-map-open` is on `body`. Add enough bottom padding to
`#tab-signals`, `.listings-grid-shell`, and `.table-scroll` so the final result
and sentinel can scroll clear of the launcher.

- [ ] **Step 6: Run UI and syntax tests**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_ui.py -q
node --check static\js\main\core.js
node --check static\js\main\listings.js
```

Expected: semantic, lazy-load, supported-tab, and saved-page assertions pass.

- [ ] **Step 7: Commit the launcher shell**

```powershell
git add templates/partials/listing_map_workspace.html templates/index.html static/js/main/core.js static/js/main/listings.js static/css/main/layout.css tests/test_listing_map_ui.py
git diff --cached --check
git commit -m "feat: add bottom center map launcher"
```

---

### Task 7: Full-screen Leaflet workspace and lazy group panel

**Files:**
- Create: `static/js/main/listing_map.js`
- Create: `static/css/main/listing_map.css`
- Create: `tests/test_listing_map_js.py`
- Modify: `tests/test_listing_map_ui.py`

**Interfaces:**
- Produces browser/CommonJS helpers: `normalizeMode`, `buildSummaryUrl`,
  `buildItemsUrl`, `normalizeBaseLayer`, `mapBaseLayers`,
  `safeTrackingContext`, and `precisionCopy`.
- Produces browser API: `window.RadarListingMap.open(snapshot)` and
  `window.RadarListingMap.close(options)`.
- Consumes the two map API contracts and the fixed vendor config from Task 6.

- [ ] **Step 1: Write failing Node contract tests**

Use the existing Node/CommonJS subprocess pattern from
`tests/test_binh_duong_map_js.py`. Assert:

```javascript
mapApi.normalizeMode("signals") === "signals"
mapApi.normalizeMode("all") === "all"
mapApi.normalizeMode("market") === null
mapApi.normalizeBaseLayer("satellite") === "satellite"
mapApi.normalizeBaseLayer("broken") === "street"
mapApi.precisionCopy("road").badge === "Theo tên đường"
mapApi.precisionCopy("ward").badge === "Theo trung tâm phường"
```

Verify the summary URL carries the exact filter query plus mode, item URL
repeats the snapshot and adds a validated location key/page/limit, and safe
tracking context contains only mode, precision, listing count, and layer IDs.

- [ ] **Step 2: Run JS tests and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_js.py -q
```

Expected: `static/js/main/listing_map.js` is missing.

- [ ] **Step 3: Implement the UMD module and Leaflet loader**

Use the same CommonJS/browser wrapper as `static/js/binh_duong_map.js`.
`loadLeaflet()` creates one stylesheet and one script using the fixed URL,
integrity, and `crossOrigin="anonymous"` values. Concurrent calls share one
promise; load failure renders a retry state and leaves list tabs usable.

Base-layer definitions are:

```javascript
{
  street: {
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    maxZoom: 19
  },
  satellite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    maxZoom: 19
  }
}
```

Include complete OpenStreetMap and Esri attribution strings.

- [ ] **Step 4: Implement open, close, history, and restoration**

On open:

- record active tab, its scroll container and scrollTop, focused element, and
  filter query;
- set `body.listing-map-open`;
- unhide workspace and move focus to the close button;
- push one same-URL history state `{radarListingMap: true}` unless opened from
  `popstate`;
- lazy-load Leaflet and request the summary with a dedicated AbortController.

On close:

- abort summary and item requests;
- remove map layers and call `map.remove()`;
- hide workspace and clear `body.listing-map-open`;
- restore the tab, scrollTop, and prior focus;
- consume the synthetic history entry only for explicit close.

`popstate` closes an open map without pushing or navigating again. Escape closes
the map. Tab and Shift+Tab remain inside the workspace while open.

- [ ] **Step 5: Render honest groups and lazy items**

Use one `L.circleMarker` per server group:

- exact: solid green ring and exact-location copy;
- road: indigo grouped marker with listing count;
- ward: amber grouped marker with listing count.

Do not alter coordinates client-side. Fit bounds only across returned groups;
when none are mapped, keep the supported-area extent and show
`unmapped_count`.

Selecting a group requests `/api/map-listing-items` with the frozen filter
snapshot. Desktop uses the side panel; mobile uses the same content in a bottom
sheet. Item cards include title, price, area, property type, ward/road,
thumbnail, date, and MOS for signals. Selecting a card calls the existing lazy
listing/modal function; no full description is rendered in the panel.

- [ ] **Step 6: Implement stale-request and error behavior**

Maintain monotonically increasing summary/item sequence IDs. An aborted or older
response cannot mutate map state. Provide:

- summary retry without closing the map;
- item retry scoped to the selected group;
- base-layer fallback while preserving markers;
- visible mapped/unmapped and precision counts;
- no uncaught promise rejection for `AbortError`.

Allowlist and emit only:

- `listing_map_opened`;
- `listing_map_closed`;
- `listing_map_base_layer_changed`;
- `listing_map_group_selected`;
- `listing_map_retry`.

Tracking payloads contain mode, precision, mapped/unmapped counts, group count,
base-layer ID, and close reason only. They never contain coordinates, listing
IDs, raw keywords, location labels, or contact data.

- [ ] **Step 7: Style desktop/mobile workspace**

Desktop: fixed inset workspace, 360-pixel side panel, canvas filling the
remainder, top toolbar, visible close control, and keyboard focus outlines.

Mobile: canvas fills the viewport including safe areas, panel becomes a
bottom sheet with a bounded height and independent scrolling, controls have
44-pixel targets, and no horizontal overflow occurs at 390 CSS pixels.

Use `prefers-reduced-motion` to remove nonessential transitions.

- [ ] **Step 8: Run JS, UI, and syntax tests**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_js.py tests\test_listing_map_ui.py -q
node --check static\js\main\listing_map.js
git diff --check
```

Expected: helpers, lazy vendor loading, history, copy, and DOM contracts pass.

- [ ] **Step 9: Commit the workspace**

```powershell
git add static/js/main/listing_map.js static/css/main/listing_map.css tests/test_listing_map_js.py tests/test_listing_map_ui.py
git diff --cached --check
git commit -m "feat: render filtered listings on Leaflet map"
```

---

### Task 8: Local integration, performance, and Plan 1 gate

**Files:**
- Modify only when a real defect is found in a Task 1–7 file

**Interfaces:**
- Consumes all Plan 1 deliverables.
- Produces local evidence required before planning-overlay integration.

- [ ] **Step 1: Run focused automated verification**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_query_scope.py `
  tests\test_listing_map_schema.py `
  tests\test_listing_location_registry.py `
  tests\test_listing_location_resolver.py `
  tests\test_listing_location_backfill.py `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_ui.py `
  tests\test_listing_map_js.py `
  tests\test_market_data_trust.py `
  tests\test_market_data_performance.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run syntax and regression checks**

```powershell
& $py -X utf8 -m py_compile app.py routes\market_api.py services\market_data.py services\listing_map.py services\listing_location_resolver.py services\listing_location_backfill.py db\schema.py db\listing_map_locations.py cli\map_locations.py cleansing\reprocess.py radar.py
node --check static\js\main\core.js
node --check static\js\main\listings.js
node --check static\js\main\listing_map.js
& $py -X utf8 -m pytest tests\test_guest_visibility.py tests\test_security_hardening.py tests\test_drop_filter.py -q
git diff --check
```

Expected: syntax, redaction, security, and filter regressions pass.

- [ ] **Step 3: Measure APIs against budgets**

Run cold once, warm five times, and record response byte size for both modes:

```powershell
$urls = @(
  "$base/api/map-listings?mode=signals",
  "$base/api/map-listings?mode=all"
)
foreach ($url in $urls) {
  1..6 | ForEach-Object {
    $timer = Measure-Command { $response = Invoke-WebRequest -UseBasicParsing $url }
    [PSCustomObject]@{
      Url = $url
      Run = $_
      Milliseconds = [Math]::Round($timer.TotalMilliseconds, 1)
      Bytes = $response.RawContentLength
    }
  }
}
```

Expected: cold at most 2500 ms, all warm runs at most 1000 ms, and the raw
payload is small enough that compressed size can remain below 750 KB. If a
budget fails, inspect the actual query plan before adding indexes or caps.

- [ ] **Step 4: Run local desktop and mobile browser flows**

At 1440×900 and 390×844 verify:

- launcher is bottom-center in both supported tabs;
- it does not cover the final result or mobile bottom navigation;
- it disappears on other tabs and while sidebar/tools/modal/chat/map is open;
- map opens without losing filters, list contents, or scroll position;
- Browser Back, Escape, and close button return to the same dashboard state;
- exact/road/ward copy is visible and unmapped count is honest;
- selecting a group lazy-loads compact items;
- OpenStreetMap and satellite base layers switch;
- a failed tile/API request preserves usable list tabs;
- keyboard focus is trapped and restored;
- launcher, dialog, close button, base-layer controls, group buttons, and retry
  controls expose correct accessible names/roles/states;
- loading toggles `aria-busy`, status changes are announced without stealing
  focus, and every map action is reachable by keyboard alone;
- no horizontal overflow or console error occurs.

- [ ] **Step 5: Compare map/feed parity with live local data**

For default, one ward, one property type, one keyword, one price range, one
area range, one date range, `only_drops=1`, `mos_min=25`, and `complete=1`,
compare API totals. The invariant is:

```text
map.summary.total = corresponding feed total
map.summary.mapped + map.summary.unmapped_count = map.summary.total
```

Expected: every comparison passes. Do not waive a mismatch as rounding.

- [ ] **Step 6: Review exact changed paths and stop before deploy**

```powershell
git status --short
git log --oneline --max-count=8
git diff origin/main...HEAD --stat
git diff origin/main...HEAD --check
```

Expected: only Plan 1 paths and approved documentation commits are present.
Do not push or deploy yet; continue with
`docs/superpowers/plans/2026-07-29-listing-planning-overlays.md`.
