"""
Telegram Alert — SQLite version

Gửi thông báo signal mới mỗi lần chạy crawl-daily.
Cấu hình: thêm vào file .env hoặc set env var:
    TELEGRAM_BOT_TOKEN=xxx
    TELEGRAM_CHAT_ID=xxx
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


def _get_credentials():
    from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    return TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Gửi message Telegram tới admin chat (TELEGRAM_CHAT_ID env). Return True nếu thành công."""
    token, chat_id = _get_credentials()
    if not chat_id:
        logger.warning("Telegram: chưa cấu hình TELEGRAM_CHAT_ID")
        return False
    return send_message_to(chat_id, text, parse_mode=parse_mode)


def send_message_to(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Gửi tới chat_id bất kỳ (dùng cho VIP push, bind confirm)."""
    if not _HAS_REQUESTS:
        logger.warning("Telegram: pip install requests")
        return False
    token, _ = _get_credentials()
    import os
    if not token:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or not chat_id:
        logger.warning("Telegram send_message_to: missing token/chat_id")
        return False
    if os.getenv("TELEGRAM_DRY_RUN", "").strip() == "1":
        logger.info(f"[telegram DRY] to={chat_id} text={text[:80]!r}")
        return True
    try:
        resp = _requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
                  "disable_web_page_preview": True},
            timeout=10,
        )
        ok = resp.json().get("ok", False)
        if not ok:
            logger.warning(f"Telegram API error: {resp.json()}")
        return ok
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def send_listing_card(chat_id: str, listing: dict, base_url: str = "") -> bool:
    """Format 1 listing thành card đẹp + gửi tới chat_id."""
    lid = listing.get("id")
    title = (listing.get("title") or "(không tên)")[:120]
    ward = listing.get("ward") or ""
    price = listing.get("price_ty")
    mos = listing.get("mos_pct")
    area = listing.get("area_m2")
    parts = [f"🔥 <b>{title}</b>"]
    meta = []
    if ward: meta.append(f"📍 {ward}")
    if price is not None: meta.append(f"💰 {price} tỷ")
    if area is not None: meta.append(f"📐 {area} m²")
    if mos is not None: meta.append(f"⚡ MOS {mos}%")
    if meta: parts.append(" · ".join(meta))
    if lid:
        url = f"{base_url.rstrip('/')}/?listing={lid}" if base_url else f"/?listing={lid}"
        parts.append(f"🔗 <a href=\"{url}\">Xem chi tiết</a>")
    return send_message_to(chat_id, "\n".join(parts))


def _already_alerted(conn, listing_id: int, alert_type: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM alert_logs WHERE listing_id=? AND alert_type=? "
        "AND sent_at >= datetime('now', '-7 days')",
        (listing_id, alert_type),
    ).fetchone()
    return row is not None


def _log_alert(conn, listing_id: int, alert_type: str, message: str):
    try:
        conn.execute(
            "INSERT OR IGNORE INTO alert_logs (listing_id, alert_type, message, sent_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (listing_id, alert_type, message),
        )
    except Exception:
        pass


def alert_new_signals(conn, signal_ids_before: set) -> tuple:
    """
    So sánh signal trước/sau crawl, gửi Telegram cho signal mới.
    Trả về (alert_count, new_signal_list).
    """
    rows = conn.execute("""
        SELECT v.listing_id, v.mos_pct, v.fair_ppm2, v.actual_ppm2,
               l.title, l.url, l.price_ty, l.area_m2, l.area, l.property_type
        FROM valuation_results v
        JOIN listings l ON l.id = v.listing_id
        WHERE v.is_signal = 1 AND l.probably_sold = 0
    """).fetchall()

    alert_count = 0
    new_signals = []

    for r in rows:
        lid = r["listing_id"]
        if lid in signal_ids_before:
            continue
        if _already_alerted(conn, lid, "mos_signal"):
            continue

        mos   = round(r["mos_pct"] or 0, 1)
        price = r["price_ty"] or 0
        area  = r["area_m2"] or 0
        title = (r["title"] or "")[:80]
        url   = r["url"] or ""

        msg = (
            f"🚨 <b>MOS SIGNAL -{mos}%</b>\n"
            f"📍 {r['area']} | {r['property_type']}\n"
            f"🏷️ {title}\n"
            f"💵 {price:.2f} tỷ | {area:.0f} m²\n"
            f"📉 Fair: {r['fair_ppm2']:.1f} tr/m² → Actual: {r['actual_ppm2']:.1f} tr/m²\n"
            f"🔗 {'https://guland.vn/' + url if not url.startswith('http') else url}"
        )
        if send_message(msg):
            _log_alert(conn, lid, "mos_signal", msg)
            alert_count += 1
        new_signals.append(dict(r))

    return alert_count, new_signals


def alert_delisted_signals(conn, hours: int = 72) -> int:
    """
    Logic giá trị: signal biến mất nhanh = market-validated → alert thứ cấp
    "Deal vừa khớp tại khu X — còn N signal tương tự đang active".
    User → biết khu này đang nóng → ra quyết định mua các signal còn lại nhanh hơn.
    """
    from analytics.lifecycle import get_delisted_signals, segment_velocity
    delisted = get_delisted_signals(conn, hours=hours)
    if not delisted:
        return 0

    # Đếm active signals cùng segment để gợi ý "còn N cơ hội"
    active_by_segment = {}
    rows = conn.execute("""
        SELECT l.area, l.property_type, COUNT(*) AS n
          FROM valuation_results v JOIN listings l ON l.id = v.listing_id
         WHERE v.is_signal = 1 AND l.is_active = 1 AND l.probably_sold = 0
         GROUP BY l.area, l.property_type
    """).fetchall()
    for r in rows:
        active_by_segment[(r["area"], r["property_type"])] = r["n"]

    sent = 0
    for d in delisted:
        lid = d["id"]
        if _already_alerted(conn, lid, "delisted_signal"):
            continue
        hours_alive = (d.get("lifecycle_hours") or 0)
        n_same     = active_by_segment.get((d["area"], d["property_type"]), 0)
        mos        = round(d.get("mos_pct") or 0, 1)

        msg = (
            f"✅ <b>SIGNAL KHỚP</b> sau {hours_alive}h (−{mos}% MOS)\n"
            f"📍 {d['area']} | {d['property_type']}\n"
            f"🏷️ {(d.get('title') or '')[:80]}\n"
            f"💵 {(d.get('price_ty') or 0):.2f} tỷ | {(d.get('area_m2') or 0):.0f} m²\n"
            f"🔥 Khu này còn <b>{n_same}</b> signal tương tự đang active — xem nhanh!"
        )
        if send_message(msg):
            _log_alert(conn, lid, "delisted_signal", msg)
            sent += 1
    return sent


def collect_hot_deals_3d(conn) -> list:
    """
    Lấy listings ĐƯỢC ĐĂNG TRONG 3 NGÀY QUA (posted_at) và lần đầu DB thấy
    cũng trong 3 ngày, có (is_hot=1 OR is_signal=1), chưa alert trong 7 ngày.
    Lọc kép posted_at + first_seen_at giúp tránh:
      - Tin tháng trước được hệ thống cào lần đầu hôm nay (filter posted_at)
      - Tin được crawl lại nhiều lần (filter first_seen_at)
    """
    rows = conn.execute("""
        SELECT l.id AS listing_id, l.title, l.url, l.price_ty, l.area_m2,
               l.area, l.ward, l.property_type, l.is_hot, l.source,
               l.road_tier, l.has_so, l.frontage_m, l.price_dropped,
               l.posted_at, l.first_seen_at,
               l.possibly_duplicate, l.duplicate_of_id,
               canon.price_ty  AS canonical_price_ty,
               canon.posted_at AS canonical_posted_at,
               v.mos_pct, v.fair_ppm2, v.actual_ppm2, v.is_signal,
               v.signal_score, v.n_segment, v.segment,
               m.median_ppm2 AS ward_median
          FROM listings l
          LEFT JOIN listings canon         ON canon.id = l.duplicate_of_id
          LEFT JOIN valuation_results v    ON v.listing_id = l.id
          LEFT JOIN market_weekly m
                 ON m.area = l.area AND m.property_type = l.property_type
         WHERE l.probably_sold = 0
           AND l.first_seen_at >= datetime('now', '-72 hours')
           AND l.posted_at     >= date('now', '-3 day')
           AND (l.is_hot = 1 OR v.is_signal = 1)
           AND COALESCE(v.signal_score, 0) >= 55
           AND (
                COALESCE(l.possibly_duplicate, 0) = 0
                OR (l.possibly_duplicate = 1
                    AND canon.price_ty IS NOT NULL
                    AND l.price_ty < canon.price_ty * 0.90)
           )
           AND NOT EXISTS (
                SELECT 1 FROM listings older
                 WHERE older.content_hash IS NOT NULL
                   AND older.content_hash = l.content_hash
                   AND older.id != l.id
                   AND older.first_seen_at < datetime('now', '-3 day')
           )
         ORDER BY COALESCE(v.signal_score, 0) DESC, COALESCE(v.mos_pct, 0) DESC
    """).fetchall()

    fresh = []
    for r in rows:
        if not _already_alerted(conn, r["listing_id"], "hot_deal_3d"):
            fresh.append(dict(r))
    return fresh


def collect_fresh_signals(conn, since_ts: str) -> list:
    """
    Lấy listings mới crawl trong run hiện tại (first_seen_at >= since_ts)
    đã được valuation đánh giá là deal ngộp (v.is_signal = 1) và chưa alert.
    Order: signal_score desc, mos_pct desc.
    """
    rows = conn.execute("""
        SELECT l.id AS listing_id, l.title, l.url, l.price_ty, l.area_m2,
               l.area, l.ward, l.property_type, l.is_hot, l.source,
               l.road_tier, l.has_so, l.frontage_m, l.price_dropped,
               l.posted_at, l.first_seen_at,
               l.possibly_duplicate, l.duplicate_of_id,
               canon.price_ty  AS canonical_price_ty,
               v.mos_pct, v.fair_ppm2, v.actual_ppm2, v.is_signal,
               v.signal_score, v.n_segment, v.segment,
               m.median_ppm2 AS ward_median
          FROM listings l
          LEFT JOIN listings canon       ON canon.id = l.duplicate_of_id
          LEFT JOIN valuation_results v  ON v.listing_id = l.id
          LEFT JOIN market_weekly m
                 ON m.area = l.area AND m.property_type = l.property_type
         WHERE l.probably_sold = 0
           AND l.first_seen_at >= ?
           AND v.is_signal = 1
         ORDER BY COALESCE(v.signal_score, 0) DESC, COALESCE(v.mos_pct, 0) DESC
    """, (since_ts,)).fetchall()

    fresh = []
    for r in rows:
        if not _already_alerted(conn, r["listing_id"], "fresh_signal"):
            fresh.append(dict(r))
    return fresh


def _compose_reasons(d: dict) -> list:
    """Liệt kê 1-5 lý do tại sao deal đáng chú ý — dùng cho field 'Vì sao rẻ'."""
    reasons = []

    canon_price = d.get("canonical_price_ty")
    if d.get("possibly_duplicate") and canon_price and (d.get("price_ty") or 0) > 0:
        drop_pct = (1 - d["price_ty"] / canon_price) * 100
        if drop_pct >= 10:
            reasons.append(
                f"💸 <b>Đăng lại với giá giảm {drop_pct:.0f}%</b> "
                f"(lần đầu {canon_price:.2f} tỷ → nay {d['price_ty']:.2f} tỷ)"
            )

    mos = d.get("mos_pct") or 0
    if d.get("is_signal") and mos > 0:
        n = d.get("n_segment") or 0
        wm = d.get("ward_median")
        seg_label = _esc(f"{d.get('ward') or d.get('area') or '?'}/{d.get('property_type') or '?'}")
        if wm:
            reasons.append(
                f"Thực {(d.get('actual_ppm2') or 0):.1f} tr/m² &lt; median {seg_label} {wm:.1f} tr/m² — rẻ hơn fair value <b>{mos:.1f}%</b> (n={n} mẫu)"
            )
        else:
            reasons.append(f"Rẻ hơn fair value <b>{mos:.1f}%</b> (n={n} mẫu segment)")

    if d.get("is_hot"):
        reasons.append("Chủ ghi <b>ngộp/cắt lỗ/bán gấp</b> trong tin")

    score = d.get("signal_score") or 0
    # Threshold re-tuned 2026-04-27 (signal_score MOS cap 65, max thực ~66):
    # ≥60 = TOP, 45-59 = REVIEW, <45 = LOẠI (không alert).
    if score >= 60:
        reasons.append(f"Signal score <b>{score}pt — TOP</b> (multi-factor)")
    elif score >= 45:
        reasons.append(f"Signal score {score}pt — REVIEW")

    tier = d.get("road_tier") or 0
    tier_label = {1: "đường lớn có tên", 2: "đường nhựa/DX", 3: "hẻm xe hơi ≥5m"}
    if d.get("is_signal") and tier in (1, 2, 3):
        reasons.append(f"Đường tốt ({tier_label[tier]}) — thanh khoản")

    area = d.get("area_m2") or 0
    if 50 <= area <= 200:
        reasons.append(f"DT {area:.0f}m² nằm trong sweet-spot 50–200")

    price = d.get("price_ty") or 0
    if 0 < price <= 3:
        reasons.append("Tầm giá ≤3 tỷ — vừa túi NĐT cá nhân")

    if d.get("price_dropped"):
        reasons.append("Đã giảm giá so với lần đăng đầu")

    if not d.get("has_so"):
        reasons.append("⚠️ Chưa rõ pháp lý — verify trước khi gặp chủ")

    return reasons


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_consolidated_daily_alert(conn, deals: list, new_count: int,
                                   total_active_signals: int = 0,
                                   alert_type: str = "fresh_signal") -> int:
    """
    Gửi 1 tin Telegram tổng hợp gồm:
      - Header: số tin mới crawl run này + số deal ngộp mới
      - Mỗi deal: tags + giá/DT/ward + 'Vì sao đáng chú ý' + 2 link:
          'Mở trong Radar' (dashboard project) + 'Original source' (link gốc dạng anchor)
      - Footer: 'Còn lại N tin ngộp đang active — xem thêm tại Dashboard'
    Tự chia thành nhiều tin nếu vượt 4000 ký tự.
    Đánh dấu các listing đã alert trong alert_logs (alert_type).
    """
    from config.settings import DASHBOARD_BASE_URL
    base = DASHBOARD_BASE_URL.rstrip("/")

    if not deals:
        msg = (
            f"📊 <b>Radar BDS — Crawl run này</b>\n"
            f"🆕 Tin mới crawl: <b>{new_count}</b>\n"
            f"😴 Không có deal ngộp mới trong run này.\n"
            f'<i>Tổng signal đang active toàn DB: {total_active_signals} — '
            f'<a href="{_esc(base)}/">xem Dashboard</a></i>'
        )
        send_message(msg)
        return 0

    header = [
        f"🚨 <b>Radar BDS — Alert deal ngộp</b>",
        f"🆕 Tin mới crawl run này: <b>{new_count}</b>",
        f"🔥 Deal ngộp mới: <b>{len(deals)}</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
    ]

    MAX_DEALS = 15
    blocks = []
    for i, d in enumerate(deals[:MAX_DEALS], 1):
        title = _esc(d.get("title") or "")[:90]
        price = d.get("price_ty") or 0
        area  = d.get("area_m2") or 0
        ward  = _esc(d.get("ward") or d.get("area") or "?")
        ptype = _esc(d.get("property_type") or "?")
        src   = _esc(d.get("source") or "?")

        listing_id = d.get("listing_id")
        project_url = f"{base}/listing/{listing_id}"

        orig_url = d.get("url") or ""
        if orig_url and not orig_url.startswith("http"):
            orig_url = "https://guland.vn/" + orig_url

        tags = []
        if d.get("is_hot"):
            tags.append("🔴 NGỘP")
        if d.get("is_signal"):
            tags.append(f"💰 -{(d.get('mos_pct') or 0):.1f}%")
        if d.get("possibly_duplicate") and d.get("canonical_price_ty"):
            tags.append("💸 GIẢM GIÁ")
        tag_str = " ".join(tags) or "🆕"

        lines = [
            f"\n<b>{i}. {tag_str}</b> — {price:.2f} tỷ | {area:.0f} m² | {ward}",
            f"📂 {ptype} | nguồn: {src}",
            f"🏷️ {title}",
        ]
        if d.get("is_signal"):
            lines.append(
                f"📉 Fair <b>{(d.get('fair_ppm2') or 0):.1f}</b> → Thực <b>{(d.get('actual_ppm2') or 0):.1f}</b> tr/m²"
            )
        reasons = _compose_reasons(d)
        if reasons:
            lines.append("💡 <i>Vì sao đáng chú ý:</i>")
            for r in reasons:
                lines.append(f"   • {r}")
        lines.append(f'🔗 <a href="{_esc(project_url)}">Mở trong Radar</a>')
        if orig_url:
            lines.append(f'📎 <a href="{_esc(orig_url)}">Original source</a>')
        blocks.append("\n".join(lines))

    if len(deals) > MAX_DEALS:
        blocks.append(f"\n<i>... và {len(deals)-MAX_DEALS} deals khác — xem Dashboard</i>")

    # Footer: tổng tin ngộp đang active + link dashboard
    shown_count = len(deals[:MAX_DEALS])
    remaining = max(int(total_active_signals or 0) - shown_count, 0)
    footer = (
        f"\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Còn lại <b>{remaining}</b> tin ngộp đang active — "
        f'<a href="{_esc(base)}/">xem thêm tại Dashboard</a>'
    )

    # Gộp + chia tin nếu cần (Telegram limit 4096 chars)
    LIMIT = 3800
    chunks = []
    cur = "\n".join(header)
    for b in blocks:
        if len(cur) + len(b) + 1 > LIMIT:
            chunks.append(cur)
            cur = b
        else:
            cur += "\n" + b
    # Cố gắng append footer vào chunk cuối; nếu không vừa, tách thành chunk riêng
    if cur:
        if len(cur) + len(footer) + 1 > LIMIT:
            chunks.append(cur)
            chunks.append(footer.lstrip("\n"))
        else:
            chunks.append(cur + footer)

    sent_ok = True
    for c in chunks:
        if not send_message(c):
            sent_ok = False
            break

    if sent_ok:
        for d in deals[:MAX_DEALS]:
            _log_alert(conn, d["listing_id"], alert_type, "[consolidated]")
        return len(deals[:MAX_DEALS])
    return 0
