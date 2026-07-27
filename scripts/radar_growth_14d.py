#!/usr/bin/env python3
"""Summarize Radar BDS's 14-day article → social → UTM → lead loop."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
STATE_ROOT = Path("/opt/radar-bds/var/social_queue")
VIEW_ACTIONS = (
    "seo_landing_viewed", "seo_article_viewed", "seo_report_viewed",
    "seo_report_hub_viewed", "seo_knowledge_hub_viewed",
)
TARGETS_14D = {
    "articles": 10,
    "page_posts": 10,
    "group_posts": 2,
    "comments": 4,
    "social_utm_visits": 120,
    "content_views": 240,
    "leads": 1,
}
UTM_CONVENTION = {
    "page": "facebook / organic_social / page_article / {slug}",
    "group": "facebook / group_post / group_data_post / {slug}-{group}",
    "comment": "facebook / comment / public_post_seeding / {ward}-{topic}",
    "page_comment": "facebook / pinned_comment / page_article / {slug}",
}


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _when(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        return parsed.astimezone(TZ)
    except ValueError:
        return None


def _recent(value: Any, cutoff: datetime) -> bool:
    parsed = _when(value)
    return bool(parsed and parsed >= cutoff)


def _content_counts(cutoff: datetime) -> dict[str, int]:
    from config.seo_articles import SEO_ARTICLES

    articles = 0
    for page in SEO_ARTICLES.values():
        if not str(page.get("path", "")).startswith("/tin-tuc/"):
            continue
        article = page.get("article") or {}
        if _recent(article.get("published_at") or article.get("modified_at"), cutoff):
            articles += 1

    page_state = _load_json(STATE_ROOT / "posted_slugs.json", {}).get("posted", {})
    page_posts = sum(_recent(row.get("posted_at"), cutoff) for row in page_state.values())

    group_rows = _load_json(STATE_ROOT / "group-autopost/state.json", {}).get("actions", [])
    group_posts = sum(
        row.get("status") == "published" and _recent(row.get("at"), cutoff)
        for row in group_rows
    )

    comment_rows = _load_json(STATE_ROOT / "public-post-comment/state.json", {}).get("actions", [])
    comments = sum(
        row.get("status") == "published" and _recent(row.get("at"), cutoff)
        for row in comment_rows
    )
    return {
        "articles": articles,
        "page_posts": page_posts,
        "group_posts": group_posts,
        "comments": comments,
    }


def _db_counts(cutoff: datetime) -> dict[str, Any]:
    from db.connection import get_conn

    cutoff_text = cutoff.isoformat()
    actions = list(VIEW_ACTIONS) + ["social_utm_visit", "cta_clicked", "lead_capture_submit"]
    placeholders = ",".join("?" for _ in actions)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT action, COUNT(*) AS n FROM user_audit_log "
            f"WHERE created_at >= ? AND action IN ({placeholders}) GROUP BY action",
            (cutoff_text, *actions),
        ).fetchall()
        action_counts = {str(row["action"]): int(row["n"]) for row in rows}
        lead_row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN listing_url LIKE '%utm_source=%' THEN 1 ELSE 0 END) AS attributed "
            "FROM lead_captures WHERE created_at >= ?",
            (cutoff_text,),
        ).fetchone()
    return {
        "action_counts": action_counts,
        "content_views": sum(action_counts.get(action, 0) for action in VIEW_ACTIONS),
        "social_utm_visits": action_counts.get("social_utm_visit", 0),
        "cta_clicks": action_counts.get("cta_clicked", 0),
        "lead_submit_events": action_counts.get("lead_capture_submit", 0),
        "leads": int(lead_row["total"] or 0),
        "attributed_leads": int(lead_row["attributed"] or 0),
    }


def build_report(days: int = 14, now: datetime | None = None, include_db: bool = True) -> dict[str, Any]:
    now = (now or datetime.now(TZ)).astimezone(TZ)
    cutoff = now - timedelta(days=days)
    metrics = _content_counts(cutoff)
    if include_db:
        metrics.update(_db_counts(cutoff))
    else:
        metrics.update({
            "action_counts": {}, "content_views": 0, "social_utm_visits": 0,
            "cta_clicks": 0, "lead_submit_events": 0, "leads": 0,
            "attributed_leads": 0,
        })
    score = {
        key: {"actual": metrics[key], "target": target, "met": metrics[key] >= target}
        for key, target in TARGETS_14D.items()
    }
    return {
        "window": {"days": days, "from": cutoff.isoformat(), "to": now.isoformat()},
        "utm_convention": UTM_CONVENTION,
        "metrics": metrics,
        "targets_14d": score,
    }


def _print_text(report: dict[str, Any]) -> None:
    window = report["window"]
    print(f"Radar BDS growth loop — {window['days']} ngày ({window['from'][:10]} → {window['to'][:10]})")
    print("Bài → Page → group/comment → UTM → lead")
    for key, row in report["targets_14d"].items():
        mark = "OK" if row["met"] else "CHƯA"
        print(f"- {key}: {row['actual']} / {row['target']} [{mark}]")
    m = report["metrics"]
    print(f"- cta_clicks: {m['cta_clicks']}")
    print(f"- attributed_leads: {m['attributed_leads']} / {m['leads']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-db", action="store_true", help="Only inspect config/social state")
    args = parser.parse_args()
    report = build_report(max(1, args.days), include_db=not args.no_db)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_text(report)


if __name__ == "__main__":
    main()
