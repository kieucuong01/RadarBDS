# Listing Maps Automatic Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group nearby-road listings into their referenced road marker, remove the Maps GIS block, and add a free browser-assisted workflow that automatically accepts only high-confidence Google Maps suggestions into a deterministic registry.

**Architecture:** The existing map-only context extractor continues to distinguish direct, nearby, and alley relations, but the resolver emits one road location identity for all successfully matched road references. A new pure evidence evaluator validates bounded browser observations and writes accepted entries to a separate auto-override file; the registry builder merges manual overrides first and accepted auto-overrides second. Google Maps browsing remains an agent-operated offline maintenance step, never a public request-time or crawl dependency.

**Tech Stack:** Python 3.12, Flask, PostgreSQL, Shapely, Leaflet, vanilla JavaScript, pytest, Node syntax checks, PowerShell release scripts, Codex Browser control.

## Global Constraints

- Use the existing isolated worktree at `C:\Users\ASUS\Documents\Claude\Projects\Radar BDS\.worktrees\listing-maps-planning`.
- Rebase the approved spec commit onto the latest `origin/main` before implementation.
- Use PostgreSQL via `DATABASE_URL`; never print, copy, or commit credentials.
- Do not write browser-derived values into canonical `listings` columns or valuation fields.
- Do not browse Google Maps during crawl, reprocess, API, or page rendering.
- Do not use a paid Google API.
- Do not automate CAPTCHA solving, login bypasses, or high-volume scraping.
- Manual override precedence is absolute.
- Auto-accept only when every hard gate passes and confidence is at least `0.90`.
- Quarantined candidates retain landmark/ward fallback and never receive guessed coordinates.
- For one compatibility release, the API returns `nearby_count: 0`; the UI does not render it.
- Stage only explicit task files. Preserve unrelated dirty changes.
- Every behavior change follows RED → GREEN → focused regression → commit.
- The final release is commit → push → `origin/main` → deploy → production backfill → production browser proof.

---

### Task 1: Align the worktree with production main and establish a clean baseline

**Files:**
- Verify: `docs/superpowers/specs/2026-07-29-listing-map-auto-registry-design.md`
- Verify: existing Maps implementation and test files

**Interfaces:**
- Consumes: approved design commit `8ae7d13`
- Produces: a clean branch based on latest `origin/main`, with the approved
  design and implementation-plan commits preserved

- [ ] **Step 1: Verify the worktree and fetch current main**

Run:

```powershell
$wt = "C:/Users/ASUS/Documents/Claude/Projects/Radar BDS/.worktrees/listing-maps-planning"
git -c safe.directory=$wt status --short --branch
git -c safe.directory=$wt fetch origin main
git -c safe.directory=$wt log --oneline --decorate --max-count=12 --all
```

Expected: only the committed design and implementation-plan documents differ
from the old Maps release history; no uncommitted files are present.

- [ ] **Step 2: Rebase the design commit onto current main**

Run:

```powershell
$wt = "C:/Users/ASUS/Documents/Claude/Projects/Radar BDS/.worktrees/listing-maps-planning"
git -c safe.directory=$wt rebase --onto origin/main de34b583d0cb235e5dd3774e51f2bb1a4f301df5
```

Expected: the approved design and implementation-plan commits become the only
branch commits above current `origin/main`.

- [ ] **Step 3: Verify Maps baseline tests**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest `
  tests\test_listing_map_context.py `
  tests\test_listing_location_resolver.py `
  tests\test_listing_location_registry.py `
  tests\test_listing_location_backfill.py `
  tests\test_listing_location_coverage.py `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_js.py `
  tests\test_listing_map_ui.py -q
```

Expected: all baseline Maps tests pass before production code changes.

- [ ] **Step 4: Record the clean baseline**

Run:

```powershell
git status --short
git rev-parse HEAD
git merge-base --is-ancestor origin/main HEAD
```

Expected: clean status and `origin/main` is an ancestor of `HEAD`.

---

### Task 2: Resolve nearby and alley references to the referenced road identity

**Files:**
- Modify: `services/listing_location_resolver.py:394-689`
- Modify: `tests/test_listing_location_resolver.py:91-115`
- Modify: `tests/test_listing_location_backfill.py`

**Interfaces:**
- Consumes: `MapLocationContext.nearby_road`, `relation`, and `distance_m`
- Produces: `ResolvedLocation(precision="road", relation="near"|"alley")` using the same `location_key` as a direct reference to the same scoped road

- [ ] **Step 1: Replace old nearby precision assertions with failing road-group assertions**

Add or update these tests in `tests/test_listing_location_resolver.py`:

```python
def test_nearby_and_direct_references_share_one_road_location_key():
    direct = _resolve(text="Mặt tiền DX43")
    nearby = _resolve(text="Cách DX43 100m")
    alley = _resolve(text="1 sẹc đường DX43")

    assert direct.location.precision == "road"
    assert nearby.location.precision == "road"
    assert alley.location.precision == "road"
    assert {
        direct.location.location_key,
        nearby.location.location_key,
        alley.location.location_key,
    } == {"road:thu-dau-mot:phu-loi:dx-43"}
    assert nearby.location.relation == "near"
    assert alley.location.relation == "alley"
```

```python
def test_nearby_road_keeps_landmark_scope_without_creating_nearby_key():
    result = _resolve(
        text="Cách Đường số 35 100m, TĐC Phú Chánh B"
    )

    assert result.location.precision == "road"
    assert result.location.location_key == (
        "road:thu-dau-mot:phu-tan:duong-so-35:tdc-phu-chanh-b"
    )
    assert result.location.reference_road == "duong so 35"
    assert result.location.relation == "near"
```

- [ ] **Step 2: Run the two tests and verify RED**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest `
  tests\test_listing_location_resolver.py::test_nearby_and_direct_references_share_one_road_location_key `
  tests\test_listing_location_resolver.py::test_nearby_road_keeps_landmark_scope_without_creating_nearby_key -q
```

Expected: FAIL because current code emits `precision="nearby"` and a `nearby:` key.

- [ ] **Step 3: Extract one scoped road-key helper**

Add near `_slug` in `services/listing_location_resolver.py`:

```python
def _road_location_key(
    city: str,
    ward: str,
    road: str,
    landmark: str = "",
) -> str:
    key = f"road:{_slug(city)}:{_slug(ward)}:{_slug(road)}"
    if landmark:
        key += f":{_slug(landmark)}"
    return key
```

Use this helper for direct-road resolution instead of duplicating string construction.

- [ ] **Step 4: Change the resolved nearby-road branch**

In the `if nearby_road:` branch, keep `_match_road(...)` and all ambiguity/not-found handling. For a matched road, create:

```python
resolved = _resolved_from_entry(
    listing_id=listing_id,
    precision="road",
    location_key=_road_location_key(
        city,
        ward,
        nearby_road,
        landmark_key if landmark_entry else "",
    ),
    entry=road_entry,
    resolver_version=registry.resolver_version,
    signature=signature,
    relation=relation or "near",
    reference_road=nearby_road,
    landmark_key=landmark_key if landmark_entry else "",
)
```

Do not pass `accuracy_radius_m` for the road group. Retain the existing unresolved, ambiguity, and coverage-issue branches.

- [ ] **Step 5: Add a backfill regression proving legacy nearby rows become road rows**

In `tests/test_listing_location_backfill.py`, add a candidate whose existing row has:

```python
{
    "existing_location_precision": "nearby",
    "existing_location_key": "nearby:thu-dau-mot:phu-loi:dx-43:near",
    "existing_resolver_version": "osm-binh-duong-20260729-v2",
}
```

Assert the backfill upserts:

```python
assert written[0].precision == "road"
assert written[0].location_key == "road:thu-dau-mot:phu-loi:dx-43"
assert written[0].relation == "near"
```

- [ ] **Step 6: Run resolver and backfill tests**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_context.py `
  tests\test_listing_location_resolver.py `
  tests\test_listing_location_backfill.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the resolver behavior**

Run:

```powershell
git add `
  services/listing_location_resolver.py `
  tests/test_listing_location_resolver.py `
  tests/test_listing_location_backfill.py
git commit -m "fix: group nearby listings by referenced road"
```

---

### Task 3: Remove nearby visuals and the official GIS block

**Files:**
- Modify: `templates/partials/listing_map_workspace.html`
- Modify: `static/js/main/listing_map.js`
- Modify: `static/css/main/listing_map.css`
- Modify: `services/listing_map.py`
- Modify: `app.py:1412,4127-4129`
- Modify: `tests/test_listing_map_js.py`
- Modify: `tests/test_listing_map_ui.py`
- Modify: `tests/test_listing_map_api.py`
- Modify: `tests/test_listing_map_service.py`

**Interfaces:**
- Consumes: active precision values `exact`, `road`, `landmark`, and `ward`
- Produces: a map with no nearby circle/counter and no outbound GIS block; API compatibility field `nearby_count` is always `0`

- [ ] **Step 1: Write failing template and JavaScript source-contract tests**

Replace the GIS-link test in `tests/test_listing_map_ui.py` with:

```python
def test_workspace_omits_official_gis_and_nearby_visuals():
    template = _read("templates/partials/listing_map_workspace.html")
    script = _read("static/js/main/listing_map.js")
    styles = _read("static/css/main/listing_map.css")

    assert "listing-map-official-gis" not in template
    assert "listingMapOfficialGisLink" not in script
    assert "listing_map_official_gis_opened" not in script
    assert 'root.L.circle(' not in script
    assert "listing-map-precision-nearby" not in styles
    assert "Gần đúng" not in template
```

Update precision expectations in `tests/test_listing_map_js.py`:

```python
def test_precision_contract_has_no_nearby_copy():
    assert _run_node("mapApi.precisionCopy('road').badge") == "Theo tên đường"
    assert _run_node("mapApi.precisionCopy('landmark').badge") == "Theo khu vực"
    assert _run_node("mapApi.precisionCopy('ward').badge") == "Theo trung tâm phường"
    assert _run_node("mapApi.precisionCopy('nearby').badge") == "Theo tên đường"
```

The last assertion is a compatibility fallback only; no active group may use `nearby`.

- [ ] **Step 2: Write failing API/service tests**

In `tests/test_listing_map_service.py`, remove the nearby fixture group and assert:

```python
assert summary["nearby_count"] == 0
assert (
    summary["exact_count"]
    + summary["road_count"]
    + summary["landmark_count"]
    + summary["ward_count"]
    == summary["mapped"]
)
assert {group["precision"] for group in payload["locations"]} <= {
    "exact",
    "road",
    "landmark",
    "ward",
}
```

In `tests/test_listing_map_api.py`, assert:

```python
response = client.get(
    "/api/map-listing-items"
    "?mode=signals"
    "&location_key=nearby:thu-dau-mot:phu-loi:dx-43:near"
    "&page=1"
)
assert response.status_code == 400
assert "listing_map_official_gis_opened" not in LISTING_MAP_EVENTS
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_js.py `
  tests\test_listing_map_ui.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_service.py -q
```

Expected: FAIL on the existing GIS block, nearby circle, nearby counter, and API key regex.

- [ ] **Step 4: Remove the GIS template and styles**

Delete the complete `.listing-map-official-gis` block from
`templates/partials/listing_map_workspace.html`.

Delete only selectors dedicated to:

```css
.listing-map-official-gis
.listing-map-official-gis-copy
.listing-map-official-gis-link
```

Remove `.listing-map-precision-nearby` from shared precision selectors without changing exact/road/landmark/ward styles.

- [ ] **Step 5: Remove nearby circle rendering and GIS tracking**

In `static/js/main/listing_map.js`:

- remove the `if (group.precision === "nearby")` block that calls `L.circle`;
- remove the `nearby` style/copy object;
- make `precisionCopy("nearby")` fall back to the road copy;
- remove the nearby summary card;
- remove `listingMapOfficialGisLink` binding and
  `listing_map_official_gis_opened` emission.

The marker loop must retain:

```javascript
var marker = root.L.circleMarker(
  [lat, lng],
  markerStyle(group.precision)
);
```

- [ ] **Step 6: Enforce the four-precision API contract**

In `app.py`, change:

```python
_LISTING_MAP_LOCATION_KEY_RE = re.compile(
    r"^(exact|road|landmark|ward):[a-z0-9:-]+$"
)
```

Remove `listing_map_official_gis_opened` from the map analytics allowlist.

In `services/listing_map.py`:

- stop counting nearby rows as active mapped precision;
- return `"nearby_count": 0`;
- preserve the invariant using exact + road + landmark + ward;
- keep compact SQL and public redaction unchanged.

- [ ] **Step 7: Run UI/API/service tests and JS syntax**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_js.py `
  tests\test_listing_map_ui.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_service.py -q
node --check static\js\main\listing_map.js
```

Expected: PASS with no GIS or nearby visual contract.

- [ ] **Step 8: Commit the public map cleanup**

Run:

```powershell
git add `
  app.py `
  services/listing_map.py `
  templates/partials/listing_map_workspace.html `
  static/js/main/listing_map.js `
  static/css/main/listing_map.css `
  tests/test_listing_map_js.py `
  tests/test_listing_map_ui.py `
  tests/test_listing_map_api.py `
  tests/test_listing_map_service.py
git commit -m "feat: simplify listing map road groups"
```

---

### Task 4: Add deterministic browser evidence parsing and confidence gates

**Files:**
- Create: `services/listing_location_auto_registry.py`
- Create: `tests/test_listing_location_auto_registry.py`
- Modify: `config/listing_map.py`

**Interfaces:**
- Produces: `BrowserLocationEvidence.from_mapping(data) -> BrowserLocationEvidence`
- Produces: `parse_google_maps_coordinates(url) -> tuple[float, float] | None`
- Produces: `evaluate_browser_evidence(evidence, *, manual_keys, ward_contains) -> AutoRegistryDecision`
- Produces: `canonical_evidence_hash(evidence) -> str`

- [ ] **Step 1: Write failing coordinate-parser tests**

Create `tests/test_listing_location_auto_registry.py`:

```python
import pytest

from services.listing_location_auto_registry import (
    BrowserLocationEvidence,
    canonical_evidence_hash,
    evaluate_browser_evidence,
    parse_google_maps_coordinates,
)


PHU_CHANH_B_URL = (
    "https://www.google.com/maps/place/"
    "Khu+t%C3%A1i+%C4%91%E1%BB%8Bnh+c%C6%B0+Ph%C3%BA+Ch%C3%A1nh+B/"
    "@11.058782,106.7015151,17z/data=!3m1!4b1"
    "!4m6!3m5!1s0x3174cfc3c87ff1b1:0x62a06002cd918551"
    "!8m2!3d11.058782!4d106.7015151!16s%2Fg%2F11ggg3n5ns"
)


def test_google_maps_url_parser_accepts_public_place_coordinates():
    assert parse_google_maps_coordinates(PHU_CHANH_B_URL) == (
        11.058782,
        106.7015151,
    )


def test_google_maps_url_parser_rejects_non_google_and_out_of_bounds_urls():
    assert parse_google_maps_coordinates(
        "https://example.com/@11.058782,106.7015151,17z"
    ) is None
    assert parse_google_maps_coordinates(
        "https://www.google.com/maps/@50.0,5.0,17z"
    ) is None
```

- [ ] **Step 2: Run parser tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_location_auto_registry.py::test_google_maps_url_parser_accepts_public_place_coordinates `
  tests\test_listing_location_auto_registry.py::test_google_maps_url_parser_rejects_non_google_and_out_of_bounds_urls -q
```

Expected: ERROR because the new module does not exist.

- [ ] **Step 3: Implement evidence dataclasses and URL parsing**

Create:

```python
@dataclass(frozen=True)
class BrowserLocationEvidence:
    candidate_key: str
    candidate_type: str
    city: str
    ward: str
    canonical: str
    aliases: tuple[str, ...]
    query: str
    result_title: str
    result_address: str
    result_type: str
    source_url: str
    unique_result: bool
    checked_at: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "BrowserLocationEvidence":
        candidate_type = str(data.get("candidate_type") or "").strip().lower()
        if candidate_type not in {"road", "landmark"}:
            raise ValueError("candidate_type must be road or landmark")
        return cls(
            candidate_key=str(data.get("candidate_key") or "").strip(),
            candidate_type=candidate_type,
            city=str(data.get("city") or "").strip(),
            ward=str(data.get("ward") or "").strip(),
            canonical=str(data.get("canonical") or "").strip(),
            aliases=tuple(str(value).strip() for value in data.get("aliases") or ()),
            query=str(data.get("query") or "").strip(),
            result_title=str(data.get("result_title") or "").strip(),
            result_address=str(data.get("result_address") or "").strip(),
            result_type=str(data.get("result_type") or "").strip(),
            source_url=str(data.get("source_url") or "").strip(),
            unique_result=bool(data.get("unique_result")),
            checked_at=str(data.get("checked_at") or "").strip(),
        )
```

Implement URL parsing for:

```python
_GOOGLE_MAPS_HOSTS = {"google.com", "www.google.com", "maps.google.com"}
_AT_COORDINATES_RE = re.compile(
    r"/@(?P<lat>-?\d+(?:\.\d+)?),(?P<lng>-?\d+(?:\.\d+)?)"
)
_DATA_COORDINATES_RE = re.compile(
    r"!3d(?P<lat>-?\d+(?:\.\d+)?).*?!4d(?P<lng>-?\d+(?:\.\d+)?)"
)
```

Return coordinates only when the host is allowlisted and
`_inside_service_bounds(lat, lng)` passes. Define it locally in the new module
from the existing configured bounds:

```python
def _inside_service_bounds(lat: float, lng: float) -> bool:
    (south, west), (north, east) = LISTING_MAP_BOUNDS
    return south <= lat <= north and west <= lng <= east
```

- [ ] **Step 4: Write failing confidence-gate tests**

Add:

```python
def _phu_chanh_b_evidence(**changes):
    data = {
        "candidate_key": "landmark:thu-dau-mot:phu-tan:tdc-phu-chanh-b",
        "candidate_type": "landmark",
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Tân",
        "canonical": "TĐC Phú Chánh B",
        "aliases": [
            "TDC Phu Chanh B",
            "Khu tái định cư Phú Chánh B",
        ],
        "query": "TĐC Phú Chánh B, Phú Tân, Thủ Dầu Một",
        "result_title": "Khu tái định cư Phú Chánh B",
        "result_address": "Đ. Số 55, Khu TĐC Phú Chánh B",
        "result_type": "Housing complex",
        "source_url": PHU_CHANH_B_URL,
        "unique_result": True,
        "checked_at": "2026-07-29T16:00:00Z",
    }
    data.update(changes)
    return BrowserLocationEvidence.from_mapping(data)


def test_exact_landmark_inside_ward_auto_accepts_at_high_confidence():
    decision = evaluate_browser_evidence(
        _phu_chanh_b_evidence(),
        manual_keys=frozenset(),
        ward_contains=lambda city, ward, lat, lng: True,
    )

    assert decision.status == "accepted"
    assert decision.confidence >= 0.90
    assert decision.override["lat"] == 11.058782
    assert decision.override["lng"] == 106.7015151


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"unique_result": False}, "multiple_or_unselected_result"),
        ({"result_title": "Phú Chánh"}, "title_mismatch"),
        ({"result_type": "Coffee shop"}, "invalid_result_type"),
        ({"source_url": "https://example.com/maps"}, "invalid_source_url"),
    ],
)
def test_low_confidence_evidence_is_quarantined(changes, reason):
    decision = evaluate_browser_evidence(
        _phu_chanh_b_evidence(**changes),
        manual_keys=frozenset(),
        ward_contains=lambda city, ward, lat, lng: True,
    )

    assert decision.status == "quarantined"
    assert reason in decision.reasons
    assert decision.override is None
```

Add a road test requiring exact numeric scope:

```python
def test_numbered_road_requires_full_token_and_ward_or_landmark_scope():
    evidence = _phu_chanh_b_evidence(
        candidate_key="road:thu-dau-mot:phu-tan:duong-so-35",
        candidate_type="road",
        canonical="Đường số 35",
        aliases=["Đường 35"],
        result_title="Đường số 35",
        result_address="Phú Tân, Thủ Dầu Một",
        result_type="Road",
    )
    decision = evaluate_browser_evidence(
        evidence,
        manual_keys=frozenset(),
        ward_contains=lambda city, ward, lat, lng: True,
    )
    assert decision.status == "accepted"
```

- [ ] **Step 5: Run confidence tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_location_auto_registry.py -q
```

Expected: FAIL because evaluation and decisions are not implemented.

- [ ] **Step 6: Implement deterministic evaluation**

Add:

```python
@dataclass(frozen=True)
class AutoRegistryDecision:
    status: str
    confidence: float
    reasons: tuple[str, ...]
    override: Mapping[str, object] | None
```

The evaluator must apply hard gates in this order:

1. unique result;
2. complete evidence fields;
3. valid Google Maps coordinate URL;
4. exact normalized canonical-or-full-alias title match;
5. accepted result type:
   - road: `road`, `route`, `street`;
   - landmark: `housing complex`, `housing development`, `residential area`,
     `neighborhood`, `place`;
6. point inside the scoped ward or address contains the normalized ward;
7. candidate key absent from `manual_keys`;
8. numbered road includes ward or landmark scope.

Use this score only after hard gates pass:

```python
score = 0.50  # exact title/alias
score += 0.20  # valid coordinate and service bounds
score += 0.15  # ward containment or address match
score += 0.10  # accepted result type
score += 0.05  # unique selected result
```

Round confidence to two decimals. Accept only at `>= 0.90`.

- [ ] **Step 7: Implement canonical evidence hashing**

Serialize these fields with `ensure_ascii=False`, `sort_keys=True`, and compact
separators:

```python
{
    "candidate_key": evidence.candidate_key,
    "candidate_type": evidence.candidate_type,
    "city": evidence.city,
    "ward": evidence.ward,
    "canonical": evidence.canonical,
    "aliases": sorted(evidence.aliases),
    "query": evidence.query,
    "result_title": evidence.result_title,
    "result_address": evidence.result_address,
    "result_type": evidence.result_type,
    "source_url": evidence.source_url,
    "unique_result": evidence.unique_result,
    "checked_at": evidence.checked_at,
}
```

Return `hashlib.sha256(encoded).hexdigest()`.

- [ ] **Step 8: Run all evidence tests**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_location_auto_registry.py -q
& $py -X utf8 -m py_compile services\listing_location_auto_registry.py
```

Expected: PASS.

- [ ] **Step 9: Commit the evidence evaluator**

Run:

```powershell
git add `
  config/listing_map.py `
  services/listing_location_auto_registry.py `
  tests/test_listing_location_auto_registry.py
git commit -m "feat: validate browser map evidence"
```

---

### Task 5: Merge accepted auto-overrides deterministically

**Files:**
- Create: `config/listing_map_location_auto_overrides.json`
- Modify: `config/listing_map.py`
- Modify: `scripts/build_listing_location_registry.py`
- Modify: `tests/test_listing_location_registry.py`

**Interfaces:**
- Consumes: auto file `{resolver_version, entries}`
- Produces: `load_combined_location_overrides(manual_path, auto_path) -> dict`
- Produces: manifest fields `auto_overrides_sha256` and `auto_override_count`

- [ ] **Step 1: Create the empty auto-override contract at the current version**

Create:

```json
{
  "resolver_version": "osm-binh-duong-20260729-v2",
  "entries": []
}
```

Keep `LISTING_MAP_RESOLVER_VERSION`, the manual override file, the empty
auto-override file, and existing artifacts at
`osm-binh-duong-20260729-v2` in this task. Task 7 performs the v3 bump in the
same commit as the first accepted entries and rebuilt artifacts, so every
intermediate commit remains internally consistent.

- [ ] **Step 2: Write failing precedence and hash tests**

In `tests/test_listing_location_registry.py`, add:

```python
def test_manual_overrides_win_over_auto_overrides(tmp_path):
    manual = {
        "resolver_version": "test-v3",
        "road_aliases": [],
        "roads": [
            {
                "city": "THỦ DẦU MỘT",
                "ward": "Phú Tân",
                "road_name": "Đường số 35",
                "lat": 11.0636566,
                "lng": 106.6941886,
                "source": "OpenStreetMap",
                "source_url": "https://www.openstreetmap.org/way/225107254",
                "verified_at": "2026-07-29",
            }
        ],
        "landmark_aliases": [],
        "landmarks": [],
    }
    auto = {
        "resolver_version": "test-v3",
        "entries": [
            {
                "status": "accepted",
                "confidence": 0.95,
                "candidate_type": "road",
                "city": "THỦ DẦU MỘT",
                "ward": "Phú Tân",
                "canonical": "Đường số 35",
                "lat": 11.058782,
                "lng": 106.7015151,
                "source": "Google Maps browser suggestion",
                "source_url": (
                    "https://www.google.com/maps/"
                    "@11.058782,106.7015151,17z"
                ),
                "checked_at": "2026-07-29T16:00:00Z",
                "evidence_hash": "0" * 64,
            }
        ],
    }

    combined = combine_location_overrides(manual, auto)

    assert combined["roads"] == manual["roads"]
    assert combined["auto_override_count"] == 0
```

Add:

```python
def test_registry_manifest_hashes_accepted_auto_overrides(tmp_path):
    osm, sources, manual, boundaries = _generated_payloads()
    auto = {
        "resolver_version": manual["resolver_version"],
        "entries": [],
    }
    paths = build_location_registries(
        osm,
        sources,
        tmp_path,
        overrides=manual,
        auto_overrides=auto,
        boundary_paths=(boundaries,),
    )
    manifest = json.loads(paths[3].read_text(encoding="utf-8"))
    assert len(manifest["auto_overrides_sha256"]) == 64
    assert manifest["auto_override_count"] == 0
```

- [ ] **Step 3: Run the two tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_location_registry.py::test_manual_overrides_win_over_auto_overrides `
  tests\test_listing_location_registry.py::test_registry_manifest_hashes_accepted_auto_overrides -q
```

Expected: FAIL because auto-overrides are not accepted by the builder.

- [ ] **Step 4: Implement the merge boundary**

Add:

```python
def combine_location_overrides(
    manual: Mapping[str, object],
    auto: Mapping[str, object],
) -> dict:
    manual_version = str(manual.get("resolver_version") or "")
    auto_version = str(auto.get("resolver_version") or "")
    if manual_version != auto_version:
        raise ValueError("manual and auto override versions must match")

    combined = {
        "resolver_version": manual_version,
        "road_aliases": list(manual.get("road_aliases") or ()),
        "roads": list(manual.get("roads") or ()),
        "landmark_aliases": list(manual.get("landmark_aliases") or ()),
        "landmarks": list(manual.get("landmarks") or ()),
    }
```

Build scoped manual identity sets from normalized city, ward, and canonical
road/landmark. Append only auto entries with:

- `status == "accepted"`;
- `confidence >= 0.90`;
- 64-character hexadecimal `evidence_hash`;
- no manual identity collision.

Convert accepted road entries to the existing curated road shape and accepted
landmarks to the curated landmark shape. Return
`combined["auto_override_count"]`.

- [ ] **Step 5: Extend the builder and CLI input**

Change:

```python
def build_location_registries(
    osm_payload,
    sources,
    output_dir,
    *,
    overrides=None,
    auto_overrides=None,
    boundary_paths=(),
):
```

Add `--auto-overrides` defaulting to
`LISTING_MAP_AUTO_OVERRIDE_PATH`. Load and combine before alias validation.

Manifest additions:

```python
"auto_overrides_sha256": _payload_sha256(auto_overrides),
"auto_override_count": int(combined_overrides["auto_override_count"]),
```

- [ ] **Step 6: Run registry tests and deterministic output checks**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_location_registry.py -q
& $py -X utf8 -m py_compile scripts\build_listing_location_registry.py
```

Expected: PASS and byte-stability tests remain green.

- [ ] **Step 7: Commit deterministic auto-override merge**

Run:

```powershell
git add `
  config/listing_map.py `
  config/listing_map_location_auto_overrides.json `
  scripts/build_listing_location_registry.py `
  tests/test_listing_location_registry.py
git commit -m "feat: merge automatic map overrides"
```

---

### Task 6: Add queue export and automatic evidence ingestion commands

**Files:**
- Modify: `cli/map_locations.py`
- Modify: `radar.py`
- Modify: `services/listing_location_auto_registry.py`
- Create: `tests/test_listing_location_auto_registry_cli.py`
- Modify: `docs/dev_commands.md`

**Interfaces:**
- Produces CLI: `radar.py map-location-research-queue --limit 50 --candidate-type all`
- Produces CLI: `radar.py map-location-ingest-evidence --input evidence.json [--apply]`
- Produces: atomic updates to `config/listing_map_location_auto_overrides.json`

- [ ] **Step 1: Write failing queue-export tests**

Create `tests/test_listing_location_auto_registry_cli.py`:

```python
import json
from types import SimpleNamespace

from cli import map_locations


def _evidence_payload(**changes):
    data = {
        "candidate_key": "landmark:thu-dau-mot:phu-tan:tdc-phu-chanh-b",
        "candidate_type": "landmark",
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Tân",
        "canonical": "TĐC Phú Chánh B",
        "aliases": [
            "TDC Phu Chanh B",
            "Khu tái định cư Phú Chánh B",
        ],
        "query": "TĐC Phú Chánh B, Phú Tân, Thủ Dầu Một",
        "result_title": "Khu tái định cư Phú Chánh B",
        "result_address": "Đ. Số 55, Khu TĐC Phú Chánh B",
        "result_type": "Housing complex",
        "source_url": (
            "https://www.google.com/maps/"
            "@11.058782,106.7015151,17z"
        ),
        "unique_result": True,
        "checked_at": "2026-07-29T16:00:00Z",
    }
    data.update(changes)
    return data


def test_research_queue_outputs_bounded_google_maps_search_urls(monkeypatch):
    monkeypatch.setattr(
        map_locations,
        "load_listing_location_coverage",
        lambda status, limit: [
            {
                "candidate_key": "abc",
                "city": "THỦ DẦU MỘT",
                "ward": "Phú Tân",
                "road_candidate": "",
                "landmark_candidate": "tdc phu chanh b",
                "relation": "at",
                "status": "not_found",
                "affected_listing_count": 25,
                "sample_listing_ids": [1, 2],
                "resolution_note": "landmark_not_found",
            }
        ],
    )
    args = SimpleNamespace(limit=50, candidate_type="all")

    payload = map_locations.cmd_map_location_research_queue(args)

    assert payload["total_candidates"] == 1
    assert payload["items"][0]["query"] == (
        "tdc phu chanh b, Phú Tân, THỦ DẦU MỘT"
    )
    assert payload["items"][0]["search_url"] == (
        "https://www.google.com/maps/search/?api=1&"
        "query=tdc+phu+chanh+b%2C+Ph%C3%BA+T%C3%A2n%2C+"
        "TH%E1%BB%A6+D%E1%BA%A6U+M%E1%BB%98T"
    )
```

- [ ] **Step 2: Write failing dry-run/apply ingestion tests**

Add:

```python
def test_ingest_evidence_dry_run_does_not_write(tmp_path, monkeypatch):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps({"items": [_evidence_payload()]}, ensure_ascii=False),
        encoding="utf-8",
    )
    auto_path = tmp_path / "auto.json"
    auto_path.write_text(
        json.dumps({"resolver_version": "test-v3", "entries": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(map_locations, "LISTING_MAP_AUTO_OVERRIDE_PATH", auto_path)
    monkeypatch.setattr(map_locations, "point_is_in_scoped_ward", lambda *args: True)

    payload = map_locations.cmd_map_location_ingest_evidence(
        SimpleNamespace(input=evidence_path, apply=False)
    )

    assert payload["accepted"] == 1
    assert json.loads(auto_path.read_text(encoding="utf-8"))["entries"] == []
```

```python
def test_ingest_evidence_apply_writes_only_accepted_entries_atomically(
    tmp_path,
    monkeypatch,
):
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "items": [
                    _evidence_payload(),
                    _evidence_payload(unique_result=False),
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    auto_path = tmp_path / "auto.json"
    auto_path.write_text(
        json.dumps({"resolver_version": "test-v3", "entries": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(map_locations, "LISTING_MAP_AUTO_OVERRIDE_PATH", auto_path)
    monkeypatch.setattr(map_locations, "point_is_in_scoped_ward", lambda *args: True)

    payload = map_locations.cmd_map_location_ingest_evidence(
        SimpleNamespace(input=evidence_path, apply=True)
    )

    saved = json.loads(auto_path.read_text(encoding="utf-8"))
    assert payload == {
        "attempted": 2,
        "accepted": 1,
        "quarantined": 1,
        "applied": 1,
    }
    assert len(saved["entries"]) == 1
    assert saved["entries"][0]["status"] == "accepted"
```

- [ ] **Step 3: Run CLI tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_location_auto_registry_cli.py -q
```

Expected: FAIL because commands are absent.

- [ ] **Step 4: Implement queue export**

Add `cmd_map_location_research_queue(args)` to `cli/map_locations.py`:

- load all unresolved statuses;
- sort by descending affected listing count;
- choose `road_candidate` or `landmark_candidate`;
- filter by `candidate_type`;
- limit to `1..50`;
- build query as `candidate, ward, city`;
- build search URL with `urllib.parse.urlencode`;
- print compact JSON without descriptions or sensitive fields.

- [ ] **Step 5: Implement evidence ingestion**

Add `cmd_map_location_ingest_evidence(args)`:

1. load the bounded input JSON;
2. reject more than 50 items;
3. convert each item with `BrowserLocationEvidence.from_mapping`;
4. evaluate with:

```python
decision = evaluate_browser_evidence(
    evidence,
    manual_keys=load_manual_override_keys(),
    ward_contains=point_is_in_scoped_ward,
)
```

5. default to dry-run;
6. on `--apply`, merge accepted decisions by `candidate_key`, sort entries, and
   write UTF-8 LF JSON through a temporary file followed by `os.replace`;
7. never store quarantined browser payloads in the active auto-overrides file.

- [ ] **Step 6: Register both CLI commands**

In `radar.py`:

```python
p_map_queue = sub.add_parser(
    "map-location-research-queue",
    help="Export unresolved map candidates for browser research",
)
p_map_queue.add_argument("--limit", type=int, default=50)
p_map_queue.add_argument(
    "--candidate-type",
    choices=("all", "road", "landmark"),
    default="all",
)

p_map_ingest = sub.add_parser(
    "map-location-ingest-evidence",
    help="Validate and ingest browser map evidence",
)
p_map_ingest.add_argument("--input", type=Path, required=True)
p_map_ingest.add_argument("--apply", action="store_true")
```

Wire both commands in `main()`.

- [ ] **Step 7: Document exact commands**

Add to `docs/dev_commands.md`:

```powershell
& $py -X utf8 radar.py map-location-research-queue `
  --limit 50 `
  --candidate-type all

& $py -X utf8 radar.py map-location-ingest-evidence `
  --input .local\listing-map-evidence\batch.json

& $py -X utf8 radar.py map-location-ingest-evidence `
  --input .local\listing-map-evidence\batch.json `
  --apply
```

State that browser evidence files stay under ignored `.local/` and must not
contain listing descriptions, phone numbers, cookies, or account state.

- [ ] **Step 8: Run CLI and parser tests**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_location_auto_registry.py `
  tests\test_listing_location_auto_registry_cli.py -q
& $py -X utf8 -m py_compile cli\map_locations.py radar.py
```

Expected: PASS.

- [ ] **Step 9: Commit queue and ingestion commands**

Run:

```powershell
git add `
  cli/map_locations.py `
  radar.py `
  services/listing_location_auto_registry.py `
  tests/test_listing_location_auto_registry_cli.py `
  docs/dev_commands.md
git commit -m "feat: automate map registry evidence ingestion"
```

---

### Task 7: Process the initial TĐC browser-research slice

**Files:**
- Modify: `config/listing_map.py`
- Modify: `config/listing_map_location_overrides.json`
- Modify: `config/listing_map_location_auto_overrides.json`
- Modify: `static/maps/listing-locations/manifest.json`
- Modify: `static/maps/listing-locations/road-centers.json`
- Modify: `static/maps/listing-locations/landmark-centers.json`
- Modify: `static/maps/listing-locations/ward-centers.json` only if deterministic rebuild changes its hash
- Modify: `tests/test_listing_location_registry.py`
- Modify: `tests/test_listing_location_resolver.py`
- Runtime evidence only: `.local/listing-map-evidence/2026-07-29-initial.json`

**Interfaces:**
- Consumes: queue export and browser evidence schema from Task 6
- Produces: accepted v3 landmarks/roads and quarantined operational output

- [ ] **Step 1: Export the top landmark and road queues**

Run:

```powershell
& $py -X utf8 radar.py map-location-research-queue `
  --limit 50 `
  --candidate-type landmark
& $py -X utf8 radar.py map-location-research-queue `
  --limit 50 `
  --candidate-type road
```

Capture only the initial exact candidates:

- `TĐC Phú Chánh B`;
- `TĐC Phú Chánh C`;
- `TĐC Phú Chánh D`;
- `TĐC Định Hòa`;
- unresolved numbered/DX roads scoped to those landmarks.

- [ ] **Step 2: Use the Browser skill to collect bounded evidence**

For each candidate:

1. open its generated Google Maps search URL;
2. inspect one selected result;
3. capture title, address, result type, full result URL, and uniqueness;
4. stop and record no result on CAPTCHA, login, ambiguous selection, or page
   contract failure;
5. write a maximum of 50 evidence items to the ignored initial JSON file.

Do not read cookies, local storage, account state, listing descriptions, or
browser history.

- [ ] **Step 3: Dry-run automatic evaluation**

Run:

```powershell
& $py -X utf8 radar.py map-location-ingest-evidence `
  --input .local\listing-map-evidence\2026-07-29-initial.json
```

Expected: JSON totals for attempted, accepted, and quarantined. No tracked file changes.

- [ ] **Step 4: Apply accepted evidence automatically**

Run:

```powershell
& $py -X utf8 radar.py map-location-ingest-evidence `
  --input .local\listing-map-evidence\2026-07-29-initial.json `
  --apply
```

Expected: only decisions at confidence `>= 0.90` appear in
`config/listing_map_location_auto_overrides.json`.

- [ ] **Step 5: Write failing production-registry regressions**

Add:

```python
def test_production_registry_resolves_landmark_only_phu_chanh_b():
    registry = load_location_registry()
    context = extract_map_location_context(
        "Đất TĐC Phú Chánh B, Phú Tân",
        "",
    )
    result = resolve_listing_location(
        {
            "id": 990001,
            "city": "THỦ DẦU MỘT",
            "ward": "Phú Tân",
            "road_name": "",
        },
        registry,
        context,
    )

    assert result.location.precision == "landmark"
    assert result.location.location_key.endswith("tdc-phu-chanh-b")
    assert result.issue is None
```

Keep existing road regressions for Đường 35/37 and add:

```python
def test_production_registry_groups_near_phu_chanh_road_as_road():
    registry = load_location_registry()
    context = extract_map_location_context(
        "1 sẹc Đường số 35, TĐC Phú Chánh B",
        "",
    )
    result = resolve_listing_location(
        {
            "id": 990002,
            "city": "THỦ DẦU MỘT",
            "ward": "Phú Tân",
            "road_name": "",
        },
        registry,
        context,
    )

    assert result.location.precision == "road"
    assert result.location.relation == "alley"
```

- [ ] **Step 6: Run regressions and verify RED before rebuilding**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_location_registry.py::test_production_registry_resolves_landmark_only_phu_chanh_b `
  tests\test_listing_location_resolver.py::test_production_registry_groups_near_phu_chanh_road_as_road -q
```

Expected: the landmark test fails against old artifacts.

- [ ] **Step 7: Bump the resolver version and rebuild deterministic artifacts**

Use the pinned OSM input already retained under ignored `.local/listing-map/`
and the repository source/override files:

First update these three values together to
`osm-binh-duong-20260729-v3`:

- `LISTING_MAP_RESOLVER_VERSION` in `config/listing_map.py`;
- `resolver_version` in `config/listing_map_location_overrides.json`;
- `resolver_version` in `config/listing_map_location_auto_overrides.json`.

Then run:

```powershell
& $py -X utf8 scripts\build_listing_location_registry.py `
  --osm-json .local\listing-map\osm-binh-duong-20260729-v2.json `
  --sources config\listing_map_location_sources.json `
  --overrides config\listing_map_location_overrides.json `
  --auto-overrides config\listing_map_location_auto_overrides.json `
  --output-dir static\maps\listing-locations
```

Run the same command twice and verify the four artifact hashes do not change on
the second build.

- [ ] **Step 8: Run registry and resolver tests**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_location_registry.py `
  tests\test_listing_location_resolver.py `
  tests\test_listing_location_auto_registry.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit accepted initial registry entries**

Run:

```powershell
git add `
  config/listing_map.py `
  config/listing_map_location_overrides.json `
  config/listing_map_location_auto_overrides.json `
  static/maps/listing-locations/manifest.json `
  static/maps/listing-locations/road-centers.json `
  static/maps/listing-locations/landmark-centers.json `
  static/maps/listing-locations/ward-centers.json `
  tests/test_listing_location_registry.py `
  tests/test_listing_location_resolver.py
git commit -m "data: resolve high-confidence map landmarks"
```

Do not stage `.local/listing-map-evidence/`.

---

### Task 8: Add the no-approval maintenance and release runbook

**Files:**
- Create: `docs/listing_map_registry_automation.md`
- Modify: `docs/dev_commands.md`
- Modify: `docs/operations.md`
- Create: `tests/test_listing_map_automation_docs.py`

**Interfaces:**
- Consumes: the queue, browser, ingestion, registry build, backfill, and deploy commands
- Produces: a complete automatic maintenance contract with stop gates rather than approval gates

- [ ] **Step 1: Write failing documentation-contract tests**

Create:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_map_automation_runbook_has_required_commands_and_stop_gates():
    text = (
        ROOT / "docs" / "listing_map_registry_automation.md"
    ).read_text(encoding="utf-8")

    required = (
        "map-location-research-queue",
        "map-location-ingest-evidence",
        "--apply",
        "build_listing_location_registry.py",
        "map-locations --full --dry-run",
        "map-locations --full",
        "deploy_production.ps1",
        "confidence >= 0.90",
        "CAPTCHA",
        "không cần người dùng duyệt",
    )
    for value in required:
        assert value in text
```

- [ ] **Step 2: Run the docs test and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_automation_docs.py -q
```

Expected: FAIL because the runbook does not exist.

- [ ] **Step 3: Write the operational runbook**

Document these exact phases:

1. production coverage snapshot;
2. queue export with maximum 50 candidates;
3. browser evidence collection;
4. dry-run ingestion;
5. automatic apply of accepted entries;
6. deterministic registry double-build;
7. focused tests;
8. full dry-run backfill;
9. commit and push;
10. deploy;
11. full production backfill;
12. API and browser smoke.

Document stop conditions:

- CAPTCHA, login, or browser block;
- page contract missing required evidence;
- manual override conflict;
- confidence below `0.90`;
- non-deterministic artifact hashes;
- any focused test failure;
- backfill invariant failure;
- mapped/ward counts regress unexpectedly;
- deploy or production smoke failure.

State explicitly that a stop condition records/quarantines the candidate and
does not ask the user to approve it.

- [ ] **Step 4: Run docs tests and diff checks**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_map_automation_docs.py -q
git diff --check
```

Expected: PASS.

- [ ] **Step 5: Commit the automatic runbook**

Run:

```powershell
git add `
  docs/listing_map_registry_automation.md `
  docs/dev_commands.md `
  docs/operations.md `
  tests/test_listing_map_automation_docs.py
git commit -m "docs: automate listing map registry maintenance"
```

---

### Task 9: Run full local verification and review the implementation

**Files:**
- Verify all files changed in Tasks 2-8

**Interfaces:**
- Consumes: complete v3 implementation
- Produces: evidence that code, artifacts, UI contracts, privacy, and deterministic output pass locally

- [ ] **Step 1: Run Python and JavaScript syntax checks**

Run:

```powershell
& $py -X utf8 -m py_compile `
  app.py `
  radar.py `
  cli\map_locations.py `
  services\listing_location_auto_registry.py `
  services\listing_location_resolver.py `
  services\listing_location_backfill.py `
  services\listing_map.py `
  scripts\build_listing_location_registry.py
node --check static\js\main\listing_map.js
```

Expected: no output and exit code `0`.

- [ ] **Step 2: Run the complete Maps test matrix**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_context.py `
  tests\test_listing_location_resolver.py `
  tests\test_listing_location_registry.py `
  tests\test_listing_location_backfill.py `
  tests\test_listing_location_coverage.py `
  tests\test_listing_map_schema.py `
  tests\test_listing_map_query_scope.py `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_js.py `
  tests\test_listing_map_ui.py `
  tests\test_listing_location_auto_registry.py `
  tests\test_listing_location_auto_registry_cli.py `
  tests\test_listing_map_automation_docs.py `
  tests\test_market_data_performance.py -q
```

Expected: all pass.

- [ ] **Step 3: Run artifact and source hygiene checks**

Run:

```powershell
git diff --check
git status --short
rg -n "listing-map-official-gis|listing_map_official_gis_opened|root\.L\.circle\(" `
  templates\partials\listing_map_workspace.html `
  static\js\main\listing_map.js `
  static\css\main\listing_map.css `
  app.py
```

Expected: `rg` returns no matches; only intended tracked files are changed.

- [ ] **Step 4: Review security and privacy boundaries**

Verify:

- no browser cookies, history, or account state are read;
- no listing descriptions, phones, or original listing source URLs enter
  evidence JSON; only the selected public Google Maps result URL is retained;
- guest/free/VIP map payload redaction tests remain green;
- evidence input is bounded to 50 items;
- paths are fixed or validated;
- auto file updates are atomic;
- manual overrides cannot be overwritten.

- [ ] **Step 5: Request code review**

Use `superpowers:requesting-code-review` against the complete branch diff.
Resolve every Critical or Important finding and rerun the affected test matrix.

- [ ] **Step 6: Commit review fixes if required**

Run only when review changes exist:

```powershell
git add `
  app.py `
  radar.py `
  cli/map_locations.py `
  config/listing_map.py `
  config/listing_map_location_overrides.json `
  config/listing_map_location_auto_overrides.json `
  scripts/build_listing_location_registry.py `
  services/listing_location_auto_registry.py `
  services/listing_location_resolver.py `
  services/listing_map.py `
  static/css/main/listing_map.css `
  static/js/main/listing_map.js `
  templates/partials/listing_map_workspace.html `
  tests/test_listing_location_auto_registry.py `
  tests/test_listing_location_auto_registry_cli.py `
  tests/test_listing_location_backfill.py `
  tests/test_listing_location_registry.py `
  tests/test_listing_location_resolver.py `
  tests/test_listing_map_api.py `
  tests/test_listing_map_automation_docs.py `
  tests/test_listing_map_js.py `
  tests/test_listing_map_service.py `
  tests/test_listing_map_ui.py `
  docs/dev_commands.md `
  docs/listing_map_registry_automation.md `
  docs/operations.md
git diff --cached --name-only
git commit -m "fix: harden automatic map registry"
```

The list is deliberately restricted to files owned by this plan. Before
committing, remove any path that the review did not change and verify the
cached file list contains no unrelated work.

---

### Task 10: Release, backfill, and prove production behavior

**Files:**
- Production state only after all tracked work is committed

**Interfaces:**
- Consumes: tested branch whose commits are ancestors of pushed `main`
- Produces: active production service, v3 registry/backfill, and browser proof for both tabs

- [ ] **Step 1: Verify release scope**

Run:

```powershell
git status --short
git log --oneline --decorate --max-count=15
git diff --stat origin/main...HEAD
```

Expected: clean worktree and only Maps auto-registry changes above main.

- [ ] **Step 2: Push the feature branch and update main without force**

Run:

```powershell
git push origin codex/listing-maps-planning
git fetch origin main
git rebase origin/main
git push origin codex/listing-maps-planning --force-with-lease
git push origin HEAD:main
```

Expected: fast-forward update of `origin/main`; never use an unconditional force push.

- [ ] **Step 3: Deploy the pushed main**

Run:

```powershell
.\scripts\deploy_production.ps1
```

If the production host cannot resolve its repository SSH alias, use the
existing bundle fallback documented in `scripts/ship_production.ps1`; do not
alter the server Git remote as part of this feature.

Expected: service restarts and standard dashboard/signals smoke passes.

- [ ] **Step 4: Run production dry-run backfill**

Run through the production environment:

```bash
cd /opt/radar-bds/current
/opt/radar-bds/.venv/bin/python -X utf8 radar.py map-locations --full --dry-run
```

Verify:

```text
exact + road + landmark + ward + unmapped = scanned
nearby = 0
```

Stop before apply if invariants fail or ward fallback increases unexpectedly.

- [ ] **Step 5: Apply production full backfill**

Run:

```bash
cd /opt/radar-bds/current
/opt/radar-bds/.venv/bin/python -X utf8 radar.py map-locations --full
```

Expected: `nearby=0`, no stale active nearby groups, and accepted landmark
coverage increases or remains stable.

- [ ] **Step 6: Verify public API contracts**

Check:

```text
/api/map-listings?mode=signals
/api/map-listings?mode=all
```

For each:

- `mapped + unmapped_count == total`;
- `exact_count + road_count + landmark_count + ward_count == mapped`;
- `nearby_count == 0`;
- no location group has `precision=nearby`;
- public items contain no description, phone, source URL, seller, or contact
  fields.

- [ ] **Step 7: Verify desktop and mobile browser behavior**

Using production `https://radarbds.vn/`:

1. open Săn Deal Maps;
2. confirm no GIS block, no nearby legend, and no dashed circles;
3. confirm nearby-derived examples appear in a road group;
4. open a listing modal, close it, and verify Maps plus selected group remain;
5. repeat for Tin Rao;
6. resize to `390x844` and verify the fixed launcher is horizontally centered;
7. verify TĐC Phú Chánh B landmark-only listings use its landmark marker when
   the candidate was auto-accepted;
8. check console errors and warnings.

- [ ] **Step 8: Verify service and deployed commit**

Run:

```bash
cd /opt/radar-bds/current
git rev-parse HEAD
systemctl is-active radar-bds.service
```

Expected: production HEAD equals the pushed `origin/main` commit and service is
`active`.

- [ ] **Step 9: Report exact automatic-enrichment results**

Report:

- commit and production HEAD;
- registry road/landmark/auto-override counts;
- attempted, accepted, quarantined, and not-found browser candidates;
- backfill exact/road/landmark/ward/unmapped counts;
- Săn Deal and Tin Rao map counts;
- named TĐC examples resolved;
- any quarantined cases and their deterministic reason;
- production browser result for modal-state preservation.
