"""
SQLite Database Layer — MVP
Nguyên tắc: RAW → PROCESSED separation
- raw_listings: lưu toàn bộ tin gốc, không bao giờ sửa/xóa
- listings: normalized, reprocessable bất cứ lúc nào từ raw_listings
"""
import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

def _resolve_db_path() -> Path:
    """
    Priority: env RADAR_DB_PATH → test writable → dùng.
    Fallback: thử các path theo thứ tự cho đến khi writable.

    ⚠️  Windows NTFS mount không hỗ trợ SQLite WAL → KHÔNG đặt DB_PATH
        trỏ vào mount. Dùng export-raw / import-raw-backup để persist data.
    """
    import os, tempfile
    env = os.environ.get("RADAR_DB_PATH", "").strip()
    if env:
        p = Path(env)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            test = p.parent / ".write_test"
            test.touch(); test.unlink()
            logger.info(f"DB path (env): {p}")
            return p
        except Exception as e:
            logger.warning(f"RADAR_DB_PATH không dùng được ({e}), fallback auto")

    # Auto-detect: thử từng path, dùng cái nào writable
    candidates = [
        Path.home() / "radar_bds.db",          # ~/radar_bds.db (session home)
        Path(tempfile.gettempdir()) / f"radar_bds_{os.getpid()}.db",  # cross-platform
        Path(tempfile.gettempdir()) / "radar_bds.db",
    ]
    for p in candidates:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            # Kiểm tra file có writable không (kể cả khi đã tồn tại)
            if p.exists():
                import stat
                mode = p.stat().st_mode
                if not (mode & stat.S_IWUSR):
                    continue  # file tồn tại nhưng read-only → thử path khác
            test = p.parent / ".write_test"
            test.touch(); test.unlink()
            logger.info(f"DB path (auto): {p}")
            return p
        except Exception:
            continue

    # Last resort
    p = Path(tempfile.mktemp(suffix=".db", prefix="radar_bds_"))
    logger.warning(f"DB path (last resort): {p}")
    return p


DB_PATH = _resolve_db_path()

_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """
    Per-thread SQLite connection.
    HARDENING: bỏ check_same_thread=False — mỗi thread có connection riêng,
    tránh race condition trên cùng 1 transaction từ nhiều worker.
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")   # 5s retry on lock
        _local.conn = conn
    return _local.conn

@contextmanager
def get_conn():
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_schema():
    """Tạo bảng nếu chưa có, hỗ trợ migration thêm cột."""
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        
        # Migration: Thêm cột llm_verified, llm_notes nếu chưa có
        try:
            conn.execute("ALTER TABLE listings ADD COLUMN llm_verified INTEGER DEFAULT 0")
            conn.execute("ALTER TABLE listings ADD COLUMN llm_notes TEXT")
            logger.info("Migrated: added LLM columns to listings table")
        except sqlite3.OperationalError:
            pass # Cột đã tồn tại


def close_all():
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None


# ─── Schema ──────────────────────────────────────────────────────────────────

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
-- Signal Outcome Tracking — human-in-the-loop feedback
-- User review từng signal trên web /review → verdict + reason text
-- Hybrid learning: numeric prior (per-segment reject rate) + LLM rules
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS signal_feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id      INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    verdict         TEXT NOT NULL,            -- 'good' | 'bad' | 'maybe' | 'sold' | 'spam'
    reason_text     TEXT,                     -- free-text user nhập
    snapshot_mos    REAL,                     -- v.mos_pct tại thời điểm review
    snapshot_score  INTEGER,                  -- v.signal_score tại thời điểm review
    snapshot_segment TEXT,                    -- ward|property_type|road_tier để aggregate prior
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_feedback_listing  ON signal_feedback(listing_id);
CREATE INDEX IF NOT EXISTS idx_feedback_verdict  ON signal_feedback(verdict, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_segment  ON signal_feedback(snapshot_segment);

CREATE TABLE IF NOT EXISTS feedback_rules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_text       TEXT NOT NULL,            -- human-readable: "Loại signal nếu ward=X và area>Y"
    rule_sql        TEXT,                     -- SQL WHERE clause (NULL nếu chỉ là human note)
    confidence      REAL,                     -- 0.0–1.0 do Groq estimate
    sample_size     INTEGER,                  -- # feedback hỗ trợ rule
    enabled         INTEGER DEFAULT 1,        -- toggle on/off để A/B test
    created_at      TEXT DEFAULT (datetime('now')),
    last_used_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_feedback_rules_enabled ON feedback_rules(enabled);
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


# ─── RAW layer ────────────────────────────────────────────────────────────────

def get_raw_urls(source: str) -> set:
    """Lấy set URL đã có trong raw_listings — dùng để skip khi crawl lại."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT url FROM raw_listings WHERE source = ?", (source,)
        ).fetchall()
    return {r[0] for r in rows}


def insert_raw(source: str, source_id: Optional[str], url: str,
               raw_data: dict, crawl_run_id: Optional[int] = None) -> Optional[int]:
    """
    Lưu raw record. UNIQUE(source, url) → bỏ qua nếu đã có.
    Trả về raw_id hoặc None nếu đã tồn tại.
    """
    with get_conn() as conn:
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO raw_listings
                   (source, source_id, url, raw_json, crawl_run_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (source, source_id, url,
                 json.dumps(raw_data, ensure_ascii=False), crawl_run_id)
            )
            return cur.lastrowid if cur.lastrowid else None
        except Exception as e:
            logger.error(f"insert_raw error [{url}]: {e}")
            return None


def get_raw_for_reprocess(source: Optional[str] = None,
                          since: Optional[str] = None,
                          incremental: bool = False) -> list:
    """
    Lấy raw records để reprocess.
    source: filter theo nguồn. since: ISO date string 'YYYY-MM-DD'.
    incremental: Nếu True, chỉ lấy các raw_listings chưa từng được normalize (raw_id chưa có trong bảng listings).
    """
    if incremental:
        query = """
            SELECT r.id, r.source, r.source_id, r.url, r.raw_json, r.crawled_at 
            FROM raw_listings r
            LEFT JOIN listings l ON r.id = l.raw_id
            WHERE l.raw_id IS NULL
        """
    else:
        query = "SELECT id, source, source_id, url, raw_json, crawled_at FROM raw_listings WHERE 1=1"
        
    params = []
    if source:
        query += " AND r.source = ?" if incremental else " AND source = ?"
        params.append(source)
    if since:
        query += " AND r.crawled_at >= ?" if incremental else " AND crawled_at >= ?"
        params.append(since)
    query += " ORDER BY r.crawled_at ASC" if incremental else " ORDER BY crawled_at ASC"

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


# ─── PROCESSED layer ──────────────────────────────────────────────────────────

def upsert_listing(rec: dict, crawl_run_id: Optional[int] = None) -> tuple:
    """
    Insert or update listing từ normalized record.
    Returns (listing_id, is_new).
    """
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, price_ty, price_first_ty, price_dropped FROM listings WHERE url = ?",
            (rec["url"],)
        ).fetchone()

        now = datetime.now().isoformat()

        if existing is None:
            # Logic giá trị: set first_seen_at=last_seen_at=now cho lifecycle tracking
            cur = conn.execute("""
                INSERT INTO listings (
                    raw_id, source, source_id, url, title, description,
                    area, ward, raw_area_text, price_ty, price_per_m2, area_m2,
                    property_type, tx_type, frontage_m, depth_m, road_width_m,
                    road_type, road_tier, has_so, is_hot, contact_phone, seller_name,
                    price_first_ty, crawled_at, updated_at,
                    first_seen_at, last_seen_at, is_active, posted_at
                ) VALUES (
                    :raw_id, :source, :source_id, :url, :title, :description,
                    :area, :ward, :raw_area_text, :price_ty, :price_per_m2, :area_m2,
                    :property_type, :tx_type, :frontage_m, :depth_m, :road_width_m,
                    :road_type, :road_tier, :has_so, :is_hot, :contact_phone, :seller_name,
                    :price_ty, :crawled_at, :updated_at,
                    :crawled_at, :crawled_at, 1, :posted_at
                )
            """, {
                "raw_id":       rec.get("raw_id"),
                "source":       rec["source"],
                "source_id":    rec.get("source_id", ""),
                "url":          rec["url"],
                "title":        rec.get("title", ""),
                "description":  rec.get("description", ""),
                "area":         rec.get("area", ""),
                "ward":         rec.get("ward") or rec.get("area") or None,
                "raw_area_text": rec.get("raw_area_text", ""),
                "price_ty":     rec.get("price_ty"),
                "price_per_m2": rec.get("price_per_m2"),
                "area_m2":      rec.get("area_m2"),
                "property_type": rec.get("property_type", "khac"),
                "tx_type":      rec.get("tx_type", "ban"),
                "frontage_m":   rec.get("frontage_m"),
                "depth_m":      rec.get("depth_m"),
                "road_width_m": rec.get("road_width_m"),
                "road_type":    rec.get("road_type", "unknown"),
                "road_tier":    int(rec.get("road_tier", 0)),
                "has_so":       int(rec.get("has_so", False)),
                "is_hot":       int(rec.get("is_hot", False)),
                "contact_phone": rec.get("contact_phone"),
                "seller_name":  rec.get("seller_name"),
                "crawled_at":   now,
                "updated_at":   now,
                "posted_at":    rec.get("post_date"),
            })
            listing_id = cur.lastrowid

            if rec.get("price_ty") or rec.get("price_per_m2"):
                conn.execute(
                    "INSERT INTO price_history (listing_id, price_ty, price_per_m2, crawl_run_id) VALUES (?,?,?,?)",
                    (listing_id, rec.get("price_ty"), rec.get("price_per_m2"), crawl_run_id)
                )
            return listing_id, True

        else:
            listing_id  = existing["id"]
            first_price = existing["price_first_ty"] or existing["price_ty"]
            new_price   = rec.get("price_ty")
            price_dropped  = existing["price_dropped"]
            price_drop_pct = None

            if new_price and first_price and new_price < first_price * 0.99:
                price_dropped  = 1
                price_drop_pct = round((first_price - new_price) / first_price * 100, 2)

            conn.execute("""
                UPDATE listings SET
                    title               = :title,
                    price_ty            = :price_ty,
                    price_per_m2        = :price_per_m2,
                    area_m2             = :area_m2,
                    property_type       = :property_type,
                    area                = :area,
                    road_tier           = CASE WHEN :road_tier > 0 THEN :road_tier
                                               WHEN llm_verified = 1 THEN road_tier
                                               ELSE 0 END,
                    road_type           = :road_type,
                    ward                = :ward,                 -- cho phép NULL overwrite (re-normalize có thể loại ward sai khi text chứa địa danh non-TDM)
                    has_so              = :has_so,
                    is_hot              = :is_hot,
                    price_dropped       = :price_dropped,
                    price_drop_pct      = :price_drop_pct,
                    consecutive_missing = 0,
                    updated_at          = :updated_at,
                    last_seen_at        = :updated_at,
                    first_seen_at       = COALESCE(first_seen_at, :updated_at),
                    is_active           = 1,
                    delisted_at         = NULL,
                    posted_at           = COALESCE(posted_at, :posted_at)
                WHERE id = :id
            """, {
                "id":            listing_id,
                "title":         rec.get("title", ""),
                "price_ty":      new_price,
                "price_per_m2":  rec.get("price_per_m2"),
                "area_m2":       rec.get("area_m2"),
                "property_type": rec.get("property_type", "dat_nen"),
                "area":          rec.get("area", ""),
                "road_tier":     int(rec.get("road_tier", 0)),
                "road_type":     rec.get("road_type") or "unknown",
                "ward":          rec.get("ward") or None,
                "has_so":        int(rec.get("has_so", False)),
                "is_hot":        int(rec.get("is_hot", False)),
                "price_dropped": price_dropped,
                "price_drop_pct": price_drop_pct,
                "updated_at":    now,
                "posted_at":     rec.get("post_date"),
            })

            if new_price or rec.get("price_per_m2"):
                conn.execute(
                    "INSERT INTO price_history (listing_id, price_ty, price_per_m2, crawl_run_id) VALUES (?,?,?,?)",
                    (listing_id, new_price, rec.get("price_per_m2"), crawl_run_id)
                )
            return listing_id, False


def update_listing_outlier(listing_id: int, is_outlier: bool,
                           direction: Optional[str], sigma: Optional[float]) -> None:
    """Cập nhật outlier flag sau khi chạy valuation."""
    with get_conn() as conn:
        conn.execute("""
            UPDATE listings SET
                is_outlier        = ?,
                outlier_direction = ?,
                outlier_sigma     = ?
            WHERE id = ?
        """, (int(is_outlier), direction, sigma, listing_id))


def insert_images(listing_id: int, img_urls: list) -> None:
    with get_conn() as conn:
        for order, url in enumerate(img_urls):
            img_type = _classify_image_type(url, order)
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO listing_images (listing_id, img_url, img_order, img_type) VALUES (?,?,?,?)",
                    (listing_id, url, order, img_type)
                )
            except Exception as e:
                logger.warning(f"Image insert skip: {e}")


def _classify_image_type(url: str, order: int) -> str:
    url_lower = url.lower()
    if any(k in url_lower for k in ["so-hong", "sohong", "gcn", "giay-chung-nhan"]):
        return "so_hong"
    if any(k in url_lower for k in ["aerial", "drone", "satellite"]):
        return "aerial"
    return "cover" if order == 0 else "unknown"


# ─── Crawl runs ───────────────────────────────────────────────────────────────

def start_crawl_run(source: str, area: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO crawl_runs (source, area) VALUES (?, ?)", (source, area)
        )
        return cur.lastrowid


def finish_crawl_run(run_id: int, stats: dict,
                     status: str = "done", error_msg: str = None) -> None:
    with get_conn() as conn:
        conn.execute("""
            UPDATE crawl_runs SET
                finished_at     = datetime('now'),
                n_fetched       = :n_fetched,
                n_new           = :n_new,
                n_updated       = :n_updated,
                n_price_dropped = :n_price_dropped,
                n_skipped       = :n_skipped,
                status          = :status,
                error_msg       = :error_msg
            WHERE id = :id
        """, {
            "id":              run_id,
            "n_fetched":       stats.get("fetched", 0),
            "n_new":           stats.get("new", 0),
            "n_updated":       stats.get("updated", 0),
            "n_price_dropped": stats.get("price_dropped", 0),
            "n_skipped":       stats.get("skipped", 0),
            "status":          status,
            "error_msg":       error_msg,
        })


def mark_missing_listings(source: str, seen_urls: set) -> int:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, url, consecutive_missing FROM listings WHERE source=? AND probably_sold=0",
            (source,)
        ).fetchall()
        sold_count = 0
        for row in rows:
            if row["url"] not in seen_urls:
                n = row["consecutive_missing"] + 1
                sold = 1 if n >= 3 else 0
                sold_at = datetime.now().isoformat() if sold and n == 3 else None
                if sold:
                    sold_count += 1
                conn.execute(
                    "UPDATE listings SET consecutive_missing=?, probably_sold=?, sold_at=COALESCE(sold_at,?) WHERE id=?",
                    (n, sold, sold_at, row["id"])
                )
    return sold_count


# ─── Analytics ────────────────────────────────────────────────────────────────

def save_alert_log(listing_id: int, alert_type: str, message: str) -> bool:
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO alert_logs (listing_id, alert_type, message) VALUES (?,?,?)",
                (listing_id, alert_type, message)
            )
            return True
        except sqlite3.IntegrityError:
            return False


def save_valuation_result(listing_id: int, result: dict,
                          crawl_run_id: Optional[int] = None) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO valuation_results
                (listing_id, crawl_run_id, fair_ppm2, actual_ppm2, mos_pct,
                 is_signal, is_outlier, outlier_direction, outlier_sigma,
                 segment, n_segment, signal_score, road_tier)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            listing_id, crawl_run_id,
            result.get("fair_ppm2"),
            result.get("actual_ppm2"),
            result.get("mos_pct"),
            int(result.get("is_signal", False)),
            int(result.get("is_outlier", False)),
            result.get("outlier_direction"),
            result.get("outlier_sigma"),
            result.get("segment"),
            result.get("n_segment"),
            result.get("signal_score"),
            result.get("road_tier", 0),
        ))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_existing_source_ids(source: str) -> set:
    """Lấy source_ids đã có trong raw_listings (dùng incremental)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT source_id FROM raw_listings WHERE source=? AND source_id IS NOT NULL",
            (source,)
        ).fetchall()
    return {r[0] for r in rows}
