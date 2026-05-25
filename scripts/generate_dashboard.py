"""
Generate dashboard_signals.html — Investor-focused view.

Sections:
  1. Market Pulse (3 segments median + min/max + n)
  2. Top 3 Headline Deals (signal_score × MOS)
  3. All Signals grid with filters + "Xem thêm" collapse
  4. Price/m² distribution histogram (per property type)
  5. Full listings table (search, sort, filter, paginated "Xem thêm")

Usage:
    python generate_dashboard.py
    python radar.py dashboard
"""
import argparse
import json
import sys
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ──────────────────────────────────────────────────────────
# Logic giá trị: rebuild canonical URL từ title + ID.
#   Guland: format /post/{slug}-{id} — reconstruct từ title để tránh URL stale/sai format
#   BatDongSan: đôi khi trả về slug corrupt (thiếu "đ"), rebuild từ title sạch hơn.
import re as _re
import unicodedata as _ud

_VN_MAP = str.maketrans({"đ": "d", "Đ": "D"})

def _slugify_vn(text: str) -> str:
    if not text: return ""
    # Logic giá trị: "đ" → "d" TRƯỚC khi normalize NFD (vì NFD không tách được đ/Đ)
    text = text.translate(_VN_MAP)
    text = _ud.normalize("NFD", text)
    text = "".join(c for c in text if _ud.category(c) != "Mn")
    text = text.lower()
    text = _re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text

def _extract_id_tail(url: str) -> str:
    """Lấy ID cuối URL — BĐS: `pr{N}`, Guland: `{N}` thuần."""
    if not url: return ""
    m = _re.search(r"pr(\d+)(?:\.html)?/?$", url)
    if m: return f"pr{m.group(1)}"
    m = _re.search(r"-(\d{5,})(?:/|\.html)?$", url)
    if m: return m.group(1)
    return ""

def _canonical_url(url: str, source: str, title: str) -> str:
    """
    Fix URL theo source:
      - Guland  : giữ slug gốc (nó match slugify-rule của guland), chỉ ensure /post/ prefix
      - BDS     : slug thường bị corrupt (đ stripped) → rebuild từ title
    """
    if not url: return ""

    if source == "guland":
        # Logic giá trị: giữ slug gốc — đã match quy tắc của guland. Chỉ thêm /post/ nếu thiếu.
        if "/post/" in url:
            return url
        if url.startswith("https://guland.vn/"):
            return "https://guland.vn/post/" + url[len("https://guland.vn/"):]
        if url.startswith("http://guland.vn/"):
            return "http://guland.vn/post/" + url[len("http://guland.vn/"):]
        return url

    if source == "batdongsan":
        tail = _extract_id_tail(url)  # pr{id}
        slug = _slugify_vn(title or "")
        if not (tail and slug):
            return url  # thiếu dữ liệu → để nguyên
        m = _re.match(r"(https?://batdongsan\.com\.vn/[^/]+/)", url)
        base = m.group(1) if m else "https://batdongsan.com.vn/"
        return f"{base}{slug}-{tail}"

    return url


def _days_ago(crawled_at: str) -> int:
    try:
        d = date.fromisoformat(crawled_at[:10])
        return (date.today() - d).days
    except Exception:
        return 0


# ──────────────────────────────────────────────────────────
def load_data(db_path: str) -> dict:
    from db.connection import get_conn

    with get_conn() as conn:
        # Signals + valuation — bỏ duplicate/sold
        sig_rows = conn.execute("""
            SELECT v.mos_pct, v.actual_ppm2, v.fair_ppm2, v.is_signal,
                   v.is_outlier, v.outlier_direction, v.n_segment,
                   l.id, l.title, l.source, l.area_m2, l.price_ty,
                   l.property_type, l.is_hot, l.price_dropped, l.price_drop_pct,
                   l.url, l.crawled_at, l.posted_at, l.ward, l.road_type, l.has_so, l.frontage_m,
                   COALESCE(v.signal_score, 0)                   AS signal_score,
                   COALESCE(v.road_tier, l.road_tier, 0)         AS road_tier,
                   l.seller_name
            FROM valuation_results v
            JOIN listings l ON v.listing_id = l.id
            WHERE l.probably_sold = 0 AND l.possibly_duplicate = 0
            ORDER BY v.is_signal DESC,
                     COALESCE(v.signal_score, 0) DESC,
                     v.mos_pct DESC
        """).fetchall()

        # Full listings (bảng toàn cảnh)
        all_rows = conn.execute("""
            SELECT l.id, l.title, l.source, l.area_m2, l.price_ty, l.price_per_m2,
                   l.property_type, l.ward, l.road_type, l.has_so, l.frontage_m,
                   l.url, l.crawled_at, l.posted_at, l.is_hot, l.price_dropped,
                   COALESCE(v.is_signal, 0)              AS is_signal,
                   COALESCE(v.mos_pct, 0)                AS mos_pct,
                   COALESCE(v.signal_score, 0)           AS signal_score,
                   COALESCE(v.road_tier, l.road_tier, 0) AS road_tier,
                   v.fair_ppm2                           AS fair_ppm2,
                   l.seller_name
            FROM listings l
            LEFT JOIN valuation_results v ON v.listing_id = l.id
            WHERE l.probably_sold = 0 AND l.possibly_duplicate = 0
            ORDER BY l.property_type, l.price_per_m2 NULLS LAST
        """).fetchall()

        # Market weekly
        mw_rows = conn.execute("""
            SELECT property_type, median_ppm2, n_listings
            FROM market_weekly WHERE area = 'Tân An'
        """).fetchall()

        # Range ppm2 per type (loại outlier)
        range_rows = conn.execute("""
            SELECT property_type,
                   ROUND(MIN(price_per_m2)::numeric, 1),
                   ROUND(MAX(price_per_m2)::numeric, 1)
            FROM listings
            WHERE is_outlier = 0 AND probably_sold = 0 AND price_per_m2 IS NOT NULL
            GROUP BY property_type
        """).fetchall()

        stats = conn.execute("""
            SELECT
                (SELECT COUNT(*) FROM listings
                   WHERE probably_sold = 0 AND possibly_duplicate = 0)                        AS total,
                (SELECT COUNT(*) FROM valuation_results v JOIN listings l ON v.listing_id = l.id
                   WHERE v.is_signal = 1 AND l.possibly_duplicate = 0)                        AS signals,
                (SELECT COUNT(*) FROM listings WHERE is_hot = 1)                              AS hot,
                (SELECT COUNT(*) FROM listings WHERE price_dropped = 1)                       AS price_drops,
                (SELECT COUNT(*) FROM raw_listings)                                           AS raw_total
        """).fetchone()

        # Images: lấy tất cả ảnh của mỗi listing
        img_rows = conn.execute("""
            SELECT listing_id, COALESCE(local_path, img_url) as img_url
            FROM listing_images
            ORDER BY listing_id, img_order
        """).fetchall()

    # Map listing_id → list of image URLs
    from collections import defaultdict
    img_map = defaultdict(list)
    for r in img_rows:
        img_map[r[0]].append(r[1])

    # Pack signals
    signals = [{
        "mos_pct":      round(r[0], 1) if r[0] else 0,
        "actual_ppm2":  round(r[1], 1) if r[1] else 0,
        "fair_ppm2":    round(r[2], 1) if r[2] else 0,
        "is_signal":    bool(r[3]),
        "is_outlier":   bool(r[4]),
        "outlier_dir":  r[5] or "",
        "n_segment":    r[6] or 0,
        "id":           r[7],
        "title":        r[8] or "",
        "source":       r[9] or "",
        "area_m2":      r[10] or 0,
        "price_ty":     r[11] or 0,
        "prop_type":    r[12] or "khac",
        "is_hot":       bool(r[13]),
        "price_dropped":bool(r[14]),
        "drop_pct":     r[15],
        "url":          _canonical_url(r[16] or "", r[9] or "", r[8] or ""),
        "crawled_at":   (r[17] or "")[:10],
        "posted_at":    (r[18] or r[17] or "")[:10],
        "days_ago":     _days_ago(r[18] or r[17] or ""),
        "ward":         r[19] or "",
        "road_type":    r[20] or "unknown",
        "has_so":       bool(r[21]),
        "frontage_m":   r[22],
        "signal_score": int(r[23] or 0),
        "road_tier":    int(r[24] or 0),
        "seller_name":  r[25] or "",
        "imgs":         img_map.get(r[7], []),
    } for r in sig_rows]

    # Pack all listings
    all_listings = [{
        "id":           r[0],
        "title":        r[1] or "",
        "source":       r[2] or "",
        "area_m2":      r[3],
        "price_ty":     r[4],
        "price_per_m2": round(r[5], 1) if r[5] else None,
        "prop_type":    r[6] or "khac",
        "ward":         r[7] or "Tân An",
        "road_type":    r[8] or "unknown",
        "has_so":       bool(r[9]),
        "frontage_m":   r[10],
        "url":          _canonical_url(r[11] or "", r[2] or "", r[1] or ""),
        "crawled_at":   (r[12] or "")[:10],
        "posted_at":    (r[13] or r[12] or "")[:10],
        "days_ago":     _days_ago(r[13] or r[12] or ""),
        "is_hot":       bool(r[14]),
        "price_dropped":bool(r[15]),
        "is_signal":    bool(r[16]),
        "mos_pct":      round(r[17], 1) if r[17] else 0,
        "signal_score": int(r[18] or 0),
        "road_tier":    int(r[19] or 0),
        "fair_ppm2":    round(r[20], 1) if r[20] else None,
        "seller_name":  r[21] or "",
        "imgs":         img_map.get(r[0], []),
    } for r in all_rows]

    # Market pulse
    range_map = {r[0]: (r[1], r[2]) for r in range_rows}
    type_label = {"dat_nen": "Đất nền", "dat_vuon": "Đất vườn", "nha_dat": "Nhà đất"}
    market = []
    for r in mw_rows:
        ptype = r[0]
        lo, hi = range_map.get(ptype, (None, None))
        market.append({
            "type":     ptype,
            "label":    type_label.get(ptype, ptype),
            "median":   round(r[1], 1) if r[1] else 0,
            "n":        r[2] or 0,
            "min_ppm2": lo,
            "max_ppm2": hi,
        })

    return {
        "signals":      signals,
        "all_listings": all_listings,
        "market":       market,
        "stats":        dict(stats),
    }


# ──────────────────────────────────────────────────────────
PROP_LABELS = {"dat_nen": "Đất nền", "dat_vuon": "Đất vườn", "nha_dat": "Nhà đất", "khac": "Khác"}


def build_html(data: dict, generated_at: str) -> str:
    signals_json = json.dumps(data["signals"], ensure_ascii=False)
    all_json     = json.dumps(data["all_listings"], ensure_ascii=False)
    market_json  = json.dumps(data["market"], ensure_ascii=False)
    s            = data["stats"]
    n_total      = s.get("total", 0)
    n_signals    = s.get("signals", 0)
    n_hot        = s.get("hot", 0)
    n_drops      = s.get("price_drops", 0)

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Radar BDS — Tân An · Nhà đầu tư</title>
<style>
:root {{
  --bg:#0b0d18; --surface:#12152a; --card:#181b33; --card2:#20243f;
  --border:#2a2f52; --border2:#3a406b;
  --accent:#6c8eff; --accent2:#8ea7ff;
  --green:#00e5a0; --green-dim:rgba(0,229,160,.14);
  --red:#ff5c6c; --red-dim:rgba(255,92,108,.12);
  --orange:#ffb347; --orange-dim:rgba(255,179,71,.14);
  --yellow:#ffe066;
  --text:#e6e9f5; --muted:#7a80a8; --muted2:#505677;
  --radius:12px;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,-apple-system,sans-serif;font-size:14px;line-height:1.5;min-height:100vh}}
a{{color:inherit;text-decoration:none}}
button{{font-family:inherit}}

/* ── HEADER ─────────────────────── */
.header{{display:flex;align-items:center;justify-content:space-between;padding:14px 28px;background:var(--surface);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:100;backdrop-filter:blur(8px)}}
.header-left{{display:flex;align-items:center;gap:16px}}
.logo{{font-size:1.15rem;font-weight:800;color:#fff;letter-spacing:-.02em}}
.logo span{{color:var(--accent)}}
.header-pills{{display:flex;gap:8px}}
.pill{{background:var(--card2);border:1px solid var(--border);border-radius:20px;padding:4px 12px;font-size:.75rem;font-weight:600}}
.pill.green{{background:var(--green-dim);border-color:var(--green);color:var(--green)}}
.pill.orange{{background:var(--orange-dim);border-color:var(--orange);color:var(--orange)}}
.pill.red{{background:var(--red-dim);border-color:var(--red);color:var(--red)}}
.header-right{{font-size:.72rem;color:var(--muted)}}

/* ── LAYOUT ─────────────────────── */
.page{{max-width:1400px;margin:0 auto;padding:28px 28px 60px}}
.section{{margin-bottom:40px}}
.section-head{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:16px;gap:14px}}
.section-title{{font-size:1.1rem;font-weight:700}}
.section-title .count{{color:var(--muted);font-weight:500;margin-left:6px;font-size:.9rem}}
.section-sub{{font-size:.78rem;color:var(--muted)}}
.kicker{{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:var(--accent);margin-bottom:6px}}

/* ── MARKET PULSE ─────────────────── */
.market-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
.mcard{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px 22px;position:relative;overflow:hidden}}
.mcard::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--accent),var(--accent2))}}
.mcard.vuon::before{{background:linear-gradient(90deg,var(--green),#5cd1a4)}}
.mcard.nha::before {{background:linear-gradient(90deg,var(--orange),#ffd08a)}}
.mc-label{{font-size:.72rem;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.08em}}
.mc-median{{font-size:2.1rem;font-weight:900;color:var(--accent);line-height:1.1}}
.mcard.vuon .mc-median{{color:var(--green)}}
.mcard.nha  .mc-median{{color:var(--orange)}}
.mc-unit{{font-size:.8rem;color:var(--muted);margin-left:4px;font-weight:500}}
.mc-range{{font-size:.76rem;color:var(--muted);margin-top:10px;display:flex;justify-content:space-between}}
.mc-range b{{color:var(--text)}}
.mc-n{{font-size:.72rem;color:var(--muted);margin-top:2px}}

/* ── HEADLINE DEALS ─────────────── */
.headline-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}}
.hcard{{background:linear-gradient(180deg,var(--card),var(--surface));border:1px solid var(--border2);border-radius:var(--radius);padding:0;position:relative;overflow:hidden;transition:transform .15s,border-color .15s}}
.hcard-img-wrap{{width:100%;height:200px;overflow:hidden;background:var(--surface);position:relative}}
.hcard-img{{width:100%;height:100%;object-fit:cover;display:block}}
.hcard .rank{{position:absolute;top:12px;right:14px;font-size:1.5rem;font-weight:900;color:var(--accent);opacity:.8;letter-spacing:-.02em;background:rgba(0,0,0,.55);padding:2px 8px;border-radius:8px;z-index:2}}
.hcard:hover{{transform:translateY(-2px);border-color:var(--accent)}}
.hcard-body{{padding:16px 20px 18px}}
.hcard-top{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;gap:10px}}
.hcard-mos{{font-size:2.4rem;font-weight:900;color:var(--green);line-height:1}}
.hcard-mos .pct{{font-size:1rem;font-weight:700;margin-left:2px}}
.hcard-mos-lbl{{font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-top:2px}}
.hcard-score{{font-size:.75rem;font-weight:700;color:var(--accent);background:rgba(108,142,255,.12);padding:3px 8px;border-radius:10px;white-space:nowrap}}
.hcard-title{{font-size:.92rem;font-weight:600;line-height:1.4;margin:6px 0 10px;min-height:2.7em;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.hcard-meta{{display:flex;gap:10px;flex-wrap:wrap;font-size:.78rem;color:var(--muted);margin-bottom:8px}}
.hcard-meta b{{color:var(--text)}}
.price-compare{{display:flex;flex-direction:column;gap:2px;margin:8px 0}}
.pc-row{{display:flex;align-items:baseline;gap:6px;font-size:.85rem}}
.pc-label{{font-size:.72rem;color:var(--muted);width:55px}}
.pc-actual{{color:var(--green);font-weight:800;font-size:1.1rem}}
.pc-fair-val{{color:var(--accent2);font-weight:700;font-size:1rem}}
.pc-unit{{color:var(--muted);font-size:.72rem}}
.hcard-bar{{height:5px;background:var(--border);border-radius:3px;margin:10px 0 8px;overflow:hidden;position:relative}}
.hcard-bar-fill{{height:100%;background:linear-gradient(90deg,var(--green),#5cd1a4);border-radius:3px}}
.hcard-badges{{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}}
.badge{{font-size:.68rem;font-weight:700;padding:3px 8px;border-radius:10px;background:var(--card2);color:var(--muted);text-transform:uppercase;letter-spacing:.04em}}
.badge.hot{{background:var(--red-dim);color:var(--red)}}
.badge.drop{{background:var(--orange-dim);color:var(--orange)}}
.badge.tier1{{background:rgba(255,224,102,.14);color:var(--yellow)}}
.badge.tier2{{background:rgba(108,142,255,.14);color:var(--accent)}}
.badge.tier3{{background:rgba(108,142,255,.1);color:var(--accent2)}}
.badge.so{{background:var(--green-dim);color:var(--green)}}
.hcard-link{{display:inline-block;margin-top:12px;padding:7px 14px;background:var(--accent);color:#fff;border-radius:8px;font-weight:700;font-size:.8rem;transition:background .12s}}
.hcard-link:hover{{background:var(--accent2)}}

/* ── FILTERS ────────────────────── */
.filters{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px;align-items:center}}
.fb{{background:var(--card2);border:1px solid var(--border);color:var(--muted);border-radius:20px;padding:6px 14px;font-size:.76rem;font-weight:600;cursor:pointer;transition:all .15s;white-space:nowrap}}
.fb:hover{{color:var(--text);border-color:var(--border2)}}
.fb.active{{background:var(--accent);border-color:var(--accent);color:#fff}}
.filter-count{{font-size:.72rem;color:var(--muted);margin-left:auto}}

/* ── SIGNAL CARDS ───────────────── */
.cards-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}}
.scard{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:0;display:flex;flex-direction:column;gap:0;overflow:hidden;transition:transform .12s,border-color .12s}}
.scard:hover{{transform:translateY(-2px);border-color:var(--border2)}}
.sc-img-wrap{{width:100%;height:180px;overflow:hidden;background:var(--surface);position:relative}}
.sc-img{{width:100%;height:100%;object-fit:cover;display:block}}

/* ── SLIDER CSS ─────────────────── */
.slider-slide {{ display:none; width:100%; height:100%; object-fit:cover; }}
.slider-slide.active {{ display:block; }}
.slider-btn {{ position:absolute; top:50%; transform:translateY(-50%); background:rgba(0,0,0,0.5); color:#fff; border:none; width:28px; height:28px; border-radius:50%; cursor:pointer; font-size:1rem; opacity:0; transition:opacity 0.2s, background 0.2s; z-index:10; display:flex; align-items:center; justify-content:center; }}
.sc-img-wrap:hover .slider-btn, .hcard-img-wrap:hover .slider-btn {{ opacity:1; }}
.slider-btn:hover {{ background:rgba(0,0,0,0.8); }}
.slider-btn.prev {{ left:8px; }}
.slider-btn.next {{ right:8px; }}
.slider-dots {{ position:absolute; bottom:8px; left:0; right:0; display:flex; justify-content:center; gap:4px; z-index:10; }}
.slider-dot {{ width:6px; height:6px; border-radius:50%; background:rgba(255,255,255,0.4); cursor:pointer; }}
.slider-dot.active {{ background:#fff; box-shadow:0 0 2px rgba(0,0,0,0.5); }}
.sc-top{{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;padding:14px 16px 0}}
.sc-mos{{font-size:1.7rem;font-weight:900;line-height:1;color:var(--green)}}
.sc-mos .pct{{font-size:.85rem;font-weight:700;margin-left:1px}}
.sc-mos-lbl{{font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}}
.sc-score{{font-size:.72rem;font-weight:700;color:var(--accent);background:rgba(108,142,255,.12);padding:3px 8px;border-radius:10px}}
.sc-title{{font-size:.85rem;font-weight:600;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:2.4em;padding:6px 16px 0}}
.sc-meta{{display:flex;gap:9px;flex-wrap:wrap;font-size:.75rem;color:var(--muted);padding:0 16px}}
.sc-meta b{{color:var(--text);font-weight:600}}
.sc-price{{display:flex;flex-direction:column;gap:1px;padding:4px 16px 0}}
.sc-price-row{{display:flex;align-items:baseline;gap:6px;font-size:.8rem}}
.sc-price-label{{font-size:.65rem;color:var(--muted);width:45px}}
.sc-actual{{color:var(--green);font-weight:800;font-size:1rem}}
.sc-fair{{color:var(--accent2);font-weight:700;font-size:.9rem}}
.sc-bar{{height:4px;background:var(--border);border-radius:0;overflow:hidden}}
.sc-bar-fill{{height:100%;background:var(--green);border-radius:2px}}
.sc-bottom{{display:flex;justify-content:space-between;align-items:center;margin-top:2px;padding:0 16px 14px}}
.sc-badges{{display:flex;gap:4px;flex-wrap:wrap}}
.sc-link{{font-size:.72rem;color:var(--accent);font-weight:700}}
.sc-link:hover{{color:var(--accent2)}}

/* ── SHOW-MORE button ───────────── */
.show-more-wrap{{display:flex;justify-content:center;margin-top:16px}}
.show-more{{background:var(--card2);border:1px solid var(--border2);color:var(--text);padding:9px 24px;border-radius:24px;font-size:.78rem;font-weight:700;cursor:pointer;transition:all .15s}}
.show-more:hover{{background:var(--accent);border-color:var(--accent);color:#fff}}

/* ── DISTRIBUTION CHART ─────────── */
.dist-wrap{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px 24px}}
.dist-tabs{{display:flex;gap:6px;margin-bottom:16px}}
.dist-tab{{background:var(--card2);border:1px solid var(--border);color:var(--muted);padding:6px 14px;border-radius:18px;font-size:.76rem;font-weight:600;cursor:pointer}}
.dist-tab.active{{background:var(--accent);border-color:var(--accent);color:#fff}}
.hist{{display:flex;align-items:flex-end;gap:2px;height:140px;padding:10px 0;border-bottom:1px solid var(--border);position:relative}}
.hist-bar{{flex:1;background:var(--accent);border-radius:3px 3px 0 0;min-height:2px;position:relative;transition:background .15s;cursor:pointer}}
.hist-bar.signal{{background:var(--green)}}
.hist-bar.outlier{{background:var(--red)}}
.hist-bar:hover{{opacity:.85}}
.hist-bar:hover::after{{content:attr(data-label);position:absolute;bottom:100%;left:50%;transform:translateX(-50%);background:#000;color:#fff;padding:4px 8px;border-radius:4px;font-size:.68rem;white-space:nowrap;margin-bottom:4px;z-index:10}}
.hist-axis{{display:flex;justify-content:space-between;margin-top:6px;font-size:.68rem;color:var(--muted)}}
.hist-legend{{display:flex;gap:14px;margin-top:12px;font-size:.72rem;color:var(--muted)}}
.hist-legend .lg{{display:flex;align-items:center;gap:5px}}
.hist-legend .dot{{width:10px;height:10px;border-radius:50%}}
.hist-legend .dot.blue{{background:var(--accent)}}
.hist-legend .dot.green{{background:var(--green)}}
.hist-legend .dot.red{{background:var(--red)}}
.hist-median{{position:absolute;top:0;bottom:0;width:2px;background:var(--yellow);opacity:.6}}
.hist-median::after{{content:'median';position:absolute;top:-4px;left:5px;font-size:.64rem;color:var(--yellow);font-weight:700}}

/* ── TABLE ──────────────────────── */
.table-wrap{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}}
.table-toolbar{{display:flex;gap:10px;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border);flex-wrap:wrap}}
.search-input{{background:var(--card2);border:1px solid var(--border);color:var(--text);padding:7px 12px;border-radius:20px;font-size:.78rem;outline:none;min-width:240px;flex:1;max-width:320px}}
.search-input::placeholder{{color:var(--muted)}}
.search-input:focus{{border-color:var(--accent)}}
table{{width:100%;border-collapse:collapse;font-size:.8rem}}
thead{{background:var(--surface)}}
th{{padding:10px 12px;text-align:left;font-size:.7rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid var(--border);cursor:pointer;user-select:none;white-space:nowrap}}
th:hover{{color:var(--text)}}
th.sorted{{color:var(--accent)}}
th .arr{{opacity:.6;margin-left:3px;font-size:.7rem}}
td{{padding:9px 12px;border-bottom:1px solid var(--border)}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:var(--card2)}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
td.title-cell{{max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.row-sig{{color:var(--green);font-weight:700}}
.row-hot{{color:var(--red);font-weight:700;font-size:.7rem}}
.row-drop{{color:var(--orange);font-weight:700;font-size:.7rem}}
.row-badges{{display:flex;gap:3px}}
.row-link{{color:var(--accent);font-size:.72rem;font-weight:700}}

.empty{{padding:40px;text-align:center;color:var(--muted);font-size:.85rem}}

@media (max-width:880px){{
  .market-grid{{grid-template-columns:1fr}}
  .page{{padding:18px 14px 40px}}
  .header{{padding:10px 14px;flex-direction:column;align-items:flex-start;gap:6px}}
  table{{font-size:.72rem}}
  th,td{{padding:6px 8px}}
  td.title-cell{{max-width:180px}}
}}

/* Lightbox Overlay */
.lightbox {{ display: none; position: fixed; z-index: 9999; padding-top: 50px; left: 0; top: 0; width: 100%; height: 100%; overflow: auto; background-color: rgba(0,0,0,0.9); }}
.lightbox-content {{ margin: auto; display: block; max-width: 90%; max-height: 90vh; object-fit: contain; cursor: default; }}
.lightbox-close {{ position: absolute; top: 15px; right: 35px; color: #f1f1f1; font-size: 40px; font-weight: bold; cursor: pointer; }}
.lightbox-close:hover, .lightbox-close:focus {{ color: #bbb; text-decoration: none; cursor: pointer; }}
.lightbox-btn {{ position: absolute; top: 50%; transform: translateY(-50%); background: rgba(0,0,0,0.5); color: white; border: none; font-size: 50px; cursor: pointer; padding: 10px 20px; z-index: 10000; user-select: none; border-radius: 5px; }}
.lightbox-btn:hover {{ background: rgba(0,0,0,0.8); }}
.lightbox-btn.prev {{ left: 20px; }}
.lightbox-btn.next {{ right: 20px; }}
</style>
</head>
<body>

<header class="header">
  <div class="header-left">
    <div class="logo">Radar <span>BDS</span></div>
    <div class="header-pills">
      <span class="pill">{n_total} listings</span>
      <span class="pill green">{n_signals} signals</span>
      {'<span class="pill red">' + str(n_hot) + ' hot</span>' if n_hot else ''}
      {'<span class="pill orange">' + str(n_drops) + ' giảm giá</span>' if n_drops else ''}
    </div>
  </div>
  <div class="header-right">Cập nhật: {generated_at}</div>
</header>

<main class="page">

  <!-- ═══ MARKET PULSE ═══ -->
  <section class="section">
    <div class="section-head">
      <div>
        <div class="kicker">Market Pulse</div>
        <div class="section-title">Tân An · Thủ Dầu Một</div>
      </div>
      <div class="section-sub">Median tính trên dữ liệu đã loại outlier</div>
    </div>
    <div class="market-grid" id="marketGrid"></div>
  </section>

  <!-- ═══ HEADLINE DEALS ═══ -->
  <section class="section" id="sec-headline">
    <div class="section-head">
      <div>
        <div class="kicker">Top Deals</div>
        <div class="section-title">⚡ 3 cơ hội đáng xem nhất<span class="count" id="headlineCount"></span></div>
      </div>
      <div class="section-sub">Xếp theo Signal Score × MOS%</div>
    </div>
    <div class="headline-grid" id="headlineGrid"></div>
  </section>

  <!-- ═══ ALL SIGNALS ═══ -->
  <section class="section" id="sec-signals">
    <div class="section-head">
      <div>
        <div class="kicker">Signals</div>
        <div class="section-title">Tất cả tin rẻ hơn thị trường<span class="count" id="signalsCount"></span></div>
      </div>
      <div class="section-sub">MOS ≥ 20% (fair value · Ridge regression)</div>
    </div>
    <div class="filters" id="sigFilters">
      <button class="fb active" data-filter="all">Tất cả</button>
      <button class="fb" data-filter="dat_nen">Đất nền</button>
      <button class="fb" data-filter="dat_vuon">Đất vườn</button>
      <button class="fb" data-filter="nha_dat">Nhà đất</button>
      <button class="fb" data-filter="hot">🔥 Hot</button>
      <button class="fb" data-filter="drop">💰 Giảm giá</button>
      <span class="filter-count" id="sigFilterCount"></span>
    </div>
    <div class="cards-grid" id="signalsGrid"></div>
    <div class="show-more-wrap" id="sigMoreWrap" style="display:none">
      <button class="show-more" id="sigMoreBtn">Xem thêm</button>
    </div>
  </section>

  <!-- ═══ DISTRIBUTION ═══ -->
  <section class="section">
    <div class="section-head">
      <div>
        <div class="kicker">Distribution</div>
        <div class="section-title">📊 Phân bố giá/m² theo phân khúc</div>
      </div>
      <div class="section-sub">Xem tin đang đứng ở đâu so với mặt bằng</div>
    </div>
    <div class="dist-wrap">
      <div class="dist-tabs" id="distTabs"></div>
      <div class="hist" id="histBars"></div>
      <div class="hist-axis" id="histAxis"></div>
      <div class="hist-legend">
        <span class="lg"><span class="dot blue"></span>Bình thường</span>
        <span class="lg"><span class="dot green"></span>Signal (≥20% dưới median)</span>
        <span class="lg"><span class="dot red"></span>Outlier</span>
      </div>
    </div>
  </section>

  <!-- ═══ FULL TABLE ═══ -->
  <section class="section" id="sec-table">
    <div class="section-head">
      <div>
        <div class="kicker">All Listings</div>
        <div class="section-title">📋 Toàn bộ tin đang rao<span class="count" id="tableCount"></span></div>
      </div>
      <div class="section-sub">Search theo tiêu đề · Click cột để sort</div>
    </div>
    <div class="filters" id="tblFilters">
      <button class="fb active" data-filter="all">Tất cả</button>
      <button class="fb" data-filter="signal">🟢 Signal</button>
      <button class="fb" data-filter="dat_nen">Đất nền</button>
      <button class="fb" data-filter="dat_vuon">Đất vườn</button>
      <button class="fb" data-filter="nha_dat">Nhà đất</button>
    </div>
    <div class="table-wrap">
      <div class="table-toolbar">
        <input type="text" class="search-input" id="tblSearch" placeholder="🔎 Tìm theo tiêu đề..." />
        <span class="filter-count" id="tblFilterCount"></span>
      </div>
      <div style="overflow-x:auto"><table id="tbl">
        <thead><tr>
          <th data-sort="prop_type">Loại</th>
          <th data-sort="price_ty" class="num">Tổng (tỷ)</th>
          <th data-sort="area_m2" class="num">DT (m²)</th>
          <th data-sort="price_per_m2" class="num sorted">Giá/m² ↑</th>
          <th data-sort="fair_ppm2" class="num">Fair</th>
          <th data-sort="mos_pct" class="num">MOS%</th>
          <th>Title</th>
          <th data-sort="days_ago" class="num">Ngày</th>
          <th data-sort="source">Nguồn</th>
          <th>Link</th>
        </tr></thead>
        <tbody id="tblBody"></tbody>
      </table></div>
    </div>
    <div class="show-more-wrap" id="tblMoreWrap" style="display:none">
      <button class="show-more" id="tblMoreBtn">Xem thêm</button>
    </div>
  </section>

  <!-- Lightbox Overlay -->
  <div id="lightbox" class="lightbox" onclick="closeLightbox()">
    <span class="lightbox-close">&times;</span>
    <button class="lightbox-btn prev" onclick="lbNav(event, -1)" id="lbPrev" style="display:none">‹</button>
    <img id="lightbox-img" class="lightbox-content" onclick="event.stopPropagation()">
    <button class="lightbox-btn next" onclick="lbNav(event, 1)" id="lbNext" style="display:none">›</button>
  </div>
</main>

<script>
const SIGNALS = {signals_json};
const ALL_LISTINGS = {all_json};
const MARKET = {market_json};

const PROP_LABELS = {{ dat_nen:'Đất nền', dat_vuon:'Đất vườn', nha_dat:'Nhà đất', khac:'Khác' }};
const PROP_CLASS  = {{ dat_vuon:'vuon', nha_dat:'nha' }};
const TIER_LABELS = {{ 1:'MT đường tên', 2:'MT/đường lớn', 3:'Ô tô/hẻm 5m+', 4:'Hẻm 3-5m', 5:'Hẻm <3m' }};

// ── Lightbox ───────────────────────────────
let lbImages = [];
let lbIndex = 0;

function openLightbox(imgElement) {{
  const wrap = imgElement.closest('.hcard-img-wrap, .sc-img-wrap');
  if (!wrap) {{
    document.getElementById('lightbox-img').src = imgElement.src;
    lbImages = [imgElement.src];
    lbIndex = 0;
  }} else {{
    const slides = Array.from(wrap.querySelectorAll('.slider-slide'));
    lbImages = slides.map(s => s.src);
    lbIndex = slides.indexOf(imgElement);
    document.getElementById('lightbox-img').src = lbImages[lbIndex];
  }}
  
  document.getElementById('lbPrev').style.display = lbImages.length > 1 ? 'block' : 'none';
  document.getElementById('lbNext').style.display = lbImages.length > 1 ? 'block' : 'none';
  document.getElementById('lightbox').style.display = 'block';
}}

function closeLightbox() {{
  document.getElementById('lightbox').style.display = 'none';
}}

function lbNav(e, dir) {{
  e.stopPropagation();
  if (lbImages.length <= 1) return;
  lbIndex = (lbIndex + dir + lbImages.length) % lbImages.length;
  document.getElementById('lightbox-img').src = lbImages[lbIndex];
}}

document.addEventListener('keydown', e => {{ 
  if(e.key === "Escape") closeLightbox(); 
  if(document.getElementById('lightbox').style.display === 'block') {{
    if(e.key === "ArrowLeft") lbNav(e, -1);
    if(e.key === "ArrowRight") lbNav(e, 1);
  }}
}});

// ── Market Pulse ────────────────────────────
function renderMarket() {{
  const g = document.getElementById('marketGrid');
  g.innerHTML = MARKET.map(m => `
    <div class="mcard ${{PROP_CLASS[m.type]||''}}">
      <div class="mc-label">${{m.label}}</div>
      <div><span class="mc-median">${{m.median}}</span><span class="mc-unit">tr/m²</span></div>
      <div class="mc-range"><span>Min <b>${{m.min_ppm2||'—'}}</b></span><span>Max <b>${{m.max_ppm2||'—'}}</b></span></div>
      <div class="mc-n">${{m.n}} tin trong mẫu</div>
    </div>`).join('');
}}

// ── Helpers ────────────────────────────────
function badges(x) {{
  const arr = [];
  if (x.source) {{
    let sname = x.source;
    if (sname === 'batdongsan') sname = 'BDS.com.vn';
    else if (sname === 'guland') sname = 'Guland';
    else if (sname === 'facebook') sname = 'Facebook';
    arr.push(`<span class="badge" style="background:#e8f0fe;color:#1a73e8;border:1px solid #d2e3fc">🌐 ${{sname}}</span>`);
  }}
  if (x.is_hot) arr.push(`<span class="badge hot">🔥 Hot</span>`);
  if (x.price_dropped) arr.push(`<span class="badge drop">💰 ${{x.drop_pct?Math.round(x.drop_pct)+'%':'Giảm'}}</span>`);
  if (x.road_tier === 1) arr.push(`<span class="badge tier1">Tier 1</span>`);
  else if (x.road_tier === 2) arr.push(`<span class="badge tier2">MT/đường lớn</span>`);
  else if (x.road_tier === 3) arr.push(`<span class="badge tier3">Ô tô vào</span>`);
  if (x.has_so) arr.push(`<span class="badge so">SHR</span>`);
  return arr.join('');
}}

function mosBarWidth(mos) {{ return Math.min(100, Math.max(0, mos*1.5)); }}

// ── Image Slider ────────────────────────────
function nextSlide(e, btn, dir) {{
  e.preventDefault(); e.stopPropagation();
  const wrap = btn.parentElement;
  const slides = wrap.querySelectorAll('.slider-slide');
  const dots = wrap.querySelectorAll('.slider-dot');
  let idx = Array.from(slides).findIndex(s => s.classList.contains('active'));
  slides[idx].classList.remove('active');
  if (dots.length) dots[idx].classList.remove('active');
  idx = (idx + dir + slides.length) % slides.length;
  slides[idx].classList.add('active');
  if (dots.length) dots[idx].classList.add('active');
}}
function changeSlide(e, dot, idx) {{
  e.preventDefault(); e.stopPropagation();
  const wrap = dot.parentElement.parentElement;
  const slides = wrap.querySelectorAll('.slider-slide');
  const dots = wrap.querySelectorAll('.slider-dot');
  let curr = Array.from(slides).findIndex(s => s.classList.contains('active'));
  slides[curr].classList.remove('active');
  dots[curr].classList.remove('active');
  slides[idx].classList.add('active');
  dots[idx].classList.add('active');
}}
function getSliderHtml(imgs, wrapClass, imgClass) {{
  if (!imgs || !imgs.length) return '';
  const slides = imgs.map((src, i) => `<img class="${{imgClass}} slider-slide ${{i===0?'active':''}}" src="${{src}}" alt="ảnh" loading="lazy" onerror="this.style.display='none'" onclick="openLightbox(this)" style="cursor:zoom-in;">`).join('');
  let ctrls = '';
  if (imgs.length > 1) {{
    const dots = imgs.map((_, i) => `<span class="slider-dot ${{i===0?'active':''}}" onclick="changeSlide(event, this, ${{i}})"></span>`).join('');
    ctrls = `
      <button class="slider-btn prev" onclick="nextSlide(event, this, -1)">‹</button>
      <button class="slider-btn next" onclick="nextSlide(event, this, 1)">›</button>
      <div class="slider-dots">${{dots}}</div>
    `;
  }}
  return `<div class="${{wrapClass}}">${{slides}}${{ctrls}}</div>`;
}}

// ── Headline Deals ──────────────────────────
function renderHeadline() {{
  // Top 3 signals by (signal_score * mos_pct)
  const signals = SIGNALS.filter(s => s.is_signal);
  signals.sort((a,b) => (b.signal_score * b.mos_pct) - (a.signal_score * a.mos_pct));
  const top3 = signals.slice(0, 3);
  document.getElementById('headlineCount').textContent = ` · ${{top3.length}}/${{signals.length}}`;
  const g = document.getElementById('headlineGrid');
  if (top3.length === 0) {{
    g.innerHTML = '<div class="empty">Chưa có deal nào đủ tiêu chí. Chạy crawl mới để cập nhật.</div>';
    return;
  }}
  g.innerHTML = top3.map((x, i) => `
    <div class="hcard">
      ${{getSliderHtml(x.imgs, 'hcard-img-wrap', 'hcard-img')}}
      <div class="rank">#${{i+1}}</div>
      <div class="hcard-body">
        <div class="hcard-top">
          <div>
            <div class="hcard-mos">-${{x.mos_pct}}<span class="pct">%</span></div>
            <div class="hcard-mos-lbl">Dưới fair value</div>
          </div>
          <div class="hcard-score">SCORE ${{x.signal_score}}</div>
        </div>
        <div class="hcard-title">${{x.title||'(không có tiêu đề)'}}</div>
        <div class="price-compare">
          <div class="pc-row"><span class="pc-label">Thực tế:</span><span class="pc-actual">${{x.actual_ppm2}}</span><span class="pc-unit">tr/m²</span></div>
          <div class="pc-row"><span class="pc-label">Định giá:</span><span class="pc-fair-val">${{x.fair_ppm2}}</span><span class="pc-unit">tr/m²</span></div>
        </div>
        <div class="hcard-bar"><div class="hcard-bar-fill" style="width:${{mosBarWidth(x.mos_pct)}}%"></div></div>
        <div class="hcard-meta">
          <span>📐 <b>${{x.area_m2||'—'}}</b> m²</span>
          <span>💵 <b>${{x.price_ty}}</b> tỷ</span>
          <span>📍 ${{x.ward||'Tân An'}}</span>
          <span>🗓 ${{x.days_ago}} ngày</span>
          ${{x.seller_name ? `<span>👤 ${{x.seller_name}}</span>` : ''}}
        </div>
        <div class="hcard-badges">${{badges(x)}}</div>
        <a class="hcard-link" href="${{x.url}}" target="_blank" rel="noopener">Xem tin →</a>
      </div>
    </div>`).join('');
}}

// ── All Signals ─────────────────────────────
let sigFilter = 'all';
let sigShown = 6;
const SIG_PAGE = 6;

function filteredSignals() {{
  const base = SIGNALS.filter(s => s.is_signal);
  if (sigFilter === 'all') return base;
  if (sigFilter === 'hot')  return base.filter(s => s.is_hot);
  if (sigFilter === 'drop') return base.filter(s => s.price_dropped);
  return base.filter(s => s.prop_type === sigFilter);
}}

function renderSignalCard(x) {{
  return `
    <div class="scard">
      ${{getSliderHtml(x.imgs, 'sc-img-wrap', 'sc-img')}}
      <div class="sc-top">
        <div>
          <div class="sc-mos">-${{x.mos_pct}}<span class="pct">%</span></div>
          <div class="sc-mos-lbl">${{PROP_LABELS[x.prop_type]||x.prop_type}}</div>
        </div>
        <div class="sc-score">${{x.signal_score}}</div>
      </div>
      <div class="sc-title">${{x.title||'(không có tiêu đề)'}}</div>
      <div class="sc-price">
        <div class="sc-price-row"><span class="sc-price-label">Thực tế:</span><span class="sc-actual">${{x.actual_ppm2}}</span> <span class="sc-price-label">tr/m²</span></div>
        <div class="sc-price-row"><span class="sc-price-label">Định giá:</span><span class="sc-fair">${{x.fair_ppm2}}</span> <span class="sc-price-label">tr/m²</span></div>
      </div>
      <div class="sc-bar"><div class="sc-bar-fill" style="width:${{mosBarWidth(x.mos_pct)}}%"></div></div>
      <div class="sc-meta">
        <span>📐 <b>${{x.area_m2||'—'}}</b>m²</span>
        <span>💵 <b>${{x.price_ty}}</b>T</span>
        <span>🗓 ${{x.days_ago}}d</span>
        <span>📍 ${{x.ward||'—'}}</span>
        ${{x.seller_name ? `<span>👤 ${{x.seller_name}}</span>` : ''}}
      </div>
      <div class="sc-bottom">
        <div class="sc-badges">${{badges(x)}}</div>
        <a class="sc-link" href="${{x.url}}" target="_blank" rel="noopener">Xem →</a>
      </div>
    </div>`;
}}

function renderSignals() {{
  const list  = filteredSignals();
  const total = list.length;
  const show  = Math.min(sigShown, total);
  const g     = document.getElementById('signalsGrid');
  g.innerHTML = list.slice(0, show).map(renderSignalCard).join('') || '<div class="empty">Không có signal nào khớp bộ lọc.</div>';
  document.getElementById('signalsCount').textContent = ` · ${{show}}/${{total}}`;
  document.getElementById('sigFilterCount').textContent = `Hiển thị ${{show}}/${{total}}`;
  const wrap = document.getElementById('sigMoreWrap');
  const btn  = document.getElementById('sigMoreBtn');
  if (total > sigShown) {{
    wrap.style.display = 'flex';
    btn.textContent = `Xem thêm (${{total - sigShown}})`;
  }} else if (sigShown > SIG_PAGE && total <= sigShown) {{
    wrap.style.display = 'flex';
    btn.textContent = `Thu gọn`;
  }} else {{
    wrap.style.display = 'none';
  }}
}}

document.getElementById('sigFilters').addEventListener('click', e => {{
  if (!e.target.matches('.fb')) return;
  document.querySelectorAll('#sigFilters .fb').forEach(b => b.classList.remove('active'));
  e.target.classList.add('active');
  sigFilter = e.target.dataset.filter;
  sigShown  = SIG_PAGE;
  renderSignals();
}});

document.getElementById('sigMoreBtn').addEventListener('click', () => {{
  const total = filteredSignals().length;
  if (sigShown >= total) sigShown = SIG_PAGE;
  else                   sigShown = Math.min(total, sigShown + SIG_PAGE * 2);
  renderSignals();
}});

// ── Distribution chart ──────────────────────
let distType = 'dat_nen';

function renderDistTabs() {{
  // Logic giá trị: chỉ update class .active, không innerHTML → listener đã attach giữ nguyên
  const tabs = document.getElementById('distTabs');
  if (!tabs.dataset.inited) {{
    tabs.innerHTML = MARKET.map(m =>
      `<button class="dist-tab" data-type="${{m.type}}">${{m.label}} (${{m.n}})</button>`
    ).join('');
    tabs.dataset.inited = '1';
  }}
  tabs.querySelectorAll('.dist-tab').forEach(b => {{
    b.classList.toggle('active', b.dataset.type === distType);
  }});
}}

function renderHistogram() {{
  const items  = ALL_LISTINGS.filter(l => l.prop_type === distType && l.price_per_m2);
  if (!items.length) {{
    document.getElementById('histBars').innerHTML = '<div class="empty">Không có dữ liệu</div>';
    document.getElementById('histAxis').innerHTML = '';
    return;
  }}
  const vals = items.map(l => l.price_per_m2);
  const min  = Math.floor(Math.min(...vals));
  const max  = Math.ceil(Math.max(...vals));
  const m    = MARKET.find(x => x.type === distType);
  const median = m ? m.median : (min+max)/2;

  const BINS = 18;
  const step = (max - min) / BINS || 1;
  const bins = Array.from({{length: BINS}}, () => ({{sig:0, out:0, norm:0}}));
  items.forEach(l => {{
    let idx = Math.min(BINS-1, Math.floor((l.price_per_m2 - min) / step));
    if (idx < 0) idx = 0;
    if (l.is_signal) bins[idx].sig++;
    else if (Math.abs(l.price_per_m2 - median) / median > 0.6) bins[idx].out++;
    else bins[idx].norm++;
  }});
  const maxCount = Math.max(...bins.map(b => b.sig + b.out + b.norm)) || 1;

  const barsEl = document.getElementById('histBars');
  // Median line position
  const medianPct = ((median - min) / (max - min)) * 100;
  barsEl.innerHTML = `<div class="hist-median" style="left:${{medianPct}}%"></div>` +
    bins.map((b, i) => {{
      const total = b.sig + b.out + b.norm;
      const h = total > 0 ? (total / maxCount) * 100 : 0;
      const cls = b.sig > 0 ? 'signal' : (b.out > 0 ? 'outlier' : '');
      const lo = (min + i*step).toFixed(1);
      const hi = (min + (i+1)*step).toFixed(1);
      return `<div class="hist-bar ${{cls}}" style="height:${{h}}%" data-label="${{lo}}-${{hi}} tr/m² · ${{total}} tin${{b.sig?' · '+b.sig+' signal':''}}"></div>`;
    }}).join('');
  document.getElementById('histAxis').innerHTML = `<span>${{min}}</span><span>${{Math.round((min+max)/2)}}</span><span>${{max}} tr/m²</span>`;
}}

// ── Full Table ──────────────────────────────
let tblFilter = 'all';
let tblSearch = '';
let tblSort   = {{key:'price_per_m2', dir:1}};
let tblShown  = 40;
const TBL_PAGE = 40;

function filteredTable() {{
  let list = [...ALL_LISTINGS];
  if (tblFilter === 'signal')         list = list.filter(l => l.is_signal);
  else if (tblFilter === 'dat_nen')   list = list.filter(l => l.prop_type === 'dat_nen');
  else if (tblFilter === 'dat_vuon')  list = list.filter(l => l.prop_type === 'dat_vuon');
  else if (tblFilter === 'nha_dat')   list = list.filter(l => l.prop_type === 'nha_dat');
  if (tblSearch) {{
    const q = tblSearch.toLowerCase();
    list = list.filter(l => (l.title||'').toLowerCase().includes(q));
  }}
  list.sort((a,b) => {{
    const av = a[tblSort.key], bv = b[tblSort.key];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'string') return av.localeCompare(bv) * tblSort.dir;
    return (av - bv) * tblSort.dir;
  }});
  return list;
}}

function renderTable() {{
  const list  = filteredTable();
  const total = list.length;
  const show  = Math.min(tblShown, total);
  const rows  = list.slice(0, show).map(l => {{
    const sigMark = l.is_signal ? `<span class="row-sig">-${{l.mos_pct}}%</span>` : '';
    const hot    = l.is_hot ? `<span class="row-hot">🔥</span>` : '';
    const drop   = l.price_dropped ? `<span class="row-drop">💰</span>` : '';
    // Logic giá trị: so sánh ppm2 vs fair → màu (green=rẻ, red=mắc, muted=xấp xỉ)
    let fairCell = '<span style="color:var(--muted2)">—</span>';
    if (l.fair_ppm2 && l.price_per_m2) {{
      const delta = ((l.price_per_m2 - l.fair_ppm2) / l.fair_ppm2) * 100;
      const color = delta < -10 ? 'var(--green)' : (delta > 10 ? 'var(--red)' : 'var(--muted)');
      fairCell = `<span style="color:${{color}}">${{l.fair_ppm2}}</span>`;
    }}
    let sname = l.source;
    if (sname === 'batdongsan') sname = 'BDS.com.vn';
    else if (sname === 'guland') sname = 'Guland';
    else if (sname === 'facebook') sname = 'Facebook';
    if (l.seller_name) sname += `<br><small style="color:var(--muted);white-space:nowrap">👤 ${{l.seller_name}}</small>`;

    return `<tr>
      <td>${{PROP_LABELS[l.prop_type]||l.prop_type}}</td>
      <td class="num"><b>${{l.price_ty||'—'}}</b></td>
      <td class="num">${{l.area_m2||'—'}}</td>
      <td class="num">${{l.price_per_m2||'—'}}</td>
      <td class="num">${{fairCell}}</td>
      <td class="num">${{sigMark||''}}</td>
      <td class="title-cell" title="${{(l.title||'').replace(/"/g,'&quot;')}}">${{l.title||'(—)'}}  <span class="row-badges">${{hot}}${{drop}}</span></td>
      <td class="num">${{l.days_ago}}d</td>
      <td>${{sname}}</td>
      <td><a class="row-link" href="${{l.url}}" target="_blank" rel="noopener">Xem</a></td>
    </tr>`;
  }}).join('');
  document.getElementById('tblBody').innerHTML = rows || '<tr><td colspan="10" class="empty">Không có dữ liệu khớp.</td></tr>';
  document.getElementById('tableCount').textContent = ` · ${{show}}/${{total}}`;
  document.getElementById('tblFilterCount').textContent = `Hiển thị ${{show}}/${{total}}`;
  const wrap = document.getElementById('tblMoreWrap');
  const btn  = document.getElementById('tblMoreBtn');
  if (total > tblShown) {{
    wrap.style.display = 'flex';
    btn.textContent = `Xem thêm (${{total - tblShown}})`;
  }} else if (tblShown > TBL_PAGE && total <= tblShown) {{
    wrap.style.display = 'flex';
    btn.textContent = 'Thu gọn';
  }} else {{
    wrap.style.display = 'none';
  }}
  // Update sort markers
  document.querySelectorAll('#tbl th').forEach(th => {{
    th.classList.remove('sorted');
    const arrSpan = th.querySelector('.arr'); if (arrSpan) arrSpan.remove();
  }});
  const activeTh = document.querySelector(`#tbl th[data-sort="${{tblSort.key}}"]`);
  if (activeTh) {{
    activeTh.classList.add('sorted');
    const arr = document.createElement('span');
    arr.className = 'arr';
    arr.textContent = tblSort.dir === 1 ? '↑' : '↓';
    activeTh.appendChild(arr);
  }}
}}

document.getElementById('tblFilters').addEventListener('click', e => {{
  if (!e.target.matches('.fb')) return;
  document.querySelectorAll('#tblFilters .fb').forEach(b => b.classList.remove('active'));
  e.target.classList.add('active');
  tblFilter = e.target.dataset.filter;
  tblShown  = TBL_PAGE;
  renderTable();
}});

document.getElementById('tblSearch').addEventListener('input', e => {{
  tblSearch = e.target.value;
  tblShown  = TBL_PAGE;
  renderTable();
}});

document.querySelectorAll('#tbl th[data-sort]').forEach(th => {{
  th.addEventListener('click', () => {{
    const key = th.dataset.sort;
    if (tblSort.key === key) tblSort.dir *= -1;
    else tblSort = {{key, dir: 1}};
    renderTable();
  }});
}});

document.getElementById('tblMoreBtn').addEventListener('click', () => {{
  const total = filteredTable().length;
  if (tblShown >= total) tblShown = TBL_PAGE;
  else                   tblShown = Math.min(total, tblShown + TBL_PAGE * 2);
  renderTable();
  if (tblShown === TBL_PAGE) document.getElementById('sec-table').scrollIntoView({{behavior:'smooth', block:'start'}});
}});
document.getElementById('distTabs').addEventListener('click', e => {{
  if (!e.target.matches('.dist-tab')) return;
  distType = e.target.dataset.type;
  renderDistTabs();
  renderHistogram();
}});

// ── Init ────────────────────────────────────
renderMarket();
renderHeadline();
renderSignals();
renderDistTabs();
renderHistogram();
renderTable();
</script>
</body>
</html>
"""


# ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",     default=None,                          help="Deprecated; runtime uses DATABASE_URL")
    parser.add_argument("--output", default="dashboard_signals.html",      help="Output HTML path")
    args = parser.parse_args()

    if args.db is None:
        args.db = ""

    data = load_data(args.db)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = build_html(data, generated_at)

    out_path = Path(args.output)
    out_path.write_text(html, encoding="utf-8")
    print(f"Dashboard saved -> {out_path.resolve()}")


if __name__ == "__main__":
    main()
