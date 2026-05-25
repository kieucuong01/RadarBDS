import json

from db.connection import get_conn
from db.schema import init_schema

def cmd_query(args):
    init_schema()

    if getattr(args, "stats", False):
        _query_stats()
    elif getattr(args, "top50_cheap", False):
        _query_top_cheap(source=getattr(args, "source", None), limit=getattr(args, "limit", None) or 50)
    elif getattr(args, "signals", False):
        _query_signals(limit=getattr(args, "limit", None) or 20)
    elif getattr(args, "search", None):
        _query_search(args.search, table="listings")
    elif getattr(args, "raw_search", None):
        _query_search(args.raw_search, table="raw")
    else:
        print("Chưa chỉ định query. Dùng --stats / --top50-cheap / --signals / --search / --raw-search")

def _query_stats():
    with get_conn() as conn:
        s = conn.execute("""
            SELECT
                (SELECT COUNT(*) FROM raw_listings) as raw_total,
                (SELECT COUNT(*) FROM raw_listings WHERE source='guland') as raw_guland,
                (SELECT COUNT(*) FROM raw_listings WHERE source='batdongsan') as raw_bds,
                (SELECT COUNT(*) FROM listings WHERE probably_sold=0) as listings_active,
                (SELECT COUNT(*) FROM valuation_results WHERE is_signal=1) as signals,
                (SELECT COUNT(*) FROM valuation_results WHERE is_outlier=1) as outliers,
                (SELECT COUNT(*) FROM listings WHERE price_dropped=1) as price_drops
        """).fetchone()
        from cleansing.dedup import get_dedup_stats
        d = get_dedup_stats(conn)

        print(f"\n{'='*40}")
        print(f"Raw listings    : {s['raw_total']} (guland={s['raw_guland']}, bds={s['raw_bds']})")
        print(f"Listings active : {s['listings_active']}")
        print(f"Signals         : {s['signals']}")
        print(f"Outliers        : {s['outliers']}")
        print(f"Price drops     : {s['price_drops']}")
        print(f"\nDedup:")
        print(f"  Unique lots   : {d['unique_lots']} / {d['total_listings']}")
        print(f"  Flagged dup   : {d['flagged']} (cross={d['cross_source']}, same={d['same_source']})")

        segs = conn.execute(
            "SELECT area, property_type, median_ppm2, n_listings FROM market_weekly ORDER BY median_ppm2 DESC"
        ).fetchall()
        print(f"\nMarket weekly:")
        for s in segs:
            print(f"  {s['area']} | {s['property_type']:12} | median={s['median_ppm2']:5.1f} tr/m² | n={s['n_listings']}")
        print(f"{'='*40}")

def _query_top_cheap(source=None, limit=50):
    with get_conn() as conn:
        if source:
            rows = conn.execute("""
                SELECT l.title, l.price_ty, l.area_m2, l.price_per_m2, l.url
                FROM listings l
                JOIN raw_listings r ON l.raw_id = r.id
                WHERE r.source = ? AND l.price_per_m2 > 0
                ORDER BY l.price_per_m2 ASC LIMIT ?
            """, (source, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT title, price_ty, area_m2, price_per_m2, url
                FROM listings
                WHERE price_per_m2 > 0
                ORDER BY price_per_m2 ASC LIMIT ?
            """, (limit,)).fetchall()

    print(f"\nTop {limit} rẻ nhất/m² (source={source or 'all'}):")
    print(f"{'#':>3}  {'Giá/m²':>8}  {'Giá':>7}  {'DT':>9}  Tên")
    print("-" * 85)
    for i, r in enumerate(rows, 1):
        pm2   = r["price_per_m2"] or 0
        price = r["price_ty"] or 0
        area  = r["area_m2"] or 0
        title = (r["title"] or "")[:55]
        print(f"{i:3}.  {pm2:6.1f} tr  {price:5.2f} tỷ  {area:7.0f}m²  {title}")

def _query_signals(limit=20):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT v.mos_pct, v.actual_ppm2, v.fair_ppm2, v.signal_score,
                   l.title, l.price_ty, l.area_m2, l.source, l.url
            FROM valuation_results v
            JOIN listings l ON v.listing_id = l.id
            WHERE v.is_signal = 1 AND l.possibly_duplicate = 0
            ORDER BY v.signal_score DESC NULLS LAST, v.mos_pct DESC LIMIT ?
        """, (limit,)).fetchall()

    print(f"\nTop {limit} signals (sorted by score -> MOS):")
    print(f"{'#':>3}  {'Score':>6}  {'MOS':>6}  {'Thuc':>7}  {'Fair':>7}  {'Gia':>6}  Ten")
    print("-" * 100)
    for i, r in enumerate(rows, 1):
        score = r['signal_score']
        badge = "HOT" if score and score >= 70 else ("RVW" if score and score >= 50 else "---")
        print(f"{i:3}.  {badge} {(score or 0):3}pt  {r['mos_pct']:5.1f}%  {r['actual_ppm2']:5.1f}tr  "
              f"{r['fair_ppm2']:5.1f}tr  {(r['price_ty'] or 0):4.2f}ty  {(r['title'] or '')[:50]}")

def _query_search(keyword, table="listings"):
    keyword_lower = keyword.lower()
    with get_conn() as conn:
        if table == "raw":
            rows = conn.execute("""
                SELECT id, source, url, raw_json FROM raw_listings
                WHERE lower(raw_json) LIKE ?
                LIMIT 20
            """, (f"%{keyword_lower}%",)).fetchall()
            print(f"\nTìm '{keyword}' trong raw_listings: {len(rows)} kết quả")
            for r in rows:
                d = json.loads(r["raw_json"])
                print(f"  id={r['id']} source={r['source']}")
                print(f"  title={d.get('title','')}")
                print(f"  price={d.get('price_ty','')} tỷ | area={d.get('area_m2','')}m²")
                print(f"  url={r['url']}")
                print()
        else:
            rows = conn.execute("""
                SELECT id, title, price_ty, area_m2, price_per_m2, source, url
                FROM listings
                WHERE lower(title) LIKE ? OR lower(url) LIKE ?
                LIMIT 20
            """, (f"%{keyword_lower}%", f"%{keyword_lower}%")).fetchall()
            print(f"\nTìm '{keyword}' trong listings: {len(rows)} kết quả")
            for r in rows:
                pm2 = r["price_per_m2"] or 0
                print(f"  [{r['source']}] {r['title']}")
                print(f"  {r['price_ty']} tỷ | {r['area_m2']}m² | {pm2:.1f} tr/m²")
                print(f"  {r['url']}")
                print()

def cmd_deal_brief(args):
    init_schema()
    from analytics.price_trend import get_price_trend_summary

    with get_conn() as conn:
        if getattr(args, "top", None):
            rows = conn.execute("""
                SELECT l.id, l.title, l.url, l.price_ty, l.area_m2, l.property_type,
                       l.frontage_m, l.contact_phone, l.is_hot, l.price_dropped,
                       l.road_tier, l.has_so,
                       v.mos_pct, v.fair_ppm2, v.actual_ppm2, v.signal_score,
                       v.n_segment, v.segment
                FROM listings l JOIN valuation_results v ON v.listing_id=l.id
                WHERE v.is_signal=1 AND v.signal_score IS NOT NULL
                ORDER BY v.signal_score DESC, v.mos_pct DESC
                LIMIT ?
            """, (args.top,)).fetchall()
        elif getattr(args, "id", None):
            rows = conn.execute("""
                SELECT l.id, l.title, l.url, l.price_ty, l.area_m2, l.property_type,
                       l.frontage_m, l.contact_phone, l.is_hot, l.price_dropped,
                       l.road_tier, l.has_so,
                       v.mos_pct, v.fair_ppm2, v.actual_ppm2, v.signal_score,
                       v.n_segment, v.segment
                FROM listings l JOIN valuation_results v ON v.listing_id=l.id
                WHERE l.id = ?
            """, (args.id,)).fetchall()
        else:
            print("Dùng: python radar.py deal-brief --id X  hoặc  --top N")
            return

    if not rows:
        print("Không tìm thấy listing.")
        return

    tier_labels = {0: "Không rõ", 1: "Đường tên", 2: "Đường DX/nhựa", 3: "Hẻm ≥5m", 4: "Hẻm 3-5m", 5: "Hẻm <3m"}
    score_label = lambda s: "🔥 TOP" if s and s >= 60 else ("⚡ REVIEW" if s and s >= 45 else "⚠️ LOẠI")

    for row in rows:
        trend = get_price_trend_summary(row["id"])
        flags = []
        if not row["has_so"]:           flags.append("⚠️ Chưa rõ pháp lý")
        if row["area_m2"] and row["area_m2"] > 500 and row["property_type"] == "dat_nen":
            flags.append("⚠️ Diện tích lớn — thanh khoản thấp")
        if row["road_tier"] in (4, 5):  flags.append("⚠️ Hẻm nhỏ — khó phát triển")
        if row["n_segment"] and row["n_segment"] < 15:
            flags.append("⚠️ Ít mẫu trong segment — fair value kém tin cậy")
        if trend.get("trend") == "rising":
            flags.append("⚠️ Giá đang tăng — cần xác minh lại")

        price_ty    = row["price_ty"] or 0
        upside_20   = round(price_ty * 1.20, 2)
        upside_40   = round(price_ty * 1.40, 2)

        score_str = f"{row['signal_score']}pt {score_label(row['signal_score'])}" if row["signal_score"] else "N/A"

        print("\n" + "═" * 62)
        print(f"  DEAL BRIEF — Listing #{row['id']}")
        print("═" * 62)
        print(f"  {row['title'][:70]}")
        print(f"  🔗 {row['url']}")
        print()
        print(f"  💰 Giá       : {price_ty:.2f} tỷ")
        print(f"  📐 Diện tích : {row['area_m2']:.0f} m²"
              + (f"  (ngang {row['frontage_m']:.1f}m)" if row['frontage_m'] else ""))
        print(f"  🏷️ Loại      : {row['property_type']}")
        print(f"  🛣️ Đường     : {tier_labels.get(row['road_tier'] or 0, '?')}")
        if row["contact_phone"]:
            print(f"  📞 SĐT       : {row['contact_phone']}")
        print()
        print(f"  📊 MOS       : {row['mos_pct']:.1f}%  (fair={row['fair_ppm2']:.1f} tr/m² | thực={row['actual_ppm2']:.1f} tr/m²)")
        n_seg = row['n_segment'] or 0
        conf = 'high' if n_seg >= 45 else ('medium' if n_seg >= 15 else 'low')
        print(f"  🎯 Confidence: {conf} ({n_seg} mẫu | seg={row['segment']})")
        print(f"  ⭐ Score     : {score_str}")
        if row["is_hot"]:   print(f"  🔴 Bán gấp / tin ngộp")
        if row["price_dropped"]: print(f"  📉 Đã giảm giá")
        print()

        if trend.get("n_records", 0) > 1:
            print(f"  📈 Trend  : {trend['n_records']} records | "
                  f"Drop {trend['total_drop_pct']:.1f}% | "
                  f"{trend['n_drops']} lần giảm | "
                  f"{trend['days_on_market']} ngày trên thị trường")
        else:
            print(f"  📈 Trend  : chưa đủ dữ liệu (cần ≥2 lần crawl)")

        print(f"\n  💡 Upside   : +20% → {upside_20:.2f}tỷ | +40% → {upside_40:.2f}tỷ")

        if flags:
            print(f"\n  ❗ Red flags:")
            for f in flags:
                print(f"     {f}")
        else:
            print(f"\n  ✅ Không có red flag rõ ràng")

        print("─" * 62)

def cmd_inspect(args):
    init_schema()
    from cleansing.dedup import get_dedup_stats

    with get_conn() as conn:
        raw_rows = conn.execute("""
            SELECT source, COUNT(*) as n FROM raw_listings GROUP BY source ORDER BY n DESC
        """).fetchall()
        raw_total = sum(r["n"] for r in raw_rows)

        listings_total = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE probably_sold=0"
        ).fetchone()[0]

        llm_verified = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE llm_verified=1"
        ).fetchone()[0]

        ward_unknown = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE probably_sold=0 AND (ward IS NULL OR ward='' OR ward='unknown')"
        ).fetchone()[0]

        tier_rows = conn.execute("""
            SELECT road_tier, COUNT(*) as n FROM listings
            WHERE probably_sold=0 GROUP BY road_tier ORDER BY road_tier
        """).fetchall()

        ptype_rows = conn.execute("""
            SELECT property_type, COUNT(*) as n FROM listings
            WHERE probably_sold=0 GROUP BY property_type ORDER BY n DESC
        """).fetchall()

        val_total = conn.execute("SELECT COUNT(*) FROM valuation_results").fetchone()[0]
        signals   = conn.execute("SELECT COUNT(*) FROM valuation_results WHERE is_signal=1").fetchone()[0]
        outliers  = conn.execute("SELECT COUNT(*) FROM valuation_results WHERE is_outlier=1").fetchone()[0]

        no_price  = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE probably_sold=0 AND price_ty IS NULL"
        ).fetchone()[0]
        no_area   = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE probably_sold=0 AND area_m2 IS NULL"
        ).fetchone()[0]
        price_drops = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE price_dropped=1"
        ).fetchone()[0]
        has_so_count = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE has_so=1 AND probably_sold=0"
        ).fetchone()[0]

        dedup = get_dedup_stats(conn)

        mkt_rows = conn.execute("""
            SELECT area, property_type, median_ppm2, n_listings
            FROM market_weekly ORDER BY median_ppm2 DESC
        """).fetchall()

    W = 52
    print(f"\n{'═'*W}")
    print(f"  RADAR BDS — DB INSPECT")
    print(f"{'═'*W}")

    print(f"\n── RAW LISTINGS ({raw_total} tổng) ──────────────────────")
    for r in raw_rows:
        print(f"  {r['source']:15s} : {r['n']:>5}")

    print(f"\n── LISTINGS ({listings_total} active) ──────────────────────")
    pct_llm  = round(llm_verified / listings_total * 100) if listings_total else 0
    pct_ward = round((listings_total - ward_unknown) / listings_total * 100) if listings_total else 0
    print(f"  LLM enriched   : {llm_verified:>5}  ({pct_llm}%)")
    print(f"  Ward known     : {listings_total - ward_unknown:>5}  ({pct_ward}%)")
    print(f"  No price       : {no_price:>5}")
    print(f"  No area        : {no_area:>5}")
    print(f"  Has SHR/GCN    : {has_so_count:>5}")
    print(f"  Price drops    : {price_drops:>5}")

    print(f"\n── ROAD TIER ─────────────────────────────────────────")
    tier_labels = {0: "unknown", 1: "MT đường tên", 2: "Đường nhựa/ĐX",
                   3: "Hẻm xe hơi ≥3m", 4: "Hẻm xe máy <3m"}
    for r in tier_rows:
        tier = r["road_tier"] or 0
        pct = round(r["n"] / listings_total * 100) if listings_total else 0
        print(f"  tier={tier} {tier_labels.get(tier,'?'):18s} : {r['n']:>5}  ({pct}%)")

    print(f"\n── PROPERTY TYPE ─────────────────────────────────────")
    for r in ptype_rows:
        pct = round(r["n"] / listings_total * 100) if listings_total else 0
        print(f"  {(r['property_type'] or 'NULL'):15s} : {r['n']:>5}  ({pct}%)")

    print(f"\n── VALUATION ─────────────────────────────────────────")
    pct_sig = round(signals / val_total * 100) if val_total else 0
    print(f"  Valuated       : {val_total:>5}  / {listings_total} active")
    print(f"  Signals        : {signals:>5}  ({pct_sig}% — target 10–30%)")
    print(f"  Outliers       : {outliers:>5}")

    print(f"\n── DEDUP ─────────────────────────────────────────────")
    print(f"  Unique lots    : {dedup['unique_lots']:>5}  / {dedup['total_listings']}")
    print(f"  Flagged dup    : {dedup['flagged']:>5}  (cross={dedup['cross_source']}, same={dedup['same_source']})")

    if mkt_rows:
        print(f"\n── MARKET WEEKLY ─────────────────────────────────────")
        for r in mkt_rows:
            print(f"  {r['area']:12s} | {(r['property_type'] or ''):12s} | "
                  f"median={r['median_ppm2']:5.1f} tr/m² | n={r['n_listings']}")

    print(f"\n{'═'*W}\n")


def cmd_crawl_health(args):
    """Hiển thị health dashboard cho các crawl runs gần đây."""
    init_schema()
    limit = getattr(args, "limit", None) or 10

    with get_conn() as conn:
        runs = conn.execute("""
            SELECT id, source, started_at, finished_at, status,
                   n_new, n_skipped, n_fetched, error_msg
            FROM crawl_runs ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()

    if not runs:
        print("Chưa có crawl run nào.")
        return

    W = 90
    print(f"\n{'═'*W}")
    print(f"  CRAWL HEALTH — {limit} runs gần nhất")
    print(f"{'═'*W}")
    print(f"  {'ID':>4} | {'Source':12} | {'Started':19} | {'Status':8} | {'New':>5} | {'Skip':>5} | {'Errors'}")
    print(f"  {'─'*4}-+-{'─'*12}-+-{'─'*19}-+-{'─'*8}-+-{'─'*5}-+-{'─'*5}-+-{'─'*20}")

    for r in runs:
        started = (r["started_at"] or "")[:19]
        err_summary = ""
        if r["error_msg"]:
            try:
                errors = json.loads(r["error_msg"])
                if isinstance(errors, list):
                    types = {}
                    for e in errors:
                        t = e.get("error_type", "unknown")
                        types[t] = types.get(t, 0) + 1
                    err_summary = ", ".join(f"{t}:{n}" for t, n in types.items())
                else:
                    err_summary = str(r["error_msg"])[:40]
            except Exception:
                err_summary = str(r["error_msg"])[:40]

        n_new = r["n_new"] or 0
        n_skip = r["n_skipped"] or 0
        status_icon = "done" if r["status"] == "done" else r["status"]

        print(f"  {r['id']:>4} | {(r['source'] or ''):12} | {started:19} | {status_icon:8} | {n_new:>5} | {n_skip:>5} | {err_summary}")

    # Summary
    with get_conn() as conn:
        recent = conn.execute("""
            SELECT source,
                   COUNT(*) as runs,
                   SUM(COALESCE(n_new, 0)) as total_new,
                   SUM(CASE WHEN error_msg IS NOT NULL AND error_msg != '' THEN 1 ELSE 0 END) as runs_with_errors
            FROM crawl_runs
            WHERE started_at > datetime('now', '-7 days')
            GROUP BY source
        """).fetchall()

    if recent:
        print(f"\n── TUẦN QUA ──────────────────────────────────────────")
        for r in recent:
            err_pct = round(r["runs_with_errors"] / r["runs"] * 100) if r["runs"] else 0
            health = "OK" if err_pct < 30 else "WARN" if err_pct < 60 else "CRIT"
            print(f"  {(r['source'] or ''):12} | {r['runs']:>3} runs | {r['total_new']:>5} new | "
                  f"errors: {r['runs_with_errors']}/{r['runs']} ({err_pct}%) [{health}]")

    print(f"\n{'═'*W}\n")
