"""Fail-closed cleanup of local image copies already present in S3."""
from __future__ import annotations

from pathlib import Path

from services.s3_image_storage import (
    iter_image_files,
    list_object_keys,
    s3_image_storage_enabled,
)


def _object_key(path: Path, root: Path) -> str:
    return f"data/images/{path.relative_to(root).as_posix()}"


def prune_verified_local_images(root: Path, *, apply: bool = False) -> dict[str, int]:
    """Delete only local images whose exact object keys exist in S3.

    The complete local snapshot and remote key listing both finish before any
    deletion begins. If S3 is disabled or listing fails, no local file is
    removed.
    """
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
