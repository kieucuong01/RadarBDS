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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.database_sqlite import (
    init_schema, get_conn, get_raw_for_reprocess,
    upsert_listing, insert_images, update_listing_outlier,
    save_valuation_result, start_crawl_run, finish_crawl_run,
)
from cleansing.normalizer import normalize_record, compute_content_hash


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
                     segment, n_segment, signal_score, road_tier)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                r.listing_id, r.price_per_m2_fair, r.price_per_m2_actual,
                r.discount_pct, int(r.is_signal), int(r.is_outlier),
                r.outlier_direction or None, r.outlier_sigma or None,
                f"{r.area}|{r.property_type}", r.segment_n,
                r.signal_score, listing.road_tier if listing else 0,
            ))
            conn.execute("""
                UPDATE listings
                SET is_outlier=?, outlier_direction=?, outlier_sigma=?
                WHERE id=?
            """, (int(r.is_outlier), r.outlier_direction or None,
                  r.outlier_sigma or None, r.listing_id))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def reprocess_listings(source: str = None, since: str = None, full: bool = False) -> dict:
    """
    Bước 1: raw_listings → listings (normalize + upsert).
    Trả về stats và danh sách ID các listing vừa được xử lý.
    """
    raws = get_raw_for_reprocess(source=source, since=since, incremental=not full)
    logger.info(f"Reprocess: {len(raws)} raw records (source={source}, since={since}, full={full})")

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


def reprocess_valuation(incremental_ids: list = None) -> dict:
    """
    Bước 2: listings → valuation_results (chạy lại engine).
    Nếu incremental_ids có giá trị, chỉ tính định giá cho các ID đó.
    """
    from analytics.valuation import ValuationEngine, Listing
    from datetime import date

    with get_conn() as conn:
        if not incremental_ids:
            # Full run: Xóa valuation cũ để tính lại sạch
            logger.info("Valuation: Full reprocess, clearing old results...")
            conn.execute("DELETE FROM valuation_results")
            
        # 1. Lấy dữ liệu để TRAIN model (Fit). Chỉ lấy 30k tin gần nhất để đảm bảo hiệu năng và độ tươi.
        # Với 500k tin, việc load toàn bộ là không cần thiết vì có TIME_DECAY.
        train_rows = conn.execute("""
            SELECT id, area, ward, property_type, tx_type, price_per_m2, price_ty,
                   area_m2, frontage_m, depth_m, road_width_m, road_type, road_tier,
                   has_so, is_hot, price_dropped, crawled_at, url, contact_phone
            FROM listings
            WHERE price_per_m2 IS NOT NULL AND price_per_m2 > 0
              AND probably_sold = 0
            ORDER BY id DESC
            LIMIT 30000
        """).fetchall()

        # 2. Lấy dữ liệu để ĐỊNH GIÁ (Valuate).
        if incremental_ids:
            # Chỉ định giá những tin vừa mới xử lý
            placeholders = ",".join(["?"] * len(incremental_ids))
            valuate_rows = conn.execute(f"""
                SELECT id, area, ward, property_type, tx_type, price_per_m2, price_ty,
                       area_m2, frontage_m, depth_m, road_width_m, road_type, road_tier,
                       has_so, is_hot, price_dropped, crawled_at, url, contact_phone
                FROM listings
                WHERE id IN ({placeholders})
                  AND price_per_m2 IS NOT NULL AND price_per_m2 > 0
            """, incremental_ids).fetchall()
        else:
            valuate_rows = train_rows # Full run thì định giá chính mảng train luôn (hoặc toàn bộ)

    def row_to_listing(row):
        crawled = date.fromisoformat(row["crawled_at"][:10]) if row["crawled_at"] else None
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
            road_width_m = float(row["road_width_m"]) if row["road_width_m"] else None,
            road_type    = row["road_type"] or "unknown",
            road_tier     = int(row["road_tier"] or 0),
            has_so        = bool(row["has_so"]),
            is_hot        = bool(row["is_hot"]),
            price_dropped = bool(row["price_dropped"]),
            crawled_at    = crawled,
            url           = row["url"] or "",
            contact_phone = row["contact_phone"] or "",
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
                    road_width_m = COALESCE(?, road_width_m),
                    price_ty = COALESCE(?, price_ty),
                    area_m2 = COALESCE(?, area_m2),
                    price_per_m2 = COALESCE(?, price_per_m2),
                    llm_verified = 1,
                    llm_notes = ?
                WHERE id = ?
            """, (
                res.get('ward'), res.get('road_type'), res.get('road_width_m'),
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


GROQ_BATCH_SIZE       = 10
GROQ_RPM_DELAY        = 6.0    # stay within 6000 TPM free tier
GROQ_RETRY_WAIT       = 65     # wait sau 429 (1 phút + buffer)
GROQ_FIELDS_BATCH_SIZE = 5     # full extraction nặng hơn → batch nhỏ hơn
GROQ_FULL_DELAY        = 8.0   # delay giữa full-extraction batches

_VALID_ROAD_TYPES = {
    'hem_xe_may', 'hem_ba_gac', 'hem_xe_hoi',
    'duong_nhua', 'be_tong', 'duong_dat', 'mat_tien_kinh_doanh',
}


def enrich_listings_with_groq(limit: int = 600, ward: str = None) -> int:
    """
    Enrich hard listings (road_tier=0) bằng Groq Llama 3.3 70B.
    Chỉ gọi Groq cho tin mà regex đã thất bại — hybrid approach.
    ward: nếu truyền vào, chỉ enrich listings thuộc phường đó.
    """
    import time
    import json as _json
    from cleansing.groq_enricher import GroqEnricher

    enricher = GroqEnricher()
    if not enricher.enabled:
        logger.warning("GROQ_API_KEY missing — bỏ qua Groq enrichment.")
        return 0

    with get_conn() as conn:
        if ward:
            rows = conn.execute("""
                SELECT id, title, description FROM listings
                WHERE road_tier = 0
                  AND llm_verified = 0
                  AND ward = ?
                ORDER BY id
                LIMIT ?
            """, (ward, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, title, description FROM listings
                WHERE road_tier = 0
                  AND llm_verified = 0
                ORDER BY id
                LIMIT ?
            """, (limit,)).fetchall()

    if not rows:
        logger.info("Groq: không có listing nào cần enrich.")
        return 0

    total = len(rows)
    logger.info(f"Groq Enrichment: {total} hard listings cần xử lý (batch={GROQ_BATCH_SIZE})...")
    done = 0
    chunks = [rows[i:i + GROQ_BATCH_SIZE] for i in range(0, total, GROQ_BATCH_SIZE)]

    for i, chunk in enumerate(chunks, 1):
        batch = [
            {"id": r["id"], "title": r["title"] or "",
             "description": (r["description"] or "")[:200]}  # truncate: road info ở đầu, tiết kiệm TPM
            for r in chunk
        ]

        results = {}
        for attempt in range(2):
            try:
                results = enricher.enrich_batch(batch)
                break
            except Exception as exc:
                if "429" in str(exc) and attempt == 0:
                    logger.warning(f"Rate limit 429 — chờ {GROQ_RETRY_WAIT}s rồi retry...")
                    time.sleep(GROQ_RETRY_WAIT)
                else:
                    logger.error(f"Batch {i} lỗi: {exc}")
                    break

        with get_conn() as conn:
            for row in chunk:
                res = results.get(row["id"], {})
                if not res:
                    # Không đánh verified khi batch lỗi hoàn toàn (results={}) — retry lần sau
                    if results:  # results có data nhưng id này không có → Groq bỏ qua thật
                        conn.execute("UPDATE listings SET llm_verified=1 WHERE id=?", (row["id"],))
                    continue
                # has_so: Groq mặc định true; chỉ false khi bài ghi rõ không sổ/vi bằng
                hs = res.get("has_so")
                has_so_val = 0 if hs is False else 1
                road_tier_val = res.get("road_tier")   # int 1–4 hoặc None
                conn.execute("""
                    UPDATE listings SET
                        ward         = COALESCE(?, ward),
                        road_type    = COALESCE(?, road_type),
                        road_width_m = COALESCE(?, road_width_m),
                        has_so       = COALESCE(?, has_so),
                        road_tier    = COALESCE(?, road_tier),
                        llm_verified = 1,
                        llm_notes    = ?
                    WHERE id = ?
                """, (
                    res.get("ward") or None,
                    res.get("road_type") or None,
                    res.get("road_width_m") or None,
                    has_so_val,
                    road_tier_val,
                    _json.dumps(res, ensure_ascii=False),
                    row["id"],
                ))
            done += len(chunk)

        logger.info(f"  Batch {i}/{len(chunks)}: {done}/{total} done")
        if i < len(chunks):
            time.sleep(GROQ_RPM_DELAY)

    logger.info(f"Groq Enrichment: hoàn tất {done}/{total} listings.")
    return done


def enrich_frontage_with_groq(limit: int = 500, ward: str = None) -> int:
    """
    Enrich frontage_m và road_width_m cho listings còn NULL bằng Groq full extraction.
    Chỉ ghi đè 2 fields này — không đụng fields khác.
    """
    import time
    import json as _json
    from cleansing.groq_enricher import GroqEnricher

    enricher = GroqEnricher()
    if not enricher.enabled:
        logger.warning("GROQ_API_KEY missing — bỏ qua frontage enrichment.")
        return 0

    with get_conn() as conn:
        q = "SELECT id, title, description FROM listings WHERE frontage_m IS NULL"
        params = []
        if ward:
            q += " AND ward = ?"
            params.append(ward)
        q += " ORDER BY id LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()

    if not rows:
        logger.info("Groq frontage: không có listing nào cần enrich.")
        return 0

    total = len(rows)
    logger.info(f"Groq frontage enrich: {total} listings (batch={GROQ_FIELDS_BATCH_SIZE})...")
    done = 0
    chunks = [rows[i:i + GROQ_FIELDS_BATCH_SIZE] for i in range(0, total, GROQ_FIELDS_BATCH_SIZE)]

    for i, chunk in enumerate(chunks, 1):
        batch = [
            {"id": r["id"], "title": r["title"] or "",
             "description": (r["description"] or "")[:300]}
            for r in chunk
        ]
        results = {}
        for attempt in range(2):
            try:
                results = enricher.enrich_full_batch(batch)
                break
            except Exception as exc:
                if "429" in str(exc) and attempt == 0:
                    logger.warning(f"Rate limit 429 — chờ {GROQ_RETRY_WAIT}s...")
                    time.sleep(GROQ_RETRY_WAIT)
                else:
                    logger.error(f"Batch {i} lỗi: {exc}")
                    break

        with get_conn() as conn:
            for row in chunk:
                res = results.get(row["id"], {})
                if not res:
                    continue
                frontage    = res.get("frontage_m")    or None
                road_width  = res.get("road_width_m")  or None
                if frontage is None and road_width is None:
                    continue
                conn.execute("""
                    UPDATE listings SET
                        frontage_m   = COALESCE(?, frontage_m),
                        road_width_m = COALESCE(?, road_width_m)
                    WHERE id = ?
                """, (frontage, road_width, row["id"]))
            done += len(chunk)

        logger.info(f"  Batch {i}/{len(chunks)}: {done}/{total} done")
        if i < len(chunks):
            time.sleep(GROQ_FULL_DELAY)

    logger.info(f"Groq frontage enrich: hoàn tất {done} listings.")
    return done


def verify_signals_with_groq(limit: int = 300, ward: str = None) -> int:
    """
    Groq verify toàn bộ fields cho signal listings (is_signal=1, llm_verified=0).
    Cập nhật tất cả trường quan trọng, tính lại price_per_m2, rồi re-valuate.
    """
    import time
    import json as _json
    from cleansing.groq_enricher import GroqEnricher

    enricher = GroqEnricher()
    if not enricher.enabled:
        logger.warning("GROQ_API_KEY missing — bỏ qua signal verification.")
        return 0

    with get_conn() as conn:
        q = """
            SELECT l.id, l.title, l.description FROM listings l
            JOIN valuation_results v ON l.id = v.listing_id
            WHERE v.is_signal = 1
              AND l.llm_verified = 0
        """
        params = []
        if ward:
            q += " AND l.ward = ?"
            params.append(ward)
        q += " ORDER BY v.signal_score DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()

    if not rows:
        logger.info("Groq signal verify: không có signal listing nào cần verify.")
        return 0

    total = len(rows)
    logger.info(f"Groq signal verify: {total} signal listings (batch={GROQ_FIELDS_BATCH_SIZE})...")
    done = 0
    chunks = [rows[i:i + GROQ_FIELDS_BATCH_SIZE] for i in range(0, total, GROQ_FIELDS_BATCH_SIZE)]

    for i, chunk in enumerate(chunks, 1):
        batch = [
            {"id": r["id"], "title": r["title"] or "",
             "description": (r["description"] or "")[:300]}
            for r in chunk
        ]
        results = {}
        for attempt in range(2):
            try:
                results = enricher.enrich_full_batch(batch)
                break
            except Exception as exc:
                if "429" in str(exc) and attempt == 0:
                    logger.warning(f"Rate limit 429 — chờ {GROQ_RETRY_WAIT}s...")
                    time.sleep(GROQ_RETRY_WAIT)
                else:
                    logger.error(f"Batch {i} lỗi: {exc}")
                    break

        with get_conn() as conn:
            for row in chunk:
                res = results.get(row["id"], {})
                if not res:
                    # batch thành công nhưng listing này không có kết quả → mark verified
                    if results:
                        conn.execute("UPDATE listings SET llm_verified=1 WHERE id=?", (row["id"],))
                    continue

                p = res.get("price_ty")
                a = res.get("area_m2")
                ppm2 = None
                if p and a and float(a) > 0:
                    ppm2 = round((float(p) * 1000) / float(a), 3)

                road_type_val = res.get("road_type")
                if road_type_val not in _VALID_ROAD_TYPES:
                    road_type_val = None  # reject hallucinated enum values

                hs = res.get("has_so")
                has_so_val = 0 if hs is False else (1 if hs is True else None)

                conn.execute("""
                    UPDATE listings SET
                        price_ty      = COALESCE(?, price_ty),
                        area_m2       = COALESCE(?, area_m2),
                        price_per_m2  = COALESCE(?, price_per_m2),
                        frontage_m    = COALESCE(?, frontage_m),
                        road_tier     = COALESCE(?, road_tier),
                        road_type     = COALESCE(?, road_type),
                        road_width_m  = COALESCE(?, road_width_m),
                        has_so        = COALESCE(?, has_so),
                        property_type = COALESCE(?, property_type),
                        ward          = COALESCE(?, ward),
                        llm_verified  = 1,
                        llm_notes     = ?
                    WHERE id = ?
                """, (
                    p or None,
                    a or None,
                    ppm2,
                    res.get("frontage_m") or None,
                    res.get("road_tier")  or None,
                    road_type_val,
                    res.get("road_width_m") or None,
                    has_so_val,
                    res.get("property_type") or None,
                    res.get("ward") or None,
                    _json.dumps(res, ensure_ascii=False),
                    row["id"],
                ))
            done += len(chunk)

        logger.info(f"  Batch {i}/{len(chunks)}: {done}/{total} done")
        if i < len(chunks):
            time.sleep(GROQ_FULL_DELAY)

    logger.info(f"Groq signal verify: hoàn tất {done} listings. Re-valuating...")
    if done > 0:
        reprocess_valuation()
    return done


def run_full_reprocess(source: str = None, since: str = None, use_gemini: bool = False, use_groq: bool = False, full: bool = False):
    """Chạy pipeline reprocess: raw → listings → valuation."""
    logger.info("=" * 55)
    logger.info(f"{'FULL' if full else 'INCREMENTAL'} REPROCESS START")

    listing_stats = reprocess_listings(source=source, since=since, full=full)
    processed_ids = listing_stats.get("processed_ids", [])
    
    # Valuation: Nếu full=False, chỉ định giá các tin vừa mới xử lý
    val_stats = reprocess_valuation(incremental_ids=None if full else processed_ids)

    if use_gemini:
        n_enriched = enrich_listings_with_gemini(limit=50)
        if n_enriched > 0:
            logger.info("Re-valuating after Gemini enrichment...")
            val_stats = reprocess_valuation()

    if use_groq:
        n_enriched = enrich_listings_with_groq()
        if n_enriched > 0:
            logger.info("Re-valuating after Groq enrichment...")
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
    logger.info(f"  Valuation: {val_stats}")
    logger.info(f"  PriceDrop: {n_drops} new drops detected")
    logger.info(f"  Lifecycle: {n_delisted} delisted ({n_likely_sold} likely sold <72h)")
    logger.info(f"  Dedup    : {dedup_stats['dup_groups']} groups | {dedup_stats['flagged']} flagged | {dedup_stats['unique_lots']} unique lots")
    logger.info(f"  ContentHash: {n_hashes} rows updated")
    logger.info("=" * 55)

    return {"listings": listing_stats, "valuation": val_stats,
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
    parser.add_argument("--groq",          action="store_true", help="Chỉ chạy Groq enrichment (không reprocess)")
    parser.add_argument("--groq-frontage", action="store_true", dest="groq_frontage", help="Groq enrich frontage_m/road_width_m cho listings còn NULL")
    parser.add_argument("--groq-signals",  action="store_true", dest="groq_signals",  help="Groq verify toàn bộ fields cho signal listings")
    parser.add_argument("--ward",          help="Lọc theo phường khi dùng --groq* (vd: 'Tân An')")
    args = parser.parse_args()

    init_schema()

    if args.groq:
        n = enrich_listings_with_groq(ward=args.ward)
        if n > 0:
            reprocess_valuation()
    elif getattr(args, "groq_frontage", False):
        enrich_frontage_with_groq(ward=args.ward)
    elif getattr(args, "groq_signals", False):
        verify_signals_with_groq(ward=args.ward)
    elif args.valuation_only:
        reprocess_valuation()
    elif args.listings_only:
        reprocess_listings(source=args.source, since=args.since, full=args.full)
    else:
        run_full_reprocess(source=args.source, since=args.since, use_gemini=args.gemini, full=args.full)
