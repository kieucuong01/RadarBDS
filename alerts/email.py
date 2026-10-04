"""SMTP wrapper for transactional emails (lead ack, listing alerts).

Env vars:
- SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASS
- SMTP_FROM (display "RadarBDS <noreply@...>"), defaults to SMTP_USER
- SMTP_DRY_RUN=1 → log instead of send (dev / no SMTP configured)

All functions return bool (True = sent / dry-run logged, False = failed).
Never raise — email failure must not break the request path.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from typing import Iterable

logger = logging.getLogger(__name__)


def _smtp_config() -> dict:
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587") or 587),
        "user": os.getenv("SMTP_USER", "").strip(),
        "pwd": os.getenv("SMTP_PASS", "").strip(),
        "sender": os.getenv("SMTP_FROM", "").strip() or os.getenv("SMTP_USER", "").strip(),
        "dry_run": os.getenv("SMTP_DRY_RUN", "").strip() == "1",
    }


def _is_configured(cfg: dict) -> bool:
    return bool(cfg["host"] and cfg["user"] and cfg["pwd"])


def send_email(to: str, subject: str, html: str, text: str | None = None) -> bool:
    """Send a single email. Returns True on success / dry-run; False on failure."""
    if not to or "@" not in to:
        return False
    cfg = _smtp_config()
    if cfg["dry_run"] or not _is_configured(cfg):
        logger.info(f"[email DRY] to={to} subject={subject!r} (SMTP not configured or DRY_RUN)")
        return True

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("RadarBDS", cfg["sender"]))
    msg["To"] = to
    msg.set_content(text or _html_to_text(html))
    msg.add_alternative(html, subtype="html")

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as srv:
            srv.starttls(context=ctx)
            srv.login(cfg["user"], cfg["pwd"])
            srv.send_message(msg)
        logger.info(f"[email] sent to={to} subject={subject!r}")
        return True
    except Exception as e:
        logger.warning(f"[email] FAILED to={to} subject={subject!r}: {e}")
        return False


def _html_to_text(html: str) -> str:
    import re
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Templates
# ─────────────────────────────────────────────────────────────────────────────
def send_lead_ack(to_email: str, name: str | None, listing_title: str | None,
                  listing_id: int | None = None) -> bool:
    """Confirmation email after lead capture (guest mini-form / logged-in Ráp mối)."""
    salutation = f"Chào {name}," if name else "Chào bạn,"
    title_line = (f"Tin bạn quan tâm: <strong>{listing_title}</strong> (mã #{listing_id})"
                  if listing_title else f"Mã tin: #{listing_id}" if listing_id else "")
    html = f"""\
<!doctype html><html><body style="font-family:Segoe UI,Roboto,Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#222">
  <h2 style="color:#0f766e;margin:0 0 12px">✅ RadarBDS đã nhận yêu cầu ráp mối</h2>
  <p>{salutation}</p>
  <p>Cảm ơn bạn đã gửi yêu cầu qua RadarBDS. Đội ngũ admin sẽ liên hệ trong <strong>30 phút</strong> để xác nhận và ráp mối trực tiếp với chủ tin.</p>
  {('<p style="background:#f0fdfa;padding:12px;border-radius:8px;border:1px solid #ccfbf1">' + title_line + '</p>') if title_line else ''}
  <p style="color:#64748b;font-size:13px;margin-top:24px">Nếu không phải bạn gửi yêu cầu này, vui lòng bỏ qua email.</p>
  <p style="color:#64748b;font-size:12px;margin-top:8px">— RadarBDS · Bình Dương</p>
</body></html>"""
    return send_email(to_email, "✅ RadarBDS đã nhận yêu cầu ráp mối", html)


def send_listing_alert(to_email: str, user_name: str | None, listings: Iterable[dict]) -> bool:
    """Batch alert: VIP user nhận tin mới khớp watchlist."""
    listings = list(listings)
    if not listings:
        return False
    cfg = _smtp_config()
    if cfg['dry_run'] or not _is_configured(cfg):
        return False  # Only actual delivery may advance notification_log.
    from config.settings import DASHBOARD_BASE_URL
    base = DASHBOARD_BASE_URL.rstrip('/')
    def event_text(listing):
        event = listing.get('_notification_event', 'new')
        if event == 'price_drop':
            previous, current = listing.get('_prev_notified_price_ty'), listing.get('price_ty')
            return f'Giảm giá: {previous} → {current} tỷ'
        return {'new': 'Tin mới', 'source_removed': 'Tin đã bị gỡ khỏi nguồn — chưa xác nhận đã bán',
                'source_reappeared': 'Tin xuất hiện lại trên nguồn'}.get(event, 'Cập nhật')
    salutation = f"Chào {escape(user_name)}," if user_name else "Chào bạn,"
    rows = "\n".join(
        f'<tr><td style="padding:10px;border-bottom:1px solid #e5e7eb">'
        f'<a href="{escape(base, quote=True)}/listing/{int(l["id"])}" style="color:#0f766e;text-decoration:none">'
        f'<strong>{escape(str(l.get("title") or "(không tên)"))}</strong></a><br>'
        f'<strong>{escape(event_text(l))}</strong><br>'
        f'<small style="color:#64748b">{escape(str(l.get("ward") or ""))} · '
        f'{escape(str(l.get("price_ty") or "?"))} tỷ · MOS {escape(str(l.get("mos_pct") or "?"))}%</small>'
        f'</td></tr>'
        for l in listings[:10]
    )
    extra = (f'<p style="color:#64748b;font-size:13px">… và {len(listings)-10} tin khác trên dashboard</p>'
             if len(listings) > 10 else '')
    html = f"""\
<!doctype html><html><body style="font-family:Segoe UI,Roboto,Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#222">
  <h2 style="color:#0f766e;margin:0 0 12px">🔔 {len(listings)} cập nhật BĐS đang theo dõi</h2>
  <p>{salutation}</p>
  <p>Cập nhật theo watchlist hoặc các BĐS đã lưu mà bạn đã bật thông báo:</p>
  <table style="width:100%;border-collapse:collapse;margin-top:8px">{rows}</table>
  {extra}
  <p style="margin-top:16px"><a href="{escape(base, quote=True)}/bds-da-luu" style="background:#0f766e;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none">Mở BĐS đã lưu</a></p>
  <p style="color:#64748b;font-size:12px;margin-top:16px">— RadarBDS · Quản lý thông báo từng BĐS tại BĐS đã lưu; quản lý watchlist và kênh nhận trong tài khoản.</p>
</body></html>"""
    return send_email(to_email, f"🔔 {len(listings)} cập nhật BĐS đang theo dõi", html)
