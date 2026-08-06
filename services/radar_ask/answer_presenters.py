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
    "market_trend_requires_both_periods": "chưa có đủ dữ liệu ở cả hai giai đoạn để so sánh xu hướng",
}

DEFAULT_INSUFFICIENT_DETAIL = "chưa có bằng chứng phù hợp trong phạm vi dữ liệu Radar hiện có"

WARNING_TEXT = {
    "matches_use_current_asking_prices_not_transaction_prices": "Kết quả dùng mức chào hiện tại, không đại diện cho giá đã sang tên.",
    "asking_prices_not_transaction_prices": "Mẫu dùng mức chào từ tin đăng, không đại diện cho giá đã sang tên.",
    "asking_price_and_model_fair_value_are_not_transaction_prices": "Mức chào và mức mô hình là chỉ báo sàng lọc, không phải giá đã sang tên.",
    "low_sample": "Mẫu còn nhỏ nên biên sai số có thể cao.",
    "insufficient_exact_road": "Không đủ mẫu đúng tuyến; Radar đang dùng nhóm đường tương đương trong cùng phường.",
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
    for index, evidence in enumerate(selected, start=1):
        value = _mapping(evidence.value) or {}
        listing_ref = str(value.get("listing_ref") or "")
        listing_id = listing_ref.rsplit(":", 1)[-1] if ":" in listing_ref else "?"
        ward = str(value.get("ward") or "chưa rõ phường")
        line = (
            f"{index}. #{listing_id} tại {ward}: mức chào {_fmt(value.get('asking_price_ty'), digits=3)} tỷ, "
            f"{_fmt(value.get('asking_price_per_m2_million'))} triệu/m²; mức mô hình "
            f"{_fmt(value.get('fair_price_per_m2_million'))} triệu/m²; MOS "
            f"{_fmt(value.get('mos_pct'))}%, điểm tín hiệu {_integer(value.get('signal_score')) or 0}."
        )
        lines.append(line)
        claims.append(AnswerClaim(text=line, evidence_ids=[evidence.evidence_id]))
    direct = "\n".join(
        [intro, *lines, "Mức chào và mức mô hình là hai chỉ báo sàng lọc; cần kiểm tra pháp lý và hiện trạng trước khi quyết định."]
    )
    return _base_answer(
        decision,
        bundle,
        direct_answer=direct,
        claims=claims,
        followups=["Giải thích định giá của tin đứng đầu", "So sánh hai tin đầu tiên"],
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
    if days == 1:
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
    "deal_search": _present_deal_search,
    "price_drop_ranking": _present_price_drop_ranking,
    "road_market_estimate": _present_road_market_estimate,
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
