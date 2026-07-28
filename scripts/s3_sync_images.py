"""Sync Radar BDS listing images from local disk to S3-compatible storage."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.s3_image_storage import iter_image_files, list_object_keys, public_url_for_key, upload_file


logger = logging.getLogger("s3_sync_images")


def object_key_for_path(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return f"data/images/{rel}"


def collect_files(root: Path, limit: int | None = None) -> list[Path]:
    files = sorted(iter_image_files(root), key=lambda p: p.as_posix())
    if limit is not None:
        return files[: max(0, limit)]
    return files


def summarize(files: list[Path], root: Path) -> dict:
    total_bytes = 0
    thumbs = 0
    thumb_bytes = 0
    for path in files:
        size = path.stat().st_size
        total_bytes += size
        if "thumbs" in path.relative_to(root).parts:
            thumbs += 1
            thumb_bytes += size
    return {
        "files": len(files),
        "bytes": total_bytes,
        "thumb_files": thumbs,
        "thumb_bytes": thumb_bytes,
        "original_files": len(files) - thumbs,
        "original_bytes": total_bytes - thumb_bytes,
    }


def dry_run(root: Path, limit: int | None) -> int:
    files = collect_files(root, limit)
    stats = summarize(files, root)
    logger.info(
        "dry_run root=%s files=%s bytes=%s originals=%s thumbs=%s",
        root,
        stats["files"],
        stats["bytes"],
        stats["original_files"],
        stats["thumb_files"],
    )
    if files:
        first_key = object_key_for_path(files[0], root)
        logger.info("first_key=%s public_url=%s", first_key, public_url_for_key(first_key))
    return 0


def upload(root: Path, limit: int | None) -> int:
    files = collect_files(root, limit)
    uploaded = 0
    uploaded_bytes = 0
    for path in files:
        key = object_key_for_path(path, root)
        upload_file(path, key)
        uploaded += 1
        uploaded_bytes += path.stat().st_size
        if uploaded % 500 == 0:
            logger.info("uploaded files=%s bytes=%s last_key=%s", uploaded, uploaded_bytes, key)
    logger.info("upload_complete files=%s bytes=%s", uploaded, uploaded_bytes)
    return 0


def verify(root: Path, limit: int | None) -> int:
    files = collect_files(root, limit)
    local_keys = {object_key_for_path(path, root) for path in files}
    remote_keys = list_object_keys("data/images/")
    missing = sorted(local_keys - remote_keys)
    logger.info(
        "verify_complete local=%s remote_under_prefix=%s missing=%s",
        len(local_keys),
        len(remote_keys),
        len(missing),
    )
    for key in missing[:20]:
        logger.warning("missing_key=%s", key)
    return 1 if missing else 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Count local image files without uploading.")
    mode.add_argument("--upload", action="store_true", help="Upload local image files to S3.")
    mode.add_argument("--verify", action="store_true", help="Verify local files exist under the S3 prefix.")
    parser.add_argument(
        "--root",
        default=str(PROJECT_ROOT / "data" / "images"),
        help="Local data/images directory. Default: project data/images.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional max files for canary runs.")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s [%(levelname)s] %(message)s")
    root = Path(args.root).resolve()
    if not root.is_dir():
        logger.error("image root does not exist: %s", root)
        return 2
    if args.dry_run:
        return dry_run(root, args.limit)
    if args.upload:
        return upload(root, args.limit)
    return verify(root, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
