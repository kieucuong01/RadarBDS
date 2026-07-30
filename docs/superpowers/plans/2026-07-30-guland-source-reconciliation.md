# Guland Source Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh same-identity Guland prices into the existing price-history plot, preserve first-seen dates across reposts, and hide listings only after explicit source-removal evidence.

**Architecture:** Add source lifecycle/price timestamps to listings, build a pure card-reconciliation planner, and let Guland fetch detail only for new, changed-price, or bounded verification candidates. Refreshed raw IDs flow through a narrow reprocess path, while API/UI date logic is source-specific and the existing Facebook behavior remains unchanged.

**Tech Stack:** Python 3.12, PostgreSQL 18, Playwright, Flask, vanilla JavaScript, pytest/unittest, Node.js syntax/tests.

## Global Constraints

- Execute `2026-07-30-crawl-reliability-phase1.md` first.
- `first_seen_at` is immutable.
- Same URL/source ID plus the same normalized price is one observation, not a new listing or history point.
- Any confirmed increase or decrease appends one `price_history` row and sets `price_updated_at`.
- Invalid, zero, masked, contradictory, or transient prices never clear the last good price.
- Guland absence from the one-day result window is not removal evidence.
- Only two consecutive explicit removals mark a listing inactive.
- Do not add Guland cross-URL same-lot heuristics.
- Facebook card dates, deduplication, and price-history behavior remain unchanged.
- Public feed/Map hides confirmed `inactive`; `unknown` and `unreachable` remain visible.
- Revalue only listings whose raw record was newly inserted or whose confirmed price changed.

---

### Task 1: Add Source Lifecycle and Price Activity Schema

**Files:**
- Modify: `db/schema.py:70-110`
- Modify: `db/schema.py:1028-1080`
- Modify: `analytics/lifecycle.py:19-93`
- Create: `tests/test_source_lifecycle.py`

**Interfaces:**
- Adds listings columns: `price_updated_at`, `source_status`, `last_source_check_at`, `source_status_reason`.
- Produces: `mark_source_seen(conn, source: str, urls: Iterable[str], seen_at: datetime | None = None) -> int`
- Produces: `record_source_check(conn, listing_id: int, outcome: Literal["active", "removed", "unreachable"], reason: str, checked_at: datetime | None = None) -> SourceCheckResult`
- Test helper: `_seed_guland(conn, token: str) -> dict` inserts one UUID-scoped
  listing with fixed first/last-seen timestamps and returns its `id`, `url`, and
  `first_seen_at`; `_load_listing(conn, listing_id: int) -> dict` selects the
  lifecycle columns. Both helpers delete by UUID URL in `finally`.

- [x] **Step 1: Write failing migration and lifecycle tests**

```python
def test_mark_source_seen_preserves_first_seen(postgres_conn, seeded_guland):
    before = seeded_guland["first_seen_at"]
    mark_source_seen(postgres_conn, "guland", [seeded_guland["url"]], seen_at=NOW)
    row = _load_listing(postgres_conn, seeded_guland["id"])
    assert row["first_seen_at"] == before
    assert row["last_seen_at"].startswith("2026-07-30")
    assert row["source_status"] == "active"
    assert row["source_status_reason"] == "seen_in_results"


def test_two_explicit_removals_are_required(postgres_conn, seeded_guland):
    first = record_source_check(postgres_conn, seeded_guland["id"], "removed", "http_not_found")
    second = record_source_check(postgres_conn, seeded_guland["id"], "removed", "explicit_removed")
    assert first.source_status == "unknown"
    assert second.source_status == "inactive"


def test_unreachable_does_not_increment_missing(postgres_conn, seeded_guland):
    result = record_source_check(postgres_conn, seeded_guland["id"], "unreachable", "timeout")
    assert result.source_status == "unreachable"
    assert result.consecutive_missing == 0
```

- [x] **Step 2: Verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_source_lifecycle.py -q
```

Expected: missing schema columns/functions.

- [x] **Step 3: Add idempotent columns and indexes**

Add the columns to the canonical schema and `_run_migrations()`:

```sql
price_updated_at       TIMESTAMPTZ,
source_status          TEXT NOT NULL DEFAULT 'unknown'
                       CHECK (source_status IN ('unknown','active','inactive','unreachable')),
last_source_check_at   TIMESTAMPTZ,
source_status_reason   TEXT NOT NULL DEFAULT ''
```

Add:

```sql
CREATE INDEX IF NOT EXISTS idx_listings_source_status_check
ON listings(source, source_status, last_source_check_at, id)
```

- [x] **Step 4: Replace elapsed-time delisting with evidence updates**

`mark_source_seen()` bulk-updates by `(source, url)`, clears
`consecutive_missing`, sets active compatibility fields, and never changes a
non-null `first_seen_at`.

`record_source_check()` uses a row lock, increments missing only for `removed`,
sets inactive on the second consecutive removal, and treats `unreachable` as
visible non-removal evidence.

Change `sweep_delisted()` so elapsed time alone cannot mark any source inactive.
It may finalize lifecycle metrics only for rows already confirmed
`source_status='inactive'`.

- [x] **Step 5: Verify GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_source_lifecycle.py -q
```

- [x] **Step 6: Commit lifecycle schema**

```powershell
git add db/schema.py analytics/lifecycle.py tests/test_source_lifecycle.py
git commit -m "feat: add source verified listing lifecycle"
```

### Task 2: Build the Pure Guland Card Reconciliation Planner

**Files:**
- Create: `services/guland_reconciliation.py`
- Create: `tests/test_guland_reconciliation.py`

**Interfaces:**
- Produces: `canonical_price_vnd(price_ty: object) -> int | None`
- Produces: `ExistingGulandSnapshot(raw_id, listing_id, url, source_id, price_ty, first_seen_at, source_status)`
- Produces: `GulandReconciliationPlan(new_cards, unchanged_cards, changed_cards, invalid_price_cards)`
- Produces: `plan_guland_cards(cards, existing_by_url) -> GulandReconciliationPlan`

- [ ] **Step 1: Write failing canonical-price tests**

```python
def test_canonical_price_rounds_to_one_million_vnd():
    assert canonical_price_vnd(2.5) == 2_500_000_000
    assert canonical_price_vnd(2.5004) == 2_500_000_000


def test_invalid_prices_never_become_changes():
    assert canonical_price_vnd(None) is None
    assert canonical_price_vnd(0) is None
    assert canonical_price_vnd(float("nan")) is None
```

- [ ] **Step 2: Write failing partition tests**

```python
def test_planner_separates_new_unchanged_changed_and_invalid():
    new_url = "https://guland.vn/post/new-1001"
    same_url = "https://guland.vn/post/same-1002"
    changed_url = "https://guland.vn/post/changed-1003"
    masked_url = "https://guland.vn/post/masked-1004"
    existing = {
        same_url: ExistingGulandSnapshot(2, 12, same_url, "1002", 2.5, FIRST_SEEN, "active"),
        changed_url: ExistingGulandSnapshot(3, 13, changed_url, "1003", 2.5, FIRST_SEEN, "active"),
        masked_url: ExistingGulandSnapshot(4, 14, masked_url, "1004", 2.5, FIRST_SEEN, "active"),
    }
    cards = [
        {"url": new_url, "price_ty": 1.9},
        {"url": same_url, "price_ty": 2.5},
        {"url": changed_url, "price_ty": 2.7},
        {"url": masked_url, "price_ty": None},
    ]
    plan = plan_guland_cards(cards, existing)
    assert [c["url"] for c in plan.new_cards] == [new_url]
    assert [c["url"] for c in plan.unchanged_cards] == [same_url]
    assert [c["url"] for c in plan.changed_cards] == [changed_url]
    assert [c["url"] for c in plan.invalid_price_cards] == [masked_url]
```

- [ ] **Step 3: Verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_guland_reconciliation.py -q
```

- [ ] **Step 4: Implement immutable dataclasses and one-million-VND comparison**

The planner is pure: no database, Playwright, logging, or global state. It uses
the parsed `price_ty` supplied on each card and does not infer cross-URL
identity.

- [ ] **Step 5: Verify GREEN and commit**

```powershell
& $py -X utf8 -m pytest tests\test_guland_reconciliation.py -q
git add services/guland_reconciliation.py tests/test_guland_reconciliation.py
git commit -m "feat: plan guland card reconciliation"
```

### Task 3: Reconcile Existing Cards and Verify Stale Source URLs

**Files:**
- Modify: `crawler/base_crawler.py:147-218`
- Modify: `crawler/guland_pw.py:110-640`
- Modify: `analytics/lifecycle.py`
- Modify: `tests/test_guland_crawler_stats.py`
- Create: `tests/test_guland_source_verifier.py`

**Interfaces:**
- Base hook: `after_targets(self, page, run_id: int) -> None`
- Guland loader: `_load_existing_snapshots(urls: list[str]) -> dict[str, ExistingGulandSnapshot]`
- Guland verifier: `_verify_stale_listings(page, limit: int) -> dict`
- Detail result fields: `url`, `http_status`, `page_status`, `detail_price_raw`, `error`.
- Test helper: `_run_cards(monkeypatch, cards, snapshots, details) -> tuple[dict,
  list[str], list[str]]` stubs `_scroll_all_cards`, snapshot loading, detail
  fetching, raw writes, and lifecycle writes; it returns stats, fetched detail
  URLs, and seen URLs. The helper uses real `plan_guland_cards()`.

- [ ] **Step 1: Write failing existing-card crawl tests**

```python
def test_existing_same_price_marks_seen_without_detail(monkeypatch):
    url = "https://guland.vn/post/same-2001"
    card = {"url": url, "post_id": "2001", "price_ty": 2.5}
    snapshot = ExistingGulandSnapshot(21, 31, url, "2001", 2.5, FIRST_SEEN, "active")
    stats, fetched_urls, seen_urls = _run_cards(
        monkeypatch, [card], {url: snapshot}, {},
    )
    assert stats["existing"] == 1
    assert stats["unchanged"] == 1
    assert stats["updated"] == 0
    assert fetched_urls == []
    assert seen_urls == [url]


def test_existing_changed_price_enters_detail_batch(monkeypatch):
    url = "https://guland.vn/post/changed-2002"
    card = {"url": url, "post_id": "2002", "price_ty": 2.7}
    snapshot = ExistingGulandSnapshot(22, 32, url, "2002", 2.5, FIRST_SEEN, "active")
    detail = {"url": url, "http_status": 200, "page_status": "live", "detail_price_raw": "2,7 tỷ"}
    stats, fetched_urls, _seen_urls = _run_cards(
        monkeypatch, [card], {url: snapshot}, {url: detail},
    )
    assert fetched_urls == [url]
    assert stats["updated"] == 1
    assert stats["refreshed_raw_ids"] == [22]
```

- [ ] **Step 2: Write failing verifier classification tests**

```python
@pytest.mark.parametrize(
    ("detail", "outcome"),
    [
        ({"http_status": 200, "page_status": "live"}, "active"),
        ({"http_status": 404, "page_status": "removed"}, "removed"),
        ({"http_status": 503, "page_status": "unreachable"}, "unreachable"),
        ({"error": "timeout"}, "unreachable"),
    ],
)
def test_detail_result_classification(detail, outcome):
    assert classify_detail_result(detail).outcome == outcome
```

- [ ] **Step 3: Verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_guland_crawler_stats.py tests\test_guland_source_verifier.py -q
```

- [ ] **Step 4: Extend the detail fetch contract**

The page script must:

- preserve HTTP status;
- classify `/khong-tim-thay`, HTTP 404/410, or Vietnamese text matching
  `tin.*(?:đã|bị).*(?:gỡ|xóa)|tin.*không.*tồn tại` as explicit removal;
- extract current advertised price in this order:
  `meta[itemprop="price"]`, `[itemprop="price"]`, `.dtl-inf__prc`,
  `.dtl-inf__price`, `.dtl-prc`;
- return `page_status='live'` only when the page identity/content is present.

Do not classify Cloudflare, timeout, blank HTML, or 5xx as removed.

- [ ] **Step 5: Replace per-card `url_exists()` calls with one snapshot query**

`_run_crawl()` parses card prices, calls `plan_guland_cards()`, bulk-marks every
valid discovered existing URL seen, fetches details for `new_cards +
changed_cards`, and returns these counters:

```python
{
    "fetched": 0,
    "new": 0,
    "existing": 0,
    "unchanged": 0,
    "updated": 0,
    "invalid_price": 0,
    "errors": 0,
    "inserted_raw_ids": [],
    "refreshed_raw_ids": [],
}
```

A changed price is accepted only when the detail result is live and its
canonical detail price agrees with the card price. Otherwise preserve the old
raw/listing price and increment `errors`.

- [ ] **Step 6: Add bounded verification after result targets**

`after_targets()` invokes `_verify_stale_listings()` only for Guland. The limit
comes from `GULAND_STATUS_VERIFY_LIMIT`, defaults to `50`, and is clamped to
`0..200`.

Candidate order:

```sql
ORDER BY
  CASE COALESCE(source_status,'unknown') WHEN 'unknown' THEN 0 ELSE 1 END,
  last_source_check_at NULLS FIRST,
  id
LIMIT ?
```

Use product visibility filters and exclude already confirmed inactive rows.
Each result calls `record_source_check()`; changed live prices join the same
refresh pipeline.

- [ ] **Step 7: Verify GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_guland_reconciliation.py tests\test_guland_crawler_stats.py tests\test_guland_source_verifier.py -q
```

- [ ] **Step 8: Commit crawler reconciliation**

```powershell
git add crawler/base_crawler.py crawler/guland_pw.py analytics/lifecycle.py tests/test_guland_crawler_stats.py tests/test_guland_source_verifier.py
git commit -m "feat: reconcile existing guland listings"
```

### Task 4: Refresh Raw Data, Append Price History, and Revalue Narrowly

**Files:**
- Modify: `db/raw_listings.py`
- Modify: `db/listings.py:241-474`
- Modify: `cleansing/reprocess.py:336-680`
- Modify: `cli/crawlers.py:298-480`
- Modify: `tests/test_price_history.py`
- Create: `tests/test_guland_targeted_reprocess.py`

**Interfaces:**
- Produces: `refresh_raw_listing(source: str, url: str, raw_data: dict, crawl_run_id: int | None = None) -> int`
- Produces: `run_targeted_reprocess(raw_ids: list[int]) -> dict`
- `upsert_listing()` sets `price_updated_at` only for a distinct confirmed Guland `price_ty`.
- Test helper: `_listing_state(listing_id: int) -> dict` selects
  `first_seen_at`, `price_ty`, `price_updated_at`, and `updated_at`;
  `_history_prices(listing_id: int) -> list[float]` selects ordered non-null
  `price_history.price_ty`.
- Test helper: `_seed_targeted_pair() -> dict` inserts two UUID-scoped raw and
  listing rows and returns `changed_raw_id`, `changed_listing_id`,
  `untouched_listing_id`, and `untouched_updated_at`; teardown deletes all
  dependent rows by those listing IDs.

- [ ] **Step 1: Write failing Guland history tests**

```python
def test_guland_same_price_preserves_first_seen_and_history():
    listing_id, _ = upsert_listing(self._rec(price_ty=2.5), crawl_run_id=1)
    self._track(listing_id)
    first_seen = _listing_state(listing_id)["first_seen_at"]
    upsert_listing(self._rec(price_ty=2.5), crawl_run_id=2)
    assert _listing_state(listing_id)["first_seen_at"] == first_seen
    assert _listing_state(listing_id)["price_updated_at"] is None
    assert _history_prices(listing_id) == [2.5]


def test_guland_increase_and_decrease_append_history():
    listing_id, _ = upsert_listing(self._rec(price_ty=2.5), crawl_run_id=1)
    self._track(listing_id)
    upsert_listing(self._rec(price_ty=2.7), crawl_run_id=2)
    upsert_listing(self._rec(price_ty=2.4), crawl_run_id=3)
    assert _history_prices(listing_id) == [2.5, 2.7, 2.4]
    assert _listing_state(listing_id)["price_updated_at"] is not None
```

- [ ] **Step 2: Write a failing narrow-reprocess test**

```python
def test_targeted_reprocess_only_touches_requested_raw_ids(monkeypatch):
    seeded = _seed_targeted_pair()
    result = run_targeted_reprocess([seeded["changed_raw_id"]])
    assert result["listings"]["processed_ids"] == [seeded["changed_listing_id"]]
    assert result["valuation"]["total"] == 1
    untouched = _listing_state(seeded["untouched_listing_id"])
    assert untouched["updated_at"] == seeded["untouched_updated_at"]
```

- [ ] **Step 3: Verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_price_history.py tests\test_guland_targeted_reprocess.py -q
```

- [ ] **Step 4: Implement same-row raw refresh**

`refresh_raw_listing()` updates only `(source, url)`, writes JSON with
`ensure_ascii=False`, updates `crawled_at` and `crawl_run_id`, and raises
`LookupError` when the identity is absent. It never inserts a second same-URL
row.

- [ ] **Step 5: Make Guland history price-driven**

For existing Guland listings:

```python
price_changed = (
    new_price is not None
    and not _same_price_snapshot(existing["price_ty"], new_price)
)
```

Set:

```sql
price_updated_at =
  CASE WHEN :price_changed <> 0 THEN :updated_at ELSE price_updated_at END
```

For Guland, `_should_insert_price_history()` compares `price_ty` only; area/ppm2
reparsing at the same price cannot add a plot point. Facebook keeps the current
price-plus-ppm2 behavior.

- [ ] **Step 6: Add the narrow reprocess orchestration**

`run_targeted_reprocess(raw_ids)` calls:

1. `reprocess_listings(raw_ids=raw_ids)`;
2. `reprocess_valuation(incremental_ids=processed_ids)`;
3. listing map backfill only for `processed_ids`.

It does not run global lifecycle sweeping, trend rebuild, cross-source dedup, or
full valuation.

Update `_cmd_crawl()` to gather `inserted_raw_ids + refreshed_raw_ids` from
Guland stats and call `run_targeted_reprocess()` once. Image work receives only
the returned processed listing IDs.

- [ ] **Step 7: Verify GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_price_history.py tests\test_guland_targeted_reprocess.py tests\test_daily_crawl_limits.py -q
```

- [ ] **Step 8: Commit price refresh and targeted reprocess**

```powershell
git add db/raw_listings.py db/listings.py cleansing/reprocess.py cli/crawlers.py tests/test_price_history.py tests/test_guland_targeted_reprocess.py
git commit -m "feat: record guland price changes"
```

### Task 5: Feed Guland Price Changes into the Existing History API

**Files:**
- Modify: `app.py:5250-5315`
- Modify: `tests/test_price_history.py:750-818`

**Interfaces:**
- `/api/history/<id>` returns existing `history`, `lot_history`, `comps`, and `tier`.
- Guland history items add `recorded_at`; existing `date` remains for client compatibility.
- Test helper: `_seed_api_history(source: str, snapshots:
  list[tuple[float, str]]) -> int` inserts one UUID-scoped listing plus ordered
  `price_history` rows and returns its ID; teardown removes dependent rows.

- [ ] **Step 1: Write failing history API tests**

```python
def test_guland_history_keeps_distinct_same_day_price_changes():
    from app import app
    listing_id = _seed_api_history("guland", [
        (2.5, "2026-07-30 08:00:00"),
        (2.7, "2026-07-30 11:00:00"),
        (2.4, "2026-07-30 15:00:00"),
    ])
    history = app.test_client().get(f"/api/history/{listing_id}").get_json()["history"]
    assert [row["price_ty"] for row in history] == [2.5, 2.7, 2.4]
    assert history[-1]["recorded_at"].endswith("15:00:00")


def test_facebook_same_day_parser_snapshots_still_collapse():
    from app import app
    listing_id = _seed_api_history("facebook", [
        (2.0, "2026-04-24 20:17:40"),
        (2.35, "2026-04-24 20:19:09"),
    ])
    assert app.test_client().get(f"/api/history/{listing_id}").get_json()["history"] == [
        {"date": "2026-04-02", "price_ty": 2.35}
    ]
```

- [ ] **Step 2: Verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_price_history.py -q
```

- [ ] **Step 3: Make history ranking source-specific**

For Guland, order and date plot points by `price_history.recorded_at` and do not
collapse distinct same-day prices. For Facebook, retain the final same-day
parser snapshot behavior and posted-date semantics.

Do not merge separate Guland listing IDs into one price series unless the
existing source-ID identity relationship already links them.

- [ ] **Step 4: Verify and commit**

```powershell
& $py -X utf8 -m pytest tests\test_price_history.py tests\test_lot_history.py -q
git add app.py tests/test_price_history.py
git commit -m "feat: plot guland price history"
```

### Task 6: Use Source-Specific Card Dates and Labels

**Files:**
- Modify: `services/market_data.py:112-124`
- Modify: `services/market_data.py:670-695`
- Modify: `services/market_data.py:1060-1114`
- Modify: `services/market_data.py:1176-1188`
- Modify: `static/js/main/signal_card.js:220-270`
- Modify: `static/js/main/signals.js:700-746`
- Modify: `static/js/main/listing_map.js:660-680`
- Modify: `tests/test_source_policy.py`
- Modify: `tests/js/test_signal_card.js`
- Modify: `tests/test_listing_map_js.py`

**Interfaces:**
- Produces SQL helper: `listing_activity_at_sql(alias: str = "l") -> str`
- Signal cards add: `card_date_reason: Literal["first_seen", "price_updated", "posted"]`
- Keeps: `days_ago` numeric for all existing clients.
- Test helper: `_set_activity(listing_id: int, *, first_seen_at: str,
  price_updated_at: str | None, posted_at: str | None) -> None` updates only the
  activity columns of the UUID-scoped test listing; `_admin_signal_by_id(client,
  listing_id: int) -> dict` logs in with the existing test admin helper and
  returns that listing from `/api/signals`.

- [ ] **Step 1: Write failing source-specific API tests**

```python
def test_guland_card_uses_first_seen_until_price_change(self):
    _set_activity(
        self.guland_id,
        first_seen_at=FIRST_SEEN,
        price_updated_at=None,
        posted_at="2026-07-30",
    )
    first = _admin_signal_by_id(self.client, self.guland_id)
    assert first["days_ago"] == days_since(FIRST_SEEN)
    assert first["card_date_reason"] == "first_seen"

    _set_activity(
        self.guland_id,
        first_seen_at=FIRST_SEEN,
        price_updated_at=TODAY,
        posted_at="2026-07-30",
    )
    updated = _admin_signal_by_id(self.client, self.guland_id)
    assert updated["days_ago"] == 0
    assert updated["card_date_reason"] == "price_updated"


def test_facebook_card_keeps_posted_at(self):
    _set_activity(
        self.facebook_id,
        first_seen_at=FIRST_SEEN,
        price_updated_at=TODAY,
        posted_at=FACEBOOK_POSTED,
    )
    card = _admin_signal_by_id(self.client, self.facebook_id)
    assert card["card_date_reason"] == "posted"
    assert card["days_ago"] == days_since(FACEBOOK_POSTED)
```

- [ ] **Step 2: Write failing renderer tests**

```javascript
assert.match(renderer, /Cập nhật giá/);
assert.match(renderer, /Theo dõi từ/);
assert.match(renderer, /card_date_reason/);
assert.match(renderer, /CẬP NHẬT GIÁ/);
```

- [ ] **Step 3: Verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_source_policy.py tests\test_listing_map_js.py -q
node tests\js\test_signal_card.js
```

- [ ] **Step 4: Implement one SQL activity expression everywhere**

```python
def listing_activity_at_sql(alias="l"):
    return (
        f"CASE WHEN {alias}.source='guland' "
        f"THEN COALESCE({alias}.price_updated_at, {alias}.first_seen_at, {alias}.crawled_at) "
        f"ELSE COALESCE({alias}.posted_at, {alias}.crawled_at) END"
    )
```

Use it for signal sorting, date-range filtering, selected `activity_at`, and
`days_ago`. Add `COALESCE(source_status,'unknown') <> 'inactive'` to shared
public listing filters so confirmed inactive rows disappear from feed and Map.

- [ ] **Step 5: Render the reason without breaking established card UI**

- `price_updated`: time tag `Cập nhật giá hôm nay/N ngày trước`; new badge text
  `CẬP NHẬT GIÁ`.
- `first_seen`: time tag `Theo dõi từ hôm nay/N ngày trước`; normal new badge
  remains based on `days_ago`.
- `posted`: retain current Facebook time copy and `MỚI` badge.

Apply the same semantics to shared cards, legacy signal cards, and Map popup
time copy. Keep `Lưu`, `Ráp mối`, source tag rules, and redaction unchanged.

- [ ] **Step 6: Verify GREEN and syntax**

```powershell
& $py -X utf8 -m pytest tests\test_source_policy.py tests\test_listing_map_js.py tests\test_signal_detail_ui.py tests\test_refactor_structure.py -q
node --check static\js\main\signal_card.js
node --check static\js\main\signals.js
node --check static\js\main\listing_map.js
node tests\js\test_signal_card.js
```

- [ ] **Step 7: Commit card behavior**

```powershell
git add services/market_data.py static/js/main/signal_card.js static/js/main/signals.js static/js/main/listing_map.js tests/test_source_policy.py tests/js/test_signal_card.js tests/test_listing_map_js.py
git commit -m "feat: show guland price activity dates"
```

### Task 7: Add Dry-Run Historical Reconciliation

**Files:**
- Create: `services/guland_historical_reconciliation.py`
- Create: `cli/guland_reconciliation.py`
- Modify: `radar.py:90-100`
- Modify: `radar.py:340-360`
- Modify: `radar.py:430-448`
- Create: `tests/test_guland_historical_reconciliation.py`
- Modify: `docs/daily_crawl_flow.md`
- Modify: `docs/operations.md`

**Interfaces:**
- CLI: `radar.py guland-reconcile --limit N [--apply]`
- Produces: `reconcile_guland_candidates(limit: int, apply: bool) -> dict`
- Dry-run is default and performs no database writes.
- Test helper: `_fake_reconciliation_dependencies(monkeypatch)` supplies two
  bounded candidates, one confirmed price change, one two-strike explicit
  removal, and spies for lifecycle/raw/reprocess writes. It returns a dictionary
  of those spies keyed by `raw_refresh`, `lifecycle`, and `reprocess`.

- [ ] **Step 1: Write failing dry-run/apply tests**

```python
def test_reconcile_default_is_dry_run(monkeypatch):
    spies = _fake_reconciliation_dependencies(monkeypatch)
    stats = reconcile_guland_candidates(limit=20, apply=False)
    assert stats["apply"] is False
    assert stats["scanned"] <= 20
    assert spies["raw_refresh"].call_count == 0
    assert spies["lifecycle"].call_count == 0
    assert spies["reprocess"].call_count == 0


def test_reconcile_apply_updates_only_confirmed_changes(monkeypatch):
    spies = _fake_reconciliation_dependencies(monkeypatch)
    stats = reconcile_guland_candidates(limit=20, apply=True)
    assert stats["price_changes"] == 1
    assert stats["inactive_confirmed"] == 1
    assert spies["raw_refresh"].call_args.args[1] == CONFIRMED_CHANGED_URL
```

- [ ] **Step 2: Verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_guland_historical_reconciliation.py -q
```

- [ ] **Step 3: Implement bounded candidate reconciliation**

Candidate scope is Guland rows that are currently displayable by product
filters, ordered by unknown/stale source checks. The service reuses the detail
classification, price confirmation, lifecycle, raw refresh, and targeted
reprocess contracts from Tasks 1-4.

Stats contain only counts and bounded listing IDs:

```python
{
    "apply": False,
    "scanned": 0,
    "active": 0,
    "inactive_first_confirmation": 0,
    "inactive_confirmed": 0,
    "unreachable": 0,
    "price_changes": 0,
    "invalid_prices": 0,
    "errors": 0,
    "changed_listing_ids": [],
}
```

- [ ] **Step 4: Backfill deterministic historical timestamps**

On apply before live checks:

- fill null `first_seen_at` from `crawled_at`;
- set `price_updated_at` only for listings with at least two distinct valid
  `price_history.price_ty` values, using the latest distinct change timestamp;
- initialize null/invalid source status to `unknown`;
- never fabricate missing past prices.

- [ ] **Step 5: Verify CLI dry run**

```powershell
& $py -X utf8 radar.py guland-reconcile --limit 20
```

Expected: `apply=false`, bounded counts, no listing/raw/history timestamps
changed.

- [ ] **Step 6: Document production sequence**

Document:

```powershell
& $py -X utf8 radar.py guland-reconcile --limit 100
& $py -X utf8 radar.py guland-reconcile --limit 100 --apply
```

State that production apply requires explicit user approval after dry-run
counts are reviewed.

- [ ] **Step 7: Commit the reconciliation command**

```powershell
git add services/guland_historical_reconciliation.py cli/guland_reconciliation.py radar.py tests/test_guland_historical_reconciliation.py docs/daily_crawl_flow.md docs/operations.md
git commit -m "feat: add bounded guland reconciliation"
```

### Task 8: Full Verification Before Release

**Files:**
- Verify only; update plan checkboxes during execution.

**Interfaces:**
- Produces: release evidence; does not authorize production apply/deploy.

- [ ] **Step 1: Compile all touched Python**

```powershell
& $py -X utf8 -m py_compile db\schema.py db\raw_listings.py db\listings.py db\crawl_runs.py analytics\lifecycle.py services\guland_reconciliation.py services\guland_historical_reconciliation.py crawler\base_crawler.py crawler\guland_pw.py cleansing\reprocess.py cli\crawlers.py cli\guland_reconciliation.py cli\queries.py alerts\ops.py radar.py app.py services\market_data.py
```

- [ ] **Step 2: Run all focused Python tests**

```powershell
& $py -X utf8 -m pytest tests\test_postgres_connection.py tests\test_raw_insert_results.py tests\test_crawl_run_status.py tests\test_crawl_health.py tests\test_ops_alert.py tests\test_daily_crawl_limits.py tests\test_guland_crawler_stats.py tests\test_source_lifecycle.py tests\test_guland_reconciliation.py tests\test_guland_source_verifier.py tests\test_guland_targeted_reprocess.py tests\test_guland_historical_reconciliation.py tests\test_price_history.py tests\test_lot_history.py tests\test_drop_filter.py tests\test_source_policy.py -q
```

- [ ] **Step 3: Run UI tests and JavaScript syntax**

```powershell
node --check static\js\main\signal_card.js
node --check static\js\main\signals.js
node --check static\js\main\listing_map.js
node tests\js\test_signal_card.js
& $py -X utf8 -m pytest tests\test_signal_detail_ui.py tests\test_listing_map_js.py tests\test_refactor_structure.py -q
```

- [ ] **Step 4: Run local API smoke tests**

```powershell
& $py -X utf8 -c "from app import app; c=app.test_client(); [print(p, c.get(p).status_code) for p in ['/api/dashboard','/api/signals?page=1&limit=3']]"
```

Expected: both endpoints return 200; `/api/dashboard` remains lightweight and
`/api/signals` remains thumbnail-first.

- [ ] **Step 5: Run dry-run reconciliation and inspect samples**

```powershell
& $py -X utf8 radar.py guland-reconcile --limit 50
```

Confirm no writes, no unbounded request count, no secrets, and that sampled
price changes match live card/detail values.

- [ ] **Step 6: Review diff and request code review**

```powershell
git diff --check
git status --short
git log --oneline --decorate -12
```

Use `superpowers:requesting-code-review`, address only actionable findings, and
rerun affected tests.

- [ ] **Step 7: Finish the branch**

Use `superpowers:verification-before-completion` and
`superpowers:finishing-a-development-branch`. Do not merge, push, apply
production reconciliation, or deploy without the user's explicit release
instruction for this change set.
