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
