"""Telegram helpers for per-user VIP watchlist notifications.

This module intentionally does not support legacy admin/global broadcasts.
Listing notifications must go through `cli.notify.push_new_listings_to_vip`,
which filters active, unexpired VIP users and sends to each user's private
`telegram_chat_id`.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


def _get_bot_token() -> str:
    from config.settings import TELEGRAM_BOT_TOKEN

    return (TELEGRAM_BOT_TOKEN or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()


def send_message_to(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Send a Telegram message to a bound user chat."""
    if not _HAS_REQUESTS:
        logger.warning("Telegram: pip install requests")
        return False
    token = _get_bot_token()
    if not token or not chat_id:
        logger.warning("Telegram send_message_to: missing token/chat_id")
        return False
    if os.getenv("TELEGRAM_DRY_RUN", "").strip() == "1":
        logger.info(f"[telegram DRY] to={chat_id} text={text[:80]!r}")
        return True
    try:
        resp = _requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        ok = resp.json().get("ok", False)
        if not ok:
            logger.warning(f"Telegram API error: {resp.json()}")
        return ok
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def _fmt_ty(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.2f} tỷ"
    except (TypeError, ValueError):
        return "-"


def _fmt_area(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.0f} m²"
    except (TypeError, ValueError):
        return "-"


def _fmt_pct(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "-"


def _deal_tone(mos) -> str:
    try:
        m = float(mos or 0)
    except (TypeError, ValueError):
        m = 0
    if m >= 30:
        return "Biên an toàn cao"
    if m >= 20:
        return "Biên an toàn tốt"
    if m >= 10:
        return "Cần xem thêm dữ liệu"
    return "Theo dõi thêm"


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_watchlist_digest(
    chat_id: str,
    listings: list,
    base_url: str = "",
    max_items: int = 6,
    watchlist_names=None,
) -> bool:
    """Send one compact VIP watchlist digest to a user's bound Telegram chat."""
    if not listings:
        return False
    base = (base_url or "").rstrip("/")
    dashboard_url = f"{base}/" if base else "/"
    shown = listings[:max_items]
    older_count = max(len(listings) - len(shown), 0)
    filter_text = ", ".join((watchlist_names or [])[:3])
    if watchlist_names and len(watchlist_names) > 3:
        filter_text += f" +{len(watchlist_names) - 3}"

    lines = [
        "📡 <b>RADAR BDS - TIN KHỚP WATCHLIST VIP</b>",
        f"🎯 <b>{len(listings)} tin</b> đang khớp tiêu chí của bạn",
    ]
    if filter_text:
        lines.append(f"🔎 Watchlist: <b>{_esc(filter_text)}</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    for idx, listing in enumerate(shown, 1):
        lid = listing.get("id") or listing.get("listing_id")
        detail_url = f"{base}/listing/{lid}" if base and lid else dashboard_url
        title = _esc((listing.get("title") or "(không tên)")[:90])
        ward = _esc(listing.get("ward") or listing.get("area") or "-")
        ptype = _esc(listing.get("property_type") or "-")
        price_text = _fmt_ty(listing.get("price_ty"))
        area_text = _fmt_area(listing.get("area_m2"))
        mos_text = _fmt_pct(listing.get("mos_pct"))
        tone = _deal_tone(listing.get("mos_pct"))
        lines.extend([
            "",
            f"<b>{idx}. {tone}</b>",
            f"🔗 <a href=\"{_esc(detail_url)}\"><b>{title}</b></a>",
            f"💰 {price_text}  ·  📐 {area_text}  ·  📉 MOS {mos_text}",
            f"📍 {ward}  ·  {ptype}",
            "ℹ️ Mở detail để xem lịch sử giá, comps và kiểm tra pháp lý/đường trước khi liên hệ.",
        ])

    lines.append("")
    if older_count:
        lines.append(
            f"📌 Còn <b>{older_count}</b> tin khác cũng khớp watchlist. "
            f"<a href=\"{_esc(dashboard_url)}\"><b>Xem thêm trên Dashboard</b></a>"
        )
    else:
        lines.append(f"📌 <a href=\"{_esc(dashboard_url)}\"><b>Mở Dashboard để xem thêm ngữ cảnh</b></a>")
    return send_message_to(chat_id, "\n".join(lines))
