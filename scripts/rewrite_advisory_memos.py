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
from services.signal_quality import LATEST_VALUATION_CTE


DEFAULT_MODEL = "claude-code-advisory-opinion-v3"


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
        "broker discount claim": "môi giới nói còn thương lượng",
        "broker_discount_claim": "môi giới nói còn thương lượng",
        "repost same price": "đăng lại cùng giá",
        "repost_same_price": "đăng lại cùng giá",
        "needs road check": "cần kiểm tra đường thực tế",
        "needs_road_check": "cần kiểm tra đường thực tế",
        "wide road claim": "tin nói đường rộng, cần đo lại thực tế",
        "wide_road_claim": "tin nói đường rộng, cần đo lại thực tế",
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
        "be_tong": "đường bê tông",
        "be tong": "đường bê tông",
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


def _cap_first(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]


def _fair_total_ty(row) -> float | None:
    if row["fair_ppm2"] is None or row["area_m2"] is None:
        return None
    return float(row["fair_ppm2"]) * float(row["area_m2"]) / 1000


def _ratio(part: Any, total: Any) -> float | None:
    if part is None or total in (None, 0):
        return None
    try:
        total_f = float(total)
        if total_f <= 0:
            return None
        return float(part) / total_f
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _text_blob(row) -> str:
    return f"{row['title'] or ''}\n{row['description'] or ''}".lower()


def _has_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def _dimension_note(row) -> str | None:
    frontage = row["frontage_m"]
    depth = row["depth_m"]
    if frontage and depth:
        try:
            f = float(frontage)
            d = float(depth)
        except (TypeError, ValueError):
            return None
        shape = f"{_num(f, 1)}x{_num(d, 1)}"
        if d / max(f, 0.1) >= 8:
            return f"Form đất {shape} khá dài và hẹp; cần xem lối vào, ranh đất và khả năng tách/thanh khoản."
        if f >= 7 and d >= 20:
            return f"Form đất {shape} có bề ngang tốt, dễ xoay phương án xây ở/khai thác hơn loại ngang nhỏ."
        return f"Form đất khoảng {shape}; nên đối chiếu lại với sổ và mốc ranh ngoài thực địa."
    return None


def _location_notes(row) -> list[str]:
    text = _text_blob(row)
    notes: list[str] = []
    if _has_any(text, ["mỹ phước tân vạn", "my phuoc tan van"]):
        notes.append("Có nhắc gần trục Mỹ Phước Tân Vạn, đây là yếu tố thanh khoản tốt nếu khoảng cách thực tế đúng.")
    if _has_any(text, ["quốc lộ 13", "ql13", "qlo 13"]):
        notes.append("Có liên hệ Quốc lộ 13; cần đo lại khoảng cách thật vì chênh vài trăm mét có thể làm khác giá.")
    if _has_any(text, ["chợ", "cho "]):
        notes.append("Có yếu tố gần chợ/khu dân cư, phù hợp nhóm mua ở thật nếu đường và pháp lý sạch.")
    if _has_any(text, ["khu công nghiệp", "kcn", "công nhân", "cong nhan"]):
        notes.append("Có câu chuyện gần khu công nghiệp hoặc tệp thuê ở, nên kiểm tra nhu cầu thuê thực tế quanh lô.")
    if _has_any(text, ["cho thuê", "phòng trọ", "dãy trọ", "nha tro", "thu nhập", "thu nhap"]):
        notes.append("Tin có yếu tố dòng tiền cho thuê/trọ; phải tách giá trị đất và giá trị công trình để tránh mua hớ phần xây dựng.")
    if _has_any(text, ["1 xẹt", "1 xet", "một xẹt", "cách", "cach"]):
        notes.append("Tin mô tả lô không nằm trực diện trục chính; nên kiểm tra đường vào thật và độ dễ bán lại.")
    if _has_any(text, ["2 lô", "2lo", "hai lô", "liền kề", "lien ke"]):
        notes.append("Có dấu hiệu nhiều lô/liền kề; cần xác nhận giá đang tính cho một lô hay toàn bộ phần rao bán.")
    return notes[:3]


def _history_notes(row) -> list[str]:
    notes: list[str] = []
    price_history_count = _as_int(row["price_history_count"]) or 0
    lot_history_count = _as_int(row["lot_history_count"]) or 0
    if row["price_dropped"]:
        notes.append(
            f"Tin có giảm giá khoảng {_pct(row['price_drop_pct'])}; đây là điểm ép giá tốt, nhưng phải hỏi vì sao chủ giảm."
        )
    elif price_history_count >= 2:
        notes.append(
            f"Có {price_history_count} mốc lịch sử giá; nên xem giá cũ để biết chủ đang giảm thật hay chỉ đổi cách đăng."
        )
    if lot_history_count >= 3:
        notes.append(
            f"Lịch sử cùng lô có {lot_history_count} lần xuất hiện, cần soi các lần đăng lại để tránh nhầm tin cũ thành cơ hội mới."
        )
    return notes


def _risk_notes(row, flags: list[str]) -> list[str]:
    notes: list[str] = []
    tho_cu_ratio = _ratio(row["tho_cu_m2"], row["area_m2"])
    if tho_cu_ratio is not None and tho_cu_ratio < 0.35:
        notes.append(
            f"Thổ cư chỉ khoảng {int(round(tho_cu_ratio * 100))}% diện tích; phần đất còn lại có thể kéo giảm giá trị sử dụng và khả năng vay."
        )
    if not row["has_so"]:
        notes.append("Chưa có tín hiệu pháp lý rõ; phải xem giấy tờ trước khi tính tới cọc.")
    if _as_int(row["n_segment"]) is not None and (_as_int(row["n_segment"]) or 0) < 10:
        notes.append(f"Mẫu so sánh chỉ khoảng {_as_int(row['n_segment']) or 0} tin, nên số định giá chỉ dùng để sàng lọc ban đầu.")
    if row["price_ty"] and row["price_ty"] >= 4:
        notes.append("Giá tổng cao; tệp mua lại hẹp hơn, cần biên an toàn dày hơn đất nhỏ tiền.")
    if flags:
        notes.append("Cờ cần lưu ý: " + "; ".join(flags[:3]) + ".")
    return _unique(notes)[:5]


def _valuation_notes(row, fair_ty: float | None, actual_ppm2: Any) -> list[str]:
    notes: list[str] = []
    fair_ppm2 = row["fair_ppm2"]
    if actual_ppm2 and fair_ppm2:
        gap_ppm2 = float(fair_ppm2) - float(actual_ppm2)
        notes.append(
            f"Giá rao khoảng {_ppm(actual_ppm2)}, thấp hơn mốc tham chiếu {_ppm(fair_ppm2)} khoảng {_ppm(gap_ppm2)}."
        )
    else:
        notes.append(f"Giá rao khoảng {_ppm(actual_ppm2)}; mốc tham chiếu hiện là {_ppm(fair_ppm2)}.")
    if fair_ty is not None and row["price_ty"] is not None:
        gap_ty = float(fair_ty) - float(row["price_ty"])
        notes.append(
            f"Quy ra toàn thửa, giá tham chiếu khoảng {_price_ty(fair_ty)}, chênh so với giá rao khoảng {_price_ty(gap_ty)}."
        )
    notes.append(f"Biên an toàn hiện khoảng {_pct(row['mos_pct'])}; điểm ưu tiên là {_as_int(row['signal_score']) or 0}.")
    samples = _as_int(row["n_segment"]) or 0
    if samples >= 50:
        notes.append(f"Có khoảng {samples} mẫu so sánh, nên mặt bằng giá khu vực tương đối đáng tham khảo.")
    elif samples >= 10:
        notes.append(f"Có khoảng {samples} mẫu so sánh, đủ để sàng lọc nhưng vẫn cần soi đúng hẻm/đường.")
    else:
        notes.append(f"Chỉ có khoảng {samples} mẫu so sánh, cần hạ độ tin cậy cho con số định giá.")
    return notes


def _action_note(row, fair_ty: float | None) -> str:
    if fair_ty is None:
        return "Gọi hỏi vị trí, sổ và giá chốt trước; nếu không có đủ dữ liệu thì không nên đi xem mất thời gian."
    target_ty = fair_ty * 0.82
    asking_ty = float(row["price_ty"]) if row["price_ty"] is not None else None
    margin = float(row["mos_pct"] or 0)
    verdict = row["verdict"]
    if verdict == "cheap_real" and margin >= 20:
        if asking_ty is not None and target_ty >= asking_ty:
            return (
                f"Giá rao đã thấp hơn mốc mua thận trọng khoảng {_price_ty(target_ty)}; nếu dữ liệu đúng, nên xem sớm "
                "và cố giữ giá mua không cao hơn giá rao, tốt nhất ép thêm bằng các điểm cần kiểm tra."
            )
        return (
            f"Có thể hẹn xem sớm; nếu vị trí/pháp lý đúng, neo thương lượng quanh {_price_ty(target_ty)} "
            "để giữ biên an toàn sau chi phí."
        )
    if verdict == "cheap_real":
        if asking_ty is not None and target_ty >= asking_ty:
            return (
                "Đáng kiểm tra, nhưng không nên trả cao hơn giá rao hiện tại; dùng điểm pháp lý, thổ cư, đường và lịch sử đăng lại để ép thêm."
            )
        return (
            f"Đáng kiểm tra, nhưng chỉ nên xuống tiền khi chốt được thấp hơn giá rao hoặc có lợi thế thực địa rõ; "
            f"mốc mua thận trọng quanh {_price_ty(target_ty)}."
        )
    if verdict == "suspect":
        return "Hỏi vị trí chính xác, ảnh sổ và giá chốt trước; nếu người bán vòng vo hoặc giá thay đổi khi hỏi sâu thì bỏ qua."
    if verdict == "insufficient_info":
        return "Ưu tiên bổ sung dữ liệu còn thiếu; chưa đủ cơ sở để đặt lịch xem nếu không có vị trí/sổ/đường rõ."
    return (
        f"Không cần đuổi theo giá hiện tại; chỉ quay lại nếu giá về quanh {_price_ty(target_ty)} "
        "hoặc phát hiện lợi thế riêng mà dữ liệu chưa phản ánh."
    )


def _advisory_stance(row, flags: list[str]) -> tuple[str, str]:
    margin = float(row["mos_pct"] or 0)
    samples = _as_int(row["n_segment"]) or 0
    price_ty = float(row["price_ty"] or 0)
    many_reposts = (_as_int(row["lot_history_count"]) or 0) >= 8
    thin_samples = samples < 10
    unclear_road = "cần kiểm tra đường thực tế" in flags or "thiếu thông tin đường" in flags or not row["road_type"]
    low_tho_cu = (_ratio(row["tho_cu_m2"], row["area_m2"]) or 1) < 0.35
    dimension = _dimension_note(row) or ""

    if row["verdict"] == "suspect":
        return (
            "Tôi xếp tin này vào nhóm nghi vấn, chưa nên xem là cơ hội đầu tư.",
            "Giá có thể tạo cảm giác rẻ, nhưng rủi ro sai giá, sai lô hoặc điều kiện đường/pháp lý đang lớn hơn lợi thế ban đầu.",
        )
    if row["verdict"] == "insufficient_info":
        return (
            "Tôi chưa cho tin này vào nhóm ưu tiên vốn.",
            "Biên giá nhìn tốt nhưng dữ liệu nền còn thiếu, nên bước đúng là lọc thông tin trước chứ chưa phải đi xem hay giữ chỗ.",
        )
    if row["verdict"] == "not_cheap":
        reasons = []
        if margin < 15:
            reasons.append("biên giá còn mỏng")
        if low_tho_cu:
            reasons.append("tỷ lệ thổ cư thấp")
        if "dài và hẹp" in dimension:
            reasons.append("form đất dài/hẹp làm thanh khoản kén hơn")
        if price_ty >= 4:
            reasons.append("giá tổng cao làm vòng thoát hàng chậm")
        reason_text = "; ".join(reasons) if reasons else "phần chênh với mặt bằng chưa đủ hấp dẫn"
        return (
            "Tôi không ưu tiên thương vụ này ở giá hiện tại.",
            f"Lý do chính: {reason_text}. Khi mua đầu tư, những điểm này làm biên lợi nhuận thực tế mỏng hơn con số định giá ban đầu.",
        )
    if margin >= 30 and not thin_samples and not unclear_road and not low_tho_cu:
        return (
            "Đây là tin đáng ưu tiên đi xem sớm.",
            "Biên giá đủ dày, dữ liệu so sánh không quá mỏng và chưa thấy điểm nghẽn lớn ngay trên tin đăng.",
        )
    if margin >= 25:
        reason = "Biên giá tốt"
        if thin_samples:
            reason += ", nhưng mẫu so sánh mỏng"
        if unclear_road:
            reason += ", đường/vị trí cần soi kỹ"
        if low_tho_cu:
            reason += ", tỷ lệ thổ cư thấp"
        if many_reposts:
            reason += ", lịch sử đăng lại nhiều"
        return (
            "Đây là tin đáng kiểm tra, nhưng không được mua theo cảm xúc rẻ.",
            f"{reason}; chỉ chuyển thành cơ hội thật nếu các điểm này qua kiểm chứng.",
        )
    return (
        "Tôi chỉ xếp tin này vào nhóm theo dõi hoặc ép giá.",
        "Biên an toàn chưa đủ rộng để chủ động xuống tiền nếu không có lợi thế riêng ngoài dữ liệu đang thấy.",
    )


def _investor_thesis(row, flags: list[str]) -> list[str]:
    notes: list[str] = []
    text = _text_blob(row)
    prop = _property_vi(row["property_type"])
    ward = row["ward"] or "khu vực này"
    road = _road_vi(row)
    dimension = _dimension_note(row)
    tho_cu_ratio = _ratio(row["tho_cu_m2"], row["area_m2"])

    notes.append(
        f"Lợi thế đầu tiên của lô này là giá vào: {prop} {_area(row['area_m2'])} tại {ward}, "
        f"giá rao {_price_ty(row['price_ty'])}, lối vào {road}."
    )
    if dimension:
        if "dài và hẹp" in dimension:
            clean_dimension = dimension.replace("Form đất ", "", 1)
            notes.append(
                f"Form đất là điểm phải cân nhắc: {clean_dimension} Loại này có thể rẻ/m2 nhưng thanh khoản không mạnh bằng lô cân đối."
            )
        elif "bề ngang tốt" in dimension:
            clean_dimension = dimension.replace("Form đất ", "", 1)
            notes.append(
                f"Form đất là điểm cộng thật: {clean_dimension} Với nhà đầu tư, bề ngang tốt giúp dễ bán lại hoặc khai thác hơn."
            )
        else:
            notes.append(dimension)

    if tho_cu_ratio is not None:
        if tho_cu_ratio < 0.35:
            notes.append(
                f"Thổ cư chỉ khoảng {int(round(tho_cu_ratio * 100))}% diện tích, nên không thể định giá như đất ở full thổ cư."
            )
        elif tho_cu_ratio >= 0.8:
            notes.append("Tỷ lệ thổ cư cao là điểm cộng, giúp câu chuyện vay/mua ở thật dễ hơn nếu sổ đúng.")
    elif row["has_so"]:
        notes.append("Có tín hiệu có sổ, nhưng chưa đủ để kết luận pháp lý sạch nếu chưa thấy sổ và ranh.")

    for location_note in _location_notes(row):
        if "Mỹ Phước Tân Vạn" in location_note or "Quốc lộ 13" in location_note:
            notes.append(location_note + " Nếu khoảng cách đúng, đây là điểm hỗ trợ thanh khoản.")
        elif "cho thuê" in location_note or "trọ" in location_note:
            notes.append(location_note + " Khi định giá, phải tách riêng giá trị dòng tiền và giá trị đất.")
        else:
            notes.append(location_note)

    if row["price_dropped"]:
        notes.append(
            f"Việc giảm giá khoảng {_pct(row['price_drop_pct'])} cho thấy có dư địa thương lượng; nhưng nếu giảm vì lỗi pháp lý/vị trí thì không nên xem là món hời."
        )
    lot_history = _as_int(row["lot_history_count"]) or 0
    if lot_history >= 10:
        notes.append(
            f"Lịch sử cùng lô xuất hiện {lot_history} lần là một tín hiệu quan trọng: có thể hàng khó ra, hoặc nhiều môi giới đăng lại làm nhiễu giá thật."
        )
    elif lot_history >= 3:
        notes.append(f"Lô đã xuất hiện {lot_history} lần, nên cần hỏi người bán đây là hàng mới giảm hay chỉ là tin đăng lại.")

    if "giá ghi ước lượng" in flags:
        notes.append("Giá ghi dạng ước lượng làm giảm độ chắc; phải hỏi giá chốt bằng số rõ ràng trước khi tính lời.")
    return _unique(notes)[:7]


def _valuation_opinion(row, fair_ty: float | None, actual_ppm2: Any) -> list[str]:
    margin = float(row["mos_pct"] or 0)
    samples = _as_int(row["n_segment"]) or 0
    notes = _valuation_notes(row, fair_ty, actual_ppm2)

    if fair_ty is not None and row["price_ty"] is not None:
        asking = float(row["price_ty"])
        gap = fair_ty - asking
        if margin >= 30:
            notes.append(
                f"Tôi xem phần chênh khoảng {_price_ty(gap)} là biên để trả cho rủi ro kiểm chứng, không phải lợi nhuận chắc chắn."
            )
        elif margin < 15:
            notes.append(
                "Với biên này, giá tham chiếu chỉ giúp biết tài sản không quá đắt; nó chưa tạo lợi thế mua đầu tư rõ."
            )
        else:
            notes.append(
                "Biên giá có nhưng chưa dày; muốn biến thành thương vụ đầu tư thì phải có thêm lợi thế thực địa hoặc thương lượng giảm thêm."
            )

    if samples < 10:
        notes.append(
            "Tôi sẽ chiết khấu mạnh con số định giá vì mẫu so sánh mỏng; nếu đi xem, hãy coi đây là tin cần xác minh chứ không phải deal đã thắng."
        )
    elif samples >= 35 and margin >= 25:
        notes.append(
            "Mẫu so sánh đủ để tin rằng tin này lệch khỏi mặt bằng khu vực; câu hỏi còn lại là lệch vì rẻ thật hay vì có lỗi tài sản."
        )

    return _unique(notes)[:6]


def _deal_breakers(row, flags: list[str]) -> list[str]:
    breakers: list[str] = []
    if "cần kiểm tra đường thực tế" in flags or not row["road_type"]:
        breakers.append("Nếu đường thực tế nhỏ hơn mô tả hoặc ô tô không vào được như kỳ vọng, phải hạ giá hoặc bỏ.")
    if "cần xác minh thổ cư" in flags or (_ratio(row["tho_cu_m2"], row["area_m2"]) or 1) < 0.35:
        breakers.append("Nếu thổ cư/khả năng chuyển mục đích không rõ, không được lấy giá đất ở để quyết định mua.")
    if "cần xác minh đúng lô" in flags or (_as_int(row["lot_history_count"]) or 0) >= 8:
        breakers.append("Nếu không xác nhận đúng lô và lịch sử đăng lại, rủi ro nhầm hàng hoặc giá ảo rất cao.")
    if "giá ghi ước lượng" in flags or "môi giới nói còn thương lượng" in flags:
        breakers.append("Nếu giá chốt không rõ hoặc đổi khi hỏi sâu, nên xem đây là tin nhiễu.")
    if row["price_ty"] and float(row["price_ty"]) >= 4:
        breakers.append("Giá tổng cao làm vòng thoát hàng chậm hơn; chỉ mua nếu biên an toàn thật sự còn sau khi kiểm chứng.")
    if not breakers:
        breakers.append("Điểm quyết định vẫn là vị trí chính xác, sổ và lối vào; ba điểm này sai thì định giá phải làm lại.")
    return breakers[:5]


def _strategy(row, fair_ty: float | None, flags: list[str]) -> list[str]:
    strategy = [_action_note(row, fair_ty)]
    if row["verdict"] == "cheap_real":
        strategy.append("Cách làm đúng là hỏi nhanh các điểm loại trừ, rồi đi xem sớm nếu câu trả lời rõ; tin rẻ thật thường không nên để quá lâu.")
    elif row["verdict"] == "not_cheap":
        strategy.append("Không cần tranh mua. Để lại số, theo dõi thêm, và chỉ quay lại khi chủ giảm hoặc xuất hiện lợi thế mà tin đăng chưa thể hiện.")
    elif row["verdict"] == "suspect":
        strategy.append("Không đặt lịch xem nếu chưa có vị trí và ảnh sổ; tin nghi vấn phải lọc qua điện thoại trước.")
    else:
        strategy.append("Hỏi bổ sung trước khi đi xem: vị trí, ảnh sổ, đường vào, thổ cư, giá chốt và lý do bán.")

    if row["price_dropped"]:
        strategy.append("Khi thương lượng, dùng lịch sử giảm giá làm điểm neo: hỏi lý do giảm và thử ép thêm thay vì chấp nhận giá mới là đáy.")
    if "cần kiểm tra đường thực tế" in flags:
        strategy.append("Đừng chốt qua ảnh; đường thực tế là biến số có thể làm giá trị thay đổi nhiều nhất.")
    return _unique(strategy)[:4]


def build_reasoning(row) -> str:
    ward = row["ward"] or "khu vực này"
    margin = _pct(row["mos_pct"])
    lot = f"{_property_vi(row['property_type'])} {_area(row['area_m2'])}"
    verdict = row["verdict"]
    if verdict == "cheap_real":
        return f"{ward}: {lot} có biên giá {margin}, đáng xem thực địa nếu vị trí/đường/pháp lý đúng."
    if verdict == "suspect":
        return f"{ward}: {lot} có giá hoặc thông tin cần nghi ngờ, phải kiểm chứng trước khi xem là cơ hội thật."
    if verdict == "insufficient_info":
        return f"{ward}: {lot} thiếu dữ liệu quan trọng nên chưa thể kết luận chất lượng đầu tư."
    return f"{ward}: {lot} có biên an toàn khoảng {margin}, chưa đủ dày để xếp là cơ hội rẻ mạnh."


def _conclusion(row) -> str:
    verdict = row["verdict"]
    lot = _cap_first(f"{_property_vi(row['property_type'])} khoảng {_area(row['area_m2'])} tại {row['ward'] or 'khu vực này'}")
    price = _price_ty(row["price_ty"])
    margin = _pct(row["mos_pct"])
    if verdict == "cheap_real":
        return (
            f"{lot}, giá rao {price}, đang có biên an toàn khoảng {margin}. "
            "Đáng đưa vào nhóm ưu tiên xem thực địa, nhưng chỉ có giá trị đầu tư nếu vị trí, "
            "lối vào và pháp lý khớp với tin đăng."
        )
    if verdict == "suspect":
        return (
            f"{lot}, giá rao {price}, nhìn qua có vẻ hấp dẫn nhưng chưa nên xem là cơ hội thật. "
            "Ưu tiên kiểm chứng giá chốt, đúng lô, diện tích và pháp lý trước khi mất thời gian đi xem."
        )
    if verdict == "insufficient_info":
        return (
            f"{lot} hiện thiếu dữ liệu then chốt để kết luận. "
            "Có thể giữ lại để hỏi thêm, nhưng chưa nên ưu tiên vốn nếu chưa rõ vị trí, sổ, lối vào và giá chốt."
        )
    return (
        f"{lot}, giá rao {price}, có biên an toàn khoảng {margin} nhưng chưa đủ dày. "
        "Có thể là tài sản ổn, nhưng chưa đáng ưu tiên như một thương vụ rẻ mạnh nếu không có lợi thế riêng ngoài giá."
    )


def build_memo(row) -> str:
    fair_ty = _fair_total_ty(row)
    actual_ppm2 = row["actual_ppm2"] or row["price_per_m2"]

    flags = _unique(
        [_flag_vi(flag) for flag in _json_list(row["red_flags"])]
        + [_flag_vi(flag) for flag in _json_list(row["source_quality_flags"])]
    )
    stance_title, stance_body = _advisory_stance(row, flags)
    thesis = _investor_thesis(row, flags)
    valuation = _valuation_opinion(row, fair_ty, actual_ppm2)
    breakers = _deal_breakers(row, flags)
    strategy = _strategy(row, fair_ty, flags)

    return "\n".join(
        [
            "# Ghi chú cố vấn",
            "",
            "## Nhận định",
            f"{stance_title} {_conclusion(row)}",
            "",
            stance_body,
            "",
            "## Luận điểm đầu tư",
            *[f"- {item}" for item in thesis],
            "",
            "## Định giá theo góc nhìn đầu tư",
            *[f"- {item}" for item in valuation],
            "",
            "## Điều kiện loại bỏ",
            *[f"- {item}" for item in breakers],
            "",
            "## Cách xử lý",
            *[f"- {item}" for item in strategy],
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
               l.title, l.description, l.source, l.ward, l.property_type, l.price_ty,
               l.area_m2, l.price_per_m2, l.frontage_m, l.depth_m,
               l.road_tier, l.road_type, l.has_so, l.tho_cu_m2,
               l.price_dropped, l.price_drop_pct,
               v.fair_ppm2, v.actual_ppm2, v.mos_pct, v.signal_score,
               v.n_segment, COALESCE(v.source_quality_flags, '') AS source_quality_flags,
               (SELECT COUNT(*) FROM price_history ph WHERE ph.listing_id = l.id) AS price_history_count,
               (SELECT COUNT(*)
                  FROM listings lh
                 WHERE lh.id = COALESCE(l.duplicate_of_id, l.id)
                    OR lh.duplicate_of_id = COALESCE(l.duplicate_of_id, l.id)
               ) AS lot_history_count
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
