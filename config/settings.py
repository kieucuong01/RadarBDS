"""
Radar BDS - Global Configuration
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _project_storage_roots() -> tuple[Path, ...]:
    roots = [PROJECT_ROOT]
    for candidate in PROJECT_ROOT.parents:
        if (candidate / ".git").is_dir():
            roots.append(candidate.resolve())
            break
    return tuple(roots)


PROJECT_STORAGE_ROOTS = _project_storage_roots()


# ─── .env LOADER (no external dep) ──────────────────────────────────────────
# Tự load .env ở project root nếu chưa có python-dotenv.
# Non-fatal — thiếu file không throw, env var đã set từ shell có ưu tiên.
def _load_dotenv(env_path: Path, *, override: bool = False) -> None:
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip().lstrip("\ufeff"), v.strip().strip('"').strip("'")
            if k and (override or k not in os.environ):
                os.environ[k] = v
    except Exception:
        pass

# Base/prod-shaped env first; ignored local overrides second.
_load_dotenv(PROJECT_ROOT / ".env")
_load_dotenv(PROJECT_ROOT / ".env.local", override=True)


def _storage_path_is_outside_project(storage_dir: Path) -> bool:
    try:
        return (
            storage_dir.is_absolute()
            and not any(
                storage_dir.is_relative_to(root)
                for root in PROJECT_STORAGE_ROOTS
            )
        )
    except (OSError, RuntimeError, ValueError):
        return False


@dataclass(frozen=True)
class DigitalProductCommerceSettings:
    sales_enabled: bool
    storage_dir: Path | None
    payos_client_id: str = field(repr=False)
    payos_api_key: str = field(repr=False)
    payos_checksum_key: str = field(repr=False)
    cookie_secret: str = field(repr=False)

    @property
    def ready_for_checkout(self) -> bool:
        return bool(
            self.sales_enabled
            and self.storage_dir
            and _storage_path_is_outside_project(self.storage_dir)
            and self.payos_client_id
            and self.payos_api_key
            and self.payos_checksum_key
            and len(self.cookie_secret) >= 64
        )


def get_digital_product_commerce_settings() -> DigitalProductCommerceSettings:
    storage_value = os.getenv("DIGITAL_PRODUCT_STORAGE_DIR", "").strip()
    sales_value = os.getenv("DIGITAL_PRODUCT_SALES_ENABLED", "0").strip().lower()
    storage_dir = Path(storage_value) if storage_value else None
    if storage_dir and storage_dir.is_absolute():
        try:
            storage_dir = storage_dir.resolve(strict=False)
        except (OSError, RuntimeError):
            storage_dir = None
    return DigitalProductCommerceSettings(
        sales_enabled=sales_value in {"1", "true", "yes", "on"},
        storage_dir=storage_dir,
        payos_client_id=os.getenv("PAYOS_CLIENT_ID", "").strip(),
        payos_api_key=os.getenv("PAYOS_API_KEY", "").strip(),
        payos_checksum_key=os.getenv("PAYOS_CHECKSUM_KEY", "").strip(),
        cookie_secret=os.getenv("DIGITAL_PRODUCT_COOKIE_SECRET", "").strip(),
    )


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
# Margin of safety threshold cho is_signal. 0.10 = listing rẻ hơn fair value >=10%.
SIGNAL_MOS_THRESHOLD = float(os.getenv("SIGNAL_MOS_THRESHOLD", 0.10))

# Ngưỡng % giảm giá để VIP nhận push lại cùng một listing. So với giá tại
# lần push gần nhất; dưới ngưỡng → skip để tránh spam, đạt/vượt → re-alert.
SIGNAL_REALERT_THRESHOLD_PCT = float(os.getenv("SIGNAL_REALERT_THRESHOLD_PCT", 5.0))

# ─── ALERTS ──────────────────────────────────────────────────────────────────
# Legal document-image evidence is parked for a later OCR/extraction phase.
LEGAL_IMAGE_EVIDENCE_ENABLED = os.getenv("LEGAL_IMAGE_EVIDENCE_ENABLED", "0").lower() in {"1", "true", "yes", "on"}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://radarbds.vn").strip().rstrip("/")
DASHBOARD_BASE_URL = os.getenv("DASHBOARD_BASE_URL", PUBLIC_BASE_URL).strip().rstrip("/")
DEFAULT_SITE_TITLE = "Radar BDS - Săn deal nhà đất Bình Dương bằng dữ liệu"
DEFAULT_SITE_DESCRIPTION = (
    "Radar BDS giúp săn deal nhà đất Bình Dương bằng dữ liệu: lọc tin rao, định giá, "
    "so sánh thị trường và phát hiện bất động sản có biên an toàn tốt."
)
DEFAULT_SITE_KEYWORDS = (
    "radar bds, săn deal bất động sản, nhà đất Bình Dương, bất động sản Bình Dương, "
    "định giá nhà đất, đất nền Bình Dương"
)


def _looks_corrupted_text(value: str) -> bool:
    if not value:
        return False
    mojibake_markers = (
        "\u00c3",
        "\u00c4",
        "\u00c6",
        "\u00e1\u00ba",
        "\u00e1\u00bb",
        "\u00e2\u20ac",
        "\ufffd",
    )
    return any(marker in value for marker in mojibake_markers) or "??" in value or value.count("?") >= 3


def _seo_env_text(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    return default if _looks_corrupted_text(value) else value


SITE_NAME = _seo_env_text("SITE_NAME", "Radar BDS")
SITE_TITLE = _seo_env_text("SITE_TITLE", DEFAULT_SITE_TITLE)
SITE_DESCRIPTION = _seo_env_text("SITE_DESCRIPTION", DEFAULT_SITE_DESCRIPTION)
SITE_KEYWORDS = _seo_env_text("SITE_KEYWORDS", DEFAULT_SITE_KEYWORDS)
SITE_OG_IMAGE = os.getenv("SITE_OG_IMAGE", f"{PUBLIC_BASE_URL}/static/images/seo/radarbds-og.png").strip()
DEFAULT_GOOGLE_ANALYTICS_ID = "G-YRJZ26W8Y2"
GOOGLE_ANALYTICS_ID = os.getenv("GOOGLE_ANALYTICS_ID", os.getenv("GA4_MEASUREMENT_ID", DEFAULT_GOOGLE_ANALYTICS_ID)).strip()
GOOGLE_SEARCH_CONSOLE_VERIFICATION = os.getenv("GOOGLE_SEARCH_CONSOLE_VERIFICATION", "").strip()

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
