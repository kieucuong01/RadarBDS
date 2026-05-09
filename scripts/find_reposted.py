import sqlite3

conn = sqlite3.connect(r'C:\Users\ASUS\radar_bds.db')

r = conn.execute('SELECT COUNT(*), COUNT(DISTINCT listing_id) FROM price_history')
total_rows, unique_listings = r.fetchone()
print(f'price_history: {total_rows} rows / {unique_listings} unique listings\n')

sql = """
    SELECT l.id, l.title, l.ward, l.price_ty, l.source,
           COUNT(ph.id) as n_records,
           ROUND(MIN(ph.price_ty), 3) as price_min,
           ROUND(MAX(ph.price_ty), 3) as price_max,
           ROUND((MAX(ph.price_ty) - MIN(ph.price_ty)) / MAX(ph.price_ty) * 100, 1) as drop_pct,
           MIN(ph.recorded_at) as first_seen,
           MAX(ph.recorded_at) as last_seen
    FROM listings l
    JOIN price_history ph ON ph.listing_id = l.id
    WHERE l.probably_sold = 0
    GROUP BY l.id
    HAVING n_records >= 2 AND price_max > price_min
    ORDER BY drop_pct DESC
    LIMIT 30
"""
rows = conn.execute(sql).fetchall()
print(f'Tin re-list co giam gia ({len(rows)} ket qua):')
header = f"{'ID':>6}  {'Ward':18}  {'Lan':>3}  {'Giam':>6}  {'Tu':>8} -> {'Den':>8}  Title"
print(header)
print('-' * 105)
for row in rows:
    id_, title, ward, price, source, n, pmin, pmax, drop, first, last = row
    title_short = str(title)[:45] if title else '-'
    print(f"{id_:>6}  {str(ward):18}  {n:>3}  {drop:>5}%  {pmin:>8.3f}ty -> {pmax:>8.3f}ty  {title_short}")

print('\n--- Co the trung lap (possibly_duplicate=1) va giam gia ---')
sql2 = """
    SELECT l.id, l.title, l.ward, l.price_ty, l.price_dropped, l.duplicate_of_id,
           l.source, l.url
    FROM listings l
    WHERE l.possibly_duplicate = 1
      AND l.price_dropped = 1
      AND l.probably_sold = 0
    ORDER BY l.ward, l.price_ty
    LIMIT 20
"""
rows2 = conn.execute(sql2).fetchall()
print(f'({len(rows2)} ket qua)')
for row in rows2:
    id_, title, ward, price, dropped, dup_of, source, url = row
    title_short = str(title)[:50] if title else '-'
    print(f"  id={id_} ward={ward} gia={price}ty drop={dropped} dup_of={dup_of} [{source}] {title_short}")
