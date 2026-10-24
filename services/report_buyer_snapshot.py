"""Generation-only buyer facts. Prices describe the recorded cohort at generation."""
from collections import Counter
from datetime import datetime
import math
import statistics
from zoneinfo import ZoneInfo

from services.signal_quality import ACTIONABLE_SUPPRESS_FLAGS, split_quality_flags

MIN_SAMPLES = 15
TYPE_LABELS = {'dat_nen': 'Đất nền', 'nha_dat': 'Nhà đất'}
BUDGETS = ((0, 1.5, 'Dưới 1,5 tỷ'), (1.5, 2, '1,5–dưới 2 tỷ'),
           (2, 3, '2–dưới 3 tỷ'), (3, 5, '3–dưới 5 tỷ'), (5, None, 'Từ 5 tỷ'))
TZ = ZoneInfo('Asia/Ho_Chi_Minh')


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.replace(tzinfo=TZ) if result.tzinfo is None else result.astimezone(TZ)
    except (ValueError, TypeError):
        return None


def distribution(values):
    values = sorted(values)
    result = {'n': len(values), 'median': None, 'p25': None, 'p75': None}
    if len(values) >= MIN_SAMPLES:
        q = statistics.quantiles(values, n=4, method='inclusive')
        result.update(median=statistics.median(values), p25=q[0], p75=q[2])
    return result


def valid_snapshot(snapshot):
    """Fail closed on incomplete, inconsistent or mismatched saved fact packets."""
    try:
        if snapshot['schema_version'] != 1 or snapshot['contract_version'] != 'buyer-cohort-v1':
            return False
        start, end, generated = [timestamp(snapshot[k]) for k in ('period_start','period_end','generated_at')]
        if not start or not end or not generated or not start < end <= generated:
            return False
        if snapshot['price_time_basis'] != 'current_known_prices_of_period_collected_records_at_generation':
            return False
        n = snapshot['qualified_count']
        if type(n) is not int or n < 0 or snapshot['min_samples'] != MIN_SAMPLES:
            return False
        for name in ('segments','budgets','comparisons'):
            groups = snapshot[name]
            if sum(r['n'] for r in groups) != n:
                return False
            for row in groups:
                if row['property_type'] not in TYPE_LABELS or type(row['n']) is not int or row['n'] < 1:
                    return False
                for key in ('asking_ty','ppm2','area_m2'):
                    values = row[key]
                    if values['n'] != row['n']:
                        return False
                    stats = [values[k] for k in ('p25','median','p75')]
                    if row['n'] < MIN_SAMPLES:
                        if any(v is not None for v in stats):
                            return False
                    elif not all(isinstance(v, (int,float)) and math.isfinite(v) and v > 0 for v in stats) or stats != sorted(stats):
                        return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def _group(items, **keys):
    return dict(keys, n=len(items), asking_ty=distribution([r['price_ty'] for r in items]),
                ppm2=distribution([r['price_per_m2'] for r in items]),
                area_m2=distribution([r['area_m2'] for r in items]))


def build_buyer_snapshot(rows, *, period_start, period_end, generated_at):
    start, end, generated = map(timestamp, (period_start, period_end, generated_at))
    if not start or not end or not generated or not start < end <= generated:
        raise ValueError('A buyer snapshot requires a closed, valid period and generation date')
    qualified, seen, excluded = [], set(), Counter()
    for raw in rows:
        row = dict(raw)
        reason = None
        if row.get('source') != 'facebook' or row.get('tx_type') != 'ban':
            reason = 'source_or_transaction'
        elif row.get('property_type') not in TYPE_LABELS:
            reason = 'other_or_unknown_type'
        elif not isinstance(row.get('ward'), str) or not row['ward'].strip():
            reason = 'missing_scope'
        elif any(row.get(k) for k in ('duplicate_of_id', 'possibly_duplicate', 'review_hidden',
                                      'is_blacklisted', 'is_outlier', 'valuation_is_outlier',
                                      'suspicious_bait', 'probably_sold')):
            reason = 'quality_or_duplicate'
        elif (split_quality_flags(row.get('extraction_quality_flags')) |
              split_quality_flags(row.get('source_quality_flags'))) & ACTIONABLE_SUPPRESS_FLAGS:
            reason = 'extraction_or_source_quality'
        try:
            price, area, ppm = [float(row.get(k)) for k in ('price_ty', 'area_m2', 'price_per_m2')]
            valid = all(math.isfinite(v) and v > 0 for v in (price, area, ppm))
            valid = valid and abs(ppm - price * 1000 / area) <= max(.001, price * 1000 / area * .01)
        except (ValueError, TypeError, ZeroDivisionError):
            valid = False
        if not valid:
            reason = reason or 'invalid_measurements'
        if type(row.get('id')) is not int or row['id'] in seen:
            reason = reason or 'duplicate_or_missing_id'
        if reason:
            excluded[reason] += 1
            continue
        seen.add(row['id'])
        row.update(price_ty=price, area_m2=area, price_per_m2=ppm)
        qualified.append(row)
    segments = [_group([r for r in qualified if r['property_type'] == pt], property_type=pt,
                       label=label) for pt, label in TYPE_LABELS.items()
                if any(r['property_type'] == pt for r in qualified)]
    budgets, comparisons = [], []
    for low, high, label in BUDGETS:
        for pt in TYPE_LABELS:
            group = [r for r in qualified if r['property_type'] == pt and
                     low <= r['price_ty'] and (high is None or r['price_ty'] < high)]
            if group:
                budgets.append(_group(group, low=low, high=high, label=label, property_type=pt))
    for ward in sorted({r.get('ward') for r in qualified if r.get('ward')}):
        for pt in TYPE_LABELS:
            group = [r for r in qualified if r['ward'] == ward and r['property_type'] == pt]
            if group:
                comparisons.append(_group(group, scope=ward, property_type=pt))
    durations, drops = [], set()
    event_count = 0
    for row in qualified:
        first, last = timestamp(row.get('first_seen_at')), timestamp(row.get('last_seen_at'))
        if first and last and first <= last <= generated:
            durations.append((last.date() - first.date()).days)
        for event in row.get('price_events') or []:
            at = timestamp(event.get('recorded_at'))
            try:
                old, new = float(event['old_price_ty']), float(event['new_price_ty'])
                valid = all(math.isfinite(v) and v > 0 for v in (old, new))
            except (KeyError, ValueError, TypeError):
                valid = False
            if at and start <= at < end and valid and new < old:
                drops.add(row['id'])
                event_count += 1
    examples = []
    for group in sorted(budgets, key=lambda b: b['n'], reverse=True):
        candidates = [r for r in qualified if r['property_type'] == group['property_type'] and
                      r['price_ty'] >= group['low'] and (group['high'] is None or r['price_ty'] < group['high'])]
        median = statistics.median(r['price_ty'] for r in candidates)
        row = min(candidates, key=lambda r: (abs(r['price_ty'] - median), r['id']))
        examples.append(dict(href=f'/listing/{row["id"]}', title=f'{TYPE_LABELS[row["property_type"]]} tại {row["ward"]}',
                             type=TYPE_LABELS[row['property_type']], price=f'{row["price_ty"]:g} tỷ',
                             area=f'{row["area_m2"]:g} m²', price_per_m2=f'{row["price_per_m2"]:g} tr/m²',
                             selection_note=f'Mẫu gần trung vị tổng giá trong nhóm {group["label"]} / {TYPE_LABELS[row["property_type"]]}. Chọn để đối chiếu, không xếp theo MOS hoặc khuyến nghị mua.'))
        if len(examples) == 6:
            break
    return dict(schema_version=1, contract_version='buyer-cohort-v1',
                period_start=period_start, period_end=period_end, generated_at=generated_at,
                price_time_basis='current_known_prices_of_period_collected_records_at_generation',
                min_samples=MIN_SAMPLES, qualified_count=len(qualified),
                excluded_count=sum(excluded.values()), exclusions=dict(excluded),
                segments=segments, budgets=budgets, comparisons=comparisons, examples=examples,
                history=dict(observed_drop_count=len(drops), observed_drop_events=event_count,
                             days_observed_n=len(durations), days_observed=distribution(durations)))


def query_buyer_snapshot(conn, wards, period_start, period_end, *, generated_at):
    """Called by the monthly publisher only, never from report HTTP/download routes."""
    from services.monthly_report_data import canonical_quality_listing_sql, WARD_ALIASES
    names = sorted({n for ward in wards for n in (ward, WARD_ALIASES.get(ward, ward))})
    placeholders = ','.join('?' for _ in names)
    where = (f"{canonical_quality_listing_sql('l')} AND l.ward IN ({placeholders}) "
             'AND l.crawled_at::timestamp >= ? AND l.crawled_at::timestamp < ?')
    params = [*names, period_start, period_end]
    result = conn.execute(f"""
SELECT l.id, l.source, l.tx_type, l.ward, l.property_type, l.price_ty, l.area_m2,
       l.price_per_m2, l.first_seen_at, l.last_seen_at, l.extraction_quality_flags,
       l.suspicious_bait, v.source_quality_flags, v.is_outlier AS valuation_is_outlier
FROM listings l LEFT JOIN LATERAL (
 SELECT source_quality_flags, is_outlier FROM valuation_results
 WHERE listing_id=l.id ORDER BY computed_at DESC, id DESC LIMIT 1
) v ON TRUE WHERE {where}
""", params).fetchall()
    rows = {int(r['id']): dict(r) for r in result}
    canonical_wards = {alias: ward for ward, alias in WARD_ALIASES.items()}
    for row in rows.values():
        row['ward'] = canonical_wards.get(row['ward'], row['ward'])
    history = conn.execute(f"""
SELECT h.listing_id, h.price_ty, h.recorded_at FROM price_history h
JOIN listings l ON l.id=h.listing_id WHERE {where}
AND h.recorded_at::timestamp < ? ORDER BY h.listing_id, h.recorded_at::timestamp, h.id
""", [*params, period_end]).fetchall()
    previous = {}
    for item in history:
        key = int(item['listing_id'])
        if key in rows and key in previous:
            rows[key].setdefault('price_events', []).append(dict(
                recorded_at=item['recorded_at'], old_price_ty=previous[key], new_price_ty=item['price_ty']))
        previous[key] = item['price_ty']
    return build_buyer_snapshot(list(rows.values()), period_start=period_start,
                                period_end=period_end, generated_at=generated_at)
