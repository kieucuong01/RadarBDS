"""Download listing images to local storage for dashboard rendering."""
from __future__ import annotations

import hashlib
import io
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from db.connection import advisory_lock, get_conn
from db.listings import canonical_image_asset_key
from services.image_assets import ensure_thumbnail
from services.s3_image_storage import s3_image_storage_enabled, upload_file

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data" / "images"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_ATTEMPTS = 3
TRANSIENT_HTTP_STATUS = {408, 429, 500, 502, 503, 504}
TERMINAL_HTTP_STATUS = {403, 404, 410}
FORMAT_EXTENSIONS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
}


class InvalidImageResponse(ValueError):
    pass


class TerminalImageResponse(RuntimeError):
    def __init__(self, status: int):
        self.status = int(status)
        super().__init__(f"terminal image response: {status}")


def image_object_path(
    *,
    image_id: int,
    listing_id: int,
    img_url: str,
    format_name: str,
    root: Path | None = None,
) -> tuple[Path, str]:
    """Return a collision-free local path and stable object key."""
    extension = FORMAT_EXTENSIONS.get(str(format_name or "").upper())
    if not extension:
        raise InvalidImageResponse(f"unsupported image format: {format_name}")
    asset_key = canonical_image_asset_key(img_url)
    fingerprint = hashlib.sha256(asset_key.encode("utf-8")).hexdigest()[:12]
    filename = f"{int(listing_id)}_{int(image_id)}_{fingerprint}{extension}"
    local_path = (root or DATA_DIR) / filename
    return local_path, f"data/images/{filename}"


def _validated_image_format(data: bytes, content_type: str) -> str:
    if not data:
        raise InvalidImageResponse("empty image response")
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidImageResponse("image response exceeds size limit")
    normalized_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type in {"text/html", "application/xhtml+xml", "text/plain"}:
        raise InvalidImageResponse(f"non-image content type: {normalized_type}")
    try:
        with Image.open(io.BytesIO(data)) as image:
            format_name = str(image.format or "").upper()
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImageResponse("response body is not a decodable image") from exc
    if format_name not in FORMAT_EXTENSIONS:
        raise InvalidImageResponse(f"unsupported image format: {format_name}")
    return format_name


def _fetch_validated_image(img_url: str) -> tuple[bytes, str]:
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(img_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as response:
                content_length = str(
                    getattr(response, "headers", {}).get("Content-Length", "") or ""
                ).strip()
                if content_length:
                    try:
                        declared_size = int(content_length)
                    except ValueError:
                        declared_size = 0
                    if declared_size > MAX_IMAGE_BYTES:
                        raise InvalidImageResponse(
                            "declared image size exceeds limit"
                        )
                data = response.read(MAX_IMAGE_BYTES + 1)
                content_type = str(
                    getattr(response, "headers", {}).get("Content-Type", "") or ""
                )
                return data, _validated_image_format(data, content_type)
        except urllib.error.HTTPError as exc:
            if exc.code in TERMINAL_HTTP_STATUS:
                raise TerminalImageResponse(exc.code) from exc
            last_error = exc
            if exc.code not in TRANSIENT_HTTP_STATUS or attempt >= MAX_ATTEMPTS:
                raise
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
            last_error = exc
            if attempt >= MAX_ATTEMPTS:
                raise
        if attempt < MAX_ATTEMPTS:
            time.sleep(0.25 * attempt)
    if last_error:
        raise last_error
    raise InvalidImageResponse("image download failed without response")


def _remove_file(path: Path | None) -> None:
    if not path:
        return
    try:
        if path.exists():
            path.unlink()
    except OSError:
        logger.warning("Could not clean image artifact: %s", path)


def _upload_downloaded_image(local_file_path: Path, relative_path: str, thumb_path: Path | None) -> None:
    if not thumb_path or not thumb_path.exists():
        raise InvalidImageResponse(f"thumbnail missing for {relative_path}")
    upload_file(local_file_path, relative_path)
    upload_file(thumb_path, f"data/images/thumbs/{thumb_path.name}")


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
        local_file_path: Path | None = None
        partial_path: Path | None = None
        thumb_path: Path | None = None
        try:
            img_id = row["id"]
            listing_id = row["listing_id"]
            img_url = row["img_url"]

            if not img_url or not img_url.startswith(("http://", "https://")):
                continue

            try:
                img_data, format_name = _fetch_validated_image(img_url)
                local_file_path, relative_path = image_object_path(
                    image_id=int(img_id),
                    listing_id=int(listing_id),
                    img_url=img_url,
                    format_name=format_name,
                )
                local_file_path.parent.mkdir(parents=True, exist_ok=True)
                partial_path = local_file_path.with_suffix(
                    f"{local_file_path.suffix}.part"
                )
                partial_path.write_bytes(img_data)
                os.replace(partial_path, local_file_path)
                partial_path = None
                try:
                    thumb_path = ensure_thumbnail(local_file_path)
                except Exception as e:
                    logger.warning("Could not create thumbnail %s: %s", local_file_path, e)

                if s3_image_storage_enabled():
                    try:
                        _upload_downloaded_image(local_file_path, relative_path, thumb_path)
                    except Exception as e:
                        logger.warning("S3 image upload failed for %s: %s", relative_path, e)
                        _remove_file(local_file_path)
                        _remove_file(thumb_path)
                        continue

                with get_conn() as conn:
                    conn.execute(
                        "UPDATE listing_images SET local_path = ? WHERE id = ?",
                        (relative_path, img_id),
                    )
                success_count += 1
                logger.info("Downloaded image: %s", relative_path)
            except TerminalImageResponse as e:
                logger.warning("Image download failed %s: %s", img_url, e.status)
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE listing_images SET local_path = ? WHERE id = ?",
                        ("NOT_FOUND", img_id),
                    )
            except Exception as e:
                logger.warning("Image download failed %s: %s", img_url, e)
        finally:
            _remove_file(partial_path)
            if progress_callback:
                progress_callback(idx, len(rows), success_count)

    logger.info("Downloaded successfully: %s/%s images.", success_count, len(rows))
    return success_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    download_images()
