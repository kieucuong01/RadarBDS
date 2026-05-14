"""
Radar BDS - Global Configuration
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


# ─── .env LOADER (no external dep) ──────────────────────────────────────────
# Tự load .env ở project root nếu chưa có python-dotenv.
# Non-fatal — thiếu file không throw, env var đã set từ shell có ưu tiên.
def _load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass

_load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# ─── DATABASE ───────────────────────────────────────────────────────────────
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME", "radar_bds")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")
DB_URL  = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ─── CRAWLER ────────────────────────────────────────────────────────────────
CRAWLER_THREADS       = int(os.getenv("CRAWLER_THREADS", 8))
CRAWLER_DELAY_MIN     = float(os.getenv("CRAWLER_DELAY_MIN", 1.5))   # seconds between requests
CRAWLER_DELAY_MAX     = float(os.getenv("CRAWLER_DELAY_MAX", 4.0))
CRAWLER_RETRY_MAX     = int(os.getenv("CRAWLER_RETRY_MAX", 3))
CRAWLER_TIMEOUT       = int(os.getenv("CRAWLER_TIMEOUT", 30))
CRAWL_INTERVAL_MINS   = int(os.getenv("CRAWL_INTERVAL_MINS", 60))    # run every N minutes

# ─── GEOFENCING ─────────────────────────────────────────────────────────────
WATCH_AREAS = [
    {
        "name": "Tân An",
        "district": "Thủ Dầu Một",
        "province": "Bình Dương",
        "keywords": ["tân an", "thủ dầu một", "bình dương"],
    },
    {
        "name": "Hiệp An",
        "district": "Thủ Dầu Một",
        "province": "Bình Dương",
        "keywords": ["hiệp an", "thủ dầu một", "bình dương"],
    },
    {
        "name": "Tương Bình Hiệp",
        "district": "Thủ Dầu Một",
        "province": "Bình Dương",
        "keywords": ["tương bình hiệp", "thủ dầu một", "bình dương"],
    },
    {
        "name": "Định Hòa",
        "district": "Thủ Dầu Một",
        "province": "Bình Dương",
        "keywords": ["định hòa", "thủ dầu một", "bình dương"],
    },
    {
        "name": "Chánh Mỹ",
        "district": "Thủ Dầu Một",
        "province": "Bình Dương",
        "keywords": ["chánh mỹ", "thủ dầu một", "bình dương"],
    },
]

ALERT_KEYWORDS = [
    "quy hoạch khu công nghiệp", "kcn", "mở rộng kcn", "cao tốc",
    "cắt lỗ", "ngộp", "bán gấp", "bán nhanh", "kẹt tiền",
    "sốt đất", "tăng giá", "đầu tư", "lợi nhuận",
]

# ─── SIGNAL DETECTION ───────────────────────────────────────────────────────
# Margin of safety threshold cho is_signal. 0.25 = listing rẻ hơn fair value ≥25%.
SIGNAL_MOS_THRESHOLD = float(os.getenv("SIGNAL_MOS_THRESHOLD", 0.25))

# ─── ALERTS ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
DASHBOARD_BASE_URL = os.getenv("DASHBOARD_BASE_URL", "http://localhost:5000")

# Cảnh báo khi giá thấp hơn X% so với mặt bằng chung
ALERT_PRICE_DROP_PCT  = float(os.getenv("ALERT_PRICE_DROP_PCT", 20.0))
# Cảnh báo khi giá/m2 thấp hơn ngưỡng tuyệt đối (triệu/m2)
ALERT_PRICE_PER_M2_MAX = {
    "Tân An":       float(os.getenv("ALERT_TAN_AN_MAX", 5.0)),
    "Mỹ Phước":     float(os.getenv("ALERT_MY_PHUOC_MAX", 8.0)),
    "Phước Long":   float(os.getenv("ALERT_PHUOC_LONG_MAX", 4.0)),
    "Thủ Dầu Một":  float(os.getenv("ALERT_TDM_MAX", 15.0)),
}

# ─── FACEBOOK ────────────────────────────────────────────────────────────────
FACEBOOK_EMAIL    = os.getenv("FACEBOOK_EMAIL", "")
FACEBOOK_PASSWORD = os.getenv("FACEBOOK_PASSWORD", "")
FACEBOOK_GROUPS   = [
    "https://www.facebook.com/groups/batdongsanlongan",
    "https://www.facebook.com/groups/batdongsanbinhduong",
    "https://www.facebook.com/groups/batdongsanbinhphuoc",
    # Thêm các group cụ thể tại đây
]
FACEBOOK_SCROLL_TIMES = int(os.getenv("FACEBOOK_SCROLL_TIMES", 10))

# ─── ADMIN CONTROL ROOM ───────────────────────────────────────────────────────
ADMIN_BASIC_USER = os.getenv("ADMIN_BASIC_USER", "").strip()
ADMIN_BASIC_PASS = os.getenv("ADMIN_BASIC_PASS", "").strip()

# ─── USER AGENTS ─────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]
