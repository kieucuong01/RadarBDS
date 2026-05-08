"""
Radar BDS — Main Orchestrator (SQLite MVP)
Chạy 24/7 với đa luồng, health check, auto-restart từng crawler.
Pipeline: crawler → SQLite upsert (incremental) → price drop check
          → valuation engine → signals → market_weekly → alerts
"""
import logging
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from config.database_sqlite import (
    init_schema, get_conn,
    get_existing_source_ids,
    upsert_listing, insert_images,
    start_crawl_run, finish_crawl_run,
    mark_missing_listings,
    save_alert_log, save_valuation_result,
)
from config.settings import WATCH_AREAS, CRAWL_INTERVAL_MINS
from analytics.market_trend import detect_price_drops, compute_weekly_trend
from alerts.telegram import send_message

# ─── Logging ──────────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/radar_bds.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("orchestrator")

_shutdown = threading.Event()


def _handle_signal(signum, frame):
    logger.info(f"Signal {signum} received — shutting down...")
    _shutdown.set()


signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ─── Valuation integration ────────────────────────────────────────────────────

def run_valuation_and_alerts(crawl_run_id: int) -> int:
    """
    Đọc listings từ DB → chạy valuation engine → ghi results → gửi alerts.
    Trả về số signals gửi.
    """
    try:
        from analytics.valuation import ValuationEngine, Listing
        from datetime import date

        with get_conn() as conn:
            rows = conn.execute("""
                SELECT id, area, property_type, tx_type, price_per_m2, price_ty,
                       area_m2, frontage_m, depth_m, road_width_m, road_type,
                       has_so, is_hot, price_dropped, crawled_at, url
                FROM listings
                WHERE price_per_m2 IS NOT NULL
                  AND price_per_m2 > 0
                  AND probably_sold = 0
            """).fetchall()

        if not rows:
            logger.info("Valuation: no listings found")
            return 0

        # Tạo Listing objects
        listings = []
        id_map   = {}
        for row in rows:
            try:
                crawled = None
                if row["crawled_at"]:
                    try:
                        crawled = date.fromisoformat(row["crawled_at"][:10])
                    except Exception:
                        pass

                l = Listing(
                    id=row["id"],
                    area=row["area"] or "unknown",
                    property_type=row["property_type"] or "khac",
                    tx_type=row["tx_type"] or "ban",
                    price_per_m2=float(row["price_per_m2"]),
                    price_total=float(row["price_ty"] or 0),
                    area_m2=float(row["area_m2"] or 0),
                    frontage_m=float(row["frontage_m"]) if row["frontage_m"] else None,
                    depth_m=float(row["depth_m"]) if row["depth_m"] else None,
                    road_width_m=float(row["road_width_m"]) if row["road_width_m"] else None,
                    road_type=row["road_type"] or "unknown",
                    has_so=bool(row["has_so"]),
                    is_hot=bool(row["is_hot"]),
                    crawled_at=crawled,
                    url=row["url"] or "",
                )
                listings.append(l)
                id_map[l.id] = l
            except Exception as e:
                logger.warning(f"Listing build error id={row['id']}: {e}")

        engine = ValuationEngine()
        engine.fit(listings)
        results = engine.valuate_batch(listings)

        n_signals = 0
        with get_conn() as conn:
            for res in results:
                lid = res.get("id")
                if not lid:
                    continue

                save_valuation_result(lid, {
                    "fair_ppm2":   res.price_per_m2_fair,
                    "actual_ppm2": res.price_per_m2_actual,
                    "mos_pct":     res.discount_pct,
                    "is_signal":   res.is_signal,
                    "segment":     f"{res.area}|{res.property_type}",
                    "n_segment":   res.segment_n,
                }, crawl_run_id=crawl_run_id)

                # Alert nếu là signal
                if res.is_signal:
                    listing = id_map.get(lid)
                    msg     = _build_alert_message(listing, res)

                    # Dedup: chỉ gửi 1 lần/ngày
                    alert_type = "price_drop_signal" if getattr(listing, "is_hot", False) else "mos_signal"
                    if save_alert_log(lid, alert_type, msg):
                        send_message(msg)
                        n_signals += 1

        logger.info(f"Valuation done: {len(results)} results, {n_signals} alerts sent")
        return n_signals

    except Exception as e:
        logger.error(f"Valuation pipeline error: {e}", exc_info=True)
        return 0


def _build_alert_message(listing, res) -> str:
    emoji = "🔥" if getattr(listing, "is_hot", False) else "📊"
    return (
        f"{emoji} <b>Radar BDS — Deal Signal</b>\n"
        f"MOS: <b>{res.discount_pct:.1f}%</b> | Giá TT: {res.price_per_m2_actual:.1f} tr/m² | Fair: {res.price_per_m2_fair:.1f} tr/m²\n"
        f"Diện tích: {getattr(listing, 'area_m2', 0):.0f} m² | "
        f"Giá: {getattr(listing, 'price_total', 0):.2f} tỷ\n"
        f"Khu vực: {getattr(listing, 'area', '')}\n"
        f"🔗 {getattr(listing, 'url', '')}"
    )


# ─── Per-source crawl & save ──────────────────────────────────────────────────

def _save_raw_records(raw_records: list, run_id: int, area_name: str, source: str) -> dict:
    """Normalize và upsert raw records vào SQLite. Trả về stats."""
    from cleansing.normalizer import normalize_record as _normalize_record

    stats = {"fetched": len(raw_records), "new": 0, "updated": 0, "price_dropped": 0, "skipped": 0}
    seen_urls_this_run = set()

    for raw in raw_records:
        try:
            raw["area_name"] = raw.get("area_name") or area_name

            # Normalize sử dụng hàm hiện có (không cần PostgreSQL)
            rec = _normalize_record(raw)
            if not rec or not rec.get("url"):
                stats["skipped"] += 1
                continue

            if rec["url"] in seen_urls_this_run:
                stats["skipped"] += 1
                continue
            seen_urls_this_run.add(rec["url"])

            # Map field names sang SQLite schema
            db_rec = {
                "source":       source,
                "source_id":    str(raw.get("external_id") or raw.get("source_id") or ""),
                "url":          rec["url"],
                "title":        rec.get("title", ""),
                "description":  rec.get("description", ""),
                "area":         raw.get("area_name") or rec.get("raw_area_text", ""),
                "raw_area_text": rec.get("raw_area_text", ""),
                "price_ty":     rec.get("price_total"),
                "price_per_m2": rec.get("price_per_m2"),
                "area_m2":      rec.get("area_m2"),
                "property_type": rec.get("property_type", "khac"),
                "tx_type":      rec.get("transaction_type", "ban"),
                "is_hot":       int(rec.get("is_hot", False)),
                "contact_phone": rec.get("contact_phone"),
                "seller_name":  rec.get("seller_name"),
                "raw_json":     raw,
            }

            listing_id, is_new = upsert_listing(db_rec, crawl_run_id=run_id)

            if is_new:
                stats["new"] += 1
            else:
                stats["updated"] += 1

            # Lưu ảnh nếu crawler đã extract
            img_urls = raw.get("img_urls") or []
            if img_urls:
                insert_images(listing_id, img_urls)

            # Track price drop
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT price_dropped FROM listings WHERE id = ?", (listing_id,)
                ).fetchone()
                if row and row["price_dropped"]:
                    stats["price_dropped"] += 1

        except Exception as e:
            logger.error(f"Save error [{raw.get('url', '')}]: {e}")
            stats["skipped"] += 1

    return stats


def crawl_area_bds(area: dict) -> tuple:
    """Crawl BatDongSan cho một khu vực. Trả về (area_name, raw_records, seen_urls)."""
    try:
        from crawler.batdongsan import BatDongSanCrawler

        # Lấy existing source_ids + URLs để incremental skip
        with get_conn() as conn:
            existing_ids  = get_existing_source_ids("batdongsan")
            existing_urls = {
                row[0] for row in conn.execute(
                    "SELECT url FROM listings WHERE source = 'batdongsan'"
                ).fetchall()
            }

        crawler   = BatDongSanCrawler()
        records   = crawler.crawl_area(area, existing_source_ids=existing_ids, existing_urls=existing_urls)
        seen_urls = {r.get("url") for r in records if r.get("url")}
        return area["name"], records, seen_urls
    except Exception as e:
        logger.error(f"[BDS] {area['name']} crawl failed: {e}")
        return area["name"], [], set()


def crawl_facebook_all() -> list:
    """Crawl tất cả Facebook groups."""
    try:
        from crawler.facebook import FacebookCrawler
        crawler = FacebookCrawler()
        return crawler.crawl_all_groups()
    except Exception as e:
        logger.error(f"[Facebook] crawl failed: {e}")
        return []


# ─── Main crawl cycle ──────────────────────────────────────────────────────────

def run_crawl_cycle() -> None:
    logger.info("=" * 60)
    logger.info(f"Crawl cycle START: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_seen_urls: dict[str, set] = {}  # source → set of seen URLs

    # BatDongSan — đa luồng theo khu vực
    with ThreadPoolExecutor(max_workers=min(len(WATCH_AREAS), 4)) as ex:
        futures = {ex.submit(crawl_area_bds, area): area for area in WATCH_AREAS}
        for future in as_completed(futures):
            area = futures[future]
            try:
                area_name, records, seen_urls = future.result(timeout=300)
                logger.info(f"[BDS] {area_name}: {len(records)} new records fetched")

                run_id = start_crawl_run("batdongsan", area_name)
                stats  = _save_raw_records(records, run_id, area_name, "batdongsan")
                finish_crawl_run(run_id, stats)

                all_seen_urls.setdefault("batdongsan", set()).update(seen_urls)
                logger.info(f"[BDS] {area_name}: {stats}")
            except Exception as e:
                logger.error(f"[BDS] {area['name']} future error: {e}")

    # Đánh dấu listings đã bán (mất tích 3 lần crawl liên tiếp)
    if "batdongsan" in all_seen_urls:
        sold = mark_missing_listings("batdongsan", all_seen_urls["batdongsan"])
        if sold:
            logger.info(f"[BDS] Marked {sold} listings as probably_sold")

    # Facebook (sequential)
    fb_records = crawl_facebook_all()
    if fb_records:
        logger.info(f"[Facebook] {len(fb_records)} records")
        run_id = start_crawl_run("facebook", "all")
        stats  = _save_raw_records(fb_records, run_id, "", "facebook")
        finish_crawl_run(run_id, stats)
        logger.info(f"[Facebook] {stats}")

    # Price drop detection (scan toàn bộ DB)
    try:
        with get_conn() as conn:
            n_drops = detect_price_drops(conn)
        logger.info(f"Price drops detected: {n_drops}")
    except Exception as e:
        logger.error(f"Price drop detection error: {e}")

    # Market weekly trend
    try:
        with get_conn() as conn:
            trends = compute_weekly_trend(conn)
        logger.info(f"Market weekly updated: {len(trends)} segments")
    except Exception as e:
        logger.error(f"Market trend error: {e}")

    # Valuation + Alerts
    try:
        run_id     = start_crawl_run("valuation", "all")
        n_signals  = run_valuation_and_alerts(crawl_run_id=run_id)
        finish_crawl_run(run_id, {"fetched": 0, "new": 0, "updated": 0, "price_dropped": 0, "skipped": 0})
        logger.info(f"Valuation signals: {n_signals}")
    except Exception as e:
        logger.error(f"Valuation error: {e}")

    logger.info(f"Crawl cycle END: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# ─── Scheduler ────────────────────────────────────────────────────────────────

def scheduler_loop() -> None:
    interval_secs = CRAWL_INTERVAL_MINS * 60
    logger.info(f"Scheduler started — interval: {CRAWL_INTERVAL_MINS} min")

    while not _shutdown.is_set():
        try:
            run_crawl_cycle()
        except Exception as e:
            logger.critical(f"Crawl cycle crashed: {e}", exc_info=True)
            try:
                send_message(f"⚠️ <b>Radar BDS</b>: crawl cycle crashed!\n<code>{e}</code>")
            except Exception:
                pass

        for _ in range(interval_secs // 5):
            if _shutdown.is_set():
                break
            time.sleep(5)

    logger.info("Scheduler stopped")


# ─── Entrypoint ───────────────────────────────────────────────────────────────

def main():
    logger.info("Radar BDS starting up...")
    init_schema()

    try:
        send_message("✅ <b>Radar BDS</b> khởi động thành công!")
    except Exception:
        logger.warning("Telegram not configured, skipping startup message")

    try:
        scheduler_loop()
    finally:
        logger.info("Radar BDS stopped cleanly")


if __name__ == "__main__":
    # Nếu truyền --import thì chạy import luôn rồi exit
    if "--import" in sys.argv:
        init_schema()
        from cleansing.db_import import import_all_clean_files
        import_all_clean_files("data")
    elif "--once" in sys.argv:
        # Chạy 1 cycle rồi exit (dùng để test)
        init_schema()
        run_crawl_cycle()
    else:
        main()
