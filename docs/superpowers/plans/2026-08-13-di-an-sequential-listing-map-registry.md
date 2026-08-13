# Dĩ An Sequential Listing Map Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every active Dĩ An listing with trustworthy road or named-area evidence out of an inaccurate ward-center fallback, processing all seven legacy ward filters in descending production impact.

**Architecture:** Add a map-only explicit ward hint to the existing deterministic context, combine it with official 2025 consolidation scopes, and resolve against the existing pinned OSM registry before adding any curated point. Parser hardening removes price/area false positives; scoped aliases and forced aggregates connect genuine listing names to existing OSM geometry.

**Tech Stack:** Python 3.12, PostgreSQL, Flask, pinned OpenStreetMap JSON, static JSON registry, pytest, PowerShell, Browser Use.

## Global Constraints

- Process wards in this order: `Dĩ An`, `Đông Hòa`, `Tân Đông Hiệp`, `Bình An`, `Tân Bình`, `An Bình`, `Bình Thắng`.
- Preserve resolver priority `exact -> road -> landmark -> ward`.
- Never mutate `listings.ward`, canonical road fields, valuation, deduplication, feedback, or AI review.
- Use an explicit text ward only for map registry lookup; stored ward remains the filter and fallback identity.
- Reject `TL` after a price, dimensions, road widths, generic KDC prose, and advertising suffixes.
- Prefer pinned OSM geometry. Browser-derived points require unique public evidence, a bounded radius, provenance, and verification date.
- Every behavior change follows verified RED -> GREEN.
- Build registry artifacts twice with byte-identical hashes.
- Preserve unrelated `.playwright-cli/` and all `.local/` audit files outside Git.

---

### Task 1: Add safe Dĩ An ward hints and parser guards

**Files:**
- Modify: `services/listing_map_context.py`
- Modify: `services/listing_location_resolver.py`
- Test: `tests/test_listing_map_context.py`
- Test: `tests/test_listing_location_resolver.py`

**Interfaces:**
- Produces `MapLocationContext.ward_hint: str`.
- `resolve_listing_location()` consumes the hint only for road/landmark lookup scopes.

- [ ] **Step 1: Write failing literal context tests**

```python
def test_di_an_context_extracts_explicit_ward_hint_and_nguyen_thai_hoc():
    context = extract_map_location_context(
        "Nhà phường Dĩ An",
        "Gần đường Nguyễn Thái Học 150m",
    )
    assert context.ward_hint == "Dĩ An"
    assert context.nearby_road == "nguyen thai hoc"


def test_di_an_price_tl_area_is_not_a_road():
    context = extract_map_location_context(
        "Đất 6,9 tỷ TL - 108,6m2",
        "Mặt tiền đối diện sân vận động",
    )
    assert context.direct_road == ""
    assert context.nearby_road == ""
```

- [ ] **Step 2: Run the two tests and verify RED**

Run the exact tests with Python 3.12. Expected failures: missing `ward_hint`, `Nguyễn Thái Học` incorrectly normalizes to `nguyen thai binh`, or `TL 108` is accepted.

- [ ] **Step 3: Add the minimal parser behavior**

Add `ward_hint` with a default empty string, extract only explicit Dĩ An-area ward phrases, preserve `nguyen thai hoc`, and reject `TL <area>` when surrounding text proves price negotiation/area rather than a named provincial road.

- [ ] **Step 4: Add resolver tests for lookup-only hint precedence**

Use a controlled `LocationRegistry` with the same road token in the stored and hinted wards. Assert the hinted ward supplies the resolved point while `location_key` still contains the stored listing ward. Assert a missing hint falls back to the stored ward.

- [ ] **Step 5: Run focused context/resolver tests GREEN**

Run all `test_listing_map_context.py` and the new resolver tests; no existing Thủ Dầu Một/Bến Cát behavior may regress.

### Task 2: Complete phường Dĩ An

**Files:**
- Modify: `config/listing_map.py`
- Modify: `config/listing_map_location_sources.json`
- Modify: `config/listing_map_location_overrides.json`
- Modify as tests require: `services/listing_map_context.py`
- Test: `tests/test_listing_location_resolver.py`, `tests/test_listing_location_registry.py`

**Interfaces:**
- Consumes 252 production ward-center rows; 154 currently contain a parser road and 12 contain a landmark clue.
- Produces resolved groups for genuine Võ Thị Sáu, Nguyễn Thái Học, ĐT743 variants, Phan Bội Châu, Trần Quang Khải, Nguyễn Du, Nguyễn Tri Phương, QL1K, Hai Bà Trưng, Đông Minh, and accepted named areas.

- [ ] Verify actual listing text for every road family with count at least two; classify contaminated candidates separately.
- [ ] Write RED resolver tests for each accepted alias and for aggregate Nguyễn Du/numbered roads where OSM has multiple fragments.
- [ ] Add official consolidation scope from new Dĩ An to legacy An Bình and the relevant Tân Đông Hiệp scope without opening unrelated Đông Hòa roads blindly.
- [ ] Add only aliases/aggregates or evidence-backed overrides that make the RED tests pass.
- [ ] Record projected Dĩ An `ward -> road/landmark` counts before continuing.

### Task 3: Complete phường Đông Hòa

**Interfaces:**
- Consumes 160 ward-center rows; 85 contain road candidates and 15 contain landmark candidates.
- Produces QL1K, Nguyễn Đình Chiểu, Hai Bà Trưng, GS roads, D1/D3, Võ Thị Sáu, Nguyễn Công Hoan, ĐT743 and accepted Bình Nguyên/Đông Tác/TĐC Đông Hòa groups.

- [ ] Verify and RED-test `QL1K`/`Quốc lộ 1K` compact forms and explicit `GS1`, `GS12`, `GS14` grid names.
- [ ] Configure official new Đông Hòa lookup scopes for legacy Bình An and Bình Thắng.
- [ ] Aggregate only proven same-road OSM fragments and add scoped aliases for missing `Đường` prefixes.
- [ ] Reject `TL 90/41/77` price-area artifacts and prose-contaminated road names.
- [ ] Record projected Đông Hòa before/after counts.

### Task 4: Complete phường Tân Đông Hiệp

**Interfaces:**
- Consumes 109 ward-center rows; 37 contain road candidates and 20 contain named-area candidates.
- Produces ĐT743 variants, Mỹ Phước–Tân Vạn, Lê Thị Út, Lê Hồng Phong, Phạm Văn Diêu, Hồ Lang, D12, and accepted Đông An/Icon Central/Hồ Lang/Tứ Hải areas.

- [ ] Add official map lookup scope from new Tân Đông Hiệp to legacy Tân Bình.
- [ ] Write RED tests for accepted road aliases and named landmarks using literal expected location-key slugs.
- [ ] Reject `TL 60/87/150/58/109` price-area artifacts and generic `KDC ngay...` prose.
- [ ] Prefer existing OSM roads; use browser evidence only for a named area absent from the pinned registry.
- [ ] Record projected Tân Đông Hiệp before/after counts.

### Task 5: Complete phường Bình An

**Interfaces:**
- Consumes 68 ward-center rows; 58 contain road candidates and eight contain landmark candidates.
- Produces QL1K, ĐT743A, Bình Thung, Vành đai 3, numbered roads, KDC Phúc Đạt, and Bình Nguyên where evidence is unique.

- [ ] RED-test canonical QL1K and ĐT743A aliases plus the correct Bình An OSM entries.
- [ ] Disambiguate numbered roads with a named-area clue; leave bare duplicated road numbers at ward precision.
- [ ] Reject price-like `quốc lộ 7 tỷ` and generic `TĐC Lò Ô kinh doanh...` extraction.
- [ ] Record projected Bình An before/after counts.

### Task 6: Complete phường Tân Bình

**Interfaces:**
- Consumes 61 ward-center rows; 26 contain road candidates and six contain landmarks.
- Produces Bùi Thị Xuân, Huỳnh Thị Tuổi, Nguyễn Thị Tuổi, Liên Huyện, Phạm Văn Diêu, Mỹ Phước–Tân Vạn, Lê Hồng Phong and accepted Biconsi/Hoàng Nam areas.

- [ ] RED-test clipping of `Huỳnh Thị Tuổi ...` suffixes and distinguish it from Nguyễn Thị Tuổi.
- [ ] Resolve only explicit `N16` with a supporting scope; do not infer other N roads from dimensions.
- [ ] Reject `đang trải nhựa`, generic KDC, electrical-substation prose, and KCN distance-only mentions.
- [ ] Record projected Tân Bình before/after counts.

### Task 7: Complete An Bình and Bình Thắng

**Interfaces:**
- Consumes 11 An Bình and five Bình Thắng ward-center rows.
- Produces only verified QL1K/ĐT743/Trần Đại Nghĩa/ĐT43 and 30 Tháng 4/ĐT743A matches that belong to the respective scope.

- [ ] Inspect every one of the 16 remaining rows because the batch is bounded.
- [ ] RED-test each accepted road and reject wrong-ward text such as a listing explicitly located in Linh Xuân or Lái Thiêu.
- [ ] Leave `DT 387` at ward precision unless the text explicitly proves it is a road rather than an area value.
- [ ] Record both projected before/after counts.

### Task 8: Deterministic build, production release, and seven-ward proof

**Files:**
- Bump: `config/listing_map.py`, source/override resolver versions
- Regenerate: `static/maps/listing-locations/ward-centers.json`, `road-centers.json`, `landmark-centers.json`, `manifest.json`

**Interfaces:**
- Produces one reversible Dĩ An resolver release and exact production evidence.

- [ ] Build the four artifacts twice from pinned OSM v4 and compare full SHA-256 values.
- [ ] Run `test_listing_location_registry.py`, `test_listing_map_context.py`, `test_listing_location_resolver.py`, `test_listing_location_backfill.py`, and `test_listing_location_coverage.py`.
- [ ] Run Python compilation, `git diff --check`, and local full map-location dry-run.
- [ ] Commit only scoped files, rebase safely if origin moves, rerun all Maps tests, push `main`, and deploy the exact SHA.
- [ ] Run production full dry-run, inspect projected per-ward moves, apply, then require a second dry-run with `updated=0`.
- [ ] Verify exact local/origin/VPS SHA, service active, origin/public HTTP 200, registry resolver version, and Browser Use Maps rendering for all seven ward filters.
