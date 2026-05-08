"""
Centralized logging setup — file + console.
Idempotent: gọi nhiều lần không duplicate handlers.
"""
import logging
import logging.handlers
from pathlib import Path

_CONFIGURED = False


def setup_logging(level: int = logging.INFO,
                  log_dir: str = None,
                  log_name: str = "radar.log",
                  max_bytes: int = 5 * 1024 * 1024,   # 5MB
                  backup_count: int = 5) -> None:
    """
    Khởi tạo logger cho toàn project.
    - Console: INFO
    - File: DEBUG, rotating 5MB × 5 files
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Clear existing handlers (tránh duplicate khi import nhiều lần)
    root.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # File handler — safe fallback nếu không write được
    try:
        log_path = Path(log_dir) if log_dir else Path(__file__).resolve().parent.parent / "logs"
        log_path.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_path / log_name,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception as e:
        # Không throw — CLI vẫn chạy được kể cả khi không ghi file được
        root.warning(f"File logging disabled: {e}")

    # Giảm noise của thư viện bên thứ 3
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)

    _CONFIGURED = True
