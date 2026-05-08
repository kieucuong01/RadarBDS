import sys
import json
import logging
from pathlib import Path
from config.database_sqlite import init_schema, get_conn, insert_raw
from cli.utils import _parse_price, _parse_area, _detect_prop, _map_road_type, _map_has_so, _parse_road_width
import re

def cmd_import_guland(args):
    init_schema()

    if getattr(args, "file", None):
        with open(args.file, "r", encoding="utf-8") as f:
            records = json.load(f)
    else:
        print("Paste JSON array rồi nhấn Ctrl+D:")
        raw = sys.stdin.read().strip()
        records = json.loads(raw)

    print(f"Loaded {len(records)} records")

    with get_conn() as conn:
        existing = {row[0] for row in conn.execute(
            "SELECT url FROM raw_listings WHERE source='guland'"
        ).fetchall()}

    inserted = skipped = 0

    for r in records:
        if r.get("url"):
            url = r["url"].split("?")[0]
            if not url:
                skipped += 1; continue
            if url in existing:
                skipped += 1; continue

            price_ty = r.get("price_ty") or _parse_price(r.get("price_raw", ""))
            area_m2  = r.get("area_m2")  or _parse_area(r.get("area_raw", ""))
            pm2      = r.get("price_per_m2")
            if not pm2 and price_ty and area_m2 and area_m2 > 0:
                pm2 = round(price_ty * 1e9 / area_m2 / 1e6, 2)

            road_type = _map_road_type(r.get("road_type_raw", ""))
            has_so    = _map_has_so(r.get("legal_raw", ""))
            road_w    = _parse_road_width(r.get("road_width_raw", ""))
            source_id = r.get("post_id", "")
            title     = r.get("title", "")
            desc      = r.get("description", "")
            ward      = r.get("ward", "Tân An")

            rec = {
                "source": "guland", "source_id": source_id, "url": url,
                "title": title, "description": desc,
                "price_ty": price_ty, "area_m2": area_m2, "price_per_m2": pm2,
                "area_name": r.get("area_name", "Tân An"),
                "raw_area_text": r.get("address", ""),
                "property_type": _detect_prop(title + " " + desc),
                "tx_type": r.get("tx_type", "ban"),
                "road_type": road_type,
                "road_width_m": road_w,
                "has_so": has_so,
                "contact_phone": r.get("contact_phone", ""),
                "province": r.get("province", "Bình Dương"),
                "district": r.get("district", "Thủ Dầu Một"),
                "ward": ward,
                "img_urls": r.get("imgs", []),
            }
        else:
            slug = r.get("u", "").split("?")[0]
            if not slug:
                skipped += 1; continue
            url = "https://guland.vn/" + slug
            if url in existing:
                skipped += 1; continue

            price_ty = _parse_price(r.get("p", ""))
            area_m2  = _parse_area(r.get("a", ""))
            pm2 = None
            if r.get("pm2"):
                try: pm2 = float(str(r["pm2"]).replace(",", "."))
                except: pass
            if not pm2 and price_ty and area_m2 and area_m2 > 0:
                pm2 = round(price_ty * 1e9 / area_m2 / 1e6, 2)

            title = r.get("t", "")
            ward  = "Phú An" if ("phu-an" in slug or "phú an" in title.lower()) else "Tân An"
            rec = {
                "source": "guland", "source_id": r.get("sid", ""), "url": url,
                "title": title, "description": "",
                "price_ty": price_ty, "area_m2": area_m2, "price_per_m2": pm2,
                "area_name": "Tân An",
                "property_type": _detect_prop(title),
                "tx_type": "ban", "province": "Bình Dương",
                "district": "Thủ Dầu Một", "ward": ward, "img_urls": [],
            }

        try:
            insert_raw(source="guland", source_id=rec.get("source_id") or None,
                       url=url, raw_data=rec, crawl_run_id=None)
            inserted += 1
        except Exception as e:
            logging.warning(f"insert error {url}: {e}")
            skipped += 1

    print(f"Inserted: {inserted} | Skipped: {skipped}")
    with get_conn() as conn:
        g = conn.execute("SELECT COUNT(*) FROM raw_listings WHERE source='guland'").fetchone()[0]
        t = conn.execute("SELECT COUNT(*) FROM raw_listings").fetchone()[0]
    print(f"Guland raw: {g} | Total raw: {t}")

def cmd_import_batdongsan(args):
    init_schema()

    if getattr(args, "file", None):
        with open(args.file, "r", encoding="utf-8") as f:
            records = json.load(f)
    else:
        print("Paste JSON array rồi nhấn Ctrl+D:")
        records = json.loads(sys.stdin.read().strip())

    print(f"Loaded {len(records)} records")

    with get_conn() as conn:
        existing = {row[0] for row in conn.execute(
            "SELECT url FROM raw_listings WHERE source='batdongsan'"
        ).fetchall()}

    inserted = skipped = 0

    def _pf(s):
        if not s: return None
        try: return float(re.sub(r"[^\d.]", "", s))
        except: return None

    for r in records:
        url = r.get("url", "").split("?")[0]
        if not url:
            skipped += 1; continue
        if url in existing:
            skipped += 1; continue

        price_ty = r.get("price_ty") or _parse_price(r.get("price_raw", ""))
        area_m2  = r.get("area_m2")  or _parse_area(r.get("area_raw", ""))
        pm2      = r.get("price_per_m2")
        if not pm2 and price_ty and area_m2 and area_m2 > 0:
            pm2 = round(price_ty * 1e9 / area_m2 / 1e6, 2)

        road_type = _map_road_type(r.get("road_type_raw", ""))
        has_so    = _map_has_so(r.get("legal_raw", ""))
        title     = r.get("title", "")
        desc      = r.get("description", "")
        ward      = r.get("ward", "Tân An")

        rec = {
            "source": "batdongsan", "source_id": r.get("post_id", ""), "url": url,
            "title": title, "description": desc,
            "price_ty": price_ty, "area_m2": area_m2, "price_per_m2": pm2,
            "area_name": r.get("area_name", "Tân An"),
            "raw_area_text": r.get("address", ""),
            "property_type": _detect_prop(title + " " + desc),
            "tx_type": r.get("tx_type", "ban"),
            "road_type": road_type,
            "frontage_m": _pf(r.get("frontage_raw", "")),
            "depth_m":    _pf(r.get("depth_raw", "")),
            "has_so": has_so,
            "contact_phone": r.get("contact_phone", ""),
            "province": r.get("province", "Bình Dương"),
            "district": r.get("district", "Thủ Dầu Một"),
            "ward": ward,
            "img_urls": r.get("imgs", []),
        }
        try:
            insert_raw(source="batdongsan", source_id=rec["source_id"] or None,
                       url=url, raw_data=rec, crawl_run_id=None)
            inserted += 1
        except Exception as e:
            logging.warning(f"insert error {url}: {e}")
            skipped += 1

    print(f"Inserted: {inserted} | Skipped: {skipped}")
    with get_conn() as conn:
        b = conn.execute("SELECT COUNT(*) FROM raw_listings WHERE source='batdongsan'").fetchone()[0]
        t = conn.execute("SELECT COUNT(*) FROM raw_listings").fetchone()[0]
    print(f"BDS raw: {b} | Total raw: {t}")

def cmd_delete_batdongsan(args):
    init_schema()
    with get_conn() as conn:
        raw_count = conn.execute("SELECT COUNT(*) FROM raw_listings WHERE source='batdongsan'").fetchone()[0]
        lst_count = conn.execute("SELECT COUNT(*) FROM listings WHERE source='batdongsan'").fetchone()[0]
        print(f"Sẽ xóa: {raw_count} raw_listings + {lst_count} listings (source=batdongsan)")

        if not getattr(args, "yes", False):
            confirm = input("Xác nhận xóa? [y/N] ").strip().lower()
            if confirm != "y":
                print("Hủy."); return

        conn.execute("""
            DELETE FROM valuation_results
            WHERE listing_id IN (SELECT id FROM listings WHERE source='batdongsan')
        """)
        conn.execute("DELETE FROM listings WHERE source='batdongsan'")
        conn.execute("DELETE FROM raw_listings WHERE source='batdongsan'")
        print(f"Đã xóa {raw_count} raw + {lst_count} listings batdongsan.")

def cmd_delete_guland(args):
    init_schema()
    with get_conn() as conn:
        raw_count = conn.execute("SELECT COUNT(*) FROM raw_listings WHERE source='guland'").fetchone()[0]
        lst_count = conn.execute("SELECT COUNT(*) FROM listings WHERE source='guland'").fetchone()[0]
        print(f"Sẽ xóa: {raw_count} raw_listings + {lst_count} listings (source=guland)")

        if not getattr(args, "yes", False):
            confirm = input("Xác nhận xóa? [y/N] ").strip().lower()
            if confirm != "y":
                print("Hủy.")
                return

        conn.execute("""
            DELETE FROM valuation_results
            WHERE listing_id IN (SELECT id FROM listings WHERE source='guland')
        """)
        conn.execute("DELETE FROM listings WHERE source='guland'")
        conn.execute("DELETE FROM raw_listings WHERE source='guland'")
        print(f"Đã xóa {raw_count} raw + {lst_count} listings guland khỏi DB.")

def cmd_export_raw(args):
    init_schema()
    out = getattr(args, "out", None) or str(Path(__file__).parent.parent / "data" / "raw_backup.json")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT source, source_id, url, raw_json, crawled_at FROM raw_listings ORDER BY id"
        ).fetchall()
    records = []
    for r in rows:
        records.append({
            "source":     r["source"],
            "source_id":  r["source_id"],
            "url":        r["url"],
            "raw_json":   json.loads(r["raw_json"]),
            "crawled_at": r["crawled_at"],
        })
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"Exported {len(records)} raw records → {out_path}")

def cmd_import_raw_backup(args):
    init_schema()
    src = getattr(args, "file", None) or str(Path(__file__).parent.parent / "data" / "raw_backup.json")
    if not Path(src).exists():
        print(f"Không tìm thấy file: {src}")
        print("Hint: chạy 'python radar.py export-raw' ở session trước để tạo backup")
        return

    with open(src, "r", encoding="utf-8") as f:
        records = json.load(f)
    print(f"Loaded {len(records)} records từ {src}")

    inserted = skipped = 0
    for r in records:
        rid = insert_raw(
            source=r["source"],
            source_id=r.get("source_id"),
            url=r["url"],
            raw_data=r["raw_json"],
        )
        if rid:
            inserted += 1
        else:
            skipped += 1

    print(f"Raw restore: {inserted} inserted | {skipped} skipped (đã có)")

    if inserted > 0 and not getattr(args, "no_reprocess", False):
        print("\nChạy reprocess...")
        from cleansing.reprocess import run_full_reprocess
        result = run_full_reprocess()
        r = result["listings"]
        v = result["valuation"]
        print(f"Listings : {r['new']} new | {r['updated']} updated")
        print(f"Valuation: {v['total']} valuated | {v['signals']} signals")

def cmd_import_facebook_json(args):
    init_schema()
    src = args.file
    if not Path(src).exists():
        print(f"Không tìm thấy file: {src}")
        return

    with open(src, "r", encoding="utf-8") as f:
        posts = json.load(f)

    from crawler.facebook_chrome import build_record, is_relevant

    inserted = skipped = irrelevant = 0
    for post in posts:
        text = (post.get("text") or post.get("description") or "")
        if not is_relevant(text):
            irrelevant += 1
            continue
        record = build_record(post)
        if not record:
            irrelevant += 1
            continue
        rid = insert_raw(
            source="facebook",
            source_id=record.get("post_id") or None,
            url=record["url"],
            raw_data=record,
        )
        if rid:
            inserted += 1
        else:
            skipped += 1

    print(f"[facebook] imported={inserted} | skipped={skipped} (đã có) | irrelevant={irrelevant}")

    if inserted > 0 and not getattr(args, "no_reprocess", False):
        print("\nChạy reprocess...")
        from cleansing.reprocess import run_full_reprocess
        result = run_full_reprocess()
        r = result["listings"]
        v = result["valuation"]
        print(f"Listings : {r['new']} new | {r['updated']} updated")
        print(f"Valuation: {v['total']} valuated | {v['signals']} signals")
