# Crawl Reliability Phase 2: Images and Raw History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate Facebook image-object collisions, recover bounded Guland listings with zero usable images, harden downloads, and preserve append-only raw revisions for edits to the same source URL.

**Architecture:** Keep `raw_listings` as the latest normalized input and add an append-only `raw_listing_revisions` ledger behind repository helpers. Reconcile observed Facebook gallery slots and generate collision-free object keys from image-row identity plus normalized asset identity. Expand the existing dry-run-first Guland image repair to select zero-ready listings and use the hardened downloader.

**Tech Stack:** Python 3.12, PostgreSQL compatibility adapter, Flask repository modules, urllib, Pillow, Playwright, pytest.

## Global Constraints

- Do not add external LLM calls to crawl, reprocess, image recovery, or history.
- Facebook remains primary; Guland remains a bounded secondary workflow.
- Guland identity remains source-ID/URL based; do not add cross-URL same-lot heuristics.
- Existing image object paths remain readable; no destructive global rename.
- Dry-run is the default for Guland backfill and production apply requires explicit user approval.
- Do not merge, push, deploy, or mutate production as part of this plan.
- Use test-first RED → GREEN cycles and commit each independently reviewable task.

---

### Task 1: Append-only raw listing revisions

**Files:**
- Modify: `db/schema.py`
- Modify: `db/raw_listings.py`
- Create: `tests/test_raw_listing_history.py`

**Interfaces:**
- Produces: `canonical_raw_json(raw_data: Mapping) -> tuple[str, str]`
- Produces: `update_raw_listing_payload(raw_id: int, raw_data: Mapping, *, change_kind: str, crawl_run_id: int | None = None, conn=None) -> bool`
- Produces: `refresh_raw_listing(source: str, url: str, raw_data: dict, crawl_run_id: int | None = None, *, change_kind: str = "source_refresh") -> int`
- Produces: `get_raw_listing_revisions(raw_id: int) -> list[dict]`

- [x] **Step 1: Write failing schema and repository tests**

Create tests that:

```python
result = insert_raw_result("facebook", "post-1", url, {"text": "A"})
assert [r["revision_no"] for r in get_raw_listing_revisions(result.raw_id)] == [1]

assert update_raw_listing_payload(result.raw_id, {"text": "A"}, change_kind="source_refresh") is False
assert len(get_raw_listing_revisions(result.raw_id)) == 1

assert update_raw_listing_payload(result.raw_id, {"text": "B"}, change_kind="source_refresh") is True
assert update_raw_listing_payload(result.raw_id, {"text": "A"}, change_kind="source_refresh") is True
assert [r["revision_no"] for r in get_raw_listing_revisions(result.raw_id)] == [1, 2, 3]
assert [r["raw_json"]["text"] for r in get_raw_listing_revisions(result.raw_id)] == ["A", "B", "A"]
```

Also insert one legacy `raw_listings` row directly, refresh it, and assert that
the old state is seeded before the new state. Assert canonical JSON ignores
dictionary insertion order but not actual values.

- [x] **Step 2: Run tests and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_raw_listing_history.py -q
```

Expected: collection or schema assertions fail because the ledger and helpers
do not exist.

- [x] **Step 3: Add the revision schema**

Add `raw_listing_revisions` with:

```sql
id              INTEGER PRIMARY KEY AUTOINCREMENT,
raw_listing_id  INTEGER NOT NULL REFERENCES raw_listings(id) ON DELETE CASCADE,
revision_no     INTEGER NOT NULL,
source          TEXT NOT NULL,
source_id       TEXT,
url             TEXT NOT NULL,
raw_json        TEXT NOT NULL,
content_hash    TEXT NOT NULL,
changed_fields  JSONB NOT NULL DEFAULT '[]'::jsonb,
change_kind     TEXT NOT NULL,
crawl_run_id    INTEGER,
observed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
UNIQUE(raw_listing_id, revision_no)
```

Add indexes on `(raw_listing_id, revision_no DESC)` and
`(source, url, observed_at DESC)`. Add an idempotent migration helper for an
existing PostgreSQL database.

- [x] **Step 4: Implement revision-aware repository writes**

Canonicalize with:

```python
payload = json.dumps(raw_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

In one transaction:

1. lock/read the current raw row;
2. seed its current snapshot if no revisions exist;
3. return `False` for an identical hash;
4. compute literal sorted top-level changed keys;
5. append the next revision and update `raw_listings`;
6. return `True`.

Make `insert_raw_result()` append revision 1 only after the raw insert succeeds.
Keep duplicate insert behavior unchanged.

- [x] **Step 5: Run focused tests and verify GREEN**

```powershell
& $py -X utf8 -m pytest tests\test_raw_listing_history.py tests\test_raw_insert_results.py -q
& $py -X utf8 -m py_compile db\schema.py db\raw_listings.py
```

- [x] **Step 6: Commit**

```powershell
git add db/schema.py db/raw_listings.py tests/test_raw_listing_history.py
git commit -m "feat: preserve raw listing revisions"
```

---

### Task 2: Reconcile Facebook image slots without collisions

**Files:**
- Modify: `db/listings.py`
- Modify: `cleansing/reprocess.py`
- Modify: `cli/crawlers.py`
- Modify: `cleansing/image_cleanup.py`
- Modify: `db/guland_coordinates.py`
- Modify: `services/guland_image_backfill.py`
- Create: `tests/test_facebook_image_reconciliation.py`
- Modify: `tests/test_guland_coordinate_repository.py`
- Modify: `tests/test_guland_image_backfill.py`

**Interfaces:**
- Consumes: `update_raw_listing_payload(...)`
- Produces: `canonical_image_asset_key(url: str) -> str`
- Produces: `sync_listing_images(listing_id: int, img_urls: Sequence[str], *, source: str) -> dict[str, int]`

- [x] **Step 1: Write failing Facebook gallery tests**

Cover:

```python
# Same path, rotated signed query: retain one slot row and ready local_path.
sync_listing_images(listing_id, [url_with_sig_b], source="facebook")
assert rows == [{"img_order": 0, "img_url": url_with_sig_b, "local_path": old_path}]

# Different source asset at the same order: retain one slot row but reset download.
sync_listing_images(listing_id, [different_asset], source="facebook")
assert rows == [{"img_order": 0, "img_url": different_asset, "local_path": None}]

# A partial one-image observation does not delete historical slot 1.
assert image_orders == [0, 1]
```

Seed duplicate slot rows and assert the observed slot is collapsed to one
canonical row. Assert Guland and other sources keep URL-identity insert
behavior.

- [x] **Step 2: Run tests and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_facebook_image_reconciliation.py -q
```

- [x] **Step 3: Implement source-aware image synchronization**

Normalize an asset identity from lowercase scheme/host/path while dropping the
query and fragment. For Facebook:

- choose the newest ready row, otherwise newest row, for each observed order;
- keep `local_path` when normalized asset identity is unchanged;
- set `local_path=NULL`, `ocr_text=NULL`, and refresh `crawled_at` when changed;
- delete other rows in that observed order;
- update URL/order/type on the chosen row;
- insert a new row when the slot does not exist;
- do not delete unobserved higher orders.

For non-Facebook sources, retain URL-deduplicated insert semantics. Make
`reprocess_listings()` call `sync_listing_images()` with the listing source.

- [x] **Step 4: Route every runtime raw mutation through history**

Replace direct `UPDATE raw_listings SET raw_json` calls in:

- `_refresh_existing_facebook_images`;
- Guland repair-missing;
- broker-image cleanup;
- coordinate merge and rollback;
- Guland image recovery.

Use explicit `change_kind` values: `facebook_image_refresh`,
`source_repair`, `broker_image_cleanup`, `coordinate_backfill`,
`coordinate_rollback`, and `guland_image_recovery`.

- [x] **Step 5: Verify GREEN**

```powershell
& $py -X utf8 -m pytest `
  tests\test_facebook_image_reconciliation.py `
  tests\test_raw_listing_history.py `
  tests\test_guland_coordinate_repository.py `
  tests\test_guland_image_backfill.py `
  tests\test_guland_targeted_reprocess.py -q
```

- [x] **Step 6: Commit**

```powershell
git add db/listings.py cleansing/reprocess.py cli/crawlers.py cleansing/image_cleanup.py db/guland_coordinates.py services/guland_image_backfill.py tests/test_facebook_image_reconciliation.py tests/test_guland_coordinate_repository.py tests/test_guland_image_backfill.py
git commit -m "fix: reconcile repeated listing image slots"
```

---

### Task 3: Harden image downloading and object identity

**Files:**
- Modify: `cleansing/download_images.py`
- Modify: `tests/test_download_images.py`

**Interfaces:**
- Consumes: `canonical_image_asset_key(url: str)`
- Produces: `image_object_path(image_id: int, listing_id: int, img_url: str, format_name: str) -> tuple[Path, str]`
- Keeps: `download_images(...) -> int`

- [x] **Step 1: Add failing downloader tests**

Use real in-memory PNG bytes and controlled response doubles. Assert:

- two rows with the same listing/order receive different paths containing each
  image row ID;
- an HTTP 503 is retried and then succeeds;
- HTML with status 200 is rejected and does not update `local_path`;
- an oversized body is rejected before publishing a final file;
- terminal 404 writes `NOT_FOUND`;
- a failed S3 thumbnail upload leaves `local_path` unset;
- success uploads original and thumbnail before updating the row;
- no `.part` file remains after failure.

- [x] **Step 2: Run tests and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_download_images.py -q
```

- [x] **Step 3: Implement bounded validated download**

Use constants:

```python
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_ATTEMPTS = 3
TRANSIENT_HTTP_STATUS = {408, 429, 500, 502, 503, 504}
TERMINAL_HTTP_STATUS = {403, 404, 410}
```

Read at most `MAX_IMAGE_BYTES + 1`, decode/verify with Pillow, derive
`jpg/png/webp`, and compute:

```text
data/images/{listing_id}_{image_id}_{sha256(asset_key)[:12]}.{ext}
```

Write to a sibling `.part` path, call `os.replace`, create the thumbnail, then
upload. In S3 mode require the thumbnail path to exist and both uploads to
succeed before updating `local_path`. Retry only transient failures with
bounded backoff; clean partial/final local artifacts when publishing fails.

- [x] **Step 4: Verify GREEN and compatibility**

```powershell
& $py -X utf8 -m pytest `
  tests\test_download_images.py `
  tests\test_image_assets.py `
  tests\test_market_data_images.py `
  tests\test_image_cleanup.py `
  tests\test_s3_image_storage.py -q
& $py -X utf8 -m py_compile cleansing\download_images.py
```

- [x] **Step 5: Commit**

```powershell
git add cleansing/download_images.py tests/test_download_images.py
git commit -m "fix: harden listing image downloads"
```

---

### Task 4: Expand Guland backfill from zero rows to zero ready

**Files:**
- Modify: `services/guland_image_backfill.py`
- Modify: `cli/guland_images.py`
- Modify: `radar.py`
- Modify: `tests/test_guland_image_backfill.py`
- Modify: `tests/test_cli_command_logging.py`

**Interfaces:**
- Produces: `run_guland_image_backfill(*, apply=False, limit=50, recover_live_missing=True, download_recovered=True, include_inactive=False) -> dict[str, object]`

- [x] **Step 1: Write failing zero-ready tests**

Construct rows for:

- no image rows;
- `local_path=NULL`;
- `local_path=NOT_FOUND`;
- S3 original missing;
- S3 thumbnail missing;
- original and thumbnail both present.

Assert only the last listing is ready. Assert selection is limited to the
lowest listing IDs after deterministic ordering, with `1 <= limit <= 200`.
Assert dry-run performs no raw, image-row, reset, download, or S3 write.

On apply, assert a live-confirmed URL matching a `NOT_FOUND` row resets that
row to `NULL`, includes the listing in targeted download IDs, and records raw
history only when the payload changed.

- [x] **Step 2: Run tests and verify RED**

```powershell
& $py -X utf8 -m pytest tests\test_guland_image_backfill.py tests\test_cli_command_logging.py -q
```

- [x] **Step 3: Implement zero-ready planning and bounded CLI**

Compute ready listing IDs from DB rows plus the S3 key inventory. Select all
eligible raw targets whose listing ID is not ready, not only zero-row/raw-empty
targets. Add these stats:

```text
zero_row_targets
zero_ready_targets
live_checked_targets
live_recoverable_targets
retry_rows_reset
raw_updated
listing_images_inserted
recovered_images_downloaded
errors
```

Clamp/validate `--limit` to 1–200, default 50, and pass it from `radar.py`
through `cli/guland_images.py`. Preserve dry-run default and
`--include-inactive`.

- [x] **Step 4: Verify GREEN**

```powershell
& $py -X utf8 -m pytest `
  tests\test_guland_image_backfill.py `
  tests\test_cli_command_logging.py `
  tests\test_guland_crawler_stats.py `
  tests\test_daily_crawl_limits.py -q
& $py -X utf8 radar.py guland-image-backfill --help
```

- [x] **Step 5: Commit**

```powershell
git add services/guland_image_backfill.py cli/guland_images.py radar.py tests/test_guland_image_backfill.py tests/test_cli_command_logging.py
git commit -m "feat: recover zero-ready Guland images"
```

---

### Task 5: Operations documentation and final verification

**Files:**
- Modify: `docs/daily_crawl_flow.md`
- Modify: `docs/dev_commands.md`
- Modify: `docs/operations.md`
- Modify: this plan

**Interfaces:**
- Documents: local dry-run, bounded apply command, raw history behavior, and
  explicit production approval gate.

- [ ] **Step 1: Update operations documentation**

Document:

```powershell
& $py -X utf8 radar.py guland-image-backfill --limit 50
& $py -X utf8 radar.py guland-image-backfill --limit 50 --apply
```

State that apply checks zero-ready displayable listings, retries recovered
URLs, and writes raw revisions. Production apply still requires explicit user
approval.

- [ ] **Step 2: Run the focused phase-two suite**

```powershell
& $py -X utf8 -m pytest `
  tests\test_raw_listing_history.py `
  tests\test_raw_insert_results.py `
  tests\test_facebook_image_reconciliation.py `
  tests\test_download_images.py `
  tests\test_guland_image_backfill.py `
  tests\test_guland_coordinate_repository.py `
  tests\test_guland_targeted_reprocess.py `
  tests\test_guland_crawler_stats.py `
  tests\test_daily_crawl_limits.py `
  tests\test_cli_command_logging.py `
  tests\test_image_assets.py `
  tests\test_market_data_images.py `
  tests\test_image_cleanup.py `
  tests\test_s3_image_storage.py -q
```

- [ ] **Step 3: Run syntax and local dry-run verification**

```powershell
& $py -X utf8 -m py_compile `
  db\schema.py db\raw_listings.py db\listings.py `
  cli\crawlers.py cli\guland_images.py `
  cleansing\reprocess.py cleansing\download_images.py cleansing\image_cleanup.py `
  services\guland_image_backfill.py db\guland_coordinates.py radar.py
& $py -X utf8 radar.py guland-image-backfill --limit 20
git diff --check
```

Dry-run must report bounded counts and make no DB/object writes.

- [ ] **Step 4: Self-review inline**

Review the complete diff against the design:

- no remaining runtime direct update of `raw_listings.raw_json`;
- every new image object key includes image-row identity;
- Facebook query-only URL rotation retains a ready path;
- changed assets reset download state;
- Guland targets zero-ready rather than only zero-row;
- no production apply/deploy logic added.

Fix all critical or important findings and rerun affected tests.

- [ ] **Step 5: Run repository-wide tests**

Use the documented isolated test PostgreSQL URL and production-like public base
URL override:

```powershell
& $py -X utf8 -m pytest -q
```

Record exact passed, skipped, and failed counts. Do not claim the branch is
green if unrelated baseline failures remain.

- [ ] **Step 6: Commit documentation and verification evidence**

```powershell
git add docs/daily_crawl_flow.md docs/dev_commands.md docs/operations.md docs/superpowers/plans/2026-07-30-crawl-reliability-phase2-images-raw-history.md
git commit -m "docs: record phase two image verification"
```

- [ ] **Step 7: Stop before release**

Report commits, focused/full verification, dry-run counts, and any remaining
baseline failures. Do not merge, push, deploy, or run production `--apply`
without a new explicit instruction.
