# S3 Zero-Local Listing Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upload listing originals and thumbnails to Vietnix S3, keep local files only through broker-image classification, then remove every exact-key-verified local copy.

**Architecture:** Add one fail-closed retention service that snapshots local image files, fetches the full S3 image-key set before deleting anything, and unlinks only exact matches. Reuse it from the existing S3 migration CLI for operator dry-run/apply and invoke it after the shared broker-image cleanup helper so no Flask request path performs S3 I/O.

**Tech Stack:** Python 3.12, pathlib, existing boto3-compatible S3 helpers, argparse, pytest/unittest mocks, PostgreSQL-backed crawl workflow.

## Global Constraints

- Public listing originals and 520x338 WebP thumbnails must keep their existing Vietnix S3 URLs, bytes, MIME types, and `Cache-Control: public, max-age=2592000, immutable` metadata.
- Broker/profile-image detection must finish while local files still exist.
- A missing S3 key, disabled S3 mode, S3 listing failure, or unsafe apply root must preserve local files.
- The service may delete only supported image files below the exact resolved image root; it must preserve directories and `.part` files.
- No S3 HEAD/GET/LIST call may be added to Flask/Nginx/public API request handling.
- Crawl, normalization, valuation, database commits, notifications, and cache publication must not be relabeled failed by optional local-storage maintenance.
- Preserve the unrelated `.playwright-cli/` local artifact and the two dirty production social scripts.
- `data/raw_backup.json` private-S3 offload is a separate release after this production rollout passes.

---

### Task 1: Fail-closed local image pruning service

**Files:**
- Create: `services/s3_local_retention.py`
- Create: `tests/test_s3_local_retention.py`

**Interfaces:**
- Consumes: `services.s3_image_storage.iter_image_files(root)`, `list_object_keys("data/images/")`, and `s3_image_storage_enabled()`.
- Produces: `prune_verified_local_images(root: Path, *, apply: bool = False) -> dict` with stable integer fields `local_files`, `local_bytes`, `eligible_files`, `eligible_bytes`, `missing_remote_files`, `missing_remote_bytes`, `deleted_files`, `deleted_bytes`, and `delete_failures`.

- [ ] **Step 1: Read the good-test rules before editing tests**

Read `C:\Users\ASUS\.codex\plugins\cache\openai-curated-remote\superpowers\6.2.0\skills\test-driven-development\writing-good-tests.md` completely.

- [ ] **Step 2: Write failing dry-run and apply tests**

Create tests using real temporary files and mock only the external S3 key listing:

```python
from pathlib import Path

import pytest

from services import s3_local_retention as retention


def _image_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "data" / "images"
    thumb = root / "thumbs" / "sample.webp"
    original = root / "sample.jpg"
    thumb.parent.mkdir(parents=True)
    original.write_bytes(b"original")
    thumb.write_bytes(b"thumb")
    return root, original, thumb


def test_dry_run_reports_exact_matches_without_deleting(tmp_path, monkeypatch):
    root, original, thumb = _image_tree(tmp_path)
    monkeypatch.setattr(retention, "s3_image_storage_enabled", lambda: True)
    monkeypatch.setattr(
        retention,
        "list_object_keys",
        lambda _prefix: {"data/images/sample.jpg", "data/images/thumbs/sample.webp"},
    )

    stats = retention.prune_verified_local_images(root, apply=False)

    assert stats["eligible_files"] == 2
    assert stats["deleted_files"] == 0
    assert original.exists() and thumb.exists()


def test_apply_deletes_only_exact_remote_matches(tmp_path, monkeypatch):
    root, original, thumb = _image_tree(tmp_path)
    missing = root / "missing.png"
    missing.write_bytes(b"keep")
    monkeypatch.setattr(retention, "s3_image_storage_enabled", lambda: True)
    monkeypatch.setattr(
        retention,
        "list_object_keys",
        lambda _prefix: {"data/images/sample.jpg", "data/images/thumbs/sample.webp"},
    )

    stats = retention.prune_verified_local_images(root, apply=True)

    assert stats["deleted_files"] == 2
    assert stats["missing_remote_files"] == 1
    assert not original.exists() and not thumb.exists()
    assert missing.exists()
    assert root.is_dir() and (root / "thumbs").is_dir()


def test_s3_listing_failure_preserves_every_local_file(tmp_path, monkeypatch):
    root, original, thumb = _image_tree(tmp_path)
    monkeypatch.setattr(retention, "s3_image_storage_enabled", lambda: True)

    def fail_listing(_prefix):
        raise RuntimeError("S3 list failed")

    monkeypatch.setattr(retention, "list_object_keys", fail_listing)

    with pytest.raises(RuntimeError, match="S3 list failed"):
        retention.prune_verified_local_images(root, apply=True)

    assert original.exists() and thumb.exists()


def test_disabled_s3_and_partial_files_are_never_pruned(tmp_path, monkeypatch):
    root, original, thumb = _image_tree(tmp_path)
    partial = root / "inflight.jpg.part"
    partial.write_bytes(b"partial")
    monkeypatch.setattr(retention, "s3_image_storage_enabled", lambda: False)

    with pytest.raises(RuntimeError, match="not enabled"):
        retention.prune_verified_local_images(root, apply=True)

    assert original.exists() and thumb.exists() and partial.exists()


def test_partial_file_is_outside_the_supported_image_snapshot(tmp_path, monkeypatch):
    root, original, thumb = _image_tree(tmp_path)
    partial = root / "inflight.jpg.part"
    partial.write_bytes(b"partial")
    monkeypatch.setattr(retention, "s3_image_storage_enabled", lambda: True)
    monkeypatch.setattr(
        retention,
        "list_object_keys",
        lambda _prefix: {"data/images/sample.jpg", "data/images/thumbs/sample.webp"},
    )

    stats = retention.prune_verified_local_images(root, apply=True)

    assert stats["local_files"] == 2
    assert not original.exists() and not thumb.exists()
    assert partial.exists()
```

- [ ] **Step 3: Run the tests and verify RED**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_s3_local_retention.py -q
```

Expected: collection fails because `services.s3_local_retention` does not exist.

- [ ] **Step 4: Implement the minimal service**

Implement the module with local snapshot before remote listing and no unlink before the listing completes:

```python
from pathlib import Path

from services.s3_image_storage import (
    iter_image_files,
    list_object_keys,
    s3_image_storage_enabled,
)


def _object_key(path: Path, root: Path) -> str:
    return f"data/images/{path.relative_to(root).as_posix()}"


def prune_verified_local_images(root: Path, *, apply: bool = False) -> dict:
    image_root = Path(root).resolve()
    if not image_root.is_dir():
        raise ValueError(f"image root is not a directory: {image_root}")
    if not s3_image_storage_enabled():
        raise RuntimeError("S3 image storage is not enabled")

    files = list(iter_image_files(image_root))
    local = [(path, path.stat().st_size, _object_key(path, image_root)) for path in files]
    remote_keys = list_object_keys("data/images/")
    stats = {
        "local_files": len(local),
        "local_bytes": sum(size for _path, size, _key in local),
        "eligible_files": 0,
        "eligible_bytes": 0,
        "missing_remote_files": 0,
        "missing_remote_bytes": 0,
        "deleted_files": 0,
        "deleted_bytes": 0,
        "delete_failures": 0,
    }
    for path, size, key in local:
        if key not in remote_keys:
            stats["missing_remote_files"] += 1
            stats["missing_remote_bytes"] += size
            continue
        stats["eligible_files"] += 1
        stats["eligible_bytes"] += size
        if not apply:
            continue
        try:
            path.unlink()
        except OSError:
            stats["delete_failures"] += 1
        else:
            stats["deleted_files"] += 1
            stats["deleted_bytes"] += size
    return stats
```

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_s3_local_retention.py -q
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m py_compile services\s3_local_retention.py
```

Expected: all retention tests pass and compilation exits 0.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- services/s3_local_retention.py tests/test_s3_local_retention.py
git commit -m "feat: prune verified local S3 image copies"
```

---

### Task 2: Dry-run/apply operator CLI

**Files:**
- Modify: `scripts/s3_sync_images.py`
- Create: `tests/test_s3_sync_images.py`

**Interfaces:**
- Consumes: `prune_verified_local_images(root, apply=...)` from Task 1.
- Produces: `--prune-local [--apply]`; apply is accepted only for `PROJECT_ROOT / "data" / "images"` after resolution.

- [ ] **Step 1: Write failing parser and safety tests**

```python
from pathlib import Path

from scripts import s3_sync_images


def test_prune_cli_defaults_to_dry_run():
    args = s3_sync_images.parse_args(["--prune-local"])
    assert args.prune_local is True
    assert args.apply is False


def test_prune_apply_rejects_noncanonical_root(tmp_path, monkeypatch):
    other = tmp_path / "data" / "images"
    other.mkdir(parents=True)
    called = []
    monkeypatch.setattr(
        s3_sync_images,
        "prune_verified_local_images",
        lambda *_args, **_kwargs: called.append(True),
    )

    status = s3_sync_images.main(["--prune-local", "--apply", "--root", str(other)])

    assert status == 2
    assert called == []


def test_prune_cli_forwards_apply_and_returns_failure_status(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        s3_sync_images,
        "prune_verified_local_images",
        lambda root, *, apply: captured.update(root=root, apply=apply) or {
            "local_files": 1,
            "local_bytes": 10,
            "eligible_files": 1,
            "eligible_bytes": 10,
            "missing_remote_files": 0,
            "missing_remote_bytes": 0,
            "deleted_files": 0,
            "deleted_bytes": 0,
            "delete_failures": 1,
        },
    )

    status = s3_sync_images.main(["--prune-local", "--apply"])

    assert status == 1
    assert captured == {
        "root": (s3_sync_images.PROJECT_ROOT / "data" / "images").resolve(),
        "apply": True,
    }
```

- [ ] **Step 2: Run the focused tests and verify RED**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_s3_sync_images.py -q
```

Expected: parser rejects `--prune-local` because the mode is not implemented.

- [ ] **Step 3: Implement the CLI mode**

Add `--prune-local` to the required mutually exclusive mode group, add `--apply`, reject `--apply` with other modes, validate the canonical root before destructive use, invoke the Task 1 service, and log exactly one bounded `prune_complete` summary. Return 1 only when an attempted deletion failed; preserve existing return behavior for dry-run/upload/verify.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_s3_sync_images.py tests\test_s3_local_retention.py -q
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m py_compile scripts\s3_sync_images.py
```

- [ ] **Step 5: Commit Task 2**

```powershell
git add -- scripts/s3_sync_images.py tests/test_s3_sync_images.py
git commit -m "feat: add fail-closed local image prune CLI"
```

---

### Task 3: Run pruning only after broker-image cleanup

**Files:**
- Modify: `cli/crawlers.py:30-37`
- Modify: `tests/test_daily_crawl_limits.py`

**Interfaces:**
- Consumes: Task 1 `prune_verified_local_images()` and `services.image_assets.DATA_IMAGES_DIR`.
- Produces: `_prune_local_s3_images_after_cleanup() -> dict | None`, called after `clean_broker_images()` by `_clean_broker_images_after_download()`.

- [ ] **Step 1: Write an ordering regression test**

Add a test that patches the functions imported by the helper and records events:

```python
def test_broker_cleanup_finishes_before_s3_local_prune(monkeypatch):
    from cli import crawlers

    events = []
    monkeypatch.setattr(
        "cleansing.image_cleanup.clean_broker_images",
        lambda **_kwargs: events.append("broker_cleanup") or {
            "scanned": 1,
            "deleted": 0,
            "reasons": {},
        },
    )
    monkeypatch.setattr(
        "services.s3_image_storage.s3_image_storage_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "services.s3_local_retention.prune_verified_local_images",
        lambda _root, *, apply: events.append(("prune", apply)) or {
            "deleted_files": 2,
            "deleted_bytes": 20,
            "missing_remote_files": 0,
            "delete_failures": 0,
        },
    )

    crawlers._clean_broker_images_after_download(source="facebook", limit=10)

    assert events == ["broker_cleanup", ("prune", True)]


def test_s3_local_prune_failure_does_not_replace_broker_result(monkeypatch, capsys):
    from cli import crawlers

    broker_stats = {"scanned": 2, "deleted": 1, "reasons": {"metadata": 1}}
    monkeypatch.setattr(
        "cleansing.image_cleanup.clean_broker_images",
        lambda **_kwargs: broker_stats,
    )
    monkeypatch.setattr(
        "services.s3_image_storage.s3_image_storage_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "services.s3_local_retention.prune_verified_local_images",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("S3 list failed")),
    )

    result = crawlers._clean_broker_images_after_download(source="facebook", limit=10)

    assert result is broker_stats
    assert "[s3-local-prune] failed: S3 list failed" in capsys.readouterr().out
```

- [ ] **Step 2: Run the new tests and verify RED**

Run the two exact new node IDs with pytest. Expected: the ordering test records
only `broker_cleanup`, and the failure-isolation test has no prune failure
message because the hook does not exist.

- [ ] **Step 3: Implement the isolated post-cleanup hook**

Add `_prune_local_s3_images_after_cleanup()` that returns immediately in local mode, calls the Task 1 service with `apply=True` in S3 mode, prints a bounded summary, and catches/report exceptions without raising. Call it only after `clean_broker_images()` and before `_clean_broker_images_after_download()` returns its existing broker stats.

- [ ] **Step 4: Run crawl and image regression tests**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m pytest tests\test_daily_crawl_limits.py tests\test_image_cleanup.py tests\test_download_images.py tests\test_s3_local_retention.py tests\test_s3_sync_images.py tests\test_s3_image_storage.py tests\test_image_assets.py -q
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -X utf8 -m py_compile cli\crawlers.py services\s3_local_retention.py scripts\s3_sync_images.py
```

- [ ] **Step 5: Commit Task 3**

```powershell
git add -- cli/crawlers.py tests/test_daily_crawl_limits.py
git commit -m "feat: prune local images after broker cleanup"
```

---

### Task 4: Operations contract and full local verification

**Files:**
- Modify: `docs/operations.md`

**Interfaces:**
- Consumes: Task 2 CLI and Task 3 automatic hook.
- Produces: production dry-run/apply/verification/rollback runbook.

- [ ] **Step 1: Document zero-local S3 operations**

Add a concise section near the crawl/image operations documenting:

```powershell
& $py -X utf8 scripts/s3_sync_images.py --verify
& $py -X utf8 scripts/s3_sync_images.py --prune-local
& $py -X utf8 scripts/s3_sync_images.py --prune-local --apply
```

State the mandatory order `dry-run -> verify missing=0 -> apply -> API/S3/browser smoke`, exact root protection, directory preservation, automatic post-broker cleanup, fail-closed missing behavior, and rollback by disabling the automatic call rather than restoring local copies.

- [ ] **Step 2: Run full scoped verification**

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m py_compile cli\crawlers.py services\s3_image_storage.py services\s3_local_retention.py scripts\s3_sync_images.py
& $py -X utf8 -m pytest tests\test_daily_crawl_limits.py tests\test_image_cleanup.py tests\test_download_images.py tests\test_s3_local_retention.py tests\test_s3_sync_images.py tests\test_s3_image_storage.py tests\test_image_assets.py -q
git diff --check
git status --short
```

Expected: compilation exit 0, all focused tests pass, diff check clean, and only `.playwright-cli/` remains unrelated/untracked.

- [ ] **Step 3: Commit Task 4**

```powershell
git add -- docs/operations.md
git commit -m "docs: add zero-local S3 image runbook"
```

---

### Task 5: Push, deploy without touching dirty social work, and prune production

**Files:**
- No new source files.
- Production runtime target: `/opt/radar-bds/current/data/images` only.

**Interfaces:**
- Consumes: commits from Tasks 1-4 and existing Vietnix S3 credentials.
- Produces: pushed SHA, active production service on the same SHA, zero verified local image copies, lower root-disk usage, and public browser/API proof.

- [ ] **Step 1: Verify and push main**

```powershell
git status --short
git log -5 --oneline
git push origin main
git rev-parse HEAD
git rev-parse origin/main
```

Require matching local/remote SHAs. Stage or push no unrelated file.

- [ ] **Step 2: Inspect production dirty paths before deploy**

Use read-only SSH to record `git status --short`, current SHA, service state, `df -h /`, image count/bytes, and diffs only for `scripts/browser_use_page_post.py` and `scripts/radar_social_auto_post.py`. Do not stash, reset, overwrite, archive, or commit those paths.

- [ ] **Step 3: Deploy the pushed SHA while preserving unrelated dirty files**

The standard deploy script intentionally refuses any unexpected production dirt. If the two known social scripts remain the only dirty paths and do not overlap this release, use a targeted fast-forward deployment: `git fetch origin main`, `git merge --ff-only origin/main`, install no new dependency, compile the changed Python files, restart `radar-bds.service`, and run local origin HTTP smokes. Stop rather than mutate the dirty paths if fast-forward reports overlap or any new dirt appears.

- [ ] **Step 4: Run production dry-run and reconciliation**

Under the production S3 environment run:

```bash
/opt/radar-bds/.venv/bin/python -X utf8 scripts/s3_sync_images.py --prune-local
/opt/radar-bds/.venv/bin/python -X utf8 scripts/s3_sync_images.py --verify
```

Record dry-run eligible files/bytes. Require `missing=0` before apply.

- [ ] **Step 5: Apply exact-root pruning**

Run only after Step 4 passes:

```bash
/opt/radar-bds/.venv/bin/python -X utf8 scripts/s3_sync_images.py --prune-local --apply
```

Then record file count, directory bytes, `df -h /`, and confirm both `data/images` and `data/images/thumbs` directories still exist. Report what was removed and that recovery is from S3 object keys.

- [ ] **Step 6: Verify production quality and speed contract**

Require all of the following fresh evidence:

- `systemctl is-active radar-bds nginx postgresql redis-server` reports active;
- VPS-local `/api/dashboard`, `/api/signals`, and `/api/listings` return 200;
- public `/api/signals` and `/api/listings` sampled image URLs are all Vietnix S3;
- sampled thumbnail and original HEAD return 200, `image/webp`, and immutable 30-day cache metadata;
- desktop and mobile homepage render image cards without broken images or console/application errors;
- no request-time S3 listing appears in application logs;
- production SHA equals pushed `origin/main` SHA;
- the two unrelated dirty social scripts remain present and unchanged from the pre-deploy diff snapshot.

- [ ] **Step 7: Record the production result**

Update `docs/operations.md` only if measured counts/bytes or a durable operational caveat must be preserved, commit/push that evidence separately, and repeat the SHA/service/public checks. Do not claim completion from local tests alone.
