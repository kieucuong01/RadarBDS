"""PostgreSQL schema and idempotent migrations for Radar BDS."""
import json
import logging
from typing import Any

from config.property_types import LEGACY_PROPERTY_TYPE_ALIASES, normalize_property_types
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
CREATE INDEX IF NOT EXISTS idx_raw_source_crawled
    ON raw_listings(source, crawled_at DESC);

CREATE TABLE IF NOT EXISTS raw_listing_revisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_listing_id  INTEGER NOT NULL REFERENCES raw_listings(id) ON DELETE CASCADE,
    revision_no     INTEGER NOT NULL,
    source          TEXT NOT NULL,
    source_id       TEXT,
    url             TEXT NOT NULL,
    raw_json        TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    changed_fields  JSONB NOT NULL DEFAULT '[]'::jsonb,
    change_kind     TEXT NOT NULL,
    crawl_run_id    INTEGER,
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(raw_listing_id, revision_no)
);
CREATE INDEX IF NOT EXISTS idx_raw_revisions_listing
    ON raw_listing_revisions(raw_listing_id, revision_no DESC);
CREATE INDEX IF NOT EXISTS idx_raw_revisions_source_url
    ON raw_listing_revisions(source, url, observed_at DESC);


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
    extraction_quality_flags TEXT NOT NULL DEFAULT '',
    measurement_provenance TEXT NOT NULL DEFAULT '{}',
    crawl_run_id        INTEGER,

    -- Outlier flag (thay vì drop)
    is_outlier          INTEGER DEFAULT 0,   -- 1 = nằm ngoài ±2σ của segment
    outlier_direction   TEXT,                -- 'high' | 'low' (low = có thể là deal thật)
    outlier_sigma       REAL,                -- cách mean bao nhiêu sigma

    -- Price tracking
    price_dropped       INTEGER DEFAULT 0,
    price_drop_pct      REAL,
    price_first_ty      REAL,
    price_updated_at    TIMESTAMPTZ,
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
    first_seen_at       TEXT DEFAULT (datetime('now')),
    last_seen_at        TEXT DEFAULT (datetime('now')),
    delisted_at         TEXT,
    is_active           INTEGER DEFAULT 1,
    lifecycle_hours     INTEGER,
    source_status       TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (source_status IN ('unknown','active','inactive','unreachable')),
    last_source_check_at TIMESTAMPTZ,
    source_status_reason TEXT NOT NULL DEFAULT '',

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
CREATE INDEX IF NOT EXISTS idx_listings_source_first_seen
    ON listings(source, (COALESCE(first_seen_at, crawled_at)));


CREATE TABLE IF NOT EXISTS listing_map_locations (
    listing_id BIGINT PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
    lat DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lng DOUBLE PRECISION NOT NULL CHECK (lng BETWEEN -180 AND 180),
    location_precision TEXT NOT NULL
        CHECK (location_precision IN ('exact', 'road', 'landmark', 'nearby', 'ward')),
    location_key TEXT NOT NULL,
    location_label TEXT NOT NULL,
    source TEXT NOT NULL,
    resolver_version TEXT NOT NULL,
    listing_location_signature TEXT NOT NULL,
    accuracy_radius_m DOUBLE PRECISION
        CHECK (accuracy_radius_m IS NULL OR accuracy_radius_m >= 0),
    relation TEXT,
    reference_road TEXT,
    landmark_key TEXT,
    resolution_status TEXT NOT NULL DEFAULT 'resolved'
        CHECK (resolution_status IN ('resolved', 'ambiguous', 'not_found', 'invalid')),
    resolution_reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_listing_map_locations_precision
    ON listing_map_locations(location_precision);
CREATE INDEX IF NOT EXISTS idx_listing_map_locations_point
    ON listing_map_locations(lat, lng);
CREATE INDEX IF NOT EXISTS idx_listing_map_locations_key
    ON listing_map_locations(location_key);

CREATE TABLE IF NOT EXISTS listing_map_location_coverage (
    candidate_key TEXT PRIMARY KEY,
    city TEXT NOT NULL,
    ward TEXT NOT NULL DEFAULT '',
    road_candidate TEXT NOT NULL DEFAULT '',
    landmark_candidate TEXT NOT NULL DEFAULT '',
    relation TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL
        CHECK (status IN ('resolved', 'ambiguous', 'not_found', 'invalid')),
    affected_listing_count INTEGER NOT NULL DEFAULT 0,
    sample_listing_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolution_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_listing_map_coverage_status_count
    ON listing_map_location_coverage(status, affected_listing_count DESC);


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
    error_msg       TEXT NOT NULL DEFAULT '',
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


CREATE TABLE IF NOT EXISTS valuation_model_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name      TEXT NOT NULL,
    model_version   TEXT NOT NULL,
    status          TEXT DEFAULT 'complete',
    config_json     TEXT,
    metrics_json    TEXT,
    total_count     INTEGER DEFAULT 0,
    signal_count    INTEGER DEFAULT 0,
    computed_at     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_valuation_model_runs_latest
    ON valuation_model_runs(model_name, model_version, computed_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS valuation_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_run_id    INTEGER REFERENCES valuation_model_runs(id) ON DELETE SET NULL,
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

CREATE TABLE IF NOT EXISTS valuation_shadow_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_run_id    INTEGER REFERENCES valuation_model_runs(id) ON DELETE CASCADE,
    listing_id      INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    fair_ppm2       REAL,
    actual_ppm2     REAL,
    mos_pct         REAL,
    is_signal       INTEGER DEFAULT 0,
    signal_score    INTEGER DEFAULT NULL,
    road_tier       INTEGER DEFAULT 0,
    segment         TEXT,
    n_segment       INTEGER,
    source_quality_flags TEXT,
    source_quality_recheck INTEGER DEFAULT 0,
    legal_status    TEXT DEFAULT 'unverified',
    trust_tier      TEXT DEFAULT 'candidate_signal',
    trust_score     INTEGER DEFAULT 0,
    legal_flags     TEXT,
    area_ratio      REAL,
    area_adjustment REAL,
    road_model_tier INTEGER DEFAULT 3,
    road_penalty    REAL DEFAULT 1.0,
    fallback_level  TEXT,
    audit_json      TEXT,
    computed_at     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_shadow_valuation_listing_computed
    ON valuation_shadow_results(listing_id, computed_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_shadow_valuation_signal
    ON valuation_shadow_results(is_signal, mos_pct DESC);


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
CREATE INDEX IF NOT EXISTS idx_ai_training_listing_latest
    ON ai_training_feedback(listing_id, created_at DESC, id DESC);
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
CREATE INDEX IF NOT EXISTS idx_ai_deal_review_listing_latest
    ON ai_deal_review(listing_id, created_at DESC, id DESC);
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


CREATE TABLE IF NOT EXISTS user_favorite_listings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    listing_id  INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, listing_id)
);
CREATE INDEX IF NOT EXISTS idx_favorites_user_created
    ON user_favorite_listings(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_favorites_listing
    ON user_favorite_listings(listing_id);


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
CREATE INDEX IF NOT EXISTS idx_audit_created_user
    ON user_audit_log(created_at DESC, user_id);


-- ================================================================
-- RADAR ASK: typed, auditable RAG runtime (legacy assistant retained)
-- ================================================================
CREATE TABLE IF NOT EXISTS radar_ask_sessions (
    id           UUID PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title        TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb
                 CHECK (jsonb_typeof(summary_json) = 'object'),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_radar_ask_sessions_owner_updated
    ON radar_ask_sessions(user_id, updated_at DESC, id DESC);


CREATE TABLE IF NOT EXISTS radar_ask_messages (
    id          UUID PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES radar_ask_sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL CHECK (char_length(content) BETWEEN 1 AND 12000),
    answer_json JSONB CHECK (answer_json IS NULL OR jsonb_typeof(answer_json) = 'object'),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_radar_ask_messages_session_created
    ON radar_ask_messages(session_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_radar_ask_messages_retention
    ON radar_ask_messages(created_at);


CREATE TABLE IF NOT EXISTS radar_ask_runs (
    id                  UUID PRIMARY KEY,
    session_id          UUID NOT NULL REFERENCES radar_ask_sessions(id) ON DELETE CASCADE,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    idempotency_key     TEXT NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 128),
    question            TEXT NOT NULL CHECK (char_length(question) BETWEEN 1 AND 2000),
    requested_depth     TEXT CHECK (requested_depth IS NULL OR requested_depth IN ('fast', 'standard', 'deep')),
    effective_depth     TEXT CHECK (effective_depth IS NULL OR effective_depth IN ('fast', 'standard', 'deep')),
    status              TEXT NOT NULL DEFAULT 'created'
                        CHECK (status IN (
                            'created', 'clarifying', 'queued', 'running',
                            'completed', 'insufficient', 'failed', 'cancelled'
                        )),
    outcome             TEXT CHECK (outcome IS NULL OR outcome IN (
                            'answered', 'insufficient', 'clarification',
                            'provider_failure', 'validation_failure',
                            'database_failure', 'budget_hard_stop', 'cancelled'
                        )),
    route_json          JSONB CHECK (route_json IS NULL OR jsonb_typeof(route_json) = 'object'),
    answer_json         JSONB CHECK (answer_json IS NULL OR jsonb_typeof(answer_json) = 'object'),
    model               TEXT,
    error_code          TEXT,
    retryable           BOOLEAN NOT NULL DEFAULT FALSE,
    available_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    worker_id           TEXT,
    lease_until         TIMESTAMPTZ,
    attempt_count       INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 2),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_radar_ask_runs_session_created
    ON radar_ask_runs(session_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_radar_ask_runs_user
    ON radar_ask_runs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_radar_ask_runs_queue
    ON radar_ask_runs(status, available_at, created_at)
    WHERE status = 'queued';


CREATE TABLE IF NOT EXISTS radar_ask_tool_calls (
    id                  UUID PRIMARY KEY,
    run_id              UUID NOT NULL REFERENCES radar_ask_runs(id) ON DELETE CASCADE,
    tool_call_key       TEXT NOT NULL CHECK (char_length(tool_call_key) BETWEEN 1 AND 128),
    tool_name           TEXT NOT NULL CHECK (char_length(tool_name) BETWEEN 1 AND 128),
    arguments_json      JSONB NOT NULL CHECK (jsonb_typeof(arguments_json) = 'object'),
    result_summary_json JSONB NOT NULL CHECK (jsonb_typeof(result_summary_json) = 'object'),
    status              TEXT NOT NULL CHECK (status IN ('planned', 'running', 'completed', 'failed')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    UNIQUE(run_id, tool_call_key)
);
CREATE INDEX IF NOT EXISTS idx_radar_ask_tool_calls_run
    ON radar_ask_tool_calls(run_id, created_at, id);


CREATE TABLE IF NOT EXISTS radar_ask_evidence (
    id            UUID PRIMARY KEY,
    run_id        UUID NOT NULL REFERENCES radar_ask_runs(id) ON DELETE CASCADE,
    evidence_key  TEXT NOT NULL CHECK (char_length(evidence_key) BETWEEN 1 AND 160),
    evidence_kind TEXT NOT NULL CHECK (char_length(evidence_kind) BETWEEN 1 AND 80),
    source_ref    TEXT NOT NULL CHECK (char_length(source_ref) BETWEEN 1 AND 500),
    payload_json  JSONB NOT NULL CHECK (jsonb_typeof(payload_json) = 'object'),
    min_tier      TEXT NOT NULL CHECK (min_tier IN ('free', 'vip', 'admin')),
    as_of         TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(run_id, evidence_key)
);
CREATE INDEX IF NOT EXISTS idx_radar_ask_evidence_run
    ON radar_ask_evidence(run_id, created_at, id);


-- Usage intentionally does not cascade with runs: deleting chat content must
-- preserve the immutable billing and budget ledger.
CREATE TABLE IF NOT EXISTS radar_ask_usage (
    id                  UUID PRIMARY KEY,
    run_key             UUID NOT NULL UNIQUE,
    user_id             INTEGER REFERENCES users(id) ON DELETE SET NULL,
    tier                TEXT NOT NULL CHECK (tier IN ('free', 'vip', 'admin')),
    model               TEXT,
    depth               TEXT CHECK (depth IS NULL OR depth IN ('fast', 'standard', 'deep')),
    usage_date          DATE NOT NULL,
    usage_month         DATE NOT NULL,
    settlement_status   TEXT NOT NULL CHECK (settlement_status IN ('reserved', 'settled', 'released')),
    question_status     TEXT NOT NULL CHECK (question_status IN ('reserved', 'answered', 'released')),
    reserved_usd        NUMERIC(12, 6) NOT NULL DEFAULT 0 CHECK (reserved_usd >= 0),
    actual_usd          NUMERIC(12, 6) NOT NULL DEFAULT 0 CHECK (actual_usd >= 0),
    prompt_tokens       INTEGER NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
    completion_tokens   INTEGER NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
    cache_hit_tokens    INTEGER NOT NULL DEFAULT 0 CHECK (cache_hit_tokens >= 0),
    cache_miss_tokens   INTEGER NOT NULL DEFAULT 0 CHECK (cache_miss_tokens >= 0),
    outcome             TEXT CHECK (outcome IS NULL OR outcome IN (
                            'answered', 'insufficient', 'clarification',
                            'provider_failure', 'validation_failure',
                            'database_failure', 'budget_hard_stop', 'cancelled'
                        )),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    settled_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_radar_ask_usage_user_day
    ON radar_ask_usage(user_id, usage_date);
CREATE INDEX IF NOT EXISTS idx_radar_ask_usage_month
    ON radar_ask_usage(usage_month, settlement_status);


CREATE TABLE IF NOT EXISTS radar_ask_feedback (
    id         UUID PRIMARY KEY,
    message_id UUID NOT NULL REFERENCES radar_ask_messages(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating     TEXT NOT NULL CHECK (rating IN ('helpful', 'not_helpful')),
    note       TEXT CHECK (note IS NULL OR char_length(note) <= 500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_radar_ask_feedback_message
    ON radar_ask_feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_radar_ask_feedback_user
    ON radar_ask_feedback(user_id, created_at DESC);


CREATE TABLE IF NOT EXISTS assistant_sessions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_token           TEXT NOT NULL UNIQUE,
    user_id                 INTEGER REFERENCES users(id) ON DELETE SET NULL,
    tier                    TEXT,
    investment_profile_json TEXT,
    page_context_json       TEXT,
    last_intent             TEXT,
    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_assistant_sessions_user
    ON assistant_sessions(user_id, updated_at DESC);


CREATE TABLE IF NOT EXISTS assistant_messages (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        INTEGER NOT NULL REFERENCES assistant_sessions(id) ON DELETE CASCADE,
    role              TEXT NOT NULL,
    message           TEXT NOT NULL,
    intent            TEXT,
    entities_json     TEXT,
    tool_name         TEXT,
    tool_payload_json TEXT,
    actions_json      TEXT,
    created_at        TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_assistant_messages_session
    ON assistant_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_assistant_messages_intent
    ON assistant_messages(intent, created_at DESC);


CREATE TABLE IF NOT EXISTS assistant_feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER REFERENCES assistant_messages(id) ON DELETE CASCADE,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    rating     TEXT NOT NULL,
    note       TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_assistant_feedback_message
    ON assistant_feedback(message_id);


CREATE TABLE IF NOT EXISTS assistant_user_profiles (
    user_id          INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    budget_min_ty    REAL,
    budget_max_ty    REAL,
    strategy         TEXT,
    risk_appetite    TEXT,
    preferred_wards  TEXT,
    property_types   TEXT,
    road_tiers       TEXT,
    updated_at       TEXT DEFAULT (datetime('now'))
);


CREATE TABLE IF NOT EXISTS rate_limits (
    key          TEXT PRIMARY KEY,       -- 'listings:user:42' | 'listings:ip:1.2.3.4'
    window_start TEXT,
    count        INTEGER DEFAULT 0
);


CREATE TABLE IF NOT EXISTS listing_reports (
    id                BIGSERIAL PRIMARY KEY,
    listing_id        BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    reason            TEXT NOT NULL CHECK (reason IN (
        'sold_or_unavailable', 'wrong_price_or_area', 'duplicate',
        'wrong_location', 'spam_or_scam', 'other'
    )),
    note              TEXT CHECK (note IS NULL OR char_length(note) <= 500),
    reporter_key_hash TEXT NOT NULL,
    ip_hash           TEXT NOT NULL,
    reporter_user_id  BIGINT REFERENCES users(id) ON DELETE SET NULL,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'reviewed', 'dismissed')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at       TIMESTAMPTZ,
    reviewed_by       BIGINT REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_listing_reports_pending
    ON listing_reports(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_listing_reports_reporter_created
    ON listing_reports(reporter_key_hash, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_listing_reports_ip_created
    ON listing_reports(ip_hash, created_at DESC);

-- Shared state for admin-triggered asynchronous work.
-- The partial unique index prevents two Gunicorn workers from accepting
-- overlapping crawl/maintenance work.
CREATE TABLE IF NOT EXISTS admin_jobs (
    id                 TEXT PRIMARY KEY,
    kind               TEXT NOT NULL CHECK (kind IN (
                           'facebook_crawl', 'crawl_maintenance',
                           'missing_image_backfill', 'source_retry'
                       )),
    status             TEXT NOT NULL CHECK (status IN (
                           'queued', 'running', 'succeeded', 'failed'
                       )),
    stage              TEXT NOT NULL DEFAULT 'queued',
    mode               TEXT NOT NULL DEFAULT '',
    profile_url        TEXT NOT NULL DEFAULT '',
    source             TEXT NOT NULL DEFAULT '',
    broker_name        TEXT NOT NULL DEFAULT '',
    item_limit         INTEGER,
    days               INTEGER,
    download_images    BOOLEAN NOT NULL DEFAULT FALSE,
    maintenance_action TEXT NOT NULL DEFAULT '',
    progress_pct       INTEGER NOT NULL DEFAULT 0
                           CHECK (progress_pct BETWEEN 0 AND 100),
    progress_label     TEXT NOT NULL DEFAULT '',
    stats              JSONB NOT NULL DEFAULT '{}'::jsonb,
    logs               JSONB NOT NULL DEFAULT '[]'::jsonb,
    error              TEXT,
    context            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by         TEXT NOT NULL DEFAULT '',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at         TIMESTAMPTZ,
    heartbeat_at       TIMESTAMPTZ,
    finished_at        TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_admin_jobs_one_active
    ON admin_jobs ((1))
    WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS idx_admin_jobs_recent
    ON admin_jobs(created_at DESC, id DESC);

-- DB-backed configuration for Facebook crawl broker profiles.
CREATE TABLE IF NOT EXISTS facebook_crawl_profiles (
    url              TEXT PRIMARY KEY,
    city             TEXT NOT NULL DEFAULT '',
    broker_name      TEXT NOT NULL DEFAULT '',
    daily_limit      INTEGER NOT NULL DEFAULT 20 CHECK (daily_limit BETWEEN 1 AND 500),
    range_days       INTEGER NOT NULL DEFAULT 7 CHECK (range_days BETWEEN 1 AND 60),
    crawl_every_days INTEGER NOT NULL DEFAULT 1 CHECK (crawl_every_days IN (1, 3, 7)),
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_facebook_crawl_profiles_active
    ON facebook_crawl_profiles(active, city, broker_name);
CREATE INDEX IF NOT EXISTS idx_facebook_crawl_profiles_updated
    ON facebook_crawl_profiles(updated_at DESC);


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
                    try:
                        required_public_tables = (
                            "public_dataset_versions",
                            "signal_card_read_model",
                        )
                        missing_public_tables = [
                            table
                            for table in required_public_tables
                            if not _table_exists(conn, table)
                        ]
                        if missing_public_tables:
                            _migrate_public_read_model(conn)
                        still_missing = [
                            table
                            for table in required_public_tables
                            if not _table_exists(conn, table)
                        ]
                        if still_missing:
                            raise RuntimeError(
                                "required table "
                                + ", ".join(still_missing)
                                + " is missing"
                            )
                    except Exception as migration_exc:
                        raise RuntimeError(
                            "required table "
                            + ", ".join(missing_public_tables)
                            + " is unavailable"
                        ) from migration_exc
                    try:
                        _migrate_listing_map_locations(conn)
                        if not _table_exists(conn, "listing_map_locations"):
                            raise RuntimeError(
                                "required table listing_map_locations is missing"
                            )
                    except Exception as migration_exc:
                        raise RuntimeError(
                            "required table listing_map_locations is unavailable"
                        ) from migration_exc
                    # Preserve the required public read path before attempting
                    # best-effort migrations on legacy tables the runtime role
                    # may not own. A later privilege error aborts the current
                    # PostgreSQL transaction, so without this boundary the new
                    # required tables are silently rolled back as well.
                    conn.commit()
                    try:
                        _migrate_admin_jobs(conn)
                        _migrate_facebook_crawl_profiles(conn)
                        _migrate_listing_reports(conn)
                        _migrate_user_favorite_listings(conn)
                        _migrate_property_type_aliases(conn)
                    except Exception as migration_exc:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        logger.warning(
                            "Limited schema migration skipped after DDL privilege failure: %s",
                            migration_exc,
                        )
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


def _migrate_listing_map_locations(conn: Any) -> None:
    """Create the derived listing-location store and its read indexes."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listing_map_locations (
            listing_id BIGINT PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
            lat DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90),
            lng DOUBLE PRECISION NOT NULL CHECK (lng BETWEEN -180 AND 180),
            location_precision TEXT NOT NULL
                CHECK (location_precision IN ('exact', 'road', 'landmark', 'nearby', 'ward')),
            location_key TEXT NOT NULL,
            location_label TEXT NOT NULL,
            source TEXT NOT NULL,
            resolver_version TEXT NOT NULL,
            listing_location_signature TEXT NOT NULL,
            accuracy_radius_m DOUBLE PRECISION
                CHECK (accuracy_radius_m IS NULL OR accuracy_radius_m >= 0),
            relation TEXT,
            reference_road TEXT,
            landmark_key TEXT,
            resolution_status TEXT NOT NULL DEFAULT 'resolved'
                CHECK (resolution_status IN ('resolved', 'ambiguous', 'not_found', 'invalid')),
            resolution_reason TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    for column_sql in (
        "accuracy_radius_m DOUBLE PRECISION",
        "relation TEXT",
        "reference_road TEXT",
        "landmark_key TEXT",
        "resolution_status TEXT NOT NULL DEFAULT 'resolved'",
        "resolution_reason TEXT",
    ):
        conn.execute(
            f"""
            ALTER TABLE listing_map_locations
            ADD COLUMN IF NOT EXISTS {column_sql}
            """
        )
    conn.execute(
        """
        ALTER TABLE listing_map_locations
        DROP CONSTRAINT IF EXISTS listing_map_locations_location_precision_check
        """
    )
    conn.execute(
        """
        ALTER TABLE listing_map_locations
        ADD CONSTRAINT listing_map_locations_location_precision_check
        CHECK (location_precision IN ('exact', 'road', 'landmark', 'nearby', 'ward'))
        NOT VALID
        """
    )
    conn.execute(
        """
        ALTER TABLE listing_map_locations
        VALIDATE CONSTRAINT listing_map_locations_location_precision_check
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listing_map_location_coverage (
            candidate_key TEXT PRIMARY KEY,
            city TEXT NOT NULL,
            ward TEXT NOT NULL DEFAULT '',
            road_candidate TEXT NOT NULL DEFAULT '',
            landmark_candidate TEXT NOT NULL DEFAULT '',
            relation TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL
                CHECK (status IN ('resolved', 'ambiguous', 'not_found', 'invalid')),
            affected_listing_count INTEGER NOT NULL DEFAULT 0,
            sample_listing_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolution_note TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_listing_map_coverage_status_count
        ON listing_map_location_coverage(status, affected_listing_count DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_listing_map_locations_precision
        ON listing_map_locations(location_precision)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_listing_map_locations_point
        ON listing_map_locations(lat, lng)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_listing_map_locations_key
        ON listing_map_locations(location_key)
        """
    )


def _migrate_listing_reports(conn: Any) -> None:
    """Create the isolated user-report queue and abuse-control indexes."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listing_reports (
            id BIGSERIAL PRIMARY KEY,
            listing_id BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            reason TEXT NOT NULL CHECK (reason IN (
                'sold_or_unavailable', 'wrong_price_or_area', 'duplicate',
                'wrong_location', 'spam_or_scam', 'other'
            )),
            note TEXT CHECK (note IS NULL OR char_length(note) <= 500),
            reporter_key_hash TEXT NOT NULL,
            ip_hash TEXT NOT NULL,
            reporter_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'reviewed', 'dismissed')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reviewed_at TIMESTAMPTZ,
            reviewed_by BIGINT REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_listing_reports_pending "
        "ON listing_reports(status, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_listing_reports_reporter_created "
        "ON listing_reports(reporter_key_hash, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_listing_reports_ip_created "
        "ON listing_reports(ip_hash, created_at DESC)"
    )


def _migrate_admin_jobs(conn: Any) -> None:
    """Create worker-safe persisted state for admin asynchronous jobs."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN (
                'facebook_crawl', 'crawl_maintenance',
                'missing_image_backfill', 'source_retry'
            )),
            status TEXT NOT NULL CHECK (status IN (
                'queued', 'running', 'succeeded', 'failed'
            )),
            stage TEXT NOT NULL DEFAULT 'queued',
            mode TEXT NOT NULL DEFAULT '',
            profile_url TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            broker_name TEXT NOT NULL DEFAULT '',
            item_limit INTEGER,
            days INTEGER,
            download_images BOOLEAN NOT NULL DEFAULT FALSE,
            maintenance_action TEXT NOT NULL DEFAULT '',
            progress_pct INTEGER NOT NULL DEFAULT 0
                CHECK (progress_pct BETWEEN 0 AND 100),
            progress_label TEXT NOT NULL DEFAULT '',
            stats JSONB NOT NULL DEFAULT '{}'::jsonb,
            logs JSONB NOT NULL DEFAULT '[]'::jsonb,
            error TEXT,
            context JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            heartbeat_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_admin_jobs_one_active
        ON admin_jobs ((1))
        WHERE status IN ('queued', 'running')
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_admin_jobs_recent
        ON admin_jobs(created_at DESC, id DESC)
        """
    )


def _migrate_facebook_crawl_profiles(conn: Any) -> None:
    """Create DB-backed configuration for Facebook crawl broker profiles."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS facebook_crawl_profiles (
            url TEXT PRIMARY KEY,
            city TEXT NOT NULL DEFAULT '',
            broker_name TEXT NOT NULL DEFAULT '',
            daily_limit INTEGER NOT NULL DEFAULT 20
                CHECK (daily_limit BETWEEN 1 AND 500),
            range_days INTEGER NOT NULL DEFAULT 7
                CHECK (range_days BETWEEN 1 AND 60),
            crawl_every_days INTEGER NOT NULL DEFAULT 1
                CHECK (crawl_every_days IN (1, 3, 7)),
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_by TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_facebook_crawl_profiles_active
        ON facebook_crawl_profiles(active, city, broker_name)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_facebook_crawl_profiles_updated
        ON facebook_crawl_profiles(updated_at DESC)
        """
    )


def _migrate_raw_listing_revisions(conn: Any) -> None:
    """Create append-only source snapshots for edits to one raw URL."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_listing_revisions (
            id BIGSERIAL PRIMARY KEY,
            raw_listing_id BIGINT NOT NULL
                REFERENCES raw_listings(id) ON DELETE CASCADE,
            revision_no INTEGER NOT NULL,
            source TEXT NOT NULL,
            source_id TEXT,
            url TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            changed_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
            change_kind TEXT NOT NULL,
            crawl_run_id BIGINT,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(raw_listing_id, revision_no)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_revisions_listing
        ON raw_listing_revisions(raw_listing_id, revision_no DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_revisions_source_url
        ON raw_listing_revisions(source, url, observed_at DESC)
        """
    )


def _migrate_guland_publishers(conn: Any) -> None:
    """Create deterministic Guland publisher identity and activity storage."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_publishers (
            id BIGSERIAL PRIMARY KEY,
            source TEXT NOT NULL CHECK (source IN ('guland')),
            publisher_key TEXT NOT NULL,
            identity_type TEXT NOT NULL,
            identity_confidence TEXT NOT NULL
                CHECK (identity_confidence IN ('low','medium','high')),
            display_name TEXT NOT NULL DEFAULT '',
            activity_class TEXT NOT NULL DEFAULT 'unknown'
                CHECK (activity_class IN (
                    'unknown','low_manual','high_activity','automated_repost'
                )),
            activity_reason TEXT NOT NULL DEFAULT '',
            manual_override TEXT NOT NULL DEFAULT ''
                CHECK (manual_override IN (
                    '','allow_manual','hide_high_activity'
                )),
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_classified_at TIMESTAMPTZ,
            metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE(source, publisher_key)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listing_publishers (
            listing_id BIGINT PRIMARY KEY
                REFERENCES listings(id) ON DELETE CASCADE,
            publisher_id BIGINT
                REFERENCES source_publishers(id) ON DELETE SET NULL,
            identity_status TEXT NOT NULL DEFAULT 'unknown'
                CHECK (identity_status IN ('identified','unknown','unreachable')),
            evidence_type TEXT NOT NULL DEFAULT 'unknown',
            identity_confidence TEXT NOT NULL DEFAULT 'low'
                CHECK (identity_confidence IN ('low','medium','high')),
            checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS publisher_activity_daily (
            publisher_id BIGINT NOT NULL
                REFERENCES source_publishers(id) ON DELETE CASCADE,
            activity_date DATE NOT NULL,
            new_listing_count INTEGER NOT NULL DEFAULT 0,
            seen_listing_count INTEGER NOT NULL DEFAULT 0,
            bump_count INTEGER NOT NULL DEFAULT 0,
            near_duplicate_count INTEGER NOT NULL DEFAULT 0,
            repeated_template_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(publisher_id, activity_date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS publisher_listing_observations (
            publisher_id BIGINT NOT NULL
                REFERENCES source_publishers(id) ON DELETE CASCADE,
            listing_id BIGINT NOT NULL
                REFERENCES listings(id) ON DELETE CASCADE,
            activity_date DATE NOT NULL,
            was_new BOOLEAN NOT NULL DEFAULT FALSE,
            was_seen BOOLEAN NOT NULL DEFAULT TRUE,
            was_bumped BOOLEAN NOT NULL DEFAULT FALSE,
            near_duplicate_count INTEGER NOT NULL DEFAULT 0,
            repeated_template BOOLEAN NOT NULL DEFAULT FALSE,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY(publisher_id, listing_id, activity_date)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_publishers_activity
        ON source_publishers(activity_class, manual_override)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_publishers_last_seen
        ON source_publishers(last_seen_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_listing_publishers_publisher
        ON listing_publishers(publisher_id)
        """
    )


def _run_migrations(conn: Any) -> None:
    """Thêm cột mới vào bảng cũ nếu chưa có (idempotent)."""
    _migrate_listing_map_locations(conn)
    _migrate_listing_reports(conn)
    _migrate_admin_jobs(conn)
    _migrate_facebook_crawl_profiles(conn)
    _migrate_raw_listing_revisions(conn)
    _migrate_guland_publishers(conn)
    _migrate_public_read_model(conn)
    conn.execute(
        """
        ALTER TABLE crawl_run_progress
        ADD COLUMN IF NOT EXISTS error_msg TEXT NOT NULL DEFAULT ''
        """
    )
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
        ("price_updated_at",   "ALTER TABLE listings ADD COLUMN price_updated_at TIMESTAMPTZ"),
        (
            "source_status",
            "ALTER TABLE listings ADD COLUMN source_status TEXT NOT NULL "
            "DEFAULT 'unknown' CHECK (source_status IN "
            "('unknown','active','inactive','unreachable'))",
        ),
        (
            "last_source_check_at",
            "ALTER TABLE listings ADD COLUMN last_source_check_at TIMESTAMPTZ",
        ),
        (
            "source_status_reason",
            "ALTER TABLE listings ADD COLUMN source_status_reason TEXT NOT NULL DEFAULT ''",
        ),
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
        (
            "extraction_quality_flags",
            "ALTER TABLE listings ADD COLUMN extraction_quality_flags TEXT NOT NULL DEFAULT ''",
        ),
        (
            "measurement_provenance",
            "ALTER TABLE listings ADD COLUMN measurement_provenance TEXT NOT NULL DEFAULT '{}'",
        ),
        ("crawl_run_id", "ALTER TABLE listings ADD COLUMN crawl_run_id INTEGER"),
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_source_crawled ON raw_listings(source, crawled_at DESC)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_listings_source_first_seen "
            "ON listings(source, (COALESCE(first_seen_at, crawled_at)))"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_listings_source_status_check "
            "ON listings(source, source_status, last_source_check_at, id)"
        )
    except Exception as e:
        logger.warning(f"Index skip listings auxiliary indexes: {e}")

    _migrate_digital_product_order_schema(conn)
    _migrate_public_content_items(conn)

    # Migrations cho valuation_results
    v_existing = _table_columns(conn, "valuation_results")
    v_migrations = [
        (
            "model_run_id",
            "ALTER TABLE valuation_results ADD COLUMN model_run_id INTEGER "
            "REFERENCES valuation_model_runs(id) ON DELETE SET NULL",
        ),
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

    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_valuation_model_run "
            "ON valuation_results(model_run_id)"
        )
    except Exception as e:
        logger.warning(f"Index skip idx_valuation_model_run: {e}")

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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_training_listing_latest "
            "ON ai_training_feedback(listing_id, created_at DESC, id DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_deal_review_listing_latest "
            "ON ai_deal_review(listing_id, created_at DESC, id DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_created_user "
            "ON user_audit_log(created_at DESC, user_id)"
        )
    except Exception as e:
        logger.warning(f"Index skip admin performance indexes: {e}")

    _drop_legacy_feedback(conn)
    _normalize_ai_training_feedback_labels(conn)
    _migrate_legal_verifications(conn)
    _migrate_notification_log(conn)
    _migrate_user_favorite_listings(conn)
    _migrate_property_type_aliases(conn)


def _migrate_public_read_model(conn: Any) -> None:
    """Create durable public dataset counters used by hot read paths."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public_dataset_versions (
            dataset_name TEXT PRIMARY KEY,
            version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.execute(
        """
        INSERT INTO public_dataset_versions(dataset_name, version)
        VALUES ('signals', 0), ('listings', 0), ('market', 0)
        ON CONFLICT (dataset_name) DO NOTHING
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS signal_card_read_model (
            listing_id BIGINT PRIMARY KEY
                REFERENCES listings(id) ON DELETE CASCADE,
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            source_status TEXT NOT NULL DEFAULT 'unknown',
            url TEXT NOT NULL DEFAULT '',
            ward TEXT,
            property_type TEXT,
            area_m2 DOUBLE PRECISION,
            frontage_m DOUBLE PRECISION,
            depth_m DOUBLE PRECISION,
            price_ty DOUBLE PRECISION,
            listing_price_per_m2 DOUBLE PRECISION,
            actual_ppm2 DOUBLE PRECISION,
            fair_ppm2 DOUBLE PRECISION,
            fair_ppm2_old DOUBLE PRECISION,
            fair_ppm2_new DOUBLE PRECISION,
            mos_pct DOUBLE PRECISION,
            mos_pct_old DOUBLE PRECISION,
            mos_pct_new DOUBLE PRECISION,
            signal_score INTEGER NOT NULL DEFAULT 0,
            is_actionable BOOLEAN NOT NULL DEFAULT FALSE,
            listing_is_signal BOOLEAN NOT NULL DEFAULT FALSE,
            is_hot BOOLEAN NOT NULL DEFAULT FALSE,
            possibly_duplicate BOOLEAN NOT NULL DEFAULT FALSE,
            price_dropped BOOLEAN NOT NULL DEFAULT FALSE,
            price_drop_pct DOUBLE PRECISION,
            price_first_ty DOUBLE PRECISION,
            suspicious_bait BOOLEAN NOT NULL DEFAULT FALSE,
            duplicate_of_id BIGINT,
            activity_at TIMESTAMPTZ,
            crawled_at TEXT,
            posted_at TEXT,
            first_seen_at TEXT,
            price_updated_at TEXT,
            road_name TEXT,
            road_type TEXT,
            road_width_m DOUBLE PRECISION,
            road_tier INTEGER NOT NULL DEFAULT 0,
            tho_cu_m2 DOUBLE PRECISION,
            tho_cu_ratio DOUBLE PRECISION,
            has_so BOOLEAN,
            trust_tier TEXT NOT NULL DEFAULT 'candidate_signal',
            trust_score INTEGER NOT NULL DEFAULT 0,
            legal_status TEXT NOT NULL DEFAULT 'unverified',
            legal_flags TEXT NOT NULL DEFAULT '',
            source_quality_flags TEXT NOT NULL DEFAULT '',
            source_quality_recheck BOOLEAN NOT NULL DEFAULT FALSE,
            has_legal_doc_image BOOLEAN NOT NULL DEFAULT FALSE,
            publisher_visible_public BOOLEAN NOT NULL DEFAULT TRUE,
            publisher_rank SMALLINT NOT NULL DEFAULT 1,
            primary_image_id BIGINT
                REFERENCES listing_images(id) ON DELETE SET NULL,
            image_count INTEGER NOT NULL DEFAULT 0,
            refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.execute(
        """
        ALTER TABLE signal_card_read_model
        ADD COLUMN IF NOT EXISTS listing_price_per_m2 DOUBLE PRECISION
        """
    )
    conn.execute(
        """
        ALTER TABLE signal_card_read_model
        ADD COLUMN IF NOT EXISTS listing_is_signal
            BOOLEAN NOT NULL DEFAULT FALSE
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_signal_card_public_newest
        ON signal_card_read_model(
            publisher_rank, activity_at DESC, listing_id DESC
        )
        WHERE is_actionable AND publisher_visible_public
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_signal_card_public_filter
        ON signal_card_read_model(
            source, ward, property_type, publisher_rank,
            activity_at DESC, listing_id DESC
        )
        WHERE is_actionable AND publisher_visible_public
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_signal_card_public_mos
        ON signal_card_read_model(mos_pct DESC, listing_id DESC)
        WHERE is_actionable AND publisher_visible_public
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_signal_card_all_public_newest
        ON signal_card_read_model(
            publisher_rank, activity_at DESC, listing_id DESC
        )
        WHERE publisher_visible_public AND NOT possibly_duplicate
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_signal_card_all_public_filter
        ON signal_card_read_model(
            source, ward, property_type, publisher_rank,
            activity_at DESC, listing_id DESC
        )
        WHERE publisher_visible_public
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_signal_card_all_public_drop
        ON signal_card_read_model(
            publisher_rank, activity_at DESC, listing_id DESC
        )
        WHERE publisher_visible_public AND price_dropped
        """
    )
    for table in (
        "signal_card_read_model",
        "listings",
        "valuation_results",
        "valuation_shadow_results",
        "listing_images",
        "listing_publishers",
        "source_publishers",
    ):
        conn.execute(
            f"""
            DO $$
            BEGIN
                ALTER TABLE {table} SET (
                    autovacuum_analyze_scale_factor = 0.02,
                    autovacuum_analyze_threshold = 100
                );
            EXCEPTION
                WHEN insufficient_privilege THEN
                    RAISE NOTICE 'Skipping optional analyze tuning for {table}';
            END $$;
            """
        )


def _migrate_public_content_items(conn: Any) -> None:
    """Create the runtime-owned public content store idempotently."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public_content_items (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            item_type TEXT NOT NULL
                CHECK (item_type IN ('hot_topic', 'legal_document')),
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'published')),
            status_reason TEXT NOT NULL DEFAULT '',
            slug TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            source_key TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_url TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            topic TEXT NOT NULL DEFAULT '',
            published_at TIMESTAMPTZ,
            fingerprint TEXT NOT NULL,
            document_number TEXT NOT NULL DEFAULT '',
            issuing_authority TEXT NOT NULL DEFAULT '',
            document_type TEXT NOT NULL DEFAULT '',
            document_scope TEXT NOT NULL DEFAULT '',
            pdf_source_url TEXT NOT NULL DEFAULT '',
            pdf_object_key TEXT NOT NULL DEFAULT '',
            pdf_sha256 TEXT NOT NULL DEFAULT '',
            pdf_size_bytes BIGINT,
            pdf_content_type TEXT NOT NULL DEFAULT '',
            pdf_uploaded_at TIMESTAMPTZ,
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT public_content_published_date_required
                CHECK (status <> 'published' OR published_at IS NOT NULL),
            UNIQUE (slug),
            UNIQUE (canonical_url),
            UNIQUE (fingerprint),
            CONSTRAINT public_content_official_pdf_required
                CHECK (
                    status <> 'published'
                    OR item_type <> 'legal_document'
                    OR (
                        document_number <> ''
                        AND issuing_authority <> ''
                        AND document_type <> ''
                        AND pdf_object_key <> ''
                        AND pdf_sha256 ~ '^[0-9a-f]{64}$'
                        AND pdf_size_bytes > 0
                        AND pdf_content_type = 'application/pdf'
                        AND pdf_uploaded_at IS NOT NULL
                    )
                )
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_public_content_status_date
        ON public_content_items(item_type, status, published_at DESC, id DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_public_content_source_date
        ON public_content_items(source_key, published_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_public_content_legal_filters
        ON public_content_items(
            issuing_authority,
            document_type,
            published_at DESC
        )
        WHERE item_type = 'legal_document' AND status = 'published'
        """
    )


def _migrate_digital_product_order_schema(conn: Any) -> None:
    """Build or repair commerce tables before adding dependent objects."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS digital_product_orders (id BIGINT)"
    )
    order_columns = (
        "id BIGINT",
        "public_id TEXT",
        "product_slug TEXT",
        "product_version TEXT",
        "expected_amount INTEGER",
        "currency TEXT",
        "payos_order_code BIGINT",
        "payment_link_id TEXT",
        "checkout_url TEXT",
        "qr_code TEXT",
        "status TEXT",
        "recovery_token_hash TEXT",
        "paid_amount INTEGER",
        "payment_reference TEXT",
        "status_reason TEXT",
        "created_at TIMESTAMPTZ",
        "updated_at TIMESTAMPTZ",
        "payment_expires_at TIMESTAMPTZ",
        "paid_at TIMESTAMPTZ",
        "download_expires_at TIMESTAMPTZ",
        "download_count INTEGER",
        "last_download_at TIMESTAMPTZ",
        "last_checked_at TIMESTAMPTZ",
    )
    for column_sql in order_columns:
        conn.execute(
            "ALTER TABLE digital_product_orders "
            f"ADD COLUMN IF NOT EXISTS {column_sql}"
        )

    _repair_digital_product_identity(conn, "digital_product_orders")
    conn.execute("""
        UPDATE digital_product_orders
           SET public_id = CASE
                   WHEN NULLIF(BTRIM(public_id), '') IS NULL
                   THEN '__migration_review_order_' || id::text
                   ELSE BTRIM(public_id)
               END,
               product_slug = COALESCE(NULLIF(BTRIM(product_slug), ''), 'migration-review'),
               product_version = COALESCE(NULLIF(BTRIM(product_version), ''), '0'),
               expected_amount = CASE
                   WHEN expected_amount IS NULL OR expected_amount <= 0 THEN 1
                   ELSE expected_amount
               END,
               currency = 'VND',
               payos_order_code = COALESCE(payos_order_code, id),
               status = CASE
                   WHEN NULLIF(BTRIM(public_id), '') IS NULL
                     OR NULLIF(BTRIM(product_slug), '') IS NULL
                     OR NULLIF(BTRIM(product_version), '') IS NULL
                     OR expected_amount IS NULL
                     OR expected_amount <= 0
                     OR currency IS DISTINCT FROM 'VND'
                     OR payos_order_code IS NULL
                     OR payment_expires_at IS NULL
                   THEN 'payment_review'
                   WHEN status IN ('pending', 'paid', 'expired', 'cancelled', 'payment_review')
                   THEN status
                   ELSE 'payment_review'
               END,
               created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
               updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP),
               payment_expires_at = COALESCE(payment_expires_at, CURRENT_TIMESTAMP),
               download_count = GREATEST(COALESCE(download_count, 0), 0)
    """)
    for column_name, default_sql in (
        ("currency", "'VND'"),
        ("status", "'pending'"),
        ("created_at", "CURRENT_TIMESTAMP"),
        ("updated_at", "CURRENT_TIMESTAMP"),
        ("download_count", "0"),
    ):
        conn.execute(
            "ALTER TABLE digital_product_orders "
            f"ALTER COLUMN {column_name} SET DEFAULT {default_sql}"
        )
    conn.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT public_id
                  FROM digital_product_orders
                 GROUP BY public_id
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'digital_product_orders migration blocked: duplicate public_id';
            END IF;
            IF EXISTS (
                SELECT payos_order_code
                  FROM digital_product_orders
                 GROUP BY payos_order_code
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'digital_product_orders migration blocked: duplicate payos_order_code';
            END IF;
        END $$;
    """)
    for column_name in (
        "public_id",
        "product_slug",
        "product_version",
        "expected_amount",
        "currency",
        "payos_order_code",
        "status",
        "created_at",
        "updated_at",
        "payment_expires_at",
        "download_count",
    ):
        conn.execute(
            "ALTER TABLE digital_product_orders "
            f"ALTER COLUMN {column_name} SET NOT NULL"
        )

    _add_commerce_constraint(
        conn,
        "digital_product_orders",
        "digital_product_orders_pkey",
        "PRIMARY KEY (id)",
        primary_key=True,
    )
    for constraint_name, definition in (
        ("digital_product_orders_public_id_key", "UNIQUE (public_id)"),
        (
            "digital_product_orders_expected_amount_check",
            "CHECK (expected_amount > 0)",
        ),
        (
            "digital_product_orders_currency_check",
            "CHECK (currency = 'VND')",
        ),
        (
            "digital_product_orders_payos_order_code_key",
            "UNIQUE (payos_order_code)",
        ),
        (
            "digital_product_orders_payment_link_id_key",
            "UNIQUE (payment_link_id)",
        ),
        (
            "digital_product_orders_status_check",
            "CHECK (status IN ('pending', 'paid', 'expired', 'cancelled', 'payment_review'))",
        ),
        (
            "digital_product_orders_download_count_check",
            "CHECK (download_count >= 0)",
        ),
    ):
        _add_commerce_constraint(
            conn,
            "digital_product_orders",
            constraint_name,
            definition,
        )

    # The referenced order PK is repaired before the event table can exist.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS digital_product_order_events (id BIGINT)"
    )
    event_columns = (
        "id BIGINT",
        "order_id BIGINT",
        "event_type TEXT",
        "external_reference TEXT",
        "payload_hash TEXT",
        "created_at TIMESTAMPTZ",
    )
    for column_sql in event_columns:
        conn.execute(
            "ALTER TABLE digital_product_order_events "
            f"ADD COLUMN IF NOT EXISTS {column_sql}"
        )

    _repair_digital_product_identity(conn, "digital_product_order_events")
    conn.execute("""
        UPDATE digital_product_order_events
           SET event_type = COALESCE(NULLIF(BTRIM(event_type), ''), 'migration_review'),
               external_reference = COALESCE(external_reference, ''),
               payload_hash = COALESCE(payload_hash, ''),
               created_at = COALESCE(created_at, CURRENT_TIMESTAMP)
    """)
    for column_name, default_sql in (
        ("external_reference", "''"),
        ("payload_hash", "''"),
        ("created_at", "CURRENT_TIMESTAMP"),
    ):
        conn.execute(
            "ALTER TABLE digital_product_order_events "
            f"ALTER COLUMN {column_name} SET DEFAULT {default_sql}"
        )
    conn.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM digital_product_order_events
                 WHERE order_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'digital_product_order_events migration blocked: order_id is unknown';
            END IF;
            IF EXISTS (
                SELECT 1
                  FROM digital_product_order_events event
                  LEFT JOIN digital_product_orders orders
                    ON orders.id = event.order_id
                 WHERE orders.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'digital_product_order_events migration blocked: orphan order_id';
            END IF;
        END $$;
    """)
    for column_name in (
        "order_id",
        "event_type",
        "external_reference",
        "payload_hash",
        "created_at",
    ):
        conn.execute(
            "ALTER TABLE digital_product_order_events "
            f"ALTER COLUMN {column_name} SET NOT NULL"
        )

    _add_commerce_constraint(
        conn,
        "digital_product_order_events",
        "digital_product_order_events_pkey",
        "PRIMARY KEY (id)",
        primary_key=True,
    )
    _add_commerce_constraint(
        conn,
        "digital_product_order_events",
        "digital_product_order_events_order_id_fkey",
        "FOREIGN KEY (order_id) REFERENCES digital_product_orders(id)",
    )
    _add_commerce_constraint(
        conn,
        "digital_product_order_events",
        "digital_product_order_events_order_event_reference_key",
        "UNIQUE (order_id, event_type, external_reference)",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_digital_product_orders_status_expiry "
        "ON digital_product_orders(status, payment_expires_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_digital_product_order_events_order_id "
        "ON digital_product_order_events(order_id)"
    )


def _repair_digital_product_identity(conn: Any, table_name: str) -> None:
    conn.execute(
        f"""
        DO $$
        DECLARE
            id_data_type TEXT;
            identity_state TEXT;
            identity_generation_state TEXT;
            default_expr TEXT;
            sequence_name TEXT;
            max_id BIGINT;
            missing_count BIGINT;
        BEGIN
            SELECT data_type, is_identity, identity_generation, column_default
              INTO id_data_type, identity_state, identity_generation_state, default_expr
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = '{table_name}'
               AND column_name = 'id';

            IF id_data_type NOT IN ('smallint', 'integer', 'bigint') THEN
                RAISE EXCEPTION
                    '{table_name} migration blocked: id must be an integer type';
            END IF;
            IF id_data_type <> 'bigint' THEN
                ALTER TABLE {table_name}
                    ALTER COLUMN id TYPE BIGINT USING id::bigint;
            END IF;
            IF EXISTS (
                SELECT id
                  FROM {table_name}
                 WHERE id IS NOT NULL
                 GROUP BY id
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    '{table_name} migration blocked: duplicate id';
            END IF;

            SELECT GREATEST(COALESCE(MAX(id), 0), 0),
                   COUNT(*) FILTER (WHERE id IS NULL)
              INTO max_id, missing_count
              FROM {table_name};
            IF max_id > 9223372036854775807 - missing_count THEN
                RAISE EXCEPTION
                    '{table_name} migration blocked: id range exhausted';
            END IF;
            WITH numbered AS (
                SELECT ctid, ROW_NUMBER() OVER (ORDER BY ctid) AS offset
                  FROM {table_name}
                 WHERE id IS NULL
            )
            UPDATE {table_name} AS target
               SET id = max_id + numbered.offset
              FROM numbered
             WHERE target.ctid = numbered.ctid;

            ALTER TABLE {table_name}
                ALTER COLUMN id SET NOT NULL;

            IF identity_state <> 'YES' THEN
                IF default_expr IS NOT NULL THEN
                    RAISE EXCEPTION
                        '{table_name} migration blocked: non-identity id default requires manual review';
                END IF;
                ALTER TABLE {table_name}
                    ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY;
            ELSIF identity_generation_state <> 'BY DEFAULT' THEN
                ALTER TABLE {table_name}
                    ALTER COLUMN id SET GENERATED BY DEFAULT;
            END IF;

            SELECT pg_get_serial_sequence('public.{table_name}', 'id')
              INTO sequence_name;
            IF sequence_name IS NULL THEN
                RAISE EXCEPTION
                    '{table_name} migration blocked: identity sequence is unavailable';
            END IF;
            SELECT GREATEST(COALESCE(MAX(id), 0), 0)
              INTO max_id
              FROM {table_name};
            PERFORM setval(
                sequence_name::regclass,
                GREATEST(max_id, 1),
                max_id > 0
            );
        END $$;
        """
    )


def _add_commerce_constraint(
    conn: Any,
    table_name: str,
    constraint_name: str,
    definition: str,
    *,
    primary_key: bool = False,
) -> None:
    if primary_key:
        conn.execute(
            f"""
            DO $$
            DECLARE
                id_attribute SMALLINT;
            BEGIN
                SELECT attnum
                  INTO id_attribute
                  FROM pg_attribute
                 WHERE attrelid = 'public.{table_name}'::regclass
                   AND attname = 'id'
                   AND attnum > 0
                   AND NOT attisdropped;
                IF id_attribute IS NULL THEN
                    RAISE EXCEPTION
                        '{table_name} migration blocked: id column is unavailable';
                END IF;
                IF EXISTS (
                    SELECT 1
                      FROM pg_constraint
                     WHERE contype = 'p'
                       AND conrelid = 'public.{table_name}'::regclass
                ) AND NOT EXISTS (
                    SELECT 1
                      FROM pg_constraint
                     WHERE contype = 'p'
                       AND conrelid = 'public.{table_name}'::regclass
                       AND array_length(conkey, 1) = 1
                       AND conkey[1] = id_attribute
                ) THEN
                    RAISE EXCEPTION
                        '{table_name} migration blocked: primary key must be id';
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                      FROM pg_constraint
                     WHERE contype = 'p'
                       AND conrelid = 'public.{table_name}'::regclass
                       AND array_length(conkey, 1) = 1
                       AND conkey[1] = id_attribute
                ) THEN
                    ALTER TABLE {table_name}
                    ADD CONSTRAINT {constraint_name} {definition};
                END IF;
            END $$;
            """
        )
        return

    existence_check = (
        f"conname = '{constraint_name}'"
    )
    conn.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                  FROM pg_constraint
                 WHERE {existence_check}
                   AND conrelid = 'public.{table_name}'::regclass
            ) THEN
                ALTER TABLE {table_name}
                ADD CONSTRAINT {constraint_name} {definition};
            END IF;
        END $$;
        """
    )


def _normalize_json_type_array(raw: str | None) -> str | None:
    if not raw:
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(parsed, list):
        return raw
    return json.dumps(normalize_property_types(parsed), ensure_ascii=False)


def _migrate_json_type_array_column(conn: Any, table: str, column: str, key_column: str = "id") -> None:
    columns = _table_columns(conn, table) if _table_exists(conn, table) else set()
    if column not in columns or key_column not in columns:
        return
    try:
        rows = conn.execute(
            f"SELECT {key_column}, {column} FROM {table} "
            f"WHERE {column} LIKE '%dat_vuon%' OR {column} LIKE '%dat_lon%'"
        ).fetchall()
        for row in rows:
            normalized = _normalize_json_type_array(row[column])
            if normalized != row[column]:
                conn.execute(
                    f"UPDATE {table} SET {column}=? WHERE {key_column}=?",
                    (normalized, row[key_column]),
                )
    except Exception as e:
        logger.warning(f"Property type JSON alias migration skipped for {table}.{column}: {e}")


def _migrate_property_type_aliases(conn: Any) -> None:
    """Collapse legacy garden/large-land buckets into the active land type."""
    aliases = tuple(LEGACY_PROPERTY_TYPE_ALIASES)
    if not aliases:
        return
    placeholders = ",".join("?" for _ in aliases)

    if _table_exists(conn, "listings") and "property_type" in _table_columns(conn, "listings"):
        try:
            conn.execute(
                f"UPDATE listings SET property_type='dat_nen' WHERE property_type IN ({placeholders})",
                aliases,
            )
        except Exception as e:
            logger.warning(f"Listing property type alias migration skipped: {e}")

    if _table_exists(conn, "market_weekly") and "property_type" in _table_columns(conn, "market_weekly"):
        try:
            # Derived table with a unique key by type; remove stale buckets and recompute trends.
            conn.execute(
                f"DELETE FROM market_weekly WHERE property_type IN ({placeholders})",
                aliases,
            )
        except Exception as e:
            logger.warning(f"Market weekly property type alias cleanup skipped: {e}")

    _migrate_json_type_array_column(conn, "user_watchlists", "prop_types")
    _migrate_json_type_array_column(conn, "assistant_user_profiles", "property_types", "user_id")

    for table in ("valuation_results", "valuation_shadow_results"):
        if not _table_exists(conn, table) or "segment" not in _table_columns(conn, table):
            continue
        try:
            conn.execute(
                f"""
                UPDATE {table}
                   SET segment=REPLACE(REPLACE(segment, 'dat_vuon', 'dat_nen'), 'dat_lon', 'dat_nen')
                 WHERE segment LIKE '%dat_vuon%' OR segment LIKE '%dat_lon%'
                """
            )
        except Exception as e:
            logger.warning(f"Valuation segment alias cleanup skipped for {table}: {e}")


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


def _migrate_user_favorite_listings(conn: Any) -> None:
    """Create the saved-listings table even when old core tables are not owned by this role."""
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_favorite_listings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                listing_id  INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                created_at  TEXT DEFAULT (datetime('now')),
                UNIQUE(user_id, listing_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_favorites_user_created
            ON user_favorite_listings(user_id, created_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_favorites_listing
            ON user_favorite_listings(listing_id)
        """)
    except Exception as e:
        logger.warning(f"Favorite listings migration skipped: {e}")


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
