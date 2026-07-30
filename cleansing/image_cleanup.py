"""Remove broker/profile images from listing image galleries."""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from db.connection import DATA_DIR, advisory_lock, get_conn
from db.raw_listings import update_raw_listing_payload

logger = logging.getLogger(__name__)

BAD_ASSET_RE = re.compile(
    r"(avatar|author|broker|contact|logo|member|profile|seller|user|placeholder|no-image)",
    re.I,
)
LEGAL_RE = re.compile(r"(so[-_ ]?hong|sohong|gcn|giay[-_ ]?chung[-_ ]?nhan|s[oổ]\s*h[oồ]ng)", re.I)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_FACE_CLASSIFIER = None


def _images_dir() -> Path:
    return DATA_DIR / "images"


def _is_legal_image(img_type: str, img_url: str, local_path: str) -> bool:
    text = " ".join([img_type or "", img_url or "", local_path or ""])
    return (img_type or "").lower() == "so_hong" or bool(LEGAL_RE.search(text))


def _metadata_reason(img_url: str, local_path: str) -> Optional[str]:
    text = " ".join([img_url or "", local_path or ""])
    return "metadata" if BAD_ASSET_RE.search(text) else None


def _local_file(local_path: str) -> Optional[Path]:
    if not local_path or local_path == "NOT_FOUND":
        return None
    name = Path(str(local_path).replace("\\", "/")).name
    if not name or Path(name).suffix.lower() not in IMAGE_EXTS:
        return None
    return _images_dir() / name


def _thumb_file(image_path: Optional[Path]) -> Optional[Path]:
    if not image_path:
        return None
    return image_path.parent / "thumbs" / f"{image_path.stem}.webp"


def _detect_local_broker_face(local_path: str, strong: bool = True) -> Optional[str]:
    """Return a broker-image reason when a local image looks like avatar/selfie."""
    global _FACE_CLASSIFIER
    image_path = _local_file(local_path)
    if not image_path or not image_path.exists():
        return None
    thumb_path = _thumb_file(image_path)
    detection_path = thumb_path if thumb_path and thumb_path.exists() else image_path
    try:
        import cv2
    except Exception:
        return None

    try:
        img = cv2.imread(str(detection_path))
        if img is None:
            return None
        height, width = img.shape[:2]
        if width <= 0 or height <= 0:
            return None
        scale = 1.0
        max_dim = max(width, height)
        if max_dim > 640:
            scale = 640.0 / max_dim
            img = cv2.resize(img, (int(width * scale), int(height * scale)))
        if _FACE_CLASSIFIER is None:
            cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
            _FACE_CLASSIFIER = cv2.CascadeClassifier(str(cascade_path))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = _FACE_CLASSIFIER.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(32, 32))
    except Exception as e:
        logger.debug("Face detection skipped for %s: %s", detection_path, e)
        return None

    if len(faces) == 0:
        return None

    img_area = float(width * height)
    portrait = height >= width * 1.15
    for (x, y, w, h) in faces:
        orig_x = x / scale
        orig_y = y / scale
        orig_w = w / scale
        orig_h = h / scale
        area_ratio = (orig_w * orig_h) / img_area
        width_ratio = orig_w / float(width)
        upper_face = orig_y < height * 0.55
        if area_ratio >= 0.10 or width_ratio >= 0.34:
            return "face_large"
        if strong and portrait and upper_face and (area_ratio >= 0.035 or width_ratio >= 0.22):
            return "face_large"
        if strong and len(faces) >= 2 and area_ratio >= 0.04:
            return "face_large"
    return None


def _should_run_face_detection(local_path: str) -> bool:
    """Fast shape prefilter so full cleanup does not CV-scan every property photo."""
    image_path = _local_file(local_path)
    if not image_path or not image_path.exists():
        return False
    try:
        from PIL import Image

        with Image.open(image_path) as img:
            width, height = img.size
    except Exception:
        # If a caller mocks face detection in tests, keep the path reachable.
        return True
    if width <= 0 or height <= 0:
        return False
    portrait_or_square = height >= width * 0.85
    small_asset = max(width, height) <= 420
    return portrait_or_square or small_asset


def _remove_url_from_raw(conn, raw_id: Optional[int], img_url: str) -> bool:
    if not raw_id or not img_url:
        return False
    row = conn.execute("SELECT raw_json FROM raw_listings WHERE id=?", (raw_id,)).fetchone()
    if not row:
        return False
    try:
        payload = json.loads(row["raw_json"] or "{}")
    except Exception:
        return False

    changed = False
    for key in ("imgs", "img_urls"):
        values = payload.get(key)
        if isinstance(values, list) and img_url in values:
            payload[key] = [v for v in values if v != img_url]
            changed = True
    if changed:
        update_raw_listing_payload(
            int(raw_id),
            payload,
            change_kind="broker_image_cleanup",
            conn=conn,
        )
    return changed


def _unlink(path: Optional[Path]) -> bool:
    if not path or not path.exists() or not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError as e:
        logger.warning("Image cleanup unlink failed %s: %s", path, e)
        return False


def _candidate_reason(row, strong: bool) -> Optional[str]:
    img_url = row["img_url"] or ""
    local_path = row["local_path"] or ""
    img_type = row["img_type"] or ""

    reason = _metadata_reason(img_url, local_path)
    if reason:
        return reason

    if _is_legal_image(img_type, img_url, local_path):
        return None

    if int(row["img_order"] or 0) > 1:
        return None

    if not _should_run_face_detection(local_path):
        return None

    return _detect_local_broker_face(local_path, strong=strong)


def clean_broker_images(
    source: Optional[str] = None,
    apply: bool = False,
    limit: Optional[int] = None,
    strong: bool = True,
) -> dict:
    with advisory_lock("clean-broker-images"):
        return _clean_broker_images(source=source, apply=apply, limit=limit, strong=strong)


def _clean_broker_images(
    source: Optional[str] = None,
    apply: bool = False,
    limit: Optional[int] = None,
    strong: bool = True,
) -> dict:
    """Scan and optionally delete broker/profile images from listing_images."""
    where = []
    params = []
    if source:
        where.append("l.source = ?")
        params.append(source)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    limit_sql = " LIMIT ?" if limit else ""
    if limit:
        params.append(int(limit))

    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT li.id, li.listing_id, li.img_url, li.img_order, li.img_type, li.local_path,
                   l.source, l.raw_id
              FROM listing_images li
              JOIN listings l ON l.id = li.listing_id
              {where_sql}
             ORDER BY CASE
                    WHEN lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')) LIKE '%avatar%'
                      OR lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')) LIKE '%author%'
                      OR lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')) LIKE '%broker%'
                      OR lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')) LIKE '%contact%'
                      OR lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')) LIKE '%logo%'
                      OR lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')) LIKE '%member%'
                      OR lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')) LIKE '%profile%'
                      OR lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')) LIKE '%seller%'
                      OR lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')) LIKE '%placeholder%'
                      OR lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')) LIKE '%no-image%'
                    THEN 0 ELSE 1 END,
                    li.id DESC
             {limit_sql}
            """,
            params,
        ).fetchall()

        stats = {
            "scanned": len(rows),
            "candidates": 0,
            "deleted": 0,
            "files_deleted": 0,
            "thumbs_deleted": 0,
            "raw_updated": 0,
            "reasons": {},
            "apply": bool(apply),
        }
        reasons = Counter()

        for row in rows:
            reason = _candidate_reason(row, strong=strong)
            if not reason:
                continue
            stats["candidates"] += 1
            reasons[reason] += 1

            if not apply:
                continue

            image_path = _local_file(row["local_path"] or "")
            thumb_path = _thumb_file(image_path)
            conn.execute("DELETE FROM listing_images WHERE id=?", (row["id"],))
            if _unlink(image_path):
                stats["files_deleted"] += 1
            if _unlink(thumb_path):
                stats["thumbs_deleted"] += 1
            if _remove_url_from_raw(conn, row["raw_id"], row["img_url"]):
                stats["raw_updated"] += 1
            stats["deleted"] += 1

        stats["reasons"] = dict(reasons)
        return stats
