"""Admin duplicate-review queries and policy helpers.

This module is transport-agnostic: callers own authentication, connection
scopes, cache handling, and JSON response construction.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Callable

from cleansing.dedup import (
    _combined_text,
    _has_reliable_lot_signature,
    _road_tokens,
    _text_similarity,
)
from config.settings import LEGAL_IMAGE_EVIDENCE_ENABLED
from services.image_assets import resolve_image_url


AuditWriter = Callable[..., None]


class DuplicateQcError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _image_order_sql(prefix: str = "") -> str:
    col = f"{prefix}." if prefix else ""
    if LEGAL_IMAGE_EVIDENCE_ENABLED:
        return f"CASE WHEN {col}img_type='so_hong' THEN 0 ELSE 1 END, {col}img_order, {col}id"
    return f"{col}img_order, {col}id"

def _admin_duplicate_review_items(conn) -> list[dict]:
    ambiguous_duplicate_sql = """
              AND (
                   l.source <> 'facebook'
                OR c.source <> 'facebook'
                OR COALESCE(l.ward,'') = ''
                OR COALESCE(c.ward,'') = ''
                OR l.ward <> c.ward
                OR COALESCE(l.property_type,'') = ''
                OR COALESCE(c.property_type,'') = ''
                OR l.property_type <> c.property_type
                OR COALESCE(l.area_m2,0) <= 0
                OR COALESCE(c.area_m2,0) <= 0
                OR ABS(l.area_m2 - c.area_m2) >
                   CASE
                     WHEN l.area_m2 < c.area_m2
                     THEN CASE WHEN l.area_m2 * 0.03 > 3.0 THEN l.area_m2 * 0.03 ELSE 3.0 END
                     ELSE CASE WHEN c.area_m2 * 0.03 > 3.0 THEN c.area_m2 * 0.03 ELSE 3.0 END
                   END
                OR (
                    l.frontage_m IS NOT NULL
                    AND c.frontage_m IS NOT NULL
                    AND ABS(l.frontage_m - c.frontage_m) > 0.35
                )
                OR (
                    l.depth_m IS NOT NULL
                    AND c.depth_m IS NOT NULL
                    AND ABS(l.depth_m - c.depth_m) > 0.8
                )
              )
    """
    road_name_select_l = "l.road_name" if _has_listing_column(conn, "road_name") else "NULL"
    road_name_select_c = "c.road_name" if _has_listing_column(conn, "road_name") else "NULL"
    rows = conn.execute(f"""
        SELECT l.id, l.title, l.url, l.source, l.source_id, l.ward, l.property_type, l.price_ty, l.area_m2,
               l.frontage_m, l.depth_m, l.tho_cu_m2, l.contact_phone,
               l.description, COALESCE(l.posted_at, l.crawled_at, l.updated_at) AS dt,
               l.duplicate_of_id, c.title AS canonical_title, c.url AS canonical_url,
               {road_name_select_l} AS road_name,
               c.source AS canonical_source, c.source_id AS canonical_source_id, c.ward AS canonical_ward,
               c.property_type AS canonical_property_type,
               c.price_ty AS canonical_price_ty, c.area_m2 AS canonical_area_m2,
               c.frontage_m AS canonical_frontage_m, c.depth_m AS canonical_depth_m,
               c.tho_cu_m2 AS canonical_tho_cu_m2, c.contact_phone AS canonical_contact_phone,
               {road_name_select_c} AS canonical_road_name, c.description AS canonical_description,
               COALESCE(c.posted_at, c.crawled_at, c.updated_at) AS canonical_dt,
               li.local_path AS img_local, li.img_url AS img_url,
               ci.local_path AS canonical_img_local, ci.img_url AS canonical_img_url
        FROM listings l
        JOIN listings c ON c.id = l.duplicate_of_id
        LEFT JOIN listing_images li ON li.id = (
            SELECT id FROM listing_images WHERE listing_id = l.id ORDER BY {_image_order_sql()} LIMIT 1
        )
        LEFT JOIN listing_images ci ON ci.id = (
            SELECT id FROM listing_images WHERE listing_id = c.id ORDER BY {_image_order_sql()} LIMIT 1
        )
        WHERE COALESCE(l.probably_sold,0)=0
          AND COALESCE(l.is_blacklisted,0)=0
          AND l.possibly_duplicate=1
          AND NOT (
            l.source = c.source
            AND (
                 (COALESCE(l.source_id,'') <> '' AND l.source_id = c.source_id)
              OR (COALESCE(l.url,'') <> '' AND l.url = c.url)
            )
          )
          AND NOT EXISTS (
            SELECT 1
            FROM dedup_overrides o
            WHERE o.active=1
              AND o.action='merge'
              AND o.listing_id=l.id
              AND o.target_listing_id=c.id
          )
          {ambiguous_duplicate_sql}
        ORDER BY l.updated_at DESC
        LIMIT 500
    """).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        if _admin_same_listing_identity(item):
            continue
        if _admin_should_auto_merge_duplicate_pair(item):
            continue
        if _admin_should_auto_split_duplicate_pair(item):
            continue
        if _admin_should_hide_safe_duplicate_review_pair(item):
            continue
        items.append(_admin_duplicate_qc_item(row))
    existing_pairs = {(item["id"], item["duplicate_of_id"]) for item in items}
    if len(items) < 500:
        items.extend(_admin_suspected_duplicate_items(conn, existing_pairs, 500 - len(items)))
    return items


def _admin_duplicate_qc_item(row, *, suspected: bool = False) -> dict:
    item = dict(row)
    item["detail_url"] = f"/listing/{item['id']}"
    item["canonical_detail_url"] = f"/listing/{item['duplicate_of_id']}"
    item["image"] = resolve_image_url(item.pop("img_local"), item.pop("img_url"))
    item["canonical_image"] = resolve_image_url(item.pop("canonical_img_local"), item.pop("canonical_img_url"))
    item["description_excerpt"] = (item.get("description") or "")[:260]
    item["canonical_description_excerpt"] = (item.get("canonical_description") or "")[:260]
    item["suspected_duplicate"] = bool(suspected)
    reasons = _duplicate_qc_reasons(item)
    item["qc_reasons"] = (["Nghi ngờ cùng lô"] + reasons) if suspected else reasons
    for key in ("contact_phone", "canonical_contact_phone"):
        item.pop(key, None)
    return item


def _admin_duplicate_member_from_item(item: dict, *, canonical: bool = False) -> dict:
    prefix = "canonical_" if canonical else ""
    return {
        "id": item.get("duplicate_of_id") if canonical else item.get("id"),
        "source": item.get(f"{prefix}source"),
        "source_id": item.get(f"{prefix}source_id"),
        "url": item.get(f"{prefix}url"),
        "title": item.get(f"{prefix}title"),
        "ward": item.get(f"{prefix}ward"),
        "property_type": item.get(f"{prefix}property_type"),
        "price_ty": item.get(f"{prefix}price_ty"),
        "area_m2": item.get(f"{prefix}area_m2"),
        "frontage_m": item.get(f"{prefix}frontage_m"),
        "depth_m": item.get(f"{prefix}depth_m"),
        "tho_cu_m2": item.get(f"{prefix}tho_cu_m2"),
        "road_name": item.get(f"{prefix}road_name"),
        "dt": item.get(f"{prefix}dt"),
        "detail_url": item.get("canonical_detail_url") if canonical else item.get("detail_url"),
        "image": item.get("canonical_image") if canonical else item.get("image"),
        "description_excerpt": item.get("canonical_description_excerpt") if canonical else item.get("description_excerpt"),
    }


def _admin_duplicate_review_groups(items: list[dict]) -> list[dict]:
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_a] = root_b

    for item in items:
        try:
            union(int(item["id"]), int(item["duplicate_of_id"]))
        except (KeyError, TypeError, ValueError):
            continue

    components: dict[int, dict] = {}
    for item in items:
        try:
            listing_id = int(item["id"])
            target_id = int(item["duplicate_of_id"])
        except (KeyError, TypeError, ValueError):
            continue
        root = find(listing_id)
        component = components.setdefault(
            root,
            {
                "pairs": [],
                "members": {},
                "incoming": {},
                "qc_reasons": [],
                "suspected_duplicate": False,
                "first_seen": len(components),
            },
        )
        component["pairs"].append(item)
        component["incoming"][target_id] = component["incoming"].get(target_id, 0) + 1
        component["members"][listing_id] = _admin_duplicate_member_from_item(item)
        component["members"][target_id] = _admin_duplicate_member_from_item(item, canonical=True)
        component["suspected_duplicate"] = component["suspected_duplicate"] or bool(item.get("suspected_duplicate"))
        for reason in item.get("qc_reasons") or []:
            if reason not in component["qc_reasons"]:
                component["qc_reasons"].append(reason)

    groups = []
    for component in components.values():
        members_by_id = component["members"]
        if len(members_by_id) < 2:
            continue
        default_target_id = max(
            members_by_id,
            key=lambda member_id: (component["incoming"].get(member_id, 0), member_id),
        )
        members = sorted(
            members_by_id.values(),
            key=lambda member: (member["id"] != default_target_id, -int(member["id"] or 0)),
        )
        member_ids = sorted(int(member["id"]) for member in members if member.get("id"))
        groups.append({
            "group_id": f"dup-{member_ids[0]}-{member_ids[-1]}",
            "default_target_id": default_target_id,
            "member_count": len(members),
            "pair_count": len(component["pairs"]),
            "members": members,
            "pairs": component["pairs"],
            "qc_reasons": component["qc_reasons"],
            "suspected_duplicate": component["suspected_duplicate"],
            "_first_seen": component["first_seen"],
        })

    groups.sort(key=lambda group: (group["_first_seen"], -group["member_count"]))
    for group in groups:
        group.pop("_first_seen", None)
    return groups


def _admin_same_listing_identity(item: dict) -> bool:
    source = (item.get("source") or "").strip()
    canonical_source = (item.get("canonical_source") or "").strip()
    if not source or source != canonical_source:
        return False

    source_id = (item.get("source_id") or "").strip()
    canonical_source_id = (item.get("canonical_source_id") or "").strip()
    if source_id and canonical_source_id and source_id == canonical_source_id:
        return True

    url = (item.get("url") or "").strip().rstrip("/")
    canonical_url = (item.get("canonical_url") or "").strip().rstrip("/")
    return bool(url and canonical_url and url == canonical_url)


def _has_listing_column(conn, column_name: str) -> bool:
    try:
        return bool(conn.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name='listings'
              AND column_name=?
            """,
            (column_name,),
        ).fetchone())
    except Exception:
        return False


def _admin_listing_from_duplicate_item(item: dict, *, canonical: bool = False) -> dict:
    prefix = "canonical_" if canonical else ""
    return {
        "id": item.get("duplicate_of_id") if canonical else item.get("id"),
        "source": item.get(f"{prefix}source"),
        "source_id": item.get(f"{prefix}source_id"),
        "title": item.get(f"{prefix}title"),
        "description": item.get(f"{prefix}description"),
        "ward": item.get(f"{prefix}ward"),
        "property_type": item.get(f"{prefix}property_type"),
        "area_m2": item.get(f"{prefix}area_m2"),
        "frontage_m": item.get(f"{prefix}frontage_m"),
        "depth_m": item.get(f"{prefix}depth_m"),
        "road_name": item.get(f"{prefix}road_name"),
        "contact_phone": item.get(f"{prefix}contact_phone"),
        "price_ty": item.get(f"{prefix}price_ty"),
        "price_per_m2": item.get(f"{prefix}price_per_m2"),
        "tho_cu_m2": item.get(f"{prefix}tho_cu_m2"),
        "posted_at": item.get(f"{prefix}dt"),
        "crawled_at": item.get(f"{prefix}dt"),
    }


def _admin_near_value(a, b, *, abs_tol: float, rel_tol: float) -> bool:
    a_num = _safe_float(a)
    b_num = _safe_float(b)
    if a_num is None or b_num is None or a_num <= 0 or b_num <= 0:
        return False
    return abs(a_num - b_num) <= max(abs_tol, min(a_num, b_num) * rel_tol)


def _admin_phone_tail(value) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[-9:] if len(digits) >= 9 else ""


def _admin_distinctive_area(value) -> bool:
    area = _safe_float(value)
    if area is None or area <= 0:
        return False
    rounded = round(area)
    if abs(area - rounded) > 0.05:
        return True
    if rounded <= 0:
        return False
    # Common template lot sizes should not be treated as unique identifiers.
    if rounded % 50 == 0:
        return False
    if area <= 400 and rounded % 25 == 0:
        return False
    return True


def _admin_road_conflict(item: dict) -> bool:
    try:
        from cleansing.dedup import _combined_text, _road_tokens
    except Exception:
        return False

    listing = _admin_listing_from_duplicate_item(item)
    canonical = _admin_listing_from_duplicate_item(item, canonical=True)
    roads_a = _road_tokens(_combined_text(listing))
    roads_b = _road_tokens(_combined_text(canonical))
    if roads_a and roads_b:
        return not bool(roads_a.intersection(roads_b))

    road_name_a = (listing.get("road_name") or "").strip().casefold()
    road_name_b = (canonical.get("road_name") or "").strip().casefold()
    return bool(road_name_a and road_name_b and road_name_a != road_name_b)


def _admin_should_auto_split_duplicate_pair(item: dict) -> bool:
    if _admin_same_listing_identity(item):
        return False
    if item.get("source") != "facebook" or item.get("canonical_source") != "facebook":
        return False
    return _admin_road_conflict(item)


def _admin_should_auto_merge_duplicate_pair(item: dict) -> bool:
    if _admin_same_listing_identity(item):
        return False
    if item.get("source") != "facebook" or item.get("canonical_source") != "facebook":
        return False

    ward = (item.get("ward") or "").strip()
    canonical_ward = (item.get("canonical_ward") or "").strip()
    both_wards_missing = not ward and not canonical_ward
    one_ward_missing = bool(ward) != bool(canonical_ward)
    if ward and canonical_ward and ward != canonical_ward:
        return False
    if (item.get("property_type") or "") != (item.get("canonical_property_type") or ""):
        return False

    area_a = _safe_float(item.get("area_m2"))
    area_b = _safe_float(item.get("canonical_area_m2"))
    both_areas_missing = (area_a is None or area_a <= 0) and (area_b is None or area_b <= 0)
    area_match = _admin_near_value(area_a, area_b, abs_tol=1.0, rel_tol=0.005)
    distinctive_area_match = area_match and (_admin_distinctive_area(area_a) or _admin_distinctive_area(area_b))
    if not area_match and not both_areas_missing:
        return False
    if one_ward_missing and not distinctive_area_match:
        return False

    tc_a = _safe_float(item.get("tho_cu_m2"))
    tc_b = _safe_float(item.get("canonical_tho_cu_m2"))
    if (tc_a is None) != (tc_b is None):
        return False
    if tc_a is not None and not _admin_near_value(tc_a, tc_b, abs_tol=1.0, rel_tol=0.01):
        return False

    try:
        from cleansing.dedup import _combined_text, _road_tokens, _text_similarity
    except Exception:
        return False

    listing = _admin_listing_from_duplicate_item(item)
    canonical = _admin_listing_from_duplicate_item(item, canonical=True)
    roads_a = _road_tokens(_combined_text(listing))
    roads_b = _road_tokens(_combined_text(canonical))
    road_name_a = (listing.get("road_name") or "").strip().casefold()
    road_name_b = (canonical.get("road_name") or "").strip().casefold()
    shared_road = bool(roads_a and roads_b and roads_a.intersection(roads_b))
    same_road_name = bool(road_name_a and road_name_b and road_name_a == road_name_b)
    road_conflict = bool((roads_a and roads_b and not shared_road) or (road_name_a and road_name_b and not same_road_name))

    frontage_match = _admin_near_value(item.get("frontage_m"), item.get("canonical_frontage_m"), abs_tol=0.1, rel_tol=0.005)
    depth_match = _admin_near_value(item.get("depth_m"), item.get("canonical_depth_m"), abs_tol=0.3, rel_tol=0.005)
    dims_match = frontage_match and depth_match
    text_sim = _text_similarity(_combined_text(listing), _combined_text(canonical))
    phone_a = _admin_phone_tail(item.get("contact_phone"))
    phone_b = _admin_phone_tail(item.get("canonical_contact_phone"))
    same_phone = bool(phone_a and phone_a == phone_b)

    if road_conflict:
        return False

    if both_areas_missing:
        if not same_phone:
            return False
        return text_sim >= 0.86

    if distinctive_area_match and text_sim >= 0.86:
        return True

    if distinctive_area_match and text_sim >= 0.82:
        return bool(
            same_phone
            or dims_match
            or shared_road
            or same_road_name
            or (ward and canonical_ward and ward == canonical_ward)
        )

    if both_wards_missing:
        return bool(dims_match and (text_sim >= 0.88 or same_phone))

    if not shared_road and not same_road_name:
        return False

    if dims_match and (text_sim >= 0.55 or same_phone):
        return True
    return bool(text_sim >= 0.92 and (dims_match or same_phone))


def _admin_should_hide_safe_duplicate_review_pair(item: dict) -> bool:
    if _admin_same_listing_identity(item):
        return False
    if item.get("source") != "facebook" or item.get("canonical_source") != "facebook":
        return False
    if (item.get("property_type") or "") != (item.get("canonical_property_type") or ""):
        return False

    ward = (item.get("ward") or "").strip()
    canonical_ward = (item.get("canonical_ward") or "").strip()
    same_ward = bool(ward and canonical_ward and ward == canonical_ward)
    both_wards_missing = not ward and not canonical_ward
    if ward and canonical_ward and ward != canonical_ward:
        return False

    try:
        from cleansing.dedup import _combined_text, _road_tokens, _text_similarity
    except Exception:
        return False

    listing = _admin_listing_from_duplicate_item(item)
    canonical = _admin_listing_from_duplicate_item(item, canonical=True)
    text_a = _combined_text(listing)
    text_b = _combined_text(canonical)
    roads_a = _road_tokens(text_a)
    roads_b = _road_tokens(text_b)
    road_name_a = (listing.get("road_name") or "").strip().casefold()
    road_name_b = (canonical.get("road_name") or "").strip().casefold()
    shared_road = bool(roads_a and roads_b and roads_a.intersection(roads_b))
    same_road_name = bool(road_name_a and road_name_b and road_name_a == road_name_b)
    road_conflict = bool((roads_a and roads_b and not shared_road) or (road_name_a and road_name_b and not same_road_name))
    if road_conflict:
        return False

    text_sim = _text_similarity(text_a, text_b)
    area_a = _safe_float(item.get("area_m2"))
    area_b = _safe_float(item.get("canonical_area_m2"))
    both_areas_missing = (area_a is None or area_a <= 0) and (area_b is None or area_b <= 0)
    area_match_1pct = _admin_near_value(area_a, area_b, abs_tol=1.0, rel_tol=0.01)
    area_match_3pct = _admin_near_value(area_a, area_b, abs_tol=3.0, rel_tol=0.03)
    distinctive_area_match = area_match_3pct and (_admin_distinctive_area(area_a) or _admin_distinctive_area(area_b))
    relaxed_frontage_match = _admin_near_value(item.get("frontage_m"), item.get("canonical_frontage_m"), abs_tol=0.35, rel_tol=0.01)
    relaxed_depth_match = _admin_near_value(item.get("depth_m"), item.get("canonical_depth_m"), abs_tol=1.05, rel_tol=0.01)
    relaxed_dims_match = relaxed_frontage_match and relaxed_depth_match
    same_road = shared_road or same_road_name

    if both_areas_missing:
        if same_ward and text_sim >= 0.90:
            return True
        if same_road and text_sim >= 0.88:
            return True
        return False

    if same_ward and same_road and area_match_1pct and relaxed_dims_match:
        return True

    if both_wards_missing and distinctive_area_match and text_sim >= 0.80:
        return True

    if both_wards_missing and same_road and area_match_1pct and relaxed_dims_match and text_sim >= 0.70:
        return True

    return False

def _admin_is_suspected_duplicate_pair(item: dict) -> bool:
    if _admin_same_listing_identity(item):
        return False

    try:
        from cleansing.dedup import _has_reliable_lot_signature
    except Exception:
        return False

    listing = _admin_listing_from_duplicate_item(item)
    canonical = _admin_listing_from_duplicate_item(item, canonical=True)
    return _has_reliable_lot_signature(
        listing,
        canonical,
        allow_facebook_same_price=True,
    )


def _admin_suspected_duplicate_items(conn, existing_pairs: set[tuple[int, int]], limit: int) -> list[dict]:
    if limit <= 0:
        return []

    try:
        from cleansing.dedup import _combined_text, _road_tokens
    except Exception:
        return []

    road_name_select_l = "l.road_name" if _has_listing_column(conn, "road_name") else "NULL"
    road_name_select_c = "c.road_name" if _has_listing_column(conn, "road_name") else "NULL"
    candidate_rows = conn.execute(f"""
        SELECT id, source, source_id, url, title, description, area, ward, property_type,
               price_ty, price_per_m2, area_m2, frontage_m, depth_m,
               tho_cu_m2, {road_name_select_l} AS road_name, contact_phone,
               COALESCE(posted_at, crawled_at, updated_at) AS dt
        FROM listings l
        WHERE COALESCE(probably_sold,0)=0
          AND COALESCE(is_blacklisted,0)=0
          AND COALESCE(possibly_duplicate,0)=0
          AND duplicate_of_id IS NULL
          AND source='facebook'
          AND area_m2 IS NOT NULL
          AND area_m2 > 0
          AND property_type IN ('dat_nen','nha_dat','nha_tro')
        ORDER BY COALESCE(updated_at, crawled_at, posted_at, '') DESC
        LIMIT 8000
    """).fetchall()
    split_rows = conn.execute("""
        SELECT listing_id, target_listing_id
        FROM dedup_overrides
        WHERE active=1
          AND action='split'
          AND listing_id IS NOT NULL
          AND target_listing_id IS NOT NULL
    """).fetchall()
    split_pairs = {
        tuple(sorted((int(r["listing_id"]), int(r["target_listing_id"]))))
        for r in split_rows
    }

    def compatible_type(a: str, b: str) -> bool:
        return a == b

    from collections import defaultdict

    phone_pat = re.compile(r"(?:0|\+84)\d[\d\s.()-]{7,14}\d")

    def text_phone_tail(row: dict) -> str:
        text = f"{row.get('contact_phone') or ''} {row.get('title') or ''} {row.get('description') or ''}"
        for match in phone_pat.finditer(text):
            digits = re.sub(r"\D", "", match.group(0))
            if len(digits) >= 9:
                return digits[-9:]
        return ""

    buckets = defaultdict(list)
    for row in candidate_rows:
        d = dict(row)
        area = _safe_float(d.get("area_m2"))
        if not area:
            continue
        ward = (d.get("ward") or "").strip()
        prop = d.get("property_type") or ""
        type_keys = ["dat_land"] if prop == "dat_nen" else [prop]
        area_bucket = int(round(area / 10.0))
        d["_road_tokens"] = _road_tokens(_combined_text(d))
        d["_phone_tail"] = text_phone_tail(d)
        for type_key in type_keys:
            for token in d["_road_tokens"]:
                buckets[("road", token, type_key, area_bucket)].append(d)
            if d["_phone_tail"] and area >= 300:
                buckets[("phone_area", d["_phone_tail"], type_key, area_bucket)].append(d)

    pair_ids = []
    seen = set(existing_pairs)
    for bucket_rows in buckets.values():
        if len(bucket_rows) < 2:
            continue
        for idx, first in enumerate(bucket_rows):
            for second in bucket_rows[idx + 1:]:
                if first["id"] == second["id"]:
                    continue
                if not compatible_type(first.get("property_type"), second.get("property_type")):
                    continue
                area_a = _safe_float(first.get("area_m2"))
                area_b = _safe_float(second.get("area_m2"))
                if not area_a or not area_b:
                    continue
                if abs(area_a - area_b) > max(3.0, min(area_a, area_b) * 0.01):
                    continue
                if first.get("ward") and second.get("ward") and first.get("ward") != second.get("ward"):
                    continue
                first_roads = first.get("_road_tokens") or set()
                second_roads = second.get("_road_tokens") or set()
                shared_road = bool(first_roads and second_roads and first_roads.intersection(second_roads))
                same_phone = bool(first.get("_phone_tail") and first.get("_phone_tail") == second.get("_phone_tail"))
                if first_roads and second_roads and not shared_road:
                    continue
                if not shared_road and not same_phone:
                    continue
                older, newer = sorted(
                    (first, second),
                    key=lambda x: ((x.get("dt") or ""), int(x.get("id") or 0)),
                )
                pair = (older["id"], newer["id"])
                if pair in seen:
                    continue
                if tuple(sorted(pair)) in split_pairs:
                    continue
                item_probe = {
                    "id": older["id"],
                    "source": older.get("source"),
                    "source_id": older.get("source_id"),
                    "url": older.get("url"),
                    "title": older.get("title"),
                    "description": older.get("description"),
                    "ward": older.get("ward"),
                    "property_type": older.get("property_type"),
                    "area_m2": older.get("area_m2"),
                    "frontage_m": older.get("frontage_m"),
                    "depth_m": older.get("depth_m"),
                    "tho_cu_m2": older.get("tho_cu_m2"),
                    "road_name": older.get("road_name"),
                    "contact_phone": older.get("contact_phone"),
                    "price_ty": older.get("price_ty"),
                    "price_per_m2": older.get("price_per_m2"),
                    "dt": older.get("dt"),
                    "duplicate_of_id": newer["id"],
                    "canonical_source": newer.get("source"),
                    "canonical_source_id": newer.get("source_id"),
                    "canonical_url": newer.get("url"),
                    "canonical_title": newer.get("title"),
                    "canonical_description": newer.get("description"),
                    "canonical_ward": newer.get("ward"),
                    "canonical_property_type": newer.get("property_type"),
                    "canonical_area_m2": newer.get("area_m2"),
                    "canonical_frontage_m": newer.get("frontage_m"),
                    "canonical_depth_m": newer.get("depth_m"),
                    "canonical_tho_cu_m2": newer.get("tho_cu_m2"),
                    "canonical_road_name": newer.get("road_name"),
                    "canonical_contact_phone": newer.get("contact_phone"),
                    "canonical_price_ty": newer.get("price_ty"),
                    "canonical_price_per_m2": newer.get("price_per_m2"),
                    "canonical_dt": newer.get("dt"),
                }
                if not _admin_is_suspected_duplicate_pair(item_probe):
                    continue
                seen.add(pair)
                if _admin_should_auto_merge_duplicate_pair(item_probe):
                    continue
                pair_ids.append(pair)
                if len(pair_ids) >= limit:
                    break
            if len(pair_ids) >= limit:
                break
        if len(pair_ids) >= limit:
            break

    items = []
    for listing_id, target_id in pair_ids:
        row = conn.execute(f"""
        SELECT l.id, l.title, l.url, l.source, l.source_id, l.ward, l.property_type,
               l.price_ty, l.price_per_m2, l.area_m2, l.frontage_m, l.depth_m,
               l.tho_cu_m2, {road_name_select_l} AS road_name, l.contact_phone,
               l.description, COALESCE(l.posted_at, l.crawled_at, l.updated_at) AS dt,
               c.id AS duplicate_of_id, c.title AS canonical_title, c.url AS canonical_url,
               c.source AS canonical_source, c.source_id AS canonical_source_id,
               c.ward AS canonical_ward, c.property_type AS canonical_property_type,
               c.price_ty AS canonical_price_ty, c.price_per_m2 AS canonical_price_per_m2,
               c.area_m2 AS canonical_area_m2, c.frontage_m AS canonical_frontage_m,
               c.depth_m AS canonical_depth_m, c.tho_cu_m2 AS canonical_tho_cu_m2,
               {road_name_select_c} AS canonical_road_name,
               c.contact_phone AS canonical_contact_phone,
               c.description AS canonical_description,
               COALESCE(c.posted_at, c.crawled_at, c.updated_at) AS canonical_dt,
               li.local_path AS img_local, li.img_url AS img_url,
               ci.local_path AS canonical_img_local, ci.img_url AS canonical_img_url
        FROM listings l
        JOIN listings c ON c.id = ?
        LEFT JOIN listing_images li ON li.id = (
            SELECT id FROM listing_images WHERE listing_id = l.id ORDER BY {_image_order_sql()} LIMIT 1
        )
        LEFT JOIN listing_images ci ON ci.id = (
            SELECT id FROM listing_images WHERE listing_id = c.id ORDER BY {_image_order_sql()} LIMIT 1
        )
        WHERE l.id = ?
        """, (target_id, listing_id)).fetchone()
        if row:
            items.append(_admin_duplicate_qc_item(row, suspected=True))
    return items


def _duplicate_qc_reasons(item: dict) -> list[str]:
    reasons = []
    if item.get("source") != "facebook" or item.get("canonical_source") != "facebook":
        reasons.append("Khác hoặc không phải nguồn Facebook")
    if not item.get("ward") or not item.get("canonical_ward"):
        reasons.append("Thiếu phường")
    elif item.get("ward") != item.get("canonical_ward"):
        reasons.append("Khác phường")
    if not item.get("property_type") or not item.get("canonical_property_type"):
        reasons.append("Thiếu loại hình")
    elif item.get("property_type") != item.get("canonical_property_type"):
        reasons.append("Khác loại hình")

    area_a = _safe_float(item.get("area_m2"))
    area_b = _safe_float(item.get("canonical_area_m2"))
    if not area_a or not area_b:
        reasons.append("Thiếu diện tích")
    else:
        area_tolerance = max(3.0, min(area_a, area_b) * 0.03)
        if abs(area_a - area_b) > area_tolerance:
            reasons.append("Diện tích lệch")

    frontage_a = _safe_float(item.get("frontage_m"))
    frontage_b = _safe_float(item.get("canonical_frontage_m"))
    if frontage_a and frontage_b and abs(frontage_a - frontage_b) > 0.35:
        reasons.append("Ngang lệch")

    depth_a = _safe_float(item.get("depth_m"))
    depth_b = _safe_float(item.get("canonical_depth_m"))
    if depth_a and depth_b and abs(depth_a - depth_b) > 0.8:
        reasons.append("Dài lệch")

    return reasons or ["Cần kiểm tra thủ công"]

def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def load_duplicate_review_payload(conn) -> dict:
    items = _admin_duplicate_review_items(conn)
    return {"items": items, "groups": _admin_duplicate_review_groups(items)}
