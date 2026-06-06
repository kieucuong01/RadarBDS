"""Helpers for data-backed advisory memo context.

The memo itself is still authored by the agent and stored append-only in
ai_deal_review. This module only prepares the valuation dossier and admin
explanation so the writing is grounded in system data and appraisal principles.
"""

from __future__ import annotations

import json
from typing import Any


def _row_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row.items())
    except Exception:
        pass
    keys = getattr(row, "keys", lambda: [])()
    return {key: row[key] for key in keys}


def _get(row: dict[str, Any], key: str, default: Any = None) -> Any:
    return row.get(key, default)


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 2) -> float | None:
    n = _num(value)
    if n is None:
        return None
    rounded = round(n, digits)
    if abs(rounded - int(rounded)) < 10 ** (-digits):
        return float(int(rounded))
    return rounded


def _fmt_num(value: Any, suffix: str = "", digits: int = 1) -> str:
    n = _num(value)
    if n is None:
        return "NULL"
    if abs(n - round(n)) < 0.05:
        text = str(int(round(n)))
    else:
        text = f"{n:.{digits}f}".rstrip("0").rstrip(".")
    return f"{text}{suffix}"


def _flag_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, list):
        return [str(x).strip() for x in parsed if str(x).strip()]
    for sep in (";", "|", ","):
        if sep in text:
            return [part.strip() for part in text.split(sep) if part.strip()]
    return [text]


def _text(row: dict[str, Any]) -> str:
    return " ".join(
        str(_get(row, key) or "")
        for key in ("title", "description", "road_type", "property_type", "ward")
    ).lower()


def _sample_confidence(sample_size: Any) -> str:
    n = int(_num(sample_size) or 0)
    if n >= 35:
        return "tot"
    if n >= 20:
        return "tam_du"
    if n >= 10:
        return "mong"
    return "rat_mong"


def _use_case_hints(row: dict[str, Any]) -> list[str]:
    text = _text(row)
    hints: list[str] = []
    if any(term in text for term in ("cho thuê", "cho thue", "phòng trọ", "phong tro", "thu nhập", "thu nhap")):
        hints.append("cho thue")
    road_tier = _num(_get(row, "road_tier"))
    road_type = str(_get(row, "road_type") or "").lower()
    if road_tier is not None and road_tier <= 1:
        hints.append("thanh khoan duong tot")
    elif "xe" in road_type:
        hints.append("co the vao xe")
    area = _num(_get(row, "area_m2"))
    if area and area >= 150:
        hints.append("giu dai han hoac chia tach neu phap ly cho phep")
    frontage = _num(_get(row, "frontage_m"))
    if frontage and frontage >= 5:
        hints.append("mat ngang de khai thac hon")
    return hints


def _missing_info(row: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key, label in (
        ("ward", "thieu_phuong"),
        ("property_type", "thieu_loai_tai_san"),
        ("price_ty", "thieu_gia"),
        ("area_m2", "thieu_dien_tich"),
        ("road_tier", "thieu_cap_duong"),
    ):
        if _get(row, key) in (None, "", 0):
            missing.append(label)
    return missing


def _risk_context(row: dict[str, Any], price_history: list[dict] | None, lot_history: list[dict] | None) -> dict[str, Any]:
    flags = _flag_list(_get(row, "source_quality_flags")) + _flag_list(_get(row, "legal_flags"))
    focus: list[str] = []

    if _get(row, "source_quality_recheck"):
        flags.append("can_kiem_tra_chat_luong_nguon")
        focus.append("doi_chieu_lai_du_lieu_nguon")
    if (_get(row, "legal_status") or "unverified") == "unverified":
        focus.append("phap_ly_chua_xac_minh")
    if _get(row, "has_so") in (0, False):
        flags.append("chua_ro_so")
        focus.append("xac_minh_so_va_tho_cu")
    if _sample_confidence(_get(row, "n_segment")) in ("mong", "rat_mong"):
        flags.append("mau_so_sanh_mong")
    if _get(row, "suspicious_bait"):
        flags.append("nghi_gia_moi")
        focus.append("xac_nhan_gia_chot")
    if _get(row, "price_dropped"):
        flags.append("lich_su_giam_gia")
        focus.append("hoi_ly_do_giam_gia")
    if _get(row, "road_tier") in (None, "", 0) or "hem" in str(_get(row, "road_type") or "").lower():
        focus.append("kiem_tra_duong_thuc_te")
    if price_history and len(price_history) > 1:
        focus.append("doi_chieu_lich_su_gia")
    if lot_history and len(lot_history) > 1:
        focus.append("doi_chieu_lich_su_lo")

    deduped_flags = list(dict.fromkeys(flag for flag in flags if flag))
    deduped_focus = list(dict.fromkeys(item for item in focus if item))
    return {
        "flags": deduped_flags,
        "missing_info": _missing_info(row),
        "verification_focus": deduped_focus,
    }


def _action_pricing(row: dict[str, Any], risk_context: dict[str, Any]) -> dict[str, Any]:
    asking_ty = _num(_get(row, "price_ty"))
    area = _num(_get(row, "area_m2"))
    fair_ppm2 = _num(_get(row, "fair_ppm2"))
    mos = _num(_get(row, "mos_pct")) or 0.0
    fair_ty = fair_ppm2 * area / 1000 if fair_ppm2 and area else None
    high_risk = bool(risk_context["flags"] or risk_context["missing_info"] or risk_context["verification_focus"])

    view_ty = asking_ty
    if fair_ty and (mos < 15 or high_risk):
        view_ty = min(v for v in (asking_ty, fair_ty * 0.9) if v is not None)

    risk_factor = 0.78 if high_risk else 0.85
    bid_ty = None
    if fair_ty:
        bid_ty = fair_ty * risk_factor
        if asking_ty:
            bid_ty = min(bid_ty, asking_ty * (0.95 if high_risk else 1.0))

    walk_away_parts = [
        "bỏ qua nếu không đối chiếu được đúng vị trí, đường và pháp lý",
    ]
    if bid_ty:
        walk_away_parts.append(f"không nên đuổi theo nếu giá chốt vượt quanh {_fmt_num(bid_ty, ' tỷ', 2)} khi rủi ro vẫn còn")

    questions = [
        "Xin anh/chị gửi ảnh sổ hoặc giấy tờ thể hiện diện tích và phần thổ cư.",
        "Vị trí đúng lô nào, đường trước đất rộng thực tế bao nhiêu và xe hơi vào được không?",
        "Giá hiện tại có phải giá chốt không, lý do giảm giá/đăng lại là gì?",
    ]
    if "cho thue" in _use_case_hints(row):
        questions.append("Hợp đồng thuê hiện tại còn bao lâu, tiền thuê thực nhận mỗi tháng là bao nhiêu?")
    if _get(row, "source_quality_recheck"):
        questions.append("Xác nhận lại giá, diện tích và vị trí vì hệ thống có cờ cần kiểm tra nguồn.")

    return {
        "gia_rao_hien_tai_ty": _round(asking_ty, 2),
        "gia_he_thong_tham_chieu_ty": _round(fair_ty, 2),
        "gia_nen_di_xem_ty": _round(view_ty, 2),
        "gia_nen_tra_khi_con_rui_ro_ty": _round(bid_ty, 2),
        "dieu_kien_bo_qua": "; ".join(walk_away_parts),
        "due_diligence_questions": questions,
    }


def build_memo_dossier(
    row: Any,
    price_history: list[dict] | None = None,
    lot_history: list[dict] | None = None,
) -> dict[str, Any]:
    """Return structured context for a human/agent-authored investment memo."""
    data = _row_dict(row)
    area = _num(_get(data, "area_m2"))
    fair_ppm2 = _num(_get(data, "fair_ppm2"))
    fair_ty = fair_ppm2 * area / 1000 if fair_ppm2 and area else None
    risks = _risk_context(data, price_history, lot_history)

    return {
        "valuation_principles": {
            "primary_method": "so_sanh_thi_truong",
            "primary_method_note": "So sánh thị trường là trục chính: định giá theo lô cùng phường/khu, loại tài sản, diện tích, đường và đặc điểm sử dụng gần nhất.",
            "secondary_checks": [
                "dong_tien_khi_co_khai_thac",
                "chi_phi_thay_the_chi_la_kiem_tra_phu",
                "gia_tri_su_dung_tot_nhat",
            ],
            "reconciliation_rule": "Nếu dữ liệu mẫu mỏng, nguồn có cờ, hoặc pháp lý/vị trí chưa rõ thì phải hạ độ tin cậy và đòi biên an toàn lớn hơn.",
        },
        "price": {
            "asking_price_ty": _round(_get(data, "price_ty"), 2),
            "asking_ppm2": _round(_get(data, "actual_ppm2") or _get(data, "price_per_m2"), 1),
            "reference_ppm2": _round(fair_ppm2, 1),
            "reference_total_ty": _round(fair_ty, 2),
            "safety_margin_pct": _round(_get(data, "mos_pct"), 1),
            "first_price_ty": _round(_get(data, "price_first_ty"), 2),
            "price_drop_pct": _round(_get(data, "price_drop_pct"), 1),
            "price_dropped": bool(_get(data, "price_dropped")),
        },
        "asset": {
            "ward": _get(data, "ward"),
            "property_type": _get(data, "property_type"),
            "area_m2": _round(area, 1),
            "frontage_m": _round(_get(data, "frontage_m"), 1),
            "depth_m": _round(_get(data, "depth_m"), 1),
            "road_tier": _get(data, "road_tier"),
            "road_type": _get(data, "road_type"),
            "tho_cu_m2": _round(_get(data, "tho_cu_m2"), 1),
            "tho_cu_ratio": _round(_get(data, "tho_cu_ratio"), 2),
            "has_so": bool(_get(data, "has_so", 0)),
            "is_hot": bool(_get(data, "is_hot")),
            "use_case_hints": _use_case_hints(data),
        },
        "market": {
            "segment": _get(data, "segment"),
            "comparison_group": "phuong_loai_tai_san_duong_dien_tich",
            "sample_size": int(_num(_get(data, "n_segment")) or 0),
            "sample_confidence": _sample_confidence(_get(data, "n_segment")),
            "source_quality_flags": _flag_list(_get(data, "source_quality_flags")),
            "source_quality_recheck": bool(_get(data, "source_quality_recheck")),
            "legal_status": _get(data, "legal_status") or "unverified",
            "trust_tier": _get(data, "trust_tier") or "candidate_signal",
            "trust_score": _get(data, "trust_score") or 0,
        },
        "history": {
            "price_history": price_history or [],
            "lot_history": lot_history or [],
            "price_history_count": len(price_history or []),
            "lot_history_count": len(lot_history or []),
        },
        "risks": risks,
        "action_pricing": _action_pricing(data, risks),
    }


def build_admin_valuation_workflow_markdown(row: Any) -> str:
    data = _row_dict(row)
    dossier = build_memo_dossier(data)
    price = dossier["price"]
    asset = dossier["asset"]
    market = dossier["market"]
    action = dossier["action_pricing"]

    signal_gate = "qua" if _get(data, "is_signal") else "không qua"
    dropped = "có" if _get(data, "price_dropped") else "không"
    hot = "có" if _get(data, "is_hot") else "không"
    recheck = "có" if market["source_quality_recheck"] else "không"
    quality_flags = ", ".join(market["source_quality_flags"]) or "không có"

    return "\n".join([
        "### Luồng định giá kỹ thuật cho quản trị",
        "",
        "1. Nạp dữ liệu nguồn: crawler/* lưu dữ liệu gốc vào raw_listings; listing này đang có "
        f"nguồn={_get(data, 'source')}, mã tin={_get(data, 'id')}.",
        "2. Chuẩn hóa và trích xuất: cleansing/normalizer.py và cleansing/feature_extractor.py chuẩn hóa "
        "giá, diện tích, giá/m2, phường, loại tài sản, cấp đường, thổ cư, từ khóa nóng và cờ pháp lý/chất lượng nguồn.",
        "3. Gộp tin trùng và lịch sử: cleansing/dedup.py gom tin đăng lại/cùng lô nếu đủ điều kiện; "
        "cờ giảm giá được lấy từ lịch sử giá đáng tin.",
        "4. Định giá: analytics/valuation.py chọn nhóm so sánh theo phường/khu, loại tài sản, cấp đường, diện tích "
        "và các đặc điểm tài sản; kết quả được lưu thành snapshot trong valuation_results.",
        "5. Cổng hiển thị: services.signal_quality.actionable_signal_sql() chỉ cho tín hiệu mới nhất ra UI khi không bị "
        "ẩn, chặn, trùng nghiêm trọng hoặc cờ chất lượng nguồn cần kiểm tra lại.",
        "",
        "### Cơ sở định giá chuẩn tắc",
        "",
        "- so sánh thị trường là trục chính: dùng các lô so sánh gần nhất về khu vực, loại tài sản, diện tích, đường và pháp lý để suy ra giá tham chiếu/m2.",
        "- dòng tiền chỉ là lớp kiểm tra phụ khi tin có nhà cho thuê, phòng trọ, mặt bằng hoặc dòng thu nhập rõ; không dùng để thổi giá đất nền trống.",
        "- chi phí/thay thế chỉ dùng như kiểm tra phụ với tài sản có công trình; với đất/nhà phố thanh khoản, thị trường thực tế vẫn nặng hơn.",
        "- giá trị sử dụng tốt nhất là lớp kiểm tra cuối: memo phải tự hỏi lô này đáng giá nhất khi ở thật, cho thuê, chia tách, giữ dài hạn hay kinh doanh.",
        "- Khi mẫu so sánh mỏng, nguồn có cờ hoặc pháp lý/vị trí chưa xác minh, kết luận phải hạ độ tin cậy và yêu cầu biên an toàn lớn hơn.",
        "",
        "### Ảnh chụp định giá hiện tại",
        "",
        f"- phường={asset['ward'] or 'NULL'}, loại tài sản={asset['property_type'] or 'NULL'}, cấp đường={asset['road_tier']}",
        f"- giá rao={_fmt_num(price['asking_price_ty'], ' tỷ')}, diện tích={_fmt_num(asset['area_m2'], ' m2')}, "
        f"giá rao/m2={_fmt_num(price['asking_ppm2'], ' tr/m2')}",
        f"- giá tham chiếu/m2={_fmt_num(price['reference_ppm2'], ' tr/m2')}, tổng giá trị tham chiếu={_fmt_num(price['reference_total_ty'], ' tỷ', 2)}, "
        f"biên an toàn={_fmt_num(price['safety_margin_pct'], '%')}",
        f"- điểm tín hiệu={_get(data, 'signal_score') or 0}, số mẫu so sánh={market['sample_size']}, độ chắc mẫu={market['sample_confidence']}, qua cổng tín hiệu={signal_gate}",
        f"- có sổ={asset['has_so']}, thổ cư={_fmt_num(asset['tho_cu_m2'], ' m2')}, tin nóng={hot}, có giảm giá={dropped}, mức giảm={_fmt_num(price['price_drop_pct'], '%')}",
        f"- cần kiểm tra chất lượng nguồn={recheck}, cờ chất lượng nguồn={quality_flags}, "
        f"tầng tin cậy={market['trust_tier']}, điểm tin cậy={market['trust_score']}, trạng thái pháp lý={market['legal_status']}",
        "",
        "### Mức giá hành động",
        "",
        "mức giá hành động dưới đây là neo tham khảo để admin/agent viết memo, không phải khuyến nghị đặt cọc tự động.",
        f"- Giá rao hiện tại: {_fmt_num(action['gia_rao_hien_tai_ty'], ' tỷ', 2)}.",
        f"- Giá hệ thống cho là hợp lý: {_fmt_num(action['gia_he_thong_tham_chieu_ty'], ' tỷ', 2)}.",
        f"- Giá nên đi xem: {_fmt_num(action['gia_nen_di_xem_ty'], ' tỷ', 2)}.",
        f"- Giá nên trả nếu còn rủi ro: {_fmt_num(action['gia_nen_tra_khi_con_rui_ro_ty'], ' tỷ', 2)}.",
        f"- Điều kiện bỏ qua: {action['dieu_kien_bo_qua']}.",
    ])
