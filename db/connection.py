"""SQLite connection management for Radar BDS."""
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_db_path() -> Path:
    """
    Priority: env RADAR_DB_PATH -> test writable -> use it.
    Fallback: try known local paths until one is writable.
    """
    import os
    import stat
    import tempfile

    env = os.environ.get("RADAR_DB_PATH", "").strip()
    if env:
        p = Path(env)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            test = p.parent / ".write_test"
            test.touch()
            test.unlink()
            logger.info(f"DB path (env): {p}")
            return p
        except Exception as e:
            logger.warning(f"RADAR_DB_PATH khong dung duoc ({e}), fallback auto")

    project_root = Path(__file__).parent.parent
    candidates = [
        project_root / "data" / "radar_bds.db",
        Path.home() / "radar_bds.db",
        Path(tempfile.gettempdir()) / "radar_bds.db",
    ]
    for p in candidates:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists() and not (p.stat().st_mode & stat.S_IWUSR):
                continue
            test = p.parent / ".write_test"
            test.touch()
            test.unlink()
            logger.info(f"DB path (auto): {p}")
            return p
        except Exception:
            continue

    p = Path(tempfile.mktemp(suffix=".db", prefix="radar_bds_"))
    logger.warning(f"DB path (last resort): {p}")
    return p


DB_PATH = _resolve_db_path()
_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """
    Per-thread SQLite connection.
    Each worker gets its own connection to avoid transaction races.
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
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


def close_all():
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None
