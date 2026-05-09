import os
import json
import sqlite3
import logging
import statistics
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from config import database_sqlite as db_mod

# Import the extracted services
from services.market_data import load_data, load_trend_data, load_listing_detail, get_base_filters, get_city_for_ward, CITY_MAP, _days_ago, resolve_image_url
from services.ai_bot import AIBot

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Serve local downloaded images (data/images/<filename>)
_DATA_IMAGES_DIR = Path(__file__).parent / "data" / "images"

@app.route("/data/images/<path:filename>")
def serve_local_image(filename):
    return send_from_directory(_DATA_IMAGES_DIR, filename)

@app.route("/")
def index():
    return render_template('index.html')

@app.route("/api/dashboard")
def api_dashboard():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    db_path = str(db_mod.DB_PATH.resolve())
    include_trend = request.args.get("include_trend") == "1"
    # Load data without fetching all listings to save time/memory
    data = load_data(db_path, sources, wards, prop_types, only_drops, trend_period, skip_listings=True, include_trend=include_trend, mos_min=mos_min)
    
    return jsonify({
        "stats": data["stats"],
        "signals": data["signals"],
        "market": data["market"],
        "trend_data": data["trend_data"],
        "all_wards": data["all_wards"],
        "all_sources": data["all_sources"],
        "wards_by_city": data["wards_by_city"],
        "active_city": active_city,
        "active_wards": wards,
        "active_sources": sources,
        "active_props": prop_types,
        "trend_period": trend_period
    })

@app.route("/api/trends")
def api_trends():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    db_path = str(db_mod.DB_PATH.resolve())
    return jsonify({
        "trend_data": load_trend_data(db_path, sources, wards, prop_types, only_drops, trend_period),
        "trend_period": trend_period
    })

@app.route('/api/heatmap')
def api_heatmap():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    db_path = str(db_mod.DB_PATH.resolve())
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    where_parts = ["l.probably_sold = 0", "l.price_per_m2 > 0", "l.price_per_m2 < 1000"]
    if only_drops:
        where_parts.append("l.price_dropped = 1")
    else:
        where_parts.append("l.possibly_duplicate = 0")
    params = []
    
    # Filter by city if no specific wards selected
    if not wards and active_city and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]

    if wards:
        where_parts.append(f"l.ward IN ({','.join(['?']*len(wards))})")
        params.extend(wards)
    if sources:
        where_parts.append(f"l.source IN ({','.join(['?']*len(sources))})")
        params.extend(sources)
    if prop_types:
        where_parts.append(f"l.property_type IN ({','.join(['?']*len(prop_types))})")
        params.extend(prop_types)
    where_sql = " AND ".join(where_parts)
    
    # Market fields use all valid listings; opportunity fields use signal deals only.
    query = f"""
        SELECT l.ward,
               l.price_per_m2,
               l.price_ty,
               l.area_m2,
               v.fair_ppm2,
               v.mos_pct,
               COALESCE(v.is_signal, 0) as is_signal,
               COALESCE(v.is_outlier, 0) as is_outlier
        FROM listings l
        LEFT JOIN valuation_results v ON l.id = v.listing_id
        WHERE {where_sql}
          AND l.ward IS NOT NULL
          AND l.ward != 'unknown'
          AND COALESCE(v.is_outlier, 0) = 0
    """
    rows = conn.execute(query, params).fetchall()
    conn.close()

    grouped = {}
    for r in rows:
        ward = r["ward"]
        item = grouped.setdefault(ward, {
            "prices": [],
            "price_tys": [],
            "fair_tys": [],
            "signal_mos": []
        })
        item["prices"].append(r["price_per_m2"])
        if r["price_ty"]:
            item["price_tys"].append(r["price_ty"])
        if r["fair_ppm2"] and r["area_m2"]:
            item["fair_tys"].append(r["fair_ppm2"] * r["area_m2"] / 1000)
        if r["is_signal"] == 1 and r["mos_pct"] and r["mos_pct"] > 0:
            item["signal_mos"].append(r["mos_pct"])

    heatmap_data = []
    for ward, g in grouped.items():
        total_count = len(g["prices"])
        deal_count = len(g["signal_mos"])
        median_mos = round(statistics.median(g["signal_mos"]), 1) if g["signal_mos"] else 0
        avg_signal_mos = round(sum(g["signal_mos"]) / deal_count, 1) if deal_count else 0
        signal_rate = round((deal_count / total_count) * 100, 1) if total_count else 0
        heatmap_data.append({
            "ward": ward,
            "total_count": total_count,
            "deal_count": deal_count,
            "median_mos": median_mos,
            "avg_signal_mos": avg_signal_mos,
            "signal_rate": signal_rate,
            "count": deal_count,
            "avg_price": round(sum(g["prices"]) / total_count, 1) if total_count else 0,
            "avg_mos": median_mos,
            "avg_price_ty": round(sum(g["price_tys"]) / len(g["price_tys"]), 2) if g["price_tys"] else 0,
            "avg_fair_ty": round(sum(g["fair_tys"]) / len(g["fair_tys"]), 2) if g["fair_tys"] else 0
        })

    heatmap_data.sort(key=lambda x: (x["deal_count"], x["median_mos"]), reverse=True)
    return jsonify(heatmap_data)

@app.route('/api/listings')
def api_listings():
    active_city, wards, sources, prop_types, only_drops, trend_period, mos_min = get_base_filters(request)
    if not wards and active_city in CITY_MAP:
        wards = CITY_MAP[active_city]
    try:
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 50))
        area_min = float(request.args.get("area_min") or 0)
        area_max = float(request.args.get("area_max") or 0)
        price_min = float(request.args.get("price_min") or 0)
        price_max = float(request.args.get("price_max") or 0)
    except ValueError:
        page, limit = 1, 50
        area_min = area_max = price_min = price_max = 0
    offset = (page - 1) * limit
    
    db_path = str(db_mod.DB_PATH.resolve())
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    where_parts = ["probably_sold = 0"]
    if only_drops:
        where_parts.append("price_dropped = 1")
    else:
        where_parts.append("possibly_duplicate = 0")
    params = []
    
    if wards:
        where_parts.append(f"ward IN ({','.join(['?']*len(wards))})")
        params.extend(wards)
    if sources:
        where_parts.append(f"source IN ({','.join(['?']*len(sources))})")
        params.extend(sources)
    if prop_types:
        where_parts.append(f"property_type IN ({','.join(['?']*len(prop_types))})")
        params.extend(prop_types)
    if only_drops:
        where_parts.append("price_dropped = 1")
        
    where_sql = " AND ".join(where_parts)

    sort_col_map = {
        "area": "l.area_m2", "price": "l.price_ty", "price_m2": "l.price_per_m2",
        "fair": "v.fair_ppm2", "date": "COALESCE(l.posted_at, l.crawled_at)",
        "ward": "l.ward", "prop_type": "l.property_type",
    }
    sort_by = request.args.get("sort_by", "price_m2")
    sort_dir = "DESC" if request.args.get("sort_dir", "asc").lower() == "desc" else "ASC"
    order_expr = sort_col_map.get(sort_by, "l.price_per_m2")

    query = f"""
        SELECT l.*, v.is_signal, v.mos_pct, v.fair_ppm2, v.signal_score
        FROM listings l
        LEFT JOIN valuation_results v ON l.id = v.listing_id
        WHERE {where_sql}
        ORDER BY {order_expr} {sort_dir} NULLS LAST
        LIMIT ? OFFSET ?
    """
    query_params = list(params)
    query_params.extend([limit, offset])
    rows = conn.execute(query, query_params).fetchall()
    
    count_query = f"SELECT COUNT(*) FROM listings WHERE {where_sql}"
    total = conn.execute(count_query, params).fetchone()[0]
    
    listing_ids = [r['id'] for r in rows]
    from collections import defaultdict
    img_map = defaultdict(list)
    if listing_ids:
        placeholders = ",".join("?" * len(listing_ids))
        img_rows = conn.execute(f"""
            SELECT listing_id, local_path, img_url
            FROM listing_images
            WHERE listing_id IN ({placeholders})
            ORDER BY listing_id, img_order
        """, listing_ids).fetchall()
        for r in img_rows:
            url = resolve_image_url(r[1], r[2])
            if url:
                img_map[r[0]].append(url)
        
    conn.close()
    
    listings = [{
        "id": r['id'], "title": r['title'], "description": r['description'] or "",
        "price_ty": r['price_ty'], "area_m2": r['area_m2'],
        "price_per_m2": round(r['price_per_m2'],1) if r['price_per_m2'] else None, "prop_type": r['property_type'],
        "ward": r['ward'], "url": r['url'], "is_signal": bool(r['is_signal']), "mos_pct": round(r['mos_pct'],1) if r['mos_pct'] else 0,
        "fair_ppm2": round(r['fair_ppm2'],1) if r['fair_ppm2'] else None,
        "days_ago": _days_ago(r['posted_at'] or r['crawled_at']), "is_hot": bool(r['is_hot']), "price_dropped": bool(r['price_dropped']),
        "source": r['source'], "imgs": img_map.get(r['id'], [])
    } for r in rows]
    
    return jsonify({
        "listings": listings,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit > 0 else 1
    })

@app.route('/listing/<int:listing_id>')
def listing_detail(listing_id):
    db_path = str(db_mod.DB_PATH.resolve())
    data = load_listing_detail(db_path, listing_id)
    if not data:
        return "Listing not found", 404
    
    l = data["listing"]
    imgs = data["images"]
    history_json = json.dumps(data["history"], ensure_ascii=False)
    desc_html = l.get('description', '').replace('\n', '<br>') if l.get('description') else 'Không có mô tả.'
    
    return render_template('listing_detail.html', l=l, imgs=imgs, history_json=history_json, desc_html=desc_html)

@app.route('/api/history/<int:listing_id>')
def get_price_history(listing_id):
    with db_mod.get_conn() as conn:
        rows = conn.execute("""
            SELECT recorded_at, price_ty, price_per_m2
            FROM price_history
            WHERE listing_id = ?
            ORDER BY recorded_at ASC, id ASC
        """, (listing_id,)).fetchall()
        curr = conn.execute("SELECT updated_at, price_ty, ward, area_m2, property_type FROM listings WHERE id = ?", (listing_id,)).fetchone()
        history = []
        last_price = None
        has_last = False
        for r in rows:
            price_ty = r[1]
            same_as_last = has_last and _same_price_value(price_ty, last_price)
            if same_as_last:
                continue
            history.append({'date': (r[0] or '')[:10], 'price_ty': price_ty})
            last_price = price_ty
            has_last = True

        if curr and curr[1]:
            current_price = curr[1]
            if not history or not _same_price_value(history[-1]['price_ty'], current_price):
                history.append({'date': (curr[0] or '')[:10], 'price_ty': current_price})

        comps = []
        if curr and curr[2]:
            ward = curr[2]
            area = curr[3] or 0
            comp_rows = conn.execute("""
                SELECT title, price_ty, area_m2, COALESCE(posted_at, crawled_at) as dt
                FROM listings
                WHERE ward = ? AND id != ? AND price_ty > 0 AND probably_sold = 0
                  AND area_m2 BETWEEN ? AND ?
                ORDER BY COALESCE(posted_at, crawled_at) DESC LIMIT 3
            """, (ward, listing_id, area * 0.6, area * 1.5)).fetchall()
            for c in comp_rows:
                comps.append({
                    'title': (c[0] or '')[:40],
                    'price_ty': c[1],
                    'area_m2': c[2],
                    'date': (c[3] or '')[:7]
                })

        return jsonify({'history': history, 'comps': comps})

def _same_price_value(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) < 0.000001

@app.route("/review")
def review_list():
    ward = (request.args.get("ward") or "").strip()
    try:
        min_score = int(request.args.get("min_score", "55"))
    except ValueError:
        min_score = 55
    try:
        limit = int(request.args.get("limit", "500"))
    except ValueError:
        limit = 500

    sql = """
        SELECT l.id, l.title, l.url, l.price_ty, l.area_m2, l.ward,
               l.property_type, l.road_tier, l.has_so, l.source,
               l.description,
               v.mos_pct, v.signal_score, v.fair_ppm2, v.actual_ppm2,
               v.segment, v.n_segment,
               f.verdict
          FROM listings l
          JOIN valuation_results v ON v.listing_id = l.id
          LEFT JOIN signal_feedback f ON f.listing_id = l.id
         WHERE v.is_signal = 1
           AND COALESCE(l.probably_sold, 0) = 0
           AND (f.verdict IS NULL OR f.verdict = 'maybe')
           AND COALESCE(v.signal_score, 0) >= ?
    """
    params = [min_score]
    if ward:
        sql += " AND l.ward = ?"
        params.append(ward)
    sql += " ORDER BY COALESCE(v.signal_score, 0) DESC, v.mos_pct DESC"
    if limit > 0:
        sql += f" LIMIT {limit}"

    with db_mod.get_conn() as c:
        rows = c.execute(sql, params).fetchall()
        ward_opts = [r[0] for r in c.execute("""
            SELECT l.ward, COUNT(*) AS n
              FROM listings l
              JOIN valuation_results v ON v.listing_id = l.id
              LEFT JOIN signal_feedback f ON f.listing_id = l.id
             WHERE v.is_signal = 1
               AND COALESCE(l.probably_sold, 0) = 0
               AND (f.verdict IS NULL OR f.verdict = 'maybe')
               AND l.ward IS NOT NULL
             GROUP BY l.ward
             ORDER BY n DESC
        """).fetchall()]
        listing_ids = [r["id"] for r in rows]
        images_by_id = {}
        if listing_ids:
            placeholders = ",".join("?" * len(listing_ids))
            img_rows = c.execute(
                f"SELECT listing_id, COALESCE(local_path, img_url) FROM listing_images "
                f"WHERE listing_id IN ({placeholders}) ORDER BY listing_id, img_order",
                listing_ids
            ).fetchall()
            for lid, url in img_rows:
                images_by_id.setdefault(lid, []).append(url)
    rows = [dict(r) for r in rows]
    for r in rows:
        r["images"] = images_by_id.get(r["id"], [])
    return render_template('review.html', rows=rows, ward=ward, ward_opts=ward_opts, min_score=min_score)

@app.route("/review/<int:listing_id>", methods=["POST"])
def review_submit(listing_id):
    verdict = request.form.get("verdict")
    reason = (request.form.get("reason") or "").strip()
    if verdict not in ("good", "bad", "maybe", "sold", "spam"):
        return jsonify({"error": "invalid verdict"}), 400
    with db_mod.get_conn() as c:
        snap = c.execute("""
            SELECT v.mos_pct, v.signal_score,
                   (COALESCE(l.ward,'?') || '|' || COALESCE(l.property_type,'?') || '|' ||
                    COALESCE(l.road_tier, 0)) AS seg
              FROM valuation_results v
              JOIN listings l ON l.id = v.listing_id
             WHERE v.listing_id=?
        """, (listing_id,)).fetchone()
        c.execute("""
            INSERT INTO signal_feedback
              (listing_id, verdict, reason_text, snapshot_mos, snapshot_score, snapshot_segment)
            VALUES (?,?,?,?,?,?)
        """, (
            listing_id, verdict, reason or None,
            snap["mos_pct"] if snap else None,
            snap["signal_score"] if snap else None,
            snap["seg"] if snap else None,
        ))
        c.commit()
    return jsonify({"ok": True})

@app.route("/review/stats")
def review_stats():
    with db_mod.get_conn() as c:
        summary = c.execute("""
            SELECT verdict, COUNT(*) AS n FROM signal_feedback
             GROUP BY verdict ORDER BY n DESC
        """).fetchall()
        segments = []
        for r in c.execute("""
            SELECT snapshot_segment AS seg,
                   SUM(CASE WHEN verdict='good' THEN 1 ELSE 0 END) AS g,
                   SUM(CASE WHEN verdict IN ('bad','spam') THEN 1 ELSE 0 END) AS bs,
                   COUNT(*) AS n
              FROM signal_feedback
             WHERE snapshot_segment IS NOT NULL
             GROUP BY snapshot_segment
            HAVING n >= 3
             ORDER BY n DESC
        """):
            reject_pct = (r["bs"] / r["n"]) * 100 if r["n"] else 0
            adj = -round(reject_pct / 100 * 30) if r["n"] >= 5 else 0
            segments.append({"seg": r["seg"], "n": r["n"], "g": r["g"],
                             "bs": r["bs"], "reject_pct": reject_pct, "adj": adj})
        rules = c.execute("""
            SELECT id, rule_text, rule_sql, confidence, sample_size,
                   enabled, last_used_at FROM feedback_rules
             ORDER BY enabled DESC, created_at DESC
        """).fetchall()
        rules = [dict(r) for r in rules]
    return render_template('review_stats.html', summary=summary, segments=segments, rules=rules)

@app.route("/review/rule/<int:rule_id>/toggle", methods=["POST"])
def review_rule_toggle(rule_id):
    with db_mod.get_conn() as c:
        cur = c.execute("SELECT enabled FROM feedback_rules WHERE id=?", (rule_id,)).fetchone()
        if not cur:
            return jsonify({"error": "not found"}), 404
        new_val = 0 if cur["enabled"] else 1
        c.execute("UPDATE feedback_rules SET enabled=? WHERE id=?", (new_val, rule_id))
        c.commit()
    return jsonify({"ok": True, "enabled": bool(new_val)})

@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json
    message = data.get("message")
    history = data.get("history", [])
    
    if not message:
        return jsonify({"error": "No message provided"}), 400
        
    db_path = str(db_mod.DB_PATH.resolve())
    bot = AIBot(db_path)
    response = bot.chat(message, history)
    
    return jsonify({"response": response})

def ensure_perf_indexes():
    with db_mod.get_conn() as conn:
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_listings_filter_fast
            ON listings(ward, source, property_type, probably_sold, possibly_duplicate)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_listings_ward_ppm2
            ON listings(ward, price_per_m2)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_images_listing_order
            ON listing_images(listing_id, img_order)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_valuation_signal_score
            ON valuation_results(is_signal, signal_score DESC, mos_pct DESC)
        """)
        conn.commit()

if __name__ == "__main__":
    ensure_perf_indexes()
    app.run(host="127.0.0.1", port=5000, debug=True)
