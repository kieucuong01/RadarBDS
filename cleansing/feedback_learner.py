"""
Feedback Learner — gọi Groq tổng hợp signal_feedback thành rules SQL.

Workflow:
  1. Mỗi N feedback bad/spam (default 20), trigger learner
  2. Lấy 50 feedback gần nhất kèm context listing
  3. Groq sinh 3-5 SQL WHERE clauses để loại tin tương lai có pattern tương tự
  4. Validate SQL bằng EXPLAIN; reject nếu syntax error
  5. Lưu vào feedback_rules để alert filter dùng
"""
import json
import logging
import os
from typing import List, Dict, Any

import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"   # 70B cho reasoning chất lượng

_SYSTEM = (
    "Bạn là analyst BĐS Thủ Dầu Một. Phân tích pattern feedback của nhà đầu tư "
    "để rút ra các SQL WHERE clauses lọc tin tương lai. "
    "Luôn trả về JSON object có key \"rules\" chứa array, không giải thích thêm."
)

_USER_TMPL = """Dưới đây là {n} signal mà nhà đầu tư đánh giá BAD/SPAM/SOLD (cần loại trong tương lai).
Mỗi signal có thông tin + lý do reject của nhà đầu tư.

Phân tích pattern → sinh 3-5 SQL WHERE clauses để loại tin tương lai có đặc điểm tương tự.

YÊU CẦU SQL:
- Chỉ dùng cột trong bảng `listings`: ward, property_type, road_tier, has_so, area_m2, price_ty, price_per_m2, is_hot, frontage_m
- KHÔNG dùng JOIN, subquery phức tạp
- Mỗi rule phải dựa trên ≥3 case trong data
- WHERE clause phải syntax-valid SQLite (vd: `ward='Tân An' AND area_m2 > 1000`)
- Confidence (0.0-1.0): cao nếu lý do reject lặp lại nhiều lần với cùng pattern

Format JSON:
{{"rules": [
  {{"text": "<mô tả tiếng Việt 1 câu>",
    "sql":  "<WHERE clause>",
    "conf": <float 0.0-1.0>,
    "n":    <số case hỗ trợ>}},
  ...
]}}

DỮ LIỆU FEEDBACK:
{feedback_json}
"""


def _call_groq(feedback_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.warning("GROQ_API_KEY không tìm thấy")
        return []

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _USER_TMPL.format(
                n=len(feedback_rows),
                feedback_json=json.dumps(feedback_rows, ensure_ascii=False, indent=1),
            )},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": 1500,
    }
    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=45,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        raw = json.loads(content)
        rules = raw.get("rules", [])
        if not isinstance(rules, list):
            logger.warning(f"Groq trả format lạ: keys={list(raw.keys())}")
            return []
        return rules
    except requests.HTTPError as e:
        logger.error(f"Groq HTTP error: {e.response.status_code} {e.response.text[:200]}")
        return []
    except Exception as e:
        logger.error(f"Groq call failed: {e}")
        return []


def _validate_sql(conn, where_clause: str) -> bool:
    """Test rule SQL bằng EXPLAIN — không chạy thật, chỉ check parse."""
    try:
        conn.execute(f"EXPLAIN SELECT 1 FROM listings WHERE ({where_clause}) LIMIT 1")
        return True
    except Exception as e:
        logger.warning(f"Rule SQL invalid: {where_clause!r} → {e}")
        return False


def run_learner(conn, min_new: int = 20, force: bool = False) -> int:
    """
    Returns: số rules được sinh ra và save.
    """
    # Đếm feedback mới kể từ lần extract gần nhất (dùng max created_at của feedback_rules làm mốc)
    last_extract = conn.execute(
        "SELECT MAX(created_at) FROM feedback_rules"
    ).fetchone()[0] or "1970-01-01"
    new_count = conn.execute(
        "SELECT COUNT(*) FROM signal_feedback WHERE created_at > ?", (last_extract,)
    ).fetchone()[0]

    if new_count < min_new and not force:
        logger.info(f"Feedback learner skip: new={new_count} < min_new={min_new} (use --force to override)")
        return 0

    logger.info(f"Feedback learner: {new_count} new feedback since {last_extract}")

    # Lấy 50 feedback bad/spam/sold gần nhất kèm context listing
    rows = conn.execute("""
        SELECT f.verdict, f.reason_text,
               ROUND(f.snapshot_mos*100, 1) AS mos_pct, f.snapshot_score AS score,
               l.ward, l.property_type, l.road_tier, l.has_so,
               ROUND(l.area_m2, 0) AS area_m2,
               ROUND(l.price_ty, 2) AS price_ty,
               ROUND(l.price_per_m2, 1) AS price_per_m2,
               SUBSTR(l.title, 1, 100) AS title_snippet
          FROM signal_feedback f
          JOIN listings l ON l.id = f.listing_id
         WHERE f.verdict IN ('bad', 'spam', 'sold')
         ORDER BY f.created_at DESC
         LIMIT 50
    """).fetchall()

    if not rows:
        logger.info("Feedback learner: no bad/spam/sold feedback yet")
        return 0

    feedback_data = [dict(r) for r in rows]
    logger.info(f"Calling Groq with {len(feedback_data)} feedback rows...")
    rules = _call_groq(feedback_data)

    if not rules:
        logger.warning("Groq returned no rules")
        return 0

    saved = 0
    for r in rules:
        text = (r.get("text") or "").strip()
        sql = (r.get("sql") or "").strip()
        conf = float(r.get("conf") or 0.0)
        n = int(r.get("n") or 0)

        if not text or not sql:
            continue
        if conf < 0.3 or n < 3:
            logger.info(f"Skip low-confidence rule (conf={conf}, n={n}): {text}")
            continue
        if not _validate_sql(conn, sql):
            continue

        # Skip duplicate rules (same SQL)
        existing = conn.execute(
            "SELECT id FROM feedback_rules WHERE rule_sql = ?", (sql,)
        ).fetchone()
        if existing:
            logger.info(f"Skip duplicate rule SQL: {sql}")
            continue

        conn.execute("""
            INSERT INTO feedback_rules (rule_text, rule_sql, confidence, sample_size)
            VALUES (?, ?, ?, ?)
        """, (text, sql, conf, n))
        saved += 1
        logger.info(f"Saved rule (conf={conf}, n={n}): {text} → {sql}")

    conn.commit()
    logger.info(f"Feedback learner done: {saved}/{len(rules)} rules saved")
    return saved


if __name__ == "__main__":
    # Quick smoke (cần ≥1 feedback bad trong DB)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    from config.database_sqlite import get_conn
    with get_conn() as c:
        n = run_learner(c, min_new=1, force=True)
        print(f"Saved {n} rules")
