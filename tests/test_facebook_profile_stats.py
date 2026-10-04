import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest import mock

import psycopg
import pytest

from db.connection import PgConnection
from services import admin_quality


@pytest.fixture
def profile_db():
    url = os.environ.get('RADAR_TEST_DATABASE_URL', '')
    if not url or 'test' not in psycopg.conninfo.conninfo_to_dict(url).get('dbname', ''):
        pytest.fail('An explicit RADAR_TEST_DATABASE_URL test database is required')
    with psycopg.connect(url) as raw:
        raw.execute('''
            CREATE TEMP TABLE raw_listings (id SERIAL PRIMARY KEY, source TEXT,
                url TEXT, raw_json TEXT, crawled_at TEXT, UNIQUE(source,url));
            CREATE TEMP TABLE listings (id SERIAL PRIMARY KEY, raw_id INTEGER,
                title TEXT, description TEXT, price_ty FLOAT, area_m2 FLOAT,
                ward TEXT, property_type TEXT);
            CREATE TEMP TABLE listing_images (listing_id INTEGER);
            CREATE TEMP TABLE valuation_results (id SERIAL PRIMARY KEY,
                listing_id INTEGER, source_quality_flags TEXT);
            CREATE TEMP TABLE admin_jobs (id TEXT, kind TEXT, profile_url TEXT,
                status TEXT, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ, stats JSONB);
            CREATE TEMP TABLE crawl_runs (id INTEGER, source TEXT, started_at TEXT);
            CREATE TEMP TABLE crawl_run_progress (id SERIAL PRIMARY KEY, run_id INTEGER, target_url TEXT,
                status TEXT, completed_at TEXT);
        ''')
        conn = PgConnection(raw)

        @contextmanager
        def factory():
            yield conn

        yield conn, factory
        raw.rollback()


def insert_post(conn, profile, index, *, received='2026-08-01T10:00:00+07:00', posted=None):
    data = {'profile_url': profile, 'date_raw': posted or received,
            'description': 'Bán đất Tân An, diện tích rõ, giá rõ, sổ riêng. ' * 3,
            'imgs': ['https://example.test/photo.jpg']}
    cursor = conn.execute('INSERT INTO raw_listings(source,url,raw_json,crawled_at) VALUES(?,?,?,?)',
                          ('facebook', f'{profile}/posts/{index}', json.dumps(data), received))
    conn.execute('''INSERT INTO listings(raw_id,title,description,price_ty,area_m2,ward,property_type)
                    VALUES(?,?,?,2.5,100,'Tân An','dat_nen')''',
                 (cursor.lastrowid, str(index), data['description']))


def test_other_brokers_new_posts_do_not_erase_old_broker_quality(profile_db):
    conn, factory = profile_db
    old = 'https://www.facebook.com/old-broker'
    for index in range(8):
        insert_post(conn, old, index)
    conn.execute('''INSERT INTO raw_listings(source,url,raw_json,crawled_at)
                    SELECT 'facebook','https://example.test/busy/' || n,?, '2026-10-04T10:00:00+07:00'
                    FROM generate_series(1,3100) n''',
                 (json.dumps({'profile_url': 'https://www.facebook.com/busy-broker'}),))
    stats = admin_quality.facebook_profile_stats([old], conn_factory=factory)[old]
    assert stats['raw_count'] == 8
    assert stats['data_quality']['sample_size'] == 8
    assert stats['data_quality']['score'] == 100
    assert stats['latest_received_at'] == '2026-08-01T10:00:00+07:00'
    assert stats['data_quality']['is_stale'] is True


def test_quality_sample_is_bounded_without_truncating_history(profile_db):
    conn, factory = profile_db
    url = 'https://www.facebook.com/sampled-broker'
    for index in range(120):
        insert_post(conn, url, index)
    stats = admin_quality.facebook_profile_stats([url], conn_factory=factory)[url]
    assert stats['raw_count'] == 120
    assert stats['data_quality']['sample_size'] == 100


def test_real_small_sample_stays_insufficient_and_mobile_url_is_matched(profile_db):
    conn, factory = profile_db
    for index in range(4):
        insert_post(conn, 'https://m.facebook.com/small/?ref=bookmarks', index)
    url = 'https://www.facebook.com/small'
    stats = admin_quality.facebook_profile_stats([url], conn_factory=factory)[url]
    assert stats['raw_count'] == 4
    assert stats['data_quality']['sample_size'] == 4
    assert stats['data_quality']['score'] is None


def test_full_import_of_old_posts_does_not_count_as_recent_posting():
    rows = [{'crawled_at': datetime.now(timezone.utc).isoformat(),
             'raw': {'date_raw': '2026-01-01T10:00:00+07:00'}} for _ in range(100)]
    activity = admin_quality.facebook_profile_activity(rows)
    assert activity['posts_7d'] == 0
    assert activity['posts_30d'] == 0
    assert activity['confidence'] == 'low'


def test_missing_post_dates_are_reported_instead_of_using_import_dates():
    activity = admin_quality.facebook_profile_activity([{'crawled_at': '2026-10-04'}])
    assert activity['posts_30d'] == 0
    assert activity['dated_posts'] == 0
    assert activity['undated_posts'] == 1


def test_stats_failure_is_explicit_instead_of_looking_like_no_history():
    @contextmanager
    def broken():
        raise RuntimeError('private connection details')
        yield

    url = 'https://www.facebook.com/broker'
    with mock.patch.object(admin_quality, 'logger', create=True) as logger:
        stat = admin_quality.facebook_profile_stats([url], conn_factory=broken)[url]
    assert stat['stats_status'] == 'unavailable'
    assert stat['data_quality']['status'] == 'unavailable'
    assert 'private connection details' not in json.dumps(stat)
    assert logger.warning.called


def test_manual_run_without_new_posts_is_distinct_from_last_received_post(profile_db):
    conn, factory = profile_db
    url = 'https://www.facebook.com/history-broker'
    insert_post(conn, url, 1)
    conn.execute('''INSERT INTO admin_jobs(id,kind,profile_url,status,started_at,finished_at,created_at,stats)
                    VALUES('job','facebook_crawl',?,'succeeded',
                    '2026-10-04T10:00:00+07:00','2026-10-04T10:05:00+07:00',
                    '2026-10-04T10:00:00+07:00','{"crawl":{"fetched":0,"inserted":0}}')''', (url,))
    stat = admin_quality.facebook_profile_stats([url], conn_factory=factory)[url]
    assert stat['last_crawl']['status'] == 'succeeded'
    assert str(stat['last_crawl']['started_at']).startswith('2026-10-04')
    assert stat['latest_received_at'] == '2026-08-01T10:00:00+07:00'


def test_crawl_calendar_uses_vietnam_date_before_utc_midnight():
    from crawler import facebook_apify
    now = datetime(2026, 10, 4, 21, tzinfo=timezone.utc)
    with mock.patch.object(facebook_apify, 'datetime') as clock:
        clock.now.return_value = now
        day = facebook_apify.facebook_crawl_today()
    assert day.isoformat() == '2026-10-05'


def test_unprocessed_posts_are_not_misclassified_as_bad_broker_quality(profile_db):
    conn, factory = profile_db
    url = 'https://www.facebook.com/pending-broker'
    for index in range(8):
        insert_post(conn, url, index)
    conn.execute('DELETE FROM listings')
    stat = admin_quality.facebook_profile_stats([url], conn_factory=factory)[url]
    assert stat['raw_count'] == 8
    assert stat['data_quality']['score'] is None
    assert stat['data_quality']['status'] == 'pending'
    assert stat['data_quality']['unprocessed_count'] == 8


def test_numeric_profile_php_and_source_input_identity_are_preserved(profile_db):
    conn, factory = profile_db
    url = 'https://www.facebook.com/profile.php?id=123456789'
    insert_post(conn, 'https://www.facebook.com/author-alias', 0)
    conn.execute('''UPDATE raw_listings SET raw_json =
        jsonb_set(raw_json::jsonb, '{_apify_raw}', ?::jsonb)::text''',
                 (json.dumps({'inputUrl': 'https://m.facebook.com/profile.php?ref=bookmarks&id=123456789'}),))
    stat = admin_quality.facebook_profile_stats([url], conn_factory=factory)[url]
    assert stat['raw_count'] == 1
    assert stat['data_quality']['sample_size'] == 1


def test_daily_run_history_is_recorded_even_when_no_posts_were_imported(profile_db, monkeypatch):
    from cli.crawlers import _record_facebook_profile_runs
    import db.crawl_runs as runs

    conn, factory = profile_db
    conn.execute('ALTER TABLE crawl_run_progress ADD COLUMN n_new INTEGER, ADD COLUMN error_msg TEXT')
    conn.execute('ALTER TABLE crawl_run_progress ADD UNIQUE(run_id,target_url)')
    conn.execute("INSERT INTO crawl_runs(id,source,started_at) VALUES(123,'facebook','2026-10-04T10:00:00+07:00')")
    monkeypatch.setattr(runs, 'get_conn', factory)
    url = 'https://www.facebook.com/empty-profile'
    _record_facebook_profile_runs(123, {'attempted_profile_urls': [url], 'completed_profile_urls': [url]})
    stat = admin_quality.facebook_profile_stats([url], conn_factory=factory)[url]
    assert stat['raw_count'] == 0
    assert stat['last_crawl']['status'] == 'done'


def test_failed_daily_attempt_is_distinct_from_unattempted_quota_profiles(profile_db, monkeypatch):
    from cli.crawlers import _record_facebook_profile_runs
    import db.crawl_runs as runs

    conn, factory = profile_db
    conn.execute('ALTER TABLE crawl_run_progress ADD COLUMN n_new INTEGER, ADD COLUMN error_msg TEXT')
    conn.execute('ALTER TABLE crawl_run_progress ADD UNIQUE(run_id,target_url)')
    conn.execute("INSERT INTO crawl_runs(id,source,started_at) VALUES(123,'facebook','2026-10-04T10:00:00+07:00')")
    monkeypatch.setattr(runs, 'get_conn', factory)
    attempted = 'https://www.facebook.com/tried-profile'
    unattempted = 'https://www.facebook.com/not-tried'
    _record_facebook_profile_runs(123, {'attempted_profile_urls': [attempted], 'completed_profile_urls': []})
    stats = admin_quality.facebook_profile_stats([attempted, unattempted], conn_factory=factory)
    assert stats[attempted]['last_crawl']['status'] == 'error'
    assert stats[unattempted]['last_crawl'] is None
