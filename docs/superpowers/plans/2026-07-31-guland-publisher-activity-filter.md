# Guland Publisher Activity Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture reliable Guland publisher identity, classify manual versus high-volume/tool-like behavior, show only `low_manual` and `unknown` Guland listings to normal users, and provide a dry-run-first active-listing backfill.

**Architecture:** Keep publisher behavior in a new deterministic subsystem isolated from valuation and Guland lot identity. The crawler stores validated publisher evidence in raw revisions; PostgreSQL repositories link listings to publishers and maintain daily activity; shared SQL helpers enforce identical feed/count/map visibility. A bounded CLI backfill revisits current configured crawl cards plus active direct listing URLs without changing listing identity, `first_seen_at`, price history, images, coordinates, or valuation.

**Tech Stack:** Python 3.12, Flask, PostgreSQL/psycopg, Playwright, vanilla JavaScript, pytest, Node syntax checks.

## Global Constraints

- Facebook remains the primary source, but Guest/Free/VIP default sources become Facebook plus filtered Guland.
- Normal users see Guland `low_manual` first and `unknown` second; they never receive a control that reveals `high_activity` or `automated_repost`.
- Admin's `Ẩn người đăng dày/repost` toggle defaults to on; off shows every publisher class.
- Publisher activity is not a valuation/source-quality flag and must not affect fair value, MOS, signal score, price history, or `first_seen_at`.
- Guland remains source-ID-only for lot history and dedup; content similarity may classify spam but must never set `duplicate_of_id`.
- Missing identity is `unknown` and fail-open.
- No external LLM, paid enrichment, or new runtime dependency.
- Raw phones, profile URLs, member IDs, and stable publisher keys remain admin-only and are never returned by normal-user APIs.
- Production backfill is dry-run by default and requires a separately approved `--apply`.

---

## File Structure

### New files

- `services/guland_publisher_activity.py` — pure normalization, identity validation, HMAC keying, metrics, classification, and shared SQL expressions.
- `db/guland_publishers.py` — schema-facing publisher/link/activity repository and admin override queries.
- `services/guland_publisher_backfill.py` — bounded Playwright discovery/direct-detail orchestration and dry-run/apply planning.
- `cli/guland_publishers.py` — JSON CLI adapter.
- `tests/test_guland_publisher_activity.py` — pure identity/classification boundary tests.
- `tests/test_guland_publisher_repository.py` — schema, idempotency, aggregation, and override tests.
- `tests/test_guland_publisher_extraction.py` — crawler detail evidence and hotline rejection tests.
- `tests/test_guland_publisher_backfill.py` — target scope, dry-run, apply, preservation, and resume tests.

### Modified files

- `config/settings.py`, `.env.example` — publisher-key secret configuration.
- `db/schema.py`, `db/connection.py` — publisher tables, indexes, migration, and test cleanup registration.
- `crawler/guland_pw.py` — listing-scoped publisher DOM extraction and unchanged-card observation.
- `db/listings.py` — replace or clear stale Guland contact data only after a
  validated publisher-contact check.
- `cleansing/reprocess.py` — link processed Guland listings to raw publisher evidence; retire `guland_cluster_flood` generation.
- `services/signal_quality.py`, `services/valuation_tool.py` — retire historical cluster text as a blocking/baseline flag.
- `services/market_data.py` — filtered Guland public source policy, shared visibility predicate, and class-aware order.
- `services/listing_map.py` — identical publisher visibility and ordering for map summaries/items.
- `app.py` — admin toggle parsing, cache keys, admin publisher endpoints, and service argument propagation.
- `templates/index.html`, `static/js/main/filters.js` — admin-only hide/show toggle.
- `templates/admin_control_room.html`, `static/js/admin.js`, `static/css/admin.css` — publisher audit/override panel.
- `radar.py` — `guland-publisher-backfill` command routing.
- `tests/test_source_policy.py`, `tests/test_listing_map_service.py`, `tests/test_listing_map_api.py`, `tests/test_market_data_trust.py`, `tests/test_reprocess_review_hidden.py`, `tests/test_admin_control_room.py` — cross-surface and retired-gate regressions.
- `AGENTS.md`, `docs/product_rules.md`, `docs/daily_crawl_flow.md`, `docs/dev_commands.md`, `.env.example` — current source/filter/backfill operations.

---

### Task 1: Pure Publisher Identity and Classification Domain

**Files:**
- Create: `services/guland_publisher_activity.py`
- Create: `tests/test_guland_publisher_activity.py`
- Modify: `config/settings.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `PublisherEvidence`, `PublisherMetrics`, `PublisherClassification`.
- Produces: `normalize_vietnam_phone(value: str) -> str`.
- Produces: `validate_publisher_evidence(detail: Mapping[str, object], description: str) -> PublisherEvidence`.
- Produces: `validated_raw_publisher_fields(detail: Mapping[str, object], *, secret: str | None = None) -> dict[str, object]`.
- Produces: `build_publisher_key(evidence: PublisherEvidence, secret: str) -> str`.
- Produces: `classify_publisher(metrics: PublisherMetrics, confidence: str) -> PublisherClassification`.
- Produces: `effective_publisher_class(activity_class: str, manual_override: str) -> str`.
- Consumes: `GULAND_PUBLISHER_KEY_SECRET` from `config.settings`; tests pass explicit secrets and never read production secrets.

- [ ] **Step 1: Write failing phone and evidence tests**

```python
from services.guland_publisher_activity import (
    build_publisher_key,
    normalize_vietnam_phone,
    validate_publisher_evidence,
    validated_raw_publisher_fields,
)


def test_rejects_page_global_guland_hotline_and_uses_description_phone():
    evidence = validate_publisher_evidence(
        {
            "publisher_phone_candidate": "0983284379",
            "publisher_phone_scope": "footer",
            "publisher_profile_url": "",
            "publisher_source_id": "",
        },
        "Chính chủ bán đất, liên hệ 0912345678",
    )
    assert evidence.identity_type == "description_phone"
    assert evidence.confidence == "medium"
    assert normalize_vietnam_phone(evidence.phone) == "0912345678"


def test_member_identity_wins_over_phone_and_key_is_not_raw_identity():
    evidence = validate_publisher_evidence(
        {
            "publisher_source_id": "member-42",
            "publisher_profile_url": "https://guland.vn/user/member-42",
            "publisher_name": "Người đăng",
            "publisher_phone_candidate": "0912345678",
            "publisher_phone_scope": "listing_contact",
        },
        "",
    )
    key = build_publisher_key(evidence, "x" * 64)
    assert evidence.identity_type == "member_id"
    assert evidence.confidence == "high"
    assert len(key) == 64
    assert "member-42" not in key
    assert "0912345678" not in key


def test_missing_key_secret_degrades_reliable_evidence_to_unknown():
    raw = validated_raw_publisher_fields(
        {
            "publisher_source_id": "member-42",
            "publisher_profile_url": "",
            "publisher_phone_candidate": "",
            "publisher_phone_scope": "",
        },
        secret="",
    )
    assert raw["publisher_identity_status"] == "unknown"
    assert raw["publisher_identity_reason"] == "identity_secret_missing"
```

- [ ] **Step 2: Run the evidence tests and confirm the missing module failure**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_guland_publisher_activity.py -k "hotline or member_identity" -v
```

Expected: collection fails with `ModuleNotFoundError: services.guland_publisher_activity`.

- [ ] **Step 3: Implement normalization, scoped evidence validation, and HMAC keying**

Implement these immutable types:

```python
@dataclass(frozen=True)
class PublisherEvidence:
    status: str
    identity_type: str
    confidence: str
    source_id: str = ""
    profile_url: str = ""
    name: str = ""
    phone: str = ""
    reason: str = ""


@dataclass(frozen=True)
class PublisherMetrics:
    new_1d: int = 0
    new_7d: int = 0
    new_30d: int = 0
    max_new_on_day: int = 0
    active_days_30d: int = 0
    bumps_7d: int = 0
    bumps_30d: int = 0
    near_duplicates_max_day: int = 0
    days_ge_15_with_templates_14d: int = 0


@dataclass(frozen=True)
class PublisherClassification:
    activity_class: str
    reason: str
```

Validation rules:

- Canonicalize only `guland.vn`/`www.guland.vn` profile URLs with HTTPS and no non-default port.
- Accept phone candidate only when `publisher_phone_scope == "listing_contact"`.
- Reject support/footer/header candidates and known hotline values.
- Use `extract_phone(description)` only after member/profile/listing-contact evidence is absent.
- Return `status="unknown"`, `identity_type="unknown"`, and `confidence="low"` when no reliable identity exists.
- Build the key with `hmac.new(secret.encode(), namespaced_identity.encode(), hashlib.sha256).hexdigest()`.
- Raise `ValueError("GULAND_PUBLISHER_KEY_SECRET must contain at least 32 characters")` only when a reliable identity exists and the caller tries to key it with a short secret. Unknown evidence returns an empty key.
- `validated_raw_publisher_fields()` catches that configuration error, logs a
  safe warning without identity values, and returns
  `publisher_identity_status='unknown'` with
  `publisher_identity_reason='identity_secret_missing'`; a missing secret must
  never fail a listing crawl.

Add:

```python
GULAND_PUBLISHER_KEY_SECRET = os.getenv(
    "GULAND_PUBLISHER_KEY_SECRET", ""
).strip()
```

and add `GULAND_PUBLISHER_KEY_SECRET=` to `.env.example` with a comment requiring at least 32 random characters.

- [ ] **Step 4: Write failing classification boundary tests**

```python
@pytest.mark.parametrize(
    ("metrics", "expected"),
    [
        (PublisherMetrics(max_new_on_day=5, new_30d=30), "low_manual"),
        (PublisherMetrics(max_new_on_day=6, new_30d=30), "high_activity"),
        (PublisherMetrics(max_new_on_day=5, new_30d=31), "high_activity"),
        (PublisherMetrics(max_new_on_day=29, new_30d=80), "high_activity"),
        (PublisherMetrics(max_new_on_day=30, new_30d=80), "automated_repost"),
        (PublisherMetrics(bumps_7d=3), "automated_repost"),
        (PublisherMetrics(near_duplicates_max_day=10), "automated_repost"),
        (
            PublisherMetrics(days_ge_15_with_templates_14d=3),
            "automated_repost",
        ),
    ],
)
def test_classification_boundaries(metrics, expected):
    assert classify_publisher(metrics, "high").activity_class == expected


def test_insufficient_identity_confidence_stays_unknown_even_at_high_volume():
    result = classify_publisher(
        PublisherMetrics(max_new_on_day=45, new_30d=200),
        "low",
    )
    assert result.activity_class == "unknown"
```

- [ ] **Step 5: Run classification tests and confirm failure**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_guland_publisher_activity.py -k "classification or confidence" -v
```

Expected: tests fail because `classify_publisher` is not implemented.

- [ ] **Step 6: Implement exact classification and override precedence**

Use this decision order:

```python
if confidence not in {"medium", "high"}:
    return PublisherClassification("unknown", "insufficient_identity")
if metrics.max_new_on_day >= 30:
    return PublisherClassification("automated_repost", "new_listings_ge_30_day")
if metrics.bumps_7d >= 3:
    return PublisherClassification("automated_repost", "same_listing_bumps_ge_3_7d")
if metrics.near_duplicates_max_day >= 10:
    return PublisherClassification("automated_repost", "near_duplicates_ge_10_day")
if metrics.days_ge_15_with_templates_14d >= 3:
    return PublisherClassification("automated_repost", "template_burst_3d_14d")
if metrics.max_new_on_day > 5:
    return PublisherClassification("high_activity", "new_listings_gt_5_day")
if metrics.new_30d > 30:
    return PublisherClassification("high_activity", "new_listings_gt_30_30d")
return PublisherClassification("low_manual", "within_manual_thresholds")
```

`effective_publisher_class()` returns `low_manual` for `allow_manual`,
`automated_repost` for `hide_high_activity`, and otherwise returns the automatic
class.

- [ ] **Step 7: Run the domain tests**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_guland_publisher_activity.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit the pure domain**

```powershell
git add services/guland_publisher_activity.py tests/test_guland_publisher_activity.py config/settings.py .env.example
git commit -m "feat: classify Guland publisher activity"
```

---

### Task 2: Publisher Schema and Repository

**Files:**
- Create: `db/guland_publishers.py`
- Create: `tests/test_guland_publisher_repository.py`
- Modify: `db/schema.py`
- Modify: `db/connection.py`

**Interfaces:**
- Consumes: Task 1 `PublisherEvidence`, `PublisherMetrics`, `PublisherClassification`, `build_publisher_key()`, and `classify_publisher()`.
- Produces: `sync_listing_publisher(conn, listing_id: int, raw_data: Mapping[str, object], observed_at: datetime | None = None) -> int | None`.
- Produces: `record_listing_observation(conn, listing_id: int, observed_on: date, *, is_new: bool, source_date_changed: bool, near_duplicate_count: int = 0, repeated_template: bool = False) -> None`.
- Produces: `recompute_publisher(conn, publisher_id: int, as_of: date | None = None) -> PublisherClassification`.
- Produces: `set_publisher_override(conn, publisher_id: int, override: str, actor: str) -> dict`.
- Produces: `publisher_visibility_sql(alias: str = "l", include_high_activity: bool = False) -> str`.
- Produces: `publisher_sort_rank_sql(alias: str = "l") -> str`.

- [ ] **Step 1: Write failing schema and idempotency tests**

Create tests that call `init_schema()` and assert:

```python
tables = {
    row["table_name"]
    for row in conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='public'
          AND table_name IN (
              'source_publishers',
              'listing_publishers',
              'publisher_listing_observations',
              'publisher_activity_daily'
          )
        """
    ).fetchall()
}
assert tables == {
    "source_publishers",
    "listing_publishers",
    "publisher_listing_observations",
    "publisher_activity_daily",
}
```

Seed one Guland listing and call `sync_listing_publisher()` twice with identical
raw evidence. Assert one publisher row, one link row, and the same returned
publisher ID.

- [ ] **Step 2: Run repository tests and confirm missing tables/module**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_guland_publisher_repository.py -v
```

Expected: collection or schema assertions fail.

- [ ] **Step 3: Add idempotent PostgreSQL tables and indexes**

Add `_migrate_guland_publishers(conn)` to `db/schema.py` and call it from
`_run_migrations()`:

```sql
CREATE TABLE IF NOT EXISTS source_publishers (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('guland')),
    publisher_key TEXT NOT NULL,
    identity_type TEXT NOT NULL,
    identity_confidence TEXT NOT NULL
        CHECK (identity_confidence IN ('low','medium','high')),
    display_name TEXT NOT NULL DEFAULT '',
    activity_class TEXT NOT NULL DEFAULT 'unknown'
        CHECK (activity_class IN (
            'unknown','low_manual','high_activity','automated_repost'
        )),
    activity_reason TEXT NOT NULL DEFAULT '',
    manual_override TEXT NOT NULL DEFAULT ''
        CHECK (manual_override IN (
            '','allow_manual','hide_high_activity'
        )),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_classified_at TIMESTAMPTZ,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(source, publisher_key)
);

CREATE TABLE IF NOT EXISTS listing_publishers (
    listing_id BIGINT PRIMARY KEY
        REFERENCES listings(id) ON DELETE CASCADE,
    publisher_id BIGINT
        REFERENCES source_publishers(id) ON DELETE SET NULL,
    identity_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (identity_status IN ('identified','unknown','unreachable')),
    evidence_type TEXT NOT NULL DEFAULT 'unknown',
    identity_confidence TEXT NOT NULL DEFAULT 'low'
        CHECK (identity_confidence IN ('low','medium','high')),
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS publisher_activity_daily (
    publisher_id BIGINT NOT NULL
        REFERENCES source_publishers(id) ON DELETE CASCADE,
    activity_date DATE NOT NULL,
    new_listing_count INTEGER NOT NULL DEFAULT 0,
    seen_listing_count INTEGER NOT NULL DEFAULT 0,
    bump_count INTEGER NOT NULL DEFAULT 0,
    near_duplicate_count INTEGER NOT NULL DEFAULT 0,
    repeated_template_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(publisher_id, activity_date)
);

CREATE TABLE IF NOT EXISTS publisher_listing_observations (
    publisher_id BIGINT NOT NULL
        REFERENCES source_publishers(id) ON DELETE CASCADE,
    listing_id BIGINT NOT NULL
        REFERENCES listings(id) ON DELETE CASCADE,
    activity_date DATE NOT NULL,
    was_new BOOLEAN NOT NULL DEFAULT FALSE,
    was_seen BOOLEAN NOT NULL DEFAULT TRUE,
    was_bumped BOOLEAN NOT NULL DEFAULT FALSE,
    near_duplicate_count INTEGER NOT NULL DEFAULT 0,
    repeated_template BOOLEAN NOT NULL DEFAULT FALSE,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(publisher_id, listing_id, activity_date)
);
```

Add indexes on `source_publishers(activity_class, manual_override)`,
`source_publishers(last_seen_at DESC)`, and
`listing_publishers(publisher_id)`. Add only identity tables with a surrogate
`id` to the existing `ID_TABLES` helper; do not add either composite-key
activity table to automatic `RETURNING id`.

- [ ] **Step 4: Implement repository sync and unknown rows**

`sync_listing_publisher()` must:

1. Return without mutation for non-Guland listings.
2. Validate raw evidence through Task 1.
3. Upsert a `listing_publishers` row with `publisher_id=NULL` and
   `identity_status='unknown'` when evidence is insufficient.
4. Upsert `source_publishers` by `(source, publisher_key)` for reliable
   evidence.
5. Link the listing and update publisher `last_seen_at`.
6. Never copy raw phone/profile/member values into publisher API-facing
   aggregate columns.

- [ ] **Step 5: Write failing aggregation, classification, and override tests**

Seed daily rows that cover the exact Task 1 thresholds. Assert:

```python
classification = recompute_publisher(conn, publisher_id, date(2026, 7, 31))
assert classification.activity_class == "automated_repost"

updated = set_publisher_override(
    conn,
    publisher_id,
    "allow_manual",
    actor="admin:test",
)
assert updated["effective_class"] == "low_manual"
```

Also assert an `admin_audit_log` row records the before/after override and that
an invalid override raises `ValueError("invalid publisher override")`.

- [ ] **Step 6: Implement activity upsert, rolling metrics, SQL visibility, and overrides**

`record_listing_observation()` upserts
`publisher_listing_observations` by `(publisher_id, listing_id, activity_date)`
and combines evidence monotonically: boolean fields use logical OR and
`near_duplicate_count` uses `GREATEST`. It then rebuilds that publisher/day in
`publisher_activity_daily` from the observation ledger. Re-running the same
reprocess or backfill therefore cannot increment a count twice.

`recompute_publisher()` reads the rolling 1/7/14/30-day windows, calls Task 1,
and stores `activity_class`, `activity_reason`, `metrics_json`, and
`last_classified_at`.

`publisher_visibility_sql("l", False)` must evaluate:

```sql
(
  l.source <> 'guland'
  OR NOT EXISTS (
      SELECT 1
      FROM listing_publishers lp
      JOIN source_publishers sp ON sp.id=lp.publisher_id
      WHERE lp.listing_id=l.id
        AND CASE sp.manual_override
              WHEN 'allow_manual' THEN 'low_manual'
              WHEN 'hide_high_activity' THEN 'automated_repost'
              ELSE sp.activity_class
            END IN ('high_activity','automated_repost')
  )
)
```

When `include_high_activity=True`, return `1=1`.

`publisher_sort_rank_sql("l")` returns rank `0` for Facebook,
Guland `low_manual`, and `allow_manual`; rank `1` for missing/unknown links;
rank `2` for `high_activity`; and rank `3` for `automated_repost` or
`hide_high_activity`.

- [ ] **Step 7: Run repository and schema tests**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_guland_publisher_repository.py -v
```

Expected: all tests pass and cleanup removes every seeded publisher row.

- [ ] **Step 8: Commit schema and repository**

```powershell
git add db/schema.py db/connection.py db/guland_publishers.py tests/test_guland_publisher_repository.py
git commit -m "feat: persist Guland publisher activity"
```

---

### Task 3: Guland Detail Extraction and Crawl/Reprocess Integration

**Files:**
- Modify: `crawler/guland_pw.py`
- Modify: `cleansing/reprocess.py`
- Modify: `db/listings.py`
- Create: `tests/test_guland_publisher_extraction.py`
- Modify: `tests/test_guland_crawler_stats.py`
- Modify: `tests/test_guland_targeted_reprocess.py`

**Interfaces:**
- Consumes: Task 1 evidence validation and Task 2 repository functions.
- Produces raw detail keys: `publisher_source_id`, `publisher_profile_url`,
  `publisher_name`, `publisher_phone_candidate`, `publisher_phone_scope`.
- Produces raw normalized keys: `publisher_phone`,
  `publisher_identity_type`, `publisher_identity_confidence`,
  `publisher_identity_status`, `publisher_identity_checked_at`.
- Produces: `record_seen_guland_cards(conn, cards: Sequence[Mapping[str, object]], observed_at: datetime) -> dict[str, int]` in `db/guland_publishers.py`.

- [ ] **Step 1: Write failing extraction tests**

Use sanitized detail dictionaries and assert:

```python
def test_listing_contact_phone_beats_footer_hotline():
    detail = {
        "description": "Bán đất",
        "publisher_phone_candidate": "0912345678",
        "publisher_phone_scope": "listing_contact",
        "page_global_phone": "0983284379",
    }
    raw = validated_raw_publisher_fields(detail, secret="s" * 64)
    assert raw["publisher_phone"] == "0912345678"
    assert raw["publisher_identity_status"] == "identified"


def test_unscoped_phone_never_populates_contact_phone():
    detail = {
        "description": "Không có số liên hệ",
        "publisher_phone_candidate": "0983284379",
        "publisher_phone_scope": "footer",
    }
    raw = validated_raw_publisher_fields(detail, secret="s" * 64)
    assert raw["publisher_identity_status"] == "unknown"
    assert "publisher_phone" not in raw
```

Also assert `_build_record()` no longer copies a footer/global number into
`contact_phone`.

- [ ] **Step 2: Run extraction tests and confirm failure**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_guland_publisher_extraction.py -v
```

Expected: tests fail because validated publisher fields and scoped extraction
are absent.

- [ ] **Step 3: Scope DOM extraction to listing publisher components**

In `_JS_BATCH_DETAIL`, find publisher roots only within explicit detail/profile
components:

```javascript
const publisherRoot = doc.querySelector([
  '.dtl-profile',
  '.dtl-contact',
  '.profile-info',
  '[data-user-id]',
  '[class*="publisher"]',
  '[class*="seller"]'
].join(','));
const publisherPhoneEl = publisherRoot?.querySelector('a[href^="tel:"]');
const publisherProfileEl = publisherRoot?.querySelector(
  'a[href*="/user/"],a[href*="/users/"],a[href*="/profile/"]'
);
```

Return:

- `publisher_source_id` from `data-user-id`, profile path ID, or empty.
- `publisher_profile_url` from the canonical profile anchor or empty.
- `publisher_name` from the publisher root's name element or empty.
- `publisher_phone_candidate` only from `publisherRoot`.
- `publisher_phone_scope="listing_contact"` only when the candidate is inside
  `publisherRoot`; otherwise empty.

Keep a page-global phone only as diagnostic `page_global_phone`; never assign it
to `contact_phone` or publisher identity.

- [ ] **Step 4: Validate and persist raw publisher fields**

Add `validated_raw_publisher_fields(detail, secret=None)` to Task 1's service.
`_build_record()` merges those fields and sets `contact_phone` only from the
validated listing-scoped/description phone. It also records
`publisher_identity_checked_at` in ISO-8601 and
`publisher_identity_status='unknown'` when no reliable identity exists.

Update `_refresh_verified_price()` to copy only validated publisher keys, not
the raw page-global phone.

In the normalized record set `_publisher_contact_checked=True` whenever a
Guland detail page completed publisher extraction. Update existing Guland rows
in `db/listings.py` with:

```sql
contact_phone = CASE
    WHEN :is_guland <> 0 AND :publisher_contact_checked <> 0
    THEN :contact_phone
    ELSE contact_phone
END,
seller_name = CASE
    WHEN :is_guland <> 0
         AND NULLIF(BTRIM(:seller_name), '') IS NOT NULL
    THEN :seller_name
    ELSE seller_name
END,
```

This deliberately clears the known footer hotline when the checked detail has
no reliable contact. It must not clear Facebook contact data.

- [ ] **Step 5: Write failing reprocess-link and unchanged-card observation tests**

Seed:

1. A raw Guland row with member evidence.
2. A processed listing created by `run_targeted_reprocess([raw_id])`.
3. A second observation of the same card with changed `date_raw`.
4. An existing Guland listing whose `contact_phone` is the rejected footer
   hotline and whose checked detail has no reliable contact.

Assert:

```python
link = conn.execute(
    "SELECT publisher_id, identity_status FROM listing_publishers WHERE listing_id=?",
    (listing_id,),
).fetchone()
assert link["publisher_id"] is not None
assert link["identity_status"] == "identified"

daily = conn.execute(
    """
    SELECT seen_listing_count, bump_count
    FROM publisher_activity_daily
    WHERE publisher_id=? AND activity_date='2026-07-31'
    """,
    (link["publisher_id"],),
).fetchone()
assert daily["seen_listing_count"] == 1
assert daily["bump_count"] == 1

cleaned = conn.execute(
    "SELECT contact_phone FROM listings WHERE id=?",
    (hotline_listing_id,),
).fetchone()
assert cleaned["contact_phone"] in (None, "")
```

- [ ] **Step 6: Link publisher evidence during reprocess**

Immediately after `upsert_listing()` in `reprocess_listings()`:

```python
if rec["source"] == "guland":
    with get_conn() as conn:
        publisher_id = sync_listing_publisher(
            conn,
            listing_id,
            raw_data,
        )
        if publisher_id:
            record_listing_observation(
                conn,
                listing_id,
                date.today(),
                is_new=is_new,
                source_date_changed=False,
            )
            recompute_publisher(conn, publisher_id)
```

Observation insertion is idempotent through the normalized
`publisher_listing_observations` ledger from Task 2. Repeated reprocess of the
same raw ID must not increment `new_listing_count`.

- [ ] **Step 7: Observe unchanged cards without changing listing dates**

Call `record_seen_guland_cards()` from `_run_crawl()` after card discovery and
snapshot loading. For linked listings it:

- Increments one seen observation per listing/day.
- Compares card `date_raw` with current raw `date_raw`.
- Appends a raw revision with `change_kind='guland_source_bump'` only when
  `date_raw` changed.
- Increments `bump_count` for that publisher/day.
- Leaves processed `posted_at`, `first_seen_at`, and card activity unchanged.
- Returns changed raw IDs so targeted reprocess can sync evidence without a
  full reprocess.

- [ ] **Step 8: Run focused crawler/reprocess tests**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_guland_publisher_extraction.py `
  tests\test_guland_crawler_stats.py `
  tests\test_guland_targeted_reprocess.py -v
```

Expected: all tests pass; no test creates a cross-source-ID duplicate link.

- [ ] **Step 9: Commit extraction and integration**

```powershell
git add crawler/guland_pw.py cleansing/reprocess.py db/listings.py db/guland_publishers.py tests/test_guland_publisher_extraction.py tests/test_guland_crawler_stats.py tests/test_guland_targeted_reprocess.py
git commit -m "feat: capture Guland publisher evidence"
```

---

### Task 4: Dry-Run-First Active Guland Publisher Backfill

**Files:**
- Create: `services/guland_publisher_backfill.py`
- Create: `cli/guland_publishers.py`
- Create: `tests/test_guland_publisher_backfill.py`
- Modify: `radar.py`
- Modify: `db/guland_publishers.py`

**Interfaces:**
- Produces: `GulandPublisherBackfillTarget`.
- Produces: `load_guland_publisher_backfill_targets(limit: int) -> list[GulandPublisherBackfillTarget]`.
- Produces: `run_guland_publisher_backfill(*, apply: bool, limit: int, resume: bool = True) -> dict[str, object]`.
- CLI: `python -X utf8 radar.py guland-publisher-backfill --limit 100` is dry-run.
- CLI: `python -X utf8 radar.py guland-publisher-backfill --limit 100 --apply` writes.

- [ ] **Step 1: Write failing target-scope tests**

Seed Guland listings in these states:

- `active`: included.
- `inactive`: excluded.
- `unknown`, never publisher-checked: included for one attempt.
- `unreachable`, never publisher-checked: included for one attempt.
- `unknown`, already publisher-checked: excluded unless rediscovered on a
  current configured crawl card.

Assert the loader returns the expected listing IDs and is limited after stable
ordering by active first, unknown second, unreachable third, then listing ID.

- [ ] **Step 2: Write failing dry-run mutation guard**

Monkeypatch every mutation function to raise `AssertionError` and inject
deterministic current-card/detail results. Call:

```python
stats = run_guland_publisher_backfill(apply=False, limit=10)
assert stats["mode"] == "dry_run"
assert stats["would_identify"] == 1
assert stats["would_remain_unknown"] == 1
assert stats["raw_updated"] == 0
assert stats["publisher_links_updated"] == 0
```

- [ ] **Step 3: Run backfill tests and confirm missing service**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_guland_publisher_backfill.py -v
```

Expected: collection fails because the service does not exist.

- [ ] **Step 4: Implement bounded target loading and one-browser fetch**

Reuse `GulandCrawler.TARGET_URLS`, `_scroll_all_cards()`, and
`_fetch_details_batch()` in one Playwright browser session:

1. Discover current configured cards with incremental/current crawl depth.
2. Union discovered URLs with active DB targets.
3. Add never-checked unknown/unreachable targets.
4. Fetch direct details in bounded batches.
5. Verify detail URL/source ID with existing Guland identity helpers.
6. Classify removed pages as excluded, network/Cloudflare as unreachable, and
   successful identity-matching pages as live.

The limit must be validated to `1..500`. The service must respect the existing
Guland crawl lock and return a non-zero error result instead of mutating on
lock contention.

- [ ] **Step 5: Implement plan/apply separation and checkpoint**

Dry-run builds an in-memory plan and returns:

- `candidates_by_status`
- `cards_scanned`
- `pages_fetched`
- `live`
- `removed`
- `unreachable`
- `identity_by_type`
- `estimated_classes`
- `would_identify`
- `would_remain_unknown`
- `raw_updated=0`
- `publisher_links_updated=0`

Apply writes a checkpoint manifest under
`.local/guland-publisher-backfill/<run-id>.json`. Each applied target:

- Merges publisher evidence into current raw JSON.
- Calls `update_raw_listing_payload(..., change_kind="guland_publisher_backfill")`.
- Calls targeted reprocess only for changed raw IDs.
- Syncs links/activity and recomputes affected publishers.
- Records unknown/unreachable `listing_publishers.checked_at` so the one-time
  retry is durable.

Resume skips manifest rows already marked `applied`. Manifest values must not
include raw phone, profile URL, member ID, HMAC secret, or publisher key.

- [ ] **Step 6: Add preservation and idempotency tests**

Capture before/after values for:

```sql
SELECT first_seen_at, posted_at, price_ty, price_updated_at, source_id
FROM listings WHERE id=?
```

and counts/hashes for price history, images, coordinates, and valuation rows.
Assert apply changes publisher evidence/link only, and the second identical
apply reports zero raw changes and zero duplicate activity increments.

- [ ] **Step 7: Route the CLI**

Add parser:

```python
p_guland_publishers = sub.add_parser(
    "guland-publisher-backfill",
    help="Dry-run-first publisher identity/activity backfill for live Guland listings",
)
p_guland_publishers.add_argument("--limit", type=int, default=100)
p_guland_publishers.add_argument("--apply", action="store_true")
p_guland_publishers.add_argument(
    "--no-resume",
    action="store_false",
    dest="resume",
)
p_guland_publishers.set_defaults(resume=True)
```

Route to `cmd_guland_publisher_backfill(args)`, print safe sorted JSON, and
return the stats object.

- [ ] **Step 8: Run backfill and CLI tests**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_guland_publisher_backfill.py -v
& $py -X utf8 radar.py guland-publisher-backfill --help
```

Expected: tests pass and help shows dry-run default, `--apply`, `--limit`, and
`--no-resume`.

- [ ] **Step 9: Commit the backfill**

```powershell
git add services/guland_publisher_backfill.py cli/guland_publishers.py db/guland_publishers.py radar.py tests/test_guland_publisher_backfill.py
git commit -m "feat: backfill live Guland publisher identity"
```

---

### Task 5: Public Feed, Dashboard, and Map Visibility Parity

**Files:**
- Modify: `services/market_data.py`
- Modify: `services/listing_map.py`
- Modify: `app.py`
- Modify: `services/signal_quality.py`
- Modify: `services/valuation_tool.py`
- Modify: `cleansing/reprocess.py`
- Modify: `tests/test_source_policy.py`
- Modify: `tests/test_listing_map_service.py`
- Modify: `tests/test_listing_map_api.py`
- Modify: `tests/test_market_data_trust.py`
- Modify: `tests/test_reprocess_review_hidden.py`

**Interfaces:**
- Consumes: Task 2 `publisher_visibility_sql()` and `publisher_sort_rank_sql()`.
- Adds service argument: `include_guland_high_activity: bool = False`.
- Adds request helper: `_include_guland_high_activity(req, tier: str) -> bool`.
- Extends `MapFilters` with `include_guland_high_activity: bool = False`.

- [ ] **Step 1: Replace old Facebook-only source tests with failing filtered-Guland tests**

Update `tests/test_source_policy.py` so Guest/Free/VIP expectations are:

```python
def test_guest_defaults_to_facebook_plus_safe_guland(self):
    feed = self.client.get(
        f"/api/signals?city=Khac&ward={self.ward}&date_range=all&limit=20"
    ).get_json()
    assert {row["source"] for row in feed["signals"]} == {
        "facebook",
        "guland",
    }
    dashboard = self.client.get(
        f"/api/dashboard?city=Khac&ward={self.ward}&date_range=all"
    ).get_json()
    assert dashboard["active_sources"] == ["facebook", "guland"]


def test_guest_guland_query_hides_high_activity_but_keeps_unknown(self):
    self._link_guland_class(self.guland_id, "high_activity")
    unknown_id = self._seed_signal(
        source="guland",
        title="Unknown publisher stays visible",
        source_id="guland-unknown",
    )
    payload = self.client.get(
        f"/api/signals?city=Khac&ward={self.ward}"
        "&source=guland&date_range=all&limit=20"
    ).get_json()
    assert [row["id"] for row in payload["signals"]] == [unknown_id]
```

Add this deterministic test helper to the class:

```python
def _link_guland_class(self, listing_id, activity_class):
    from db.connection import get_conn

    with get_conn() as conn:
        publisher_id = conn.execute(
            """
            INSERT INTO source_publishers (
                source, publisher_key, identity_type,
                identity_confidence, activity_class
            )
            VALUES ('guland', ?, 'member_id', 'high', ?)
            """,
            (f"test-key-{listing_id}", activity_class),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO listing_publishers (
                listing_id, publisher_id, identity_status,
                evidence_type, identity_confidence
            )
            VALUES (?, ?, 'identified', 'member_id', 'high')
            """,
            (listing_id, publisher_id),
        )
```

Add a three-row ordering test: `low_manual` before `unknown` even when the
unknown row has a newer activity timestamp; existing order still applies
inside each class.

- [ ] **Step 2: Run source-policy tests and confirm the old Facebook-only behavior fails**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_source_policy.py -v
```

Expected: new Guest/Guland assertions fail.

- [ ] **Step 3: Change source normalization and shared listing filters**

Set:

```python
DEFAULT_VISIBLE_SOURCES = ("facebook", "guland")
PUBLIC_SOURCE_OPTIONS = frozenset(DEFAULT_VISIBLE_SOURCES)
ADMIN_SOURCE_OPTIONS = DEFAULT_VISIBLE_SOURCES
```

`normalize_sources_for_tier()` must validate requested sources for every tier
instead of discarding non-admin source requests.

Add `include_guland_high_activity=False` to `build_listing_filters()` and append
`publisher_visibility_sql(alias, include_guland_high_activity)` to its
`where_parts`. Propagate the argument through `load_signals()`,
`load_dashboard_summary()`, `load_counts()`, trend/indicator queries, and cache
keys.

Prefix every signal ordering expression with
`publisher_sort_rank_sql("l") ASC` when high activity is hidden. Do not expose
publisher keys or raw identity fields in `_format_signal_row()`.

- [ ] **Step 4: Retire `guland_cluster_flood` as a hard quality gate**

- Remove `guland_cluster_flood` from `ACTIONABLE_SUPPRESS_FLAGS`.
- Remove it from valuation baseline exclusion flags.
- Remove `_guland_cluster_key()` and `_guland_cluster_flag_map()` calls from
  reprocess.
- Update tests to prove a historical valuation row containing only
  `guland_cluster_flood` remains actionable.
- Preserve price/parser/source correctness blockers unchanged.

- [ ] **Step 5: Write failing map parity tests**

Seed one location group containing:

- Facebook.
- Guland `low_manual`.
- Guland `unknown`.
- Guland `high_activity`.
- Guland `automated_repost`.

Assert normal summary total and item pagination include only the first three,
and items order low/manual before unknown for Guland. Assert page 2 cannot
reintroduce hidden publisher classes.

- [ ] **Step 6: Apply the same visibility to map SQL and cache versions**

Add `include_guland_high_activity` to `MapFilters`, `_filtered_sql()`, summary
and item cache keys. Use the same Task 2 visibility and rank SQL; do not
duplicate class names in `services/listing_map.py`.

Include publisher table `MAX(last_classified_at/last_seen_at)` in
`get_listing_map_data_version()` so classification changes invalidate map
caches across processes.

- [ ] **Step 7: Parse admin include mode and propagate through every API**

Implement:

```python
def _include_guland_high_activity(req, tier: str) -> bool:
    return (
        tier == "admin"
        and (req.args.get("hide_guland_reposts") or "1").strip() == "0"
    )
```

Pass the bool to dashboard, counts, signals, all-listings, map summary, and map
item services. Include it in every relevant Flask and service cache key.
Guest/Free/VIP ignore attempts to send `hide_guland_reposts=0`.

- [ ] **Step 8: Run source/feed/map/gate tests**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_source_policy.py `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py `
  tests\test_market_data_trust.py `
  tests\test_reprocess_review_hidden.py -v
```

Expected: all tests pass; dashboard count equals feed total for each source and
admin toggle mode.

- [ ] **Step 9: Commit visibility parity**

```powershell
git add services/market_data.py services/listing_map.py services/signal_quality.py services/valuation_tool.py cleansing/reprocess.py app.py tests/test_source_policy.py tests/test_listing_map_service.py tests/test_listing_map_api.py tests/test_market_data_trust.py tests/test_reprocess_review_hidden.py
git commit -m "feat: filter Guland publisher activity on public surfaces"
```

---

### Task 6: Admin Toggle, Publisher Audit, and Overrides

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/main/filters.js`
- Modify: `templates/admin_control_room.html`
- Modify: `static/js/admin.js`
- Modify: `static/css/admin.css`
- Modify: `app.py`
- Modify: `db/guland_publishers.py`
- Modify: `tests/test_admin_control_room.py`
- Modify: `tests/test_source_policy.py`

**Interfaces:**
- Produces admin endpoint: `GET /admin/api/guland-publishers?activity_class=&limit=&offset=`.
- Produces admin endpoint: `POST /admin/api/guland-publishers/<publisher_id>/override`.
- Override body: `{"override":"allow_manual|hide_high_activity|"}`.
- Produces safe summary fields: publisher ID, display name, class, effective
  class, confidence, reason, rolling metrics, linked listing count, last seen.

- [ ] **Step 1: Write failing admin toggle tests**

Assert admin dashboard HTML contains:

```html
<input id="hideGulandReposts" type="checkbox" checked>
```

Then seed high-activity Guland and assert:

- Admin request without the parameter hides it.
- `hide_guland_reposts=1` hides it.
- `hide_guland_reposts=0` shows it.
- Guest request with `hide_guland_reposts=0` still hides it.

- [ ] **Step 2: Implement the main-dashboard admin toggle**

Inside the admin-only source filter group add:

```html
<label class="filter-option">
  <input id="hideGulandReposts" type="checkbox" checked>
  Ẩn người đăng dày/repost
</label>
```

In `getFilterQuery()`:

```javascript
const hideGulandReposts = document.getElementById('hideGulandReposts');
if (hideGulandReposts) {
  params.set(
    'hide_guland_reposts',
    hideGulandReposts.checked ? '1' : '0'
  );
}
```

The existing filter change listener must trigger a signals-first refresh.

- [ ] **Step 3: Write failing publisher list/override API tests**

Assert non-admin receives 403. Assert admin list payload does not include
`publisher_key`, raw phone, profile URL, member ID, or HMAC secret.

Post each valid override and assert effective class plus one
`admin_audit_log` row. Post `{"override":"spam"}` and assert HTTP 400 with
`{"error":"invalid_publisher_override"}`.

- [ ] **Step 4: Implement admin-safe repository list and Flask endpoints**

Repository ordering:

1. `automated_repost`
2. `high_activity`
3. `unknown`
4. `low_manual`
5. newest `last_seen_at`

Return aggregate counts only. Use the existing admin auth decorator and actor
identity. Clear dashboard/map caches after an override.

- [ ] **Step 5: Add a Data Quality publisher tab**

Add segment:

```html
<button class="segment" data-quality-tab="publisher_qc">
  Người đăng Guland
</button>
```

Render cards/rows with:

- Display name or `Không có tên`.
- Activity class and reason.
- New 1/7/30-day counts.
- Maximum one-day volume.
- Bump and near-duplicate counts.
- Identity confidence.
- Buttons `Cho phép thủ công`, `Ẩn hoạt động cao`, `Xóa ghi đè`.

Do not render phone/profile/member/publisher key.

Extend `qualityQueueRoot()` and loading functions without mixing publisher rows
into source-quality queues.

- [ ] **Step 6: Add CSS and bump admin asset versions**

Add focused `.publisher-qc-*` rules responsive at existing admin breakpoints.
Update the admin JS/CSS query version in `templates/admin_control_room.html` so
production does not retain stale assets.

- [ ] **Step 7: Run admin and browser-JS syntax tests**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_admin_control_room.py tests\test_source_policy.py -v
node --check static\js\main\filters.js
node --check static\js\admin.js
```

Expected: tests and syntax checks pass.

- [ ] **Step 8: Commit admin controls**

```powershell
git add templates/index.html static/js/main/filters.js templates/admin_control_room.html static/js/admin.js static/css/admin.css app.py db/guland_publishers.py tests/test_admin_control_room.py tests/test_source_policy.py
git commit -m "feat: manage Guland publisher filtering"
```

---

### Task 7: Documentation, Full Verification, and Production Runbook

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/product_rules.md`
- Modify: `docs/daily_crawl_flow.md`
- Modify: `docs/dev_commands.md`
- Modify: `docs/operations.md`
- Modify: `tests/test_listing_map_query_scope.py`
- Modify: `tests/test_market_data_performance.py`

**Interfaces:**
- Documents the public source-policy change and safe backfill commands.
- Documents that production apply is separate from deployment.

- [ ] **Step 1: Update product and agent rules**

Record:

- Facebook remains primary for crawl order and valuation.
- Guest/Free/VIP may see filtered Guland.
- `low_manual` and `unknown` are visible; high/tool-like classes are hidden.
- Publisher activity is not a quality/valuation flag.
- Guland dedup remains source-ID-only.
- `guland_cluster_flood` is retired as a hard gate.

- [ ] **Step 2: Document daily and backfill operations**

Add exact commands:

```powershell
# Local/production dry-run
& $py -X utf8 radar.py guland-publisher-backfill --limit 100

# Apply only after reviewing dry-run counts and receiving explicit approval
& $py -X utf8 radar.py guland-publisher-backfill --limit 100 --apply
```

Document safe output fields, checkpoint location, resume behavior, the required
`GULAND_PUBLISHER_KEY_SECRET`, and post-apply feed/map/count checks.

- [ ] **Step 3: Add query-scope and performance regressions**

Assert publisher visibility uses one indexed `NOT EXISTS` predicate and no
per-row Python DB query. Update market-data performance fixtures with publisher
tables and prove `/api/dashboard`, `/api/signals?page=1&limit=30`, and map
summary remain within existing query-count contracts.

- [ ] **Step 4: Run syntax and focused tests**

Run:

```powershell
& $py -X utf8 -m py_compile `
  app.py `
  radar.py `
  config\settings.py `
  crawler\guland_pw.py `
  cleansing\reprocess.py `
  db\listings.py `
  db\schema.py `
  db\guland_publishers.py `
  services\guland_publisher_activity.py `
  services\guland_publisher_backfill.py `
  services\market_data.py `
  services\listing_map.py `
  services\signal_quality.py `
  services\valuation_tool.py

node --check static\js\main\filters.js
node --check static\js\admin.js

& $py -X utf8 -m pytest `
  tests\test_guland_publisher_activity.py `
  tests\test_guland_publisher_repository.py `
  tests\test_guland_publisher_extraction.py `
  tests\test_guland_publisher_backfill.py `
  tests\test_guland_crawler_stats.py `
  tests\test_guland_targeted_reprocess.py `
  tests\test_source_policy.py `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_query_scope.py `
  tests\test_market_data_trust.py `
  tests\test_market_data_performance.py `
  tests\test_reprocess_review_hidden.py `
  tests\test_admin_control_room.py -v
```

Expected: all commands exit 0.

- [ ] **Step 5: Run the broader crawl/data regression set**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_guland.py `
  tests\test_guland_reconciliation.py `
  tests\test_guland_historical_reconciliation.py `
  tests\test_guland_image_extraction.py `
  tests\test_guland_image_backfill.py `
  tests\test_guland_coordinates.py `
  tests\test_guland_coordinate_backfill.py `
  tests\test_dedup.py `
  tests\test_price_history.py `
  tests\test_lot_history.py `
  tests\test_drop_filter.py `
  tests\test_guest_visibility.py -v
```

Expected: all commands exit 0 and no Guland cross-ID history behavior changes.

- [ ] **Step 6: Run a local dry-run with no writes**

Ensure `.env.local` contains a local-only
`GULAND_PUBLISHER_KEY_SECRET` of at least 32 characters without printing it.
Capture table counts before and after:

```powershell
& $py -X utf8 radar.py guland-publisher-backfill --limit 20
```

Expected:

- JSON reports `mode="dry_run"`.
- Candidate/live/identity/class estimates are present.
- Publisher/raw/listing table write counts remain unchanged.
- No secret or raw publisher identity appears in output.

- [ ] **Step 7: Verify docs and working tree**

Run:

```powershell
git diff --check
rg -n "T[B]D|T[O]DO|PLACEH[O]LDER" `
  docs\superpowers\plans\2026-07-31-guland-publisher-activity-filter.md `
  docs\superpowers\specs\2026-07-31-guland-publisher-activity-filter-design.md
git status --short
```

Expected: no whitespace error, no incomplete marker, and only intended files
are modified.

- [ ] **Step 8: Commit documentation and verification contracts**

```powershell
git add AGENTS.md docs/product_rules.md docs/daily_crawl_flow.md docs/dev_commands.md docs/operations.md tests/test_listing_map_query_scope.py tests/test_market_data_performance.py
git commit -m "docs: operate Guland publisher filtering"
```

- [ ] **Step 9: Prepare production release without applying the backfill**

After the implementation branch is reviewed and merged:

1. Pull/rebase current `origin/main`.
2. Push the reviewed branch/main as requested.
3. Deploy the saved commit.
4. Apply the idempotent schema migration with the production owner path.
5. Verify `radar-bds.service=active`.
6. Verify internal and public 200 responses for dashboard, signals, and map.
7. Confirm normal-user Guland payloads contain no publisher identity.
8. Run production `guland-publisher-backfill --limit 100` dry-run only.
9. Report dry-run candidate, coverage, and class counts.
10. Wait for explicit approval before production `--apply`.
