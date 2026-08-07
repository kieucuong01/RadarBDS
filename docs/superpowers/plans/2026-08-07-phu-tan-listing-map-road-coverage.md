# Phú Tân Listing Map Road Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve `Tin rao` / `mode=all` map placement for Phú Tân by moving road-bearing rows out of `THEO PHƯỜNG`, with a 65-listing regression gate.

**Architecture:** Keep public Maps request paths static and deterministic. Improve resolver inputs through map-only ward aliases, safer parser normalization, aggregate road registry rows for repeated OSM segments, and targeted Phú Chánh C/D evidence. Verify with fixtures and production dry-run/backfill.

**Tech Stack:** Python 3.12, Flask, PostgreSQL, static JSON registry under `static/maps/listing-locations`, pytest, PowerShell.

## Global Constraints

- Scope is `Tin rao` / `Toàn bộ tin rao`, target URL uses `tab=all`.
- Do not call Google Maps or any live geocoder during public page requests.
- Do not mutate canonical listing ward/area fields for this Maps-only improvement.
- Do not reprocess valuation, human feedback, or AI review data.
- Pilot covers Phú Tân plus legacy Phú Chánh alias only.
- Regression gate: at least `60/65` fixture rows resolve to non-ward precision.
- False positives like `kinh doanh`, `phuong binh`, `tay anh em oi`, and `5m` must not become road locations.

---

### Task 1: Add Phú Tân regression fixture and failing resolver tests

**Files:**
- Create: `tests/fixtures/phu_tan_map_ward_road_candidates.json`
- Modify: `tests/test_listing_location_resolver.py`

**Interfaces:**
- Consumes: `services.listing_location_resolver.load_location_registry()`
- Consumes: `services.listing_location_resolver.resolve_listing_location(listing, registry=...)`
- Produces: tests that fail until resolver/registry changes move at least 60 of 65 fixtures to non-ward precision.

- [ ] **Step 1: Create fixture from the approved 65 production IDs**

Store rows with fields `id`, `ward`, `road_name`, `title`, `description`, and expected `min_precision="road_or_landmark"`. Include representative roads from the 65 IDs: `Đường số 84`, `N5`, `N6`, `N3`, `Đường số 110B`, and Phú Chánh/TĐC text.

- [ ] **Step 2: Write failing tests**

Add tests:

```python
def test_phu_tan_fixture_moves_road_bearing_rows_out_of_ward_precision():
    registry = load_location_registry()
    fixtures = _load_phu_tan_fixture()
    failures = []
    for listing in fixtures:
        result = resolve_listing_location(listing, registry=registry)
        if not result.location or result.location.precision == "ward":
            failures.append((listing["id"], getattr(result.issue, "resolution_note", "")))
    assert len(fixtures) == 65
    assert len(fixtures) - len(failures) >= 60
```

```python
def test_phu_tan_false_positive_road_candidates_do_not_become_roads():
    registry = load_location_registry()
    for phrase in ("kinh doanh", "phuong binh", "tay anh em oi", "duong 5m"):
        listing = {"id": 900000, "ward": "Phú Tân", "title": f"Nhà {phrase}", "description": "", "road_name": ""}
        result = resolve_listing_location(listing, registry=registry)
        assert not result.location or result.location.precision != "road"
```

- [ ] **Step 3: Run red test**

Run:

```powershell
& $py -X utf8 -m pytest --basetemp .pytest-tmp\run tests\test_listing_location_resolver.py::test_phu_tan_fixture_moves_road_bearing_rows_out_of_ward_precision -q
```

Expected: FAIL because current resolver leaves more than 5 of the 65 rows at ward precision.

---

### Task 2: Add map-only Phú Chánh -> Phú Tân alias

**Files:**
- Modify: `config/listing_map.py`
- Modify: `services/listing_location_resolver.py`
- Modify: `tests/test_listing_location_resolver.py`

**Interfaces:**
- Produces: `canonical_map_ward(city: str, ward: str) -> str`
- Consumes: canonical ward in resolver lookups for ward, landmark, and road registry keys.

- [ ] **Step 1: Write failing alias test**

```python
def test_map_resolver_treats_phu_chanh_as_phu_tan_without_mutating_listing():
    registry = load_location_registry()
    listing = {"id": 910001, "ward": "Phú Chánh", "title": "Đường số 35 TĐC Phú Chánh", "description": "", "road_name": ""}
    result = resolve_listing_location(listing, registry=registry)
    assert result.location
    assert result.location.precision in {"road", "landmark"}
    assert "phu-tan" in result.location.location_key
    assert listing["ward"] == "Phú Chánh"
```

- [ ] **Step 2: Implement alias lookup**

Add `LISTING_MAP_WARD_ALIASES = {("THỦ DẦU MỘT", "phu chanh"): "Phú Tân"}` and use it in resolver canonicalization before registry lookup.

- [ ] **Step 3: Run alias tests**

Run:

```powershell
& $py -X utf8 -m pytest --basetemp .pytest-tmp\run tests\test_listing_location_resolver.py::test_map_resolver_treats_phu_chanh_as_phu_tan_without_mutating_listing -q
```

Expected: PASS.

---

### Task 3: Normalize coded and numbered roads safely

**Files:**
- Modify: `services/listing_map_context.py`
- Modify: `services/listing_location_resolver.py`
- Modify: `tests/test_listing_map_context.py`
- Modify: `tests/test_listing_location_resolver.py`

**Interfaces:**
- Consumes: `normalize_road_token(value: str) -> str`
- Produces: safer road candidates for `110B`, `110 b`, `11B`, `DB6`, `N5/N6`.

- [ ] **Step 1: Write red tests**

```python
def test_number_letter_roads_normalize_to_numbered_road_when_context_says_road():
    assert normalize_road_token("110B") == "duong so 110 b"
    assert normalize_road_token("110 b") == "duong so 110 b"
    assert normalize_road_token("Đường 11B") == "duong so 11 b"
```

```python
def test_width_and_marketing_phrases_do_not_become_road_candidates():
    assert extract_map_location_context("1 sẹc đường 5m", "").nearby_road == ""
    assert extract_map_location_context("Nhà kinh doanh Phú Tân", "").direct_road == ""
```

- [ ] **Step 2: Implement minimal normalization**

Update road normalization to convert pure numeric-letter tokens into `duong so ...` only when the token is not a width token ending in `m`. Keep coded prefixes `db`, `dx`, `d`, `n` as code roads.

- [ ] **Step 3: Run parser tests**

Run:

```powershell
& $py -X utf8 -m pytest --basetemp .pytest-tmp\run tests\test_listing_map_context.py tests\test_listing_location_resolver.py::test_number_letter_roads_normalize_to_numbered_road_when_context_says_road -q
```

Expected: PASS.

---

### Task 4: Build aggregate road registry entries for ambiguous roads

**Files:**
- Modify: `scripts/build_listing_location_registry.py`
- Modify: `services/listing_location_resolver.py`
- Modify: `tests/test_listing_location_registry.py`
- Modify: `tests/test_listing_location_resolver.py`
- Regenerate: `static/maps/listing-locations/road-centers.json`
- Regenerate: `static/maps/listing-locations/manifest.json`

**Interfaces:**
- Produces registry roads with `aggregate=true` and `component_count > 1` for same `(city, ward, normalized_road)`.
- Resolver uses aggregate row when exact road lookup has multiple rows.

- [ ] **Step 1: Write red resolver test for Đường số 84**

```python
def test_ambiguous_phu_tan_duong_so_84_uses_aggregate_road():
    registry = load_location_registry()
    listing = {"id": 910084, "ward": "Phú Tân", "title": "Đường số 84 TĐC Phú Chánh", "description": "", "road_name": ""}
    result = resolve_listing_location(listing, registry=registry)
    assert result.location
    assert result.location.precision == "road"
    assert "duong-so-84" in result.location.location_key
```

- [ ] **Step 2: Add registry aggregate generation**

When multiple road rows share the same `(city, normalized_ward, normalized_road)`, add one aggregate row with deterministic sorted OSM IDs, average point, and radius covering child points.

- [ ] **Step 3: Update resolver selection**

If a road lookup returns multiple rows and one is marked aggregate, use it. If no aggregate exists, keep existing ambiguous behavior.

- [ ] **Step 4: Rebuild registry and run hash check**

Run the existing registry build command with `.local\listing-map\osm-binh-duong-20260807-v4.json`, then build again into `.local\listing-map\registry-check-v4-phu-tan` and compare SHA-256 for the four JSON outputs.

---

### Task 5: Add Phú Chánh C/D landmarks and targeted overrides

**Files:**
- Modify: `config/listing_map_location_overrides.json` or `config/listing_map_location_auto_overrides.json`
- Regenerate: `static/maps/listing-locations/landmark-centers.json`
- Regenerate: `static/maps/listing-locations/road-centers.json`
- Regenerate: `static/maps/listing-locations/manifest.json`
- Modify: `tests/test_listing_location_registry.py`

**Interfaces:**
- Produces landmark entries for `tdc phu chanh c` and `tdc phu chanh d`.

- [ ] **Step 1: Write red landmark registry tests**

```python
def test_phu_chanh_c_and_d_landmarks_exist_in_phu_tan_registry():
    registry = load_location_registry()
    keys = {key for key in registry.landmarks}
    assert ("THỦ DẦU MỘT", "phu tan", "tdc phu chanh c") in keys
    assert ("THỦ DẦU MỘT", "phu tan", "tdc phu chanh d") in keys
```

- [ ] **Step 2: Add verified override entries**

Use browser/Google Maps evidence or existing internal map source URLs for C/D. Include `source_url`, `verified_at`, `accuracy_radius_m`, and boundary mismatch reason if needed.

- [ ] **Step 3: Rebuild registry**

Run build command and verify manifest counts/hash update deterministically.

---

### Task 6: Add scoped coverage CLI filters

**Files:**
- Modify: `radar.py`
- Modify: `cli/map_locations.py`
- Modify: `db/listing_location_coverage.py`
- Modify: `tests/test_listing_location_coverage.py`
- Modify: `docs/dev_commands.md`

**Interfaces:**
- Produces CLI options `--city`, `--ward`, `--include-ward-alias`.

- [ ] **Step 1: Write red CLI parser and filtering tests**

```python
def test_map_location_coverage_accepts_city_ward_alias_filters():
    args = parse_args(["map-location-coverage", "--status", "unresolved", "--city", "THỦ DẦU MỘT", "--ward", "Phú Tân", "--include-ward-alias", "Phú Chánh"])
    assert args.city == "THỦ DẦU MỘT"
    assert args.ward == "Phú Tân"
    assert args.include_ward_alias == ["Phú Chánh"]
```

- [ ] **Step 2: Implement filters**

Filter loaded coverage rows in `cmd_map_location_coverage` using normalized city and ward aliases. Keep global behavior unchanged when filters are absent.

- [ ] **Step 3: Run coverage tests**

Run:

```powershell
& $py -X utf8 -m pytest --basetemp .pytest-tmp\run tests\test_listing_location_coverage.py -q
```

Expected: PASS.

---

### Task 7: Full verification, deploy, and production backfill

**Files:**
- All touched implementation, tests, docs, generated registry files.

**Interfaces:**
- Produces production Maps state where target `tab=all` Phú Tân rows no longer cluster only at `Theo trung tâm Phú Tân`.

- [ ] **Step 1: Run local verification**

Run:

```powershell
& $py -X utf8 -m pytest --basetemp .pytest-tmp\run tests\test_listing_map_context.py tests\test_listing_location_resolver.py tests\test_listing_location_registry.py tests\test_listing_location_backfill.py tests\test_listing_location_coverage.py tests\test_listing_map_service.py tests\test_listing_map_api.py -q
& $py -X utf8 -m py_compile config\listing_map.py services\listing_map_context.py services\listing_location_resolver.py scripts\build_listing_location_registry.py cli\map_locations.py radar.py
git diff --check -- <touched-files>
```

- [ ] **Step 2: Run local dry-run**

Run:

```powershell
& $py -X utf8 radar.py map-locations --full --dry-run
```

Record non-ward improvement for Phú Tân fixture.

- [ ] **Step 3: Commit and push scoped files**

Stage only files from this plan. Preserve unrelated dirty files.

- [ ] **Step 4: Deploy production**

Run:

```powershell
.\scripts\deploy_production.ps1
```

- [ ] **Step 5: Production dry-run, apply, smoke**

Run on VPS:

```bash
set -a; . /etc/radar-bds/radar.env; set +a
cd /opt/radar-bds/current
/opt/radar-bds/.venv/bin/python -X utf8 radar.py map-locations --full --dry-run
/opt/radar-bds/.venv/bin/python -X utf8 radar.py map-locations --full
curl -fsS 'http://127.0.0.1:5000/api/map-listings?mode=all' >/dev/null
```

Expected: dry-run/apply succeeds and `mode=all` returns HTTP 200.

