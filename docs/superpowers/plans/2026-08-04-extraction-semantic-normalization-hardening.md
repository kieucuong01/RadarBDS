# Extraction Semantic Normalization Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Radar BDS deterministically read production broker phrasing more accurately while preserving geometry tolerance, old-ward semantics, and fail-closed multi-lot behavior.

**Architecture:** Extend the existing pure extractors with bounded context removal, then make `normalize_record()` consume one reconciled measurement result and persist per-field measurement provenance. Reuse those extractors and the post-merger resolver in the read-only audit so null stored fields and road/dimension gaps become visible without creating broad false positives.

**Tech Stack:** Python 3.12, PostgreSQL, existing `cleansing.feature_extractor`, `cleansing.extraction_integrity`, `cleansing.normalizer`, `db.listings`, `pytest`.

## Global Constraints

- Keep regular geometry severe only above 40% and irregular/multi-side geometry severe only above 60%.
- Explicit total area beats frontage multiplied by depth.
- Do not add external LLM calls to crawl, normalization, reprocess, or valuation.
- Do not modify/delete raw listings, price history, images, dedup history, user data, `ai_deal_review`, or `ai_training_feedback`.
- Multi-lot posts remain intact and suppressed; do not synthesize child listings.
- Keep canonical DB wards on the old valuation ward; broad new wards are context only.
- Do not change valuation formulas, MOS policy, RBAC, redaction, publisher visibility, or public cache semantics.
- Every production behavior change follows RED-GREEN-REFACTOR.

---

### Task 1: Asking-price context and compact million notation

**Files:**
- Modify: `cleansing/feature_extractor.py`
- Test: `tests/test_feature_extractor.py`

**Interfaces:**
- Consumes: `extract_price(text: str) -> float | None`.
- Produces: the same interface with safe `950TR` support and removal of non-asking amounts.

- [ ] **Step 1: Add failing price regressions**

```python
def test_extract_price_handles_compact_million_and_non_asking_amounts():
    assert extract_price("GIÁ CHỈ 950TR còn thương lượng") == 0.95
    assert extract_price("Hơn 2.3xx tỷ, thanh toán 700 triệu nhận nhà") is None
    assert extract_price("Giá bán 2,35 tỷ, hỗ trợ vay 800 triệu") == 2.35
    assert extract_price("Chủ hạ giá 400tr chỉ còn 2tỷ2") == 2.2
```

- [ ] **Step 2: Run the new test and verify the `950TR` and down-payment assertions fail for the expected parser behavior**

```powershell
& $py -X utf8 -m pytest tests/test_feature_extractor.py -k compact_million -q
```

- [ ] **Step 3: Extend folded non-asking clause stripping and add bounded compact-million parsing**

Strip amounts attached to `dua truoc`, `thanh toan`, `tra truoc`, `coc`, `ho tro vay`, and `vay` before general million matching. Accept `N tr` only for `N >= 100` with asking-price context or a complete price-only clause. Preserve the existing `giam ... con ...` branch.

- [ ] **Step 4: Run the focused price tests and existing price regressions**

```powershell
& $py -X utf8 -m pytest tests/test_feature_extractor.py -k price -q
```

---

### Task 2: Canonical measurement pass and residential-area precedence

**Files:**
- Modify: `cleansing/feature_extractor.py`
- Modify: `cleansing/normalizer.py`
- Modify: `cleansing/extraction_integrity.py`
- Test: `tests/test_feature_extractor.py`
- Test: `tests/test_extraction_integrity.py`

**Interfaces:**
- Consumes: `parse_facebook_post(text)`, `reconcile_measurements(...)`, `extract_tho_cu(text, total_area)`.
- Produces: final `area_m2`, dimensions, and `tho_cu_m2` computed from one canonical total area.

- [ ] **Step 1: Add failing normalization regressions**

```python
def test_normalize_uses_final_area_for_full_tho_cu_after_road_width():
    rec = normalize_record({
        "source": "facebook",
        "url": "https://facebook.test/full-tho-cu-road-width",
        "title": "Đất 6x18 full thổ cư giá 1,5 tỷ",
        "description": "Đường bê tông 6m, ô tô thông",
    })
    assert rec["area_m2"] == 108
    assert rec["tho_cu_m2"] == 108
    assert rec["road_width_m"] == 6


def test_normalize_three_value_shorthand_keeps_residential_area():
    rec = normalize_record({
        "source": "facebook",
        "url": "https://facebook.test/three-value-tho-cu",
        "title": "Đất Hiệp An 4,1 x 25 x 50m thổ cư giá 1tỷ490",
        "description": "Phường Phú An mới, Hiệp An Bình Dương cũ",
    })
    assert rec["area_m2"] == 102.5
    assert rec["tho_cu_m2"] == 50
    assert rec["ward"] == "Hiệp An"
```

- [ ] **Step 2: Run the two tests and verify they fail on stale/provisional thổ-cư handling**

```powershell
& $py -X utf8 -m pytest tests/test_feature_extractor.py -k "final_area or three_value" -q
```

- [ ] **Step 3: Reconcile area first and extract residential area once with the final area**

Do not let `_fb_parsed['tho_cu_m2']` overwrite `extract_tho_cu(full_text, final_area_m2)`. Add an explicit three-value shorthand parser for `W x D x TC thổ cư`; the third value is residential area only when followed by `thổ cư`, `tc`, or `odt`.

- [ ] **Step 4: Verify measurement and geometry suites**

```powershell
& $py -X utf8 -m pytest tests/test_feature_extractor.py tests/test_extraction_integrity.py -q
```

---

### Task 3: Multi-lot, property, and road semantic context

**Files:**
- Modify: `cleansing/feature_extractor.py`
- Modify: `cleansing/normalizer.py`
- Test: `tests/test_feature_extractor.py`

**Interfaces:**
- Produces: bounded multi-offer detection, context-aware property classification, and valid road name/width extraction.

- [ ] **Step 1: Add failing semantic regressions**

```python
def test_multi_lot_detects_two_area_residential_groups_without_numbered_labels():
    assert is_multi_lot_listing(
        "Bán hai lô đất",
        "445m2 thổ cư 141m2 và 534m2 thổ cư 160m2, giá 3,5 tỷ/lô",
    )


def test_property_type_ignores_nearby_industrial_context():
    assert classify_property_type(
        "Nhà 1 trệt 1 lầu",
        "Gần khu công nghiệp, diện tích 100m2",
        100,
    ) == "nha_dat"
    assert classify_property_type(
        "Cần bán kho đang cho thuê",
        "Kho hiện hữu trên đất",
        320,
    ) == "kho_xuong"


def test_road_name_keeps_nguyen_tri_phuong_and_rejects_generic_prose():
    assert extract_road_name("Nhánh Nguyễn Tri Phương, P. Chánh Nghĩa") == "Nguyen Tri Phuong"
    assert extract_road_name("2 mặt tiền đường siêu phẩm cực rẻ") is None
```

- [ ] **Step 2: Run each new behavior and verify the expected failures**

```powershell
& $py -X utf8 -m pytest tests/test_feature_extractor.py -k "two_area_residential or industrial_context or nguyen_tri_phuong" -q
```

- [ ] **Step 3: Implement bounded context stripping and road validation**

Remove industrial proximity/potential-use clauses before `_is_kho_xuong_text()`. Preserve explicit existing warehouse/factory phrases. Replace the unconditional `phuong` road-name stop with administrative-location termination and reject generic road names that contain sales adjectives but no known road/code evidence.

- [ ] **Step 4: Run feature, dedup, and signal-quality regressions**

```powershell
& $py -X utf8 -m pytest tests/test_feature_extractor.py tests/test_dedup.py tests/test_signal_quality.py -q
```

---

### Task 4: Persist measurement provenance

**Files:**
- Modify: `cleansing/normalizer.py`
- Modify: `db/listings.py`
- Modify: `db/schema.py`
- Test: `tests/test_feature_extractor.py`
- Test: `tests/test_price_history.py`

**Interfaces:**
- Produces: `measurement_provenance` JSON text on normalized records and persisted listings.

- [ ] **Step 1: Add failing pure and PostgreSQL provenance tests**

```python
def test_normalize_marks_source_and_derived_dimension_provenance():
    rec = normalize_record({
        "source": "facebook",
        "url": "https://facebook.test/provenance",
        "title": "Đất Mỹ Phước 3 diện tích 100m2",
        "description": "Giá 2 tỷ",
    })
    assert rec["measurement_provenance"]["frontage_m"] == "derived_standard_lot"
    assert rec["measurement_provenance"]["depth_m"] == "derived_standard_lot"
```

The PostgreSQL test inserts/upserts the record, reloads `measurement_provenance`, and asserts the same literal mapping.

- [ ] **Step 2: Run tests and verify the missing field/column failures**

```powershell
& $py -X utf8 -m pytest tests/test_feature_extractor.py -k provenance -q
& $py -X utf8 -m pytest tests/test_price_history.py -k provenance -q
```

- [ ] **Step 3: Add schema migration and carry provenance through repository derivation**

Add `measurement_provenance TEXT NOT NULL DEFAULT '{}'`. When the normalizer or repository derives depth from area/frontage, set `depth_m=derived_area_frontage`; standard-lot inference sets both dimensions to `derived_standard_lot`; explicit source/text values remain distinct. JSON serialization uses stable sorted keys.

- [ ] **Step 4: Run schema/upsert regressions**

```powershell
& $py -X utf8 -m pytest tests/test_price_history.py tests/test_postgres_connection.py -q
```

---

### Task 5: Make the deterministic extraction audit complete and quieter

**Files:**
- Modify: `services/extraction_audit.py`
- Test: `tests/test_extraction_audit.py`

**Interfaces:**
- Produces: findings for strong expected values when stored values are null, including dimensions and road fields.

- [ ] **Step 1: Add failing audit regressions**

```python
def test_audit_reports_explicit_area_when_stored_area_is_null():
    audit = audit_listing_extraction({
        "title": "Đất 5x29,5 tổng 154m2",
        "description": "",
        "area_m2": None,
    })
    assert "area_m2" in audit["fields"]


def test_audit_covers_missing_dimensions_and_road_fields():
    audit = audit_listing_extraction({
        "title": "Đất 5x20, đường bê tông 4m",
        "description": "",
        "frontage_m": None,
        "depth_m": None,
        "road_width_m": None,
        "road_type": "unknown",
    })
    assert {"frontage_m", "depth_m", "road_width_m", "road_type"} <= set(audit["fields"])
```

- [ ] **Step 2: Run the new audit tests and verify missing-field assertions fail**

```powershell
& $py -X utf8 -m pytest tests/test_extraction_audit.py -q
```

- [ ] **Step 3: Add null-aware comparison and canonical ward resolution**

Use one helper for optional numeric comparison. Add frontage/depth/road width/type fields. Resolve old/new ward context with `resolve_post_merger_location()` before `match_ward()` and do not report broad-new-ward-only evidence as a canonical mismatch.

- [ ] **Step 4: Run audit and admin-quality regressions**

```powershell
& $py -X utf8 -m pytest tests/test_extraction_audit.py tests/test_admin_control_room.py -q
```

---

### Task 6: Documentation, full verification, and release

**Files:**
- Modify: `docs/daily_crawl_flow.md`
- Modify: `docs/dev_commands.md`
- Verify: all scoped source and test files.

**Interfaces:**
- Documents: one-pass measurement precedence, provenance values, audit coverage, and production reprocess gate.

- [ ] **Step 1: Update operational documentation with the deterministic behavior and commands**

Add these exact operational rules to `docs/daily_crawl_flow.md` and the corresponding commands to `docs/dev_commands.md`:

```text
- Normalize price, total area, dimensions, road width, and residential area from one text pass.
- Final residential area is evaluated against final canonical total area.
- measurement_provenance distinguishes structured/text evidence from derived dimensions.
- Multi-lot posts are retained but suppressed; no synthetic child listings are created.
- Regular/irregular geometry thresholds remain >40% and >60%.
```

Document the verification commands from Steps 2-4 and state that production requires a controlled full reprocess plus signal/listing read-model parity after deployment.

- [ ] **Step 2: Run syntax checks**

```powershell
& $py -X utf8 -m py_compile cleansing/feature_extractor.py cleansing/extraction_integrity.py cleansing/normalizer.py db/listings.py db/schema.py services/extraction_audit.py
```

- [ ] **Step 3: Run focused extraction/normalization/database suites**

```powershell
& $py -X utf8 -m pytest tests/test_feature_extractor.py tests/test_extraction_integrity.py tests/test_extraction_audit.py tests/test_price_history.py tests/test_dedup.py tests/test_lot_history.py tests/test_signal_quality.py tests/test_reprocess_review_hidden.py -q
```

- [ ] **Step 4: Run the full test suite and non-mutating local integrity report**

```powershell
& $py -X utf8 -m pytest tests -q
& $py -X utf8 radar.py integrity-report --json
```

- [ ] **Step 5: Review scope and release only if all gates are clean**

```powershell
git diff --check origin/main...HEAD
git status --short
git log --oneline origin/main..HEAD
```

Then rebase current `origin/main`, push the scoped branch, fast-forward/merge to `main`, run `scripts/deploy_production.ps1`, execute one controlled full production reprocess, refresh/compare signal and listing read models, and verify deployed SHA, systemd services/timers, APIs, cache headers, and zero parity differences.
