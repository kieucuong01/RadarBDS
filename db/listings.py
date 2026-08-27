"""Processed listing repository helpers."""
import json
import logging
from datetime import datetime
from typing import Optional, Sequence
from urllib.parse import urlsplit

from config.property_types import normalize_property_type
from db.connection import get_conn

logger = logging.getLogger(__name__)
# ─── PROCESSED layer ──────────────────────────────────────────────────────────

def _present(value) -> bool:
    return value not in (None, "", 0, 0.0)


def _prefer_new_value(new_value, old_value):
    return new_value if _present(new_value) else old_value


def _float_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _derive_area_from_dimensions(frontage_m, depth_m):
    frontage = _float_or_none(frontage_m)
    depth = _float_or_none(depth_m)
    if frontage is None or depth is None:
        return None
    if 2 <= frontage <= 50 and 5 <= depth <= 500:
        return round(frontage * depth, 1)
    return None


def _derive_depth_from_area_frontage(area_m2, frontage_m):
    area = _float_or_none(area_m2)
    frontage = _float_or_none(frontage_m)
    if area is None or frontage is None or frontage <= 0:
        return None
    depth = area / frontage
    if 2 <= frontage <= 50 and 5 <= depth <= 500:
        return round(depth, 1)
    return None


_MEASUREMENT_PROVENANCE_FIELDS = {
    "area_m2",
    "frontage_m",
    "depth_m",
    "road_width_m",
    "tho_cu_m2",
}


def _measurement_provenance(value) -> dict:
    if isinstance(value, dict):
        data = value
    elif value:
        try:
            data = json.loads(value)
        except (TypeError, ValueError):
            data = {}
    else:
        data = {}
    if not isinstance(data, dict):
        return {}
    return {
        str(field): str(source)
        for field, source in data.items()
        if field in _MEASUREMENT_PROVENANCE_FIELDS and source not in (None, "")
    }


def _serialize_measurement_provenance(value) -> str:
    return json.dumps(
        _measurement_provenance(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _coerce_listing_measurements(rec: dict) -> dict:
    out = dict(rec)
    provenance = _measurement_provenance(out.get("measurement_provenance"))

    if not _present(out.get("depth_m")):
        derived_depth = _derive_depth_from_area_frontage(out.get("area_m2"), out.get("frontage_m"))
        if derived_depth is not None:
            out["depth_m"] = derived_depth
            provenance["depth_m"] = "derived_area_frontage"

    derived_area = _derive_area_from_dimensions(out.get("frontage_m"), out.get("depth_m"))
    if not _present(out.get("area_m2")) and derived_area is not None:
        out["area_m2"] = derived_area
        provenance["area_m2"] = "derived_dimensions"

    for field in _MEASUREMENT_PROVENANCE_FIELDS:
        if _present(out.get(field)) and field not in provenance:
            provenance[field] = "unknown"
    out["measurement_provenance"] = provenance

    price_ty = _float_or_none(out.get("price_ty"))
    area_m2 = _float_or_none(out.get("area_m2"))
    if price_ty is not None and area_m2 and not _present(out.get("price_per_m2")):
        out["price_per_m2"] = round(price_ty * 1000 / area_m2, 3)

    return out


_LLM_EXTRACTION_OVERRIDE_FIELDS = {
    "price_ty",
    "price_per_m2",
    "area_m2",
    "ward",
    "property_type",
    "frontage_m",
    "depth_m",
    "road_name",
    "road_type",
    "road_tier",
    "tho_cu_m2",
    "tho_cu_ratio",
    "has_so",
}
_LLM_FLOAT_FIELDS = {
    "price_ty",
    "price_per_m2",
    "area_m2",
    "frontage_m",
    "depth_m",
    "tho_cu_m2",
    "tho_cu_ratio",
}


def _json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _explicit_llm_override_fields(notes) -> dict:
    data = _json_dict(notes)
    override = data.get("extraction_override") or data.get("llm_extraction_override")
    if not isinstance(override, dict):
        return {}
    if override.get("active") is False:
        return {}
    fields = override.get("fields") if isinstance(override.get("fields"), dict) else override
    return {k: v for k, v in fields.items() if k in _LLM_EXTRACTION_OVERRIDE_FIELDS}


def _coerce_llm_override_value(field: str, value):
    if value in ("", "unknown", "null"):
        return None
    if field in _LLM_FLOAT_FIELDS:
        return _float_or_none(value)
    if field == "road_tier":
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
    if field == "has_so":
        return int(bool(value))
    if value is None:
        return None
    text = str(value).strip()
    if field == "property_type":
        text = normalize_property_type(text)
    return text or None


def _apply_explicit_llm_extraction_override(rec: dict, existing=None) -> dict:
    override_fields = {}
    if existing is not None and "llm_notes" in existing.keys():
        override_fields.update(_explicit_llm_override_fields(existing["llm_notes"]))
    override_fields.update(_explicit_llm_override_fields(rec.get("llm_notes")))
    override_fields.update(_explicit_llm_override_fields(rec.get("llm_extraction_override")))
    if not override_fields:
        return rec

    out = dict(rec)
    touched = set()
    for field, value in override_fields.items():
        out[field] = _coerce_llm_override_value(field, value)
        touched.add(field)

    provenance = _measurement_provenance(out.get("measurement_provenance"))
    for field in touched & _MEASUREMENT_PROVENANCE_FIELDS:
        if _present(out.get(field)):
            provenance[field] = "admin_override"
        else:
            provenance.pop(field, None)
    out["measurement_provenance"] = provenance

    if touched & {"price_ty", "area_m2", "price_per_m2"} and "price_per_m2" not in touched:
        price_ty = _float_or_none(out.get("price_ty"))
        area_m2 = _float_or_none(out.get("area_m2"))
        out["price_per_m2"] = round(price_ty * 1000 / area_m2, 3) if price_ty is not None and area_m2 else None

    if touched & {"tho_cu_m2", "area_m2", "tho_cu_ratio"} and "tho_cu_ratio" not in touched:
        tho_cu_m2 = _float_or_none(out.get("tho_cu_m2"))
        area_m2 = _float_or_none(out.get("area_m2"))
        out["tho_cu_ratio"] = round(tho_cu_m2 / area_m2, 3) if tho_cu_m2 is not None and area_m2 else None

    out["_llm_extraction_override_fields"] = sorted(touched)
    return out


def save_llm_extraction_override(
    listing_id: int,
    fields: dict,
    *,
    actor: str = "llm",
    model: str | None = None,
    note: str | None = None,
) -> None:
    cleaned = {
        key: value
        for key, value in (fields or {}).items()
        if key in _LLM_EXTRACTION_OVERRIDE_FIELDS
    }
    if "property_type" in cleaned:
        cleaned["property_type"] = normalize_property_type(cleaned["property_type"])
    if not cleaned:
        raise ValueError("No supported extraction override fields provided")

    now = datetime.now().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT llm_notes FROM listings WHERE id=?",
            (listing_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Listing not found: {listing_id}")

        notes = _json_dict(row["llm_notes"])
        notes["extraction_override"] = {
            "active": True,
            "fields": cleaned,
            "actor": actor,
            "model": model,
            "note": note,
            "updated_at": now,
        }
        conn.execute(
            """
            UPDATE listings
            SET llm_verified=1,
                llm_notes=?,
                updated_at=?
            WHERE id=?
            """,
            (json.dumps(notes, ensure_ascii=False, sort_keys=True), now, listing_id),
        )


def _has_listing_column(conn, column: str) -> bool:
    try:
        return bool(conn.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name='listings'
              AND column_name=?
            """,
            (column,),
        ).fetchone())
    except Exception:
        return False


def _same_price_snapshot(a: Optional[float], b: Optional[float]) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < 0.000001


def _should_insert_price_history(conn, listing_id: int,
                                 price_ty: Optional[float],
                                 price_per_m2: Optional[float],
                                 source: str = "") -> bool:
    if price_ty is None and price_per_m2 is None:
        return False

    latest = conn.execute("""
        SELECT price_ty, price_per_m2
        FROM price_history
        WHERE listing_id = ?
        ORDER BY recorded_at DESC, id DESC
        LIMIT 1
    """, (listing_id,)).fetchone()
    if latest is None:
        return True

    if source == "guland":
        return not _same_price_snapshot(price_ty, latest["price_ty"])

    return not (
        _same_price_snapshot(price_ty, latest["price_ty"])
        and _same_price_snapshot(price_per_m2, latest["price_per_m2"])
    )


def upsert_listing(rec: dict, crawl_run_id: Optional[int] = None) -> tuple:
    """
    Insert or update listing từ normalized record.
    Returns (listing_id, is_new).
    """
    rec = _coerce_listing_measurements(rec)
    with get_conn() as conn:
        has_road_name_column = _has_listing_column(conn, "road_name")
        existing = conn.execute(
            """
            SELECT id, source, price_ty, price_per_m2, area_m2,
                   frontage_m, depth_m, measurement_provenance,
                   price_first_ty, price_dropped, suspicious_bait,
                   llm_notes
            FROM listings
            WHERE url = ?
            """,
            (rec["url"],)
        ).fetchone()
        rec = _apply_explicit_llm_extraction_override(rec, existing)
        if rec.get("property_type"):
            rec["property_type"] = normalize_property_type(rec.get("property_type"))

        now = datetime.now().isoformat()

        if existing is None:
            # Logic giá trị: set first_seen_at=last_seen_at=now cho lifecycle tracking
            road_name_col = ", road_name" if has_road_name_column else ""
            road_name_val = ", :road_name" if has_road_name_column else ""
            cur = conn.execute(f"""
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description,
                    area, ward, raw_area_text, price_ty, price_per_m2, area_m2,
                    property_type, tx_type, frontage_m, depth_m,
                    road_width_m, road_type, road_tier, tho_cu_m2, tho_cu_ratio, has_so, is_hot, contact_phone, seller_name{road_name_col},
                    extraction_quality_flags, measurement_provenance, crawl_run_id,
                    price_first_ty, crawled_at, updated_at,
                    first_seen_at, last_seen_at, is_active, posted_at,
                    source_status, source_status_reason
                ) VALUES (
                    :raw_id, :source, :source_id, :url, :title, :description,
                    :area, :ward, :raw_area_text, :price_ty, :price_per_m2, :area_m2,
                    :property_type, :tx_type, :frontage_m, :depth_m,
                    :road_width_m, :road_type, :road_tier, :tho_cu_m2, :tho_cu_ratio, :has_so, :is_hot, :contact_phone, :seller_name{road_name_val},
                    :extraction_quality_flags, :measurement_provenance, :crawl_run_id,
                    :price_ty, :crawled_at, :updated_at,
                    :crawled_at, :crawled_at, 1, :posted_at,
                    :source_status, :source_status_reason
                )
            """, {
                "raw_id":       rec.get("raw_id"),
                "source":       rec["source"],
                "source_id":    rec.get("source_id", ""),
                "url":          rec["url"],
                "title":        rec.get("title", ""),
                "description":  rec.get("description", ""),
                "area":         rec.get("area", ""),
                "ward":         rec.get("ward") or rec.get("area") or None,
                "raw_area_text": rec.get("raw_area_text", ""),
                "price_ty":     rec.get("price_ty"),
                "price_per_m2": rec.get("price_per_m2"),
                "area_m2":      rec.get("area_m2"),
                "property_type": rec.get("property_type", "khac"),
                "tx_type":      rec.get("tx_type", "ban"),
                "frontage_m":   rec.get("frontage_m"),
                "depth_m":      rec.get("depth_m"),
                "road_name":    rec.get("road_name"),
                "road_width_m": rec.get("road_width_m"),
                "road_type":    rec.get("road_type", "unknown"),
                "road_tier":    int(rec.get("road_tier", 0)),
                "tho_cu_m2":    rec.get("tho_cu_m2"),
                "tho_cu_ratio": rec.get("tho_cu_ratio"),
                "has_so":       int(rec.get("has_so", True)),
                "is_hot":       int(rec.get("is_hot", False)),
                "contact_phone": rec.get("contact_phone"),
                "seller_name":  rec.get("seller_name"),
                "extraction_quality_flags": rec.get("extraction_quality_flags") or "",
                "measurement_provenance": _serialize_measurement_provenance(
                    rec.get("measurement_provenance")
                ),
                "crawl_run_id": crawl_run_id,
                "crawled_at":   now,
                "updated_at":   now,
                "posted_at":    rec.get("post_date"),
                "source_status": "active" if rec["source"] == "guland" else "unknown",
                "source_status_reason": (
                    "new_confirmed_detail" if rec["source"] == "guland" else ""
                ),
            })
            listing_id = cur.lastrowid

            if _should_insert_price_history(
                conn,
                listing_id,
                rec.get("price_ty"),
                rec.get("price_per_m2"),
                rec["source"],
            ):
                conn.execute(
                    "INSERT INTO price_history (listing_id, price_ty, price_per_m2, crawl_run_id) VALUES (?,?,?,?)",
                    (listing_id, rec.get("price_ty"), rec.get("price_per_m2"), crawl_run_id)
                )
            return listing_id, True

        else:
            listing_id  = existing["id"]
            first_price = existing["price_first_ty"] or existing["price_ty"]
            clear_stale_measurements = bool(rec.get("_clear_stale_measurements"))
            override_fields = set(rec.get("_llm_extraction_override_fields") or [])
            is_guland = (rec.get("source") or existing["source"]) == "guland"
            is_facebook = (rec.get("source") or existing["source"]) == "facebook"
            clear_stale_price = bool(
                not _present(rec.get("price_ty"))
                and "price_ty" not in override_fields
                and (clear_stale_measurements or is_facebook)
            )
            if clear_stale_measurements:
                if is_guland and not _present(rec.get("price_ty")):
                    new_price = existing["price_ty"]
                else:
                    new_price = rec.get("price_ty")
            else:
                new_price = (
                    rec.get("price_ty")
                    if "price_ty" in override_fields
                    else _prefer_new_value(rec.get("price_ty"), existing["price_ty"])
                )
            if clear_stale_measurements:
                new_area = rec.get("area_m2")
                new_ppm2 = rec.get("price_per_m2")
                new_frontage = rec.get("frontage_m")
                new_depth = rec.get("depth_m")
            else:
                new_area = (
                    rec.get("area_m2")
                    if "area_m2" in override_fields
                    else _prefer_new_value(rec.get("area_m2"), existing["area_m2"])
                )
                if "price_per_m2" in override_fields:
                    new_ppm2 = rec.get("price_per_m2")
                elif override_fields & {"price_ty", "area_m2"}:
                    new_ppm2 = None
                else:
                    new_ppm2 = _prefer_new_value(rec.get("price_per_m2"), existing["price_per_m2"])
                new_frontage = (
                    rec.get("frontage_m")
                    if "frontage_m" in override_fields
                    else _prefer_new_value(rec.get("frontage_m"), existing["frontage_m"])
                )
                new_depth = (
                    rec.get("depth_m")
                    if "depth_m" in override_fields
                    else _prefer_new_value(rec.get("depth_m"), existing["depth_m"])
                )
            if clear_stale_price:
                new_price = None
                new_ppm2 = None
            existing_provenance = _measurement_provenance(existing["measurement_provenance"])
            incoming_provenance = _measurement_provenance(rec.get("measurement_provenance"))
            if clear_stale_measurements:
                new_provenance = incoming_provenance
            else:
                new_provenance = {**existing_provenance, **incoming_provenance}
            if not _present(new_depth):
                derived_depth = _derive_depth_from_area_frontage(new_area, new_frontage)
                if derived_depth is not None:
                    new_depth = derived_depth
                    new_provenance["depth_m"] = "derived_area_frontage"
            final_measurements = {
                "area_m2": new_area,
                "frontage_m": new_frontage,
                "depth_m": new_depth,
                "road_width_m": rec.get("road_width_m"),
                "tho_cu_m2": rec.get("tho_cu_m2"),
            }
            for field, value in final_measurements.items():
                if not _present(value):
                    new_provenance.pop(field, None)
            if not _present(new_ppm2) and _present(new_price) and _present(new_area):
                new_ppm2 = round(float(new_price) * 1000 / float(new_area), 3)
            price_changed = bool(
                is_guland
                and new_price is not None
                and not _same_price_snapshot(existing["price_ty"], new_price)
            )
            price_dropped  = existing["price_dropped"]
            price_drop_pct = None
            suspicious_bait = existing["suspicious_bait"] if "suspicious_bait" in existing.keys() else 0

            clear_price = clear_stale_price and not _present(new_price)
            if (("price_ty" in override_fields) or clear_stale_price) and not new_price:
                price_dropped = 0
                price_drop_pct = None
                suspicious_bait = 0
            elif new_price and first_price and new_price < first_price * 0.99:
                drop_pct = round((first_price - new_price) / first_price * 100, 2)
                if drop_pct > 40.0:
                    price_dropped = 0
                    price_drop_pct = None
                    suspicious_bait = 1
                else:
                    price_dropped = 1
                    price_drop_pct = drop_pct
                    suspicious_bait = 0

            road_name_set = "road_name           = :road_name," if has_road_name_column else ""
            conn.execute(f"""
                UPDATE listings SET
                    title               = :title,
                    price_ty            = :price_ty,
                    price_per_m2        = :price_per_m2,
                    area_m2             = :area_m2,
                    property_type       = :property_type,
                    frontage_m          = :frontage_m,
                    depth_m             = :depth_m,
                    area                = :area,
                    {road_name_set}
                    road_width_m        = :road_width_m,
                    road_tier           = CASE WHEN :road_tier > 0 THEN :road_tier ELSE 0 END,
                    road_type           = :road_type,
                    tho_cu_m2           = :tho_cu_m2,
                    tho_cu_ratio        = :tho_cu_ratio,
                    ward                = :ward,                 -- cho phép NULL overwrite (re-normalize có thể loại ward sai khi text chứa địa danh non-TDM)
                    has_so              = :has_so,
                    is_hot              = :is_hot,
                    extraction_quality_flags = :extraction_quality_flags,
                    measurement_provenance = :measurement_provenance,
                    crawl_run_id        = COALESCE(:crawl_run_id, crawl_run_id),
                    price_first_ty      = CASE WHEN :clear_price <> 0 THEN NULL ELSE price_first_ty END,
                    price_dropped       = :price_dropped,
                    price_drop_pct      = :price_drop_pct,
                    suspicious_bait     = :suspicious_bait,
                    consecutive_missing = 0,
                    updated_at          = :updated_at,
                    price_updated_at    = CASE
                        WHEN :price_changed <> 0 THEN CAST(:price_updated_at AS TIMESTAMPTZ)
                        ELSE price_updated_at
                    END,
                    last_seen_at        = :updated_at,
                    first_seen_at       = COALESCE(first_seen_at, :updated_at),
                    is_active           = 1,
                    delisted_at         = NULL,
                    source_status       = CASE
                        WHEN :is_guland <> 0 THEN 'active'
                        ELSE source_status
                    END,
                    source_status_reason = CASE
                        WHEN :is_guland <> 0 THEN 'refreshed_detail'
                        ELSE source_status_reason
                    END,
                    contact_phone = CASE
                        WHEN :is_guland <> 0
                             AND :publisher_contact_checked <> 0
                        THEN :contact_phone
                        ELSE contact_phone
                    END,
                    seller_name = CASE
                        WHEN :is_guland <> 0
                             AND NULLIF(BTRIM(:seller_name), '') IS NOT NULL
                        THEN :seller_name
                        ELSE seller_name
                    END,
                    posted_at           = COALESCE(posted_at, :posted_at)
                WHERE id = :id
            """, {
                "id":            listing_id,
                "title":         rec.get("title", ""),
                "price_ty":      new_price,
                "price_per_m2":  new_ppm2,
                "area_m2":       new_area,
                "property_type": rec.get("property_type", "dat_nen"),
                "frontage_m":    new_frontage,
                "depth_m":       new_depth,
                "area":          rec.get("area", ""),
                "road_name":     rec.get("road_name"),
                "road_width_m":  rec.get("road_width_m"),
                "road_tier":     int(rec.get("road_tier", 0)),
                "road_type":     rec.get("road_type") or "unknown",
                "tho_cu_m2":     rec.get("tho_cu_m2"),
                "tho_cu_ratio":  rec.get("tho_cu_ratio"),
                "ward":          rec.get("ward") or None,
                "has_so":        int(rec.get("has_so", True)),
                "is_hot":        int(rec.get("is_hot", False)),
                "extraction_quality_flags": rec.get("extraction_quality_flags") or "",
                "measurement_provenance": _serialize_measurement_provenance(new_provenance),
                "crawl_run_id": crawl_run_id,
                "price_dropped": price_dropped,
                "price_drop_pct": price_drop_pct,
                "suspicious_bait": suspicious_bait,
                "clear_price":    int(clear_price),
                "updated_at":    now,
                "price_updated_at": now,
                "price_changed": int(price_changed),
                "is_guland":     int(is_guland),
                "publisher_contact_checked": int(
                    bool(rec.get("_publisher_contact_checked"))
                ),
                "contact_phone": rec.get("contact_phone"),
                "seller_name": rec.get("seller_name"),
                "posted_at":     rec.get("post_date"),
            })

            if _should_insert_price_history(
                conn,
                listing_id,
                new_price,
                new_ppm2,
                rec.get("source") or existing["source"],
            ):
                conn.execute(
                    "INSERT INTO price_history (listing_id, price_ty, price_per_m2, crawl_run_id) VALUES (?,?,?,?)",
                    (listing_id, new_price, new_ppm2, crawl_run_id)
                )
            return listing_id, False


def update_listing_outlier(listing_id: int, is_outlier: bool,
                           direction: Optional[str], sigma: Optional[float]) -> None:
    """Cập nhật outlier flag sau khi chạy valuation."""
    with get_conn() as conn:
        conn.execute("""
            UPDATE listings SET
                is_outlier        = ?,
                outlier_direction = ?,
                outlier_sigma     = ?
            WHERE id = ?
        """, (int(is_outlier), direction, sigma, listing_id))


def canonical_image_asset_key(url: str) -> str:
    """Normalize a source image identity while dropping volatile signatures."""
    text = str(url or "").strip()
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return text
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path}"


def _ready_image_path(value: object) -> bool:
    path = str(value or "").strip()
    return bool(path and path.upper() != "NOT_FOUND")


def sync_listing_images(
    listing_id: int,
    img_urls: Sequence[str],
    *,
    source: str,
) -> dict[str, int]:
    """Merge a source gallery while keeping Facebook slots collision-free."""
    stats = {"inserted": 0, "updated": 0, "removed": 0, "reset": 0}
    urls = []
    seen = set()
    for value in img_urls or []:
        url = str(value or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        urls.append(url)

    with get_conn() as conn:
        if source != "facebook":
            for order, url in enumerate(urls):
                img_type = _classify_image_type(url, order)
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO listing_images
                        (listing_id, img_url, img_order, img_type)
                    VALUES (?, ?, ?, ?)
                    """,
                    (listing_id, url, order, img_type),
                )
                if cur.lastrowid:
                    stats["inserted"] += 1
            return stats

        for order, url in enumerate(urls):
            img_type = _classify_image_type(url, order)
            candidates = conn.execute(
                """
                SELECT id, img_url, img_order, img_type, local_path
                FROM listing_images
                WHERE listing_id=? AND (img_order=? OR img_url=?)
                ORDER BY id
                """,
                (listing_id, order, url),
            ).fetchall()
            if not candidates:
                conn.execute(
                    """
                    INSERT INTO listing_images
                        (listing_id, img_url, img_order, img_type)
                    VALUES (?, ?, ?, ?)
                    """,
                    (listing_id, url, order, img_type),
                )
                stats["inserted"] += 1
                continue

            new_key = canonical_image_asset_key(url)

            def candidate_rank(row) -> tuple[int, int, int, int]:
                same_asset = canonical_image_asset_key(row["img_url"]) == new_key
                ready = _ready_image_path(row["local_path"])
                return (
                    int(same_asset and ready),
                    int(same_asset),
                    int(ready),
                    int(row["id"]),
                )

            chosen = max(candidates, key=candidate_rank)
            duplicate_ids = [
                int(row["id"])
                for row in candidates
                if int(row["id"]) != int(chosen["id"])
            ]
            if duplicate_ids:
                placeholders = ",".join("?" for _ in duplicate_ids)
                conn.execute(
                    f"DELETE FROM listing_images WHERE id IN ({placeholders})",
                    duplicate_ids,
                )
                stats["removed"] += len(duplicate_ids)

            same_asset = canonical_image_asset_key(chosen["img_url"]) == new_key
            reset = bool(not same_asset and _ready_image_path(chosen["local_path"]))
            conn.execute(
                """
                UPDATE listing_images
                SET img_url=?,
                    img_order=?,
                    img_type=?,
                    local_path=CASE WHEN ? <> 0 THEN local_path ELSE NULL END,
                    ocr_text=CASE WHEN ? <> 0 THEN ocr_text ELSE NULL END,
                    crawled_at=datetime('now')
                WHERE id=?
                """,
                (
                    url,
                    order,
                    img_type,
                    int(same_asset),
                    int(same_asset),
                    int(chosen["id"]),
                ),
            )
            stats["updated"] += 1
            stats["reset"] += int(reset)
    return stats


def insert_images(
    listing_id: int,
    img_urls: list,
    source: str = "",
) -> dict[str, int]:
    return sync_listing_images(listing_id, img_urls, source=source)


def _classify_image_type(url: str, order: int) -> str:
    url_lower = url.lower()
    if any(k in url_lower for k in ["so-hong", "sohong", "so-do", "sodo", "gcn", "qsd", "giay-chung-nhan"]):
        return "so_hong"
    if any(k in url_lower for k in ["aerial", "drone", "satellite"]):
        return "aerial"
    return "cover" if order == 0 else "unknown"



