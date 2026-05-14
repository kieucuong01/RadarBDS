"""SQLite schema and idempotent migrations for Radar BDS."""
import logging
import sqlite3

from db.connection import DB_PATH, get_conn

logger = logging.getLogger(__name__)
SCHEMA_SQL = """
-- ================================================================
-- TẦNG 1: RAW — source of truth, không bao giờ xóa/sửa
-- ================================================================
CREATE TABLE IF NOT EXISTS raw_listings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,        -- 'batdongsan' | 'guland' | 'facebook'
    source_id    TEXT,                 -- post ID gốc từ nguồn
    url          TEXT NOT NULL,
    raw_json     TEXT NOT NULL,        -- toàn bộ fields parser trả về, chưa normalize
    crawled_at   TEXT DEFAULT (datetime('now')),
    crawl_run_id INTEGER,
    UNIQUE(source, url)                -- mỗi URL chỉ lưu 1 lần (crawl lại → bỏ qua)
);

CREATE INDEX IF NOT EXISTS idx_raw_source    ON raw_listings(source, source_id);
CREATE INDEX IF NOT EXISTS idx_raw_url       ON raw_listings(url);
CREATE INDEX IF NOT EXISTS idx_raw_crawled   ON raw_listings(crawled_at DESC);


-- ================================================================
-- TẦNG 2: PROCESSED — output của pipeline, reprocessable từ raw
-- ================================================================
CREATE TABLE IF NOT EXISTS listings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_id              INTEGER REFERENCES raw_listings(id),  -- trace ngược về raw
    source              TEXT NOT NULL,
    source_id           TEXT,
    url                 TEXT UNIQUE NOT NULL,
    title               TEXT,
    description         TEXT,
    area                TEXT,
    raw_area_text       TEXT,
    price_ty            REAL,                       -- tỷ VND
    price_per_m2        REAL,                       -- triệu/m²
    area_m2             REAL,
    property_type       TEXT,
    tx_type             TEXT DEFAULT 'ban',
    frontage_m          REAL,
    depth_m             REAL,
    road_width_m        REAL,
    road_type           TEXT DEFAULT 'unknown',
    has_so              INTEGER DEFAULT 0,
    is_hot              INTEGER DEFAULT 0,
    contact_phone       TEXT,
    seller_name         TEXT,

    -- Outlier flag (thay vì drop)
    is_outlier          INTEGER DEFAULT 0,   -- 1 = nằm ngoài ±2σ của segment
    outlier_direction   TEXT,                -- 'high' | 'low' (low = có thể là deal thật)
    outlier_sigma       REAL,                -- cách mean bao nhiêu sigma

    -- Price tracking
    price_dropped       INTEGER DEFAULT 0,
    price_drop_pct      REAL,
    price_first_ty      REAL,
    suspicious_bait     INTEGER DEFAULT 0,

    -- OCR sổ hồng
    thua_so             TEXT,
    to_ban_do           TEXT,
    dien_tich_tho_cu_ocr REAL,
    dia_chi_thua        TEXT,

    -- Sold tracking
    sold_at             TEXT,
    probably_sold       INTEGER DEFAULT 0,
    consecutive_missing INTEGER DEFAULT 0,

    -- Dedup flag
    possibly_duplicate  INTEGER DEFAULT 0,   -- 1 = có thể trùng với listing khác
    duplicate_of_id     INTEGER DEFAULT NULL, -- FK → listings.id canonical

    -- Meta
    crawled_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    posted_at           TEXT,                             -- ngày đăng từ bài post (khác crawled_at)

    -- LLM Enrichment
    llm_verified        INTEGER DEFAULT 0,
    llm_notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_listings_source        ON listings(source, source_id);
CREATE INDEX IF NOT EXISTS idx_listings_area          ON listings(area);
CREATE INDEX IF NOT EXISTS idx_listings_property_type ON listings(property_type);
CREATE INDEX IF NOT EXISTS idx_listings_price_per_m2  ON listings(price_per_m2);
CREATE INDEX IF NOT EXISTS idx_listings_is_hot        ON listings(is_hot);
CREATE INDEX IF NOT EXISTS idx_listings_is_outlier    ON listings(is_outlier);
CREATE INDEX IF NOT EXISTS idx_listings_crawled_at    ON listings(crawled_at DESC);
CREATE INDEX IF NOT EXISTS idx_listings_probably_sold ON listings(probably_sold);
CREATE INDEX IF NOT EXISTS idx_listings_raw_id        ON listings(raw_id);


-- ================================================================
-- TẦNG 3: ENRICHMENT
-- ================================================================
CREATE TABLE IF NOT EXISTS listing_images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id  INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    img_url     TEXT NOT NULL,
    img_order   INTEGER DEFAULT 0,
    img_type    TEXT DEFAULT 'unknown',   -- cover | so_hong | aerial | street | unknown
    local_path  TEXT,
    ocr_text    TEXT,
    crawled_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(listing_id, img_url)
);

CREATE INDEX IF NOT EXISTS idx_images_listing ON listing_images(listing_id);
CREATE INDEX IF NOT EXISTS idx_images_type    ON listing_images(img_type);


CREATE TABLE IF NOT EXISTS price_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id   INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    price_ty     REAL,
    price_per_m2 REAL,
    crawl_run_id INTEGER,
    recorded_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_price_history_listing ON price_history(listing_id, recorded_at DESC);


-- ================================================================
-- TẦNG 4: ANALYTICS
-- ================================================================
CREATE TABLE IF NOT EXISTS crawl_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT DEFAULT (datetime('now')),
    finished_at     TEXT,
    source          TEXT,
    area            TEXT,
    n_fetched       INTEGER DEFAULT 0,
    n_new           INTEGER DEFAULT 0,
    n_updated       INTEGER DEFAULT 0,
    n_price_dropped INTEGER DEFAULT 0,
    n_skipped       INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'running',
    error_msg       TEXT
);

CREATE TABLE IF NOT EXISTS crawl_run_progress (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL,
    target_url      TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',
    n_new           INTEGER DEFAULT 0,
    completed_at    TEXT,
    UNIQUE(run_id, target_url)
);


CREATE TABLE IF NOT EXISTS market_weekly (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    week            TEXT NOT NULL,
    area            TEXT NOT NULL,
    property_type   TEXT NOT NULL,
    median_ppm2     REAL,
    avg_ppm2        REAL,
    n_listings      INTEGER DEFAULT 0,
    n_outlier_low   INTEGER DEFAULT 0,   -- số listing outlier thấp (potential deals)
    n_new           INTEGER DEFAULT 0,
    n_dropped       INTEGER DEFAULT 0,
    computed_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(week, area, property_type)
);

CREATE INDEX IF NOT EXISTS idx_market_weekly_week ON market_weekly(week DESC, area, property_type);


CREATE TABLE IF NOT EXISTS alert_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id  INTEGER REFERENCES listings(id),
    alert_type  TEXT,
    message     TEXT,
    sent_date   TEXT DEFAULT (date('now')),
    sent_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(listing_id, alert_type, sent_date)
);


CREATE TABLE IF NOT EXISTS valuation_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id      INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    crawl_run_id    INTEGER,
    fair_ppm2       REAL,
    actual_ppm2     REAL,
    mos_pct         REAL,
    is_signal       INTEGER DEFAULT 0,
    is_outlier      INTEGER DEFAULT 0,
    outlier_direction TEXT,
    outlier_sigma   REAL,
    segment         TEXT,
    n_segment       INTEGER,
    computed_at     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_valuation_listing  ON valuation_results(listing_id);
CREATE INDEX IF NOT EXISTS idx_valuation_signal   ON valuation_results(is_signal, mos_pct DESC);
CREATE INDEX IF NOT EXISTS idx_valuation_computed ON valuation_results(computed_at DESC);


-- ═══════════════════════════════════════════════════════════════════
-- Admin Control Room
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS lead_captures (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    listing_id      INTEGER REFERENCES listings(id) ON DELETE SET NULL,
    listing_url     TEXT,
    zalo_phone      TEXT NOT NULL,
    source_context  TEXT,   -- card_signal | modal_signal | listing_detail
    note            TEXT,
    status          TEXT DEFAULT 'new' -- new | called | viewing | deposit | cancelled
);
CREATE INDEX IF NOT EXISTS idx_leads_created_at ON lead_captures(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_status ON lead_captures(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_listing ON lead_captures(listing_id);

CREATE TABLE IF NOT EXISTS dedup_overrides (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    action              TEXT NOT NULL,  -- merge | split
    listing_id          INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    target_listing_id   INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    note                TEXT,
    active              INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_dedup_overrides_active ON dedup_overrides(active, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_dedup_overrides_pair ON dedup_overrides(listing_id, target_listing_id, active);

CREATE TABLE IF NOT EXISTS broker_blacklist (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    phone_norm      TEXT NOT NULL,
    reason          TEXT,
    active          INTEGER DEFAULT 1,
    UNIQUE(phone_norm)
);
CREATE INDEX IF NOT EXISTS idx_broker_blacklist_active ON broker_blacklist(active, phone_norm);

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT DEFAULT (datetime('now')),
    actor           TEXT DEFAULT 'admin',
    action          TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    entity_id       INTEGER,
    before_json     TEXT,
    after_json      TEXT,
    reason          TEXT
);
CREATE INDEX IF NOT EXISTS idx_admin_audit_entity ON admin_audit_log(entity_type, entity_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_action ON admin_audit_log(action, created_at DESC);

CREATE TABLE IF NOT EXISTS ai_training_feedback (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    listing_id          INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    actor               TEXT DEFAULT 'admin',
    verdict             TEXT NOT NULL,
    extraction_verdict  TEXT,
    valuation_verdict   TEXT,
    reason_code         TEXT,
    reason_text         TEXT,
    reason_tags         TEXT,
    note                TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_training_listing ON ai_training_feedback(listing_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_training_verdict ON ai_training_feedback(verdict, created_at DESC);

CREATE TABLE IF NOT EXISTS infra_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    kind            TEXT NOT NULL,      -- timeline | policy
    title           TEXT NOT NULL,
    subtitle        TEXT,
    summary         TEXT,
    ward            TEXT,
    road_ref        TEXT,
    project_code    TEXT,
    milestone_label TEXT,
    progress_pct    REAL,
    status_tag      TEXT,               -- done | in_progress | planned
    severity        TEXT,               -- critical | warning | info
    event_date      TEXT,
    source_url      TEXT,
    sort_order      INTEGER DEFAULT 0,
    active          INTEGER DEFAULT 1,
    created_by      TEXT DEFAULT 'admin'
);
CREATE INDEX IF NOT EXISTS idx_infra_kind_active ON infra_entries(kind, active, sort_order, event_date DESC);
"""


def init_schema() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        # Migration: thêm cột mới cho DB cũ (ALTER TABLE idempotent)
        _run_migrations(conn)
    logger.info(f"SQLite schema initialized: {DB_PATH}")


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Thêm cột mới vào bảng cũ nếu chưa có (idempotent)."""
    existing = {r[1] for r in conn.execute("PRAGMA table_info(listings)").fetchall()}
    migrations = [
        ("possibly_duplicate", "ALTER TABLE listings ADD COLUMN possibly_duplicate INTEGER DEFAULT 0"),
        ("duplicate_of_id",    "ALTER TABLE listings ADD COLUMN duplicate_of_id INTEGER DEFAULT NULL"),
        ("road_tier",          "ALTER TABLE listings ADD COLUMN road_tier INTEGER DEFAULT 0"),
        ("ward",               "ALTER TABLE listings ADD COLUMN ward TEXT"),
        # Logic giá trị: lifecycle tracking = feedback loop từ thị trường
        # Listing biến mất nhanh = deal đã khớp → proof-of-signal + boost confidence segment
        ("first_seen_at",      "ALTER TABLE listings ADD COLUMN first_seen_at TEXT"),
        ("last_seen_at",       "ALTER TABLE listings ADD COLUMN last_seen_at TEXT"),
        ("delisted_at",        "ALTER TABLE listings ADD COLUMN delisted_at TEXT"),
        ("is_active",          "ALTER TABLE listings ADD COLUMN is_active INTEGER DEFAULT 1"),
        ("lifecycle_hours",    "ALTER TABLE listings ADD COLUMN lifecycle_hours INTEGER"),
        ("posted_at",          "ALTER TABLE listings ADD COLUMN posted_at TEXT"),
        ("content_hash",       "ALTER TABLE listings ADD COLUMN content_hash TEXT"),
        ("suspicious_bait",    "ALTER TABLE listings ADD COLUMN suspicious_bait INTEGER DEFAULT 0"),
        ("llm_verified",       "ALTER TABLE listings ADD COLUMN llm_verified INTEGER DEFAULT 0"),
        ("llm_notes",          "ALTER TABLE listings ADD COLUMN llm_notes TEXT"),
        ("is_blacklisted",     "ALTER TABLE listings ADD COLUMN is_blacklisted INTEGER DEFAULT 0"),
        ("blacklisted_at",     "ALTER TABLE listings ADD COLUMN blacklisted_at TEXT"),
        ("blacklist_phone_norm", "ALTER TABLE listings ADD COLUMN blacklist_phone_norm TEXT"),
        ("review_hidden",      "ALTER TABLE listings ADD COLUMN review_hidden INTEGER DEFAULT 0"),
        ("review_hidden_at",   "ALTER TABLE listings ADD COLUMN review_hidden_at TEXT"),
        ("review_hidden_reason", "ALTER TABLE listings ADD COLUMN review_hidden_reason TEXT"),
    ]
    for col, sql in migrations:
        if col not in existing:
            try:
                conn.execute(sql)
                logger.info(f"Migration: added listings.{col}")
            except Exception as e:
                logger.warning(f"Migration skip {col}: {e}")

    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_content_hash ON listings(content_hash)")
    except Exception as e:
        logger.warning(f"Index skip idx_listings_content_hash: {e}")

    # Migrations cho valuation_results
    v_existing = {r[1] for r in conn.execute("PRAGMA table_info(valuation_results)").fetchall()}
    v_migrations = [
        ("signal_score", "ALTER TABLE valuation_results ADD COLUMN signal_score INTEGER DEFAULT NULL"),
        ("road_tier",    "ALTER TABLE valuation_results ADD COLUMN road_tier INTEGER DEFAULT 0"),
    ]
    for col, sql in v_migrations:
        if col not in v_existing:
            try:
                conn.execute(sql)
                logger.info(f"Migration: added valuation_results.{col}")
            except Exception as e:
                logger.warning(f"Migration skip valuation_results.{col}: {e}")

    _drop_legacy_feedback(conn)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone())


def _drop_legacy_feedback(conn: sqlite3.Connection) -> None:
    """Backfill review visibility once, then remove legacy feedback tables."""
    if _table_exists(conn, "signal_feedback"):
        try:
            rows = conn.execute("""
                SELECT sf.listing_id, sf.verdict
                  FROM signal_feedback sf
                  JOIN (
                        SELECT listing_id, MAX(id) AS latest_id
                          FROM signal_feedback
                         GROUP BY listing_id
                  ) latest ON latest.latest_id = sf.id
                 WHERE sf.verdict IN ('good', 'bad', 'spam', 'sold')
            """).fetchall()
            for row in rows:
                listing_id = int(row["listing_id"])
                verdict = row["verdict"]
                cluster_ids = {listing_id}
                current = conn.execute(
                    "SELECT id, duplicate_of_id FROM listings WHERE id=?",
                    (listing_id,),
                ).fetchone()
                if current:
                    canonical_id = current["duplicate_of_id"] or current["id"]
                    cluster_ids.add(int(canonical_id))
                    cluster_ids.update(
                        int(r["id"])
                        for r in conn.execute(
                            "SELECT id FROM listings WHERE duplicate_of_id=?",
                            (canonical_id,),
                        ).fetchall()
                    )
                placeholders = ",".join("?" for _ in cluster_ids)
                ids = list(cluster_ids)
                if verdict in ("bad", "spam", "sold"):
                    conn.execute(
                        f"""
                        UPDATE listings
                           SET review_hidden=1,
                               review_hidden_at=COALESCE(review_hidden_at, datetime('now')),
                               review_hidden_reason=COALESCE(review_hidden_reason, ?)
                         WHERE id IN ({placeholders})
                        """,
                        [verdict] + ids,
                    )
                elif verdict == "good":
                    conn.execute(
                        f"""
                        UPDATE listings
                           SET review_hidden=0,
                               review_hidden_at=NULL,
                               review_hidden_reason=NULL
                         WHERE id IN ({placeholders})
                        """,
                        ids,
                    )
            logger.info("Backfilled review_hidden from legacy feedback before drop")
        except Exception as e:
            logger.warning(f"Legacy feedback backfill skipped: {e}")

    for table in ("signal_feedback", "feedback_rules"):
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            logger.info(f"Dropped legacy table: {table}")
        except Exception as e:
            logger.warning(f"Drop legacy table {table} skipped: {e}")


