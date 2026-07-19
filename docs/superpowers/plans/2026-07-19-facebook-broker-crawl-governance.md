# Facebook Broker Crawl Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add city filtering, per-broker 1/3/7-day cadence, and admin-approved duplicate recommendations to Facebook Crawl.

**Architecture:** Keep `data/facebook_profiles.json` as config truth. Filter due profiles only in the production daily path, and reuse `duplicate_of_id` plus existing broker quality stats for read-only recommendations. Render controls in the existing admin template/JS/CSS without a new table or dependency.

**Tech Stack:** Python 3.12, Flask, PostgreSQL, vanilla JavaScript, CSS, pytest/unittest.

## Global Constraints

- `crawl_every_days` accepts `1`, `3`, or `7`; invalid or missing values become `1`.
- Manual, range, explicit CLI profile, and retry crawls bypass cadence.
- Analyze Facebook clusters from 90 days, same city only, with at least 10 lots per broker and 5 shared lots.
- Never auto-disable or auto-save a broker.
- Add no database table, dependency, or duplicate detector.
- Stage only files named by each task; preserve unrelated dirty changes.

---

### Task 1: Persist cadence and select due profiles

**Files:**
- Modify: `services/admin_quality.py:26-98`
- Modify: `crawler/facebook_apify.py:13-121`
- Modify: `cli/crawlers.py:93-121,305-313`
- Modify: `tests/test_daily_crawl_limits.py:39-70`
- Create: `tests/test_facebook_broker_governance.py`

**Interfaces:**
- Consumes: Facebook profile dictionaries.
- Produces: `profile_due_on(profile: dict, on_date: date | None = None) -> bool`, `profiles_due_on(profiles: list[dict], on_date: date | None = None) -> list[dict]`, and normalized `crawl_every_days` fields.

- [ ] **Step 1: Write the failing tests**

```python
import json
from datetime import date, timedelta

from crawler.facebook_apify import load_profiles, profile_due_on
from services.admin_quality import read_facebook_profile_config, write_facebook_profile_config


def test_profile_config_round_trips_cadence_and_defaults_invalid_to_daily(tmp_path):
    path = tmp_path / "facebook_profiles.json"
    path.write_text(json.dumps({"Bến Cát": [
        {"url": "https://www.facebook.com/three", "crawl_every_days": 3},
        {"url": "https://www.facebook.com/invalid", "crawl_every_days": 5},
    ]}), encoding="utf-8")
    profiles = read_facebook_profile_config(path)
    assert [p["crawl_every_days"] for p in profiles] == [3, 1]
    saved = write_facebook_profile_config(path, profiles)
    loaded = load_profiles(path)
    assert [p["crawl_every_days"] for p in saved] == [3, 1]
    assert [p["crawl_every_days"] for p in loaded] == [3, 1]


def test_profile_due_on_is_stable_for_all_cadences():
    start = date(2026, 7, 19)
    daily = {"url": "https://www.facebook.com/daily", "crawl_every_days": 1}
    three = {"url": "https://www.facebook.com/three", "crawl_every_days": 3}
    weekly = {"url": "https://www.facebook.com/weekly", "crawl_every_days": 7}
    assert all(profile_due_on(daily, start + timedelta(days=i)) for i in range(21))
    assert sum(profile_due_on(three, start + timedelta(days=i)) for i in range(21)) == 7
    assert sum(profile_due_on(weekly, start + timedelta(days=i)) for i in range(21)) == 3
```

Add to `test_daily_facebook_crawl_uses_profile_daily_limits()`:

```python
assert captured["scheduled_only"] is True
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_facebook_broker_governance.py tests\test_daily_crawl_limits.py -q
```

Expected: import fails because `profile_due_on` is absent; the daily-call assertion also lacks `scheduled_only`.

- [ ] **Step 3: Implement the minimum code**

At both JSON trust boundaries normalize cadence with:

```python
def _crawl_every_days(value) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 1
    return value if value in {1, 3, 7} else 1
```

Include `crawl_every_days` in admin read/write and runtime `_build()`. Add:

```python
def profile_due_on(profile: dict, on_date: date | None = None) -> bool:
    every = _crawl_every_days(profile.get("crawl_every_days"))
    if every == 1:
        return True
    current = on_date or datetime.now(timezone.utc).date()
    url = (profile.get("url") or "").strip().rstrip("/").lower()
    slot = int.from_bytes(hashlib.sha256(url.encode("utf-8")).digest()[:8], "big")
    return current.toordinal() % every == slot % every


def profiles_due_on(profiles: list[dict], on_date: date | None = None) -> list[dict]:
    return [profile for profile in profiles if profile_due_on(profile, on_date)]
```

Extend `_facebook_crawl_to_raw(..., scheduled_only=False)`. After loading config, filter with `profiles_due_on()` only when true. If none are due, return the existing zero-count stats before constructing Apify. Call the daily path with `_facebook_crawl_to_raw(mode="incremental", scheduled_only=True)`; all other callers retain the false default.

- [ ] **Step 4: Verify GREEN**

Run the Step 2 command. Expected: all focused tests pass.

- [ ] **Step 5: Commit**

```powershell
git add -- services/admin_quality.py crawler/facebook_apify.py cli/crawlers.py tests/test_daily_crawl_limits.py tests/test_facebook_broker_governance.py
git commit -m "feat: schedule Facebook brokers by cadence"
```

### Task 2: Compute duplicate overlap and expose recommendations

**Files:**
- Modify: `services/admin_quality.py:109-418`
- Modify: `app.py:197-198,3250-3273`
- Modify: `tests/test_facebook_broker_governance.py`
- Modify: `tests/test_admin_control_room.py:1829-1917`

**Interfaces:**
- Consumes: current profiles, per-profile stats, and rows shaped as `{cluster_id: int, profile_url: str}`.
- Produces: `build_facebook_duplicate_analysis(profiles: list[dict], stats: dict, rows: list[dict]) -> dict` and `facebook_profile_duplicate_analysis(profiles, stats, conn_factory=get_conn) -> dict`, both returning `comparisons` and `by_profile`.

- [ ] **Step 1: Write failing pure-analysis and API tests**

Append to `tests/test_facebook_broker_governance.py`:

```python
from services.admin_quality import build_facebook_duplicate_analysis


def _profile(url, name, city="Thủ Dầu Một"):
    return {"url": url, "broker_name": name, "city": city}


def _stats(score_a=90, score_b=70):
    return {
        "https://www.facebook.com/a": {"data_quality": {"score": score_a}, "latest_crawled_at": "2026-07-19 10:00:00"},
        "https://www.facebook.com/b": {"data_quality": {"score": score_b}, "latest_crawled_at": "2026-07-18 10:00:00"},
    }


def test_duplicate_analysis_is_directional_and_keeps_cleaner_broker():
    profiles = [_profile("https://www.facebook.com/a", "A"), _profile("https://www.facebook.com/b", "B")]
    rows = [{"cluster_id": i, "profile_url": profiles[0]["url"]} for i in range(1, 21)]
    rows += [{"cluster_id": i, "profile_url": profiles[1]["url"]} for i in range(1, 11)]
    result = build_facebook_duplicate_analysis(profiles, _stats(), rows)
    item = result["comparisons"][0]
    assert item["shared_lots"] == 10
    assert item["broker_a_overlap_pct"] == 50.0
    assert item["broker_b_overlap_pct"] == 100.0
    assert item["keep_url"] == profiles[0]["url"]
    assert item["reduce_url"] == profiles[1]["url"]
    assert item["recommended_crawl_every_days"] == 7
    assert result["by_profile"][profiles[1]["url"]]["shared_lots"] == 10


def test_duplicate_analysis_rejects_cross_city_pairs():
    profiles = [_profile("https://www.facebook.com/a", "A"), _profile("https://www.facebook.com/b", "B", "Bến Cát")]
    rows = [{"cluster_id": i, "profile_url": p["url"]} for i in range(1, 20) for p in profiles]
    assert build_facebook_duplicate_analysis(profiles, _stats(), rows)["comparisons"] == []
```

In the existing admin config test assert:

```python
payload = response.get_json()
self.assertIn("duplicate_comparisons", payload)
self.assertIsInstance(payload["duplicate_comparisons"], list)
```

- [ ] **Step 2: Verify RED**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_facebook_broker_governance.py tests\test_admin_control_room.py -q
```

Expected: import fails because the builder is absent, then the endpoint lacks `duplicate_comparisons`.

- [ ] **Step 3: Implement the pure builder**

Use `defaultdict(set)` and `itertools.combinations`. Normalize profile URLs by trimming whitespace/trailing slash. Build distinct cluster sets, ignore URLs outside current config, require same city, totals `>=10`, and shared clusters `>=5`.

Rank the broker to keep exactly as:

```python
def _broker_rank(url: str, shared: int, totals: dict, stats: dict) -> tuple:
    profile_stat = stats.get(url) or {}
    score = (profile_stat.get("data_quality") or {}).get("score")
    latest = parse_crawl_datetime(profile_stat.get("latest_crawled_at"))
    return float(score) if score is not None else -1.0, totals[url] - shared, latest or datetime.min
```

Return design-spec field names. Use the reduced broker's directional overlap for cadence: `7` at `>=70`, `3` at `>=50`, otherwise `None`. Sort by reduced overlap then shared count descending. For `by_profile[url]`, keep the comparison with the highest directional overlap for that profile.

- [ ] **Step 4: Implement the DB adapter and Flask wiring**

Execute one read-only query:

```sql
SELECT COALESCE(l.duplicate_of_id, l.id) AS cluster_id,
       COALESCE(NULLIF(r.raw_json::jsonb ->> 'profile_url', ''),
                NULLIF(r.raw_json::jsonb -> '_apify_raw' ->> 'inputUrl', '')) AS profile_url
FROM listings l
JOIN raw_listings r ON r.id = l.raw_id
WHERE l.source = 'facebook'
  AND COALESCE(NULLIF(l.crawled_at, ''), NULLIF(r.crawled_at, ''))::timestamp
      >= CURRENT_TIMESTAMP - INTERVAL '90 days'
```

On adapter failure return `{"comparisons": [], "by_profile": {}}`. In both GET and POST config branches, run analysis after profile stats, attach `duplicate_overlap` from `by_profile`, and return top-level `duplicate_comparisons`.

- [ ] **Step 5: Verify GREEN**

Run the Step 2 command. Expected: pure analysis and endpoint tests pass.

- [ ] **Step 6: Commit**

```powershell
git add -- services/admin_quality.py app.py tests/test_facebook_broker_governance.py tests/test_admin_control_room.py
git commit -m "feat: analyze duplicate Facebook brokers"
```

### Task 3: Add city filter, cadence selector, and approval panel

**Files:**
- Modify: `templates/admin_control_room.html:443-469`
- Modify: `static/js/admin.js:32-33,278-300,770-932`
- Modify: `static/css/admin.css:788-878,1354-1385`
- Modify: `tests/test_admin_control_room.py:1919-1946`

**Interfaces:**
- Consumes: `profiles[].crawl_every_days`, `profiles[].duplicate_overlap`, and top-level `duplicate_comparisons`.
- Produces: `crawlCityFilter`, filtered rows/comparisons, and `applyCrawlDuplicateRecommendation(url, days)` that changes draft state only.

- [ ] **Step 1: Write failing UI contract assertions**

Extend `test_admin_js_renders_crawl_ops_panel()`:

```python
self.assertIn('id="crawlCityFilter"', html)
self.assertIn('id="crawlDuplicateRecommendations"', html)
self.assertIn("crawl_every_days", js)
self.assertIn("function renderCrawlCityFilter", js)
self.assertIn("function renderCrawlDuplicateRecommendations", js)
self.assertIn("function applyCrawlDuplicateRecommendation", js)
self.assertIn(".crawl-duplicate-panel", css)
self.assertIn("Cặp môi giới trùng nhiều", html)
```

- [ ] **Step 2: Verify RED**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_admin_control_room.py::AdminControlRoomTestCase::test_admin_js_renders_crawl_ops_panel -q
```

Expected: assertions fail because the new UI contract is absent.

- [ ] **Step 3: Add the minimal template**

Above the broker table add:

```html
<div class="crawl-list-tools">
  <label class="crawl-field">Thành phố
    <select id="crawlCityFilter" class="select-control"></select>
  </label>
</div>
<section class="crawl-duplicate-panel" aria-labelledby="crawlDuplicateTitle">
  <div class="crawl-duplicate-head">
    <strong id="crawlDuplicateTitle">Cặp môi giới trùng nhiều</strong>
    <small>Chỉ áp dụng sau khi bấm Lưu danh sách</small>
  </div>
  <div id="crawlDuplicateRecommendations"></div>
</section>
```

Add a `Chu kỳ` table header. Update the empty row colspan and responsive styles for the extra cell.

- [ ] **Step 4: Add the minimal client behavior**

Add `crawlDuplicateComparisons = []` and `crawlCityFilter = ''`. `loadCrawlConfig()` assigns `data.duplicate_comparisons || []`, then renders the filter, recommendations, rows, and manual-run select.

`renderCrawlCityFilter()` derives distinct configured cities and preserves the current selection. `renderCrawlProfiles()` filters profiles by city and renders:

```javascript
<select class="crawl-small-input" data-crawl-field="crawl_every_days">
  <option value="1" ${Number(p.crawl_every_days || 1) === 1 ? 'selected' : ''}>Hàng ngày</option>
  <option value="3" ${Number(p.crawl_every_days || 1) === 3 ? 'selected' : ''}>3 ngày</option>
  <option value="7" ${Number(p.crawl_every_days || 1) === 7 ? 'selected' : ''}>7 ngày</option>
</select>
```

`readCrawlTableState()` copies cadence to the matching profile. The filter change handler first preserves visible draft edits, updates `crawlCityFilter`, and rerenders rows/recommendations.

`renderCrawlDuplicateRecommendations()` filters by city and renders names, shared lots, both percentages, quality scores, keep/reduce guidance, and an apply button only for cadence `3` or `7`.

```javascript
function applyCrawlDuplicateRecommendation(url, days) {
  readCrawlTableState();
  const profile = crawlProfiles.find(item => item.url === url);
  if (!profile || ![3, 7].includes(Number(days))) return;
  profile.crawl_every_days = Number(days);
  renderCrawlProfiles();
  showAdminToast('Đã áp dụng chu kỳ gợi ý vào bản nháp', 'success');
}
```

Applying does not call the API. Only the existing Save button persists config; only the existing active toggle disables a broker.

- [ ] **Step 5: Verify focused UI GREEN**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_admin_control_room.py::AdminControlRoomTestCase::test_admin_js_renders_crawl_ops_panel -q
node --check static\js\admin.js
```

Expected: test passes and Node reports no syntax error.

- [ ] **Step 6: Run full feature verification**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_facebook_broker_governance.py tests\test_daily_crawl_limits.py tests\test_admin_control_room.py -q
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m py_compile app.py services\admin_quality.py crawler\facebook_apify.py cli\crawlers.py
node --check static\js\admin.js
git diff --check
```

Expected: selected tests pass, compile/syntax checks succeed, and diff check is silent.

- [ ] **Step 7: Smoke and commit**

Open `/admin/facebook-crawl` as admin at desktop and mobile widths. Verify city filtering, draft cadence changes, overlap evidence, no automatic save/deactivation, and manual crawl availability for weekly profiles.

```powershell
git add -- templates/admin_control_room.html static/js/admin.js static/css/admin.css tests/test_admin_control_room.py
git commit -m "feat: govern Facebook broker crawling in admin"
```
