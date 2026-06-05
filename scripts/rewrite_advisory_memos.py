"""Rewrite existing advisory memos into a concise investor-facing style.

This is an append-only maintenance tool. It reads the latest memo per listing
from ai_deal_review and inserts a new Claude-authored memo with a distinct
model marker. It never writes ai_training_feedback.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import get_conn
from db.schema import init_schema
from services.signal_quality import LATEST_VALUATION_CTE


DEFAULT_MODEL = "claude-code-advisory-rewrite"


def _num(value: Any, digits: int = 1) -> str | None:
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(n - round(n)) < 0.05:
        return str(int(round(n)))
    return f"{n:.{digits}f}".rstrip("0").rstrip(".")


def _price_ty(value: Any) -> str:
    text = _num(value, 2)
    return f"{text} tỷ" if text is not None else "chưa rõ"


def _ppm(value: Any) -> str:
    text = _num(value, 1)
    return f"{text} triệu/m2" if text is not None else "chưa rõ"


def _pct(value: Any) -> str:
    text = _num(value, 1)
    return f"{text}%" if text is not None else "chưa rõ"


def _area(value: Any) -> str:
    text = _num(value, 1)
    return f"{text}m2" if text is not None else "chưa rõ diện tích"


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_list(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, list):
        return [str(item) for item in parsed if item]
    return [
        part.strip()
        for part in str(raw).replace(";", ",").split(",")
        if part.strip()
    ]


def _flag_vi(flag: str) -> str:
    labels = {
        "low_segment_confidence": "mẫu so sánh mỏng",
        "approximate_price_text": "giá ghi ước lượng",
        "missing_road_info": "thiếu thông tin đường",
        "missing_location_detail": "thiếu vị trí cụ thể",
        "planning_or_tho_cu_dependency": "phụ thuộc quy hoạch/thổ cư",
        "needs_location_check": "cần kiểm tra vị trí",
        "needs_map_check": "cần kiểm tra bản đồ/quy hoạch",
        "legal_unverified": "pháp lý chưa xác minh",
        "many_reposts": "đăng lại nhiều lần",
        "repost_history": "có lịch sử đăng lại",
        "high_total_price": "giá tổng cao",
        "extreme_low_ppm2": "giá/m2 thấp bất thường",
        "large_land_check": "đất diện tích lớn cần soi kỹ",
        "thin_margin": "biên an toàn mỏng",
        "parsed_price_mismatch": "giá đọc được có thể lệch",
        "needs_price_confirmation": "cần xác nhận giá chốt",
        "low_tho_cu_ratio": "tỷ lệ thổ cư thấp",
        "road_width_check": "cần kiểm tra độ rộng đường",
        "verify_tho_cu": "cần xác minh thổ cư",
        "verify_exact_lot": "cần xác minh đúng lô",
    }
    return labels.get(str(flag), str(flag).replace("_", " "))


def _property_vi(value: Any) -> str:
    labels = {
        "dat_nen": "đất nền",
        "nha_dat": "nhà đất",
        "nha_pho": "nhà phố",
        "dat_vuon": "đất vườn",
        "dat_tho_cu": "đất thổ cư",
    }
    return labels.get(str(value or "").strip(), str(value or "bất động sản").replace("_", " "))


def _road_vi(row) -> str:
    road_type = str(row["road_type"] or "").strip()
    labels = {
        "duong_nhua": "đường nhựa",
        "hem_xe_hoi": "hẻm xe hơi",
        "hem_nho": "hẻm nhỏ",
        "mat_tien": "mặt tiền",
        "unknown": "chưa rõ đường",
    }
    if road_type:
        return labels.get(road_type, road_type.replace("_", " "))
    tier = _as_int(row["road_tier"])
    if tier == 1:
        return "mặt tiền/đường lớn"
    if tier == 2:
        return "đường ô tô hoặc hẻm xe hơi"
    if tier == 3:
        return "đường nhỏ hoặc chưa rõ cấp đường"
    return "chưa rõ đường"


def _unique(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _fair_total_ty(row) -> float | None:
    if row["fair_ppm2"] is None or row["area_m2"] is None:
        return None
    return float(row["fair_ppm2"]) * float(row["area_m2"]) / 1000


def build_reasoning(row) -> str:
    ward = row["ward"] or "khu vực này"
    margin = _pct(row["mos_pct"])
    verdict = row["verdict"]
    if verdict == "cheap_real":
        return f"{ward}: có biên giá đáng chú ý, nhưng chỉ nên ưu tiên sau khi xác minh vị trí, đường và pháp lý."
    if verdict == "suspect":
        return f"{ward}: giá hoặc thông tin tin đăng có điểm cần nghi ngờ, nên kiểm chứng trước khi xem là cơ hội thật."
    if verdict == "insufficient_info":
        return f"{ward}: thiếu dữ liệu quan trọng nên chưa thể kết luận chất lượng đầu tư."
    return f"{ward}: biên an toàn khoảng {margin} chưa đủ dày để xếp là cơ hội rẻ mạnh."


def _conclusion(row) -> str:
    verdict = row["verdict"]
    if verdict == "cheap_real":
        return (
            "Nên đưa vào nhóm ưu tiên xem thực địa, nhưng chưa nên chốt chỉ từ tin đăng. "
            "Điểm đáng tiền là giá vào đang thấp hơn mốc so sánh; lợi thế này chỉ thật sự "
            "có giá trị nếu vị trí, đường và pháp lý đúng như mô tả."
        )
    if verdict == "suspect":
        return (
            "Xem đây là tin cần kiểm chứng trước, chưa phải cơ hội để ra quyết định mua. "
            "Giá có vẻ hấp dẫn nhưng rủi ro nằm ở khả năng giá mồi, sai vị trí, sai diện tích "
            "hoặc điều kiện đường/pháp lý không như tin đăng."
        )
    if verdict == "insufficient_info":
        return (
            "Chưa đủ dữ liệu để kết luận đây là thương vụ tốt. Nên giữ lại để hỏi thêm thông tin, "
            "nhưng không nên ưu tiên vốn cho đến khi rõ vị trí, pháp lý, đường vào và giá chốt."
        )
    return (
        "Không nên ưu tiên như một thương vụ rẻ mạnh. Tài sản có thể vẫn ổn để mua ở thật "
        "hoặc nắm giữ, nhưng phần chênh so với mốc tham chiếu chưa đủ dày để bù rủi ro "
        "kiểm chứng và chi phí giao dịch."
    )


def build_memo(row) -> str:
    fair_ty = _fair_total_ty(row)
    target_ty = fair_ty * 0.82 if fair_ty else None
    actual_ppm2 = row["actual_ppm2"] or row["price_per_m2"]
    samples = _as_int(row["n_segment"]) or 0
    margin = float(row["mos_pct"] or 0)
    score = _as_int(row["signal_score"]) or 0
    property_type = _property_vi(row["property_type"])
    ward = row["ward"] or "chưa rõ phường"
    road = _road_vi(row)

    flags = _unique(
        [_flag_vi(flag) for flag in _json_list(row["red_flags"])]
        + [_flag_vi(flag) for flag in _json_list(row["source_quality_flags"])]
    )

    thesis = [
        f"{property_type} tại {ward}, giá rao {_price_ty(row['price_ty'])} cho khoảng {_area(row['area_m2'])}, đường {road}.",
    ]
    if row["tho_cu_m2"]:
        thesis.append(
            f"Thổ cư tin đăng ghi khoảng {_area(row['tho_cu_m2'])}; phần còn lại cần kiểm tra mục đích sử dụng và quy hoạch."
        )
    elif row["has_so"]:
        thesis.append("Tin có tín hiệu có sổ, nhưng vẫn phải xem giấy tờ và ranh thửa trước khi đặt cọc.")
    else:
        thesis.append("Pháp lý/thổ cư chưa đủ rõ, đây là điểm có thể làm thay đổi mạnh giá trị thật.")

    if row["price_dropped"]:
        thesis.append(
            f"Có tín hiệu giảm giá khoảng {_pct(row['price_drop_pct'])}; đây là lợi thế đàm phán, nhưng cũng cần hỏi lý do chủ giảm."
        )
    elif row["source"] == "facebook":
        thesis.append(
            "Nguồn Facebook giúp bắt hàng nhanh, đổi lại phải xác minh kỹ giá thật, đúng lô và người đăng có quyền bán hay chỉ là môi giới đăng lại."
        )
    else:
        thesis.append("Nguồn tin cần đối chiếu với thực địa và pháp lý, không nên chỉ dựa vào giá rao.")

    valuation = [
        f"Giá rao khoảng {_ppm(actual_ppm2)}; mốc tham chiếu phù hợp đang khoảng {_ppm(row['fair_ppm2'])}.",
    ]
    if fair_ty is not None:
        valuation.append(
            f"Quy ra toàn thửa, mốc tham chiếu khoảng {_price_ty(fair_ty)}; biên an toàn hiện khoảng {_pct(row['mos_pct'])}."
        )
    else:
        valuation.append(
            f"Biên an toàn hiện khoảng {_pct(row['mos_pct'])}, nhưng thiếu dữ liệu để quy đổi toàn thửa chắc chắn."
        )
    if samples < 10:
        valuation.append(
            f"Chỉ có khoảng {samples} mẫu so sánh nên độ chắc chưa cao; cần xem thực địa trước khi tin con số định giá."
        )
    elif margin < 15:
        valuation.append(
            "Biên này khá mỏng với nhà đầu tư; chỉ đáng theo nếu có thêm lợi thế như vị trí đẹp, dòng tiền, hoặc thương lượng giảm tiếp."
        )
    else:
        valuation.append(
            "Biên giá đủ để kiểm tra nghiêm túc, nhưng chưa thay thế được bước soi quy hoạch, đường và pháp lý."
        )

    checks = [
        "Xin vị trí chính xác để đối chiếu quy hoạch, đường vào và khoảng cách tới trục chính.",
        "Xem sổ, thổ cư, ranh thửa và lối đi thực tế; không đặt cọc nếu chỉ nghe mô tả miệng.",
        "Xác nhận giá chốt, phí sang tên và có phát sinh môi giới/chênh lệch ngoài hợp đồng không.",
    ]
    if flags:
        checks.append("Lưu ý thêm: " + "; ".join(flags[:4]) + ".")
    else:
        checks.append("So lịch sử đăng lại và giá cũ để biết chủ thật sự cần bán hay chỉ thử giá.")

    if target_ty is None:
        action = "Ưu tiên gọi hỏi dữ liệu còn thiếu trước; nếu người bán không cung cấp được vị trí/sổ/giá chốt rõ ràng thì bỏ qua."
    elif row["verdict"] == "cheap_real":
        action = (
            f"Nếu kiểm tra đúng, có thể hẹn xem sớm và neo giá mua quanh {_price_ty(target_ty)} "
            "để giữ biên an toàn cho nhà đầu tư."
        )
    elif row["verdict"] == "not_cheap":
        action = (
            f"Chỉ nên quay lại nếu thương lượng được về quanh {_price_ty(target_ty)} "
            "hoặc có lợi thế thực địa rõ hơn số liệu đang thể hiện."
        )
    else:
        action = (
            f"Trước khi đi xem, hỏi đủ thông tin; nếu dữ liệu đúng thì giá mua hợp lý nên thấp hơn đáng kể mốc {_price_ty(fair_ty)}."
        )

    return "\n".join(
        [
            "# Ghi chú cố vấn",
            "",
            "## Kết luận",
            _conclusion(row),
            "",
            "## Luận điểm đầu tư",
            *[f"- {item}" for item in thesis],
            "",
            "## Định giá dễ hiểu",
            *[f"- {item}" for item in valuation],
            "",
            "## Trước khi đặt cọc",
            *[f"- {item}" for item in checks],
            "",
            "## Cách xử lý",
            f"- {action}",
            f"- Điểm ưu tiên hiện tại: {score}; dùng điểm này để chọn tin đi kiểm tra trước, không dùng thay quyết định mua.",
        ]
    )


def fetch_rows(limit: int | None, model: str):
    sql = f"""
        WITH {LATEST_VALUATION_CTE}, latest_memo AS (
            SELECT r.*
              FROM ai_deal_review r
             WHERE NULLIF(TRIM(COALESCE(r.memo_markdown,'')), '') IS NOT NULL
               AND r.id = (SELECT id FROM ai_deal_review x
                            WHERE x.listing_id = r.listing_id
                              AND NULLIF(TRIM(COALESCE(x.memo_markdown,'')), '') IS NOT NULL
                            ORDER BY x.created_at DESC, x.id DESC LIMIT 1)
        )
        SELECT r.id AS review_id, r.listing_id, r.verdict, r.confidence,
               r.red_flags, r.needs_map_check,
               l.title, l.source, l.ward, l.property_type, l.price_ty,
               l.area_m2, l.price_per_m2, l.frontage_m, l.depth_m,
               l.road_tier, l.road_type, l.has_so, l.tho_cu_m2,
               l.price_dropped, l.price_drop_pct,
               v.fair_ppm2, v.actual_ppm2, v.mos_pct, v.signal_score,
               v.n_segment, COALESCE(v.source_quality_flags, '') AS source_quality_flags
          FROM latest_memo r
          JOIN listings l ON l.id = r.listing_id
          LEFT JOIN latest_valuation v ON v.listing_id = l.id
         WHERE COALESCE(r.model, '') <> ?
         ORDER BY r.id DESC
    """
    params: list[Any] = [model]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    with get_conn() as conn:
        return conn.execute(sql, params).fetchall()


def apply_rows(rows, model: str) -> None:
    with get_conn() as conn:
        for row in rows:
            memo = build_memo(row)
            conn.execute(
                """
                INSERT INTO ai_deal_review
                  (listing_id, actor, verdict, confidence, reasoning,
                   red_flags, memo_markdown, needs_map_check, model, updated_at)
                VALUES (?, 'claude', ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    row["listing_id"],
                    row["verdict"],
                    row["confidence"],
                    build_reasoning(row),
                    row["red_flags"],
                    memo,
                    row["needs_map_check"],
                    model,
                ),
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Rewrite advisory memos into concise Vietnamese notes.")
    parser.add_argument("--limit", type=int, help="Limit number of latest memos to rewrite.")
    parser.add_argument("--apply", action="store_true", help="Insert rewritten memos. Without this, dry-run only.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model marker for inserted rows.")
    parser.add_argument("--preview", type=int, default=3, help="Number of dry-run examples to print.")
    args = parser.parse_args()

    init_schema()
    rows = fetch_rows(args.limit, args.model)
    print(f"candidate_memos={len(rows)} model={args.model} apply={args.apply}")
    for row in rows[: max(args.preview, 0)]:
        print(f"\n--- listing={row['listing_id']} review={row['review_id']} verdict={row['verdict']}")
        print(build_memo(row))
        print("reasoning:", build_reasoning(row))
    if args.apply:
        apply_rows(rows, args.model)
        print(f"inserted={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
