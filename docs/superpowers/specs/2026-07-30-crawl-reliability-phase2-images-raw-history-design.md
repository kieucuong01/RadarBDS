# Crawl Reliability Phase 2: Images and Raw History Design

Date: 2026-07-30  
Status: approved inline by the user

## Goal

Make listing-image ingestion resilient to repeated crawls and transient CDN
failures, recover every displayable Guland listing that has zero usable images,
and preserve append-only revisions when a source edits the same listing URL.

## Evidence

The local PostgreSQL snapshot currently contains:

- 876 Facebook `(listing_id, img_order)` groups with more than one image row;
- 742 Facebook local/S3 object paths referenced by more than one image row;
- 20 eligible Guland listings with no `listing_images` rows;
- 842 eligible Guland listings with no ready image according to DB state;
- no raw revision table.

The existing downloader names files as `{listing_id}_{img_order}.{ext}`.
Different image rows at the same order therefore overwrite the same local/S3
object. The existing Guland backfill only refetches listings whose raw payload
has no image URLs or whose image-row count is zero, so it misses listings whose
rows are all `NULL`, `NOT_FOUND`, or missing required S3 objects/thumbnails.

## Considered Approaches

### 1. Enforce one database row per image order

Delete duplicate rows, add `UNIQUE(listing_id, img_order)`, and update rows in
place. This is compact, but it requires a destructive migration and an image
row cannot safely retain the same immutable-cache S3 key when its source asset
changes.

### 2. Stable current gallery plus collision-free object keys

Keep the existing table compatible, reconcile Facebook image slots when the
same URL is recrawled, and generate every newly downloaded object key from the
image-row ID plus a fingerprint of the source asset. Existing paths remain
readable. Raw revisions preserve prior image URLs and source content.

This is the selected approach. It fixes new collisions without renaming every
legacy object and permits a bounded repair of affected rows.

### 3. Content-addressed blob store

Introduce image blobs, hashes, and a many-to-many listing gallery. This gives
strong deduplication but is too large a storage migration for the reliability
work requested here.

## Architecture

### Raw revision ledger

Add `raw_listing_revisions` as an append-only child of `raw_listings`.
Each revision stores:

- `raw_listing_id`, `revision_no`, source identity and URL;
- the complete raw JSON snapshot;
- a deterministic SHA-256 content hash;
- top-level changed fields;
- `change_kind`, `crawl_run_id`, and `observed_at`.

New raw inserts write revision 1. A refresh first seeds the existing snapshot
when a legacy raw row has no history, then appends the incoming state only when
its canonical JSON differs from the current state. If content changes from A
to B and later back to A, all three ordered revisions remain. Identical
consecutive observations do not create noise.

All runtime writes to `raw_listings.raw_json` must use the repository helper,
including Facebook image refresh, Guland detail refresh, Guland image recovery,
coordinate apply/rollback, repair-missing, and broker-image cleanup. The
current `raw_listings` row remains the latest source of truth used by
normalization.

### Facebook gallery reconciliation

When a previously seen Facebook URL returns images:

1. refresh the raw payload through the revision-aware repository;
2. during targeted reprocess, reconcile the observed image slots;
3. retain a ready row when the canonical source asset path is unchanged and
   only volatile query parameters rotate;
4. replace a slot's current source URL and reset its download state when the
   canonical asset changes;
5. remove duplicate rows for the observed slot after choosing one canonical
   row; leave unobserved trailing slots intact so a partial Apify response
   cannot erase a larger historical gallery.

Prior gallery values remain available in raw revisions.

### Collision-free image objects

Every new download uses:

```text
data/images/{listing_id}_{image_id}_{asset_fingerprint}.{ext}
```

The fingerprint is derived from a normalized source URL without volatile query
parameters. The final extension comes from verified image content, not merely
the request URL. Existing `local_path` values remain valid and are not renamed
globally.

This makes object keys unique between database rows and prevents an immutable
S3 object from being overwritten when an image slot changes.

### Hardened downloader

The downloader:

- accepts only HTTP(S) image URLs;
- retries bounded transient HTTP/network failures;
- rejects empty, oversized, HTML, and undecodable responses;
- derives the file format by decoding with Pillow;
- writes to a temporary file and atomically replaces the destination;
- removes temporary/partial files on failure;
- in S3 mode marks a row ready only after both original and thumbnail uploads
  succeed;
- records terminal `403`, `404`, and `410` as `NOT_FOUND`;
- leaves transient failures retryable.

The public function remains backward compatible and continues returning the
number of successful downloads.

### Guland zero-ready recovery

A listing is `ready` when at least one image row has:

- a valid original object key;
- the original object present in S3 when S3 storage is enabled;
- the corresponding WebP thumbnail present in S3 when S3 storage is enabled.

The backfill targets every eligible Guland listing with zero ready images,
including listings that already have raw URLs or `listing_images` rows.
Dry-run remains the default. Add `--limit` with a safe range of 1–200 so live
detail-page refetch and apply are bounded.

On apply, live-confirmed URLs are merged into revisioned raw data, missing rows
are inserted, matching `NOT_FOUND` rows are made retryable, and downloads run
only for changed/zero-ready listing IDs. Statistics distinguish zero-row,
zero-ready, live-recoverable, reset, inserted, downloaded, and error counts.

No production `--apply`, merge, push, or deploy is authorized by this design.

## Error Handling and Safety

- Raw history and latest-raw update occur in one database transaction.
- Revision numbers are unique per raw listing.
- Duplicate observations are idempotent.
- Backfill dry-run performs no database or object writes.
- Backfill live fetch is bounded and errors are counted per listing.
- A failed thumbnail/S3 upload never publishes a ready `local_path`.
- Runtime data, image objects, and manifests remain outside git.

## Verification

Required automated coverage:

- raw insert, legacy seed, changed refresh, identical refresh, and A-B-A history;
- Facebook signed-URL rotation versus changed-asset slot reconciliation;
- unique object paths for rows sharing listing/order;
- downloader transient retry, invalid body, oversize response, atomic cleanup,
  and S3 original-plus-thumbnail gate;
- Guland zero-ready selection for `NULL`, `NOT_FOUND`, missing original, and
  missing thumbnail;
- bounded dry-run/apply and retry reset;
- existing crawl, image, coordinate, reconciliation, price-history, and public
  image tests.

Operational proof is a local dry-run only. Production apply requires a later
explicit instruction.
