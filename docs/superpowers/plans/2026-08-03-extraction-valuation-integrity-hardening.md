# Extraction-to-Valuation Integrity Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Radar BDS automatically reconcile trustworthy price/area evidence, tolerate irregular-lot geometry, suppress unresolved contradictions, and publish traceable main/shadow valuations as one atomic snapshot.

**Architecture:** Add a deterministic `cleansing.extraction_integrity` policy module shared by normalization, valuation quality gating, and read-only audit. Reorder reprocess prerequisites ahead of model fitting, then replace main/shadow valuations and listing outlier state in one PostgreSQL transaction with crawl/model provenance. Keep the current main valuation algorithm and all public signal semantics unchanged.

**Tech Stack:** Python 3.12, Flask CLI router, PostgreSQL through `db.connection.get_conn()`, `pytest`, existing deterministic extractors and valuation engines.

## Global Constraints

- Do not add external LLM calls to crawl, normalization, reprocess, or valuation.
- Do not modify or delete `raw_listings`, user data, price history, dedup history, `ai_deal_review`, or `ai_training_feedback`.
- AI/Claude verdicts stay only in `ai_deal_review`; do not create human labels.
- An explicit total area wins over `frontage_m * depth_m`.
- Regular geometry suppresses only above 40%; irregular or multi-side geometry suppresses only above 60%.
- Missing area may be inferred from one valid regular dimension pair, never from irregular or multi-lot geometry.
- `price_per_m2` is derived from final `price_ty` and `area_m2` whenever both exist.
- Multi-lot posts remain intact and are suppressed; do not synthesize child listings.
- The current main model, MOS thresholds, RBAC/redaction, source visibility rules, and signal read-model semantics remain unchanged.
- `low_segment_confidence` remains warning-only.
- Public dataset/cache publication happens only after a successful valuation transaction.
- Start execution in an isolated `codex/` worktree after using `superpowers:using-git-worktrees`.
- Follow RED-GREEN-REFACTOR: every production behavior change needs a focused failing test first.

## File Map

- Create `cleansing/extraction_integrity.py`: pure measurement and geometry policy; no DB or crawler imports.
- Create `tests/test_extraction_integrity.py`: unit contract for adaptive thresholds and reconciliation.
- Modify `cleansing/normalizer.py`: call the shared resolver once and remove the 15% dimension overwrite.
- Modify `cleansing/feature_extractor.py`: recognize bounded numeric multi-lot phrases.
- Modify `db/listings.py`: persist deterministic extraction flags, the supplied crawl run, and canonical unit price.
- Modify `cleansing/reprocess.py`: shared quality flags, prerequisite ordering, explicit conversion failure, and atomic snapshot save.
- Modify `analytics/valuation.py`: expose main model identity and carry optional crawl provenance in `Listing`.
- Modify `db/schema.py`: add `valuation_results.model_run_id` and its migration/index.
- Modify `services/extraction_audit.py`: share adaptive geometry semantics.
- Modify `services/signal_quality.py`: suppress unresolved price/area inconsistency.
- Create `services/extraction_integrity_report.py`: non-mutating aggregate comparison.
- Modify `cli/system.py` and `radar.py`: expose `integrity-report`.
- Modify `docs/daily_crawl_flow.md` and `docs/dev_commands.md`: document order, gate, and verification commands.

---

### Task 1: Adaptive geometry policy

**Files:**
- Create: `cleansing/extraction_integrity.py`
- Create: `tests/test_extraction_integrity.py`

**Interfaces:**
- Produces: `geometry_difference_ratio(reported_area, frontage_m, depth_m) -> float | None`
- Produces: `is_irregular_geometry(text: str, *, dimension_pair_count: int = 1) -> bool`
- Produces: `severe_geometry_conflict(text, reported_area, frontage_m, depth_m, *, dimension_pair_count=1) -> bool`
- Constants: `REGULAR_GEOMETRY_SEVERE_RATIO = 0.40`, `IRREGULAR_GEOMETRY_SEVERE_RATIO = 0.60`

- [ ] **Step 1: Write failing geometry tests**

```python
import pytest

from cleansing.extraction_integrity import (
    geometry_difference_ratio,
    is_irregular_geometry,
    severe_geometry_conflict,
)


@pytest.mark.parametrize('reported,frontage,depth,expected', [
    (100.0, 5.0, 20.0, 0.0),
    (100.0, 5.0, 30.0, pytest.approx(1 / 3)),
    (150.0, 5.0, 20.0, pytest.approx(1 / 3)),
])
def test_geometry_difference_is_symmetric(reported, frontage, depth, expected):
    assert geometry_difference_ratio(reported, frontage, depth) == expected


def test_regular_geometry_suppresses_only_above_forty_percent():
    assert not severe_geometry_conflict('Dat vuong dep', 100, 5, 33.333)
    assert severe_geometry_conflict('Dat vuong dep', 100, 5, 34)


@pytest.mark.parametrize('cue', ['lô xéo hậu', 'đất nở hậu', 'hình thang', 'thắt hậu'])
def test_irregular_geometry_suppresses_only_above_sixty_percent(cue):
    assert is_irregular_geometry(cue)
    assert not severe_geometry_conflict(cue, 100, 5, 50)
    assert severe_geometry_conflict(cue, 100, 5, 51)


def test_multiple_dimension_pairs_use_irregular_threshold():
    assert not severe_geometry_conflict(
        'ngang trước 5m ngang sau 7m', 100, 5, 50, dimension_pair_count=2
    )
```

- [ ] **Step 2: Run the tests and observe the missing-module failure**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests/test_extraction_integrity.py -q
```

Expected: collection fails because `cleansing.extraction_integrity` does not exist.

- [ ] **Step 3: Implement the pure geometry helpers**

```python
from __future__ import annotations

import re
import unicodedata

REGULAR_GEOMETRY_SEVERE_RATIO = 0.40
IRREGULAR_GEOMETRY_SEVERE_RATIO = 0.60

_IRREGULAR_CUES = (
    'xeo', 'xeo hau', 'no hau', 'thop hau', 'that hau',
    'hinh thang', 'tam giac', 'hai mat tien',
)


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fold(text: str) -> str:
    folded = unicodedata.normalize('NFD', text or '')
    folded = ''.join(ch for ch in folded if unicodedata.category(ch) != 'Mn')
    folded = folded.lower().replace('đ', 'd')
    return re.sub(r'\s+', ' ', folded).strip()


def geometry_difference_ratio(reported_area, frontage_m, depth_m):
    area, frontage, depth = map(_number, (reported_area, frontage_m, depth_m))
    if area is None or frontage is None or depth is None:
        return None
    if area <= 0 or not (2 <= frontage <= 50 and 5 <= depth <= 500):
        return None
    rectangular_area = frontage * depth
    return abs(area - rectangular_area) / max(area, rectangular_area)


def is_irregular_geometry(text: str, *, dimension_pair_count: int = 1) -> bool:
    folded = _fold(text)
    repeated_sides = (
        len(re.findall(r'\bngang\b', folded)) > 1
        or len(re.findall(r'\b(?:dai|sau)\b', folded)) > 1
    )
    return (
        dimension_pair_count > 1
        or repeated_sides
        or any(cue in folded for cue in _IRREGULAR_CUES)
    )


def severe_geometry_conflict(
    text, reported_area, frontage_m, depth_m, *, dimension_pair_count=1
):
    ratio = geometry_difference_ratio(reported_area, frontage_m, depth_m)
    if ratio is None:
        return False
    threshold = (
        IRREGULAR_GEOMETRY_SEVERE_RATIO
        if is_irregular_geometry(text, dimension_pair_count=dimension_pair_count)
        else REGULAR_GEOMETRY_SEVERE_RATIO
    )
    return ratio > threshold
```

- [ ] **Step 4: Run the focused tests and confirm green**

Run the Task 1 pytest command. Expected: all tests pass.

- [ ] **Step 5: Commit the geometry policy**

```powershell
git add cleansing/extraction_integrity.py tests/test_extraction_integrity.py
git commit -m 'feat: add adaptive lot geometry policy'
```

---

### Task 2: Deterministic measurement reconciliation and normalizer wiring

**Files:**
- Modify: `cleansing/extraction_integrity.py`
- Modify: `cleansing/normalizer.py:210-262, 695-819`
- Modify: `db/schema.py:40-120, 1270-1330`
- Modify: `db/listings.py:268-540`
- Modify: `tests/test_extraction_integrity.py`
- Modify: `tests/test_feature_extractor.py:344-500`
- Modify: `tests/test_price_history.py`

**Interfaces:**
- Produces: immutable `MeasurementIntegrity(price_ty, area_m2, tho_cu_m2, price_per_m2, flags, repairs)`
- Produces: `has_declared_total_area(text: str) -> bool`
- Produces: `reconcile_measurements(*, text, structured_price_ty, structured_area_m2, source_price_per_m2, parsed_price_ty, parsed_area_m2, parsed_tho_cu_m2, frontage_m, depth_m, parsed_area_is_declared_total, ambiguous_price, multi_lot) -> MeasurementIntegrity`
- Consumes: parsed candidates from `parse_facebook_post()` and structured source values from `normalize_record()`
- Produces: `listings.extraction_quality_flags`, overwritten by each deterministic reprocess and never sourced from human/AI labels.

- [ ] **Step 1: Add failing resolver tests**

```python
from cleansing.extraction_integrity import reconcile_measurements


def test_explicit_total_replaces_structured_residential_area():
    result = reconcile_measurements(
        text='DT 85m2, thổ cư 60m2, giá 1,7 tỷ',
        structured_price_ty=1.7,
        structured_area_m2=60,
        source_price_per_m2=20,
        parsed_price_ty=1.7,
        parsed_area_m2=85,
        parsed_tho_cu_m2=60,
        frontage_m=None,
        depth_m=None,
        parsed_area_is_declared_total=True,
        ambiguous_price=False,
        multi_lot=False,
    )
    assert result.area_m2 == 85
    assert result.tho_cu_m2 == 60
    assert result.price_per_m2 == 20
    assert result.repairs == ('structured_area_was_residential_area',)


def test_explicit_area_is_not_overwritten_by_dimensions_at_thirty_percent():
    result = reconcile_measurements(
        text='Diện tích 100m2, ngang 5 dài 28.5',
        structured_price_ty=2,
        structured_area_m2=100,
        source_price_per_m2=14,
        parsed_price_ty=2,
        parsed_area_m2=100,
        parsed_tho_cu_m2=None,
        frontage_m=5,
        depth_m=28.5,
        parsed_area_is_declared_total=True,
        ambiguous_price=False,
        multi_lot=False,
    )
    assert result.area_m2 == 100
    assert result.price_per_m2 == 20
    assert result.flags == ()


def test_irregular_missing_area_is_not_inferred_from_dimensions():
    result = reconcile_measurements(
        text='Lô xéo hậu ngang 5 dài 30 giá 2 tỷ',
        structured_price_ty=2,
        structured_area_m2=None,
        source_price_per_m2=None,
        parsed_price_ty=2,
        parsed_area_m2=150,
        parsed_tho_cu_m2=None,
        frontage_m=5,
        depth_m=30,
        parsed_area_is_declared_total=False,
        ambiguous_price=False,
        multi_lot=False,
    )
    assert result.area_m2 is None
    assert result.price_per_m2 is None


def test_unverified_structured_ppm_conflict_fails_closed_but_recomputes_ppm():
    result = reconcile_measurements(
        text='Bán đất giá tốt',
        structured_price_ty=2,
        structured_area_m2=100,
        source_price_per_m2=10,
        parsed_price_ty=None,
        parsed_area_m2=None,
        parsed_tho_cu_m2=None,
        frontage_m=None,
        depth_m=None,
        parsed_area_is_declared_total=False,
        ambiguous_price=False,
        multi_lot=False,
    )
    assert result.price_per_m2 == 20
    assert 'price_area_inconsistent' in result.flags
```

- [ ] **Step 2: Run resolver tests and verify they fail for the missing API**

Run Task 1's pytest command. Expected: import or attribute failure for `reconcile_measurements`.

- [ ] **Step 3: Add the immutable result and reconciliation rules**

Implement this exact public shape in `cleansing/extraction_integrity.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class MeasurementIntegrity:
    price_ty: float | None
    area_m2: float | None
    tho_cu_m2: float | None
    price_per_m2: float | None
    flags: tuple[str, ...] = ()
    repairs: tuple[str, ...] = ()


def has_declared_total_area(text: str) -> bool:
    folded = _fold(text)
    return bool(re.search(
        r'\b(?:tong\s*(?:dt|dien tich)|dt(?:\s*dat)?|dien tich(?:\s*dat)?)\b'
        r'[^\n.;]{0,24}?\d+(?:[,.]\d+)?\s*(?:m[²2]|mv|met vuong)\b',
        folded,
    ))
```

`reconcile_measurements()` must implement these ordered decisions:

```python
price = _number(structured_price_ty)
parsed_price = _number(parsed_price_ty)
area = _number(structured_area_m2)
parsed_area = _number(parsed_area_m2)
tho_cu = _number(parsed_tho_cu_m2)
source_ppm = _number(source_price_per_m2)
flags, repairs = [], []

if ambiguous_price:
    price = None
elif parsed_price and (price is None or abs(parsed_price - price) / max(parsed_price, price) > 0.15):
    price = parsed_price
    repairs.append('clear_text_price')

structured_is_tho_cu = (
    area is not None and tho_cu is not None
    and abs(area - tho_cu) <= max(1.0, tho_cu * 0.03)
)
if parsed_area_is_declared_total and parsed_area:
    if structured_is_tho_cu and parsed_area > area:
        repairs.append('structured_area_was_residential_area')
    area = parsed_area
elif (
    structured_is_tho_cu and parsed_area and parsed_area > area * 1.10
    and not multi_lot and not is_irregular_geometry(text)
):
    area = parsed_area
    repairs.append('structured_area_was_residential_area')
elif area is None and parsed_area and not multi_lot and not is_irregular_geometry(text):
    area = parsed_area
    repairs.append('area_from_dimensions')

if severe_geometry_conflict(text, area, frontage_m, depth_m):
    flags.append('area_dimension_conflict')

if price is None and not ambiguous_price and source_ppm and area and not multi_lot:
    price = round(source_ppm * area / 1000, 4)
    repairs.append('price_from_unit_price')

derived_ppm = round(price * 1000 / area, 3) if price and area and area > 0 else None
if derived_ppm and source_ppm:
    mismatch = abs(derived_ppm - source_ppm) / max(derived_ppm, source_ppm)
    has_text_support = bool(parsed_price and (parsed_area_is_declared_total or parsed_area))
    if mismatch > 0.20 and not has_text_support:
        flags.append('price_area_inconsistent')

return MeasurementIntegrity(
    price_ty=price,
    area_m2=area,
    tho_cu_m2=tho_cu,
    price_per_m2=derived_ppm,
    flags=tuple(sorted(set(flags))),
    repairs=tuple(repairs),
)
```

- [ ] **Step 4: Replace normalizer's 15% overwrite with one resolver call**

In `normalize_record()`:

- retain source/text candidate extraction;
- move `_has_reported_total_area_marker()` into the shared module as `has_declared_total_area()`;
- delete `_dimension_area_override()` and all call sites;
- call `reconcile_measurements()` before property classification;
- assign the returned canonical fields;
- attach `_integrity_repairs` for the read-only report and persist `extraction_quality_flags` as a comma-separated deterministic value.

The call site must pass explicit source dimensions extracted from text, before `_infer_depth_from_area_frontage()` creates any display fallback:

```python
integrity = reconcile_measurements(
    text=_parse_text,
    structured_price_ty=price_ty,
    structured_area_m2=area_m2,
    source_price_per_m2=price_per_m2,
    parsed_price_ty=_fb_parsed.get('price_total'),
    parsed_area_m2=_fb_parsed.get('area_m2'),
    parsed_tho_cu_m2=_fb_parsed.get('tho_cu_m2'),
    frontage_m=parsed_frontage,
    depth_m=parsed_depth,
    parsed_area_is_declared_total=has_declared_total_area(_parse_text),
    ambiguous_price=_has_ambiguous_masked_price,
    multi_lot=is_multi_lot_listing(title, description),
)
price_ty = integrity.price_ty
area_m2 = integrity.area_m2
price_per_m2 = integrity.price_per_m2
extraction_quality_flags = ','.join(integrity.flags)
```

- [ ] **Step 5: Persist deterministic extraction flags on listings**

Add the nullable/default-empty column to the `listings` DDL and idempotent migration:

```sql
extraction_quality_flags TEXT NOT NULL DEFAULT '',
```

```python
(
    'extraction_quality_flags',
    "ALTER TABLE listings ADD COLUMN extraction_quality_flags TEXT NOT NULL DEFAULT ''",
)
```

Add the column to both `upsert_listing()` insert and update SQL. Updates must assign the new normalized value, including an empty string, so a later clean reprocess clears a stale flag:

```sql
extraction_quality_flags = :extraction_quality_flags
```

Use `rec.get('extraction_quality_flags') or ''` in both parameter dictionaries.

- [ ] **Step 6: Add normalizer and persistence regressions, then run red and green**

Add focused cases to `tests/test_feature_extractor.py` for:

```python
def test_normalizer_keeps_explicit_area_for_skewed_lot():
    rec = normalize_record({
        'source': 'facebook',
        'external_id': 'skewed-lot',
        'url': 'https://facebook.test/skewed-lot',
        'default_area': 'Thủ Dầu Một',
        'title': 'Bán đất diện tích 100m2 giá 2 tỷ',
        'description': 'Lô xéo hậu, ngang 5m dài 40m',
    })
    assert rec['area_m2'] == 100
    assert rec['price_per_m2'] == 20


def test_normalizer_recomputes_stale_structured_ppm():
    rec = normalize_record({
        'source': 'guland',
        'source_id': 'canonical-ppm',
        'url': 'https://guland.vn/canonical-ppm',
        'title': 'Đất 85m2 giá 1,7 tỷ',
        'description': 'Diện tích đất 85m2, thổ cư 60m2',
        'price_ty': 1.7,
        'area_m2': 60,
        'price_per_m2': 20,
    })
    assert rec['area_m2'] == 85
    assert rec['tho_cu_m2'] == 60
    assert rec['price_per_m2'] == 20
```

Add to `PriceHistoryTest`:

```python
def test_upsert_listing_replaces_deterministic_extraction_flags(self):
    from db.connection import get_conn
    from db.listings import upsert_listing

    first = self._rec()
    first['extraction_quality_flags'] = 'price_area_inconsistent'
    listing_id, _ = upsert_listing(first, crawl_run_id=1)

    second = self._rec()
    second['extraction_quality_flags'] = ''
    upsert_listing(second, crawl_run_id=2)

    with get_conn() as conn:
        row = conn.execute(
            'SELECT extraction_quality_flags FROM listings WHERE id=?',
            (listing_id,),
        ).fetchone()
    self.assertEqual(row['extraction_quality_flags'], '')
```

Run:

```powershell
& $py -X utf8 -m pytest tests/test_extraction_integrity.py tests/test_feature_extractor.py tests/test_price_history.py -q
```

Expected: new tests and all existing extractor regressions pass.

- [ ] **Step 7: Commit measurement reconciliation**

```powershell
git add cleansing/extraction_integrity.py cleansing/normalizer.py db/schema.py db/listings.py tests/test_extraction_integrity.py tests/test_feature_extractor.py tests/test_price_history.py
git commit -m 'fix: reconcile listing measurements deterministically'
```

---

### Task 3: Multi-lot detection, valuation suppression, and audit parity

**Files:**
- Modify: `cleansing/feature_extractor.py:500-585`
- Modify: `cleansing/reprocess.py:107-168`
- Modify: `services/extraction_audit.py:33-135`
- Modify: `services/signal_quality.py:30-45`
- Modify: `tests/test_feature_extractor.py`
- Modify: `tests/test_extraction_audit.py`
- Modify: `tests/test_reprocess_review_hidden.py`
- Modify: `tests/test_valuation.py`

**Interfaces:**
- Consumes: Task 1 geometry helpers and Task 2 reconciliation flags.
- Produces: broader `is_multi_lot_listing()` coverage without rental false positives.
- Produces: suppressing flags `price_area_inconsistent`, `area_dimension_conflict`, `multi_lot_listing`, and all-property `too_low_absolute_price`.

- [ ] **Step 1: Add failing multi-lot and quality tests**

```python
def test_detects_numeric_multi_lot_phrase_without_repeated_offer_pairs():
    assert is_multi_lot_listing('Bán gấp 2 lô Chánh Mỹ', 'Giá tốt liên hệ')
    assert is_multi_lot_listing('Còn 3 nền liền kề', 'Khu dân cư đẹp')
    assert not is_multi_lot_listing('Nhà trọ 12 phòng', 'Mỗi phòng đang cho thuê')


def test_apartment_unit_scaled_price_is_suppressed():
    class Row(dict):
        def __missing__(self, _key):
            return None

    row = Row({
        'source': 'guland',
        'source_id': 'bad-apartment-price',
        'url': 'https://guland.test/bad-apartment-price',
        'title': 'Căn hộ giá 1,72 tỷ',
        'description': 'Diện tích 60m2',
        'property_type': 'chung_cu',
        'tx_type': 'ban',
        'price_ty': 0.002,
        'price_per_m2': 0.033,
        'area_m2': 60,
    })
    assert 'too_low_absolute_price' in _valuation_quality_flags(row)
```

Add to `tests/test_extraction_audit.py`:

```python
def test_audit_uses_irregular_geometry_tolerance():
    result = audit_listing_extraction(_listing(
        description='Lô xéo hậu ngang 5m dài 40m',
        area_m2=100,
    ))
    assert 'area_m2' not in _fields(result)
```

Add to `tests/test_valuation.py`:

```python
def test_price_area_inconsistent_is_not_actionable():
    from services.signal_quality import is_actionable_signal
    assert not is_actionable_signal({
        'is_signal': 1,
        'source_quality_flags': 'price_area_inconsistent',
    })
```

- [ ] **Step 2: Run the focused tests and confirm expected failures**

```powershell
& $py -X utf8 -m pytest tests/test_feature_extractor.py tests/test_extraction_audit.py tests/test_reprocess_review_hidden.py tests/test_valuation.py -q
```

Expected: the numeric multi-lot, apartment suppression, adaptive audit, and new signal flag assertions fail.

- [ ] **Step 3: Implement bounded phrase and quality rules**

Expand `_MULTI_LOT_COUNT_RE` to accept `lô`, `nền`, and optional locality text without requiring area/price pairs:

```python
_MULTI_LOT_COUNT_RE = re.compile(
    r'\b(?:ban\s+(?:gap\s+)?)?(?:con\s+)?[2-9]\d?\s+'
    r'(?:lo|nen)(?:\s+(?:dat|lien\s+ke))?\b',
    re.IGNORECASE,
)
```

Return true for this count pattern unless `_MULTI_ASSET_RENTAL_CONTEXT_RE` matches. Preserve the existing repeated-offer detection.

In `_valuation_quality_flags(row)`:

- read `tx_type`;
- apply `too_low_absolute_price` to every sale property at `price_ty <= 0.05`;
- keep the existing landed-property threshold;
- re-extract source dimensions from title/description and call `severe_geometry_conflict()` so inferred stored depth is never mistaken for source evidence;
- read `l.extraction_quality_flags` from `valuation_select` and merge it into the valuation source-quality flags;
- add `price_area_inconsistent` when stored price/unit-price/area violate the canonical invariant by more than 20% without clear text support.

Add `price_area_inconsistent` to `ACTIONABLE_SUPPRESS_FLAGS`.

Change `audit_listing_extraction()` so a dimension-derived area difference is reported only when `severe_geometry_conflict()` is true. Explicit total-area and thổ-cư comparisons retain their own evidence checks.

- [ ] **Step 4: Run the focused tests and confirm green**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Commit automatic suppression and audit parity**

```powershell
git add cleansing/feature_extractor.py cleansing/reprocess.py services/extraction_audit.py services/signal_quality.py tests/test_feature_extractor.py tests/test_extraction_audit.py tests/test_reprocess_review_hidden.py tests/test_valuation.py
git commit -m 'fix: suppress unresolved extraction contradictions'
```

---

### Task 4: Persist crawl provenance through normalized listings

**Files:**
- Modify: `db/listings.py:268-540`
- Modify: `tests/test_price_history.py`

**Interfaces:**
- Consumes: existing `upsert_listing(rec: dict, crawl_run_id: int | None)` argument.
- Produces: `listings.crawl_run_id` set to the latest supplied normalization/reprocess run on insert/update; source-crawl provenance remains available through `raw_id`.

- [ ] **Step 1: Add a failing provenance test**

```python
def test_upsert_listing_persists_latest_crawl_run_id():
    from db.connection import get_conn
    from db.listings import upsert_listing

    listing_id, _ = upsert_listing(self._rec(), crawl_run_id=101)
    upsert_listing(self._rec(title='Tin cập nhật'), crawl_run_id=202)

    with get_conn() as conn:
        row = conn.execute(
            'SELECT crawl_run_id FROM listings WHERE id=?', (listing_id,)
        ).fetchone()
    assert row['crawl_run_id'] == 202
```

- [ ] **Step 2: Run the exact test and confirm it fails with null provenance**

```powershell
& $py -X utf8 -m pytest tests/test_price_history.py::PriceHistoryTest::test_upsert_listing_persists_latest_crawl_run_id -q
```

Expected assertion: `None != 202`.

- [ ] **Step 3: Wire the existing argument into insert and update SQL**

Add `crawl_run_id` to the listing insert columns/values and update assignment:

```sql
crawl_run_id = COALESCE(:crawl_run_id, crawl_run_id)
```

Pass `'crawl_run_id': crawl_run_id` in both parameter dictionaries. Do not clear an existing run when a caller supplies `None`.

- [ ] **Step 4: Run price-history regressions**

```powershell
& $py -X utf8 -m pytest tests/test_price_history.py -q
```

Expected: all tests pass and existing price-history `crawl_run_id` behavior is unchanged.

- [ ] **Step 5: Commit normalized provenance**

```powershell
git add db/listings.py tests/test_price_history.py
git commit -m 'fix: retain listing crawl provenance'
```

---

### Task 5: Move dedup, price-drop, and lifecycle state before valuation

**Files:**
- Modify: `cleansing/reprocess.py:641-712`
- Modify: `tests/test_signal_read_model.py:576-625`

**Interfaces:**
- Produces: `_run_full_reprocess()` order `listings -> hashes -> dedup -> drops/lifecycle -> trends -> valuation -> map -> publish`.
- Preserves: existing return keys and `publish_public_data()` arguments.

- [ ] **Step 1: Strengthen the existing order test so it fails**

Replace the loose final-publication assertion with an explicit event sequence:

```python
monkeypatch.setattr(reprocess, 'populate_content_hashes', lambda _conn: events.append('hashes') or 0)
monkeypatch.setattr(dedup, 'flag_duplicates_in_db', lambda _conn: events.append('dedup') or {
    'dup_groups': 0, 'flagged': 0, 'unique_lots': 1,
})
monkeypatch.setattr(market_trend, 'detect_price_drops', lambda _conn: events.append('drops') or 0)
monkeypatch.setattr(lifecycle, 'backfill_first_seen', lambda _conn: events.append('first_seen'))
monkeypatch.setattr(lifecycle, 'sweep_delisted', lambda _conn: events.append('lifecycle') or [])
monkeypatch.setattr(market_trend, 'compute_weekly_trend', lambda _conn: events.append('weekly'))
monkeypatch.setattr(market_trend, 'compute_monthly_trend', lambda _conn: events.append('monthly'))
monkeypatch.setattr(market_trend, 'compute_daily_trend', lambda _conn: events.append('daily'))

assert events == [
    'hashes', 'dedup', 'first_seen', 'drops', 'lifecycle',
    'weekly', 'monthly', 'daily', 'valuation', 'map', 'publish',
]
```

Make the mocked map and publish functions append plain event names while retaining separate argument assertions.

- [ ] **Step 2: Run the exact order test and observe valuation occurs too early**

```powershell
& $py -X utf8 -m pytest tests/test_signal_read_model.py::test_full_reprocess_publishes_after_dedup_and_market -q
```

Expected: sequence mismatch with `valuation` before prerequisites.

- [ ] **Step 3: Reorder `_run_full_reprocess()` without changing helper semantics**

Move existing blocks rather than duplicating them. Keep each `get_conn()` boundary and use this order:

```python
listing_stats = reprocess_listings(
    source=source,
    since=since,
    full=full,
    raw_ids=raw_ids,
)
processed_ids = listing_stats.get('processed_ids', [])

with get_conn() as conn:
    n_hashes = populate_content_hashes(conn)
with get_conn() as conn:
    dedup_stats = flag_duplicates_in_db(conn)
with get_conn() as conn:
    backfill_first_seen(conn)
    n_drops = detect_price_drops(conn)
    delisted_list = sweep_delisted(conn)
with get_conn() as conn:
    conn.execute('DELETE FROM market_weekly')
    compute_weekly_trend(conn)
    compute_monthly_trend(conn)
    compute_daily_trend(conn)

val_stats = reprocess_valuation(
    incremental_ids=None if full else processed_ids,
)
map_location_stats = _run_listing_map_backfill(processed_ids, full=full)
public_read_model_stats = publish_public_data(
    listing_ids=None if full else tuple(dict.fromkeys(processed_ids)),
    market_changed=True,
    strict=False,
)
```

Allow valuation exceptions to propagate; do not catch and continue to publication.

- [ ] **Step 4: Run order and targeted reprocess regressions**

```powershell
& $py -X utf8 -m pytest tests/test_signal_read_model.py tests/test_guland_targeted_reprocess.py tests/test_lifecycle.py tests/test_market_trend.py tests/test_dedup.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the pipeline order**

```powershell
git add cleansing/reprocess.py tests/test_signal_read_model.py
git commit -m 'fix: prepare listing state before valuation'
```

---

### Task 6: Atomic main/shadow valuation snapshot with model provenance

**Files:**
- Modify: `analytics/valuation.py:60-105`
- Modify: `db/schema.py:303-389, 1317-1330`
- Modify: `cleansing/reprocess.py:190-575`
- Create: `tests/test_valuation_snapshot.py`

**Interfaces:**
- Adds: `MAIN_MODEL_NAME = 'road_tier_hierarchical'` beside `MAIN_MODEL_VERSION`.
- Adds: optional `crawl_run_id: int | None = None` to `analytics.valuation.Listing`.
- Adds: nullable `valuation_results.model_run_id` plus index.
- Produces: `_replace_valuation_snapshot(main_results, shadow_results, id_map, *, incremental_ids, metrics, main_model_name, main_model_version, shadow_model_name, shadow_model_version) -> dict`.
- Internal helpers accept an existing connection and never call `get_conn()` themselves.

- [ ] **Step 1: Add failing schema/provenance integration tests**

```python
from dataclasses import dataclass
import uuid

import pytest

from db.connection import get_conn
from db.schema import init_schema


@dataclass
class SnapshotCase:
    listing_ids: list[int]
    target_id: int
    previous_max_run_id: int

    def read_state(self, conn=None):
        if conn is None:
            with get_conn() as opened:
                return self.read_state(opened)
        placeholders = ','.join('?' for _ in self.listing_ids)
        params = list(self.listing_ids)
        main = [tuple(row) for row in conn.execute(
            f'''SELECT listing_id, model_run_id, crawl_run_id, fair_ppm2,
                       actual_ppm2, mos_pct, is_signal
                FROM valuation_results
                WHERE listing_id IN ({placeholders})
                ORDER BY listing_id, id''',
            params,
        ).fetchall()]
        shadow = [tuple(row) for row in conn.execute(
            f'''SELECT listing_id, model_run_id, fair_ppm2, actual_ppm2,
                       mos_pct, is_signal
                FROM valuation_shadow_results
                WHERE listing_id IN ({placeholders})
                ORDER BY listing_id, id''',
            params,
        ).fetchall()]
        listings = [tuple(row) for row in conn.execute(
            f'''SELECT id, is_outlier, outlier_direction, outlier_sigma
                FROM listings WHERE id IN ({placeholders}) ORDER BY id''',
            params,
        ).fetchall()]
        return {'main': main, 'shadow': shadow, 'listings': listings}


@pytest.fixture
def valuation_case():
    init_schema()
    token = uuid.uuid4().hex
    listing_ids = []
    with get_conn() as conn:
        max_run_row = conn.execute(
            'SELECT COALESCE(MAX(id),0) AS max_id FROM valuation_model_runs'
        ).fetchone()
        previous_max_run_id = int(max_run_row['max_id'])
        for index in range(20):
            ppm2 = 15.0 + (index % 2)
            crawl_run_id = 717 if index == 0 else 800 + index
            listing_id = conn.execute(
                '''
                INSERT INTO listings (
                    source, source_id, url, title, description, area, ward,
                    property_type, tx_type, price_per_m2, price_ty, area_m2,
                    road_type, road_tier, has_so, crawled_at, crawl_run_id
                ) VALUES (
                    'facebook', ?, ?, 'Tin dau tu', 'Dien tich 100m2',
                    'Tan An', 'Tan An', 'dat_nen', 'ban', ?, ?, 100,
                    'duong_nhua', 2, 1, '2026-08-03T00:00:00', ?
                )
                ''',
                (
                    f'{token}-{index}', f'https://t.test/{token}/{index}',
                    ppm2, ppm2 / 10, crawl_run_id,
                ),
            ).lastrowid
            listing_ids.append(listing_id)
    case = SnapshotCase(listing_ids, listing_ids[0], previous_max_run_id)
    yield case
    with get_conn() as conn:
        placeholders = ','.join('?' for _ in listing_ids)
        conn.execute(f'DELETE FROM listings WHERE id IN ({placeholders})', listing_ids)
        conn.execute(
            'DELETE FROM valuation_model_runs WHERE id > ?',
            (previous_max_run_id,),
        )


@pytest.fixture
def seeded_snapshot(valuation_case):
    from cleansing.reprocess import reprocess_valuation

    reprocess_valuation(
        incremental_ids=valuation_case.listing_ids,
        training_ids=valuation_case.listing_ids,
    )
    return valuation_case


def test_main_valuation_rows_store_model_and_crawl_run_provenance(valuation_case):
    from cleansing.reprocess import reprocess_valuation

    reprocess_valuation(
        incremental_ids=valuation_case.listing_ids,
        training_ids=valuation_case.listing_ids,
    )

    with get_conn() as conn:
        row = conn.execute(
            '''
            SELECT v.crawl_run_id, r.model_name, r.model_version
            FROM valuation_results v
            JOIN valuation_model_runs r ON r.id=v.model_run_id
            WHERE v.listing_id=?
            ''',
            (valuation_case.target_id,),
        ).fetchone()
    assert row['crawl_run_id'] == 717
    assert row['model_name'] == 'road_tier_hierarchical'
    assert row['model_version'] == 'road_tier_hierarchical_v1'
```

- [ ] **Step 2: Add a failing real-rollback test**

```python
def test_shadow_insert_failure_rolls_back_main_and_listing_outliers(monkeypatch, seeded_snapshot):
    from cleansing import reprocess
    from db.connection import get_conn

    before = seeded_snapshot.read_state()

    def fail_shadow(*_args, **_kwargs):
        raise RuntimeError('forced shadow insert failure')

    monkeypatch.setattr(reprocess, '_insert_shadow_results', fail_shadow)
    with pytest.raises(RuntimeError, match='forced shadow insert failure'):
        reprocess.reprocess_valuation(
            incremental_ids=seeded_snapshot.listing_ids,
            training_ids=seeded_snapshot.listing_ids,
        )

    with get_conn() as conn:
        after = seeded_snapshot.read_state(conn)
    assert after == before
```

This test mocks only the failure point; assertions read the real PostgreSQL test database to prove rollback.

- [ ] **Step 3: Run the new test file and verify both behaviors fail**

```powershell
& $py -X utf8 -m pytest tests/test_valuation_snapshot.py -q
```

Expected: missing `model_run_id`/provenance and partial replacement behavior.

- [ ] **Step 4: Add the additive schema and model identity**

Update `valuation_results` DDL:

```sql
model_run_id INTEGER REFERENCES valuation_model_runs(id) ON DELETE SET NULL,
```

Because `valuation_model_runs` is currently declared after `valuation_results`, reorder only these two DDL blocks so the referenced table is created first. Add the idempotent migration:

```python
('model_run_id', 'ALTER TABLE valuation_results ADD COLUMN model_run_id INTEGER REFERENCES valuation_model_runs(id) ON DELETE SET NULL')
```

Add:

```sql
CREATE INDEX IF NOT EXISTS idx_valuation_model_run ON valuation_results(model_run_id);
```

In `analytics/valuation.py`:

```python
MAIN_MODEL_NAME = 'road_tier_hierarchical'
MAIN_MODEL_VERSION = 'road_tier_hierarchical_v1'
```

Append `crawl_run_id: int | None = None` to `Listing` so existing constructors remain compatible.

- [ ] **Step 5: Make row conversion explicit and include crawl metadata**

Add `l.crawl_run_id` to `valuation_select`. Replace both silent `except: pass` loops with a helper that raises an ID-specific error:

```python
def _convert_valuation_rows(rows, row_to_listing):
    converted = []
    for row in rows:
        try:
            converted.append(row_to_listing(row))
        except Exception as exc:
            listing_id = row['id'] if 'id' in row.keys() else 'unknown'
            raise ValueError(f'valuation input conversion failed listing_id={listing_id}: {exc}') from exc
    return converted
```

Set `crawl_run_id=row['crawl_run_id']` in `Listing`.

- [ ] **Step 6: Replace split writes with one transaction**

Refactor existing insert loops into connection-owned helpers with these bodies:

```python
def _insert_model_run(conn, *, model_name, model_version, metrics):
    return conn.execute(
        '''
        INSERT INTO valuation_model_runs (
            model_name, model_version, status, metrics_json,
            total_count, signal_count
        ) VALUES (?, ?, 'complete', ?, ?, ?)
        ''',
        (
            model_name,
            model_version,
            json.dumps(metrics, ensure_ascii=False, sort_keys=True),
            metrics['valuation_count'],
            metrics['signal_count'],
        ),
    ).lastrowid


def _insert_main_results(conn, results, id_map, model_run_id, computed_at):
    for result in results:
        listing = id_map[result.listing_id]
        conn.execute(
            '''
            INSERT INTO valuation_results (
                model_run_id, listing_id, crawl_run_id,
                fair_ppm2, actual_ppm2, mos_pct,
                is_signal, is_outlier, outlier_direction, outlier_sigma,
                segment, n_segment, signal_score, road_tier,
                source_quality_flags, source_quality_recheck,
                legal_status, trust_tier, trust_score, legal_flags,
                computed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                model_run_id, result.listing_id, listing.crawl_run_id,
                result.price_per_m2_fair, result.price_per_m2_actual,
                result.discount_pct, int(result.is_signal), int(result.is_outlier),
                result.outlier_direction or None, result.outlier_sigma or None,
                f'{result.area}|{result.property_type}', result.segment_n,
                result.signal_score, listing.road_tier,
                ','.join(result.source_quality_flags or ()),
                int(bool(result.source_quality_recheck)), result.legal_status,
                result.trust_tier, result.trust_score,
                ','.join(result.legal_flags or ()), computed_at,
            ),
        )
        conn.execute(
            '''
            UPDATE listings
            SET is_outlier=?, outlier_direction=?, outlier_sigma=?
            WHERE id=?
            ''',
            (
                int(result.is_outlier), result.outlier_direction or None,
                result.outlier_sigma or None, result.listing_id,
            ),
        )


def _insert_shadow_results(conn, results, id_map, model_run_id, computed_at):
    for result in results:
        listing = id_map[result.listing_id]
        try:
            audit = json.loads(result.note) if result.note else {}
        except (TypeError, ValueError):
            audit = {}
        conn.execute(
            '''
            INSERT INTO valuation_shadow_results (
                model_run_id, listing_id, fair_ppm2, actual_ppm2, mos_pct,
                is_signal, signal_score, road_tier, segment, n_segment,
                source_quality_flags, source_quality_recheck,
                legal_status, trust_tier, trust_score, legal_flags,
                area_ratio, area_adjustment, road_model_tier, road_penalty,
                fallback_level, audit_json, computed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                model_run_id, result.listing_id, result.price_per_m2_fair,
                result.price_per_m2_actual, result.discount_pct,
                int(result.is_signal), result.signal_score, listing.road_tier,
                audit.get('segment') or f'{result.area}|{result.property_type}',
                result.segment_n, ','.join(result.source_quality_flags or ()),
                int(bool(result.source_quality_recheck)), result.legal_status,
                result.trust_tier, result.trust_score,
                ','.join(result.legal_flags or ()), audit.get('area_ratio'),
                audit.get('area_adjustment'), audit.get('road_model_tier'),
                audit.get('road_penalty'), audit.get('fallback_level'),
                json.dumps(audit, ensure_ascii=False, sort_keys=True), computed_at,
            ),
        )


def _replace_valuation_snapshot(
    main_results,
    shadow_results,
    id_map,
    *,
    incremental_ids,
    metrics,
    main_model_name,
    main_model_version,
    shadow_model_name,
    shadow_model_version,
):
    computed_at = datetime.now(timezone.utc).isoformat()
    main_metrics = {
        **metrics,
        'valuation_count': len(main_results),
        'signal_count': sum(1 for result in main_results if result.is_signal),
    }
    shadow_metrics = {
        **metrics,
        'valuation_count': len(shadow_results),
        'signal_count': sum(1 for result in shadow_results if result.is_signal),
    }
    with get_conn() as conn:
        main_run_id = _insert_model_run(
            conn,
            model_name=main_model_name,
            model_version=main_model_version,
            metrics=main_metrics,
        )
        shadow_run_id = _insert_model_run(
            conn,
            model_name=shadow_model_name,
            model_version=shadow_model_version,
            metrics=shadow_metrics,
        )
        if incremental_ids is None:
            conn.execute('DELETE FROM valuation_results')
            conn.execute('DELETE FROM valuation_shadow_results')
            conn.execute(
                'UPDATE listings SET is_outlier=0, outlier_direction=NULL, outlier_sigma=NULL'
            )
        else:
            target_ids = list(dict.fromkeys(incremental_ids))
            placeholders = ','.join('?' for _ in target_ids)
            conn.execute(
                f'DELETE FROM valuation_results WHERE listing_id IN ({placeholders})',
                target_ids,
            )
            conn.execute(
                f'DELETE FROM valuation_shadow_results WHERE listing_id IN ({placeholders})',
                target_ids,
            )
            conn.execute(
                f'''UPDATE listings
                    SET is_outlier=0, outlier_direction=NULL, outlier_sigma=NULL
                    WHERE id IN ({placeholders})''',
                target_ids,
            )
        _insert_main_results(conn, main_results, id_map, main_run_id, computed_at)
        _insert_shadow_results(conn, shadow_results, id_map, shadow_run_id, computed_at)
    return {'main_model_run_id': main_run_id, 'shadow_model_run_id': shadow_run_id}
```

`_replace_valuation_snapshot()` must use one `with get_conn() as conn:` block, create both model-run rows, delete the target main/shadow rows, reset target outlier fields, insert both result sets, update new outlier fields, and return both run IDs only after the context commits. Do not delete historical `valuation_model_runs` rows.

The main insert column order is:

```sql
(model_run_id, listing_id, crawl_run_id, fair_ppm2, actual_ppm2, mos_pct,
 is_signal, is_outlier, outlier_direction, outlier_sigma, segment, n_segment,
 signal_score, road_tier, source_quality_flags, source_quality_recheck,
 legal_status, trust_tier, trust_score, legal_flags, computed_at)
```

Pass one ISO timestamp to all rows in the snapshot. Put `training_count`, `valuation_count`, `signal_count`, `integrity_flag_counts`, and `rejected_conversion_count` in `metrics_json`.

Compute both main and shadow results before calling `_replace_valuation_snapshot()`. Full runs must not delete old results at the beginning of `reprocess_valuation()`. Build and pass metrics with the same names used by `_insert_model_run()`:

```python
from collections import Counter

from analytics.valuation import MAIN_MODEL_NAME, MAIN_MODEL_VERSION
from services.signal_quality import ACTIONABLE_SUPPRESS_FLAGS

integrity_flag_counts = Counter(
    flag
    for listing in valuate_listings
    for flag in listing.source_quality_flags
    if flag in ACTIONABLE_SUPPRESS_FLAGS
)
snapshot_info = _replace_valuation_snapshot(
    results,
    shadow_results,
    id_map,
    incremental_ids=incremental_ids,
    metrics={
        'training_count': len(train_listings),
        'integrity_flag_counts': dict(sorted(integrity_flag_counts.items())),
        'rejected_conversion_count': 0,
    },
    main_model_name=MAIN_MODEL_NAME,
    main_model_version=MAIN_MODEL_VERSION,
    shadow_model_name=SHADOW_MODEL_NAME,
    shadow_model_version=SHADOW_MODEL_VERSION,
)
stats.update(snapshot_info)
```

- [ ] **Step 7: Run snapshot, schema, and valuation regressions**

```powershell
& $py -X utf8 -m pytest tests/test_valuation_snapshot.py tests/test_reprocess_review_hidden.py tests/test_valuation.py tests/test_postgres_connection.py tests/test_signal_read_model.py -q
```

Expected: provenance exists, forced failure rolls back, and all existing valuation semantics pass.

- [ ] **Step 8: Commit atomic snapshot handling**

```powershell
git add analytics/valuation.py db/schema.py cleansing/reprocess.py tests/test_valuation_snapshot.py tests/test_reprocess_review_hidden.py tests/test_valuation.py
git commit -m 'fix: replace valuation snapshots atomically'
```

---

### Task 7: Non-mutating integrity comparison command

**Files:**
- Create: `services/extraction_integrity_report.py`
- Create: `tests/test_extraction_integrity_report.py`
- Modify: `cli/system.py`
- Modify: `radar.py`

**Interfaces:**
- Produces: `summarize_integrity_changes(rows: list[dict]) -> dict` as a pure aggregator.
- Produces: `build_integrity_report(limit: int | None = None) -> dict` as the read-only DB entrypoint.
- Produces CLI: `radar.py integrity-report [--limit N] [--json]`.

- [ ] **Step 1: Add failing pure-report tests**

```python
from services.extraction_integrity_report import summarize_integrity_changes


def test_integrity_report_counts_repairs_suppressions_and_actionable_changes():
    report = summarize_integrity_changes([
        {
            'listing_id': 1,
            'changes': {'area_m2': [60, 85], 'price_per_m2': [28.333, 20]},
            'repairs': ['structured_area_was_residential_area'],
            'old_flags': [],
            'new_flags': [],
            'is_signal': True,
            'old_actionable': True,
            'new_actionable': True,
            'training_before': True,
            'training_after': True,
            'invariant_ok': True,
        },
        {
            'listing_id': 2,
            'changes': {},
            'repairs': [],
            'old_flags': [],
            'new_flags': ['area_dimension_conflict'],
            'is_signal': True,
            'old_actionable': True,
            'new_actionable': False,
            'training_before': True,
            'training_after': False,
            'invariant_ok': True,
        },
    ])
    assert report['scanned'] == 2
    assert report['field_changes']['area_m2'] == 1
    assert report['repair_reasons']['structured_area_was_residential_area'] == 1
    assert report['suppressing_flags']['area_dimension_conflict'] == 1
    assert report['actionable']['newly_suppressed'] == 1
    assert report['training_membership']['removed'] == 1
    assert report['invariant_violations_remaining'] == 0
```

- [ ] **Step 2: Run the test and observe the missing-module failure**

```powershell
& $py -X utf8 -m pytest tests/test_extraction_integrity_report.py -q
```

Expected: collection failure for the missing report service.

- [ ] **Step 3: Implement the pure aggregator and read-only loader**

The loader must:

- join `raw_listings` to `listings` by `raw_id`;
- read the latest main and shadow valuation rows with `DISTINCT ON`;
- parse `raw_json`, merge `raw_id`, `source`, `source_id`, `url`, and `crawled_at` from the raw row, then call `normalize_record()` without `upsert_listing()`;
- compare only `price_ty`, `area_m2`, `tho_cu_m2`, and `price_per_m2`;
- evaluate old/new suppressing flags with shared helpers;
- count current main/shadow totals and MOS deltas of at least 20 percentage points;
- never execute `INSERT`, `UPDATE`, `DELETE`, schema DDL, read-model refresh, or cache publication.

Return this stable top-level shape:

```python
{
    'scanned': int,
    'field_changes': dict[str, int],
    'repair_reasons': dict[str, int],
    'suppressing_flags': dict[str, int],
    'actionable': {'current': int, 'newly_suppressed': int, 'restored': int},
    'training_membership': {'added': int, 'removed': int},
    'models': {'main_count': int, 'shadow_count': int, 'mos_delta_ge_20': int},
    'invariant_violations_remaining': int,
    'samples': list[dict],
}
```

Cap `samples` at 50 deterministic listing IDs while counts always cover the requested scan.

- [ ] **Step 4: Add CLI parser/dispatch tests and implementation**

In `radar.py`, add:

```python
p_integrity = sub.add_parser('integrity-report', help='Read-only extraction/valuation integrity comparison')
p_integrity.add_argument('--limit', type=int)
p_integrity.add_argument('--json', action='store_true', dest='as_json')
```

Dispatch to `cmd_integrity_report(args)` in `cli/system.py`. JSON mode uses `json.dumps(report, ensure_ascii=False, indent=2)`; text mode prints the same aggregate keys without writing a file.

Add parser and read-only behavior assertions to `tests/test_extraction_integrity_report.py`.

- [ ] **Step 5: Run report and CLI tests**

```powershell
& $py -X utf8 -m pytest tests/test_extraction_integrity_report.py -q
& $py -X utf8 radar.py integrity-report --limit 200 --json
```

Expected: tests pass; command returns valid UTF-8 JSON and makes no DB changes.

- [ ] **Step 6: Commit the automated comparison command**

```powershell
git add services/extraction_integrity_report.py tests/test_extraction_integrity_report.py cli/system.py radar.py
git commit -m 'feat: add read-only integrity comparison report'
```

---

### Task 8: Documentation, regression gate, and release evidence

**Files:**
- Modify: `docs/daily_crawl_flow.md`
- Modify: `docs/dev_commands.md`
- Verify: all files changed by Tasks 1-7

**Interfaces:**
- Documents: canonical order, adaptive thresholds, atomic replacement, dry-run report, full-reprocess requirement, and rollback.
- Produces: a clean implementation branch with test and local-report evidence; production deployment remains a separately confirmed external action.

- [ ] **Step 1: Update operational documentation**

Add the exact canonical order and commands:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 radar.py integrity-report --json
& $py -X utf8 radar.py reprocess --full
& $py -X utf8 radar.py signal-read-model --refresh --compare --compare-listings --limit 200
```

State that `integrity-report` is read-only, production reprocess is required after deploy, and public publication must not occur after a valuation failure.

- [ ] **Step 2: Run syntax checks**

```powershell
& $py -X utf8 -m py_compile cleansing/extraction_integrity.py cleansing/normalizer.py cleansing/feature_extractor.py cleansing/reprocess.py analytics/valuation.py services/extraction_audit.py services/extraction_integrity_report.py services/signal_quality.py db/listings.py db/schema.py cli/system.py radar.py
```

Expected: exit code 0 with no output.

- [ ] **Step 3: Run the focused extraction-to-valuation suite**

```powershell
& $py -X utf8 -m pytest tests/test_extraction_integrity.py tests/test_extraction_integrity_report.py tests/test_extraction_audit.py tests/test_feature_extractor.py tests/test_price_history.py tests/test_dedup.py tests/test_lot_history.py tests/test_lifecycle.py tests/test_market_trend.py tests/test_valuation.py tests/test_valuation_snapshot.py tests/test_reprocess_review_hidden.py tests/test_guland_targeted_reprocess.py tests/test_signal_quality.py tests/test_signal_read_model.py -q
```

Expected: 100% pass, no warnings caused by the changed modules.

- [ ] **Step 4: Run downstream public/read-model regressions**

```powershell
& $py -X utf8 -m pytest tests/test_listing_feed.py tests/test_guest_visibility.py tests/test_source_policy.py tests/test_listing_map_service.py tests/test_listing_map_api.py tests/test_market_data_performance.py tests/test_public_cache_keys.py tests/test_public_cache.py tests/test_public_cache_headers.py tests/test_public_prewarm.py tests/test_vip_notify.py -q
```

Expected: 100% pass and public redaction/cache invariants unchanged.

- [ ] **Step 5: Run the full non-mutating local comparison**

```powershell
& $py -X utf8 radar.py integrity-report --json
```

Required gate before production:

- `invariant_violations_remaining` is `0` for actionable candidates;
- repair and suppression counts are finite and explained by named reasons;
- sample changes show no systemic price-unit inversion;
- model counts and large MOS deltas are reported, not used to switch models;
- no DB mutation is observed.

- [ ] **Step 6: Commit documentation and verification commands**

```powershell
git add docs/daily_crawl_flow.md docs/dev_commands.md
git commit -m 'docs: record extraction valuation integrity gates'
```

- [ ] **Step 7: Review branch scope and prepare handoff**

```powershell
git status --short
git diff --check origin/main...HEAD
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
```

Expected: only scoped files are changed; `.playwright-cli/` and any user-owned files are absent from commits. Report tests, local DB evidence, and remaining production actions. Do not push, deploy, or run the production full reprocess without explicit authorization for those external mutations.
