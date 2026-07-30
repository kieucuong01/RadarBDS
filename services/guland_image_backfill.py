"""Dry-run-first repair for Guland listing images."""
from __future__ import annotations

import json
import logging
import tempfile
import time
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from crawler.base_crawler import _normalize_playwright_browser_path_env
from crawler.guland_pw import GulandCrawler
from db.connection import get_conn
from db.raw_listings import update_raw_listing_payload
from services.image_assets import ensure_thumbnail
from services.s3_image_storage import (
    list_object_keys,
    normalize_object_key,
    public_url_for_key,
    s3_image_storage_enabled,
    upload_file,
)


logger = logging.getLogger(__name__)

IMAGE_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


@dataclass(frozen=True)
class GulandImageRow:
    image_id: int
    listing_id: int
    img_url: str
    img_order: int
    local_path: str


@dataclass(frozen=True)
class GulandRawImageTarget:
    listing_id: int
    raw_id: int
    url: str
    raw_json: Mapping[str, object]
    existing_image_rows: int


@dataclass(frozen=True)
class ThumbnailRepair:
    image_id: int
    listing_id: int
    image_key: str
    thumb_key: str


def _row_dict(row) -> dict:
    if hasattr(row, "items"):
        return dict(row.items())
    return dict(row)


def _parse_raw_json(value: object) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _valid_remote_image_url(value: object) -> str:
    url = str(value or "").strip()
    if not url.startswith(("http://", "https://")):
        return ""
    lower = url.lower()
    bad = ("avatar", "author", "broker", "contact", "logo", "member", "profile", "seller", "placeholder", "no-image")
    if any(token in lower for token in bad):
        return ""
    return url


def _image_urls_from_raw(raw: Mapping[str, object]) -> list[str]:
    urls: list[str] = []
    for key in ("imgs", "img_urls", "image_urls"):
        value = raw.get(key)
        if isinstance(value, list):
            urls.extend(str(item or "") for item in value)
    images = raw.get("images")
    if isinstance(images, list):
        for item in images:
            if isinstance(item, Mapping):
                urls.append(str(item.get("url") or item.get("src") or ""))
            else:
                urls.append(str(item or ""))
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        clean = _valid_remote_image_url(url)
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def _merge_raw_image_urls(raw: Mapping[str, object], urls: Sequence[str]) -> tuple[dict, bool]:
    existing = _image_urls_from_raw(raw)
    seen = set(existing)
    merged = list(existing)
    for url in urls:
        clean = _valid_remote_image_url(url)
        if clean and clean not in seen:
            seen.add(clean)
            merged.append(clean)
    if merged == existing:
        return dict(raw), False
    out = dict(raw)
    out["imgs"] = merged
    return out, True


def _is_downloaded_image_key(local_path: str) -> bool:
    key = normalize_object_key(local_path)
    if not key or key.upper().endswith("NOT_FOUND"):
        return False
    if not key.startswith("data/images/"):
        return False
    if key.startswith("data/images/thumbs/"):
        return False
    return Path(key).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}


def _thumb_key_for_image_key(image_key: str) -> str:
    key = normalize_object_key(image_key)
    return f"data/images/thumbs/{Path(key).stem}.webp"


def _build_thumbnail_repairs(
    rows: Sequence[GulandImageRow],
    s3_keys: set[str],
) -> tuple[list[ThumbnailRepair], list[int]]:
    repairs: list[ThumbnailRepair] = []
    missing_original: list[int] = []
    for row in rows:
        image_key = normalize_object_key(row.local_path)
        if not _is_downloaded_image_key(image_key):
            continue
        thumb_key = _thumb_key_for_image_key(image_key)
        if image_key not in s3_keys:
            missing_original.append(row.image_id)
            continue
        if thumb_key not in s3_keys:
            repairs.append(ThumbnailRepair(
                image_id=row.image_id,
                listing_id=row.listing_id,
                image_key=image_key,
                thumb_key=thumb_key,
            ))
    return repairs, missing_original


def _primary_image_rows(rows: Sequence[GulandImageRow]) -> list[GulandImageRow]:
    primary_by_listing_id: dict[int, GulandImageRow] = {}
    for row in sorted(rows, key=lambda item: (item.listing_id, item.img_order, item.image_id)):
        primary_by_listing_id.setdefault(row.listing_id, row)
    return list(primary_by_listing_id.values())


def _active_guland_scope_sql(include_inactive: bool) -> str:
    if include_inactive:
        return ""
    return """
              AND COALESCE(l.probably_sold, 0) = 0
              AND COALESCE(l.is_blacklisted, 0) = 0
              AND COALESCE(l.review_hidden, 0) = 0
              AND COALESCE(l.possibly_duplicate, 0) = 0
    """


def _load_guland_images(
    *,
    include_inactive: bool = False,
) -> tuple[list[GulandImageRow], list[GulandRawImageTarget]]:
    scope_sql = _active_guland_scope_sql(include_inactive)
    with get_conn() as conn:
        image_rows = conn.execute(
            f"""
            SELECT li.id AS image_id,
                   li.listing_id,
                   li.img_url,
                   li.img_order,
                   li.local_path
            FROM listing_images li
            JOIN listings l ON l.id = li.listing_id
            WHERE l.source = 'guland'
            {scope_sql}
            ORDER BY li.listing_id, li.img_order, li.id
            """
        ).fetchall()
        raw_rows = conn.execute(
            f"""
            SELECT l.id AS listing_id,
                   l.raw_id,
                   l.url,
                   r.raw_json,
                   COUNT(li.id) AS existing_image_rows
            FROM listings l
            JOIN raw_listings r ON r.id = l.raw_id
            LEFT JOIN listing_images li ON li.listing_id = l.id
            WHERE l.source = 'guland'
            {scope_sql}
            GROUP BY l.id, l.raw_id, l.url, r.raw_json
            ORDER BY l.id
            """
        ).fetchall()

    images = [
        GulandImageRow(
            image_id=int(row["image_id"]),
            listing_id=int(row["listing_id"]),
            img_url=str(row["img_url"] or ""),
            img_order=int(row["img_order"] or 0),
            local_path=str(row["local_path"] or ""),
        )
        for row in image_rows
    ]
    targets = []
    for source_row in raw_rows:
        row = _row_dict(source_row)
        raw = _parse_raw_json(row.get("raw_json"))
        targets.append(GulandRawImageTarget(
            listing_id=int(row["listing_id"]),
            raw_id=int(row["raw_id"]),
            url=str(row.get("url") or ""),
            raw_json=raw,
            existing_image_rows=int(row.get("existing_image_rows") or 0),
        ))
    return images, targets


def _fetch_live_image_map(targets: Sequence[GulandRawImageTarget]) -> dict[int, list[str]]:
    if not targets:
        return {}
    _normalize_playwright_browser_path_env()
    from playwright.sync_api import sync_playwright

    crawler = GulandCrawler()
    out: dict[int, list[str]] = {}
    urls = [target.url for target in targets]
    by_url = {target.url: target for target in targets}
    with sync_playwright() as playwright:
        browser, context = crawler._launch(playwright, headless=True)
        try:
            page = context.new_page()
            page.set_default_timeout(30_000)
            page.goto("https://guland.vn", wait_until="domcontentloaded", timeout=30_000)
            for start in range(0, len(urls), 25):
                details = crawler._fetch_details_batch(page, urls[start:start + 25])
                for url, detail in details.items():
                    target = by_url.get(url)
                    if not target:
                        continue
                    urls_found = _image_urls_from_raw({
                        "imgs": detail.get("detail_imgs") or [],
                    })
                    if urls_found:
                        out[target.listing_id] = urls_found
                time.sleep(0.3)
        finally:
            browser.close()
    return out


def _insert_listing_images(listing_id: int, urls: Sequence[str]) -> int:
    inserted = 0
    with get_conn() as conn:
        for order, url in enumerate(urls):
            clean = _valid_remote_image_url(url)
            if not clean:
                continue
            before = conn.execute(
                "SELECT COUNT(*) AS n FROM listing_images WHERE listing_id = ? AND img_url = ?",
                (listing_id, clean),
            ).fetchone()["n"]
            conn.execute(
                """
                INSERT OR IGNORE INTO listing_images (listing_id, img_url, img_order, img_type)
                VALUES (?, ?, ?, ?)
                """,
                (listing_id, clean, order, "cover" if order == 0 else "unknown"),
            )
            after = conn.execute(
                "SELECT COUNT(*) AS n FROM listing_images WHERE listing_id = ? AND img_url = ?",
                (listing_id, clean),
            ).fetchone()["n"]
            inserted += max(0, int(after) - int(before))
    return inserted


def _apply_raw_image_recovery(
    targets: Sequence[GulandRawImageTarget],
    live_images_by_listing_id: Mapping[int, Sequence[str]],
) -> tuple[int, int, list[int]]:
    raw_updated = 0
    image_rows_inserted = 0
    changed_listing_ids: list[int] = []
    by_id = {target.listing_id: target for target in targets}
    with get_conn() as conn:
        for listing_id, urls in live_images_by_listing_id.items():
            target = by_id.get(int(listing_id))
            if not target:
                continue
            merged, changed = _merge_raw_image_urls(target.raw_json, urls)
            if changed:
                update_raw_listing_payload(
                    target.raw_id,
                    merged,
                    change_kind="guland_image_recovery",
                    conn=conn,
                )
                raw_updated += 1
            if changed or target.existing_image_rows == 0:
                changed_listing_ids.append(target.listing_id)
    for listing_id in changed_listing_ids:
        image_rows_inserted += _insert_listing_images(
            listing_id,
            live_images_by_listing_id.get(listing_id, []),
        )
    return raw_updated, image_rows_inserted, sorted(set(changed_listing_ids))


def _download_public_original_to_temp(image_key: str, temp_dir: Path) -> Path:
    url = public_url_for_key(image_key)
    if not url:
        raise RuntimeError(f"missing public URL for {image_key}")
    suffix = Path(urlparse(url).path).suffix or Path(image_key).suffix or ".jpg"
    target = temp_dir / f"{Path(image_key).stem}{suffix}"
    req = urllib.request.Request(url, headers=IMAGE_FETCH_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as response:
        target.write_bytes(response.read())
    return target


def _apply_thumbnail_repairs(repairs: Sequence[ThumbnailRepair]) -> tuple[int, int]:
    uploaded = 0
    errors = 0
    with tempfile.TemporaryDirectory(prefix="guland-image-backfill-") as tmp:
        temp_dir = Path(tmp)
        for repair in repairs:
            try:
                original = _download_public_original_to_temp(repair.image_key, temp_dir)
                thumb = ensure_thumbnail(original, force=True)
                if not thumb:
                    raise RuntimeError(f"thumbnail was not created for {repair.image_key}")
                upload_file(thumb, repair.thumb_key)
                uploaded += 1
            except Exception as exc:
                errors += 1
                logger.warning("Guland thumbnail repair failed image_id=%s: %s", repair.image_id, exc)
    return uploaded, errors


def run_guland_image_backfill(
    *,
    apply: bool = False,
    recover_live_missing: bool = True,
    download_recovered: bool = True,
    include_inactive: bool = False,
) -> dict[str, object]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    image_rows, raw_targets = _load_guland_images(include_inactive=include_inactive)
    s3_keys = list_object_keys("data/images/") if s3_image_storage_enabled() else set()
    primary_rows = _primary_image_rows(image_rows)
    repairs, missing_original = _build_thumbnail_repairs(primary_rows, s3_keys)

    raw_missing_targets = [
        target
        for target in raw_targets
        if not _image_urls_from_raw(target.raw_json) or target.existing_image_rows == 0
    ]
    live_images: dict[int, list[str]] = {
        target.listing_id: _image_urls_from_raw(target.raw_json)
        for target in raw_missing_targets
        if target.existing_image_rows == 0 and _image_urls_from_raw(target.raw_json)
    }
    if recover_live_missing and raw_missing_targets:
        live_images.update(_fetch_live_image_map(raw_missing_targets))

    stats: dict[str, object] = {
        "run_id": run_id if apply else "",
        "apply": bool(apply),
        "include_inactive": bool(include_inactive),
        "eligible": len(raw_targets),
        "listing_image_rows": len(image_rows),
        "primary_image_rows": len(primary_rows),
        "downloaded_rows": sum(1 for row in image_rows if _is_downloaded_image_key(row.local_path)),
        "not_found_rows": sum(1 for row in image_rows if str(row.local_path or "").upper().endswith("NOT_FOUND")),
        "missing_original_rows": len(missing_original),
        "missing_thumbnail_rows": len(repairs),
        "raw_missing_image_targets": len(raw_missing_targets),
        "live_recoverable_targets": len(live_images),
        "thumbnail_uploaded": 0,
        "raw_updated": 0,
        "listing_images_inserted": 0,
        "recovered_images_downloaded": 0,
        "errors": 0,
    }
    if not apply:
        return stats

    uploaded, thumb_errors = _apply_thumbnail_repairs(repairs)
    stats["thumbnail_uploaded"] = uploaded
    stats["errors"] = int(stats["errors"]) + thumb_errors

    changed_listing_ids: list[int] = []
    if live_images:
        raw_updated, inserted, changed_listing_ids = _apply_raw_image_recovery(
            raw_missing_targets,
            live_images,
        )
        stats["raw_updated"] = raw_updated
        stats["listing_images_inserted"] = inserted

    if download_recovered and changed_listing_ids:
        from cleansing.download_images import download_images

        try:
            stats["recovered_images_downloaded"] = download_images(
                limit=max(500, min(3000, len(changed_listing_ids) * 12)),
                listing_ids=changed_listing_ids,
            )
        except RuntimeError as exc:
            if "download-images" not in str(exc):
                raise
            logger.warning("Recovered Guland image download skipped: %s", exc)
            stats["errors"] = int(stats["errors"]) + 1
    return stats
