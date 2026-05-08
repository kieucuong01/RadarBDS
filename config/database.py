"""
Database connection pool & schema initialization
"""
import logging
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool

from config.settings import DB_URL, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS

logger = logging.getLogger(__name__)

_pool: pool.ThreadedConnectionPool = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS areas (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) UNIQUE NOT NULL,
    province    VARCHAR(100),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS listings (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(50) NOT NULL,          -- 'batdongsan' | 'facebook' | 'nha' | ...
    external_id     VARCHAR(200),                  -- ID gốc từ trang nguồn
    url             TEXT UNIQUE,
    title           TEXT,
    description     TEXT,
    area_id         INT REFERENCES areas(id),
    raw_area_text   VARCHAR(200),                  -- địa chỉ gốc chưa chuẩn hóa
    price_total     NUMERIC(18,3),                 -- tỷ VND
    price_per_m2    NUMERIC(18,3),                 -- triệu VND/m2
    area_m2         NUMERIC(10,2),
    property_type   VARCHAR(50),                   -- 'dat_nen' | 'nha_pho' | 'nha_tro' | ...
    transaction_type VARCHAR(20),                  -- 'ban' | 'thue'
    contact_phone   VARCHAR(50),
    seller_name     VARCHAR(200),
    keywords        TEXT[],                        -- từ khóa trích xuất
    is_hot          BOOLEAN DEFAULT FALSE,         -- tin ngộp / bán gấp
    raw_json        JSONB,                         -- toàn bộ data gốc
    posted_at       TIMESTAMPTZ,
    crawled_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS price_history (
    id          SERIAL PRIMARY KEY,
    listing_id  INT REFERENCES listings(id) ON DELETE CASCADE,
    price_total NUMERIC(18,3),
    price_per_m2 NUMERIC(18,3),
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS area_stats (
    id              SERIAL PRIMARY KEY,
    area_id         INT REFERENCES areas(id),
    stat_date       DATE NOT NULL,
    avg_price_per_m2 NUMERIC(18,3),
    median_price_per_m2 NUMERIC(18,3),
    min_price_per_m2 NUMERIC(18,3),
    max_price_per_m2 NUMERIC(18,3),
    listing_count   INT,
    gross_rental_yield NUMERIC(5,2),               -- % tỷ suất cho thuê
    UNIQUE(area_id, stat_date)
);

CREATE TABLE IF NOT EXISTS sentiment_logs (
    id          SERIAL PRIMARY KEY,
    area_id     INT REFERENCES areas(id),
    source      VARCHAR(50),
    post_text   TEXT,
    sentiment   VARCHAR(20),                       -- 'buy_intent' | 'sell_panic' | 'neutral'
    score       NUMERIC(5,3),
    keywords    TEXT[],
    crawled_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alert_logs (
    id          SERIAL PRIMARY KEY,
    listing_id  INT REFERENCES listings(id),
    alert_type  VARCHAR(100),
    message     TEXT,
    sent_at     TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_listings_area_id      ON listings(area_id);
CREATE INDEX IF NOT EXISTS idx_listings_source       ON listings(source);
CREATE INDEX IF NOT EXISTS idx_listings_crawled_at   ON listings(crawled_at DESC);
CREATE INDEX IF NOT EXISTS idx_listings_price_per_m2 ON listings(price_per_m2);
CREATE INDEX IF NOT EXISTS idx_listings_is_hot       ON listings(is_hot) WHERE is_hot = TRUE;
CREATE INDEX IF NOT EXISTS idx_price_history_listing ON price_history(listing_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_area_stats_date       ON area_stats(area_id, stat_date DESC);
"""

SEED_AREAS_SQL = """
INSERT INTO areas (name, province) VALUES
    ('Tân An',      'Long An'),
    ('Mỹ Phước',    'Bình Dương'),
    ('Phước Long',  'Bình Phước'),
    ('Thủ Dầu Một', 'Bình Dương')
ON CONFLICT (name) DO NOTHING;
"""


def init_pool(minconn: int = 2, maxconn: int = 20) -> None:
    global _pool
    try:
        _pool = pool.ThreadedConnectionPool(
            minconn, maxconn,
            host=DB_HOST, port=DB_PORT,
            dbname=DB_NAME, user=DB_USER, password=DB_PASS
        )
        logger.info("DB connection pool initialized")
    except Exception as e:
        logger.critical(f"Failed to init DB pool: {e}")
        raise


def close_pool() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        logger.info("DB pool closed")


@contextmanager
def get_conn():
    global _pool
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def init_schema() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
            cur.execute(SEED_AREAS_SQL)
    logger.info("Schema initialized & areas seeded")
