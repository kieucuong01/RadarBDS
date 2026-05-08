"""
Import dữ liệu từ JSON clean files vào SQLite.
Dùng cho lần đầu setup hoặc re-import.

Usage:
    python -m cleansing.db_import
    python -m cleansing.db_import --file data/tan_an_clean.json
"""
import argparse
import json
import logging
import sys
from pathlib import Path

# Thêm project root vào path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.database_sqlite import init_schema, upsert_listing, insert_images, start_crawl_run, finish_crawl_run

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _map_clean_to_db(rec: dict) -> dict:
    """Chuyển đổi record từ tan_an_clean.json sang format DB."""
    return {
        "source":       rec.get("source", "unknown"),
        "source_id":    str(rec["listing_id"]) if rec.get("listing_id") else None,
        "url":          rec.get("url", ""),
        "title":        rec.get("title", ""),
        "description":  rec.get("description", ""),
        "area":         rec.get("area", ""),
        "raw_area_text": rec.get("area", ""),
        "price_ty":     rec.get("price_ty"),
        "price_per_m2": rec.get("price_per_m2"),
        "area_m2":      rec.get("area_m2"),
        "property_type": rec.get("property_type", "khac"),
        "tx_type":      rec.get("tx_type", "ban"),
        "frontage_m":   rec.get("frontage_m"),
        "depth_m":      rec.get("depth_m"),
        "road_width_m": rec.get("road_width_m"),
        "road_type":    rec.get("road_type", "unknown"),
        "has_so":       int(rec.get("has_so", False)),
        "is_hot":       int(rec.get("is_hot", False)),
        "contact_phone": rec.get("contact_phone"),
        "seller_name":  rec.get("seller_name"),
        "raw_json":     rec,
    }


def import_json_file(filepath: str) -> dict:
    """Import một file JSON clean vào SQLite. Trả về stats."""
    path = Path(filepath)
    if not path.exists():
        logger.error(f"File not found: {path}")
        return {"error": "file not found"}

    logger.info(f"Loading {path}...")
    with open(path, encoding="utf-8") as f:
        records = json.load(f)

    if not isinstance(records, list):
        logger.error("JSON phải là array")
        return {"error": "invalid format"}

    logger.info(f"Loaded {len(records)} records")

    # Xác định source từ records
    sources = list({r.get("source", "unknown") for r in records})
    area    = records[0].get("area", "unknown") if records else "unknown"
    source_label = "+".join(sources)

    run_id = start_crawl_run(source_label, area)

    stats = {"fetched": len(records), "new": 0, "updated": 0, "price_dropped": 0, "skipped": 0}

    for rec in records:
        try:
            if not rec.get("url"):
                logger.warning(f"Skip record no URL: {rec.get('title', '')[:50]}")
                stats["skipped"] += 1
                continue

            db_rec = _map_clean_to_db(rec)
            listing_id, is_new = upsert_listing(db_rec, crawl_run_id=run_id)

            if is_new:
                stats["new"] += 1
                logger.debug(f"  NEW [{listing_id}] {rec.get('title', '')[:60]}")
            else:
                stats["updated"] += 1
                logger.debug(f"  UPD [{listing_id}] {rec.get('title', '')[:60]}")

            # Import ảnh nếu có
            img_urls = rec.get("img_urls") or []
            if img_urls:
                insert_images(listing_id, img_urls)

        except Exception as e:
            logger.error(f"Import error [{rec.get('url', '')}]: {e}")
            stats["skipped"] += 1

    finish_crawl_run(run_id, stats)

    logger.info(
        f"Import done: {stats['new']} new, {stats['updated']} updated, "
        f"{stats['skipped']} skipped | run_id={run_id}"
    )
    return stats


def import_all_clean_files(data_dir: str = "data") -> None:
    """Import tất cả *_clean.json trong thư mục data."""
    data_path = Path(data_dir)
    files = sorted(data_path.glob("*_clean.json"))
    if not files:
        logger.warning(f"Không tìm thấy *_clean.json trong {data_path}")
        return

    for f in files:
        logger.info(f"=== Importing {f.name} ===")
        import_json_file(str(f))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import BDS clean JSON → SQLite")
    parser.add_argument("--file", type=str, help="Path đến file JSON cụ thể")
    parser.add_argument("--dir",  type=str, default="data", help="Thư mục chứa *_clean.json")
    parser.add_argument("--init", action="store_true", help="Khởi tạo schema trước khi import")
    args = parser.parse_args()

    if args.init:
        init_schema()

    if args.file:
        import_json_file(args.file)
    else:
        import_all_clean_files(args.dir)
