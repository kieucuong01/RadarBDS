"""Legal-document verification and trust-tier helpers.

OCR is intentionally disabled. Legal trust is based only on whether the listing
has a usable so hong/so do image.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from db.connection import get_conn

LEGAL_STATUSES = {
    "unverified",
    "has_document",
}


def _row_get(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if str(v)]
    return [v.strip() for v in str(value).split(",") if v.strip()]


def _status_and_tier(has_doc: bool) -> tuple[str, str]:
    if not has_doc:
        return "unverified", "candidate_signal"
    return "has_document", "has_legal_doc"


def verify_legal_listing(
    listing: Mapping[str, Any] | Any,
    legal_fields: Mapping[str, Any] | None = None,
    *,
    has_legal_doc: bool = False,
    admin_status: str | None = None,
) -> dict[str, Any]:
    """Return legal trust from document-image presence only."""
    legal = dict(legal_fields or {})
    has_doc = bool(has_legal_doc or legal.get("document_image_id"))
    score = 55 if has_doc else 0
    status, tier = _status_and_tier(has_doc)
    if admin_status in LEGAL_STATUSES:
        status = admin_status
        tier = "has_legal_doc" if status == "has_document" else "candidate_signal"
        score = max(score, 55) if status == "has_document" else 0

    return {
        "listing_id": _row_get(listing, "id"),
        "status": status,
        "trust_tier": tier,
        "confidence_score": score,
        "document_image_id": legal.get("document_image_id"),
        "thua_so": None,
        "to_ban_do": None,
        "legal_area_m2": None,
        "legal_residential_m2": None,
        "legal_address": None,
        "legal_ward": None,
        "legal_road_text": None,
        "legal_road_code": None,
        "road_match_status": "not_checked",
        "conflict_flags": [],
        "evidence_json": json.dumps(
            {
                "has_legal_doc": has_doc,
                "ocr_disabled": True,
            },
            ensure_ascii=False,
        ),
    }


def conflict_flags_text(flags: Any) -> str:
    return ",".join(_as_list(flags))


LEGAL_UPSERT_SQL = """
    INSERT INTO legal_verifications (
        listing_id, status, trust_tier, confidence_score, document_image_id,
        thua_so, to_ban_do, legal_area_m2, legal_residential_m2,
        legal_address, legal_ward, legal_road_text, legal_road_code,
        road_match_status, conflict_flags, evidence_json, verified_by, verified_at,
        updated_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP::text,CURRENT_TIMESTAMP::text)
    ON CONFLICT (listing_id) DO UPDATE SET
        status=excluded.status,
        trust_tier=excluded.trust_tier,
        confidence_score=excluded.confidence_score,
        document_image_id=COALESCE(excluded.document_image_id, legal_verifications.document_image_id),
        thua_so=COALESCE(excluded.thua_so, legal_verifications.thua_so),
        to_ban_do=COALESCE(excluded.to_ban_do, legal_verifications.to_ban_do),
        legal_area_m2=COALESCE(excluded.legal_area_m2, legal_verifications.legal_area_m2),
        legal_residential_m2=COALESCE(excluded.legal_residential_m2, legal_verifications.legal_residential_m2),
        legal_address=COALESCE(excluded.legal_address, legal_verifications.legal_address),
        legal_ward=COALESCE(excluded.legal_ward, legal_verifications.legal_ward),
        legal_road_text=COALESCE(excluded.legal_road_text, legal_verifications.legal_road_text),
        legal_road_code=COALESCE(excluded.legal_road_code, legal_verifications.legal_road_code),
        road_match_status=excluded.road_match_status,
        conflict_flags=excluded.conflict_flags,
        evidence_json=excluded.evidence_json,
        verified_by=COALESCE(excluded.verified_by, legal_verifications.verified_by),
        verified_at=CASE
            WHEN excluded.verified_by IS NOT NULL THEN CURRENT_TIMESTAMP::text
            ELSE legal_verifications.verified_at
        END,
        updated_at=CURRENT_TIMESTAMP::text
"""


def _upsert_params(result: Mapping[str, Any], verified_by: str | None = None) -> tuple[Any, ...]:
    return (
        result.get("listing_id"),
        result.get("status"),
        result.get("trust_tier"),
        result.get("confidence_score"),
        result.get("document_image_id"),
        result.get("thua_so"),
        result.get("to_ban_do"),
        result.get("legal_area_m2"),
        result.get("legal_residential_m2"),
        result.get("legal_address"),
        result.get("legal_ward"),
        result.get("legal_road_text"),
        result.get("legal_road_code"),
        result.get("road_match_status"),
        conflict_flags_text(result.get("conflict_flags")),
        result.get("evidence_json"),
        verified_by,
    )


def upsert_legal_verification(conn, result: Mapping[str, Any], verified_by: str | None = None) -> None:
    listing_id = result.get("listing_id")
    if not listing_id:
        return
    conn.execute(LEGAL_UPSERT_SQL, _upsert_params(result, verified_by))


def upsert_legal_verifications(conn, results: list[Mapping[str, Any]]) -> None:
    params = [_upsert_params(result) for result in results if result.get("listing_id")]
    if params:
        conn.executemany(LEGAL_UPSERT_SQL, params)


def _latest_legal_image_sql() -> str:
    return """
        SELECT id
          FROM listing_images li2
         WHERE li2.listing_id = l.id
           AND li2.img_type = 'so_hong'
           AND COALESCE(li2.local_path, '') != 'NOT_FOUND'
         ORDER BY li2.img_order, li2.id
         LIMIT 1
    """


def refresh_legal_verifications(
    source: str | None = None,
    listing_id: int | None = None,
    apply: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Recompute legal verification rows from listing fields and legal images."""
    where = ["COALESCE(l.probably_sold,0)=0", "COALESCE(l.is_blacklisted,0)=0"]
    params: list[Any] = []
    if source:
        where.append("l.source = ?")
        params.append(source)
    if listing_id:
        where.append("l.id = ?")
        params.append(listing_id)
    limit_sql = " LIMIT ?" if limit else ""
    if limit:
        params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT l.id, l.title, l.description, l.ward, l.area_m2, l.road_type,
                   l.tho_cu_m2, l.tho_cu_ratio,
                   li.id AS document_image_id
              FROM listings l
              LEFT JOIN listing_images li ON li.id = ({_latest_legal_image_sql()})
              LEFT JOIN legal_verifications existing_lv ON existing_lv.listing_id = l.id
             WHERE {' AND '.join(where)}
             ORDER BY CASE WHEN existing_lv.listing_id IS NULL THEN 0 ELSE 1 END, l.id DESC
             {limit_sql}
            """,
            params,
        ).fetchall()

        stats = {
            "apply": apply,
            "scanned": len(rows),
            "updated": 0,
            "statuses": {},
            "trust_tiers": {},
        }
        pending_results: list[dict[str, Any]] = []
        for row in rows:
            legal_fields = {"document_image_id": row["document_image_id"]}
            result = verify_legal_listing(row, legal_fields, has_legal_doc=bool(row["document_image_id"]))
            stats["statuses"][result["status"]] = stats["statuses"].get(result["status"], 0) + 1
            stats["trust_tiers"][result["trust_tier"]] = stats["trust_tiers"].get(result["trust_tier"], 0) + 1
            if not apply:
                continue
            pending_results.append(result)
            stats["updated"] += 1
            if len(pending_results) >= 500:
                _flush_legal_verification_batch(conn, pending_results)
                pending_results = []
        if apply and pending_results:
            _flush_legal_verification_batch(conn, pending_results)
        return stats


def _flush_legal_verification_batch(conn, results: list[Mapping[str, Any]]) -> None:
    upsert_legal_verifications(conn, list(results))
    listing_ids = [int(r["listing_id"]) for r in results if r.get("listing_id")]
    if listing_ids:
        placeholders = ",".join("?" for _ in listing_ids)
        conn.execute(
            f"""
            UPDATE valuation_results v
               SET legal_status=lv.status,
                   trust_tier=lv.trust_tier,
                   trust_score=lv.confidence_score,
                   legal_flags=lv.conflict_flags
              FROM legal_verifications lv
             WHERE v.listing_id = lv.listing_id
               AND v.listing_id IN ({placeholders})
            """,
            listing_ids,
        )
    conn.commit()
