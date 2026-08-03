# Default Signal MOS 15% Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MOS 15% the consistent default for every user-facing Săn Deal surface while preserving MOS 10% as the internal candidate floor and as an explicit VIP/Admin filter choice.

**Architecture:** Add one tier-aware MOS normalization policy to `services/signal_quality.py`, then pass its effective value through feed, count, cache-key, read-model, Maps, UI, alert, and report boundaries. Keep `SIGNAL_MOS_THRESHOLD=0.10` and `actionable_signal_sql()` candidate-oriented so eligible 10–14.9% rows remain queryable by VIP/Admin; no valuation reprocess or data rewrite is part of this change.

**Tech Stack:** Python 3.12, Flask, PostgreSQL/SQLite-compatible query helpers, Jinja2, vanilla JavaScript, pytest/unittest, Redis/public dataset versions, Nginx, Cloudflare.

## Global Constraints

- `DEFAULT_SIGNAL_MOS_MIN_PCT = 15.0`; the internal `SIGNAL_MOS_THRESHOLD` remains `0.10`.
- Guest and Free always use effective MOS 15%, even if the request supplies another value.
- VIP and Admin use MOS 15% when the request is missing, empty, invalid, or non-finite; an explicit numeric value is clamped to 0–70 and may be 10%.
- `actionable_signal_sql()` must not embed MOS 15%; the existing candidate and quality gates remain unchanged.
- `/api/signals`, `/api/counts`, `/api/dashboard`, and signals-mode Maps must share the same effective MOS value and cache-key value.
- Tin rao, crawler, normalization, deduplication, valuation, Admin QC, human labels, `ai_deal_review`, and `ai_training_feedback` remain unchanged.
- Guest/Free/VIP redaction rules remain unchanged; only Admin may receive original URLs or phone numbers.
- Tests are written and observed failing before each production-code change.
- Release completion requires rebase, focused and full relevant verification, push to `main`, standard production deploy, read-model publication, and public/browser proof.

---

## File Structure

- `services/signal_quality.py`: owns the shared default constant, allowed range, and tier-aware normalization function.
- `services/market_data.py`: parses request intent once and applies the effective value to legacy feed, totals, dashboard summaries, and cache inputs.
- `services/signal_read_model.py`: enforces the same policy at the optimized feed/count boundary.
- `services/listing_map.py` and `app.py`: carry the normalized float into signal Maps without altering Tin rao.
- `templates/index.html` and `static/js/main/boot.js`: render 15% initially, lock Guest/Free, and ignore crafted MOS URL values for locked tiers.
- `cli/notify.py`: applies 15% to a watchlist with no selected MOS while preserving explicit VIP/Admin values such as 10%.
- `services/monthly_report_data.py`: applies 15% to default public report counts and cards.
- `tests/test_signal_quality.py`: unit contract for MOS normalization.
- `tests/test_guest_visibility.py`, `tests/test_market_data_performance.py`, and `tests/test_signal_read_model.py`: feed/count/cache/read-model behavior and parity.
- `tests/test_listing_map_api.py` and `tests/test_listing_map_service.py`: Maps request and service behavior.
- `tests/test_homepage_mos_ui.py` and `tests/test_refactor_structure.py`: rendered tier behavior, default-control markup, and boot-script regression checks.
- `tests/test_vip_notify.py` and `tests/test_monthly_report_data.py`: alert and report defaults.
- `docs/product_rules.md`, `docs/operations.md`, and the approved spec: durable product and rollout documentation.

---

### Task 1: Define the Shared MOS Policy

**Files:**
- Create: `tests/test_signal_quality.py`
- Modify: `services/signal_quality.py`

**Interfaces:**
- Consumes: tier names `guest`, `free`, `vip`, and `admin`; raw query/watchlist values.
- Produces: `DEFAULT_SIGNAL_MOS_MIN_PCT: float`, `MOS_FILTER_MIN_PCT: float`, `MOS_FILTER_MAX_PCT: float`, and `effective_signal_mos_min(tier: str, requested_value=None, *, was_explicit: bool | None = None) -> float`.

- [ ] **Step 1: Write the failing normalization tests**

```python
import math

import pytest

from services.signal_quality import effective_signal_mos_min


@pytest.mark.parametrize("tier", ("guest", "free", "unknown", ""))
@pytest.mark.parametrize("requested", (None, 0, 10, 20, "bad", math.inf))
def test_non_privileged_tiers_are_fixed_at_fifteen(tier, requested):
    assert effective_signal_mos_min(tier, requested) == 15.0


@pytest.mark.parametrize("tier", ("vip", "admin"))
@pytest.mark.parametrize("requested", (None, "", "bad", math.inf, -math.inf, math.nan))
def test_privileged_missing_or_invalid_values_default_to_fifteen(tier, requested):
    assert effective_signal_mos_min(tier, requested) == 15.0


@pytest.mark.parametrize("tier", ("vip", "admin"))
def test_privileged_explicit_values_are_retained_and_clamped(tier):
    assert effective_signal_mos_min(tier, 10) == 10.0
    assert effective_signal_mos_min(tier, "12.5") == 12.5
    assert effective_signal_mos_min(tier, -5) == 0.0
    assert effective_signal_mos_min(tier, 80) == 70.0


def test_explicit_flag_distinguishes_missing_from_numeric_zero():
    assert effective_signal_mos_min("vip", 0, was_explicit=False) == 15.0
    assert effective_signal_mos_min("vip", 0, was_explicit=True) == 0.0
```

- [ ] **Step 2: Run the new tests and confirm RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_signal_quality.py -q
```

Expected: collection fails because `effective_signal_mos_min` does not exist.

- [ ] **Step 3: Implement the smallest shared policy without changing the candidate gate**

Add `import math` and the following above `ACTIONABLE_SUPPRESS_FLAGS`:

```python
DEFAULT_SIGNAL_MOS_MIN_PCT = 15.0
MOS_FILTER_MIN_PCT = 0.0
MOS_FILTER_MAX_PCT = 70.0
_MOS_FILTER_TIERS = frozenset({"vip", "admin"})


def effective_signal_mos_min(
    tier: str,
    requested_value=None,
    *,
    was_explicit: bool | None = None,
) -> float:
    """Return the user-facing MOS floor for one signal request."""
    if str(tier or "guest").strip().lower() not in _MOS_FILTER_TIERS:
        return DEFAULT_SIGNAL_MOS_MIN_PCT

    explicit = requested_value is not None if was_explicit is None else bool(was_explicit)
    if not explicit:
        return DEFAULT_SIGNAL_MOS_MIN_PCT

    try:
        value = float(requested_value)
    except (TypeError, ValueError):
        return DEFAULT_SIGNAL_MOS_MIN_PCT
    if not math.isfinite(value):
        return DEFAULT_SIGNAL_MOS_MIN_PCT
    return min(max(value, MOS_FILTER_MIN_PCT), MOS_FILTER_MAX_PCT)
```

Do not edit `actionable_signal_sql()`, `is_actionable_signal()`, or `config/settings.py`.

- [ ] **Step 4: Run the policy and existing signal-quality tests**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_signal_quality.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the policy unit**

```powershell
git add services/signal_quality.py tests/test_signal_quality.py
git commit -m "feat(signals): define default MOS policy"
```

---

### Task 2: Align Feed, Counts, Dashboard, Cache Keys, and Read Model

**Files:**
- Modify: `services/market_data.py`
- Modify: `services/signal_read_model.py`
- Modify: `tests/test_guest_visibility.py`
- Modify: `tests/test_market_data_performance.py`
- Modify: `tests/test_signal_read_model.py`

**Interfaces:**
- Consumes: `DEFAULT_SIGNAL_MOS_MIN_PCT` and `effective_signal_mos_min()` from Task 1.
- Produces: one effective `mos_min: float` used identically by `/api/signals`, `/api/counts`, `/api/dashboard`, cache queries, legacy SQL, and read-model SQL.

- [ ] **Step 1: Add request-policy tests for all four tiers**

Add this focused endpoint test to `tests/test_market_data_performance.py`:

```python
@pytest.mark.parametrize(
    ("tier", "query", "expected"),
    [
        ("guest", "", 15.0),
        ("guest", "?mos_min=10", 15.0),
        ("free", "?mos_min=10", 15.0),
        ("vip", "", 15.0),
        ("vip", "?mos_min=10", 10.0),
        ("admin", "?mos_min=12.5", 12.5),
        ("admin", "?mos_min=nan", 15.0),
    ],
)
def test_api_signals_normalizes_mos_before_cache_and_loader(
    monkeypatch, tier, query, expected
):
    import app as radar_app
    import auth.core as auth_core

    captured = {"cache": None, "loader": None}

    monkeypatch.setattr(auth_core, "current_tier", lambda: tier)
    monkeypatch.setattr(radar_app, "current_tier", lambda: tier)
    monkeypatch.setattr(radar_app, "_public_dataset_versions", lambda _names: {"signals": 1})

    def fake_load_signals(*_args, **kwargs):
        captured["loader"] = kwargs["mos_min"]
        return {"signals": [], "page": 1, "limit": 30, "total": 0, "pages": 0}

    def fake_cache(**kwargs):
        captured["cache"] = kwargs["query"]["mos_min"]
        return radar_app.CacheResult(kwargs["loader"](), "miss", 0.0)

    monkeypatch.setattr(radar_app, "load_signals", fake_load_signals)
    monkeypatch.setattr(radar_app, "get_or_load_public_payload", fake_cache)

    response = radar_app.app.test_client().get(f"/api/signals{query}")

    assert response.status_code == 200
    assert captured == {"cache": expected, "loader": expected}
```

- [ ] **Step 2: Add database-backed threshold and count parity coverage**

In `tests/test_guest_visibility.py`, add a helper that inserts a complete clean signal at an exact displayed MOS and a test using 12.0 and 16.0:

```python
def _seed_signal_at_mos(self, slug: str, mos_pct: float) -> int:
    from db.connection import get_conn

    actual = 20.0
    fair = actual / (1.0 - mos_pct / 100.0)
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO listings (
                source, source_id, url, title, description, ward,
                area_m2, property_type, price_ty, price_per_m2,
                probably_sold, possibly_duplicate, posted_at, crawled_at
            ) VALUES (
                'facebook', ?, ?, ?, 'MOS boundary fixture', ?,
                100, 'dat_nen', 2.0, 20.0, 0, 0, datetime('now'), datetime('now')
            )
            """,
            (
                f"{slug}-{self.token}",
                f"{self.url_prefix}/{slug}",
                f"Signal MOS {mos_pct}",
                self.ward,
            ),
        )
        listing_id = cur.lastrowid
        self.listing_ids.append(listing_id)
        conn.execute(
            """
            INSERT INTO valuation_results (
                listing_id, fair_ppm2, actual_ppm2, mos_pct, is_signal,
                signal_score, source_quality_flags
            ) VALUES (?, ?, ?, ?, 1, 50, '')
            """,
            (listing_id, fair, actual, mos_pct),
        )
        return listing_id


def test_default_signal_feed_and_counts_start_at_fifteen(self):
    low_id = self._seed_signal_at_mos("mos-12", 12.0)
    high_id = self._seed_signal_at_mos("mos-16", 16.0)
    query = f"city=Khac&ward={self.ward}&limit=100"

    default_payload = self.client.get(f"/api/signals?{query}").get_json()
    crafted_payload = self.client.get(f"/api/signals?{query}&mos_min=10").get_json()
    count_payload = self.client.get(f"/api/counts?{query}").get_json()

    default_ids = {row["id"] for row in default_payload["signals"]}
    crafted_ids = {row["id"] for row in crafted_payload["signals"]}
    assert low_id not in default_ids
    assert low_id not in crafted_ids
    assert high_id in default_ids
    assert high_id in crafted_ids
    assert count_payload["stats"]["signals"] == default_payload["total"]
```

Extend the existing Free session test so its 12% `is_signal=1` row remains hidden for both `mos_min=10` and `mos_min=25`, proving Free cannot lower or raise the fixed product threshold.

- [ ] **Step 3: Add read-model RED assertions**

In `tests/test_signal_read_model.py`, change the Guest count expectation from `10.0 in params` to:

```python
assert 15.0 in params
assert 10.0 not in params
```

Add a parameterized loader/count defense test:

```python
@pytest.mark.parametrize(
    ("tier", "requested", "expected"),
    [
        ("guest", 10, 15.0),
        ("free", 10, 15.0),
        ("vip", 10, 10.0),
        ("admin", 10, 10.0),
    ],
)
def test_read_model_enforces_tier_mos_policy(monkeypatch, tier, requested, expected):
    from services import signal_read_model

    captured = {}

    def fake_filters(**kwargs):
        captured["mos_min"] = kwargs["mos_min"]
        return "TRUE", []

    class _Cursor:
        def fetchone(self):
            return {"signals": 0}

    class _Connection:
        def execute(self, _sql, _params=None):
            return _Cursor()

    monkeypatch.setattr(signal_read_model, "build_signal_read_model_filters", fake_filters)
    signal_read_model.count_signals_from_read_model(
        _Connection(), tier=tier, mos_min=requested
    )
    assert captured["mos_min"] == expected
```

- [ ] **Step 4: Run the focused RED suite**

```powershell
& $py -X utf8 -m pytest tests\test_guest_visibility.py tests\test_market_data_performance.py tests\test_signal_read_model.py -q
```

Expected: failures show the current 10% Guest/Free defaults and unnormalized VIP/Admin missing values.

- [ ] **Step 5: Normalize once at request parsing and enforce again at service boundaries**

In `services/market_data.py`, import the Task 1 interfaces. Replace the integer parser in `get_base_filters()` with:

```python
requested_mos = req.args.get("mos_min")
mos_was_explicit = "mos_min" in req.args

tier = "guest"
try:
    from auth.core import current_tier as _current_tier
    tier = _current_tier()
except Exception:
    pass

mos_min = effective_signal_mos_min(
    tier,
    requested_mos,
    was_explicit=mos_was_explicit,
)
if tier == "guest":
    only_drops = False
```

Keep the existing source normalization and return tuple unchanged. Update `build_deal_sql()` so `None` falls back to `DEFAULT_SIGNAL_MOS_MIN_PCT`, not 10.

Change the signal-facing function defaults from `mos_min=0` to `mos_min=DEFAULT_SIGNAL_MOS_MIN_PCT`, then put this line at the start of `_load_signals_legacy()`, `count_filtered_signals()`, and `load_dashboard_summary()`:

```python
mos_min = effective_signal_mos_min(tier, mos_min, was_explicit=True)
```

Keep `only_drops=False` Guest-only; do not newly disable that separate filter for Free.

- [ ] **Step 6: Apply identical defense-in-depth to the read model**

In `services/signal_read_model.py`, import the policy interfaces, make the signal loader/count defaults 15, and begin both `count_signals_from_read_model()` and `load_signals_from_read_model()` with:

```python
mos_min = effective_signal_mos_min(tier, mos_min, was_explicit=True)
if tier == "guest":
    only_drops = False
```

Do not add a MOS predicate to the materialized read-model refresh itself; it must retain 10–14.9% candidates for explicit VIP/Admin queries.

- [ ] **Step 7: Update existing expectations that conflict with the approved rule**

In `tests/test_market_data_performance.py`, the current Free count test passing `mos_min=18` must expect the captured value `15.0`, because Free is fixed at 15. Keep its source/tier assertions unchanged. Preserve the existing VIP/Admin explicit-filter expectations.

- [ ] **Step 8: Run the feed/count/read-model suite GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_signal_quality.py tests\test_guest_visibility.py tests\test_market_data_performance.py tests\test_signal_read_model.py -q
```

Expected: PASS, including legacy/read-model parity and cache/loader MOS equality.

- [ ] **Step 9: Commit the signal delivery unit**

```powershell
git add services/market_data.py services/signal_read_model.py tests/test_guest_visibility.py tests/test_market_data_performance.py tests/test_signal_read_model.py
git commit -m "fix(signals): default public feeds to MOS 15"
```

---

### Task 3: Align Signals Maps Without Changing Tin Rao

**Files:**
- Modify: `app.py`
- Modify: `services/listing_map.py`
- Modify: `tests/test_listing_map_api.py`
- Modify: `tests/test_listing_map_service.py`

**Interfaces:**
- Consumes: effective `mos_min: float` returned by `get_base_filters()` and the policy from Task 1.
- Produces: `MapFilters.mos_min: float = 15.0`; signals-mode map summary/items use it, while mode `all` query semantics stay unchanged.

- [ ] **Step 1: Write Maps request RED cases**

Replace the existing Guest expectation in `tests/test_listing_map_api.py` and add tier cases around `_listing_map_filters()`:

```python
assert filters.mos_min == 15.0
```

Add:

```python
import pytest


@pytest.mark.parametrize(
    ("tier", "query", "expected"),
    [
        ("guest", "mos_min=10", 15.0),
        ("free", "mos_min=10", 15.0),
        ("vip", "", 15.0),
        ("vip", "mos_min=10", 10.0),
        ("admin", "mos_min=12.5", 12.5),
    ],
)
def test_signal_map_uses_tier_aware_mos(monkeypatch, tier, query, expected):
    import app as app_module

    captured = {}
    monkeypatch.setattr(app_module, "current_tier", lambda: tier)
    monkeypatch.setattr("auth.core.current_tier", lambda: tier)
    def loader(**kwargs):
        captured.update(kwargs)
        return {
            "mode": "signals",
            "summary": {"total": 0, "mapped": 0, "unmapped_count": 0},
            "locations": [],
        }

    monkeypatch.setattr(app_module, "load_listing_map_summary", loader)

    suffix = f"&{query}" if query else ""
    response = app_module.app.test_client().get(
        f"/api/map-listings?mode=signals{suffix}"
    )

    assert response.status_code == 200
    assert captured["mode"] == "signals"
    assert captured["filters"].mos_min == expected
```

- [ ] **Step 2: Add service RED coverage for locked Free and explicit VIP**

In `tests/test_listing_map_service.py`, exercise `_normalized_filters()` directly:

```python
import pytest


@pytest.mark.parametrize(
    ("tier", "requested", "expected"),
    [
        ("guest", 10, 15.0),
        ("free", 25, 15.0),
        ("vip", 10, 10.0),
        ("admin", 20, 20.0),
    ],
)
def test_map_filter_normalization_matches_signal_policy(tier, requested, expected):
    from services.listing_map import MapFilters, _normalized_filters

    normalized = _normalized_filters(MapFilters(mos_min=requested), tier)
    assert normalized.mos_min == expected
```

Retain or add one mode `all` assertion proving its listing query does not include `rm.mos_pct`/valuation filtering.

- [ ] **Step 3: Run Maps tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_api.py tests\test_listing_map_service.py -q
```

Expected: Guest still resolves to 10, Free is not locked, and decimal values are truncated by `int()`.

- [ ] **Step 4: Carry the float policy through Maps**

In `services/listing_map.py`:

```python
from services.signal_quality import (
    DEFAULT_SIGNAL_MOS_MIN_PCT,
    LATEST_VALUATION_CTE,
    effective_signal_mos_min,
)
```

Change the dataclass field to:

```python
mos_min: float = DEFAULT_SIGNAL_MOS_MIN_PCT
```

Change only the MOS normalization entry in `_normalized_filters()` to:

```python
mos_min=effective_signal_mos_min(tier, filters.mos_min, was_explicit=True),
```

In `app.py`, stop truncating the already-normalized value:

```python
mos_min=float(mos_min),
```

Do not alter the `mode == "all"` SQL branch or Tin rao filtering.

- [ ] **Step 5: Run Maps tests GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_api.py tests\test_listing_map_service.py tests\test_guest_visibility.py -q
```

Expected: PASS; signal Maps matches feed policy and Tin rao remains MOS-independent.

- [ ] **Step 6: Commit the Maps unit**

```powershell
git add app.py services/listing_map.py tests/test_listing_map_api.py tests/test_listing_map_service.py
git commit -m "fix(maps): align signal markers with MOS 15"
```

---

### Task 4: Render and Preserve the Correct Homepage Control State

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/main/boot.js`
- Create: `tests/test_homepage_mos_ui.py`
- Modify: `tests/test_refactor_structure.py`

**Interfaces:**
- Consumes: `window.USER_TIER` already rendered by `templates/index.html`.
- Produces: initial `#mosValue`/`#mosSlider` value 15; disabled and visibly locked for Guest/Free; enabled for VIP/Admin; crafted URL MOS is ignored when disabled.

- [ ] **Step 1: Add source-level UI RED tests**

Add to `tests/test_refactor_structure.py`:

```python
def test_homepage_mos_control_defaults_to_fifteen_and_locks_non_privileged_tiers():
    html = _read("templates/index.html")
    boot_js = _read("static/js/main/boot.js")

    assert 'id="mosValue">15</span>%' in html
    assert 'id="mosSlider" min="0" max="70" step="5" value="15"' in html
    assert "USER_TIER not in ['vip', 'admin']" in html
    assert "if (mosSlider && !mosSlider.disabled)" in boot_js


def test_homepage_mos_asset_version_changes_with_boot_behavior():
    html = _read("templates/index.html")
    assert "js/main/boot.js') }}?v=default-signal-mos-15-20260803" in html
```

Create `tests/test_homepage_mos_ui.py` to verify actual Jinja output for every tier:

```python
import re
from unittest import mock

import pytest


@pytest.mark.parametrize(
    ("tier", "locked"),
    [
        ("guest", True),
        ("free", True),
        ("vip", False),
        ("admin", False),
    ],
)
def test_rendered_homepage_mos_control_matches_tier(tier, locked):
    import app as app_module

    app_module.app.config.update(TESTING=True)
    with (
        mock.patch.object(app_module, "current_tier", return_value=tier),
        mock.patch.object(app_module, "current_user", return_value=None),
    ):
        response = app_module.app.test_client().get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    slider = re.search(r'<input[^>]+id="mosSlider"[^>]*>', html, re.S)
    assert slider is not None
    assert 'value="15"' in slider.group(0)
    assert ("disabled" in slider.group(0)) is locked
    assert re.search(r'id="mosValue">\s*15\s*</span>', html)
```

- [ ] **Step 2: Run the UI tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_homepage_mos_ui.py tests\test_refactor_structure.py -q
```

Expected: current markup contains value 10, Guest-only lock logic, and boot applies a crafted URL value to disabled controls.

- [ ] **Step 3: Update the Jinja control**

Use one Jinja flag immediately before the MOS control:

```jinja2
{% set mos_filter_locked = USER_TIER not in ['vip', 'admin'] %}
<div class="command-mos core-filter-callout {% if mos_filter_locked %}tier-locked-filter{% endif %}"
  {% if mos_filter_locked %}aria-disabled="true"{% endif %}>
```

Render the label and slider as:

```jinja2
{% if mos_filter_locked %}🔒 {% endif %}Rẻ hơn ≥ <strong><span id="mosValue">15</span>%</strong>
```

```jinja2
<input type="range" name="mos_min" id="mosSlider" min="0" max="70" step="5" value="15"
  {% if mos_filter_locked %}disabled{% endif %}
  aria-label="Biên an toàn tối thiểu"
  oninput="syncCoreFilterVisuals()"
  onchange="scheduleApplyFilters()">
```

Leave the separate `only_drops` Guest-only behavior unchanged.

- [ ] **Step 4: Prevent URL hydration from changing locked UI state**

In `static/js/main/boot.js`, change the URL hydration guard to:

```javascript
const initialMosMin = searchParams.get('mos_min');
if (initialMosMin !== null) {
  const mosSlider = document.getElementById('mosSlider');
  if (mosSlider && !mosSlider.disabled) mosSlider.value = initialMosMin;
}
```

Update the boot asset query in the template to `default-signal-mos-15-20260803`.

- [ ] **Step 5: Run Python structure and JavaScript syntax checks**

```powershell
& $py -X utf8 -m pytest tests\test_homepage_mos_ui.py tests\test_refactor_structure.py -q
node --check static\js\main\boot.js
```

Expected: PASS.

- [ ] **Step 6: Commit the homepage unit**

```powershell
git add templates/index.html static/js/main/boot.js tests/test_homepage_mos_ui.py tests/test_refactor_structure.py
git commit -m "fix(homepage): default signal filter to MOS 15"
```

---

### Task 5: Align Default Alerts and Public Reports

**Files:**
- Modify: `cli/notify.py`
- Modify: `services/monthly_report_data.py`
- Modify: `tests/test_vip_notify.py`
- Modify: `tests/test_monthly_report_data.py`

**Interfaces:**
- Consumes: `DEFAULT_SIGNAL_MOS_MIN_PCT` and `effective_signal_mos_min()`.
- Produces: watchlist `mos_min` absent/zero uses 15, explicit positive VIP/Admin watchlist MOS is retained, and default public report queries bind MOS 15.

- [ ] **Step 1: Write alert RED tests**

Change `_insert_watchlist()` in `tests/test_vip_notify.py` to accept `mos_min=0`, and `_insert_signal()` to accept `mos_pct=28.0`; bind those arguments in the existing SQL. Add:

```python
def test_default_watchlist_excludes_candidate_below_fifteen(self):
    from cli.notify import push_new_listings_to_vip

    vip_id = self._insert_user("vip", "vip-default-15", self.vip_expires)
    self._insert_watchlist(vip_id, mos_min=0)
    self._insert_signal(mos_pct=12.0)

    with mock.patch("alerts.telegram.send_watchlist_digest", return_value=True) as send:
        stats = push_new_listings_to_vip(since=self.since)

    self.assertEqual(stats["matched_users"], 0)
    send.assert_not_called()


def test_explicit_ten_watchlist_keeps_candidate_below_fifteen(self):
    from cli.notify import push_new_listings_to_vip

    vip_id = self._insert_user("vip", "vip-explicit-10", self.vip_expires)
    self._insert_watchlist(vip_id, mos_min=10)
    listing_id = self._insert_signal(mos_pct=12.0)

    with mock.patch("alerts.telegram.send_watchlist_digest", return_value=True) as send:
        stats = push_new_listings_to_vip(since=self.since)

    self.assertEqual(stats["matched_users"], 1)
    self.assertEqual(send.call_args.args[1][0]["id"], listing_id)
```

- [ ] **Step 2: Write report SQL RED assertions**

In both query tests in `tests/test_monthly_report_data.py`, add:

```python
assert "COALESCE(v.mos_pct, 0) >= ?" in sql
assert 15.0 in params
```

For `actionable_count_query()`, replace the old date-tail assertion with:

```python
assert params[-3:] == ["2026-06-01", "2026-07-01", 15.0]
```

For `featured_records_query()`, keep `params[-1] == 6` and add:

```python
assert params[-2] == 15.0
```

- [ ] **Step 3: Run alert/report tests and confirm RED**

```powershell
& $py -X utf8 -m pytest tests\test_vip_notify.py tests\test_monthly_report_data.py -q
```

Expected: default watchlist admits the 12% candidate and report SQL has no explicit 15% predicate.

- [ ] **Step 4: Apply the default only at the watchlist matching boundary**

In `cli/notify.py`, import `effective_signal_mos_min`. Replace the current truthy MOS check with:

```python
requested_mos = watchlist.get("mos_min")
mos_was_explicit = requested_mos not in (None, "", 0, 0.0, "0")
mos_min = effective_signal_mos_min(
    "vip",
    requested_mos,
    was_explicit=mos_was_explicit,
)
if float(listing.get("mos_pct") or 0) < mos_min:
    return False
```

Do not add 15 to `_fetch_new_signals()`: it must continue retrieving all actionable internal candidates so an explicit 10% watchlist can match them.

- [ ] **Step 5: Bind MOS 15 in default report queries**

In `services/monthly_report_data.py`, import `DEFAULT_SIGNAL_MOS_MIN_PCT`. Add this SQL line after `actionable_signal_sql("v")` in both `actionable_count_query()` and `featured_records_query()`:

```sql
  AND COALESCE(v.mos_pct, 0) >= ?
```

Append `DEFAULT_SIGNAL_MOS_MIN_PCT` to parameters before an optional property type and before the featured-card limit. Keep parameter ordering explicit:

```python
params.append(DEFAULT_SIGNAL_MOS_MIN_PCT)
if property_type:
    type_sql = " AND l.property_type = ?"
    params.append(property_type)
```

For featured records return:

```python
return sql, [*params, DEFAULT_SIGNAL_MOS_MIN_PCT, max(1, min(int(limit), 50))]
```

- [ ] **Step 6: Run alert/report tests GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_vip_notify.py tests\test_monthly_report_data.py -q
```

Expected: PASS; default alerts/reports exclude 10–14.9%, explicit watchlist 10 still includes them.

- [ ] **Step 7: Commit the alert/report unit**

```powershell
git add cli/notify.py services/monthly_report_data.py tests/test_vip_notify.py tests/test_monthly_report_data.py
git commit -m "fix(signals): apply MOS 15 to default alerts and reports"
```

---

### Task 6: Document the Product Contract and Verify the Complete Change

**Files:**
- Modify: `docs/product_rules.md`
- Modify: `docs/operations.md`
- Modify: `docs/superpowers/specs/2026-08-03-default-signal-mos-15-design.md`

**Interfaces:**
- Consumes: all behavior and test evidence from Tasks 1–5.
- Produces: durable documentation that distinguishes the 10% internal candidate floor from the 15% user-facing default and records the no-reprocess rollout.

- [ ] **Step 1: Update product rules with exact semantics**

Add under Signal Semantics in `docs/product_rules.md`:

```markdown
- `SIGNAL_MOS_THRESHOLD=0.10` is the internal valuation-candidate boundary; it is not the default public Săn Deal threshold.
- The default user-facing signal minimum is `DEFAULT_SIGNAL_MOS_MIN_PCT=15.0` across feed, badge/counts, dashboard, signals Maps, default alerts, and public reports.
- Guest and Free are fixed at MOS 15 even when a request supplies `mos_min`; VIP and Admin default to 15 and may explicitly select 10 to inspect eligible 10–14.9% candidates.
- Keep `actionable_signal_sql()` candidate-oriented. Apply the user-facing MOS floor at the consumer/request boundary so no valuation reprocess is required.
```

- [ ] **Step 2: Add the deployment and cache runbook**

Add to `docs/operations.md`:

```markdown
### Publish a default signal-policy change

1. Deploy the tested commit with `scripts/deploy_production.ps1`.
2. On the active VPS release run `/opt/radar-bds/.venv/bin/python -X utf8 radar.py signal-read-model --refresh --compare --limit 200`.
3. Confirm the durable `signals` dataset version and Redis mirror advanced together, then wait for or purge the prior anonymous API edge-cache entries.
4. Verify default and crafted Guest requests contain no `mos_pct_display < 15`, `/api/counts` equals `/api/signals total`, and signals Maps uses the same count.
5. Verify an authenticated VIP/Admin explicit `mos_min=10` request; if production has no eligible 10–14.9% row, record the zero-row DB fact and use query/test evidence instead of fabricating a browser example.
6. Verify Tin rao and non-admin redaction are unchanged.
```

- [ ] **Step 3: Mark the approved spec as implemented only after tests pass**

Change the spec status to:

```markdown
**Status:** Approved and implemented; production verification recorded in the release handoff
```

Do not use this status before Tasks 1–5 are GREEN.

- [ ] **Step 4: Run focused static checks**

```powershell
& $py -X utf8 -m py_compile app.py services\signal_quality.py services\market_data.py services\signal_read_model.py services\listing_map.py services\monthly_report_data.py cli\notify.py
node --check static\js\main\boot.js
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 5: Run the complete relevant test matrix**

```powershell
& $py -X utf8 -m pytest tests\test_signal_quality.py tests\test_guest_visibility.py tests\test_market_data_performance.py tests\test_signal_read_model.py tests\test_listing_map_api.py tests\test_listing_map_service.py tests\test_homepage_mos_ui.py tests\test_refactor_structure.py tests\test_vip_notify.py tests\test_monthly_report_data.py -q
```

Expected: PASS with no skipped test introduced for this feature.

- [ ] **Step 6: Commit documentation and verification contract**

```powershell
git add docs/product_rules.md docs/operations.md docs/superpowers/specs/2026-08-03-default-signal-mos-15-design.md
git commit -m "docs(signals): record MOS 15 rollout contract"
```

---

### Task 7: Rebase, Deploy, Republish, and Prove Production

**Files:**
- Verify only; no planned source edits.

**Interfaces:**
- Consumes: all commits and test evidence from Tasks 1–6.
- Produces: `origin/main`, the active VPS release, refreshed signal dataset/cache versions, and live public/authenticated evidence for the approved contract.

- [ ] **Step 1: Inspect scope and exclude unrelated files**

```powershell
git status --short
git diff --stat origin/main...HEAD
git log --oneline origin/main..HEAD
```

Expected: only the planned MOS docs/code/tests are committed. Do not stage `.playwright-cli/` or any unrelated user file.

- [ ] **Step 2: Rebase onto current remote main**

```powershell
git fetch origin
git rebase origin/main
```

Expected: clean rebase. Resolve only overlapping MOS changes and preserve newer remote work.

- [ ] **Step 3: Rerun static and focused verification after rebase**

```powershell
& $py -X utf8 -m py_compile app.py services\signal_quality.py services\market_data.py services\signal_read_model.py services\listing_map.py services\monthly_report_data.py cli\notify.py
node --check static\js\main\boot.js
& $py -X utf8 -m pytest tests\test_signal_quality.py tests\test_guest_visibility.py tests\test_market_data_performance.py tests\test_signal_read_model.py tests\test_listing_map_api.py tests\test_listing_map_service.py tests\test_homepage_mos_ui.py tests\test_refactor_structure.py tests\test_vip_notify.py tests\test_monthly_report_data.py -q
git diff --check origin/main...HEAD
```

Expected: all commands exit 0.

- [ ] **Step 4: Push the reviewed branch to main**

```powershell
git push origin HEAD:main
```

Expected: remote `main` advances without force push.

- [ ] **Step 5: Deploy through the standard script**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy_production.ps1
```

Expected: the deployed release commit equals pushed `main`, readiness polling succeeds, and `radar-bds.service` is active.

- [ ] **Step 6: Refresh and compare the production signal read model**

On the VPS active release:

```bash
cd /opt/radar-bds/current
/opt/radar-bds/.venv/bin/python -X utf8 radar.py signal-read-model --refresh --compare --limit 200
systemctl is-active radar-bds.service
```

Expected: refresh and comparison succeed, the service prints `active`, and the durable/Redis signal dataset versions agree. This refresh republishes existing candidates; it does not rerun valuation.

- [ ] **Step 7: Remove stale anonymous edge results safely**

Use the already-authenticated Cloudflare dashboard to purge only the affected Radar BDS homepage/API URLs if per-URL purge is available; otherwise purge the `radarbds.vn` cache once after confirming the new service is ready. Do not change DNS, proxy status, SSL mode, WAF, or cache rules.

Affected URLs:

```text
https://radarbds.vn/
https://radarbds.vn/api/dashboard
https://radarbds.vn/api/counts
https://radarbds.vn/api/signals
https://radarbds.vn/api/map-listings?mode=signals
```

- [ ] **Step 8: Prove Guest API consistency**

Fetch default and crafted Guest URLs with a fresh client. Record status, `X-Radar-Dataset-Version`, `X-Radar-Cache`, `Cache-Control`, total, and minimum returned `mos_pct_display` for:

```text
/api/signals?page=1&limit=100
/api/signals?page=1&limit=100&mos_min=10
/api/counts
/api/dashboard
/api/map-listings?mode=signals
```

Expected:

```text
all statuses = 200
min signal mos_pct_display >= 15.0
crafted Guest total = default Guest total
/api/counts stats.signals = /api/signals total
/api/dashboard stats.signals = /api/signals total for the same filters
signals Maps total = signal feed total for the same filters
anonymous cache control remains public; no Set-Cookie is added
```

- [ ] **Step 9: Prove VIP/Admin explicit 10 without exposing credentials**

Using an existing safe authenticated browser session or test account, request `/api/signals?page=1&limit=100&mos_min=10`. Confirm the effective filter remains 10 and, if the production DB contains an actionable 10–14.9% candidate, confirm that row appears while its URL/phone exposure still follows the tier policy. Do not print cookies, bearer tokens, passwords, phone numbers, or source URLs in logs or the handoff.

If the DB contains no such row, record the count query result as zero and cite the passing integration/query tests as behavioral proof; do not weaken the threshold or alter data to manufacture evidence.

- [ ] **Step 10: Prove browser behavior and Tin rao non-regression**

At desktop and a 390px rendered viewport:

```text
Guest: MOS label/value = 15, control disabled, crafted ?mos_min=10 remains visually 15
Free: MOS label/value = 15, control disabled
VIP/Admin: default = 15, control enabled, explicit 10 remains selected
Săn Deal badge is non-zero when the API total is non-zero and equals that total
Xem trên maps opens signal markers whose summary follows the same MOS threshold
Tin rao loads and its count/items are unchanged by MOS
No console error; no horizontal overflow; mobile map detail remains above the bottom bar
```

- [ ] **Step 11: Record final evidence and rollback point**

Record the pushed commit, deployed release path, service status, dataset versions, test totals, API totals/minimum MOS, cache headers, and browser viewport evidence. If rollback is needed, revert only the scoped MOS commits, redeploy, republish the signal dataset version, and clear affected caches; never rewrite listings, valuations, reviews, crawler data, or user data.
