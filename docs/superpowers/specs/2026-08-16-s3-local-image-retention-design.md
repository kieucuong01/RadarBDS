# Vietnix S3 Local Image Retention Design

## Status

Production already serves listing originals and 520x338 WebP thumbnails from
the public Vietnix S3 bucket. A live audit on 2026-08-16 found 68,203 local
image files consuming 2,105,159,680 bytes under
`/opt/radar-bds/current/data/images`. S3 reconciliation reported
`local=68203`, `remote_under_prefix=195721`, and `missing=0`.

The leak is operational rather than user-facing. `download_images()` uploads
the original and thumbnail before it records `listing_images.local_path`, but
successful uploads remain on local disk. The broker/profile-image cleanup then
uses those local files for face detection, so deleting them immediately inside
the downloader would silently weaken image-quality filtering.

## Goal

Keep at most seven days of successfully uploaded listing images on the VPS,
then remove only local files whose exact object keys are present in Vietnix S3.
The cleanup must not change database image keys, public URLs, image bytes,
thumbnail quality, request-time behavior, or the broker-image classifier.

The first production application should reclaim the verified files older than
seven days. The same retention pass must then run after the daily download and
broker-image cleanup sequence so disk usage does not grow without bound again.

## Non-goals

- Do not proxy image bytes through Flask or Nginx.
- Do not change the public S3 hostname, bucket ACL, object keys, image encoder,
  thumbnail dimensions, or cache metadata.
- Do not delete S3 objects in this phase.
- Do not move the live PostgreSQL database, Redis cache, Nginx cache, static
  application assets, Git checkout, or application release to object storage.
- Do not change `data/raw_backup.json` in this release. Compressed private-S3
  backup retention is a separate subsystem and release.
- Do not touch the unrelated dirty production social scripts.

## Considered approaches

### 1. Delete local files immediately after `put_object`

This has the smallest steady-state disk footprint, but it is rejected because
broker/profile-image detection runs after download and reads the local original
or thumbnail. Immediate deletion would preserve page rendering while degrading
content quality.

### 2. Run a verified seven-day retention pass after broker cleanup

This is the selected approach. It preserves the complete existing classifier
sequence, bounds local growth, and performs no work on the public request path.
The trade-off is one paginated S3 prefix listing during each scheduled crawl.

### 3. Keep manual cleanup only

This is rejected because the production directory already regrew from zero to
2.1 GB after the previous migration cleanup. A manual run fixes today's disk
pressure but does not fix recurrence.

## Components

### Retention service

Add `services/s3_local_retention.py` with a focused interface:

```python
def prune_verified_local_images(
    root: Path,
    *,
    min_age_days: int = 7,
    apply: bool = False,
    now: datetime | None = None,
) -> dict:
    ...
```

The service will:

1. Reject negative retention values and a missing/non-directory root.
2. Enumerate local image files only through the existing image-extension
   allowlist.
3. Fetch the complete `data/images/` S3 key set before deleting anything.
4. Classify each local file as too new, missing remotely, eligible, deleted, or
   failed to delete.
5. In dry-run mode, report counts and bytes without unlinking anything.
6. In apply mode, unlink only eligible files and preserve both image
   directories.

An S3 authentication, listing, or pagination error must raise before the first
local deletion. A key missing from S3 must remain local regardless of age.

### Operator CLI

Extend `scripts/s3_sync_images.py` with:

```text
--prune-local --min-age-days 7 [--apply]
```

`--prune-local` without `--apply` is a dry-run. Destructive CLI application is
allowed only when the resolved root is the canonical project
`data/images` directory. Existing `--dry-run`, `--upload`, and `--verify`
behavior remains unchanged.

The command prints one bounded summary containing local files/bytes, eligible
files/bytes, too-new files, remotely missing files, deleted files/bytes, and
delete failures. It does not print credentials or file contents.

### Daily crawl integration

After `_clean_broker_images_after_download()` returns, the daily crawl invokes
the retention service with `min_age_days=7` and `apply=True`. The hook is
best-effort and operationally isolated: a retention failure is logged and
reported as storage maintenance failure, but it does not relabel successfully
committed crawl, normalization, valuation, image upload, or database work as
failed.

The hook runs outside Flask request handling and therefore cannot add S3 calls
to `/`, `/api/signals`, `/api/listings`, `/api/counts`, `/api/dashboard`, Maps,
or listing-detail requests.

## Safety and data flow

```text
download original -> create WebP thumbnail -> put both S3 objects
    -> commit listing_images.local_path
    -> broker/profile-image cleanup using local files
    -> list complete S3 image prefix
    -> retain files younger than 7 days
    -> retain any key missing from S3
    -> unlink verified eligible local files only
```

Database values remain stable S3 object keys such as
`data/images/<asset>.<ext>`. Public URL resolution remains string-only through
`services.image_assets`; the cleanup never performs request-time S3 HEAD/GET
calls and never rewrites `listing_images`.

## Tests

Tests must prove the following with red-green TDD:

- dry-run reports eligible bytes without deleting files;
- apply deletes an old original and thumbnail when both keys exist remotely;
- a remotely missing file is preserved;
- a file younger than seven days is preserved;
- S3 listing failure leaves every local file untouched;
- the canonical-root guard blocks CLI apply against another directory;
- the daily crawl calls retention only after broker cleanup;
- retention failure does not erase the successful crawl outcome;
- existing S3 upload, image resolution, broker cleanup, and daily crawl tests
  remain green.

## Production rollout

1. Deploy code with the seven-day policy.
2. Run `--prune-local --min-age-days 7` and record eligible count/bytes.
3. Re-run full S3 reconciliation and require `missing=0`.
4. Run apply against the exact production image root.
5. Measure `df`, file count, and directory bytes.
6. Verify service activity, public API HTTP 200, all sampled URLs on Vietnix
   S3, thumbnail and original HTTP 200, WebP MIME, immutable cache metadata,
   and desktop/mobile image rendering.

Rollback is code-only: disable/remove the scheduled retention call and deploy.
Already-pruned local files are not required for normal rendering because the
public path is already S3. If local-mode disaster recovery is needed, restore
objects from S3 using the existing object keys.

## Acceptance

- Production dry-run and apply delete no file missing from the S3 prefix.
- Local files newer than seven days remain available to the classifier.
- The image root retains its directory structure.
- The root filesystem usage decreases by the measured deleted bytes.
- Public API and browser image URLs are unchanged and continue to bypass the
  VPS image-serving path.
- No request-time S3 operation is added.
- The next daily crawl completes image-quality cleanup before retention.
