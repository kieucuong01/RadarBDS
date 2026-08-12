# Thu Dau Mot Sequential Listing Map Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit every legacy ward in Thu Dau Mot in deterministic order and move every current ward-center listing that contains a trustworthy road reference onto an OSM or evidence-backed static road marker.

**Architecture:** A production read-only audit selects only active rows whose current derived precision is `ward`, runs the map-only parser on the server, and exports normalized road aggregates without listing text. Each ward batch separates parser defects, existing-but-ambiguous OSM rows, missing OSM rows, and invalid marketing/dimension tokens. Accepted coordinates are stored only in the versioned map override registry; canonical listing fields and valuation data remain unchanged.

**Tech Stack:** Python 3.12, PostgreSQL, OpenStreetMap pinned JSON, Google Maps public browser/embed evidence, static JSON registry, pytest, PowerShell.

## Global Constraints

- Process wards in this order: `Tan An`, `Hiep An`, `Tuong Binh Hiep`, `Dinh Hoa`, `Chanh My`, `Phu My`, `Phu Cuong`, `Phu Hoa`, `Phu Loi`, `Hiep Thanh`, `Chanh Nghia`, `Phu Tan`, `Phu Tho`, `Hoa Phu`.
- The baseline for a ward is the current production `listing_map_locations.location_precision='ward'`, not historical coverage rows.
- Never export production title, description, phone, seller, or source URL during an audit. Export normalized candidates, counts, and at most 12 sample listing IDs.
- Prefer clipped OSM geometry. Use a static override only when public evidence proves the road and a bounded point/radius can be justified.
- A road without exact geometry may use a nearby verified road, landmark, registered address, or official project scope as a representative point with an honest radius of 650-1800 metres.
- Do not write map evidence into canonical `listings`, valuation, deduplication, human-feedback, or AI-review fields.
- Reject dimensions such as `DT: 100m2`, road widths such as `duong 5m`, school names, and marketing prose as road candidates.
- Every parser behavior change follows RED -> GREEN. Generated registry artifacts must be byte-stable across two builds.
- Release order is tests -> deterministic build -> production dry-run -> commit -> push -> deploy -> production apply -> API/browser verification.

---

### Task 1: Establish the per-ward production audit contract

**Files:**
- Verify: `db/listing_map_locations.py`
- Verify: `services/listing_map_context.py`
- Runtime only: production read-only audit output

**Interfaces:**
- Consumes current active listings joined to `listing_map_locations` where precision is `ward`.
- Produces only `ward_precision_total`, normalized road groups, counts, relations, and bounded sample IDs.

- [ ] **Step 1: Query the current ward marker rows**

Run the server-side audit with `ward='Tan An'`. It must use the same active-row guards as `iter_location_candidates`: `probably_sold=0`, `is_blacklisted=0`, and `review_hidden=0`.

- [ ] **Step 2: Record a literal baseline**

Expected initial Tân An evidence from 2026-08-12:

```text
ward precision total: 584
road-bearing rows already detected by parser: 138
largest valid/mixed groups: DX140 14, Tran Binh Trong 14, Dai lo Binh Duong 11,
DX120 10, Duong so 5 9, Duong so 2 8, Duong so 3 7, Duong so 1 6, DX135 5
```

- [ ] **Step 3: Classify each group**

Classify as exactly one of `existing_osm_ambiguous`, `missing_osm`, `parser_false_positive`, or `evidence_backed_override`. Do not add a registry point for `parser_false_positive`.

---

### Task 2: Remove Tân An parser false positives

**Files:**
- Modify: `tests/test_listing_map_context.py`
- Modify: `services/listing_map_context.py`

**Interfaces:**
- Consumes `extract_map_location_context(title, description, stored_road_name)`.
- Produces no road for school-name, area/dimension, unfinished-road-description, and road-surface phrases.

- [ ] **Step 1: Add failing literal tests**

```python
def test_tan_an_school_and_dimensions_are_not_roads():
    assert extract_map_location_context("Gan truong THCS Tran Binh Trong", "").direct_road == ""
    assert extract_map_location_context("Dat dep", "DT: 100m2").direct_road == ""
    assert extract_map_location_context("Dat dep", "DT 2062m2").direct_road == ""
    assert extract_map_location_context("Duong DX nhua 5m", "").direct_road == ""


def test_explicit_binh_duong_provincial_road_remains_a_road():
    assert extract_map_location_context("Mat tien duong DT 741", "").direct_road == "dt 741"


def test_tan_an_landmark_stops_before_city_copy():
    context = extract_map_location_context("TDC Tan An Thu Dau Mot Binh Duong", "")
    assert context.landmark == "tdc tan an"
```

- [ ] **Step 2: Run RED**

```powershell
& $py -X utf8 -m pytest tests/test_listing_map_context.py -q
```

Expected: the new assertions fail against v25.

- [ ] **Step 3: Implement the minimum parser guards**

Stop landmarks at city/new-address copy; require a numeric suffix for `DX/DB/DH/...` road-code candidates; accept bare `DT` only for the Bình Dương provincial-road range or when preceded by the explicit word `duong`; stop school/property/marketing terms before generic person-name matching.

- [ ] **Step 4: Run GREEN**

Run `tests/test_listing_map_context.py` plus resolver regressions and confirm all pass.

---

### Task 3: Add evidence-backed Tân An landmark and roads

**Files:**
- Modify: `tests/test_listing_location_registry.py`
- Modify: `tests/test_listing_location_resolver.py`
- Modify: `config/listing_map_location_overrides.json`
- Modify: `config/listing_map.py`
- Regenerate: `static/maps/listing-locations/*.json`

**Interfaces:**
- Produces resolver version `osm-binh-duong-20260807-v26`.
- Produces a `TDC Tan An` landmark and road entries for the accepted Tân An batch.

- [ ] **Step 1: Add failing registry/resolver tests**

Assert that Tân An resolves `DX140`, `DX120`, `DX135`, `DX141`, `DX108`, `DX117`, `DX109`, `Dai lo Binh Duong`, and numbered roads `1/2/3/5/18` to `precision='road'`. Assert `TDC Tan An Thu Dau Mot Binh Duong` resolves to the Tân An landmark when it has no road.

- [ ] **Step 2: Run RED against v25**

Expected: all newly accepted missing-road/landmark cases fail or fall back to `ward`.

- [ ] **Step 3: Add override evidence**

Use these literal bounded anchors:

```text
TDC Tan An / numbered roads / Dai lo Binh Duong: 11.0186542, 106.6271991
DX140 (Cho Ben The vicinity):                11.0208579, 106.6177602
DX120 (Huynh Thi Hieu vicinity):             11.0300017, 106.6178385
DX141 exact public address:                  11.0199517, 106.6174373
DX117 between Phan Dang Luu and Le Chi Dan:  11.0227519, 106.6242868
```

Use larger radii for DX135/DX108/DX109 where public evidence proves the named road but only a nearby ward/road anchor is available.

- [ ] **Step 4: Bump v26 and build twice**

Run `scripts/build_listing_location_registry.py` twice from pinned OSM v4 and compare SHA-256 of manifest, roads, landmarks, and wards.

- [ ] **Step 5: Run GREEN**

Run registry, resolver, context, backfill, coverage, API, service, JS, UI, and automation-doc tests.

---

### Task 4: Measure Tân An production improvement and release

**Files:**
- Commit only the scoped parser, tests, config, plan, and generated artifacts.

**Interfaces:**
- Produces a production backfill using v26 and a new current ward-center baseline.

- [ ] **Step 1: Run local syntax/tests and `git diff --check`**
- [ ] **Step 2: Run production `map-locations --full --dry-run` after deployable artifacts are ready**
- [ ] **Step 3: Commit and push `main`, then deploy with `scripts/deploy_production.ps1`**
- [ ] **Step 4: Run production dry-run again, apply full backfill, and rerun the safe Tân An ward-center audit**
- [ ] **Step 5: Verify `/api/map-listings?mode=all` and the Tân An Maps modal in a browser**

The acceptance result must report the exact number moved from `ward` to `road/landmark`; a lower ward count is improvement, while a false-positive road or out-of-ward coordinate is a failed batch.

---

### Task 5: Repeat the same audited cycle for the remaining wards

**Files:**
- Modify only the parser/aliases/override rows required by the current ward.
- Regenerate static registry artifacts for every accepted batch.

**Interfaces:**
- Consumes the post-release baseline from the preceding ward.
- Produces one measured, reversible resolver version per accepted ward batch.

- [ ] **Step 1: Process Hiep An through Hoa Phu in the declared order**
- [ ] **Step 2: For every ward, save aggregate baseline and post-apply counts outside git**
- [ ] **Step 3: Keep ambiguous candidates quarantined with their deterministic reason**
- [ ] **Step 4: Mark the full goal complete only after all 14 ward audits have current production evidence and no trustworthy road-bearing ward fallback remains**
