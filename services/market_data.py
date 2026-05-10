import sqlite3
from pathlib import Path
from datetime import datetime, date
from functools import lru_cache

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
        return 0
    except Exception:
        return 0

def normalize_image_url(src: str) -> str:
    if not src:
        return ""
    s = str(src).strip().replace("\\", "/")
    if not s or s.upper().endswith("NOT_FOUND"):
        return ""
    if s.startswith(("http://", "https://", "data:")):
        return s
    if s.startswith("/data/images/"):
        return s
    marker = "data/images/"
    if marker in s:
        return "/" + s[s.index(marker):]
    return "/data/images/" + Path(s).name

@lru_cache(maxsize=20000)
def _local_image_exists(url: str) -> bool:
    if not url.startswith("/data/images/"):
        return True
    filename = url.removeprefix("/data/images/")
    image_dir = Path(__file__).resolve().parent.parent / "data" / "images"
    return (image_dir / filename).exists()

def resolve_image_url(local_src: str, remote_src: str) -> str:
    local_url = normalize_image_url(local_src)
    if local_url and _local_image_exists(local_url):
        return local_url
    remote_url = normalize_image_url(remote_src)
    if remote_url:
        return remote_url
    return local_url

def load_data(db_path, sources=None, wards=None, prop_types=None, only_drops=False, trend_period='day', skip_listings=False, include_trend=True, mos_min=0):
    if not sources:
        sources = ["facebook", "guland", "batdongsan"]
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Common filters. Normal views hide duplicates; drop-only views show reliable
    # repost drops even when the lower-price repost is marked duplicate.
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

    where_sql = " AND ".join(where_parts)

    mos_condition = ""
    mos_params = []
    if mos_min > 0:
        mos_condition = " AND v.mos_pct >= ?"
        mos_params = [mos_min]

    # 1. Stats
    stats = conn.execute(f"""
        WITH filtered AS (SELECT * FROM listings WHERE {where_sql})
        SELECT
            (SELECT COUNT(*) FROM filtered) as total,
            (SELECT COUNT(*) FROM filtered l JOIN valuation_results v ON l.id = v.listing_id WHERE v.is_signal = 1{mos_condition}) as signals,
            (SELECT COUNT(*) FROM filtered WHERE is_hot = 1) as hot,
            (SELECT COUNT(*) FROM filtered WHERE price_dropped = 1) as price_drops
    """, params + mos_params).fetchone()

    # 2. Signals
    sig_query = f"""
        SELECT v.mos_pct, v.actual_ppm2, v.fair_ppm2, v.is_signal,
               l.id, l.title, l.source, l.area_m2, l.price_ty,
               l.property_type, l.is_hot, l.price_dropped, l.price_drop_pct, l.suspicious_bait,
               l.price_first_ty, l.duplicate_of_id,
               l.url, l.crawled_at, l.posted_at, l.ward, l.road_tier, l.has_so, l.seller_name,
               l.description,
               COALESCE(v.signal_score, 0) as signal_score
        FROM valuation_results v
        JOIN listings l ON v.listing_id = l.id
        WHERE v.is_signal = 1 AND {where_sql}{mos_condition}
        ORDER BY v.signal_score DESC, v.mos_pct DESC
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
    from collections import defaultdict
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
        "signals": [{
            "id": r['id'], "title": r['title'], "mos_pct": round(r['mos_pct'],1) if r['mos_pct'] else 0, "actual_ppm2": round(r['actual_ppm2'],1) if r['actual_ppm2'] else 0,
            "fair_ppm2": round(r['fair_ppm2'],1) if r['fair_ppm2'] else None, "area_m2": r['area_m2'], "price_ty": r['price_ty'],
            "prop_type": r['property_type'], "is_hot": bool(r['is_hot']), "price_dropped": bool(r['price_dropped']),
            "suspicious_bait": bool(r['suspicious_bait']),
            "drop_pct": r['price_drop_pct'], "price_first_ty": r['price_first_ty'],
            "duplicate_of_id": r['duplicate_of_id'], "url": r['url'], "days_ago": _days_ago(r['posted_at'] or r['crawled_at']),
            "ward": r['ward'], "signal_score": r['signal_score'], "imgs": img_map.get(r['id'], []), "source": r['source'],
            "road_tier": r['road_tier'] or 0, "has_so": bool(r['has_so']),
            "description": r['description'] or ""
        } for r in sig_rows],
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

def load_trend_data(db_path, sources=None, wards=None, prop_types=None, only_drops=False, trend_period='day'):
    if not sources:
        sources = ["facebook", "guland", "batdongsan"]

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
