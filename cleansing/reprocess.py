"""
Reprocess pipeline — chạy lại từ raw_listings mà không crawl lại.

Usage:
    python -m cleansing.reprocess                     # toàn bộ
    python -m cleansing.reprocess --source guland
    python -m cleansing.reprocess --since 2025-01-01
    python -m cleansing.reprocess --source batdongsan --since 2025-W10
"""
import argparse
import logging
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from cleansing.normalizer import normalize_record, compute_content_hash
from cleansing.feature_extractor import (
    extract_area,
    extract_url_hint,
    has_ambiguous_masked_price,
    is_multi_lot_listing,
)
from db.analytics import save_valuation_result
from db.connection import advisory_lock, get_conn
from db.crawl_runs import finish_crawl_run, start_crawl_run
from db.listings import insert_images, update_listing_outlier, upsert_listing
from db.moderation import is_phone_blacklisted
from db.raw_listings import get_raw_for_reprocess
from db.schema import init_schema


GULAND_EXTREME_PPM2 = 80.0
GULAND_OLD_POST_DAYS = 14
GULAND_CLUSTER_MIN_SIZE = 4
BAD_VALUATION_VERDICTS = {"fake_price", "cannot_price", "overpriced"}
GOOD_VALUATION_VERDICTS = {"cheap_real", "correct", "good"}
LOW_ABSOLUTE_PRICE_TY = 0.5
DOWN_PAYMENT_PRICE_TY = 0.8
LARGE_LOT_AREA_M2 = 1000.0


def _float_value(value, default=0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _fold_text(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = text.replace("Đ", "D").replace("đ", "d").replace("Ä", "D").replace("Ä‘", "d")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn").lower()


def _date_prefix(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _has_positive_feedback(row) -> bool:
    verdict = (row["feedback_verdict"] or "").strip()
    extraction = (row["feedback_extraction_verdict"] or "").strip()
    valuation = (row["feedback_valuation_verdict"] or verdict).strip()
    return valuation in GOOD_VALUATION_VERDICTS and extraction in ("", "all_correct")


def _source_quality_flags(row) -> tuple:
    source = (row["source"] or "").lower()

    if _has_positive_feedback(row):
        return ()

    verdict = (row["feedback_verdict"] or "").strip()
    extraction = (row["feedback_extraction_verdict"] or "").strip()
    valuation = (row["feedback_valuation_verdict"] or verdict).strip()

    flags = list(_valuation_quality_flags(row))
    if source != "guland":
        return tuple(sorted(set(flags)))

    if int(row["suspicious_bait"] or 0):
        flags.append("suspicious_bait")
    if float(row["price_per_m2"] or 0) >= GULAND_EXTREME_PPM2:
        flags.append("extreme_guland_ppm2")

    posted = _date_prefix(row["posted_at"])
    crawled = _date_prefix(row["crawled_at"])
    if posted and crawled and (crawled - posted).days >= GULAND_OLD_POST_DAYS:
        flags.append("old_guland_post")

    if valuation in BAD_VALUATION_VERDICTS or verdict in {"fake_price", "overpriced", "cannot_price"}:
        flags.append("review_bad_valuation")
    if verdict == "bad_data" and extraction and extraction != "all_correct":
        flags.append("review_bad_extraction")

    return tuple(sorted(set(flags)))


def _valuation_quality_flags(row) -> tuple:
    flags = []
    title = row["title"] or ""
    description = row["description"] or ""
    source_id = row["source_id"] or ""
    text = _fold_text(" ".join([title, description]))
    price_ty = _float_value(row["price_ty"])
    ppm2 = _float_value(row["price_per_m2"])
    area_m2 = _float_value(row["area_m2"])
    prop_type = row["property_type"] or ""
    source = (row["source"] or "").lower()
    url_hint = extract_url_hint(row["url"] or "")

    if _fold_text(title).strip() in {"tin test", "test"} or _fold_text(source_id).startswith("test"):
        flags.append("test_artifact")

    masked_price_suffix = r"(?=\s*(?:tr|trieu|lh|lien|alo|zalo)\b|[^a-z0-9]|$)"
    approximate_price = bool(
        re.search(rf"\b\d+\s*(?:t|ty|ti)\s*\d+\s*[x*]+\s*(?:tr|trieu)?{masked_price_suffix}", text)
        or re.search(rf"\b\d+\s*(?:t|ty|ti)\s+\d+\s*[x*]+\s*(?:tr|trieu)?{masked_price_suffix}", text)
    )
    ambiguous_price = has_ambiguous_masked_price(text)
    if approximate_price:
        flags.append("approximate_price_text")
    if ambiguous_price:
        flags.append("ambiguous_price_text")

    discount_as_price = bool(re.search(
        r"(?:re\s*hon|thap\s*hon)\s*(?:thi\s*truong\s*)?\d+(?:[,.]\d+)?\s*(?:ty|ti|trieu|tr|m|k)\b",
        text,
    )) or bool(re.search(
        r"(?:ha|bot|giam(?!\s*con)|giam\s+sau|giam\s+manh)"
        r"(?:\s+\w+){0,3}\s+\d+(?:[,.]\d+)?\s*(?:ty|ti|trieu|tr|m|k)\b",
        text,
    ))
    if price_ty and price_ty <= LOW_ABSOLUTE_PRICE_TY and discount_as_price:
        flags.append("parsed_discount_as_price")

    down_payment = bool(re.search(
        r"(?:dua\s*truoc|tra\s*truoc|dat\s*coc|coc|ngan\s*hang|vietcombank|ho\s*tro\s*tra\s*gop)",
        text,
    ))
    if price_ty and price_ty <= DOWN_PAYMENT_PRICE_TY and down_payment:
        flags.append("down_payment_as_price")

    if prop_type in {"dat_nen", "nha_dat"} and price_ty and price_ty <= LOW_ABSOLUTE_PRICE_TY:
        flags.append("too_low_absolute_price")

    if source == "facebook" and prop_type in {"dat_nen", "nha_dat"} and area_m2 and not _float_value(extract_area(title + "\n" + description)):
        flags.append("missing_area_evidence")

    if prop_type in {"dat_nen", "nha_dat"} and area_m2 >= LARGE_LOT_AREA_M2:
        flags.append("large_lot_model_risk")

    category_text_conflict = bool(re.search(
        r"\b(?:can\s*ho|chung\s*cu|kho\s*xuong|nha\s*xuong)\b",
        text,
    )) and bool(re.search(r"\b(?:dat|lo\s*dat|chua\s*(?:co\s*)?tho\s*cu)\b", text))
    if prop_type in {"dat_nen", "dat_vuon"} and (
        url_hint in {"chung_cu", "kho_xuong"} or category_text_conflict
    ):
        flags.append("source_category_conflict")

    if prop_type in {"dat_nen", "dat_vuon", "nha_dat", "nha_tro"} and is_multi_lot_listing(title, description):
        flags.append("multi_lot_listing")

    description_area_m2 = _float_value(extract_area(description))
    if area_m2 and description_area_m2 and prop_type in {"dat_nen", "nha_dat"}:
        bigger = max(area_m2, description_area_m2)
        smaller = min(area_m2, description_area_m2)
        if smaller > 0 and bigger / smaller >= 1.8:
            flags.append("area_dimension_conflict")

    if prop_type in {"dat_nen", "nha_dat"} and ppm2 and ppm2 < 1.0:
        flags.append("too_low_absolute_price")

    return tuple(sorted(set(flags)))


def _ascii_signature(text: str) -> str:
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower().replace("đ", "d")
    text = re.sub(r"\b\d+(?:[,.]\d+)?\b", " ", text)
    tokens = re.findall(r"[a-z]+", text)
    return " ".join(tokens[:8])


def _guland_cluster_key(row):
    if (row["source"] or "").lower() != "guland":
        return None
    if _has_positive_feedback(row):
        return None
    title_sig = _ascii_signature(row["title"] or row["description"] or "")
    if not title_sig:
        return None
    try:
        area_bucket = int(round(float(row["area_m2"] or 0)))
        price_bucket = round(float(row["price_ty"] or 0), 1)
    except Exception:
        return None
    if area_bucket <= 0 or price_bucket <= 0:
        return None
    return (
        row["ward"] or "unknown",
        row["property_type"] or "khac",
        area_bucket,
        price_bucket,
        title_sig,
    )


def _guland_cluster_flag_map(rows) -> dict:
    unique_rows = {}
    for row in rows:
        unique_rows[row["id"]] = row

    groups = {}
    for row in unique_rows.values():
        key = _guland_cluster_key(row)
        if key:
            groups.setdefault(key, []).append(row["id"])

    flagged = {}
    for ids in groups.values():
        if len(ids) >= GULAND_CLUSTER_MIN_SIZE:
            for listing_id in ids:
                flagged.setdefault(listing_id, set()).add("guland_cluster_flood")
    return flagged


def populate_content_hashes(conn) -> int:
    """Backfill listings.content_hash từ ward/property_type/price/area/title.
    Idempotent — chỉ UPDATE khi hash mới khác hash cũ. Trả số rows updated."""
    rows = conn.execute("""
        SELECT id, ward, property_type, price_ty, area_m2, title, content_hash
          FROM listings
    """).fetchall()
    updates = []
    for r in rows:
        h = compute_content_hash(r["ward"], r["property_type"],
                                 r["price_ty"], r["area_m2"], r["title"])
        if h != r["content_hash"]:
            updates.append((h, r["id"]))
    if updates:
        conn.executemany("UPDATE listings SET content_hash=? WHERE id=?", updates)
        conn.commit()
    return len(updates)


def _batch_save_valuations(results, id_map):
    """
    OPTIMIZATION: Gộp toàn bộ valuation insert vào 1 transaction thay vì N transaction.
    Giảm ~200x số commit (241 records → 1 commit).
    """
    with get_conn() as conn:
        for r in results:
            listing = id_map.get(r.listing_id)
            conn.execute("""
                INSERT INTO valuation_results
                    (listing_id, fair_ppm2, actual_ppm2, mos_pct,
                     is_signal, is_outlier, outlier_direction, outlier_sigma,
                     segment, n_segment, signal_score, road_tier,
                     source_quality_flags, source_quality_recheck,
                     legal_status, trust_tier, trust_score, legal_flags)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                r.listing_id, r.price_per_m2_fair, r.price_per_m2_actual,
                r.discount_pct, int(r.is_signal), int(r.is_outlier),
                r.outlier_direction or None, r.outlier_sigma or None,
                f"{r.area}|{r.property_type}", r.segment_n,
                r.signal_score, listing.road_tier if listing else 0,
                ",".join(r.source_quality_flags or ()),
                int(bool(r.source_quality_recheck)),
                r.legal_status,
                r.trust_tier,
                r.trust_score,
                ",".join(r.legal_flags or ()),
            ))
            conn.execute("""
                UPDATE listings
                SET is_outlier=?, outlier_direction=?, outlier_sigma=?
                WHERE id=?
            """, (int(r.is_outlier), r.outlier_direction or None,
                  r.outlier_sigma or None, r.listing_id))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def reprocess_listings(source: str = None, since: str = None, full: bool = False, raw_ids: list = None) -> dict:
    """
    Bước 1: raw_listings → listings (normalize + upsert).
    Trả về stats và danh sách ID các listing vừa được xử lý.
    """
    raws = get_raw_for_reprocess(source=source, since=since, incremental=not full and raw_ids is None, raw_ids=raw_ids)
    logger.info(
        f"Reprocess: {len(raws)} raw records "
        f"(source={source}, since={since}, full={full}, raw_ids={len(raw_ids or [])})"
    )

    run_id = start_crawl_run(f"reprocess:{source or 'all'}", "all")
    stats  = {"fetched": len(raws), "new": 0, "updated": 0, "skipped": 0, "price_dropped": 0, "processed_ids": []}
    seen_urls = set()

    for raw in raws:
        try:
            raw_data = _parse_raw_json(raw["raw_json"])
            if not raw_data:
                stats["skipped"] += 1
                continue

            raw_data["area_name"] = raw_data.get("area_name") or raw_data.get("area", "")
            raw_data["crawled_at"] = raw.get("crawled_at", "")
            rec = normalize_record(raw_data)
            if not rec or not rec.get("url"):
                stats["skipped"] += 1
                continue

            if rec["url"] in seen_urls:
                stats["skipped"] += 1
                continue
            seen_urls.add(rec["url"])

            rec["raw_id"]   = raw["id"]
            rec["source"]   = raw["source"]
            rec["source_id"] = raw.get("source_id") or rec.get("source_id", "")
            if full or raw_ids is not None:
                rec["_clear_stale_measurements"] = True

            with get_conn() as conn:
                blocked, _ = is_phone_blacklisted(conn, rec.get("contact_phone"))
            if blocked:
                stats["skipped"] += 1
                continue

            listing_id, is_new = upsert_listing(rec, crawl_run_id=run_id)
            stats["processed_ids"].append(listing_id)

            if is_new:
                stats["new"] += 1
            else:
                stats["updated"] += 1

            img_urls = rec.get("img_urls") or []
            if img_urls:
                insert_images(listing_id, img_urls)

        except Exception as e:
            logger.error(f"Reprocess error raw_id={raw.get('id')}: {e}")
            stats["skipped"] += 1

    with get_conn() as conn:
        stats["content_hash_updated"] = populate_content_hashes(conn)

    finish_crawl_run(run_id, stats)
    logger.info(f"Listings reprocess done: {stats['new']} new, {stats['updated']} updated, {stats['skipped']} skipped")
    return stats


def reprocess_valuation(incremental_ids: list = None, training_ids: list = None) -> dict:
    """
    Bước 2: listings → valuation_results (chạy lại engine).
    Nếu incremental_ids có giá trị, chỉ tính định giá cho các ID đó.
    """
    from analytics.valuation import ValuationEngine, Listing
    from datetime import date

    if incremental_ids is not None and not incremental_ids:
        logger.info("Valuation: khong co incremental listing nao, bo qua valuation.")
        return {"total": 0, "signals": 0, "outliers": 0}

    with get_conn() as conn:
        if incremental_ids is None:
            # Full run: Xóa valuation cũ để tính lại sạch
            logger.info("Valuation: Full reprocess, clearing old results...")
            conn.execute("DELETE FROM valuation_results")
            
        # 1. Lấy dữ liệu để TRAIN model (Fit). Chỉ lấy 30k tin gần nhất để đảm bảo hiệu năng và độ tươi.
        # Với 500k tin, việc load toàn bộ là không cần thiết vì có TIME_DECAY.
        valuation_select = """
            SELECT l.id, l.title, l.description,
                   l.area, l.ward, l.property_type, l.tx_type, l.price_per_m2, l.price_ty,
                   l.area_m2, l.frontage_m, l.depth_m, l.road_type, l.road_tier,
                   l.tho_cu_m2, l.tho_cu_ratio,
                   l.has_so, l.is_hot, l.price_dropped, l.crawled_at, l.posted_at,
                   l.url, l.contact_phone, l.source, l.source_id, l.suspicious_bait,
                   l.review_hidden, l.duplicate_of_id,
                   COALESCE(lv.status, 'unverified') AS legal_status,
                   COALESCE(lv.trust_tier, 'candidate_signal') AS trust_tier,
                   COALESCE(lv.confidence_score, 0) AS trust_score,
                   COALESCE(lv.conflict_flags, '') AS legal_flags,
                   f.verdict AS feedback_verdict,
                   f.extraction_verdict AS feedback_extraction_verdict,
                   f.valuation_verdict AS feedback_valuation_verdict
            FROM listings l
            LEFT JOIN legal_verifications lv ON lv.listing_id = l.id
            LEFT JOIN ai_training_feedback f ON f.id = (
                SELECT id FROM ai_training_feedback
                WHERE listing_id = l.id
                ORDER BY created_at DESC
                LIMIT 1
            )
        """
        visible_or_recheckable = """
              AND (
                    COALESCE(l.review_hidden,0) = 0
                 OR f.verdict = 'bad_data'
              )
        """

        if training_ids:
            train_placeholders = ",".join(["?"] * len(training_ids))
            train_rows = conn.execute(f"""
                {valuation_select}
                WHERE l.id IN ({train_placeholders})
                  AND l.price_per_m2 IS NOT NULL AND l.price_per_m2 > 0
                  AND COALESCE(l.probably_sold,0) = 0
                  AND COALESCE(l.is_blacklisted,0) = 0
                  AND COALESCE(l.review_hidden,0) = 0
            """, training_ids).fetchall()
        else:
            train_rows = conn.execute(f"""
                {valuation_select}
                WHERE l.price_per_m2 IS NOT NULL AND l.price_per_m2 > 0
                  AND COALESCE(l.probably_sold,0) = 0
                  AND COALESCE(l.is_blacklisted,0) = 0
                  AND COALESCE(l.review_hidden,0) = 0
                ORDER BY l.id DESC
                LIMIT 30000
            """).fetchall()

        # 2. Lấy dữ liệu để ĐỊNH GIÁ (Valuate).
        if incremental_ids is not None:
            # Chỉ định giá những tin vừa mới xử lý
            placeholders = ",".join(["?"] * len(incremental_ids))
            valuate_rows = conn.execute(f"""
                {valuation_select}
                WHERE l.id IN ({placeholders})
                  AND l.price_per_m2 IS NOT NULL AND l.price_per_m2 > 0
                  AND COALESCE(l.probably_sold,0) = 0
                  AND COALESCE(l.is_blacklisted,0) = 0
                  {visible_or_recheckable}
            """, incremental_ids).fetchall()
        else:
            valuate_rows = conn.execute(f"""
                {valuation_select}
                WHERE l.price_per_m2 IS NOT NULL AND l.price_per_m2 > 0
                  AND COALESCE(l.probably_sold,0) = 0
                  AND COALESCE(l.is_blacklisted,0) = 0
                  {visible_or_recheckable}
                ORDER BY l.id DESC
            """).fetchall()

    cluster_flags = _guland_cluster_flag_map(list(train_rows) + list(valuate_rows))

    def row_to_listing(row):
        flags = tuple(sorted(set(_source_quality_flags(row)) | cluster_flags.get(row["id"], set())))
        crawled = date.fromisoformat(row["crawled_at"][:10]) if row["crawled_at"] else None
        posted = date.fromisoformat(row["posted_at"][:10]) if row["posted_at"] else None
        return Listing(
            id           = row["id"],
            area         = row["area"] or "unknown",
            ward         = row["ward"] or "unknown",
            property_type= row["property_type"] or "khac",
            tx_type      = (row["tx_type"] or "ban").strip().lower().replace("bán", "ban").replace("thuê", "thue"),
            price_per_m2 = float(row["price_per_m2"]),
            price_total  = float(row["price_ty"] or 0),
            area_m2      = float(row["area_m2"] or 0),
            frontage_m   = float(row["frontage_m"]) if row["frontage_m"] else None,
            depth_m      = float(row["depth_m"])    if row["depth_m"]    else None,
            tho_cu_m2    = float(row["tho_cu_m2"]) if row["tho_cu_m2"] else None,
            tho_cu_ratio = float(row["tho_cu_ratio"]) if row["tho_cu_ratio"] else None,
            road_type    = row["road_type"] or "unknown",
            road_tier     = int(row["road_tier"] or 0),
            has_so        = bool(row["has_so"]),
            is_hot        = bool(row["is_hot"]),
            price_dropped = bool(row["price_dropped"]),
            crawled_at    = crawled,
            posted_at     = posted,
            url           = row["url"] or "",
            contact_phone = row["contact_phone"] or "",
            source        = row["source"] or "",
            duplicate_of_id = int(row["duplicate_of_id"]) if row["duplicate_of_id"] else None,
            source_quality_flags = flags,
            exclude_from_baseline = bool(flags),
            positive_feedback = _has_positive_feedback(row),
            legal_status = row["legal_status"] or "unverified",
            trust_tier = row["trust_tier"] or "candidate_signal",
            trust_score = int(row["trust_score"] or 0),
            legal_flags = tuple(x for x in (row["legal_flags"] or "").split(",") if x),
            review_recheck_candidate = bool(
                row["review_hidden"]
                and row["feedback_verdict"] == "bad_data"
                and row["feedback_extraction_verdict"] in {
                    "wrong_area",
                    "wrong_price",
                    "wrong_property_type",
                    "wrong_road",
                    "wrong_ward",
                }
            ),
        )

    train_listings = []
    for r in train_rows:
        try: train_listings.append(row_to_listing(r))
        except: pass

    valuate_listings = []
    id_map = {}
    for r in valuate_rows:
        try:
            l = row_to_listing(r)
            valuate_listings.append(l)
            id_map[l.id] = l
        except: pass

    logger.info(f"Valuation: fitting engine on {len(train_listings)} listings, valuating {len(valuate_listings)}...")
    engine = ValuationEngine()
    engine.fit(train_listings)
    
    results = engine.valuate_batch(valuate_listings)

    # Nếu incremental, ta cần xóa valuation cũ của các ID này trước khi chèn mới (tránh trùng)
    if incremental_ids:
        with get_conn() as conn:
            placeholders = ",".join(["?"] * len(incremental_ids))
            conn.execute(f"DELETE FROM valuation_results WHERE listing_id IN ({placeholders})", incremental_ids)
            conn.execute(f"UPDATE listings SET is_outlier=0 WHERE id IN ({placeholders})", incremental_ids)

    _batch_save_valuations(results, id_map)
    n_signal  = sum(1 for r in results if r.is_signal)
    n_outlier = sum(1 for r in results if r.is_outlier)

    stats = {
        "total":    len(results),
        "signals":  n_signal,
        "outliers": n_outlier,
    }
    logger.info(f"Valuation done: {stats}")
    return stats


def enrich_listings_with_gemini(limit=50):
    """
    Bước 3: Làm giàu dữ liệu bằng Gemini (Hybrid Layer).
    - Fix missing ward/road_type.
    - Double check hot deals.
    """
    from cleansing.gemini_enricher import GeminiEnricher
    enricher = GeminiEnricher()
    if not enricher.model:
        logger.warning("Gemini API Key missing, skipping enrichment.")
        return 0

    from analytics.valuation import ValuationEngine, Listing
    from datetime import date

    with get_conn() as conn:
        # Lấy tin thiếu thông tin cơ bản
        rows = conn.execute("""
            SELECT id, title, description FROM listings
            WHERE (ward = 'unknown' OR road_type = 'unknown' OR road_type IS NULL)
               AND llm_verified = 0
            LIMIT ?
        """, (limit,)).fetchall()
        
        # Lấy các deal ngộp cần xác minh lại
        hot_rows = conn.execute("""
            SELECT l.id, l.title, l.description FROM listings l
            JOIN valuation_results v ON l.id = v.listing_id
            WHERE v.is_signal = 1 AND l.llm_verified = 0
            LIMIT ?
        """, (limit,)).fetchall()
        
        # Gộp và loại trùng
        to_process = {r['id']: r for r in list(rows) + list(hot_rows)}
    
    if not to_process:
        return 0

    logger.info(f"Gemini Enrichment: Processing {len(to_process)} listings...")
    count = 0
    import time
    for lid, row in to_process.items():
        res = enricher.enrich_listing(row['title'], row['description'])
        if not res:
            # Nghỉ một chút nếu lỗi (có thể do rate limit)
            time.sleep(5)
            continue
        
        # Cập nhật DB
        with get_conn() as conn:
            p = res.get('price_ty')
            a = res.get('area_m2')
            ppm2 = None
            if p and a and a > 0:
                ppm2 = round((p * 1000) / a, 3)

            conn.execute("""
                UPDATE listings SET
                    ward = COALESCE(?, ward),
                    road_type = COALESCE(?, road_type),
                    price_ty = COALESCE(?, price_ty),
                    area_m2 = COALESCE(?, area_m2),
                    price_per_m2 = COALESCE(?, price_per_m2),
                    llm_verified = 1,
                    llm_notes = ?
                WHERE id = ?
            """, (
                res.get('ward'), res.get('road_type'),
                p, a, ppm2,
                res.get('reason', ''),
                lid
            ))
            count += 1
        
        # Nghỉ để tránh rate limit (Free tier: 15 RPM)
        time.sleep(4)
    
    logger.info(f"Gemini Enrichment: Done {count} listings.")
    return count


def _parse_raw_json(raw_json_str: str) -> dict:
    import json
    try:
        return json.loads(raw_json_str)
    except Exception:
        return {}


def run_full_reprocess(source: str = None, since: str = None, use_gemini: bool = False, full: bool = False, raw_ids: list = None):
    with advisory_lock("reprocess"):
        return _run_full_reprocess(source=source, since=since, use_gemini=use_gemini, full=full, raw_ids=raw_ids)


def _run_full_reprocess(source: str = None, since: str = None, use_gemini: bool = False, full: bool = False, raw_ids: list = None):
    """Chạy pipeline reprocess: raw → listings → valuation."""
    logger.info("=" * 55)
    logger.info(f"{'FULL' if full else 'INCREMENTAL'} REPROCESS START")

    listing_stats = reprocess_listings(source=source, since=since, full=full, raw_ids=raw_ids)
    processed_ids = listing_stats.get("processed_ids", [])

    from config.settings import LEGAL_IMAGE_EVIDENCE_ENABLED
    if LEGAL_IMAGE_EVIDENCE_ENABLED:
        from cleansing.legal_verification import refresh_legal_verifications
        if full:
            legal_stats = refresh_legal_verifications(source=source, apply=True)
        else:
            legal_stats = {"apply": True, "scanned": 0, "updated": 0, "statuses": {}, "trust_tiers": {}}
            for lid in processed_ids:
                one = refresh_legal_verifications(listing_id=lid, apply=True)
                legal_stats["scanned"] += one.get("scanned", 0)
                legal_stats["updated"] += one.get("updated", 0)
                for key, val in one.get("statuses", {}).items():
                    legal_stats["statuses"][key] = legal_stats["statuses"].get(key, 0) + val
                for key, val in one.get("trust_tiers", {}).items():
                    legal_stats["trust_tiers"][key] = legal_stats["trust_tiers"].get(key, 0) + val
    else:
        legal_stats = {
            "apply": False,
            "scanned": 0,
            "updated": 0,
            "statuses": {"disabled": 1},
            "trust_tiers": {},
        }
    
    # Valuation: Nếu full=False, chỉ định giá các tin vừa mới xử lý
    val_stats = reprocess_valuation(incremental_ids=None if full else processed_ids)

    if use_gemini:
        n_enriched = enrich_listings_with_gemini(limit=50)
        if n_enriched > 0:
            logger.info("Re-valuating after Gemini enrichment...")
            val_stats = reprocess_valuation()

    # Price drops — BUG FIX: chưa từng được gọi trong pipeline
    from analytics.market_trend import compute_weekly_trend, compute_monthly_trend, compute_daily_trend, detect_price_drops
    # Logic giá trị: lifecycle feedback — listing biến mất nhanh = deal khớp
    from analytics.lifecycle import sweep_delisted, backfill_first_seen
    with get_conn() as conn:
        backfill_first_seen(conn)               # một lần cho DB cũ (idempotent)
        n_drops       = detect_price_drops(conn)
        delisted_list = sweep_delisted(conn)
    n_delisted      = len(delisted_list)
    n_likely_sold   = sum(1 for d in delisted_list if d.get("likely_sold"))

    # Market weekly, monthly, daily
    with get_conn() as conn:
        conn.execute("DELETE FROM market_weekly")
        compute_weekly_trend(conn)
        compute_monthly_trend(conn)
        compute_daily_trend(conn)
    logger.info("Market trends (weekly, monthly, daily) updated")

    # Cross-source dedup
    from cleansing.dedup import flag_duplicates_in_db
    with get_conn() as conn:
        dedup_stats = flag_duplicates_in_db(conn)

    # Content hash backfill (alert filter dùng để loại repost cùng nội dung khác URL)
    with get_conn() as conn:
        n_hashes = populate_content_hashes(conn)

    logger.info("FULL REPROCESS DONE")
    logger.info(f"  Listings : {listing_stats}")
    logger.info(f"  Legal    : {legal_stats}")
    logger.info(f"  Valuation: {val_stats}")
    logger.info(f"  PriceDrop: {n_drops} new drops detected")
    logger.info(f"  Lifecycle: {n_delisted} delisted ({n_likely_sold} likely sold <72h)")
    logger.info(f"  Dedup    : {dedup_stats['dup_groups']} groups | {dedup_stats['flagged']} flagged | {dedup_stats['unique_lots']} unique lots")
    logger.info(f"  ContentHash: {n_hashes} rows updated")
    logger.info("=" * 55)

    return {"listings": listing_stats, "legal": legal_stats, "valuation": val_stats,
            "dedup": dedup_stats, "price_drops": n_drops,
            "lifecycle": {"delisted": n_delisted, "likely_sold": n_likely_sold}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reprocess từ raw_listings")
    parser.add_argument("--source", help="Filter theo source (batdongsan/guland/facebook)")
    parser.add_argument("--since",  help="Chỉ reprocess raw crawled từ ngày này (YYYY-MM-DD)")
    parser.add_argument("--listings-only", action="store_true", help="Chỉ reprocess listings, không valuation")
    parser.add_argument("--valuation-only", action="store_true", help="Chỉ chạy lại valuation")
    parser.add_argument("--full",           action="store_true", help="Chạy toàn bộ dữ liệu (mặc định là incremental)")
    parser.add_argument("--gemini",        action="store_true", help="Bật làm giàu dữ liệu bằng Gemini")
    args = parser.parse_args()

    init_schema()

    if args.valuation_only:
        reprocess_valuation()
    elif args.listings_only:
        reprocess_listings(source=args.source, since=args.since, full=args.full)
    else:
        run_full_reprocess(source=args.source, since=args.since, use_gemini=args.gemini, full=args.full)
