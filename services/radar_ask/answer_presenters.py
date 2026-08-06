"""Pure presenters for common Radar Ask database answers."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from .contracts import (
    AnswerClaim,
    AnswerEnvelope,
    AskVerdict,
    EvidenceBundle,
    EvidenceItem,
    KeyMetric,
    RetrievalQuality,
    RouteDecision,
    SourceKind,
)


Presenter = Callable[[RouteDecision, EvidenceBundle, datetime], AnswerEnvelope]

INSUFFICIENT_DETAILS = {
    "no_eligible_listings_within_budget": "chưa có tin đủ điều kiện trong ngân sách này",
    "eligible_area_samples_not_found": "chưa có mẫu giá đủ điều kiện cho các khu vực cần so sánh",
    "no_actionable_deals_match_filters": "chưa có deal đạt đồng thời các bộ lọc",
    "no_actionable_price_drop_signals_in_window": "chưa có tín hiệu giảm giá đủ điều kiện trong khoảng thời gian này",
    "eligible_road_market_sample_not_found": "chưa có mẫu giá phù hợp cho tuyến đường này",
    "curated_document_evidence_not_found": "chưa có tài liệu chính thức đã kiểm duyệt phù hợp trong kho nguồn Radar",
    "official_land_price_row_not_found": "chưa tìm thấy dòng bảng giá đất chính thức phù hợp với địa điểm này",
    "listing_not_found_or_not_visible": "không tìm thấy tin phù hợp hoặc tài khoản hiện tại không được phép xem tin đó",
    "valuation_not_found": "tin này chưa có kết quả định giá đủ điều kiện",
    "eligible_comparables_not_found": "chưa có lô so sánh đủ điều kiện để đối chiếu",
    "price_history_not_found": "chưa có lịch sử giá đáng tin cậy cho tin này",
    "lot_history_not_found": "chưa có lịch sử lô đất đáng tin cậy cho tin này",
    "road_location_is_ambiguous": "tên đường này xuất hiện ở nhiều khu vực và cần xác định thêm phường",
    "location_is_ambiguous": "địa điểm này có nhiều cách hiểu và cần xác định rõ hơn",
    "location_not_found": "chưa xác định được địa điểm trong phạm vi dữ liệu Radar",
    "city_not_supported_or_unresolved": "chưa xác định được thành phố trong phạm vi dữ liệu Radar",
    "city_ward_scope_mismatch": "thành phố và phường trong câu hỏi chưa khớp nhau",
    "market_trend_requires_both_periods": "chưa đủ dữ liệu ở cả hai giai đoạn để so sánh xu hướng",
    "evidence_tool_unavailable": "Radar tạm thời chưa truy xuất được nguồn dữ liệu cần thiết cho câu hỏi này",
}

DEFAULT_INSUFFICIENT_DETAIL = "chưa có bằng chứng phù hợp trong phạm vi dữ liệu Radar hiện có"

WARNING_TEXT = {
    "matches_use_current_asking_prices_not_transaction_prices": "Kết quả dùng mức chào hiện tại, không đại diện cho giá đã sang tên.",
    "asking_prices_not_transaction_prices": "Mẫu dùng mức chào từ tin đăng, không đại diện cho giá đã sang tên.",
    "asking_price_trend_not_transaction_price_index": "Xu hướng dùng giá rao trung vị trong mẫu Radar, không phải chỉ số giá giao dịch.",
    "asking_price_and_model_fair_value_are_not_transaction_prices": "Mức chào và mức mô hình là chỉ báo sàng lọc, không phải giá đã sang tên.",
    "low_sample": "Mẫu còn nhỏ nên biên sai số có thể cao.",
    "insufficient_exact_road": "Không đủ mẫu đúng tuyến; Radar đang dùng nhóm đường tương đương trong cùng phường.",
}

INSUFFICIENT_NEXT_STEP_TEXT = {
    "no_eligible_listings_within_budget": "Thử nới ngân sách, mở rộng thêm phường lân cận, hoặc hỏi theo loại tài sản cụ thể để Radar tìm mẫu gần hơn.",
    "eligible_area_samples_not_found": "Thử hỏi theo khung 90 ngày, bỏ bớt điều kiện loại tài sản, hoặc so sánh từng phường một.",
    "no_actionable_deals_match_filters": "Thử nới ngưỡng giá/mức MOS, hoặc hỏi 'tin đáng kiểm tra gần nhất' để xem danh sách rộng hơn.",
    "no_actionable_price_drop_signals_in_window": "Thử mở rộng từ hôm nay sang 7-30 ngày để có đủ tín hiệu giảm giá đáng so sánh.",
    "eligible_road_market_sample_not_found": "Thử bổ sung phường của tuyến đường, hoặc hỏi theo khu/phường nếu đúng tuyến chưa đủ mẫu.",
    "market_trend_requires_both_periods": "Thử hỏi theo khung 90 ngày hoặc 180 ngày, hoặc mở rộng từ tuyến đường sang cả phường để có đủ mẫu.",
    "evidence_tool_unavailable": "Anh có thể hỏi lại theo khu vực, ngân sách hoặc một mã tin cụ thể; Radar sẽ dùng nguồn khác nếu có đủ bằng chứng.",
}

RISK_FLAG_TEXT = {
    "possibly_duplicate": "có thể là tin trùng",
    "suspicious_bait": "có dấu hiệu tin mồi",
    "missing_area_evidence": "thiếu bằng chứng diện tích đủ tin cậy",
    "invalid_area": "diện tích có dấu hiệu không hợp lệ",
    "invalid_price": "giá có dấu hiệu không hợp lệ",
    "area_mismatch": "diện tích không khớp giữa các nguồn",
    "ward_mismatch": "phường/khu vực không khớp",
    "road_conflict": "tên đường có xung đột",
    "tho_cu_mismatch": "thông tin thổ cư chưa khớp",
    "legal_status_not_verified": "pháp lý chưa được xác minh",
    "source_quality_recheck_required": "nguồn cần kiểm tra lại",
    "low_segment_confidence": "mẫu định giá cùng phân khúc còn mỏng",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _fmt(value: Any, *, digits: int = 2) -> str:
    number = _number(value)
    if number is None:
        return "—"
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _dataset_version(items: Sequence[EvidenceItem]) -> str:
    versions = list(dict.fromkeys(item.dataset_version for item in items))
    if not versions:
        return "radar-ask:foundation"
    joined = ",".join(versions)
    return joined if len(joined) <= 120 else versions[0]


def _answer_as_of(bundle: EvidenceBundle, now: datetime) -> datetime:
    return max((item.as_of for item in bundle.items), default=now)


def _risk_text(warnings: Sequence[str]) -> list[str]:
    return [WARNING_TEXT.get(warning, warning) for warning in warnings[:12]]


def _flag_text(flag: str) -> str:
    return RISK_FLAG_TEXT.get(flag, flag.replace("_", " "))


def _insufficient(
    decision: RouteDecision,
    bundle: EvidenceBundle,
    now: datetime,
) -> AnswerEnvelope:
    detail_code = bundle.missing_requirements[0] if bundle.missing_requirements else None
    detail = (
        INSUFFICIENT_DETAILS.get(detail_code, DEFAULT_INSUFFICIENT_DETAIL)
        if detail_code
        else None
    )
    direct = "Chưa đủ dữ liệu đáng tin cậy để trả lời câu hỏi này."
    if detail:
        direct = f"{direct} Hiện {detail}."
    next_step = INSUFFICIENT_NEXT_STEP_TEXT.get(detail_code or "")
    if next_step:
        direct = f"{direct} {next_step}"
    return AnswerEnvelope(
        answered=False,
        depth=decision.depth,
        verdict=AskVerdict.INSUFFICIENT,
        direct_answer=direct,
        risks=_risk_text(bundle.warnings),
        next_verification_steps=list(bundle.missing_requirements[:12]),
        as_of=_answer_as_of(bundle, now),
        dataset_version=_dataset_version(bundle.items),
    )


def _item_by_ward(
    items: Sequence[EvidenceItem],
    ward: str,
    *,
    prefix: str,
) -> EvidenceItem | None:
    for evidence in items:
        value = _mapping(evidence.value)
        if (
            evidence.source_ref.startswith(prefix)
            and value is not None
            and str(value.get("ward") or "") == ward
        ):
            return evidence
    return None


def _base_answer(
    decision: RouteDecision,
    bundle: EvidenceBundle,
    *,
    direct_answer: str,
    claims: list[AnswerClaim],
    key_metrics: list[KeyMetric] | None = None,
    followups: list[str] | None = None,
    now: datetime,
) -> AnswerEnvelope:
    return AnswerEnvelope(
        answered=True,
        depth=decision.depth,
        verdict=AskVerdict.NEEDS_CHECKS,
        direct_answer=direct_answer[:6_000],
        claims=claims,
        key_metrics=key_metrics or [],
        risks=_risk_text(bundle.warnings),
        suggested_followups=followups or [],
        as_of=_answer_as_of(bundle, now),
        dataset_version=_dataset_version(bundle.items),
    )


def _present_budget_match(
    decision: RouteDecision,
    bundle: EvidenceBundle,
    now: datetime,
) -> AnswerEnvelope:
    budget = _number(bundle.calculations.get("budget_ty"))
    raw_rows = bundle.calculations.get("area_matches")
    rows = [row for row in raw_rows if isinstance(row, Mapping)] if isinstance(raw_rows, list) else []
    selected: list[tuple[Mapping[str, Any], EvidenceItem]] = []
    for row in rows[:3]:
        ward = str(row.get("ward") or "").strip()
        evidence = _item_by_ward(bundle.items, ward, prefix="budget-area:")
        if ward and evidence is not None:
            selected.append((row, evidence))
    if budget is None or not selected:
        return _insufficient(decision, bundle, now)

    wards = [str(row["ward"]) for row, _evidence in selected]
    priority = wards[0]
    if len(wards) > 1:
        priority = f"{priority}, sau đó {', '.join(wards[1:])}"
    matched = _integer(bundle.calculations.get("matched_listing_count")) or sum(
        _integer(row.get("listing_count")) or 0 for row, _evidence in selected
    )
    intro = (
        f"Với ngân sách {_fmt(budget)} tỷ, nên ưu tiên xem {priority} "
        f"dựa trên {matched} tin phù hợp hiện có."
    )
    lines: list[str] = []
    claims: list[AnswerClaim] = []
    metrics: list[KeyMetric] = []
    for index, (row, evidence) in enumerate(selected, start=1):
        ward = str(row["ward"])
        count = _integer(row.get("listing_count")) or 0
        median_price = _fmt(row.get("median_asking_price_ty"), digits=3)
        median_ppm2 = _fmt(row.get("median_asking_ppm2_million"))
        headroom = _fmt(row.get("budget_headroom_ty"), digits=3)
        line = (
            f"{index}. {ward}: {count} tin; mức chào trung vị {median_price} tỷ "
            f"({median_ppm2} triệu/m²), còn khoảng {headroom} tỷ so với ngân sách."
        )
        lines.append(line)
        claims.append(AnswerClaim(text=line, evidence_ids=[evidence.evidence_id]))
        metrics.append(
            KeyMetric(
                label=f"Tin phù hợp tại {ward}",
                value=count,
                unit="count",
                evidence_ids=[evidence.evidence_id],
            )
        )
    direct = "\n".join(
        [intro, *lines, "Đây là mức chào từ các tin đủ điều kiện, không đại diện cho giá đã sang tên."]
    )
    return _base_answer(
        decision,
        bundle,
        direct_answer=direct,
        claims=claims,
        key_metrics=metrics,
        followups=[
            f"So sánh sâu {wards[0]} với {wards[1]}" if len(wards) > 1 else f"Xem chi tiết {wards[0]}",
            "Lọc thêm theo loại bất động sản",
        ],
        now=now,
    )


def _present_area_comparison(
    decision: RouteDecision,
    bundle: EvidenceBundle,
    now: datetime,
) -> AnswerEnvelope:
    raw_areas = bundle.calculations.get("areas")
    if not isinstance(raw_areas, Mapping):
        return _insufficient(decision, bundle, now)
    selected: list[tuple[str, Mapping[str, Any], EvidenceItem]] = []
    for ward, raw_stats in list(raw_areas.items())[:4]:
        stats = _mapping(raw_stats)
        evidence = _item_by_ward(bundle.items, str(ward), prefix="ward-market:")
        if stats is not None and evidence is not None and _number(stats.get("median_asking_ppm2_million")) is not None:
            selected.append((str(ward), stats, evidence))
    if not selected:
        return _insufficient(decision, bundle, now)
    ordered = sorted(selected, key=lambda entry: _number(entry[1].get("median_asking_ppm2_million")) or float("inf"))
    cheapest = ordered[0]
    if len(ordered) > 1:
        intro = (
            f"{cheapest[0]} đang có mức chào thấp hơn {ordered[-1][0]}: "
            f"trung vị {_fmt(cheapest[1].get('median_asking_ppm2_million'))} so với "
            f"{_fmt(ordered[-1][1].get('median_asking_ppm2_million'))} triệu/m²."
        )
    else:
        intro = f"Radar hiện chỉ có mẫu đủ điều kiện tại {cheapest[0]}, nên chưa thể so sánh cân bằng."
    lines: list[str] = []
    claims: list[AnswerClaim] = []
    for ward, stats, evidence in selected:
        count = _integer(stats.get("sample_count")) or 0
        median = _fmt(stats.get("median_asking_ppm2_million"))
        p25 = _fmt(stats.get("p25_asking_ppm2_million"))
        p75 = _fmt(stats.get("p75_asking_ppm2_million"))
        line = (
            f"{ward}: trung vị {median} triệu/m²; khoảng giữa từ {p25} triệu/m² "
            f"đến {p75} triệu/m²; mẫu {count} tin."
        )
        lines.append(line)
        claims.append(AnswerClaim(text=line, evidence_ids=[evidence.evidence_id]))
    direct = "\n".join([intro, *lines, "Các mức trên là mức chào trong mẫu Radar, không đại diện cho giá đã sang tên."])
    return _base_answer(
        decision,
        bundle,
        direct_answer=direct,
        claims=claims,
        followups=[f"So sánh deal tốt nhất tại {entry[0]}" for entry in ordered[:2]],
        now=now,
    )


def _present_area_market_estimate(
    decision: RouteDecision,
    bundle: EvidenceBundle,
    now: datetime,
) -> AnswerEnvelope:
    raw_areas = bundle.calculations.get("areas")
    if not isinstance(raw_areas, Mapping):
        return _insufficient(decision, bundle, now)
    selected: tuple[str, Mapping[str, Any], EvidenceItem] | None = None
    for ward, raw_stats in raw_areas.items():
        stats = _mapping(raw_stats)
        evidence = _item_by_ward(bundle.items, str(ward), prefix="ward-market:")
        if stats is not None and evidence is not None:
            selected = (str(ward), stats, evidence)
            break
    if selected is None:
        return _insufficient(decision, bundle, now)
    ward, stats, evidence = selected
    count = _integer(stats.get("sample_count")) or 0
    median = _fmt(stats.get("median_asking_ppm2_million"))
    p25 = _fmt(stats.get("p25_asking_ppm2_million"))
    p75 = _fmt(stats.get("p75_asking_ppm2_million"))
    days = _integer(bundle.calculations.get("window_days")) or 90
    line = (
        f"Tại {ward}, giá rao trung vị trong mẫu Radar là {median} triệu/m²; "
        f"khoảng giữa {p25}-{p75} triệu/m², trên mẫu {count} tin trong {days} ngày."
    )
    return _base_answer(
        decision,
        bundle,
        direct_answer="\n".join(
            [
                line,
                "Đây là mức chào từ tin đủ điều kiện, không đại diện cho giá đã sang tên.",
            ]
        ),
        claims=[AnswerClaim(text=line, evidence_ids=[evidence.evidence_id])],
        key_metrics=[
            KeyMetric(
                label=f"Giá rao trung vị tại {ward}",
                value=_number(stats.get("median_asking_ppm2_million")),
                unit="million_vnd_per_m2",
                evidence_ids=[evidence.evidence_id],
            ),
            KeyMetric(
                label=f"Mẫu giá tại {ward}",
                value=count,
                unit="count",
                evidence_ids=[evidence.evidence_id],
            ),
        ],
        followups=[f"So sánh {ward} với phường lân cận", f"Xem deal đáng kiểm tra tại {ward}"],
        now=now,
    )


def _present_deal_search(
    decision: RouteDecision,
    bundle: EvidenceBundle,
    now: datetime,
) -> AnswerEnvelope:
    selected = [
        evidence
        for evidence in bundle.items
        if evidence.source_kind is SourceKind.VALUATION and _mapping(evidence.value) is not None
    ][:5]
    if not selected:
        return _insufficient(decision, bundle, now)
    result_count = _integer(bundle.calculations.get("result_count")) or len(selected)
    intro = (
        f"Radar tìm thấy {result_count} tin đáng kiểm tra theo bộ lọc hiện tại. "
        "Dưới đây là các tin ưu tiên kiểm tra."
    )
    lines: list[str] = []
    claims: list[AnswerClaim] = []
    listing_ids: list[str] = []
    for index, evidence in enumerate(selected, start=1):
        value = _mapping(evidence.value) or {}
        listing_ref = str(value.get("listing_ref") or "")
        listing_id = listing_ref.rsplit(":", 1)[-1] if ":" in listing_ref else "?"
        if listing_id != "?":
            listing_ids.append(listing_id)
        ward = str(value.get("ward") or "chưa rõ phường")
        area = _number(value.get("area_m2"))
        area_text = f", diện tích {_fmt(area, digits=1)} m²" if area is not None else ""
        line = (
            f"{index}. #{listing_id} tại {ward}: mức chào {_fmt(value.get('asking_price_ty'), digits=3)} tỷ, "
            f"{_fmt(value.get('asking_price_per_m2_million'))} triệu/m²{area_text}; mức mô hình "
            f"{_fmt(value.get('fair_price_per_m2_million'))} triệu/m²; MOS "
            f"{_fmt(value.get('mos_pct'))}%, điểm tín hiệu {_integer(value.get('signal_score')) or 0}."
        )
        lines.append(line)
        claims.append(AnswerClaim(text=line, evidence_ids=[evidence.evidence_id]))
    direct = "\n".join(
        [intro, *lines, "Mức chào và mức mô hình là hai chỉ báo sàng lọc; cần kiểm tra pháp lý và hiện trạng trước khi quyết định."]
    )
    followups = []
    if listing_ids:
        followups.append(f"Giải thích định giá tin #{listing_ids[0]}")
    if len(listing_ids) >= 2:
        followups.append(f"So sánh tin #{listing_ids[0]} với tin #{listing_ids[1]}")
    return _base_answer(
        decision,
        bundle,
        direct_answer=direct,
        claims=claims,
        followups=followups,
        now=now,
    )


def _present_price_drop_ranking(
    decision: RouteDecision,
    bundle: EvidenceBundle,
    now: datetime,
) -> AnswerEnvelope:
    raw_rows = bundle.calculations.get("areas")
    rows = [row for row in raw_rows if isinstance(row, Mapping)] if isinstance(raw_rows, list) else []
    selected: list[tuple[Mapping[str, Any], EvidenceItem]] = []
    for row in rows[:5]:
        ward = str(row.get("ward") or "").strip()
        evidence = _item_by_ward(bundle.items, ward, prefix="price-drop-area:")
        if ward and evidence is not None:
            selected.append((row, evidence))
    if not selected:
        return _insufficient(decision, bundle, now)
    days = _integer(bundle.calculations.get("window_days")) or 1
    top_ward = str(selected[0][0]["ward"])
    requested_wards = bundle.calculations.get("wards")
    if isinstance(requested_wards, list) and len(requested_wards) == 1 and len(selected) == 1:
        count = _integer(selected[0][0].get("signal_count")) or 0
        if days == 1:
            intro = f"Hôm nay, {top_ward} có {count} tín hiệu giảm giá trong dữ liệu đủ điều kiện của Radar."
        else:
            intro = f"Trong {days} ngày qua, {top_ward} có {count} tín hiệu giảm giá trong dữ liệu đủ điều kiện của Radar."
    elif days == 1:
        intro = f"Hôm nay, {top_ward} đang có nhiều tín hiệu giảm giá nhất trong dữ liệu đủ điều kiện của Radar."
    else:
        intro = f"Trong {days} ngày qua, {top_ward} đang có nhiều tín hiệu giảm giá nhất trong dữ liệu đủ điều kiện của Radar."
    lines: list[str] = []
    claims: list[AnswerClaim] = []
    for index, (row, evidence) in enumerate(selected, start=1):
        line = (
            f"{index}. {row['ward']}: {_integer(row.get('signal_count')) or 0} tín hiệu; "
            f"mức giảm trung vị {_fmt(row.get('median_price_drop_pct'))}%, "
            f"MOS trung vị {_fmt(row.get('median_mos_pct'))}%."
        )
        lines.append(line)
        claims.append(AnswerClaim(text=line, evidence_ids=[evidence.evidence_id]))
    return _base_answer(
        decision,
        bundle,
        direct_answer="\n".join([intro, *lines]),
        claims=claims,
        followups=[f"Mở các deal giảm giá tại {top_ward}", "So sánh chất lượng tín hiệu giữa hai khu đầu"],
        now=now,
    )


def _present_road_market_estimate(
    decision: RouteDecision,
    bundle: EvidenceBundle,
    now: datetime,
) -> AnswerEnvelope:
    evidence = next(
        (
            item
            for item in bundle.items
            if item.source_kind is SourceKind.MARKET_STAT
            and item.source_ref.startswith("road-market:")
            and _mapping(item.value) is not None
        ),
        None,
    )
    if evidence is None:
        return _insufficient(decision, bundle, now)
    value = _mapping(evidence.value) or {}
    road = str(value.get("road") or bundle.calculations.get("road") or "tuyến đường này")
    ward = str(value.get("ward") or bundle.calculations.get("ward") or "khu vực này")
    scope = str(value.get("market_scope") or bundle.calculations.get("market_scope") or "")
    scope_text = (
        f"mẫu đúng tuyến {road} tại {ward}"
        if scope == "exact_road"
        else f"mẫu đường tương đương tại {ward} do chưa đủ tin đúng tuyến {road}"
    )
    median = _fmt(value.get("median_asking_ppm2_million"))
    p25 = _fmt(value.get("p25_asking_ppm2_million"))
    p75 = _fmt(value.get("p75_asking_ppm2_million"))
    count = _integer(value.get("sample_count")) or evidence.sample_size or 0
    line = (
        f"Theo {scope_text}, mức chào trung vị hiện là {median} triệu/m²; "
        f"khoảng giữa từ {p25} triệu/m² đến {p75} triệu/m², trên mẫu {count} tin."
    )
    direct = "\n".join([line, "Đây là mức chào từ tin Radar theo dõi, không đại diện cho giá đã sang tên."])
    return _base_answer(
        decision,
        bundle,
        direct_answer=direct,
        claims=[AnswerClaim(text=line, evidence_ids=[evidence.evidence_id])],
        followups=[f"Xem các tin trên {road}", f"So sánh {road} với đường lân cận"],
        now=now,
    )


def _present_market_trend(
    decision: RouteDecision,
    bundle: EvidenceBundle,
    now: datetime,
) -> AnswerEnvelope:
    evidence = next(
        (
            item
            for item in bundle.items
            if item.source_kind is SourceKind.MARKET_STAT
            and item.source_ref.startswith("market-trend:")
            and _mapping(item.value) is not None
        ),
        None,
    )
    if evidence is None:
        return _insufficient(decision, bundle, now)
    value = _mapping(evidence.value) or {}
    current = _number(value.get("current_median_asking_ppm2_million"))
    previous = _number(value.get("previous_median_asking_ppm2_million"))
    change_pct = _number(value.get("change_pct"))
    current_count = _integer(value.get("current_sample_count")) or 0
    previous_count = _integer(value.get("previous_sample_count")) or 0
    window_days = _integer(value.get("window_days")) or 90
    if current is None or previous is None or change_pct is None:
        return _insufficient(decision, bundle, now)

    ward = str(bundle.resolved_entities.get("ward") or "").strip()
    road = str(bundle.resolved_entities.get("road") or "").strip()
    if not ward or not road:
        parts = evidence.source_ref.split(":")
        if not ward and len(parts) > 1 and parts[1] != "all":
            ward = parts[1]
        if not road and len(parts) > 2 and parts[2] != "all":
            road = parts[2]
    scope = f"đường {road} tại {ward}" if road and ward else road or ward or "khu vực này"
    if change_pct >= 3:
        direction = "đang tăng"
    elif change_pct <= -3:
        direction = "đang giảm"
    else:
        direction = "đang đi ngang"
    signed_change = f"{change_pct:+.2f}".rstrip("0").rstrip(".").replace(".", ",")
    line = (
        f"{scope} {direction} theo giá rao trung vị: hiện {_fmt(current)} triệu/m² "
        f"so với {_fmt(previous)} triệu/m² ở nửa kỳ trước ({signed_change}%) trong khung {window_days} ngày. "
        f"Mẫu hiện tại {current_count} tin, kỳ trước {previous_count} tin."
    )
    return _base_answer(
        decision,
        bundle,
        direct_answer="\n".join(
            [
                line,
                "Nên dùng tín hiệu này để sàng lọc khu vực, rồi kiểm tra từng lô bằng pháp lý, vị trí, mặt tiền và mẫu so sánh gần nhất.",
            ]
        ),
        claims=[AnswerClaim(text=line, evidence_ids=[evidence.evidence_id])],
        key_metrics=[
            KeyMetric(
                label="Giá rao trung vị hiện tại",
                value=round(current, 2),
                unit="million_vnd_per_m2",
                evidence_ids=[evidence.evidence_id],
            ),
            KeyMetric(
                label="Thay đổi so với nửa kỳ trước",
                value=round(change_pct, 2),
                unit="pct",
                evidence_ids=[evidence.evidence_id],
            ),
        ],
        followups=[f"Xem deal đáng kiểm tra tại {scope}", f"So sánh {scope} với khu lân cận"],
        now=now,
    )


def _present_listing_risk(
    decision: RouteDecision,
    bundle: EvidenceBundle,
    now: datetime,
) -> AnswerEnvelope:
    evidence = next(
        (
            item
            for item in bundle.items
            if item.source_kind is SourceKind.VALUATION
            and item.source_ref.startswith("radar-listing:")
            and item.source_ref.endswith(":risk")
            and _mapping(item.value) is not None
        ),
        None,
    )
    if evidence is None:
        return _insufficient(decision, bundle, now)
    value = _mapping(evidence.value) or {}
    blocking = [
        _flag_text(str(flag))
        for flag in value.get("blocking_flags", [])
        if isinstance(flag, str)
    ]
    warnings = [
        _flag_text(str(flag))
        for flag in value.get("warning_flags", [])
        if isinstance(flag, str)
    ]
    risk_level = str(bundle.calculations.get("risk_level") or "needs_checks")
    if risk_level == "high" or blocking:
        verdict = AskVerdict.HIGH_RISK
        intro = "Lô này chưa nên xem là deal sạch trong Radar."
    elif warnings:
        verdict = AskVerdict.NEEDS_CHECKS
        intro = "Lô này có thể đưa vào danh sách kiểm tra, nhưng chưa đủ sạch để kết luận nhanh."
    else:
        verdict = AskVerdict.NEEDS_CHECKS
        intro = "Radar chưa thấy cờ rủi ro deterministic lớn cho lô này."

    metrics_parts: list[str] = []
    asking_price = _number(value.get("asking_price_ty"))
    asking_ppm2 = _number(value.get("asking_price_per_m2_million"))
    fair_ppm2 = _number(value.get("fair_price_per_m2_million"))
    mos_pct = _number(value.get("mos_pct"))
    sample_count = _integer(value.get("sample_count"))
    if asking_price is not None:
        metrics_parts.append(f"mức chào {_fmt(asking_price, digits=3)} tỷ")
    if asking_ppm2 is not None:
        metrics_parts.append(f"{_fmt(asking_ppm2)} triệu/m²")
    if fair_ppm2 is not None:
        metrics_parts.append(f"mức mô hình {_fmt(fair_ppm2)} triệu/m²")
    if mos_pct is not None:
        metrics_parts.append(f"MOS {_fmt(mos_pct)}%")
    if sample_count is not None:
        metrics_parts.append(f"mẫu {sample_count} tin")
    metrics_text = "; ".join(metrics_parts)

    risk_parts: list[str] = []
    if blocking:
        risk_parts.append("Điểm chặn: " + ", ".join(blocking[:6]) + ".")
    if warnings:
        risk_parts.append("Điểm cần kiểm tra thêm: " + ", ".join(warnings[:6]) + ".")
    if not risk_parts:
        risk_parts.append("Dù không có cờ lớn, vẫn cần đối chiếu giấy tờ, vị trí thực địa và mẫu so sánh gần nhất.")

    line = intro
    if metrics_text:
        line = f"{line} Số liệu hiện có: {metrics_text}."
    direct = "\n".join(
        [
            line,
            *risk_parts,
            "Kết luận này là bước sàng lọc rủi ro; trước quyết định đầu tư vẫn cần kiểm tra pháp lý gốc, quy hoạch, vị trí thực địa và thương lượng thực tế.",
        ]
    )
    key_metrics: list[KeyMetric] = []
    if mos_pct is not None:
        key_metrics.append(
            KeyMetric(
                label="MOS theo mô hình Radar",
                value=round(mos_pct, 2),
                unit="pct",
                evidence_ids=[evidence.evidence_id],
            )
        )
    if sample_count is not None:
        key_metrics.append(
            KeyMetric(
                label="Mẫu định giá",
                value=sample_count,
                unit="count",
                evidence_ids=[evidence.evidence_id],
            )
        )
    return AnswerEnvelope(
        answered=True,
        depth=decision.depth,
        verdict=verdict,
        direct_answer=direct[:6_000],
        claims=[AnswerClaim(text=line, evidence_ids=[evidence.evidence_id])],
        key_metrics=key_metrics,
        risks=_risk_text(bundle.warnings),
        suggested_followups=[
            "Giải thích vì sao lô này được định giá như vậy",
            "Tìm lô so sánh gần khu này",
        ],
        as_of=_answer_as_of(bundle, now),
        dataset_version=_dataset_version(bundle.items),
    )


def _present_official_price_explanation(
    decision: RouteDecision,
    bundle: EvidenceBundle,
    now: datetime,
) -> AnswerEnvelope:
    official = next(
        (
            item
            for item in bundle.items
            if item.source_kind is SourceKind.OFFICIAL_DOCUMENT
            and _mapping(item.value) is not None
        ),
        None,
    )
    method = next(
        (
            item
            for item in bundle.items
            if item.source_kind in {SourceKind.RADAR_METHOD, SourceKind.EDITORIAL}
            and _mapping(item.value) is not None
        ),
        None,
    )
    if official is None and method is None:
        return _insufficient(decision, bundle, now)

    claims: list[AnswerClaim] = []
    lines = [
        (
            "Không nên dùng bảng giá đất TP.HCM như giá thị trường, vì bảng giá đất "
            "không phải giá thị trường hoặc giá trị thực tế của một lô đất."
        ),
    ]
    if official is not None:
        official_line = (
            "Tài liệu chính thức cho thấy bảng giá đất chủ yếu là căn cứ quản lý "
            "và nghĩa vụ tài chính, không phải bằng chứng trực tiếp của giá giao dịch thị trường."
        )
        lines.append(official_line)
        claims.append(
            AnswerClaim(text=official_line, evidence_ids=[official.evidence_id])
        )
    if method is not None:
        method_line = (
            "Khi định giá thực tế, Radar vẫn cần đối chiếu mẫu so sánh, vị trí, "
            "pháp lý, diện tích và đặc điểm mặt tiền của lô cụ thể."
        )
        lines.append(method_line)
        claims.append(AnswerClaim(text=method_line, evidence_ids=[method.evidence_id]))
    direct = " ".join(lines)
    return _base_answer(
        decision,
        bundle,
        direct_answer=direct,
        claims=claims,
        followups=[
            "Tra bảng giá đất cho một đường cụ thể",
            "So sánh bảng giá đất với giá rao quanh khu đó",
        ],
        now=now,
    )


PRESENTERS: dict[str, Presenter] = {
    "budget_match": _present_budget_match,
    "area_comparison": _present_area_comparison,
    "area_market_estimate": _present_area_market_estimate,
    "deal_search": _present_deal_search,
    "price_drop_ranking": _present_price_drop_ranking,
    "road_market_estimate": _present_road_market_estimate,
    "market_trend": _present_market_trend,
    "listing_risk": _present_listing_risk,
    "official_price_explanation": _present_official_price_explanation,
}


def present_deterministic_answer(
    decision: RouteDecision,
    bundle: EvidenceBundle,
    *,
    now: datetime,
) -> AnswerEnvelope:
    """Turn typed calculations into a grounded answer without provider I/O."""
    if bundle.retrieval_quality in {
        RetrievalQuality.REPAIR,
        RetrievalQuality.INSUFFICIENT,
        RetrievalQuality.CONFLICTED,
    }:
        return _insufficient(decision, bundle, now)
    presenter = PRESENTERS.get(decision.question_type)
    if presenter is None:
        return _insufficient(decision, bundle, now)
    return presenter(decision, bundle, now)
