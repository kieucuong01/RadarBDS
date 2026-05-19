"""Claude pre-review CLI (CỐ VẤN).

`review-queue`  — liệt kê signal CHƯA có verdict Claude + investment memo (JSON).
`review-save`   — lưu verdict Claude (append-only) vào bảng RIÊNG ai_deal_review.

RANH GIỚI ANTI-BIAS (tuyệt đối không vi phạm):
- KHÔNG đụng `ai_training_feedback` (nhãn người = ground-truth).
- KHÔNG đụng `listings.review_hidden` / không auto-hide.
- Append-only: luôn INSERT mới, KHÔNG UPDATE/UPSERT.
Logic định giá CHỈ học từ nhãn người. Claude chỉ cố vấn; người chốt cuối.
"""

import json
import sys
from datetime import datetime, timezone

from db import connection
from db.connection import get_conn
from db.schema import init_schema

CLAUDE_VERDICTS = {"cheap_real", "suspect", "not_cheap", "insufficient_info"}
_MODEL = "claude-code-interactive"


def cmd_review_queue(args):
    """In JSON ra stdout: signal chưa review + investment memo (tier=admin)."""
    init_schema()
    from services.investment_memo import load_investment_memo

    top = getattr(args, "top", None) or 5
    ward = getattr(args, "ward", None)

    sql = """
        SELECT l.id, l.title, l.url, l.ward, l.price_ty, l.area_m2,
               v.mos_pct, v.signal_score
        FROM listings l
        JOIN valuation_results v ON v.listing_id = l.id
        LEFT JOIN ai_deal_review r
               ON r.id = (SELECT id FROM ai_deal_review
                          WHERE listing_id = l.id
                          ORDER BY created_at DESC LIMIT 1)
        WHERE v.is_signal = 1 AND v.signal_score IS NOT NULL
          AND r.id IS NULL
          AND COALESCE(l.is_blacklisted, 0) = 0
          AND COALESCE(l.review_hidden, 0) = 0
          AND COALESCE(l.probably_sold, 0) = 0
    """
    params = []
    if ward:
        sql += " AND l.ward = ?"
        params.append(ward)
    sql += " ORDER BY v.signal_score DESC, v.mos_pct DESC LIMIT ?"
    params.append(top)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    db_path = str(connection.DB_PATH)
    items = []
    for row in rows:
        memo = load_investment_memo(db_path, row["id"], tier="admin")
        if memo is None:
            continue
        items.append({
            "listing_id": row["id"],
            "title": row["title"],
            "url": row["url"],
            "ward": row["ward"],
            "price_ty": row["price_ty"],
            "area_m2": row["area_m2"],
            "mos_pct": row["mos_pct"],
            "signal_score": row["signal_score"],
            "memo": memo,
        })

    out = {
        "count": len(items),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


def cmd_review_save(args):
    """INSERT mới verdict Claude vào ai_deal_review (append-only)."""
    init_schema()

    verdict = (getattr(args, "verdict", "") or "").strip()
    if verdict not in CLAUDE_VERDICTS:
        print(f"ERROR invalid verdict '{verdict}'. Hợp lệ: "
              f"{sorted(CLAUDE_VERDICTS)}", file=sys.stderr)
        sys.exit(2)

    confidence = getattr(args, "confidence", None)
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            print("ERROR confidence phải là số trong [0,1]", file=sys.stderr)
            sys.exit(2)
        if not (0.0 <= confidence <= 1.0):
            print("ERROR confidence ngoài khoảng [0,1]", file=sys.stderr)
            sys.exit(2)

    reasoning = (getattr(args, "reasoning", "") or "").strip()[:2000]
    if not reasoning:
        print("ERROR --reasoning bắt buộc", file=sys.stderr)
        sys.exit(2)

    raw_flags = getattr(args, "red_flags", None) or ""
    flags = [f.strip() for f in raw_flags.split(";") if f.strip()]
    red_flags_json = json.dumps(flags, ensure_ascii=False) if flags else None

    needs_map = 1 if getattr(args, "needs_map_check", False) else 0
    listing_id = getattr(args, "id", None)

    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM listings WHERE id=?", (listing_id,)
        ).fetchone()
        if not exists:
            print(f"ERROR listing {listing_id} không tồn tại", file=sys.stderr)
            sys.exit(2)
        conn.execute(
            """
            INSERT INTO ai_deal_review
              (listing_id, actor, verdict, confidence, reasoning,
               red_flags, needs_map_check, model, updated_at)
            VALUES (?, 'claude', ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (listing_id, verdict, confidence, reasoning,
             red_flags_json, needs_map, _MODEL),
        )

    print(f"OK review saved listing={listing_id} verdict={verdict} "
          f"conf={confidence}")
