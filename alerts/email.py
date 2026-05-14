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
    salutation = f"Chào {user_name}," if user_name else "Chào VIP,"
    rows = "\n".join(
        f'<tr><td style="padding:10px;border-bottom:1px solid #e5e7eb">'
        f'<a href="/listing/{l.get("id","")}" style="color:#0f766e;text-decoration:none">'
        f'<strong>{l.get("title","(không tên)")}</strong></a><br>'
        f'<small style="color:#64748b">{l.get("ward","")} · '
        f'{l.get("price_ty","?")} tỷ · MOS {l.get("mos_pct","?")}%</small>'
        f'</td></tr>'
        for l in listings[:10]
    )
    extra = (f'<p style="color:#64748b;font-size:13px">… và {len(listings)-10} tin khác trên dashboard</p>'
             if len(listings) > 10 else '')
    html = f"""\
<!doctype html><html><body style="font-family:Segoe UI,Roboto,Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#222">
  <h2 style="color:#0f766e;margin:0 0 12px">🔔 {len(listings)} tin mới khớp watchlist VIP</h2>
  <p>{salutation}</p>
  <p>RadarBDS vừa crawl được các tin sau khớp tiêu chí watchlist của bạn:</p>
  <table style="width:100%;border-collapse:collapse;margin-top:8px">{rows}</table>
  {extra}
  <p style="margin-top:16px"><a href="/" style="background:#0f766e;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none">Mở Dashboard</a></p>
  <p style="color:#64748b;font-size:12px;margin-top:16px">— RadarBDS · Bạn nhận email này vì đăng ký watchlist VIP</p>
</body></html>"""
    return send_email(to_email, f"🔔 {len(listings)} tin mới khớp watchlist của bạn", html)
