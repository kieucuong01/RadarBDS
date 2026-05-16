import json
import time
import logging
import sys
from pathlib import Path
from config.database_sqlite import init_schema, get_conn, insert_raw
from cli.data_import import cmd_export_raw
from db.moderation import normalize_phone

def _get_crawlers(source_filter=None):
    from crawler.guland_pw import GulandCrawler
    from crawler.batdongsan_pw import BatDongSanCrawler

    all_crawlers = {
        "guland":     GulandCrawler,
        "batdongsan": BatDongSanCrawler,
    }
    if source_filter:
        cls = all_crawlers.get(source_filter)
        if not cls:
            print(f"Nguồn không hỗ trợ: {source_filter}. Chọn: {list(all_crawlers)}")
            return []
        return [cls()]
    return [cls() for cls in all_crawlers.values()]

def _facebook_crawl_to_raw(mode: str, limit_override=None, profiles=None, area_filter=None):
    from crawler.facebook_apify import FacebookApifyCrawler, load_profiles
    from crawler.facebook_chrome import build_record, is_relevant
    from config.area_profiles import post_mentions_other_city

    if profiles is None:
        profiles = load_profiles(area_filter=area_filter)
    if not profiles:
        print("[facebook] Khong co profile nao. Kiem tra data/facebook_profiles.json hoac --area")
        return None

    try:
        crawler = FacebookApifyCrawler()
    except RuntimeError as e:
        print(f"[facebook] LOI: {e}")
        return None

    raw_posts = crawler.crawl_all(profiles, mode=mode, limit_override=limit_override or None)
    if not raw_posts:
        print("[facebook] Khong co bai nao tu Apify (kiem tra profile URL va APIFY_TOKEN).")
        return {"fetched": 0, "inserted": 0, "skipped": 0,
                "irrelevant": 0, "out_of_area": 0}

    inserted = skipped = irrelevant = out_of_area = 0
    for post in raw_posts:
        text = post.get("text") or ""
        if not is_relevant(text):
            irrelevant += 1
            continue
        # City filter: chỉ skip khi post ghi RÕ TP KHÁC với profile_city.
        profile_city = post.get("default_area") or ""
        if profile_city and post_mentions_other_city(text, profile_city):
            out_of_area += 1
            continue
        apify_raw = post.pop("_apify_raw", None)
        record = build_record(post)
        if not record:
            irrelevant += 1
            continue
        # Giữ broker_name vào record để lưu raw_json
        broker_name = post.get("broker_name")
        if broker_name:
            record["broker_name"] = broker_name
        phone_norm = normalize_phone(record.get("contact_phone"))
        if phone_norm:
            with get_conn() as conn:
                blocked = conn.execute(
                    "SELECT 1 FROM broker_blacklist WHERE active=1 AND phone_norm=?",
                    (phone_norm,),
                ).fetchone()
            if blocked:
                skipped += 1
                continue
        raw_data = dict(record)
        if apify_raw:
            raw_data["_apify_raw"] = apify_raw
        rid = insert_raw(
            source="facebook",
            source_id=record.get("post_id") or None,
            url=record["url"],
            raw_data=raw_data,
        )
        if rid:
            inserted += 1
        else:
            skipped += 1

    return {"fetched": len(raw_posts), "inserted": inserted,
            "skipped": skipped, "irrelevant": irrelevant,
            "out_of_area": out_of_area}

def cmd_crawl_facebook(args):
    init_schema()

    profiles = [{"url": args.profile, "tier": 20, "broker_name": None, "default_area": None}] if getattr(args, "profile", None) else None
    stats = _facebook_crawl_to_raw(
        mode=args.mode,
        limit_override=getattr(args, "limit", None),
        profiles=profiles,
        area_filter=getattr(args, "area", None)
    )
    if stats is None:
        return

    print(
        f"[facebook] crawled={stats['fetched']} | "
        f"bds={stats['fetched']-stats['irrelevant']} | "
        f"imported={stats['inserted']} | skipped={stats['skipped']} (da co) | "
        f"irrelevant={stats['irrelevant']} | out_of_area={stats.get('out_of_area', 0)}"
    )

    if stats["inserted"] > 0 and not getattr(args, "no_reprocess", False):
        print("\nChay reprocess...")
        from cleansing.reprocess import run_full_reprocess
        result = run_full_reprocess()
        r = result["listings"]
        v = result["valuation"]
        print(f"Listings : {r['new']} new | {r['updated']} updated")
        print(f"Valuation: {v['total']} valuated | {v['signals']} signals")
        print(f"\nĐang tải ảnh về local...")
        from cleansing.download_images import download_images
        download_images()
    elif stats["inserted"] == 0:
        print("[facebook] Khong co bai moi, bo qua reprocess.")

def cmd_crawl(args, mode: str = "full"):
    init_schema()

    crawlers = _get_crawlers(getattr(args, "source", None))
    if not crawlers:
        return

    headless = not getattr(args, "visible", False)
    no_reprocess = getattr(args, "no_reprocess", False)
    no_alert = getattr(args, "no_alert", False)
    source_filter = getattr(args, "source", None)

    # Capture timestamp ngay trước khi crawl để filter "tin mới run này" cho VIP push
    with get_conn() as _c:
        crawl_start_ts = _c.execute("SELECT datetime('now')").fetchone()[0]

    total_new = 0
    crawler_exceptions: list[tuple[str, str]] = []
    for crawler in crawlers:
        try:
            stats = crawler.run(mode=mode, headless=headless)
            total_new += stats.get("new", 0)
            print(f"[{crawler.SOURCE_NAME}] new={stats['new']} skip={stats['skipped']} err={stats['errors']}")
        except Exception as e:
            print(f"[{crawler.SOURCE_NAME}] Lỗi: {e}")
            crawler_exceptions.append((crawler.SOURCE_NAME, str(e)))

    if mode == "incremental" and not source_filter:
        print(f"\n[facebook] Crawling 20 posts/profile (incremental)...")
        fb_stats = _facebook_crawl_to_raw(mode="incremental", limit_override=20)
        if fb_stats:
            print(
                f"[facebook] crawled={fb_stats['fetched']} | "
                f"imported={fb_stats['inserted']} | skipped={fb_stats['skipped']} | "
                f"irrelevant={fb_stats['irrelevant']} | out_of_area={fb_stats.get('out_of_area', 0)}"
            )
            total_new += fb_stats["inserted"]

    if total_new == 0:
        print(f"\nKhông có tin mới. DB không thay đổi.")
        return

    if not no_reprocess:
        print(f"\nReprocess {total_new} records mới...")
        from cleansing.reprocess import run_full_reprocess
        result = run_full_reprocess()
        r, v = result["listings"], result["valuation"]
        print(f"Listings : {r['new']} new | {r['updated']} updated")
        print(f"Valuation: {v['total']} valuated | {v['signals']} signals | {v['outliers']} outliers")

        print(f"\nĐang tải ảnh về local...")
        from cleansing.download_images import download_images
        download_images()

    class _FakeArgs:
        out = None
    cmd_export_raw(_FakeArgs())

    if not no_alert:
        try:
            from cli.notify import push_new_listings_to_vip
            push_stats = push_new_listings_to_vip(since=crawl_start_ts)
            print(f"VIP push: {push_stats['matched_users']} users matched | "
                  f"{push_stats['telegram_sent']} TG cards | "
                  f"{push_stats['email_users']} email batches")
        except Exception as e:
            print(f"[vip-push] error: {e}")

    _maybe_send_ops_alert(crawl_start_ts, crawler_exceptions)

    print(f"\n{'='*45}")
    print(f"CRAWL {mode.upper()} DONE — {total_new} records mới")
    print(f"{'='*45}")


def _maybe_send_ops_alert(crawl_start_ts: str, crawler_exceptions: list) -> None:
    """Inspect crawl_runs since the run started; fire ops alert if unhealthy."""
    try:
        from alerts.ops import send_ops_alert, summarize_crawl_health

        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT source, status, COALESCE(n_fetched,0) AS n_fetched,
                       COALESCE(n_new,0) AS n_new, COALESCE(error_msg,'') AS error_msg
                FROM crawl_runs
                WHERE source NOT LIKE 'reprocess:%'
                  AND datetime(started_at) >= datetime(?)
                ORDER BY started_at
                """,
                (crawl_start_ts,),
            ).fetchall()
        unhealthy, msg = summarize_crawl_health(rows)
        if crawler_exceptions:
            exc_text = "\n".join(f"- {src}: {err[:180]}" for src, err in crawler_exceptions)
            msg = f"{msg}\n\nException(s):\n{exc_text}"
            unhealthy = True
        if unhealthy:
            sent = send_ops_alert(msg)
            print(f"[ops-alert] unhealthy crawl, sent={sent}")
    except Exception as e:
        print(f"[ops-alert] error: {e}")

def _repair_guland(crawler, rows, headless):
    from playwright.sync_api import sync_playwright

    BATCH_JS = """
    async (urls) => {
        const results = await Promise.all(urls.map(async url => {
            try {
                const r = await fetch(url);
                const html = await r.text();
                const doc = new DOMParser().parseFromString(html, 'text/html');
                const getText = sel => doc.querySelector(sel)?.textContent.trim() || '';
                const priceEl = doc.querySelector('.sdb-inf-data.data-color-1.data-size-xl b');
                const infBs   = [...doc.querySelectorAll('.sdb-inf-data.data-size-lg b')];
                const phoneEl = doc.querySelector('[href^="tel:"]');
                const infoRow = getText('.dtl-inf__row');
                const extract = (...keys) => {
                    for (const k of keys) {
                        const m = infoRow.match(new RegExp(k + '[\\\\s\\\\-:]+([^\\\\n]+?)(?=\\\\s{2,}|$)', 'i'));
                        if (m) return m[1].trim();
                    }
                    return '';
                };
                return {
                    url,
                    price_raw:    priceEl?.textContent.trim() || '',
                    area_raw:     infBs[0]?.textContent.trim() || '',
                    pm2_raw:      infBs[1]?.textContent.trim() || '',
                    description:  getText('.dtl-inf__dsr'),
                    address:      getText('.dtl-stl__row, .dtl-adr'),
                    legal_raw:    extract('Pháp lý'),
                    road_type_raw:extract('Loại đường', 'Đường'),
                    contact_phone: phoneEl ? phoneEl.href.replace('tel:','') : '',
                    imgs: [...doc.querySelectorAll('img')]
                                .map(i => i.getAttribute('data-src') || i.getAttribute('src'))
                                .filter(s => s && s.startsWith('http') && !s.includes('logo') && !s.includes('avatar')),
                };
            } catch(e) { return {url, error: e.message}; }
        }));
        return results;
    }
    """

    BATCH_SIZE = 10
    urls = [r[1] for r in rows]
    raw_by_url = {r[1]: (r[0], json.loads(r[2])) for r in rows}

    repaired = 0
    with sync_playwright() as pw:
        browser, ctx = crawler._launch(pw, headless=headless)
        page = ctx.new_page()
        page.goto("https://guland.vn", wait_until="domcontentloaded", timeout=30_000)
        time.sleep(2)

        for i in range(0, len(urls), BATCH_SIZE):
            batch = urls[i:i + BATCH_SIZE]
            try:
                results = page.evaluate(BATCH_JS, batch)
                for res in (results or []):
                    if not res or res.get("error") or not res.get("url"):
                        continue
                    url = res["url"]
                    raw_id, raw_data = raw_by_url[url]
                    changed = False
                    for field in ["price_raw","area_raw","pm2_raw","description",
                                  "address","legal_raw","road_type_raw","contact_phone", "imgs"]:
                        v = res.get(field, "")
                        if v and v not in ("", "—"):
                            raw_data[field] = v
                            changed = True
                    if changed:
                        with get_conn() as conn:
                            conn.execute("UPDATE raw_listings SET raw_json=? WHERE id=?",
                                         (json.dumps(raw_data, ensure_ascii=False), raw_id))
                        repaired += 1
                        print(f"  [repair] OK: {url[-50:]}")
            except Exception as e:
                print(f"  [repair] Batch error: {e}")
            done = min(i + BATCH_SIZE, len(urls))
            print(f"  [repair] {done}/{len(urls)} processed, {repaired} repaired")
            time.sleep(0.5)

        browser.close()
    print(f"\n[repair] Xong: {repaired}/{len(rows)} records cập nhật data")

def _repair_batdongsan(crawler, rows, headless):
    from playwright.sync_api import sync_playwright

    repaired = 0
    with sync_playwright() as pw:
        browser, ctx = crawler._launch(pw, headless=headless)
        page = ctx.new_page()

        for i, row in enumerate(rows):
            raw_id, url, raw_json_str = row[0], row[1], row[2]
            raw_data = json.loads(raw_json_str)
            try:
                detail = crawler._fetch_detail(page, url)
                if detail:
                    for field in ["price_raw_detail","area_raw_detail","description",
                                  "address","legal_raw","road_type_raw","frontage_raw","contact_phone"]:
                        v = detail.get(field, "")
                        if v and v not in ("", "—"):
                            raw_data[field] = v
                    if detail.get("detail_imgs"):
                        raw_data["imgs"] = detail["detail_imgs"]
                    with get_conn() as conn:
                        conn.execute("UPDATE raw_listings SET raw_json=? WHERE id=?",
                                     (json.dumps(raw_data, ensure_ascii=False), raw_id))
                    repaired += 1
                    print(f"  [repair] [{i+1}/{len(rows)}] OK: {url[-50:]}")
            except Exception as e:
                print(f"  [repair] [{i+1}/{len(rows)}] Error {url[-40:]}: {e}")
            time.sleep(1)

        browser.close()
    print(f"\n[repair] Xong: {repaired}/{len(rows)} records cập nhật data")

def cmd_repair_missing(args):
    source  = args.source
    limit   = args.limit
    headless = not getattr(args, "visible", False)

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT r.id, r.url, r.raw_json
            FROM raw_listings r JOIN listings l ON l.raw_id = r.id
            WHERE r.source = ? AND (l.area_m2 IS NULL OR l.price_ty IS NULL)
            ORDER BY r.id
        """, (source,)).fetchall()

    if not rows:
        print(f"[repair] Không có listing nào thiếu data (source={source})")
        return

    if limit:
        rows = rows[:limit]

    print(f"[repair] {len(rows)} listings cần re-fetch (source={source})")

    if source == "guland":
        from crawler.guland_pw import GulandCrawler
        crawler = GulandCrawler()
        _repair_guland(crawler, rows, headless)
    elif source == "batdongsan":
        from crawler.batdongsan_pw import BatDongSanCrawler
        crawler = BatDongSanCrawler()
        _repair_batdongsan(crawler, rows, headless)
    else:
        print(f"[repair] Source '{source}' chưa hỗ trợ repair")
        return

    print("\n[repair] Chạy reprocess...")
    from cleansing.reprocess import run_full_reprocess
    stats = run_full_reprocess()
    print(f"[repair] Valuation: {stats.get('valuation', {})}")
