"""Operational/infrastructure alerts for Radar BDS.

Separate from `alerts/telegram.py` (which is strictly per-user VIP push for
listing data). This channel is for crawler health, scheduled-job failures,
and other operator-facing signals. Sends to a single admin chat configured
via `OPS_ALERT_CHAT_ID`. Silently skips when the env var is unset so that
local dev runs are not noisy.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _ops_chat_id() -> str:
    return (os.getenv("OPS_ALERT_CHAT_ID", "") or "").strip()


def send_ops_alert(text: str) -> bool:
    chat_id = _ops_chat_id()
    if not chat_id:
        return False
    from alerts.telegram import send_message_to

    return send_message_to(chat_id, f"⚙️ <b>[Radar BDS OPS]</b>\n{text}")


def summarize_crawl_health(rows: list) -> tuple[bool, str]:
    """Inspect a list of crawl_runs rows since the run started.

    Returns (unhealthy, formatted_message). `unhealthy` is True when any
    source reported status='error' or finished with zero fetched records
    (likely blocked / rate-limited / page structure change).
    """
    if not rows:
        return True, "Không có run nào được ghi vào crawl_runs — pipeline có thể bị crash sớm."

    lines = []
    unhealthy = False
    for r in rows:
        source = r["source"] if isinstance(r, dict) or hasattr(r, "keys") else r[0]
        status = r["status"] if hasattr(r, "keys") else r[1]
        n_fetched = (r["n_fetched"] if hasattr(r, "keys") else r[2]) or 0
        n_new = (r["n_new"] if hasattr(r, "keys") else r[3]) or 0
        error_msg = (r["error_msg"] if hasattr(r, "keys") else r[4]) or ""

        if status == "error":
            unhealthy = True
            tag = "❌ ERROR"
        elif status == "partial":
            unhealthy = True
            tag = "⚠️ PARTIAL"
        elif n_fetched == 0 and n_new == 0:
            unhealthy = True
            tag = "⚠️ ZERO FETCHED"
        else:
            tag = "✅ OK"
        line = f"{tag} {source}: fetched={n_fetched} new={n_new}"
        if error_msg:
            line += f"\n   ↳ {error_msg[:200]}"
        lines.append(line)

    msg = "Crawl health summary:\n" + "\n".join(lines)
    return unhealthy, msg
