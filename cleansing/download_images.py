"""Download listing images to local storage for dashboard rendering."""
from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from db.connection import advisory_lock, get_conn
from services.image_assets import ensure_thumbnail

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data" / "images"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def download_images(
    limit: int = 1000,
    listing_id: int | None = None,
    listing_ids: list[int] | None = None,
    progress_callback=None,
):
    with advisory_lock("download-images"):
        return _download_images(
            limit=limit,
            listing_id=listing_id,
            listing_ids=listing_ids,
            progress_callback=progress_callback,
        )


def _candidate_query(listing_id: int | None = None, listing_ids: list[int] | None = None) -> tuple[str, list]:
    where = [
        """
        (
            li.local_path IS NULL
            OR (
                 l.source = 'facebook'
             AND li.local_path = 'NOT_FOUND'
             AND (li.img_url LIKE '%fbcdn.net%' OR li.img_url LIKE '%scontent%')
             AND datetime(COALESCE(li.crawled_at, '1970-01-01')) >= datetime('now', '-30 days')
            )
        )
        """
    ]
    params = []
    if listing_id is not None:
        where.append("li.listing_id = ?")
        params.append(listing_id)
    elif listing_ids:
        clean_ids = sorted({int(x) for x in listing_ids if x})
        if clean_ids:
            placeholders = ",".join(["?"] * len(clean_ids))
            where.append(f"li.listing_id IN ({placeholders})")
            params.extend(clean_ids)

    sql = f"""
        SELECT li.id, li.listing_id, li.img_url, li.img_order
          FROM listing_images li
          JOIN listings l ON l.id = li.listing_id
         WHERE {' AND '.join(where)}
         ORDER BY CASE WHEN li.local_path IS NULL THEN 0 ELSE 1 END,
                  li.img_order ASC, li.id DESC
         LIMIT ?
    """
    return sql, params


def _download_images(
    limit: int = 1000,
    listing_id: int | None = None,
    listing_ids: list[int] | None = None,
    progress_callback=None,
):
    """Download missing images, plus recent Facebook CDN images marked NOT_FOUND."""
    logger.info("Downloading listing images into: %s", DATA_DIR)
    if listing_id is None and listing_ids is not None and not listing_ids:
        logger.info("No listing ids supplied for targeted image download.")
        return 0

    sql, params = _candidate_query(listing_id=listing_id, listing_ids=listing_ids)
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        logger.info("No new images to download.")
        return 0

    success_count = 0
    if progress_callback:
        progress_callback(0, len(rows), success_count)
    for idx, row in enumerate(rows, start=1):
        try:
            img_id = row["id"]
            listing_id = row["listing_id"]
            img_url = row["img_url"]
            img_order = row["img_order"]

            if not img_url or not img_url.startswith("http"):
                continue

            ext = ".jpg"
            lower_url = img_url.lower()
            if ".png" in lower_url:
                ext = ".png"
            elif ".webp" in lower_url:
                ext = ".webp"

            filename = f"{listing_id}_{img_order}{ext}"
            local_file_path = DATA_DIR / filename
            relative_path = f"data/images/{filename}"

            try:
                req = urllib.request.Request(img_url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=10) as response:
                    img_data = response.read()
                    with open(local_file_path, "wb") as f:
                        f.write(img_data)
                try:
                    ensure_thumbnail(local_file_path)
                except Exception as e:
                    logger.warning("Could not create thumbnail %s: %s", local_file_path, e)

                with get_conn() as conn:
                    conn.execute(
                        "UPDATE listing_images SET local_path = ? WHERE id = ?",
                        (relative_path, img_id),
                    )
                success_count += 1
                logger.info("Downloaded image: %s", relative_path)

                time.sleep(0.5)
            except urllib.error.HTTPError as e:
                logger.warning("Image download failed %s: %s", img_url, e.code)
                if e.code in (404, 403, 410):
                    with get_conn() as conn:
                        conn.execute(
                            "UPDATE listing_images SET local_path = ? WHERE id = ?",
                            ("NOT_FOUND", img_id),
                        )
            except Exception as e:
                logger.warning("Image download failed %s: %s", img_url, e)
        finally:
            if progress_callback:
                progress_callback(idx, len(rows), success_count)

    logger.info("Downloaded successfully: %s/%s images.", success_count, len(rows))
    return success_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    download_images()
