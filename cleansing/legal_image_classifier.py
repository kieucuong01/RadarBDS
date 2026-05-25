"""Classify land-title certificate images in listing galleries."""
from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from db.connection import DATA_DIR, advisory_lock, get_conn

logger = logging.getLogger(__name__)

LEGAL_URL_RE = re.compile(
    r"(so[-_ ]?hong|sohong|so[-_ ]?do|sodo|gcn|qsd|qsdđ|quyen[-_ ]?su[-_ ]?dung|"
    r"giay[-_ ]?chung[-_ ]?nhan|giấy[-_ ]?chứng[-_ ]?nhận)",
    re.I,
)
BAD_ASSET_RE = re.compile(
    r"(avatar|author|broker|contact|logo|member|profile|seller|user|placeholder|no-image)",
    re.I,
)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _images_dir() -> Path:
    return DATA_DIR / "images"


def _local_file(local_path: str) -> Optional[Path]:
    if not local_path or local_path == "NOT_FOUND":
        return None
    name = Path(str(local_path).replace("\\", "/")).name
    if not name or Path(name).suffix.lower() not in IMAGE_EXTS:
        return None
    return _images_dir() / name


def _metadata_reason(img_url: str, local_path: str) -> Optional[str]:
    text = " ".join([img_url or "", local_path or ""])
    if BAD_ASSET_RE.search(text):
        return None
    return "metadata" if LEGAL_URL_RE.search(text) else None


def _detect_document_image(local_path: str) -> Optional[str]:
    image_path = _local_file(local_path)
    if not image_path or not image_path.exists():
        return None
    try:
        import cv2
        import numpy as np
    except Exception:
        return None

    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return None
        height, width = img.shape[:2]
        if width <= 0 or height <= 0:
            return None
        max_dim = max(width, height)
        if max_dim > 900:
            scale = 900.0 / max_dim
            img = cv2.resize(img, (int(width * scale), int(height * scale)))
            height, width = img.shape[:2]

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mean_brightness = float(np.mean(gray))
        mean_saturation = float(np.mean(hsv[:, :, 1]))
        dark_ratio = float(np.mean(gray < 100))
        bright_ratio = float(np.mean(gray > 180))
        edges = cv2.Canny(gray, 80, 160)
        edge_ratio = float(np.mean(edges > 0))
        portrait_or_square = height >= width * 0.75
    except Exception as e:
        logger.debug("Legal document detection skipped for %s: %s", image_path, e)
        return None

    if (
        portrait_or_square
        and mean_brightness >= 145
        and mean_saturation <= 95
        and bright_ratio >= 0.45
        and 0.01 <= dark_ratio <= 0.45
        and 0.01 <= edge_ratio <= 0.28
    ):
        return "document_cv"
    return None


def _candidate_reason(row) -> Optional[str]:
    if (row["img_type"] or "").lower() == "so_hong":
        return None
    return _metadata_reason(row["img_url"] or "", row["local_path"] or "") or _detect_document_image(row["local_path"] or "")


def classify_legal_images(source: Optional[str] = None, apply: bool = False, limit: Optional[int] = None) -> dict:
    with advisory_lock("classify-legal-images"):
        return _classify_legal_images(source=source, apply=apply, limit=limit)


def _classify_legal_images(source: Optional[str] = None, apply: bool = False, limit: Optional[int] = None) -> dict:
    """Scan listing_images and optionally mark certificate images as so_hong."""
    where = ["COALESCE(li.img_type, '') != 'so_hong'"]
    params = []
    if source:
        where.append("l.source = ?")
        params.append(source)
    where_sql = "WHERE " + " AND ".join(where)
    limit_sql = " LIMIT ?" if limit else ""
    if limit:
        params.append(int(limit))

    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT li.id, li.listing_id, li.img_url, li.img_order, li.img_type, li.local_path,
                   l.source
              FROM listing_images li
              JOIN listings l ON l.id = li.listing_id
              {where_sql}
             ORDER BY CASE
                    WHEN strpos(lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')), 'sohong') > 0
                      OR strpos(lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')), 'so-hong') > 0
                      OR strpos(lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')), 'sodo') > 0
                      OR strpos(lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')), 'so-do') > 0
                      OR strpos(lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')), 'gcn') > 0
                      OR strpos(lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')), 'qsd') > 0
                      OR strpos(lower(COALESCE(li.img_url, '') || ' ' || COALESCE(li.local_path, '')), 'giay-chung-nhan') > 0
                    THEN 0 ELSE 1 END,
                    li.id DESC
             {limit_sql}
            """,
            params,
        ).fetchall()

        stats = {
            "scanned": len(rows),
            "candidates": 0,
            "updated": 0,
            "reasons": {},
            "apply": bool(apply),
        }
        reasons = Counter()
        for row in rows:
            reason = _candidate_reason(row)
            if not reason:
                continue
            stats["candidates"] += 1
            reasons[reason] += 1
            if apply:
                conn.execute("UPDATE listing_images SET img_type='so_hong' WHERE id=?", (row["id"],))
                stats["updated"] += 1
        stats["reasons"] = dict(reasons)
        return stats
