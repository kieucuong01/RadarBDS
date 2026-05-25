"""
Legacy compatibility facade for the PostgreSQL database layer.

Runtime code should import from focused `db.*` modules directly. This module
only keeps older imports (`from config.database_sqlite import ...`) from
breaking while old scripts are migrated.
"""
from db.sqlite import (  # noqa: F401
    DB_PATH,
    SCHEMA_SQL,
    close_all,
    finish_crawl_run,
    get_conn,
    get_existing_source_ids,
    get_raw_for_reprocess,
    get_raw_urls,
    init_schema,
    insert_images,
    insert_raw,
    mark_missing_listings,
    save_valuation_result,
    start_crawl_run,
    update_listing_outlier,
    upsert_listing,
)
