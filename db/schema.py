"""PostgreSQL schema and idempotent migrations for Radar BDS."""
import logging
from typing import Any

from db.connection import get_conn

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
    road_name           TEXT,
    road_width_m        REAL,
    road_type           TEXT DEFAULT 'unknown',
    tho_cu_m2           REAL,
    tho_cu_ratio        REAL,
    has_so              INTEGER DEFAULT 1,
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
CREATE INDEX IF NOT EXISTS idx_listings_duplicate_of_id ON listings(duplicate_of_id);


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
CREATE INDEX IF NOT EXISTS idx_images_listing_legal_order
    ON listing_images(
        listing_id,
        (CASE WHEN img_type = 'so_hong' THEN 0 ELSE 1 END),
        img_order,
        id
    );


CREATE TABLE IF NOT EXISTS legal_verifications (
    listing_id              INTEGER PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
    status                  TEXT DEFAULT 'unverified',
    trust_tier              TEXT DEFAULT 'candidate_signal',
    confidence_score        INTEGER DEFAULT 0,
    document_image_id       INTEGER REFERENCES listing_images(id) ON DELETE SET NULL,
    thua_so                 TEXT,
    to_ban_do               TEXT,
    legal_area_m2           REAL,
    legal_residential_m2    REAL,
    legal_address           TEXT,
    legal_ward              TEXT,
    legal_road_text         TEXT,
    legal_road_code         TEXT,
    road_match_status       TEXT DEFAULT 'unknown',
    conflict_flags          TEXT,
    evidence_json           TEXT,
    verified_by             TEXT,
    verified_at             TEXT,
    updated_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_legal_verifications_status
    ON legal_verifications(status, trust_tier, confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_legal_verifications_doc
    ON legal_verifications(document_image_id);


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


CREATE TABLE IF NOT EXISTS valuation_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id      INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    crawl_run_id    INTEGER,
    fair_ppm2       REAL,
    actual_ppm2     REAL,
    mos_pct         REAL,
    is_signal       INTEGER DEFAULT 0,
    signal_score    INTEGER DEFAULT NULL,
    is_outlier      INTEGER DEFAULT 0,
    outlier_direction TEXT,
    outlier_sigma   REAL,
    segment         TEXT,
    n_segment       INTEGER,
    source_quality_flags TEXT,
    source_quality_recheck INTEGER DEFAULT 0,
    legal_status    TEXT DEFAULT 'unverified',
    trust_tier      TEXT DEFAULT 'candidate_signal',
    trust_score     INTEGER DEFAULT 0,
    legal_flags     TEXT,
    computed_at     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_valuation_listing  ON valuation_results(listing_id);
CREATE INDEX IF NOT EXISTS idx_valuation_signal   ON valuation_results(is_signal, mos_pct DESC);
CREATE INDEX IF NOT EXISTS idx_valuation_computed ON valuation_results(computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_valuation_listing_computed
    ON valuation_results(listing_id, computed_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_valuation_signal_trust_score
    ON valuation_results(
        (CASE COALESCE(trust_tier, 'candidate_signal')
            WHEN 'has_legal_doc' THEN 0
            ELSE 1
         END),
        trust_score DESC,
        signal_score DESC,
        mos_pct DESC,
        listing_id
    )
    WHERE is_signal = 1;


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

-- Claude pre-review verdicts (CỐ VẤN). Bảng RIÊNG, KHÔNG bao giờ trộn với
-- ai_training_feedback (nhãn người = ground-truth). Append-only history;
-- latest-per-listing giải bằng subquery. Logic định giá chỉ học từ nhãn người.
CREATE TABLE IF NOT EXISTS ai_deal_review (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    listing_id      INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    actor           TEXT DEFAULT 'claude',
    verdict         TEXT NOT NULL,          -- cheap_real|suspect|not_cheap|insufficient_info
    confidence      REAL,                    -- 0.0–1.0
    reasoning       TEXT,
    red_flags       TEXT,                    -- JSON array of strings
    memo_markdown   TEXT,                    -- Claude-authored investment memo, free-form markdown
    needs_map_check INTEGER DEFAULT 0,
    model           TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_deal_review_listing ON ai_deal_review(listing_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_deal_review_verdict ON ai_deal_review(verdict, created_at DESC);

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


-- ═══════════════════════════════════════════════════════════════════
-- RBAC: 4-tier user system (Guest / Free / VIP / Admin)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier          TEXT NOT NULL UNIQUE,            -- normalized phone OR email
    identifier_type     TEXT NOT NULL,                   -- 'phone' | 'email'
    email               TEXT,                            -- = identifier nếu type=email; optional khi type=phone
    phone               TEXT,                            -- = identifier nếu type=phone
    password_hash       TEXT NOT NULL,                   -- bcrypt
    display_name        TEXT,
    tier                TEXT NOT NULL DEFAULT 'free',    -- 'free' | 'vip' | 'admin'
    vip_expires_at      TEXT,                            -- ISO datetime; NULL = chưa VIP
    telegram_chat_id    TEXT,                            -- bound qua /start <token>
    telegram_link_token TEXT,                            -- random token cho deep-link, expire 10 phút
    telegram_link_expires_at TEXT,
    notify_email        INTEGER DEFAULT 1,
    notify_telegram     INTEGER DEFAULT 1,
    created_at          TEXT DEFAULT (datetime('now')),
    last_login_at       TEXT,
    is_banned           INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_users_identifier    ON users(identifier);
CREATE INDEX IF NOT EXISTS idx_users_tier_expires  ON users(tier, vip_expires_at);
CREATE INDEX IF NOT EXISTS idx_users_telegram_chat ON users(telegram_chat_id);


CREATE TABLE IF NOT EXISTS user_sessions (
    token       TEXT PRIMARY KEY,                          -- secrets.token_urlsafe(32)
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL,                             -- ~30 ngày
    user_agent  TEXT,
    ip          TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user    ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON user_sessions(expires_at);


CREATE TABLE IF NOT EXISTS user_watchlists (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    wards            TEXT,        -- JSON array
    prop_types       TEXT,        -- JSON array
    mos_min          INTEGER DEFAULT 0,
    price_max_ty     REAL,
    price_min_ty     REAL,
    area_min         REAL,
    area_max         REAL,
    notify_telegram  INTEGER DEFAULT 1,
    notify_email     INTEGER DEFAULT 1,
    active           INTEGER DEFAULT 1,
    last_notified_at TEXT,
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_watchlists_user_active ON user_watchlists(user_id, active);


CREATE TABLE IF NOT EXISTS user_audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,                  -- nullable: guest tracking
    tier        TEXT,                     -- snapshot tier tại thời điểm action
    action      TEXT NOT NULL,
    listing_id  INTEGER,
    context     TEXT,                     -- JSON tùy action
    ip          TEXT,
    user_agent  TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_user_action ON user_audit_log(user_id, action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action_time ON user_audit_log(action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_listing     ON user_audit_log(listing_id, created_at DESC);


CREATE TABLE IF NOT EXISTS rate_limits (
    key          TEXT PRIMARY KEY,       -- 'listings:user:42' | 'listings:ip:1.2.3.4'
    window_start TEXT,
    count        INTEGER DEFAULT 0
);


-- Notification log: track mỗi push kèm snapshot giá để re-alert khi giảm tiếp.
-- Không có UNIQUE: cho phép nhiều row per (user, listing, channel) khi giá rớt
-- vượt ngưỡng. Dedup ở app-level qua _should_skip_notify() trong cli/notify.py.
CREATE TABLE IF NOT EXISTS notification_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    listing_id         INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    channel            TEXT NOT NULL,           -- 'telegram' | 'email'
    notified_price_ty  REAL,                    -- giá (tỷ) lúc push; NULL = row legacy
    sent_at            TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notif_user_listing
    ON notification_log(user_id, listing_id, sent_at DESC);
"""


def init_schema() -> None:
    with get_conn() as conn:
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT DEFAULT (CURRENT_TIMESTAMP::text)
                )
            """)
            conn.executescript(SCHEMA_SQL)
            # Migration: thêm cột mới cho DB cũ (ALTER TABLE idempotent)
            _run_migrations(conn)
        except Exception as exc:
            if _is_insufficient_privilege_error(exc):
                try:
                    conn.rollback()
                except Exception:
                    pass
                if _core_schema_exists(conn):
                    logger.warning(
                        "PostgreSQL schema init skipped because this DB role lacks DDL ownership; "
                        "existing core tables are present. Error: %s",
                        exc,
                    )
                    return
            raise
    logger.info("PostgreSQL schema initialized")


def _is_insufficient_privilege_error(exc: Exception) -> bool:
    sqlstate = getattr(exc, "sqlstate", "") or getattr(exc, "pgcode", "")
    text = f"{exc.__class__.__name__} {exc}".lower()
    return sqlstate == "42501" or "insufficientprivilege" in text or "must be owner" in text


def _core_schema_exists(conn: Any) -> bool:
    return all(_table_exists(conn, name) for name in ("raw_listings", "listings", "valuation_results", "crawl_runs"))


def _run_migrations(conn: Any) -> None:
    """Thêm cột mới vào bảng cũ nếu chưa có (idempotent)."""
    existing = _table_columns(conn, "listings")
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
        ("tho_cu_m2",          "ALTER TABLE listings ADD COLUMN tho_cu_m2 REAL"),
        ("tho_cu_ratio",       "ALTER TABLE listings ADD COLUMN tho_cu_ratio REAL"),
        ("road_name",          "ALTER TABLE listings ADD COLUMN road_name TEXT"),
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_road_name ON listings(road_name)")
    except Exception as e:
        logger.warning(f"Index skip listings auxiliary indexes: {e}")

    # Migrations cho valuation_results
    v_existing = _table_columns(conn, "valuation_results")
    v_migrations = [
        ("signal_score", "ALTER TABLE valuation_results ADD COLUMN signal_score INTEGER DEFAULT NULL"),
        ("road_tier",    "ALTER TABLE valuation_results ADD COLUMN road_tier INTEGER DEFAULT 0"),
        ("source_quality_flags", "ALTER TABLE valuation_results ADD COLUMN source_quality_flags TEXT"),
        ("source_quality_recheck", "ALTER TABLE valuation_results ADD COLUMN source_quality_recheck INTEGER DEFAULT 0"),
        ("legal_status", "ALTER TABLE valuation_results ADD COLUMN legal_status TEXT DEFAULT 'unverified'"),
        ("trust_tier",   "ALTER TABLE valuation_results ADD COLUMN trust_tier TEXT DEFAULT 'candidate_signal'"),
        ("trust_score",  "ALTER TABLE valuation_results ADD COLUMN trust_score INTEGER DEFAULT 0"),
        ("legal_flags",  "ALTER TABLE valuation_results ADD COLUMN legal_flags TEXT"),
    ]
    for col, sql in v_migrations:
        if col not in v_existing:
            try:
                conn.execute(sql)
                logger.info(f"Migration: added valuation_results.{col}")
            except Exception as e:
                logger.warning(f"Migration skip valuation_results.{col}: {e}")

    # Migrations cho ai_deal_review — Claude-authored memo, append-only
    adr_existing = _table_columns(conn, "ai_deal_review")
    adr_migrations = [
        ("memo_markdown", "ALTER TABLE ai_deal_review ADD COLUMN memo_markdown TEXT"),
    ]
    for col, sql in adr_migrations:
        if col not in adr_existing:
            try:
                conn.execute(sql)
                logger.info(f"Migration: added ai_deal_review.{col}")
            except Exception as e:
                logger.warning(f"Migration skip ai_deal_review.{col}: {e}")

    # Migrations cho lead_captures — RBAC fields
    lc_existing = _table_columns(conn, "lead_captures")
    lc_migrations = [
        ("user_id",              "ALTER TABLE lead_captures ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL"),
        ("tier",                 "ALTER TABLE lead_captures ADD COLUMN tier TEXT"),
        ("urgency",              "ALTER TABLE lead_captures ADD COLUMN urgency TEXT DEFAULT 'standard'"),
        ("guest_name",           "ALTER TABLE lead_captures ADD COLUMN guest_name TEXT"),
        ("guest_email",          "ALTER TABLE lead_captures ADD COLUMN guest_email TEXT"),
        ("notify_email_sent_at", "ALTER TABLE lead_captures ADD COLUMN notify_email_sent_at TEXT"),
    ]
    for col, sql in lc_migrations:
        if col not in lc_existing:
            try:
                conn.execute(sql)
                logger.info(f"Migration: added lead_captures.{col}")
            except Exception as e:
                logger.warning(f"Migration skip lead_captures.{col}: {e}")

    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_user ON lead_captures(user_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_urgency ON lead_captures(urgency, status, created_at DESC)")
    except Exception as e:
        logger.warning(f"Index skip lead_captures: {e}")

    _drop_legacy_feedback(conn)
    _normalize_ai_training_feedback_labels(conn)
    _migrate_legal_verifications(conn)
    _migrate_notification_log(conn)


def _migrate_notification_log(conn: Any) -> None:
    """Add notified_price_ty and ensure the app-level dedup index exists."""
    cols = _table_columns(conn, "notification_log")
    if "notified_price_ty" not in cols:
        try:
            conn.execute("ALTER TABLE notification_log ADD COLUMN notified_price_ty REAL")
            logger.info("Migration: added notification_log.notified_price_ty")
        except Exception as e:
            logger.warning(f"Migration skip notification_log.notified_price_ty: {e}")

    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notif_user_listing "
            "ON notification_log(user_id, listing_id, sent_at DESC)"
        )
    except Exception as e:
        logger.warning(f"Index skip idx_notif_user_listing: {e}")


def _migrate_legal_verifications(conn: Any) -> None:
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS legal_verifications (
                listing_id              INTEGER PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
                status                  TEXT DEFAULT 'unverified',
                trust_tier              TEXT DEFAULT 'candidate_signal',
                confidence_score        INTEGER DEFAULT 0,
                document_image_id       INTEGER REFERENCES listing_images(id) ON DELETE SET NULL,
                thua_so                 TEXT,
                to_ban_do               TEXT,
                legal_area_m2           REAL,
                legal_residential_m2    REAL,
                legal_address           TEXT,
                legal_ward              TEXT,
                legal_road_text         TEXT,
                legal_road_code         TEXT,
                road_match_status       TEXT DEFAULT 'unknown',
                conflict_flags          TEXT,
                evidence_json           TEXT,
                verified_by             TEXT,
                verified_at             TEXT,
                updated_at              TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_legal_verifications_status
            ON legal_verifications(status, trust_tier, confidence_score DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_legal_verifications_doc
            ON legal_verifications(document_image_id)
        """)
    except Exception as e:
        logger.warning(f"Legal verification migration skipped: {e}")


def _table_exists(conn: Any, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=?",
        (name,),
    ).fetchone())


def _table_columns(conn: Any, table: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=?
        """,
        (table,),
    ).fetchall()
    return {r["column_name"] for r in rows}


def _drop_legacy_feedback(conn: Any) -> None:
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


def _normalize_ai_training_feedback_labels(conn: Any) -> None:
    """Normalize legacy positive training labels to the split verdict vocabulary."""
    if not _table_exists(conn, "ai_training_feedback"):
        return
    try:
        conn.execute("""
            UPDATE ai_training_feedback
               SET verdict='cheap_real'
             WHERE verdict IN ('good', 'correct', 'too_low')
        """)
        conn.execute("""
            UPDATE ai_training_feedback
               SET valuation_verdict='cheap_real'
             WHERE valuation_verdict IN ('good', 'correct', 'too_low')
        """)
    except Exception as e:
        logger.warning(f"Training feedback label normalization skipped: {e}")
