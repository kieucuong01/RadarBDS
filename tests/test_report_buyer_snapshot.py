from copy import deepcopy

import pytest


def rows(n=20, **overrides):
    return [dict(id=i + 1, source='facebook', tx_type='ban', ward='Phú Mỹ',
                 property_type='dat_nen', price_ty=1 + i / 10, area_m2=100,
                 price_per_m2=(1 + i / 10) * 10,
                 first_seen_at='2026-09-01', last_seen_at='2026-09-20',
                 **overrides) for i in range(n)]


def build(items):
    from services.report_buyer_snapshot import build_buyer_snapshot
    return build_buyer_snapshot(items, period_start='2026-09-01', period_end='2026-10-01',
                                generated_at='2026-10-01T08:00:00+07:00')


def test_budget_boundaries_counts_quartiles_and_scope_are_explicit():
    snapshot = build(rows())
    assert snapshot['schema_version'] == 1
    assert snapshot['segments'][0]['n'] == 20
    assert snapshot['segments'][0]['asking_ty']['median'] == pytest.approx(1.95)
    assert snapshot['segments'][0]['asking_ty']['p25'] == pytest.approx(1.475)
    assert sum(r['n'] for r in snapshot['budgets']) == 20
    assert [r['n'] for r in snapshot['budgets']] == [5, 5, 10]
    assert snapshot['period_end'] == '2026-10-01'
    assert snapshot['generated_at'].startswith('2026-10-01')
    assert 'current_known' in snapshot['price_time_basis']
    assert 'phone' not in str(snapshot) and 'seller' not in str(snapshot)


def test_missing_small_and_invalid_are_not_zero_or_invented_prices():
    snapshot = build(rows(7))
    segment = snapshot['segments'][0]
    assert segment['n'] == 7
    assert segment['asking_ty']['median'] is None
    assert segment['ppm2']['p25'] is None
    assert snapshot['budgets'][0]['n'] == 5
    assert build([])['segments'] == []


def test_sale_source_measurement_duplicate_quality_and_unknown_gates():
    good = rows(1)[0]
    items = [good, deepcopy(good)]
    for i, change in enumerate([
        {'tx_type': 'thue'}, {'source': 'guland'}, {'price_ty': float('nan')},
        {'area_m2': 0}, {'price_per_m2': 200}, {'duplicate_of_id': 1},
        {'extraction_quality_flags': 'ambiguous_price_text'}, {'property_type': 'unknown'},
        {'review_hidden': 1}, {'valuation_is_outlier': 1},
    ], 2):
        items.append(dict(good, id=i, **change))
    snapshot = build(items)
    assert snapshot['qualified_count'] == 1
    assert snapshot['excluded_count'] == 11


def test_observed_history_is_not_sold_time_and_needs_real_events():
    items = rows(20)
    items[0]['price_events'] = [{'recorded_at': '2026-09-10', 'old_price_ty': 1.2, 'new_price_ty': 1.0}]
    items[1]['price_events'] = [{'recorded_at': '2026-10-10', 'old_price_ty': 1.2, 'new_price_ty': 1.0}]
    snapshot = build(items)
    assert snapshot['history']['observed_drop_count'] == 1
    assert snapshot['history']['days_observed_n'] == 20
    assert snapshot['history']['days_observed']['median'] == 19
    assert 'sold' not in snapshot['history']


def test_unclosed_month_cannot_be_frozen_and_future_fields_are_ignored():
    from services.report_buyer_snapshot import build_buyer_snapshot
    with pytest.raises(ValueError):
        build_buyer_snapshot(rows(), period_start='2026-10-01', period_end='2026-11-01',
                             generated_at='2026-10-25T08:00:00+07:00')
    r = rows(1)
    r[0]['last_seen_at'] = '2026-12-01'
    assert build(r)['history']['days_observed_n'] == 0


def test_real_postgres_query_uses_sale_cohort_and_prior_price_evidence_only():
    from db.connection import connect
    from services.report_buyer_snapshot import query_buyer_snapshot
    conn = connect()  # The shared DB guard requires RADAR_TEST_DATABASE_URL under pytest.
    try:
        conn.execute('''CREATE TEMP TABLE listings (
            id INT, source TEXT, tx_type TEXT, ward TEXT, property_type TEXT, price_ty REAL,
            area_m2 REAL, price_per_m2 REAL, first_seen_at TEXT, last_seen_at TEXT,
            crawled_at TEXT, extraction_quality_flags TEXT, suspicious_bait INT,
            is_blacklisted INT DEFAULT 0, review_hidden INT DEFAULT 0,
            duplicate_of_id INT, possibly_duplicate INT DEFAULT 0,
            is_outlier INT DEFAULT 0, probably_sold INT DEFAULT 0) ON COMMIT DROP''')
        conn.execute('''CREATE TEMP TABLE valuation_results (id INT, listing_id INT,
            computed_at TEXT, source_quality_flags TEXT, is_outlier INT) ON COMMIT DROP''')
        conn.execute('''CREATE TEMP TABLE price_history (id INT, listing_id INT,
            price_ty REAL, recorded_at TEXT) ON COMMIT DROP''')
        for i in range(21):
            conn.execute('''INSERT INTO listings (id,source,tx_type,ward,property_type,
                price_ty,area_m2,price_per_m2,crawled_at,first_seen_at,last_seen_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (i+1,'facebook','ban' if i<20 else 'thue','Phu My' if i%2 else 'Phú Mỹ','dat_nen',
                 2,100,20,'2026-09-10','2026-09-01','2026-09-20'))
        conn.execute("INSERT INTO price_history VALUES (1,1,2.5,'2026-08-30'),(2,1,2,'2026-09-11'),(3,2,1.8,'2026-10-02')")
        snap = query_buyer_snapshot(conn,['Phú Mỹ'],'2026-09-01','2026-10-01',
                                   generated_at='2026-10-01T08:00:00+07:00')
        assert snap['qualified_count'] == 20
        assert [r['scope'] for r in snap['comparisons']] == ['Phú Mỹ']
        assert snap['segments'][0]['ppm2']['median'] == 20
        assert snap['history']['observed_drop_count'] == 1
    finally:
        conn.rollback()
        conn.close()
