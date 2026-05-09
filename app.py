import os
import json
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from config import database_sqlite as db_mod

# Import the extracted services
from services.market_data import load_data, load_listing_detail, get_base_filters, get_city_for_ward, CITY_MAP, _days_ago
from services.ai_bot import AIBot

app = Flask(__name__)
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
    try:
        active_city, wards, sources, prop_types, only_drops, trend_period, discount_min, sort_by = get_base_filters(request)
        db_path = str(db_mod.DB_PATH.resolve())
        # Load data
        data = load_data(db_path, sources, wards, prop_types, only_drops, trend_period, skip_listings=False, discount_min=discount_min, sort_by=sort_by)
        
        return jsonify({
            "stats": data["stats"],
            "signals": data["signals"],
            "market": data["market"],
            "ward_stats": data["ward_stats"],
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
    except Exception as e:
        logger.error(f"Dashboard API Error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/heatmap')
def api_heatmap():
    active_city, wards, sources, prop_types, only_drops, trend_period, discount_min, sort_by = get_base_filters(request)
    db_path = str(db_mod.DB_PATH.resolve())
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    where_parts = ["probably_sold = 0", "possibly_duplicate = 0", "price_per_m2 > 0", "price_per_m2 < 1000"]
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
    if only_drops:
        where_parts.append("l.price_dropped = 1")
        
    where_sql = " AND ".join(where_parts)
    
    # Join with valuation_results to filter outliers and get real MOS
    query = f"""
        SELECT l.ward, COUNT(*) as count, 
               AVG(l.price_per_m2) as avg_price,
               AVG(v.mos_pct) as avg_mos
        FROM listings l
        LEFT JOIN valuation_results v ON l.id = v.listing_id
        WHERE {where_sql} 
          AND l.ward IS NOT NULL 
          AND l.ward != 'unknown'
          AND COALESCE(v.is_outlier, 0) = 0
        GROUP BY l.ward
        HAVING count > 0
    """
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    heatmap_data = [{
        "ward": r["ward"], 
        "count": r["count"], 
        "avg_price": round(r["avg_price"], 1) if r["avg_price"] else 0,
        "avg_mos": round(r["avg_mos"], 1) if r["avg_mos"] else 0
    } for r in rows]
    return jsonify(heatmap_data)

@app.route('/api/listings')
def api_listings():
    active_city, wards, sources, prop_types, only_drops, trend_period = get_base_filters(request)
    try:
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 50))
    except ValueError:
        page, limit = 1, 50
    offset = (page - 1) * limit
    
    db_path = str(db_mod.DB_PATH.resolve())
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    where_parts = ["probably_sold = 0", "possibly_duplicate = 0"]
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
    
    query = f"""
        SELECT l.*, v.is_signal, v.mos_pct, v.fair_ppm2, v.signal_score
        FROM listings l
        LEFT JOIN valuation_results v ON l.id = v.listing_id
        WHERE {where_sql}
        ORDER BY l.price_per_m2 ASC
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
        img_rows = conn.execute(f"SELECT listing_id, COALESCE(local_path, img_url) FROM listing_images WHERE listing_id IN ({placeholders}) ORDER BY listing_id, img_order", listing_ids).fetchall()
        for r in img_rows: img_map[r[0]].append(r[1])
        
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

@app.route('/api/comps/<int:listing_id>')
def api_comps(listing_id):
    db_path = str(db_mod.DB_PATH.resolve())
    from services.market_data import get_comps
    comps = get_comps(db_path, listing_id)
    return jsonify(comps)

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
        rows = conn.execute("SELECT recorded_at, price_ty FROM price_history WHERE listing_id = ? ORDER BY recorded_at ASC", (listing_id,)).fetchall()
        curr = conn.execute("SELECT updated_at, price_ty FROM listings WHERE id = ?", (listing_id,)).fetchone()
        history = [{'date': (r[0] or '')[:10], 'price_ty': r[1]} for r in rows]
        if curr: history.append({'date': (curr[0] or '')[:10], 'price_ty': curr[1]})
        return jsonify(history)

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

if __name__ == "__main__":
    db_mod.init_schema()
    app.run(host="127.0.0.1", port=5000, debug=True)
