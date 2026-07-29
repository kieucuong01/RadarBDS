# Listing Map Location Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 110-road manual ceiling with a generated, continuously audited road/landmark location pipeline for every Săn Deal and Tin Rao listing.

**Architecture:** A map-only context extractor reads title/description without changing canonical valuation fields. An offline, versioned gazetteer is generated from all named OpenStreetMap roads clipped to existing legacy ward boundaries plus provenance-checked local overrides; the resolver writes only derived locations and a persisted unresolved-coverage queue. Public map APIs remain compact, while Leaflet displays road, landmark, nearby-radius, ward, and future exact precision honestly.

**Tech Stack:** Python 3.12, Flask, PostgreSQL/psycopg compatibility wrapper, Shapely 2.1.2, PyProj 3.7.2, OpenStreetMap/Overpass JSON, Leaflet, vanilla JavaScript, pytest, Node.js.

## Global Constraints

- Do not write map-derived roads, landmarks, or coordinates into canonical `listings` fields.
- Do not weaken canonical proximity parsing: `cách/gần/sát/1 sẹc` must never become a frontage road for valuation or dedup.
- Do not call Overpass, Nominatim, Google, an LLM, or another geocoder from public requests, crawl, or reprocess.
- Do not introduce random coordinate jitter.
- Only source-provided validated coordinates may be labeled exact.
- Public map APIs must not expose description, evidence excerpts, URLs, phone numbers, seller names, or provenance URLs.
- Guest/Free/VIP source and redaction policies remain unchanged.
- Current modal-over-map behavior and map close/history state must remain unchanged.
- Use existing `requirements-map.txt` versions; add no new dependency.
- Registry builds must be byte-stable from pinned inputs and must preserve source hashes and provenance.
- Stage only files listed by the current task; preserve unrelated dirty work.

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `services/listing_map_context.py` | Map-only direct/nearby/alley/landmark/distance extraction |
| `services/listing_location_coverage.py` | Normalize and aggregate unresolved map-location candidates |
| `db/listing_location_coverage.py` | Persist and query the coverage queue |
| `config/listing_map_location_overrides.json` | Provenance-checked aliases, landmark entries, and exceptional road entries |
| `static/maps/listing-locations/landmark-centers.json` | Generated landmark registry |
| `tests/test_listing_map_context.py` | Map-only extraction regression tests |
| `tests/test_listing_location_coverage.py` | Coverage aggregation/repository tests |
| `tests/fixtures/listing-map/legacy-wards.geojson` | Small deterministic polygon fixture for registry tests |

### Modified files

| File | Responsibility in this change |
|---|---|
| `config/listing_map.py` | Resolver version, landmark/override/boundary paths, allowed precisions |
| `config/listing_map_overpass.ql` | Complete named-road and location-landmark extract query |
| `config/listing_map_location_sources.json` | Ward sources and legacy curated road seeds; no road-count ceiling |
| `scripts/build_listing_location_registry.py` | Generate every valid road/ward intersection and landmarks |
| `static/maps/listing-locations/{manifest,road-centers,ward-centers}.json` | Rebuilt versioned registry artifacts |
| `services/listing_location_resolver.py` | Multi-precision resolution, ambiguity guards, uncertainty radius |
| `services/listing_location_backfill.py` | Extract map context, resolve rows, update coverage queue |
| `db/listing_map_locations.py` | Load text inputs and persist expanded derived fields |
| `db/schema.py` | Expanded location schema and coverage table migration |
| `cli/map_locations.py` | Backfill and coverage-report commands |
| `radar.py` | `map-location-coverage` parser/dispatch |
| `services/listing_map.py` | New counts and compact group fields |
| `app.py` | Location-key allowlist and public payload contract |
| `static/js/main/listing_map.js` | Landmark/nearby copy, circle rendering, new counters |
| `static/css/main/listing_map.css` | Nearby/landmark UI styles |
| `templates/partials/listing_map_workspace.html` | Accuracy description copy |
| `templates/index.html` | JS/CSS cache-version bump |
| `docs/dev_commands.md` | Build, dry-run, coverage audit, backfill, and verification commands |
| Existing `tests/test_listing_location_*`, `tests/test_listing_map_*` | Contract and regression updates |

---

### Task 1: Add the map-only context extractor

**Files:**
- Create: `services/listing_map_context.py`
- Create: `tests/test_listing_map_context.py`

**Interfaces:**
- Consumes: listing `title`, `description`, and stored canonical `road_name`.
- Produces:
  - `MapLocationContext`
  - `extract_map_location_context(title: str, description: str, stored_road_name: str = "") -> MapLocationContext`
- Later tasks consume normalized `direct_road`, `nearby_road`, `landmark`, `relation`, `distance_m`, and `evidence_text`.

- [ ] **Step 1: Write failing direct-road normalization tests**

```python
from services.listing_map_context import extract_map_location_context


def test_direct_numbered_and_dx_roads_normalize_without_touching_proximity():
    cases = {
        "Đất Đường 88 khu TĐC Phú Chánh D": "duong so 88",
        "Mặt tiền ĐX-096 Hiệp An": "dx 96",
        "Đường Dx 092 thông": "dx 92",
        "Đường số 35 _ TĐC Phú Chánh B": "duong so 35",
    }
    for text, expected in cases.items():
        context = extract_map_location_context(text, "")
        assert context.direct_road == expected
        assert context.nearby_road == ""
        assert context.relation == "on"
```

- [ ] **Step 2: Write failing proximity, landmark, and distance tests**

```python
def test_proximity_relations_are_map_only_and_keep_distance():
    near = extract_map_location_context(
        "Bán đất Tân An",
        "Cách đường DX120 khoảng 100m, khu dân cư đông",
    )
    alley = extract_map_location_context(
        "Nhà 1 sẹc Huỳnh Thị Hiếu",
        "ô tô tới nhà",
    )
    assert (near.nearby_road, near.relation, near.distance_m) == (
        "dx 120",
        "near",
        100.0,
    )
    assert (alley.nearby_road, alley.relation) == (
        "huynh thi hieu",
        "alley",
    )


def test_landmark_aliases_normalize_to_one_identity():
    values = [
        "TĐC Phú Chánh C",
        "TDC Phu Chanh C",
        "tái định cư Phú Chánh C",
    ]
    assert {
        extract_map_location_context(value, "").landmark
        for value in values
    } == {"tdc phu chanh c"}
```

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_listing_map_context.py -q
```

Expected: collection fails because `services.listing_map_context` does not
exist.

- [ ] **Step 4: Implement the immutable context model and normalized extractors**

Create:

```python
from __future__ import annotations

from dataclasses import dataclass
import re

from services.listing_location_resolver import (
    normalize_location_token,
    normalize_road_token,
)


@dataclass(frozen=True)
class MapLocationContext:
    direct_road: str = ""
    nearby_road: str = ""
    landmark: str = ""
    relation: str = ""
    distance_m: float | None = None
    evidence_text: str = ""


_DISTANCE_RE = re.compile(
    r"\b(?:cach|gan|khoang)?\s*(\d{1,4}(?:[.,]\d+)?)\s*m\b",
    re.IGNORECASE,
)
_LANDMARK_RE = re.compile(
    r"\b(?:tdc|tai\s+dinh\s+cu|kdc|khu\s+dan\s+cu|"
    r"khu\s+do\s+thi|du\s+an)\s+"
    r"([a-z0-9][a-z0-9\s-]{1,70})",
    re.IGNORECASE,
)
_NEAR_PREFIX_RE = re.compile(
    r"\b(?:cach|gan|sat|ke|canh|ra|thong\s+ra)\s+"
    r"(?:duong\s+)?",
    re.IGNORECASE,
)
_ALLEY_PREFIX_RE = re.compile(
    r"\b(?:1\s*x(?:ec|et)|mot\s+x(?:ec|et)|nhanh|hem|1/)\s+"
    r"(?:duong\s+)?",
    re.IGNORECASE,
)
_CODED_ROAD_RE = re.compile(
    r"\b(?:duong\s+)?"
    r"((?:dx|d|db|dh|dl|nl|n)\s*[-./_]?\s*0*\d{1,4}[a-z]?"
    r"|(?:duong\s+)?(?:so\s+)?0*\d{1,4}[a-z]?)\b",
    re.IGNORECASE,
)
```

Implement helper functions that:

- fold Vietnamese text through `normalize_location_token`;
- stop landmark capture at punctuation or property/price words;
- normalize `Đường 88` and `Đường số 88` to `duong so 88`;
- normalize coded roads through `normalize_road_token`;
- prefer a stored road only when the text does not classify that reference as
  nearby/alley;
- keep an evidence excerpt internally, bounded to 180 characters.

The public function returns one immutable `MapLocationContext` and performs no
database write.

- [ ] **Step 5: Run focused and canonical proximity regression tests**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_context.py `
  tests\test_feature_extractor.py::test_extract_road_name_ignores_proximity_but_keeps_actual_roads `
  tests\test_feature_extractor.py::test_extract_road_name_keeps_nhanh_dx_codes -q
```

Expected: all pass; canonical
`extract_road_name("Nhà khu 1 Tân Định. Cách QL14 chỉ 70m")` remains `None`.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- services/listing_map_context.py tests/test_listing_map_context.py
git commit -m "feat: extract map-only listing location context"
```

---

### Task 2: Expand derived schema and repositories

**Files:**
- Modify: `db/schema.py`
- Modify: `db/listing_map_locations.py`
- Create: `db/listing_location_coverage.py`
- Modify: `tests/test_listing_map_schema.py`
- Create: `tests/test_listing_location_coverage.py`

**Interfaces:**
- Consumes: `ResolvedLocation` fields defined in Task 4; repository code may
  initially use attribute access without constructing those objects.
- Produces:
  - expanded `listing_map_locations`;
  - `listing_map_location_coverage`;
  - `upsert_listing_location_coverage(rows: Sequence[CoverageRow]) -> int`;
  - `load_listing_location_coverage(status: str = "", limit: int = 100) -> list[dict]`.

- [ ] **Step 1: Write failing migration-contract tests**

Update `tests/test_listing_map_schema.py`:

```python
def test_listing_map_location_migration_supports_all_honest_precisions():
    from db.schema import _migrate_listing_map_locations

    conn = _RecordingConnection()
    _migrate_listing_map_locations(conn)
    ddl = "\n".join(sql for sql, _params in conn.executed)

    for column in (
        "accuracy_radius_m DOUBLE PRECISION",
        "relation TEXT",
        "reference_road TEXT",
        "landmark_key TEXT",
        "resolution_status TEXT",
        "resolution_reason TEXT",
    ):
        assert column in ddl
    assert "'landmark'" in ddl
    assert "'nearby'" in ddl
    assert "CREATE TABLE IF NOT EXISTS listing_map_location_coverage" in ddl
    assert "DROP TABLE" not in ddl.upper()
    assert "TRUNCATE" not in ddl.upper()
    assert "UPDATE LISTINGS" not in ddl.upper()
```

- [ ] **Step 2: Write failing repository tests for candidate text and coverage rows**

Add tests that assert `iter_location_candidates()` selects `l.title` and
`l.description`, and that coverage upserts use:

```text
candidate_key, city, ward, road_candidate, landmark_candidate, relation,
status, affected_listing_count, sample_listing_ids, first_seen_at,
last_seen_at, resolution_note
```

Use a fake connection and assert public repository helpers never select phone,
URL, seller, or images.

- [ ] **Step 3: Run schema/repository tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_schema.py `
  tests\test_listing_location_coverage.py `
  tests\test_listing_location_backfill.py -q
```

Expected: failures for missing columns/table/module.

- [ ] **Step 4: Implement the idempotent PostgreSQL migration**

In both `SCHEMA_SQL` and `_migrate_listing_map_locations`, add nullable derived
columns:

```sql
accuracy_radius_m DOUBLE PRECISION
    CHECK (accuracy_radius_m IS NULL OR accuracy_radius_m >= 0),
relation TEXT,
reference_road TEXT,
landmark_key TEXT,
resolution_status TEXT NOT NULL DEFAULT 'resolved'
    CHECK (resolution_status IN ('resolved','ambiguous','not_found','invalid')),
resolution_reason TEXT
```

For existing production tables:

```sql
ALTER TABLE listing_map_locations
    ADD COLUMN IF NOT EXISTS accuracy_radius_m DOUBLE PRECISION;
ALTER TABLE listing_map_locations
    ADD COLUMN IF NOT EXISTS relation TEXT;
ALTER TABLE listing_map_locations
    ADD COLUMN IF NOT EXISTS reference_road TEXT;
ALTER TABLE listing_map_locations
    ADD COLUMN IF NOT EXISTS landmark_key TEXT;
ALTER TABLE listing_map_locations
    ADD COLUMN IF NOT EXISTS resolution_status TEXT NOT NULL DEFAULT 'resolved';
ALTER TABLE listing_map_locations
    ADD COLUMN IF NOT EXISTS resolution_reason TEXT;
ALTER TABLE listing_map_locations
    DROP CONSTRAINT IF EXISTS listing_map_locations_location_precision_check;
ALTER TABLE listing_map_locations
    ADD CONSTRAINT listing_map_locations_location_precision_check
    CHECK (location_precision IN ('exact','road','landmark','nearby','ward'))
    NOT VALID;
ALTER TABLE listing_map_locations
    VALIDATE CONSTRAINT listing_map_locations_location_precision_check;
```

Create:

```sql
CREATE TABLE IF NOT EXISTS listing_map_location_coverage (
    candidate_key TEXT PRIMARY KEY,
    city TEXT NOT NULL,
    ward TEXT NOT NULL DEFAULT '',
    road_candidate TEXT NOT NULL DEFAULT '',
    landmark_candidate TEXT NOT NULL DEFAULT '',
    relation TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL
        CHECK (status IN ('resolved','ambiguous','not_found','invalid')),
    affected_listing_count INTEGER NOT NULL DEFAULT 0,
    sample_listing_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolution_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_listing_map_coverage_status_count
ON listing_map_location_coverage(status, affected_listing_count DESC);
```

Constraint replacement may use `DROP CONSTRAINT`; tests prohibit dropping
tables/data and updating canonical listings, not this required enum expansion.

- [ ] **Step 5: Implement repository reads/writes**

Change `iter_location_candidates()` to select:

```sql
l.id, l.title, l.description, l.ward, l.road_name,
NULL::DOUBLE PRECISION AS source_lat,
NULL::DOUBLE PRECISION AS source_lng,
ml.resolver_version AS existing_resolver_version,
ml.listing_location_signature AS existing_signature
```

Extend `upsert_listing_map_locations()` with every new derived field. Create
`db/listing_location_coverage.py` with bounded sample IDs (maximum 10), JSONB
serialization, status validation, deterministic ordering, and an upsert that
preserves the oldest `first_seen_at` while updating counts and
`last_seen_at=NOW()`.

Until Task 4 expands `ResolvedLocation`, use these exact compatibility reads:

```python
getattr(row, "accuracy_radius_m", None)
getattr(row, "relation", "")
getattr(row, "reference_road", "")
getattr(row, "landmark_key", "")
getattr(row, "resolution_status", "resolved")
getattr(row, "resolution_reason", "")
```

Task 4 then exercises populated values without breaking this intermediate
commit.

- [ ] **Step 6: Run tests and compile**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_schema.py `
  tests\test_listing_location_coverage.py `
  tests\test_listing_location_backfill.py -q
& $py -X utf8 -m py_compile `
  db\schema.py `
  db\listing_map_locations.py `
  db\listing_location_coverage.py
```

Expected: pass.

- [ ] **Step 7: Commit Task 2**

```powershell
git add -- `
  db/schema.py `
  db/listing_map_locations.py `
  db/listing_location_coverage.py `
  tests/test_listing_map_schema.py `
  tests/test_listing_location_coverage.py `
  tests/test_listing_location_backfill.py
git commit -m "feat: store map precision and coverage status"
```

---

### Task 3: Generate the complete road and landmark gazetteer

**Files:**
- Modify: `config/listing_map.py`
- Modify: `config/listing_map_overpass.ql`
- Create: `config/listing_map_location_overrides.json`
- Modify: `scripts/build_listing_location_registry.py`
- Modify: `tests/test_listing_location_registry.py`
- Modify: `tests/fixtures/listing-map/osm-roads.json`
- Modify: `tests/fixtures/listing-map/location-sources.json`
- Create: `tests/fixtures/listing-map/legacy-wards.geojson`

**Interfaces:**
- Consumes:
  - pinned Overpass JSON;
  - `config/map_products/thu_dau_mot_legacy_boundaries.geojson`;
  - `config/map_products/ben_cat_legacy_boundaries.geojson`;
  - ward source points;
  - curated overrides.
- Produces:
  - `build_location_registries(osm_payload, sources, output_dir, *, overrides, boundary_paths) -> tuple[Path, Path, Path, Path]`;
  - deterministic ward, road, landmark, and manifest JSON in exactly that
    return order.

- [ ] **Step 1: Write failing complete-generation tests**

Add a fixture with:

- two connected `Đường ĐX 092` ways crossing the Hiệp An polygon;
- one unrelated named road outside every supported polygon;
- two identical `Đường số 35` names in different polygons;
- one named TĐC polygon;
- one unnamed highway to exclude.

Test:

```python
def test_builder_emits_all_named_roads_clipped_to_supported_wards(tmp_path):
    osm, sources, overrides, boundaries = _generated_payloads()
    paths = build_location_registries(
        osm,
        sources,
        tmp_path,
        overrides=overrides,
        boundary_paths=(boundaries,),
    )
    roads = json.loads(paths[1].read_text(encoding="utf-8"))["roads"]
    assert {
        (row["ward"], row["normalized_road"])
        for row in roads
    } == {
        ("Hiệp An", "dx 92"),
        ("Phú Tân", "duong so 35"),
    }
    assert next(
        row for row in roads if row["normalized_road"] == "dx 92"
    )["osm_way_ids"] == [898273670, 1504644404]
```

Test that output contains `landmark-centers.json`, that all four outputs are
byte-identical across two builds, and that manifest hashes match.

- [ ] **Step 2: Write failing provenance and ambiguity tests**

Add tests that reject:

- coordinate overrides without source/source URL/verified date;
- HTTP-only source URLs;
- out-of-bounds points;
- duplicate aliases in one scope;
- common road numbers assigned to multiple candidates without ward/landmark
  scope.

Add a test that a curated entry may cross an imperfect historical boundary only
when it includes `allow_boundary_mismatch: true` and a non-empty
`boundary_mismatch_reason`.

- [ ] **Step 3: Run registry tests and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_location_registry.py -q
```

Expected: failures for the old three-file/manual-road builder.

- [ ] **Step 4: Add complete source paths and precision configuration**

In `config/listing_map.py`:

```python
LISTING_MAP_RESOLVER_VERSION = "osm-binh-duong-20260729-v2"
LISTING_MAP_LANDMARK_REGISTRY_PATH = (
    LISTING_MAP_REGISTRY_DIR / "landmark-centers.json"
)
LISTING_MAP_OVERRIDE_PATH = (
    PROJECT_ROOT / "config" / "listing_map_location_overrides.json"
)
LISTING_MAP_WARD_BOUNDARY_PATHS = (
    PROJECT_ROOT / "config/map_products/thu_dau_mot_legacy_boundaries.geojson",
    PROJECT_ROOT / "config/map_products/ben_cat_legacy_boundaries.geojson",
)
LISTING_MAP_ALLOWED_PRECISIONS = frozenset(
    {"exact", "road", "landmark", "nearby", "ward"}
)
```

- [ ] **Step 5: Expand the pinned Overpass query**

Use:

```overpass
[out:json][timeout:180];
(
  way["highway"]["name"](10.75,106.25,11.65,107.10);
  way["highway"]["ref"](10.75,106.25,11.65,107.10);
  nwr["name"~"TĐC|TDC|tái định cư|khu dân cư|KDC|khu đô thị|dự án",i]
     (10.75,106.25,11.65,107.10);
  nwr["place"]["name"](10.75,106.25,11.65,107.10);
);
out tags center geom;
```

This file is only an offline extract recipe; production requests never execute
it.

- [ ] **Step 6: Implement ward clipping and complete road emission**

Use Shapely:

```python
from shapely.geometry import LineString, Point, shape
from shapely.ops import linemerge, unary_union


def _load_ward_boundaries(paths):
    # Return {(city, normalized_ward): (ward_label, geometry, provenance)}


def _way_line(element):
    return LineString(
        (float(point["lon"]), float(point["lat"]))
        for point in element.get("geometry") or []
    )


def _representative_line_point(geometry):
    point = geometry.interpolate(0.5, normalized=True)
    return float(point.y), float(point.x)
```

Group every valid named/ref highway by normalized identity, intersect merged
geometry with every supported ward polygon, and emit one row per non-empty
intersection. Store:

```text
city, ward, normalized_ward, road_name, normalized_road, lat, lng,
accuracy_radius_m, source, source_url, osm_way_ids
```

Compute `accuracy_radius_m` from the clipped geometry bounds using a local
WGS84 distance helper; never report less than 75 m for a road representative
point.

Preserve `fallback_parent` from the ward source registry. Bến Cát sub-zones
`Mỹ Phước 1` through `Mỹ Phước 4` use the verified `Mỹ Phước` parent geometry
only as a search scope; the builder must not duplicate every parent road into
every sub-zone or claim a sub-zone boundary that is unavailable.

- [ ] **Step 7: Implement landmarks and curated overrides**

Generate landmarks from matching OSM features, clipped/scoped when geometry is
available. Merge overrides after generated rows, with explicit precedence:

1. exact scoped curated override;
2. generated OSM candidate;
3. legacy curated road seed.

`config/listing_map_location_overrides.json` begins with:

```json
{
  "resolver_version": "osm-binh-duong-20260729-v2",
  "road_aliases": [],
  "roads": [],
  "landmark_aliases": [
    {
      "canonical": "TĐC Phú Chánh B",
      "aliases": [
        "TDC Phu Chanh B",
        "tái định cư Phú Chánh B"
      ]
    }
  ],
  "landmarks": []
}
```

Builder validation enforces provenance on every coordinate-bearing `roads` or
`landmarks` item.

- [ ] **Step 8: Run deterministic registry tests**

```powershell
& $py -X utf8 -m pytest tests\test_listing_location_registry.py -q
& $py -X utf8 -m py_compile `
  config\listing_map.py `
  scripts\build_listing_location_registry.py
```

Expected: pass, including byte-stability and failed-build output preservation.

- [ ] **Step 9: Commit Task 3 code and fixtures**

```powershell
git add -- `
  config/listing_map.py `
  config/listing_map_overpass.ql `
  config/listing_map_location_overrides.json `
  scripts/build_listing_location_registry.py `
  tests/test_listing_location_registry.py `
  tests/fixtures/listing-map/osm-roads.json `
  tests/fixtures/listing-map/location-sources.json `
  tests/fixtures/listing-map/legacy-wards.geojson
git commit -m "feat: generate complete listing location gazetteer"
```

---

### Task 4: Resolve road, landmark, nearby, ward, and ambiguity states

**Files:**
- Modify: `services/listing_location_resolver.py`
- Modify: `tests/test_listing_location_resolver.py`

**Interfaces:**
- Consumes:
  - `MapLocationContext` from Task 1;
  - four registry artifacts from Task 3.
- Produces:

```python
@dataclass(frozen=True)
class ResolutionIssue:
    listing_id: int
    candidate_key: str
    city: str
    ward: str
    road_candidate: str
    landmark_candidate: str
    relation: str
    status: str
    resolution_note: str


@dataclass(frozen=True)
class LocationResolution:
    location: ResolvedLocation | None
    issue: ResolutionIssue | None


def resolve_listing_location(
    listing: Mapping,
    registry: LocationRegistry,
    context: "MapLocationContext | None" = None,
) -> LocationResolution:
```

Use `TYPE_CHECKING` for the `MapLocationContext` import because Task 1 imports
the shared normalization helpers from this resolver:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.listing_map_context import MapLocationContext
```

- [ ] **Step 1: Update registry fixture and write failing precision tests**

Update `_registry()` so `roads` maps each
`(city, ward, normalized_road)` key to a tuple of entries and add landmark
entries.

Test precedence:

```python
def test_resolution_precedence_exact_road_landmark_nearby_ward():
    exact = _resolve(source_lat=10.991, source_lng=106.701)
    road = _resolve(text="Mặt tiền DX43")
    landmark = _resolve(text="TĐC Phú Chánh D")
    nearby = _resolve(text="Cách DX43 100m")
    ward = _resolve(text="Đất đẹp dân cư đông")
    assert [
        item.location.precision for item in
        (exact, road, landmark, nearby, ward)
    ] == ["exact", "road", "landmark", "nearby", "ward"]
    assert nearby.location.accuracy_radius_m >= 100
```

- [ ] **Step 2: Write failing ambiguity and conflict tests**

Test that two `Đường số 35` candidates in one ward return an issue with
`status="ambiguous"` and an honest ward location unless a landmark disambiguates
one candidate.

Test that a road/landmark mismatch does not silently choose a road and records
`resolution_reason="road_landmark_conflict"`.

- [ ] **Step 3: Run resolver tests and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_location_resolver.py -q
```

Expected: failures because the resolver returns only `ResolvedLocation`.

- [ ] **Step 4: Expand registry and result dataclasses**

Use:

```python
@dataclass(frozen=True)
class LocationRegistry:
    resolver_version: str
    roads: Mapping[
        tuple[str, str, str],
        tuple[Mapping[str, object], ...],
    ]
    landmarks: Mapping[
        tuple[str, str, str],
        Mapping[str, object],
    ]
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
    accuracy_radius_m: float | None = None
    relation: str = ""
    reference_road: str = ""
    landmark_key: str = ""
    resolution_status: str = "resolved"
    resolution_reason: str = ""
```

Update `load_location_registry()` to require matching versions across all four
artifacts and to return tuples for road keys so ambiguity remains visible.

- [ ] **Step 5: Implement deterministic precedence and fallback**

Implement helpers:

```python
def _road_scopes(city, ward, registry):
    normalized_ward = normalize_location_token(ward)
    scopes = [normalized_ward]
    ward_entry = registry.wards.get(
        (city, normalized_ward)
    ) or {}
    parent = normalize_location_token(ward_entry.get("fallback_parent") or "")
    if parent and parent not in scopes:
        scopes.append(parent)
    return tuple(scopes)


def _match_landmark(city, ward, normalized_landmark, registry):
    if not normalized_landmark:
        return None
    for scope in _road_scopes(city, ward, registry):
        entry = registry.landmarks.get((city, scope, normalized_landmark))
        if entry:
            return entry
    return None


def _match_road(
    city,
    ward,
    normalized_road,
    landmark_key,
    registry,
):
    entries = []
    for scope in _road_scopes(city, ward, registry):
        entries.extend(
            registry.roads.get((city, scope, normalized_road), ())
        )
    if landmark_key:
        scoped = [
            item for item in entries
            if landmark_key in tuple(item.get("landmark_keys") or ())
        ]
        if len(scoped) == 1:
            return scoped[0]
        if len(scoped) > 1:
            return "ambiguous"
    if len(entries) == 1:
        return entries[0]
    return "ambiguous" if entries else None


def _ward_fallback(
    *,
    listing_id,
    city,
    ward,
    registry,
    signature,
    status="resolved",
    reason="",
):
    entry = registry.wards.get(
        (city, normalize_location_token(ward))
    )
    if not entry:
        return None
    return _resolved_from_entry(
        listing_id=listing_id,
        precision="ward",
        location_key=f"ward:{_slug(city)}:{_slug(ward)}",
        entry=entry,
        resolver_version=registry.resolver_version,
        signature=signature,
        relation="",
        resolution_status=status,
        resolution_reason=reason,
    )
```

Rules:

- source coordinate first;
- direct road with matching landmark before direct road without landmark;
- landmark before nearby road;
- nearby/alley always stores `precision="nearby"`;
- ambiguous/not-found references return a ward location with the corresponding
  non-resolved status when a ward entry exists;
- no ward entry returns `location=None` plus an issue;
- `location_key` prefixes are exactly
  `exact:`, `road:`, `landmark:`, `nearby:`, `ward:`;
- signature includes normalized map context and resolver version inputs;
- no random imports.

When the canonical ward entry has `fallback_parent` (for example
`Mỹ Phước 3 -> Mỹ Phước`), road lookup may search the parent road scope only
when the normalized road is unique there. Multiple parent candidates remain
ambiguous unless landmark/sub-zone evidence selects one.

- [ ] **Step 6: Run resolver and context tests**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_location_resolver.py `
  tests\test_listing_map_context.py -q
& $py -X utf8 -m py_compile `
  services\listing_location_resolver.py `
  services\listing_map_context.py
```

Expected: pass.

- [ ] **Step 7: Commit Task 4**

```powershell
git add -- `
  services/listing_location_resolver.py `
  tests/test_listing_location_resolver.py
git commit -m "feat: resolve honest map location precision"
```

---

### Task 5: Integrate backfill, coverage queue, and CLI audits

**Files:**
- Create: `services/listing_location_coverage.py`
- Modify: `services/listing_location_backfill.py`
- Modify: `db/listing_map_locations.py`
- Modify: `db/listing_location_coverage.py`
- Modify: `cli/map_locations.py`
- Modify: `radar.py`
- Modify: `cleansing/reprocess.py`
- Modify: `tests/test_listing_location_backfill.py`
- Modify: `tests/test_reprocess_review_hidden.py`
- Modify: `tests/test_listing_location_coverage.py`

**Interfaces:**
- Consumes `LocationResolution` from Task 4.
- Produces:
  - `CoverageRow`;
  - `aggregate_coverage_issues(issues) -> list[CoverageRow]`;
  - `backfill_listing_locations(listing_ids: Sequence[int] | None = None, *, full: bool = False, dry_run: bool = False) -> dict[str, int]`
    with all precision and issue counts;
  - `radar.py map-location-coverage`.

- [ ] **Step 1: Write failing backfill integration tests**

Expand the candidate helper with title/description. Assert:

```python
assert stats == {
    "scanned": 6,
    "exact": 1,
    "road": 1,
    "landmark": 1,
    "nearby": 1,
    "ward": 1,
    "unmapped": 1,
    "ambiguous": 1,
    "not_found": 1,
    "invalid": 0,
    "inserted": 5,
    "updated": 0,
    "unchanged": 0,
    "deleted": 0,
}
```

Assert `extract_map_location_context()` is called before resolution, expanded
derived rows are upserted, and aggregated issues are written once per batch.

- [ ] **Step 2: Write failing coverage aggregation and CLI tests**

Test deterministic grouping:

```python
def test_coverage_issues_group_by_normalized_candidate():
    rows = aggregate_coverage_issues([
        _issue(10, road="dx 120", status="not_found"),
        _issue(11, road="dx 120", status="not_found"),
    ])
    assert len(rows) == 1
    assert rows[0].affected_listing_count == 2
    assert rows[0].sample_listing_ids == (10, 11)
```

Test parser/dispatch:

```text
radar.py map-location-coverage
radar.py map-location-coverage --status unresolved --limit 50
```

`unresolved` expands to `ambiguous,not_found,invalid`.

- [ ] **Step 3: Run backfill/CLI tests and verify RED**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_location_backfill.py `
  tests\test_listing_location_coverage.py `
  tests\test_reprocess_review_hidden.py -q
```

Expected: failures for missing aggregation/CLI/new stats.

- [ ] **Step 4: Implement coverage aggregation**

Create:

```python
@dataclass(frozen=True)
class CoverageRow:
    candidate_key: str
    city: str
    ward: str
    road_candidate: str
    landmark_candidate: str
    relation: str
    status: str
    affected_listing_count: int
    sample_listing_ids: tuple[int, ...]
    resolution_note: str
```

`candidate_key` is a SHA-256 of normalized
`city|ward|road|landmark|relation|status`. Sort rows by descending affected
count then key. Limit sample IDs to ten ascending unique IDs.

- [ ] **Step 5: Update backfill orchestration**

For each candidate:

1. derive city;
2. extract map context from title/description/stored road;
3. resolve;
4. record precision/status counts;
5. compare expanded signature/version;
6. queue changed locations;
7. collect any issue with listing ID.

On non-dry-run:

- upsert changed locations;
- delete newly unmapped derived rows;
- upsert aggregated coverage rows;
- prune stale coverage candidates during `full=True`;
- invalidate the map cache only after writes.

Do not call any network service.

- [ ] **Step 6: Implement JSON coverage CLI**

`cmd_map_location_coverage(args)` prints:

```json
{
  "status": ["ambiguous", "not_found", "invalid"],
  "total_candidates": 12,
  "affected_listings": 84,
  "items": []
}
```

Each item contains only candidate identities, counts, sample listing IDs, and
resolution notes. It does not print descriptions, phone numbers, URLs, or
seller names.

- [ ] **Step 7: Verify scoped reprocess behavior**

Keep the existing `cleansing.reprocess` scoped call. Update tests to prove:

- incremental reprocess passes only touched listing IDs;
- full reprocess triggers full map backfill;
- no external geocoder/LLM call occurs;
- human labels remain untouched.

- [ ] **Step 8: Run focused tests and compile**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_location_backfill.py `
  tests\test_listing_location_coverage.py `
  tests\test_reprocess_review_hidden.py -q
& $py -X utf8 -m py_compile `
  services\listing_location_coverage.py `
  services\listing_location_backfill.py `
  db\listing_map_locations.py `
  db\listing_location_coverage.py `
  cli\map_locations.py `
  radar.py `
  cleansing\reprocess.py
```

Expected: pass.

- [ ] **Step 9: Commit Task 5**

```powershell
git add -- `
  services/listing_location_coverage.py `
  services/listing_location_backfill.py `
  db/listing_map_locations.py `
  db/listing_location_coverage.py `
  cli/map_locations.py `
  radar.py `
  cleansing/reprocess.py `
  tests/test_listing_location_backfill.py `
  tests/test_listing_location_coverage.py `
  tests/test_reprocess_review_hidden.py
git commit -m "feat: audit unresolved listing map coverage"
```

---

### Task 6: Build and validate the production registry

**Files:**
- Modify: `config/listing_map_location_sources.json`
- Modify: `config/listing_map_location_overrides.json`
- Modify: `static/maps/listing-locations/ward-centers.json`
- Modify: `static/maps/listing-locations/road-centers.json`
- Create: `static/maps/listing-locations/landmark-centers.json`
- Modify: `static/maps/listing-locations/manifest.json`
- Modify: `tests/test_listing_location_registry.py`
- Modify: `docs/dev_commands.md`

**Interfaces:**
- Consumes the builder and validation contract from Task 3.
- Produces the actual `v2` production registry and a reproducible build command.

- [ ] **Step 1: Fetch a pinned offline extract into ignored local storage**

Run:

```powershell
$query = Get-Content -Raw -LiteralPath config\listing_map_overpass.ql
$body = @{ data = $query }
$osmPath = ".local\listing-map\osm-binh-duong-20260729-v2.json"
New-Item -ItemType Directory -Force -Path (Split-Path $osmPath) | Out-Null
Invoke-WebRequest `
  -Method Post `
  -Uri "https://overpass-api.de/api/interpreter" `
  -Headers @{"User-Agent"="RadarBDS-registry-build/2.0"} `
  -Body $body `
  -TimeoutSec 240 `
  -OutFile $osmPath
```

The `.local` input is ignored and is never committed. Record its SHA-256 in the
generated manifest.

- [ ] **Step 2: Add verified aliases and known OSM roads**

Ensure the generated extract includes these observed OSM ways:

```text
Đường số 35: 225107254
Đường số 37: 1369653803
ĐX 092: 612555137, 898273670, 1504644404
ĐX 096: 1238200031
```

Add aliases for zero padding and Vietnamese/ascii variants. Do not add a
coordinate override for DX120, Đường 88, or 11B until a visible official GIS or
OSM source is checked.

DX092 and DX096 are emitted from their Hiệp An polygon intersections. Đường số
35/37 lie outside the available legacy boundary snapshots; add them only as
landmark-scoped curated road entries for `TĐC Phú Chánh B`, using their OSM way
URLs as provenance plus `allow_boundary_mismatch: true` and the explicit reason
`broker landmark is stronger than available historical ward boundary`.

- [ ] **Step 3: Verify local-only roads/landmarks using visible map evidence**

For each of DX120, TĐC Phú Chánh B/C/D, and TĐC Định Hòa:

1. search the official GIS link already approved by the product;
2. cross-check the visible location against the road/ward context and satellite
   base layer;
3. record a point/polygon and an uncertainty radius only when the source is
   visible and consistent;
4. store the official HTTPS source URL, verification date `2026-07-29`, and a
   boundary-mismatch reason where applicable;
5. otherwise leave the road `not_found` and use only the verified
   landmark/ward fallback.

This step must not invent a coordinate to satisfy a regression expectation.

- [ ] **Step 4: Build artifacts atomically**

Run:

```powershell
& $py -X utf8 scripts\build_listing_location_registry.py `
  --osm-json .local\listing-map\osm-binh-duong-20260729-v2.json `
  --sources config\listing_map_location_sources.json `
  --overrides config\listing_map_location_overrides.json `
  --boundary config\map_products\thu_dau_mot_legacy_boundaries.geojson `
  --boundary config\map_products\ben_cat_legacy_boundaries.geojson `
  --output-dir static\maps\listing-locations
```

Expected:

- four paths printed;
- `road_count > 110`;
- `landmark_count > 0`;
- hashes populated;
- no output file is replaced if validation fails.

- [ ] **Step 5: Replace hard-coded count assertions with completeness assertions**

Production registry tests must assert:

- all supported canonical wards remain present;
- all valid named/ref OSM ways intersecting supported boundaries are represented
  or explicitly rejected with reason;
- landmark/road/ward/manifest versions match;
- all hashes match;
- all points and radii are valid;
- known OSM example roads exist;
- no manual `road_count == 110` ceiling remains.

- [ ] **Step 6: Run local dry-run coverage against current PostgreSQL**

```powershell
& $py -X utf8 radar.py map-locations --full --dry-run
& $py -X utf8 radar.py map-location-coverage --status unresolved --limit 100
```

Capture only counts and IDs in the working notes; do not commit runtime reports.
Verify every detected candidate is classified and none disappears silently.

- [ ] **Step 7: Document exact rebuild and audit commands**

Add the Task 6 commands to `docs/dev_commands.md`, including:

- required `requirements-map.txt`;
- ignored OSM input location;
- build;
- JSON validation;
- dry-run;
- full backfill;
- unresolved coverage audit;
- statement that no canonical listing field changes.

- [ ] **Step 8: Run registry/context/resolver/backfill tests**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_location_registry.py `
  tests\test_listing_map_context.py `
  tests\test_listing_location_resolver.py `
  tests\test_listing_location_backfill.py `
  tests\test_listing_location_coverage.py -q
& $py -X utf8 -m json.tool `
  static\maps\listing-locations\manifest.json > $null
& $py -X utf8 -m json.tool `
  static\maps\listing-locations\road-centers.json > $null
& $py -X utf8 -m json.tool `
  static\maps\listing-locations\landmark-centers.json > $null
```

Expected: pass.

- [ ] **Step 9: Commit Task 6**

```powershell
git add -- `
  config/listing_map_location_sources.json `
  config/listing_map_location_overrides.json `
  static/maps/listing-locations/ward-centers.json `
  static/maps/listing-locations/road-centers.json `
  static/maps/listing-locations/landmark-centers.json `
  static/maps/listing-locations/manifest.json `
  tests/test_listing_location_registry.py `
  docs/dev_commands.md
git commit -m "data: expand listing map location coverage"
```

---

### Task 7: Extend compact map API contracts

**Files:**
- Modify: `services/listing_map.py`
- Modify: `app.py`
- Modify: `tests/test_listing_map_service.py`
- Modify: `tests/test_listing_map_api.py`
- Modify: `tests/test_market_data_performance.py`

**Interfaces:**
- Consumes expanded `listing_map_locations`.
- Produces compact summary groups with:

```text
precision, accuracy_radius_m, relation, label
```

and summary counts:

```text
exact_count, road_count, landmark_count, nearby_count, ward_count,
mapped, unmapped_count, total
```

- [ ] **Step 1: Write failing summary invariant tests**

Update fixture rows to include landmark and nearby groups. Assert:

```python
assert (
    summary["exact_count"]
    + summary["road_count"]
    + summary["landmark_count"]
    + summary["nearby_count"]
    + summary["ward_count"]
    == summary["mapped"]
)
assert summary["mapped"] + summary["unmapped_count"] == summary["total"]
assert nearby_group["accuracy_radius_m"] == 150.0
assert nearby_group["relation"] == "near"
```

- [ ] **Step 2: Write failing API redaction/key tests**

Assert these keys remain stripped:

```text
description, evidence_text, source_url, url, phone, contact_phone,
seller_name
```

Assert the location-key regex accepts `landmark:` and `nearby:` but rejects
unknown prefixes and unsafe characters.

- [ ] **Step 3: Run API/service tests and verify RED**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py `
  tests\test_market_data_performance.py -q
```

Expected: missing new counters/fields and rejected new key prefixes.

- [ ] **Step 4: Extend summary SQL and serialization**

Select/group:

```sql
ml.accuracy_radius_m,
ml.relation
```

Add filtered window counts for `landmark` and `nearby`. Return only numeric
radius, allowlisted relation, and existing compact fields. Keep descriptions
out of both summary and item SQL.

- [ ] **Step 5: Update key validation**

Change:

```python
_LISTING_MAP_LOCATION_KEY_RE = re.compile(
    r"^(exact|road|landmark|nearby|ward):[a-z0-9:-]+$"
)
```

Do not add raw location values to tracking.

- [ ] **Step 6: Run focused tests and compile**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py `
  tests\test_market_data_performance.py -q
& $py -X utf8 -m py_compile services\listing_map.py app.py
```

Expected: pass.

- [ ] **Step 7: Commit Task 7**

```powershell
git add -- `
  services/listing_map.py `
  app.py `
  tests/test_listing_map_service.py `
  tests/test_listing_map_api.py `
  tests/test_market_data_performance.py
git commit -m "feat: expose honest map precision groups"
```

---

### Task 8: Render landmarks and nearby uncertainty circles

**Files:**
- Modify: `static/js/main/listing_map.js`
- Modify: `static/css/main/listing_map.css`
- Modify: `templates/partials/listing_map_workspace.html`
- Modify: `templates/index.html`
- Modify: `tests/test_listing_map_js.py`
- Modify: `tests/test_listing_map_ui.py`

**Interfaces:**
- Consumes Task 7 summary fields.
- Preserves `openListingFromMap`, `shouldCloseMapOnPopstate`, filter snapshots,
  and modal-over-map behavior.

- [ ] **Step 1: Write failing JavaScript precision/circle tests**

Add Node assertions:

```python
assert _run_node("mapApi.precisionCopy('landmark').badge") == "Theo khu vực"
assert _run_node("mapApi.precisionCopy('nearby').badge") == "Vị trí gần đúng"
assert _run_node("mapApi.normalizeAccuracyRadius(150)") == 150
assert _run_node("mapApi.normalizeAccuracyRadius(-1)") == 0
assert _run_node("mapApi.normalizeAccuracyRadius(100000)") == 20000
```

Source regression must require `root.L.circle(` for nearby groups and must keep
`root.L.circleMarker(` for the selectable center.

- [ ] **Step 2: Write failing rendered UI tests**

Assert workspace description mentions:

```text
tọa độ, tuyến đường, khu dân cư, vùng gần đúng hoặc trung tâm phường
```

Assert JS/CSS asset versions use a new shared
`listing-map-location-coverage-20260729` version.

- [ ] **Step 3: Run JS/UI tests and verify RED**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_js.py `
  tests\test_listing_map_ui.py -q
```

Expected: missing precision copy/radius/circle.

- [ ] **Step 4: Implement precision copy and styles**

Add:

```javascript
landmark: {
  badge: "Theo khu vực",
  detail: "Tin được đặt tại khu TĐC, KDC hoặc dự án đã xác minh."
},
nearby: {
  badge: "Vị trí gần đúng",
  detail: "Tin chỉ cho biết gần, cách hoặc một nhánh từ tuyến đường tham chiếu."
}
```

Use teal marker colors for `landmark`, violet/dashed styling for `nearby`, and
retain existing exact/road/ward colors.

- [ ] **Step 5: Render nearby radius without fake offsets**

Implement:

```javascript
function normalizeAccuracyRadius(value) {
  var number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return 0;
  return Math.min(Math.round(number), 20000);
}
```

In `renderMarkers()`:

```javascript
if (group.precision === "nearby") {
  var radius = normalizeAccuracyRadius(group.accuracy_radius_m);
  if (radius) {
    root.L.circle([lat, lng], {
      radius: radius,
      color: "#7c3aed",
      weight: 2,
      dashArray: "7 6",
      fillColor: "#8b5cf6",
      fillOpacity: 0.12,
      interactive: false
    }).addTo(state.markerLayer);
  }
}
```

Always add the accessible center marker to select the group. Do not change its
coordinates client-side.

- [ ] **Step 6: Add summary counters and bump cache versions**

Summary cards include `Theo khu vực` and `Gần đúng`. Update the workspace copy
and bump both listing-map asset versions in `templates/index.html`.

- [ ] **Step 7: Run JS/UI regression tests**

```powershell
node --check static\js\main\listing_map.js
& $py -X utf8 -m pytest `
  tests\test_listing_map_js.py `
  tests\test_listing_map_ui.py `
  tests\test_listing_map_api.py -q
```

Expected: pass, including modal click and popstate tests.

- [ ] **Step 8: Commit Task 8**

```powershell
git add -- `
  static/js/main/listing_map.js `
  static/css/main/listing_map.css `
  templates/partials/listing_map_workspace.html `
  templates/index.html `
  tests/test_listing_map_js.py `
  tests/test_listing_map_ui.py
git commit -m "feat: show approximate map location areas"
```

---

### Task 9: Verify, push, deploy, backfill, and prove production behavior

**Files:**
- Modify only if verification exposes a scoped defect.

**Interfaces:**
- Consumes all previous tasks.
- Produces a released `main`, production schema/registry/backfill, public API
  proof, and browser behavior proof.

- [ ] **Step 1: Run the complete focused test matrix**

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest `
  tests\test_listing_map_context.py `
  tests\test_listing_location_registry.py `
  tests\test_listing_location_resolver.py `
  tests\test_listing_location_backfill.py `
  tests\test_listing_location_coverage.py `
  tests\test_listing_map_schema.py `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_js.py `
  tests\test_listing_map_ui.py `
  tests\test_market_data_performance.py `
  tests\test_reprocess_review_hidden.py -q
```

Expected: all pass.

- [ ] **Step 2: Run static checks**

```powershell
& $py -X utf8 -m py_compile `
  app.py `
  radar.py `
  db\schema.py `
  db\listing_map_locations.py `
  db\listing_location_coverage.py `
  services\listing_map_context.py `
  services\listing_location_resolver.py `
  services\listing_location_backfill.py `
  services\listing_location_coverage.py `
  services\listing_map.py `
  scripts\build_listing_location_registry.py
node --check static\js\main\listing_map.js
git diff --check
git status --short
```

Expected: no syntax error, whitespace error, or unrelated dirty path.

- [ ] **Step 3: Run local schema/API/backfill smoke**

```powershell
& $py -X utf8 radar.py inspect
& $py -X utf8 radar.py map-locations --full --dry-run
& $py -X utf8 radar.py map-location-coverage --status unresolved --limit 20
& $py -X utf8 -c "from app import app; c=app.test_client(); [print(p, c.get(p).status_code) for p in ['/api/map-listings?mode=signals','/api/map-listings?mode=all']]"
```

Expected:

- schema reachable;
- every detected candidate classified;
- both APIs return 200;
- summary invariants hold.

- [ ] **Step 4: Run local browser verification**

Use the Playwright skill against the local app:

1. open Săn Deal Maps;
2. confirm road/landmark/nearby/ward legend and counts;
3. select a nearby circle;
4. open a listing modal over the map;
5. close the modal and confirm map state remains;
6. repeat on Tin Rao and mobile viewport;
7. assert no console error.

- [ ] **Step 5: Review commit scope and push**

```powershell
git status --short
git log --oneline origin/main..HEAD
git push origin codex/listing-maps-planning
git push origin HEAD:main
```

Expected: both pushes succeed and `origin/main` points to the verified HEAD.

- [ ] **Step 6: Deploy code and run schema migration**

```powershell
.\scripts\deploy_production.ps1
```

Expected:

- production worktree guard passes;
- service restarts active;
- `/api/dashboard` and `/api/signals` smokes pass.

If the normal GitHub alias fails, use the existing deploy script's bundle
fallback; do not reset or discard production-only files.

- [ ] **Step 7: Run production dry-run, full backfill, and coverage audit**

```powershell
$key = "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa"
$hostName = "deploy@103.90.226.230"
ssh -i $key $hostName "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py map-locations --full --dry-run"
ssh -i $key $hostName "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py map-locations --full"
ssh -i $key $hostName "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py map-location-coverage --status unresolved --limit 20"
```

Expected:

- full apply completes;
- road/landmark/nearby/ward counts sum to mapped;
- unresolved candidates are visible with counts/sample IDs;
- no canonical listing update is performed.

- [ ] **Step 8: Verify regression listing IDs in production DB**

Read-only query:

```sql
SELECT l.id,
       ml.location_precision,
       ml.location_label,
       ml.accuracy_radius_m,
       ml.resolution_status,
       ml.resolution_reason
FROM listings l
LEFT JOIN listing_map_locations ml ON ml.listing_id=l.id
WHERE l.id IN (63565,63566,63436,63432,63514,63425,62260)
ORDER BY l.id;
```

Expected:

- 63514 is road DX096;
- 63425 is road DX092;
- 63565/63566 use verified road/landmark-scoped points;
- entries without verified road coordinates use landmark/nearby/ward copy and
  retain explicit `not_found`/reason instead of claiming road precision.

- [ ] **Step 9: Verify public APIs and browser behavior**

Check:

```powershell
Invoke-RestMethod "https://radarbds.vn/api/map-listings?mode=signals"
Invoke-RestMethod "https://radarbds.vn/api/map-listings?mode=all"
```

Then run production Playwright:

1. open both map modes;
2. assert new asset version loaded;
3. verify nearby circle and label;
4. open and close listing modal without leaving Maps;
5. confirm all summary invariants;
6. confirm zero console errors and no sensitive public payload keys.

- [ ] **Step 10: Record final release evidence**

Report:

- final commit;
- pushed branches;
- production HEAD;
- service state;
- focused test count;
- production backfill counts;
- unresolved coverage counts;
- seven regression ID outcomes;
- public API summaries;
- browser modal/state and console result.

Do not claim every parcel is exact. State separately how many are exact, road,
landmark, nearby, ward, and unresolved.
