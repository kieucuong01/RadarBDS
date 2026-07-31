"""Database facade for Radar BDS.

Connection handling lives in `db.connection`; schema and migrations live in
`db.schema`; repository helpers live in focused `db.*` modules. This module keeps
historical imports stable.
"""
from db.analytics import save_valuation_result
from db.connection import DB_PATH, close_all, get_conn
from db.crawl_runs import finish_crawl_run, mark_missing_listings, start_crawl_run
from db.listings import insert_images, update_listing_outlier, upsert_listing
from db.moderation import is_phone_blacklisted, normalize_phone
from db.raw_listings import (
    get_existing_source_ids,
    get_raw_for_reprocess,
    get_raw_urls,
    insert_raw,
    insert_raw_result,
    RawInsertResult,
    refresh_raw_listing,
)
from db.schema import SCHEMA_SQL, init_schema

__all__ = [
    "DB_PATH",
    "SCHEMA_SQL",
    "close_all",
    "finish_crawl_run",
    "get_conn",
    "get_existing_source_ids",
    "get_raw_for_reprocess",
    "get_raw_urls",
    "init_schema",
    "insert_images",
    "is_phone_blacklisted",
    "insert_raw",
    "insert_raw_result",
    "RawInsertResult",
    "refresh_raw_listing",
    "mark_missing_listings",
    "normalize_phone",
    "save_valuation_result",
    "start_crawl_run",
    "update_listing_outlier",
    "upsert_listing",
]
