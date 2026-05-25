"""
Generate lightweight WebP thumbnails for existing local listing images.

Usage:
    python scripts/generate_thumbnails.py --limit 200
    python scripts/generate_thumbnails.py --force
"""
import argparse
import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.image_assets import DATA_IMAGES_DIR, IMAGE_EXTS, THUMB_DIR, ensure_thumbnail
from services.image_assets import local_path_for_url
from db.connection import get_conn


logger = logging.getLogger(__name__)


def iter_source_images():
    if not DATA_IMAGES_DIR.exists():
        return
    for path in DATA_IMAGES_DIR.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_EXTS:
            continue
        yield path


def iter_signal_cover_images(limit):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT li.local_path
            FROM valuation_results v
            JOIN listings l ON l.id = v.listing_id
            JOIN listing_images li ON li.listing_id = l.id
            WHERE v.is_signal = 1
              AND li.img_order = 0
              AND li.local_path IS NOT NULL
              AND li.local_path != 'NOT_FOUND'
            ORDER BY COALESCE(l.posted_at, l.crawled_at) DESC, l.id DESC
            LIMIT ?
        """, (limit,)).fetchall()
    for row in rows:
        path = local_path_for_url(row["local_path"])
        if path and path.exists():
            yield path


def generate_thumbnails(limit=None, force=False, source_images=None):
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    created = 0
    skipped = 0
    failed = 0

    for image_path in (source_images or iter_source_images()):
        if limit is not None and created >= limit:
            break
        thumb_path = THUMB_DIR / f"{image_path.stem}.webp"
        if thumb_path.exists() and not force:
            skipped += 1
            continue
        try:
            if ensure_thumbnail(image_path, force=force):
                created += 1
        except Exception as exc:
            failed += 1
            logger.warning("Failed thumbnail for %s: %s", image_path, exc)

    return {"created": created, "skipped": skipped, "failed": failed}


def main():
    parser = argparse.ArgumentParser(description="Generate card thumbnails for local listing images.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of thumbnails to create.")
    parser.add_argument("--signals", type=int, default=None, help="Generate thumbnails for newest signal cover images.")
    parser.add_argument("--force", action="store_true", help="Regenerate existing thumbnails.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    source_images = iter_signal_cover_images(args.signals) if args.signals else None
    result = generate_thumbnails(limit=args.limit, force=args.force, source_images=source_images)
    logger.info("Thumbnail generation complete: %s", result)


if __name__ == "__main__":
    main()
