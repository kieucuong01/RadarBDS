import sys
import re

with open('generate_dashboard.py', 'r', encoding='utf-8') as f:
    original = f.read()

# 1. Create app.py content
imports = '''import os
import json
from datetime import date, datetime
from pathlib import Path
from flask import Flask, request, render_template_string
import config.database_sqlite as db_mod
from analytics.valuation import ValuationEngine, Listing

app = Flask(__name__)
'''

load_data_func = '''
def _days_ago(crawled_at: str) -> int:
    try:
        d = date.fromisoformat(crawled_at[:10])
        return (date.today() - d).days
    except Exception:
        return 0

def _canonical_url(url: str, source: str, title: str) -> str:
    if url: return url
    if source == 'facebook': return 'https://facebook.com/search/posts/?q=' + title.replace(' ', '%20')
    return '#'

def load_data(db_path: str, active_sources: list) -> dict:
    db_mod.DB_PATH = Path(db_path)
    with db_mod.get_conn() as conn:
        q_marks = ','.join('?' * len(active_sources)) if active_sources else ''
        src_filter = f' AND source IN ({q_marks})' if active_sources else ''
        
        query = f"""
            SELECT * FROM listings
            WHERE price_per_m2 IS NOT NULL AND price_per_m2 > 0
              AND probably_sold = 0 AND possibly_duplicate = 0
              {src_filter}
        """
        rows = conn.execute(query, active_sources).fetchall()
        cols = [d[0] for d in conn.execute('SELECT * FROM listings LIMIT 0').description]
        
        img_rows = conn.execute('SELECT listing_id, image_url FROM listing_images').fetchall()
        img_map = {}
        for rid, src in img_rows:
            img_map.setdefault(rid, []).append(src)

    listings = []
    for r in rows:
        row = dict(zip(cols, r))
        crawled = date.fromisoformat(row['crawled_at'][:10]) if row['crawled_at'] else None
        l = Listing(
            id           = row['id'],
            area         = row['area'] or 'unknown',
            property_type= row['property_type'] or 'khac',
            tx_type      = (row['tx_type'] or 'ban').strip().lower().replace('bán', 'ban').replace('thuê', 'thue'),
            price_per_m2 = float(row['price_per_m2']),
            price_total  = float(row['price_ty'] or 0),
            area_m2      = float(row['area_m2'] or 0),
            frontage_m   = float(row['frontage_m']) if row['frontage_m'] else None,
            depth_m      = float(row['depth_m'])    if row['depth_m']    else None,
            road_width_m = float(row['road_width_m']) if row['road_width_m'] else None,
            road_type    = row['road_type'] or 'unknown',
            road_tier     = int(row['road_tier'] or 0),
            has_so        = bool(row['has_so']),
            is_hot        = bool(row['is_hot']),
            price_dropped = bool(row['price_dropped']),
            crawled_at    = crawled,
            url           = row['url'] or '',
            contact_phone = row['contact_phone'] or '',
        )
        l._raw = row
        listings.append(l)

    engine = ValuationEngine()
    engine.fit(listings)
    val_results = engine.valuate_batch(listings)

    all_listings_dict = []
    signals_dict = []
    
    for l, v in zip(listings, val_results):
        r = l._raw
        url = _canonical_url(r['url'] or '', r['source'] or '', r['title'] or '')
        days_ago = _days_ago(r['posted_at'] or r['crawled_at'] or '')
        imgs = img_map.get(r['id'], [])
        
        item = {
            'id': r['id'],
            'title': r['title'] or '',
            'source': r['source'] or '',
            'seller_name': r['seller_name'] or '',
            'area_m2': r['area_m2'],
            'price_ty': r['price_ty'],
            'price_per_m2': round(r['price_per_m2'], 1) if r['price_per_m2'] else None,
            'prop_type': r['property_type'] or 'khac',
            'ward': r['ward'] or 'Tân An',
            'road_type': r['road_type'] or 'unknown',
            'has_so': bool(r['has_so']),
            'frontage_m': r['frontage_m'],
            'url': url,
            'crawled_at': (r['crawled_at'] or '')[:10],
            'posted_at': (r['posted_at'] or r['crawled_at'] or '')[:10],
            'days_ago': days_ago,
            'is_hot': bool(r['is_hot']),
            'price_dropped': bool(r['price_dropped']),
            'drop_pct': r['price_drop_pct'],
            'is_signal': v.is_signal,
            'mos_pct': round(v.mos_pct, 1) if v.mos_pct else 0,
            'signal_score': v.signal_score,
            'road_tier': v.road_tier or l.road_tier,
            'fair_ppm2': round(v.fair_ppm2, 1) if v.fair_ppm2 else None,
            'imgs': imgs
        }
        all_listings_dict.append(item)
        if v.is_signal:
            signals_dict.append(item)
            
    signals_dict.sort(key=lambda x: (x['signal_score'] * x['mos_pct']), reverse=True)
    all_listings_dict.sort(key=lambda x: (x['prop_type'], x['price_per_m2'] or 0))

    # Compute Market Pulse
    market_map = {}
    for x in all_listings_dict:
        t = x['prop_type']
        if t not in market_map:
            market_map[t] = []
        if x['price_per_m2']:
            market_map[t].append(x['price_per_m2'])
            
    market = []
    type_label = {'dat_nen': 'Đất nền', 'dat_vuon': 'Đất vườn', 'nha_dat': 'Nhà đất'}
    for t, vals in market_map.items():
        if not vals: continue
        vals.sort()
        market.append({
            'type': t,
            'label': type_label.get(t, t),
            'n': len(vals),
            'min_ppm2': round(min(vals),1),
            'max_ppm2': round(max(vals),1),
            'median': round(vals[len(vals)//2],1)
        })
        
    return {
        'signals': signals_dict,
        'all_listings': all_listings_dict,
        'market': market
    }
'''

# 2. Extract build_html from original
build_html_start = original.find('def build_html')
build_html_end = original.find('def main()', build_html_start)
build_html_code = original[build_html_start:build_html_end]

# Modify build_html signature to accept active_sources
build_html_code = build_html_code.replace('def build_html(data: dict, generated_at: str) -> str:', 'def build_html(data: dict, generated_at: str, active_sources: list) -> str:')

checkboxes_html = '''
    <form method="get" style="display:flex; gap:12px; align-items:center; flex-wrap:wrap;">
       <label style="color:var(--text); font-size:0.8rem; font-weight:600;">Nguồn định giá:</label>
       <label style="color:var(--muted);"><input type="checkbox" name="source" value="facebook" {"checked" if "facebook" in active_sources else ""}> Môi giới (FB)</label>
       <label style="color:var(--muted);"><input type="checkbox" name="source" value="guland" {"checked" if "guland" in active_sources else ""}> Guland</label>
       <label style="color:var(--muted);"><input type="checkbox" name="source" value="batdongsan" {"checked" if "batdongsan" in active_sources else ""}> BDS.com.vn</label>
       <button type="submit" style="padding: 4px 12px; border-radius:12px; background:var(--accent); color:white; border:none; cursor:pointer; font-weight:600;">Định giá lại & Lọc</button>
    </form>
'''

# Insert checkboxes into header-right
build_html_code = re.sub(
    r'<div class="header-right">Cập nhật: \{generated_at\}</div>',
    f'<div class="header-right">{checkboxes_html}<div style="text-align:right; margin-top:4px; font-size:0.75rem; color:var(--muted);">Cập nhật: {{generated_at}}</div></div>',
    build_html_code
)

# 3. Create Flask routing
flask_routes = '''
@app.route("/")
def index():
    sources = request.args.getlist("source")
    if not sources:
        # Default to facebook if none specified
        sources = ["facebook"]
        
    db_path = str(Path("c:/Users/ASUS/Documents/Claude/Projects/Radar BDS/radar_bds.db").resolve())
    data = load_data(db_path, sources)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    html = build_html(data, generated_at, sources)
    return render_template_string(html)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
'''

# 4. Write app.py
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(imports + '\n' + load_data_func + '\n' + build_html_code + '\n' + flask_routes)

print("Generated app.py")
