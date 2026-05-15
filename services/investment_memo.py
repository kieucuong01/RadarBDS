"""Rule-based valuation context memo builder for listing detail views."""
from __future__ import annotations

import math
import sqlite3
import statistics
from typing import Any


VERDICT_META = {
    "below_fair": {
        "label": "Thấp hơn fair value",
        "tone": "good",
        "summary": "Giá chào đang thấp hơn fair value theo mô hình hiện tại; vẫn cần kiểm tra các giả định định giá.",
    },
    "near_fair": {
        "label": "Gần fair value",
        "tone": "muted",
        "summary": "Giá chào đang gần fair value theo mô hình hiện tại; sai số dữ liệu có thể làm thay đổi kết luận.",
    },
    "above_fair": {
        "label": "Cao hơn fair value",
        "tone": "watch",
        "summary": "Giá chào đang cao hơn fair value theo mô hình hiện tại; cần xem lại giả định hoặc điểm cộng riêng của lô.",
    },
    "data_limited": {
        "label": "Dữ liệu hạn chế",
        "tone": "watch",
        "summary": "Kết quả định giá phụ thuộc vào một số thông tin còn thiếu hoặc mẫu so sánh còn mỏng.",
    },
    "risk_flagged": {
        "label": "Cảnh báo rủi ro",
        "tone": "danger",
        "summary": "Tin rao hoặc dữ liệu định giá có dấu hiệu bất thường, cần xác minh trước khi sử dụng để ra quyết định.",
    },
    "needs_review": {
        "label": "Thiếu dữ liệu",
        "tone": "muted",
        "summary": "Chưa đủ giá, diện tích hoặc fair value để giải thích định giá một cách đáng tin.",
    },
}


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        n = float(value)
        if not math.isfinite(n):
            return None
        return n
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _pct(value: float | None) -> float | None:
    return _round(value, 1)


def _safe_bool(value: Any) -> bool:
    return bool(value) if value is not None else False


def _fetch_listing(conn: sqlite3.Connection, listing_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT l.id, l.title, l.description, l.source, l.url, l.price_ty,
               l.area_m2, l.price_per_m2, l.ward, l.property_type, l.road_tier,
               l.road_type, l.has_so, l.is_hot, l.price_dropped,
               l.price_drop_pct, l.price_first_ty, l.suspicious_bait,
               l.duplicate_of_id, l.possibly_duplicate, l.posted_at,
               l.crawled_at, l.updated_at,
               v.id AS valuation_id, v.fair_ppm2, v.actual_ppm2, v.mos_pct,
               v.is_signal, v.n_segment, v.signal_score, v.is_outlier,
               v.outlier_direction, v.outlier_sigma
          FROM listings l
          LEFT JOIN valuation_results v ON v.id = (
                SELECT vv.id
                  FROM valuation_results vv
                 WHERE vv.listing_id = l.id
                 ORDER BY vv.computed_at DESC, vv.id DESC
                 LIMIT 1
          )
         WHERE l.id = ?
           AND COALESCE(l.is_blacklisted, 0) = 0
           AND COALESCE(l.review_hidden, 0) = 0
        """,
        (listing_id,),
    ).fetchone()


def _ranked_comps(conn: sqlite3.Connection, listing: sqlite3.Row, tier: str) -> list[dict[str, Any]]:
    ward = listing["ward"]
    area = _num(listing["area_m2"]) or 0
    prop_type = listing["property_type"]
    road_tier = listing["road_tier"]
    curr_ppm2 = _num(listing["price_per_m2"]) or _num(listing["actual_ppm2"]) or 0
    if not ward or not area:
        return []

    area_min = max(1, area * 0.75)
    area_max = area * 1.30
    ppm2_min = curr_ppm2 * 0.55 if curr_ppm2 else 0
    ppm2_max = curr_ppm2 * 1.45 if curr_ppm2 else 999999

    rows = conn.execute(
        """
        SELECT id, title, url, price_ty, area_m2, price_per_m2, property_type,
               road_tier, COALESCE(posted_at, crawled_at) AS dt
          FROM listings
         WHERE ward = ?
           AND id != ?
           AND price_ty > 0
           AND probably_sold = 0
           AND COALESCE(is_blacklisted, 0) = 0
           AND COALESCE(review_hidden, 0) = 0
           AND possibly_duplicate = 0
           AND (? IS NULL OR property_type = ?)
           AND area_m2 BETWEEN ? AND ?
           AND (? <= 0 OR COALESCE(price_per_m2, 0) BETWEEN ? AND ?)
           AND (? IS NULL OR road_tier IS NULL OR ABS(road_tier - ?) <= 1)
         ORDER BY ABS(area_m2 - ?) ASC,
                  ABS(COALESCE(price_per_m2, 0) - ?) ASC,
                  COALESCE(posted_at, crawled_at) DESC
         LIMIT 20
        """,
        (
            ward,
            listing["id"],
            prop_type,
            prop_type,
            area_min,
            area_max,
            curr_ppm2,
            ppm2_min,
            ppm2_max,
            road_tier,
            road_tier,
            area,
            curr_ppm2,
        ),
    ).fetchall()

    ranked: list[dict[str, Any]] = []
    for row in rows:
        comp_area = _num(row["area_m2"]) or 0
        comp_ppm2 = _num(row["price_per_m2"]) or 0
        area_gap_pct = abs(comp_area - area) / area if area and comp_area else 0.0
        ppm2_gap_pct = abs(comp_ppm2 - curr_ppm2) / curr_ppm2 if curr_ppm2 and comp_ppm2 else 0.0
        road_gap = 0
        if road_tier is not None and row["road_tier"] is not None:
            road_gap = abs(row["road_tier"] - road_tier)
        score = 100.0
        score -= min(45.0, area_gap_pct * 100 * 0.55)
        score -= min(30.0, ppm2_gap_pct * 100 * 0.30)
        score -= min(12.0, road_gap * 6.0)
        score = round(max(0.0, min(99.0, score)), 1)
        ranked.append(
            {
                "id": row["id"],
                "title": (row["title"] or "")[:90],
                "url": (row["url"] or "") if tier == "admin" else "",
                "detail_url": f"/listing/{row['id']}",
                "price_ty": _round(_num(row["price_ty"]), 2),
                "area_m2": _round(_num(row["area_m2"]), 1),
                "price_per_m2": _round(_num(row["price_per_m2"]), 1),
                "property_type": row["property_type"],
                "date": (row["dt"] or "")[:10],
                "area_gap_pct": _pct(area_gap_pct * 100),
                "match_score": score,
            }
        )

    ranked.sort(key=lambda x: (-x["match_score"], x["area_gap_pct"] or 0, -(x["price_per_m2"] or 0)))
    return ranked


def _price_history(conn: sqlite3.Connection, listing_id: int, current_price: float | None) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT recorded_at, price_ty
          FROM price_history
         WHERE listing_id = ?
         ORDER BY recorded_at ASC, id ASC
        """,
        (listing_id,),
    ).fetchall()
    history: list[dict[str, Any]] = []
    last_price = None
    for row in rows:
        price = _num(row["price_ty"])
        if price is None:
            continue
        if last_price is not None and abs(price - last_price) < 0.0001:
            continue
        history.append({"date": (row["recorded_at"] or "")[:10], "price_ty": _round(price, 2)})
        last_price = price
    if current_price is not None and (last_price is None or abs(current_price - last_price) >= 0.0001):
        history.append({"date": "", "price_ty": _round(current_price, 2)})
    return history


def _lot_stats(conn: sqlite3.Connection, listing: sqlite3.Row) -> dict[str, Any]:
    canonical_id = listing["duplicate_of_id"] or listing["id"]
    rows = conn.execute(
        """
        SELECT id, price_ty, price_dropped, price_drop_pct,
               COALESCE(posted_at, crawled_at, updated_at) AS dt
          FROM listings
         WHERE id = ? OR duplicate_of_id = ?
         ORDER BY COALESCE(posted_at, crawled_at, updated_at) ASC, id ASC
        """,
        (canonical_id, canonical_id),
    ).fetchall()
    prices = [_num(row["price_ty"]) for row in rows if _num(row["price_ty"]) is not None]
    first_price = prices[0] if prices else _num(listing["price_first_ty"]) or _num(listing["price_ty"])
    current_price = _num(listing["price_ty"])
    inferred_drop_pct = None
    if first_price and current_price and abs(first_price - current_price) >= 0.0001:
        inferred_drop_pct = ((first_price - current_price) / first_price) * 100
    return {
        "same_lot_count": len(rows),
        "repost_count": max(0, len(rows) - 1),
        "first_seen_date": (rows[0]["dt"] or "")[:10] if rows else None,
        "last_seen_date": (rows[-1]["dt"] or "")[:10] if rows else None,
        "first_price_ty": _round(first_price, 2),
        "current_price_ty": _round(current_price, 2),
        "drop_pct": _pct(_num(listing["price_drop_pct"]) if listing["price_drop_pct"] is not None else inferred_drop_pct),
        "price_dropped": _safe_bool(listing["price_dropped"]),
        "suspicious_bait": _safe_bool(listing["suspicious_bait"]),
    }


def _comps_summary(comps: list[dict[str, Any]]) -> dict[str, Any]:
    nearest = comps[:6]
    ppm2_values = [c["price_per_m2"] for c in nearest if c.get("price_per_m2") is not None]
    return {
        "count": len(nearest),
        "median_ppm2": _round(statistics.median(ppm2_values), 1) if ppm2_values else None,
        "low_ppm2": _round(min(ppm2_values), 1) if ppm2_values else None,
        "high_ppm2": _round(max(ppm2_values), 1) if ppm2_values else None,
        "top": comps[:3],
    }


def _data_quality_warnings_and_risks(listing: sqlite3.Row, comps_count: int) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    risks: list[str] = []

    n_segment = int(listing["n_segment"] or 0)
    if n_segment < 15:
        warnings.append("Mẫu định giá trong segment còn mỏng, fair value có thể kém ổn định.")
        risks.append("Mẫu định giá mỏng làm tăng sai số fair value.")

    if not listing["road_tier"]:
        warnings.append("Cấp đường chưa rõ; cần kiểm tra thực địa và lộ giới.")
        risks.append("Cấp đường chưa rõ nên fair value có thể bị lệch.")

    if not _safe_bool(listing["has_so"]):
        warnings.append("Pháp lý/sổ hồng chưa chắc chắn; cần kiểm tra giấy tờ gốc.")
        risks.append("Pháp lý chưa đủ rõ, cần kiểm tra sổ, quy hoạch và tranh chấp.")

    if comps_count < 3:
        warnings.append("Ít hơn 3 lô so sánh gần nhất; cần thêm comps cùng phường/diện tích/cấp đường.")
        risks.append("Comps mỏng, khó xác nhận giá thị trường quanh lô này.")

    if _safe_bool(listing["suspicious_bait"]):
        warnings.append("Tin bị gắn cờ suspicious bait; cần xác minh nguồn tin, giá và tình trạng lô.")
        risks.append("Tin có dấu hiệu giá mồi/quá bất thường.")

    return warnings, risks


def _valuation_metrics(listing: sqlite3.Row) -> dict[str, Any]:
    current = _num(listing["price_ty"])
    fair_ppm2 = _num(listing["fair_ppm2"])
    area = _num(listing["area_m2"])
    mos = _num(listing["mos_pct"])
    fair_total = fair_ppm2 * area / 1000 if fair_ppm2 and area else None
    return {
        "current_price_ty": _round(current, 2),
        "actual_ppm2": _round(_num(listing["actual_ppm2"]) or _num(listing["price_per_m2"]), 1),
        "fair_ppm2": _round(fair_ppm2, 1),
        "fair_total_ty": _round(fair_total, 2),
        "mos_pct": _pct(mos),
        "valuation_sample_size": int(listing["n_segment"] or 0),
    }


def _valuation_status(listing: sqlite3.Row, metrics: dict[str, Any], comps_count: int) -> str:
    if (
        listing["valuation_id"] is None
        or metrics["current_price_ty"] is None
        or metrics["fair_ppm2"] is None
        or metrics["fair_total_ty"] is None
        or metrics["mos_pct"] is None
    ):
        return "needs_review"

    mos = metrics["mos_pct"] or 0
    major_risk = _safe_bool(listing["suspicious_bait"]) or _safe_bool(listing["is_outlier"])
    unclear_data = comps_count < 3 or not listing["road_tier"] or not _safe_bool(listing["has_so"])
    thin_segment = int(listing["n_segment"] or 0) < 15
    if major_risk:
        return "risk_flagged"
    if unclear_data or thin_segment:
        return "data_limited"
    if mos > 5:
        return "below_fair"
    if mos >= -5:
        return "near_fair"
    return "above_fair"


def _valuation_signals(listing: sqlite3.Row, metrics: dict[str, Any], comps_count: int, price_context: dict[str, Any]) -> list[str]:
    items: list[str] = []
    mos = metrics.get("mos_pct")
    if mos is not None and mos > 0:
        items.append(f"Giá chào thấp hơn fair value khoảng {mos:.1f}%.")
    if price_context.get("price_dropped") and price_context.get("drop_pct") and not price_context.get("suspicious_bait"):
        items.append(f"Lịch sử ghi nhận giá giảm khoảng {price_context['drop_pct']:.1f}%, cần kiểm tra lý do giảm.")
    if comps_count >= 3:
        items.append(f"Có {comps_count} lô gần nhất để đối chiếu giá.")
    if _safe_bool(listing["has_so"]):
        items.append("Tin đang ghi nhận có sổ/pháp lý tốt hơn mặt bằng, vẫn cần kiểm tra bản gốc.")
    if listing["road_tier"]:
        items.append(f"Đã nhận diện cấp đường/lối vào: {listing['road_type'] or 'cấp ' + str(listing['road_tier'])}.")
    return items[:5]


def _valuation_explanation(listing: sqlite3.Row, metrics: dict[str, Any], comps_summary: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    area = _num(listing["area_m2"])
    fair_ppm2 = metrics.get("fair_ppm2")
    fair_total = metrics.get("fair_total_ty")
    actual_ppm2 = metrics.get("actual_ppm2")
    current = metrics.get("current_price_ty")
    mos = metrics.get("mos_pct")

    if fair_ppm2 is not None and area is not None and fair_total is not None:
        notes.append(
            f"Fair total = fair ppm2 {fair_ppm2:.1f} triệu/m2 x diện tích {area:.1f} m2 / 1000 = {fair_total:.2f} tỷ."
        )
    else:
        notes.append("Fair total chưa tính được vì thiếu fair ppm2 hoặc diện tích hợp lệ.")

    if current is not None and fair_total is not None and mos is not None:
        notes.append(
            f"Biên an toàn hiện tại phản ánh chênh lệch giữa fair total và giá chào hiện tại, đang ở mức {mos:.1f}%."
        )

    if actual_ppm2 is not None:
        notes.append(f"Giá chào quy đổi hiện tại khoảng {actual_ppm2:.1f} triệu/m2.")

    if comps_summary.get("count"):
        median = comps_summary.get("median_ppm2")
        if median is not None:
            notes.append(
                f"Comps gần nhất có median khoảng {median:.1f} triệu/m2, dùng để đối chiếu với fair ppm2 và giá chào."
            )
        else:
            notes.append(f"Có {comps_summary['count']} comps gần nhất nhưng thiếu đủ dữ liệu giá/m2 để tính median.")

    sample_size = metrics.get("valuation_sample_size") or 0
    if sample_size:
        notes.append(f"Mẫu định giá trong segment hiện có {sample_size} tin, nên độ tin cậy phụ thuộc chất lượng mẫu này.")

    return notes[:6]


def _verification_questions(listing: sqlite3.Row, price_context: dict[str, Any]) -> list[str]:
    questions = [
        "Gửi hình sổ hồng/giấy tờ gốc, tọa độ lô đất và clip đường vào để kiểm tra.",
        "Lô có dính quy hoạch, lộ giới, tranh chấp, ngập hay hạn chế xây dựng nào không?",
        "Diện tích trên sổ, diện tích thực tế và hiện trạng ranh mốc có khớp nhau không?",
    ]
    if not listing["road_tier"]:
        questions.append("Đường trước đất rộng bao nhiêu mét, xe hơi vào được không, có bị lộ giới không?")
    if not _safe_bool(listing["has_so"]):
        questions.append("Sổ riêng hay sổ chung, diện tích thực tế và thời điểm sang tên dự kiến?")
    if price_context.get("price_dropped") or price_context.get("repost_count"):
        questions.append("Vì sao lô này đang giảm giá/repost, có thay đổi gì về pháp lý, vị trí hoặc tình trạng lô không?")
    return questions[:6]


def load_investment_memo(db_path: str, listing_id: int, tier: str = "guest") -> dict[str, Any] | None:
    """Return a tier-safe investment memo for a listing, or None if missing."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        listing = _fetch_listing(conn, listing_id)
        if not listing:
            return None

        comps = _ranked_comps(conn, listing, tier)
        summary = _comps_summary(comps)
        price_context = _lot_stats(conn, listing)
        price_context["history"] = _price_history(conn, listing_id, _num(listing["price_ty"]))[-5:]

        quality_warnings, risk_items = _data_quality_warnings_and_risks(listing, summary["count"])
        metrics = _valuation_metrics(listing)
        verdict = _valuation_status(listing, metrics, summary["count"])
        meta = VERDICT_META[verdict]

        risks = list(risk_items)
        if listing["is_outlier"]:
            risks.append("Giá nằm ngoài vùng thống kê thông thường; cần kiểm tra lỗi parse hoặc yếu tố bất thường.")
        if not risks:
            risks.append("Vẫn cần kiểm tra pháp lý, quy hoạch, hiện trạng đường và khả năng sang tên.")
        questions = _verification_questions(listing, price_context)

        return {
            "listing_id": listing["id"],
            "verdict": verdict,
            "verdict_label": meta["label"],
            "verdict_tone": meta["tone"],
            "summary": meta["summary"],
            "metrics": metrics,
            "comps_summary": summary,
            "price_context": price_context,
            "valuation_explanation": _valuation_explanation(listing, metrics, summary),
            "valuation_signals": _valuation_signals(listing, metrics, summary["count"], price_context),
            "missing_info": quality_warnings[:6],
            "risk_warnings": risks[:6],
            "risks": risks[:6],
            "verification_questions": questions,
            "broker_questions": questions,
            "data_quality_warnings": quality_warnings[:6],
            "tier": tier,
        }
    finally:
        conn.close()
