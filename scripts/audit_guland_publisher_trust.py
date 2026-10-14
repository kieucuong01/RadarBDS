"""Read-only Guland promotion impact report; --apply reclassifies atomically."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.connection import get_conn
from db.guland_publishers import (
    publisher_feed_join_sql,
    publisher_signal_eligibility_from_join_sql,
    recompute_publisher,
)
from services.guland_publisher_activity import MIN_OBSERVATION_SPAN_DAYS, MIN_OBSERVED_DAYS_30D
from services.market_data import build_deal_sql, _signal_listing_data_sql, LATEST_SHADOW_VALUATION_CTE
from services.signal_quality import LATEST_VALUATION_CTE, actionable_listing_sql
from services.signal_read_model import refresh_signal_card_read_model


def build_report(conn, sample_limit: int = 30) -> dict:
    """Only aggregate counts and bounded listing samples; no publisher PII."""
    sample_limit = max(1, min(int(sample_limit), 30))
    trusted = publisher_signal_eligibility_from_join_sql('l', 'sp')
    candidate = build_deal_sql(15).condition
    cte = f"""WITH {LATEST_VALUATION_CTE}, {LATEST_SHADOW_VALUATION_CTE},
        classified AS (
            SELECT l.id, l.ward, l.price_ty, l.area_m2,
                CASE WHEN {trusted} THEN 'eligible'
                     WHEN sp.activity_class IN ('high_activity', 'automated_repost') THEN sp.activity_class
                     WHEN sp.id IS NULL THEN 'unidentified'
                     ELSE 'insufficient_history' END AS category,
                ({candidate} AND {_signal_listing_data_sql('l')}
                 AND {actionable_listing_sql('l')}
                 AND COALESCE(l.source_status, 'unknown') <> 'inactive') AS candidate_signal
            FROM listings l
            {publisher_feed_join_sql('l', 'lp', 'sp')}
            LEFT JOIN latest_valuation v ON v.listing_id=l.id
            LEFT JOIN latest_shadow_valuation sv ON sv.listing_id=l.id
            WHERE l.source='guland'
        ) """
    groups = conn.execute(cte + """
        SELECT category, COUNT(*) AS listings,
               COUNT(*) FILTER (WHERE candidate_signal) AS candidate_signals
        FROM classified GROUP BY category ORDER BY category
    """).fetchall()
    samples = conn.execute(cte + """, ranked AS (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY category ORDER BY candidate_signal DESC, id DESC) AS rank
        FROM classified
    ) SELECT id, ward, price_ty, area_m2, category, candidate_signal
      FROM ranked WHERE rank <= ? ORDER BY category, rank
    """, (sample_limit,)).fetchall()
    return {
        'policy': {
            'min_observation_span_days': MIN_OBSERVATION_SPAN_DAYS,
            'min_observed_days_30d': MIN_OBSERVED_DAYS_30D,
            'facebook': 'unchanged',
            'basis': 'stored publisher metrics; --apply recomputes before publication',
        },
        'groups': [dict(row) for row in groups],
        'samples': [dict(row) for row in samples],
    }


def apply_reclassification(conn):
    """Caller owns commit/rollback of classification, complete cards and versions."""
    today = datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).date()
    publishers = conn.execute("""
        SELECT id FROM source_publishers WHERE source='guland' ORDER BY id FOR UPDATE
    """).fetchall()
    for row in publishers:
        recompute_publisher(conn, int(row['id']), today)
    listing_ids = tuple(int(row['id']) for row in conn.execute(
        "SELECT id FROM listings WHERE source='guland' ORDER BY id"
    ).fetchall())
    return refresh_signal_card_read_model(conn, listing_ids=listing_ids, market_changed=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample-limit', type=int, default=30)
    parser.add_argument('--apply', action='store_true', help='Reclassify and publish in one PostgreSQL transaction')
    args = parser.parse_args()
    if args.apply:
        from db.schema import init_schema
        init_schema()
    with get_conn() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        if not args.apply:
            conn.execute('SET TRANSACTION READ ONLY')
        conn.execute("SET LOCAL statement_timeout='120s'")
        result = apply_reclassification(conn) if args.apply else None
        report = build_report(conn, args.sample_limit)
    report['mode'] = 'applied' if args.apply else 'dry_run'
    if result is not None:
        report['publication'] = asdict(result)
        # PostgreSQL is committed. Cache failures cannot undo that publication.
        from services.public_cache import publish_dataset_versions
        try:
            publish_dataset_versions(result.versions)
            report['version_mirror'] = 'ok'
        except Exception as exc:
            report['version_mirror'] = {'status': 'error', 'error_type': type(exc).__name__}
        if os.getenv('RADAR_PUBLIC_CACHE_ENABLED', '0').strip() == '1':
            from services.public_prewarm import prewarm_configured_routes
            try:
                report['prewarm'] = prewarm_configured_routes(listings_version=result.versions.get('listings', 0))
            except Exception as exc:
                report['prewarm'] = {'status': 'error', 'error_type': type(exc).__name__}
    print(json.dumps(report, ensure_ascii=False, default=str, indent=2))


if __name__ == '__main__':
    main()
