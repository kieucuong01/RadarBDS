import sqlite3
from datetime import datetime, date
from collections import defaultdict

from services.image_assets import resolve_image_url

CITY_MAP = {
    "THỦ DẦU MỘT": ["Tân An", "Hiệp An", "Tương Bình Hiệp", "Định Hòa", "Chánh Mỹ", "Phú Mỹ", "Phú Cường", "Phú Hòa", "Phú Lợi", "Hiệp Thành", "Chánh Nghĩa", "Phú Tân", "Hòa Phú"],
    "BẾN CÁT": ["Phú An", "An Tây", "An Điền", "Thới Hòa", "Mỹ Phước", "Mỹ Phước 1", "Mỹ Phước 2", "Mỹ Phước 3", "Mỹ Phước 4", "Chánh Phú Hòa", "Tân Định", "Hòa Lợi"],
    "THUẬN AN": ["An Phú", "An Thạnh", "Bình Chuẩn", "Bình Hòa", "Bình Nhâm", "Hưng Định", "Lái Thiêu", "Thuận Giao", "Vĩnh Phú", "An Sơn"],
    "DĨ AN": ["An Bình", "Bình An", "Bình Thắng", "Dĩ An", "Đông Hòa", "Tân Bình", "Tân Đông Hiệp"],
    "TÂN UYÊN": ["Hội Nghĩa", "Khánh Bình", "Phú Chánh", "Tân Hiệp", "Tân Phước Khánh", "Tân Vĩnh Hiệp", "Thạnh Hội", "Thạnh Phước", "Uyên Hưng", "Vĩnh Tân"]
}

def get_city_for_ward(ward: str) -> str:
    for city, wards in CITY_MAP.items():
        if ward in wards:
            return city
    return "Khác"

def _days_ago(crawled_at: str) -> int:
    try:
        if crawled_at:
            d = date.fromisoformat(crawled_at[:10])
            return (date.today() - d).days
        return None
    except Exception:
        return None

def _build_filters(sources=None, wards=None, prop_types=None, only_drops=False, prefix="", area_min=0, area_max=0, price_min=0, price_max=0):
    if not sources:
        sources = ["facebook", "guland", "batdongsan"]

    # Common filters. Normal views hide duplicates; drop-only views show reliable
    # repost drops even when the lower-price repost is marked duplicate.
    col = lambda name: f"{prefix}{name}" if prefix else name
    where_parts = [
        f"{col('probably_sold')} = 0",
        f"COALESCE({col('is_blacklisted')},0)=0",
        f"COALESCE({col('review_hidden')},0)=0",
    ]
    if only_drops:
        where_parts.append(f"{col('price_dropped')} = 1")
    else:
        where_parts.append(f"{col('possibly_duplicate')} = 0")
    params = []

    if wards:
        where_parts.append(f"{col('ward')} IN ({','.join(['?']*len(wards))})")
        params.extend(wards)

    if sources:
        where_parts.append(f"{col('source')} IN ({','.join(['?']*len(sources))})")
        params.extend(sources)

    if prop_types:
        where_parts.append(f"{col('property_type')} IN ({','.join(['?']*len(prop_types))})")
        params.extend(prop_types)

    range_clauses, range_params = _range_filters(area_min, area_max, price_min, price_max, prefix)
    where_parts.extend(range_clauses)
    params.extend(range_params)

    return " AND ".join(where_parts), params


def _range_filters(area_min=0, area_max=0, price_min=0, price_max=0, prefix=""):
    col = lambda name: f"{prefix}{name}" if prefix else name
    clauses = []
    params = []
    if area_min and area_min > 0:
        clauses.append(f"{col('area_m2')} >= ?")
        params.append(area_min)
    if area_max and area_max > 0:
        clauses.append(f"{col('area_m2')} <= ?")
        params.append(area_max)
    if price_min and price_min > 0:
        clauses.append(f"{col('price_ty')} >= ?")
        params.append(price_min)
    if price_max and price_max > 0:
        clauses.append(f"{col('price_ty')} <= ?")
        params.append(price_max)
    return clauses, params


def _mos_filter(mos_min=0):
    mos_condition = ""
    mos_params = []
    if mos_min > 0:
        mos_condition = " AND v.mos_pct >= ?"
        mos_params = [mos_min]
    return mos_condition, mos_params


def _signal_sort_sql(sort_key: str) -> str:
    sort_map = {
        "newest": "COALESCE(l.posted_at, l.crawled_at) DESC, l.id DESC",
        "price_m2_asc": "v.actual_ppm2 IS NULL, v.actual_ppm2 ASC, l.id DESC",
        "price_asc": "l.price_ty IS NULL, l.price_ty ASC, l.id DESC",
        "mos_desc": "v.mos_pct IS NULL, v.mos_pct DESC, l.id DESC",
        "score_desc": "COALESCE(v.signal_score, 0) DESC, v.mos_pct DESC",
    }
    return sort_map.get(sort_key or "newest", sort_map["newest"])


def _primary_images(conn, listing_ids):
    if not listing_ids:
        return {}
    placeholders = ",".join("?" * len(listing_ids))
    rows = conn.execute(f"""
        SELECT listing_id, local_path, img_url
        FROM listing_images
        WHERE listing_id IN ({placeholders})
        ORDER BY listing_id, img_order
    """, listing_ids).fetchall()
    img_map = {}
    for r in rows:
        if r[0] in img_map:
            continue
        url = resolve_image_url(r[1], r[2], prefer_thumb=True)
        if url:
            img_map[r[0]] = url
    return img_map


def _format_signal_row(r, primary_img=None):
    fair_ppm2 = round(r['fair_ppm2'], 1) if r['fair_ppm2'] else None
    return {
        "id": r['id'],
        "title": r['title'],
        "mos_pct": round(r['mos_pct'], 1) if r['mos_pct'] else 0,
        "actual_ppm2": round(r['actual_ppm2'], 1) if r['actual_ppm2'] else 0,
        "fair_ppm2": fair_ppm2,
        "area_m2": r['area_m2'],
        "price_ty": r['price_ty'],
        "prop_type": r['property_type'],
        "is_hot": bool(r['is_hot']),
        "price_dropped": bool(r['price_dropped']),
        "suspicious_bait": bool(r['suspicious_bait']),
        "drop_pct": r['price_drop_pct'],
        "price_first_ty": r['price_first_ty'],
        "duplicate_of_id": r['duplicate_of_id'],
        "url": r['url'],
        "days_ago": _days_ago(r['posted_at'] or r['crawled_at']),
        "ward": r['ward'],
        "signal_score": r['signal_score'],
        "primary_img": primary_img or "",
        "source": r['source'],
        "road_tier": r['road_tier'] or 0,
        "has_so": None if r['has_so'] is None else bool(r['has_so']),
    }


def load_signals(db_path, sources=None, wards=None, prop_types=None, only_drops=False, mos_min=0, sort='newest', page=1, limit=30, area_min=0, area_max=0, price_min=0, price_max=0):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    where_sql, params = _build_filters(sources, wards, prop_types, only_drops, prefix="l.", area_min=area_min, area_max=area_max, price_min=price_min, price_max=price_max)
    mos_condition, mos_params = _mos_filter(mos_min)
    page = max(int(page or 1), 1)
    limit = min(max(int(limit or 30), 1), 100)
    offset = (page - 1) * limit
    order_sql = _signal_sort_sql(sort)

    count_row = conn.execute(f"""
        SELECT COUNT(*)
        FROM valuation_results v
        JOIN listings l ON v.listing_id = l.id
        WHERE v.is_signal = 1 AND {where_sql}{mos_condition}
    """, params + mos_params).fetchone()
    total = count_row[0] if count_row else 0

    rows = conn.execute(f"""
        SELECT v.mos_pct, v.actual_ppm2, v.fair_ppm2, v.is_signal,
               l.id, l.title, l.source, l.area_m2, l.price_ty,
               l.property_type, l.is_hot, l.price_dropped, l.price_drop_pct, l.suspicious_bait,
               l.price_first_ty, l.duplicate_of_id,
               l.url, l.crawled_at, l.posted_at, l.ward, l.road_tier, l.has_so,
               COALESCE(v.signal_score, 0) as signal_score
        FROM valuation_results v
        JOIN listings l ON v.listing_id = l.id
        WHERE v.is_signal = 1 AND {where_sql}{mos_condition}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """, params + mos_params + [limit, offset]).fetchall()

    image_map = _primary_images(conn, [r['id'] for r in rows])
    conn.close()

    return {
        "signals": [_format_signal_row(r, image_map.get(r['id'])) for r in rows],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit else 1,
        "has_more": page * limit < total,
        "sort": sort or "newest",
    }


def load_data(db_path, sources=None, wards=None, prop_types=None, only_drops=False, trend_period='day', skip_listings=False, include_trend=True, mos_min=0, include_signals=True, area_min=0, area_max=0, price_min=0, price_max=0):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    where_sql, params = _build_filters(sources, wards, prop_types, only_drops, area_min=area_min, area_max=area_max, price_min=price_min, price_max=price_max)
    mos_condition, mos_params = _mos_filter(mos_min)

    # 1. Stats
    stats = conn.execute(f"""
        WITH filtered AS (SELECT * FROM listings WHERE {where_sql})
        SELECT
            (SELECT COUNT(*) FROM filtered) as total,
            (SELECT COUNT(*) FROM filtered l JOIN valuation_results v ON l.id = v.listing_id WHERE v.is_signal = 1{mos_condition}) as signals,
            (SELECT COUNT(*) FROM filtered WHERE is_hot = 1) as hot,
            (SELECT COUNT(*) FROM filtered WHERE (
                COALESCE(posted_at, crawled_at) IS NOT NULL
                AND julianday('now') - julianday(substr(COALESCE(posted_at, crawled_at),1,10)) <= 7
            )) as new_recent_days_7,

            (SELECT COUNT(*) FROM filtered WHERE price_dropped = 1) as price_drops

    """, params + mos_params).fetchone()

    sig_rows = []
    if include_signals:
        sig_query = f"""
            SELECT v.mos_pct, v.actual_ppm2, v.fair_ppm2, v.is_signal,
                   l.id, l.title, l.source, l.area_m2, l.price_ty,
                   l.property_type, l.is_hot, l.price_dropped, l.price_drop_pct, l.suspicious_bait,
                   l.price_first_ty, l.duplicate_of_id,
                   l.url, l.crawled_at, l.posted_at, l.ward, l.road_tier, l.has_so,
                   COALESCE(v.signal_score, 0) as signal_score
            FROM valuation_results v
            JOIN listings l ON v.listing_id = l.id
            WHERE v.is_signal = 1 AND {where_sql}{mos_condition}
            ORDER BY COALESCE(v.signal_score, 0) DESC, v.mos_pct DESC
        """
        sig_rows = conn.execute(sig_query, params + mos_params).fetchall()

    # 3. All Listings
    all_rows = []
    if not skip_listings:
        all_query = f"""
            SELECT l.*, v.is_signal, v.mos_pct, v.fair_ppm2, v.signal_score
            FROM listings l
            LEFT JOIN valuation_results v ON l.id = v.listing_id
            WHERE {where_sql}
            ORDER BY l.price_per_m2 ASC
        """
        all_rows = conn.execute(all_query, params).fetchall()

    # 4. Images
    listing_ids = [r['id'] for r in sig_rows]
    if not skip_listings:
        listing_ids.extend([r['id'] for r in all_rows])
    
    listing_ids = list(set(listing_ids))
    img_rows = []
    if listing_ids:
        placeholders = ",".join("?" * len(listing_ids))
        img_rows = conn.execute(f"""
            SELECT listing_id, local_path, img_url
            FROM listing_images
            WHERE listing_id IN ({placeholders})
            ORDER BY listing_id, img_order
        """, listing_ids).fetchall()
    img_map = defaultdict(list)
    for r in img_rows:
        url = resolve_image_url(r[1], r[2])
        if url:
            img_map[r[0]].append(url)

    # 5. Market Pulse (Median per Type) - filtered
    market = []
    summary_rows = conn.execute(f"""
        SELECT property_type, AVG(price_per_m2) as mean_ppm2, COUNT(*) as n_samples
        FROM listings
        WHERE is_outlier = 0 AND {where_sql}
        GROUP BY property_type
        HAVING n_samples >= 1
    """, params).fetchall()
    type_label = {'dat_nen': 'Đất nền', 'dat_vuon': 'Đất vườn', 'nha_dat': 'Nhà đất', 'nha_tro': 'Nhà trọ', 'chung_cu': 'Chung cư'}
    for s in summary_rows:
        if s['mean_ppm2'] is None:
            continue
        market.append({
            'type': s['property_type'],
            'label': type_label.get(s['property_type'], s['property_type']),
            'median': round(s['mean_ppm2'], 1),
            'n': s['n_samples']
        })

    # 6. Trend (DYNAMIC) — Tuân theo tất cả bộ lọc (Source, Ward, PropType)
    trend_data = {}
    target_wards = wards if wards else ["Tân An", "Hiệp An", "Tương Bình Hiệp", "Định Hòa", "Chánh Mỹ"]
    
    if trend_period == 'month':
        date_fmt = "strftime('%Y-%m', COALESCE(posted_at, crawled_at))"
        prefix = 'M-'
    elif trend_period == 'day':
        date_fmt = "strftime('%Y-%m-%d', COALESCE(posted_at, crawled_at))"
        prefix = 'D-'
    else: # week
        date_fmt = "strftime('%Y-W%W', COALESCE(posted_at, crawled_at))"
        prefix = ''

    trend_query = f"""
        SELECT 
            '{prefix}' || {date_fmt} as time_key,
            ward,
            price_per_m2
        FROM listings
        WHERE {where_sql} 
          AND price_per_m2 IS NOT NULL 
          AND price_per_m2 > 0
          AND is_outlier = 0
        ORDER BY time_key ASC
    """
    
    if include_trend:
        trend_rows = conn.execute(trend_query, params).fetchall()
    else:
        trend_rows = []
    
    # Group by ward -> time_key -> list of prices -> median
    import statistics
    
    grouped_trend = defaultdict(lambda: defaultdict(list))
    for r in trend_rows:
        if r['ward'] in target_wards:
            grouped_trend[r['ward']][r['time_key']].append(r['price_per_m2'])
            
    for w, time_map in grouped_trend.items():
        ward_points = []
        for t_key, prices in sorted(time_map.items()):
            if len(prices) >= 2: # Require at least 2 samples to reduce noise/jumping
                ward_points.append({
                    'week': t_key,
                    'median_ppm2': round(statistics.median(prices), 2)
                })
        if ward_points:
            trend_data[w] = ward_points

    all_wards = [r[0] for r in conn.execute("SELECT DISTINCT ward FROM listings WHERE ward IS NOT NULL").fetchall()]
    all_sources = [r[0] for r in conn.execute("SELECT DISTINCT source FROM listings").fetchall()]
    conn.close()

    # 7. Grouped Wards for UI
    wards_by_city = {city: list(wards) for city, wards in CITY_MAP.items()}

    return {
        "stats": dict(stats),
        "signals": [_format_signal_row(r, (img_map.get(r['id']) or [""])[0]) for r in sig_rows],
        "all_listings": [{
            "id": r['id'], "title": r['title'], "description": r['description'] or "",
            "price_ty": r['price_ty'], "area_m2": r['area_m2'],
            "price_per_m2": round(r['price_per_m2'],1) if r['price_per_m2'] else None, "prop_type": r['property_type'],
            "ward": r['ward'], "url": r['url'], "is_signal": bool(r['is_signal']), "mos_pct": round(r['mos_pct'],1) if r['mos_pct'] else 0,
            "fair_ppm2": round(r['fair_ppm2'],1) if r['fair_ppm2'] else None,
            "days_ago": _days_ago(r['posted_at'] or r['crawled_at']), "is_hot": bool(r['is_hot']), "price_dropped": bool(r['price_dropped']),
            "suspicious_bait": bool(r['suspicious_bait']),
            "drop_pct": r['price_drop_pct'], "price_first_ty": r['price_first_ty'], "duplicate_of_id": r['duplicate_of_id'],
            "source": r['source'], "imgs": img_map.get(r['id'], [])
        } for r in all_rows],
        "market": market,
        "trend_data": trend_data,
        "all_wards": all_wards,
        "all_sources": all_sources,
        "wards_by_city": wards_by_city
    }

def load_trend_data(db_path, sources=None, wards=None, prop_types=None, only_drops=False, trend_period='day', area_min=0, area_max=0, price_min=0, price_max=0):
    if not sources:
        sources = ["facebook", "guland", "batdongsan"]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    where_parts = ["probably_sold = 0", "COALESCE(is_blacklisted,0)=0", "COALESCE(review_hidden,0)=0"]
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
    range_clauses, range_params = _range_filters(area_min, area_max, price_min, price_max)
    where_parts.extend(range_clauses)
    params.extend(range_params)
    where_sql = " AND ".join(where_parts)
    target_wards = wards if wards else ["Tân An", "Hiệp An", "Tương Bình Hiệp", "Định Hòa", "Chánh Mỹ"]

    if trend_period == 'month':
        date_fmt = "strftime('%Y-%m', COALESCE(posted_at, crawled_at))"
        prefix = 'M-'
    elif trend_period == 'day':
        date_fmt = "strftime('%Y-%m-%d', COALESCE(posted_at, crawled_at))"
        prefix = 'D-'
    else:
        date_fmt = "strftime('%Y-W%W', COALESCE(posted_at, crawled_at))"
        prefix = ''

    trend_rows = conn.execute(f"""
        SELECT
            '{prefix}' || {date_fmt} as time_key,
            ward,
            price_per_m2
        FROM listings
        WHERE {where_sql}
          AND price_per_m2 IS NOT NULL
          AND price_per_m2 > 0
          AND is_outlier = 0
        ORDER BY time_key ASC
    """, params).fetchall()
    conn.close()

    from collections import defaultdict
    import statistics

    grouped_trend = defaultdict(lambda: defaultdict(list))
    for r in trend_rows:
        if r['ward'] in target_wards:
            grouped_trend[r['ward']][r['time_key']].append(r['price_per_m2'])

    trend_data = {}
    for w, time_map in grouped_trend.items():
        ward_points = []
        for t_key, prices in sorted(time_map.items()):
            if len(prices) >= 2:
                ward_points.append({
                    'week': t_key,
                    'median_ppm2': round(statistics.median(prices), 2)
                })
        if ward_points:
            trend_data[w] = ward_points

    return trend_data

def load_listing_detail(db_path, listing_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    listing = conn.execute("""
        SELECT l.*, v.is_signal, v.mos_pct, v.fair_ppm2, v.signal_score
        FROM listings l
        LEFT JOIN valuation_results v ON l.id = v.listing_id
        WHERE l.id = ?
          AND COALESCE(l.is_blacklisted,0)=0
          AND COALESCE(l.review_hidden,0)=0
    """, (listing_id,)).fetchone()
    if not listing:
        return None
    
    images = [
        url for url in (
            resolve_image_url(r[0], r[1])
            for r in conn.execute("""
                SELECT local_path, img_url
                FROM listing_images
                WHERE listing_id = ?
                ORDER BY img_order
            """, (listing_id,)).fetchall()
        )
        if url
    ]
    history = [{'date': (r['recorded_at'] or '')[:10], 'price_ty': r['price_ty']} for r in conn.execute("SELECT recorded_at, price_ty FROM price_history WHERE listing_id = ? ORDER BY recorded_at ASC", (listing_id,)).fetchall()]
    conn.close()
    
    return {
        "listing": dict(listing),
        "images": images,
        "history": history
    }

def get_base_filters(req):
    active_city = req.args.get("city")
    wards = req.args.getlist("ward[]") or req.args.getlist("ward")
    sources = req.args.getlist("source[]") or req.args.getlist("source")
    prop_types = req.args.getlist("prop_type[]") or req.args.getlist("prop_type")
    only_drops = req.args.get("only_drops") == "1"
    trend_period = req.args.get("trend_period", "day")
    try:
        mos_min = int(req.args.get("mos_min", 0))
    except (ValueError, TypeError):
        mos_min = 0

    if not active_city and wards:
        active_city = get_city_for_ward(wards[0])
    if not active_city:
        active_city = "THỦ DẦU MỘT"

    return active_city, wards, sources, prop_types, only_drops, trend_period, mos_min
