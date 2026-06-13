"""Deterministic investor assistant for RadarBDS.

The public assistant is intentionally rule/tool-based. It explains filters,
builds searches, summarizes market data, and routes deal-specific questions to
the existing advisory memo surface instead of generating new deal verdicts.
"""
from __future__ import annotations

import json
import secrets
from typing import Any

from db.connection import get_conn
from services.assistant_intents import DEFAULT_SUGGESTED_QUESTIONS, parse_assistant_intent
from services.assistant_tools import (
    get_deal_snapshot,
    get_market_snapshot,
    normalize_filter_draft,
    summarize_signal_cards,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _safe_text(value: Any, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def _session_token(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.startswith("asst-") and 8 <= len(raw) <= 120:
        return raw
    return "asst-" + secrets.token_urlsafe(18)


def _action(action_type: str, label: str, **payload: Any) -> dict[str, Any]:
    data = {"type": action_type, "label": label}
    data.update(payload)
    return data


def _filter_label(filt: dict[str, Any]) -> str:
    parts: list[str] = []
    wards = filt.get("ward") or []
    props = filt.get("property_type") or []
    if wards:
        parts.append(", ".join(wards))
    if props:
        labels = {
            "dat_nen": "đất nền",
            "nha_dat": "nhà đất",
            "dat_vuon": "đất vườn",
            "nha_tro": "nhà trọ",
        }
        parts.append(", ".join(labels.get(p, p) for p in props))
    if filt.get("price_max"):
        parts.append(f"dưới {filt['price_max']:g} tỷ")
    if filt.get("mos_min"):
        parts.append(f"rẻ hơn từ {filt['mos_min']}%")
    if filt.get("only_drops"):
        parts.append("có giảm giá")
    return " · ".join(parts) or "bộ lọc săn deal"


def _safe_log_exchange(
    *,
    session_token: str,
    user_id: int | None,
    tier: str,
    page_context: dict[str, Any] | None,
    user_message: str,
    parsed: dict[str, Any],
    answer: str,
    actions: list[dict[str, Any]],
) -> None:
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM assistant_sessions WHERE session_token=?",
                (session_token,),
            ).fetchone()
            if row:
                session_id = row["id"]
                conn.execute(
                    """
                    UPDATE assistant_sessions
                    SET user_id=?, tier=?, page_context_json=?, last_intent=?, updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (user_id, tier, _json(page_context or {}), parsed.get("intent"), session_id),
                )
            else:
                session_id = conn.execute(
                    """
                    INSERT INTO assistant_sessions
                        (session_token, user_id, tier, page_context_json, last_intent)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_token, user_id, tier, _json(page_context or {}), parsed.get("intent")),
                ).lastrowid
            conn.execute(
                """
                INSERT INTO assistant_messages
                    (session_id, role, message, intent, entities_json, actions_json)
                VALUES (?, 'user', ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_message,
                    parsed.get("intent"),
                    _json(parsed.get("entities") or {}),
                    _json([]),
                ),
            )
            conn.execute(
                """
                INSERT INTO assistant_messages
                    (session_id, role, message, intent, entities_json, actions_json)
                VALUES (?, 'assistant', ?, ?, ?, ?)
                """,
                (
                    session_id,
                    answer,
                    parsed.get("intent"),
                    _json(parsed.get("entities") or {}),
                    _json(actions),
                ),
            )
    except Exception:
        # Assistant UX should not fail because logging tables are unavailable.
        return


def _build_filter_response(parsed: dict[str, Any], *, tier: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    filt = normalize_filter_draft(parsed.get("filter"))
    snapshot = get_deal_snapshot(filt, tier=tier, limit=3)
    total = snapshot.get("total", 0)
    label = _filter_label(filt)
    answer = (
        f"Mình đã dựng bộ lọc: {label}. "
        f"Hiện hệ thống thấy khoảng {total} tin phù hợp trong feed săn deal. "
        "Bạn có thể áp dụng bộ lọc để xem danh sách, rồi mở từng tin để đọc tab Cố vấn."
    )
    actions = [_action("apply_filter", "Áp dụng bộ lọc", filter=filt)]
    if tier == "guest":
        actions.append(_action("auth_required", "Đăng nhập để lưu bộ lọc", reason="watchlist_requires_login"))
    else:
        actions.append(_action("open_watchlist", "Lưu watchlist", filter=filt))
    cards = summarize_signal_cards(snapshot.get("signals") or [])
    return answer, actions, cards


def _market_summary_response(parsed: dict[str, Any], *, tier: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    filt = normalize_filter_draft(parsed.get("filter"))
    market = get_market_snapshot(filt, tier=tier)
    deals = get_deal_snapshot(filt, tier=tier, limit=3)
    stats = market.get("stats") or {}
    total = int(stats.get("total") or 0)
    signals = int(stats.get("signals") or deals.get("total") or 0)
    hot = int(stats.get("hot") or 0)
    answer = (
        f"Hôm nay RadarBDS đang thấy {signals} tín hiệu săn deal trên {total} tin phù hợp bộ lọc hiện tại. "
        f"Trong đó có khoảng {hot} tin nóng/đáng chú ý. "
        "Ưu tiên tốt nhất là lọc theo MOS tối thiểu 10%, bật Có giảm giá nếu bạn muốn săn seller đang xuống giá, "
        "rồi đọc Cố vấn ở từng tin trước khi đi xem."
    )
    actions = [_action("apply_filter", "Xem các deal này", filter=filt or {"mos_min": 10})]
    cards = summarize_signal_cards(deals.get("signals") or [])
    return answer, actions, cards


def _compare_areas_response(parsed: dict[str, Any], *, tier: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    wards = (parsed.get("entities") or {}).get("wards") or ["Tân An", "Chánh Nghĩa"]
    rows = []
    for ward in wards[:3]:
        filt = normalize_filter_draft({**(parsed.get("filter") or {}), "ward": [ward], "mos_min": (parsed.get("filter") or {}).get("mos_min", 10)})
        snapshot = get_deal_snapshot(filt, tier=tier, limit=1)
        rows.append((ward, int(snapshot.get("total") or 0), summarize_signal_cards(snapshot.get("signals") or [], limit=1)))
    summary = "; ".join(f"{ward}: {count} tín hiệu" for ward, count, _cards in rows)
    best = max(rows, key=lambda item: item[1])[0] if rows else wards[0]
    answer = (
        f"So sánh nhanh theo dữ liệu hiện có: {summary}. "
        f"Nếu mục tiêu là săn cơ hội trước, mình sẽ xem {best} trước vì đang có nhiều tín hiệu hơn. "
        "Sau đó dùng Cố vấn từng tin để kiểm tra giá, đường và rủi ro cụ thể."
    )
    actions = [
        _action("apply_filter", f"Xem {best}", filter={"ward": [best], "mos_min": 10}),
    ]
    cards: list[dict[str, Any]] = []
    for _ward, _count, item_cards in rows:
        cards.extend(item_cards)
    return answer, actions, cards


def _strategy_response(parsed: dict[str, Any], *, tier: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    filt = normalize_filter_draft(parsed.get("filter"))
    if not filt.get("mos_min"):
        filt["mos_min"] = 15
    if not filt.get("property_type"):
        filt["property_type"] = ["dat_nen", "nha_dat"]
    budget = filt.get("price_max")
    budget_text = f"với ngân sách khoảng {budget:g} tỷ" if budget else "với ngân sách bạn đưa ra"
    answer = (
        f"Chiến lược săn deal {budget_text}: ưu tiên tin có MOS từ {filt['mos_min']}%, "
        "đường tier 2-3 dễ thanh khoản, diện tích vừa phải, có lịch sử giảm giá nếu muốn thương lượng mạnh. "
        "Đừng xem MOS là quyết định mua; hãy dùng nó để chọn shortlist rồi kiểm tra sổ, vị trí thật và quy hoạch."
    )
    actions = [
        _action("apply_filter", "Áp dụng chiến lược này", filter=filt),
        _action("open_watchlist", "Lưu thành watchlist", filter=filt) if tier != "guest" else _action("auth_required", "Đăng nhập để lưu watchlist", reason="watchlist_requires_login"),
    ]
    deals = get_deal_snapshot(filt, tier=tier, limit=3)
    return answer, actions, summarize_signal_cards(deals.get("signals") or [])


def _watchlist_response(parsed: dict[str, Any], *, tier: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    filt = normalize_filter_draft(parsed.get("filter"))
    if not filt.get("mos_min"):
        filt["mos_min"] = 15
    answer = (
        f"Mình đã chuẩn bị watchlist: {_filter_label(filt)}. "
        "Bạn kiểm tra lại tiêu chí rồi lưu; VIP có thể nhận thông báo Telegram khi có tin mới khớp."
    )
    if tier == "guest":
        actions = [_action("auth_required", "Đăng nhập để lưu watchlist", reason="watchlist_requires_login")]
    else:
        actions = [_action("open_watchlist", "Lưu watchlist", filter=filt)]
    return answer, actions, []


def _lead_response() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    answer = (
        "Nếu bạn muốn đi xem hoặc cần RadarBDS hỗ trợ ráp mối, hãy để lại Zalo. "
        "Mình sẽ chuyển sang form liên hệ để admin có đủ ngữ cảnh hỗ trợ nhanh hơn."
    )
    return answer, [_action("open_lead", "Để lại Zalo")], []


def _viewing_checklist_response() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    answer = (
        "Checklist đi xem đất: 1) kiểm tra sổ và ranh thực tế; 2) đo mặt tiền, chiều sâu, lộ giới; "
        "3) hỏi đường vào có tranh chấp/lối đi chung không; 4) so giá/m2 với các tin cùng phường; "
        "5) xem lịch sử giảm giá và lý do chủ bán; 6) chụp lại sổ, đường, mốc ranh để đối chiếu sau."
    )
    return answer, [_action("open_lead", "Cần hỗ trợ đi xem")], []


def _explain_response(message: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    text = message.lower()
    if "model" in text:
        answer = (
            "RadarBDS đang hiển thị định giá theo model cũ và model mới để đối chiếu. "
            "Badge Rẻ hơn dùng giá định giá thấp hơn để bảo thủ. Assistant chỉ giải thích, không sửa kết quả định giá."
        )
    elif "road" in text or "tier" in text:
        answer = (
            "Road tier là cấp đường dùng trong định giá: tier 1 mặt tiền/đường lớn, tier 2 đường nhựa/DX, "
            "tier 3 hẻm xe hơi hoặc nhánh/xẹt, tier 4-5 hẻm nhỏ hơn. Nếu một tin cụ thể sai, cần sửa parser rồi reprocess."
        )
    elif "giam" in text or "giảm" in text:
        answer = (
            "Có giảm giá nghĩa là hệ thống thấy lịch sử rao trước đó cao hơn hiện tại hoặc repost cùng lô có giá thấp hơn. "
            "Đây là tín hiệu thương lượng, không tự động chứng minh deal tốt."
        )
    else:
        answer = (
            "MOS là biên an toàn: giá hệ thống tham chiếu cao hơn giá rao bao nhiêu phần trăm. "
            "RadarBDS dùng MOS để lọc shortlist; trước khi mua vẫn cần kiểm tra sổ, vị trí, quy hoạch và đường thực tế."
        )
    return answer, [], []


def _listing_redirect_response(parsed: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    listing_id = (parsed.get("entities") or {}).get("listing_id")
    answer = (
        f"Tin #{listing_id} có phần Cố vấn riêng trong modal. "
        "Mình không phân tích sâu từng deal ở Assistant tổng để tránh trùng và lệch với memo đã lưu."
    )
    return answer, [_action("open_listing_memo", "Mở tab Cố vấn", listing_id=listing_id)], []


def build_assistant_response(
    message: str,
    *,
    tier: str = "guest",
    user: dict[str, Any] | None = None,
    session_id: str | None = None,
    page_context: dict[str, Any] | None = None,
    current_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_message = _safe_text(message, 1200)
    token = _session_token(session_id)
    parsed = parse_assistant_intent(clean_message)
    if current_filters and not parsed.get("filter"):
        parsed["filter"] = normalize_filter_draft(current_filters)

    intent = parsed.get("intent") or "help"
    if intent in {"build_filter", "search_deals"}:
        answer, actions, cards = _build_filter_response(parsed, tier=tier)
    elif intent == "market_summary":
        answer, actions, cards = _market_summary_response(parsed, tier=tier)
    elif intent == "compare_areas":
        answer, actions, cards = _compare_areas_response(parsed, tier=tier)
    elif intent == "investment_strategy":
        answer, actions, cards = _strategy_response(parsed, tier=tier)
    elif intent == "watchlist_create":
        answer, actions, cards = _watchlist_response(parsed, tier=tier)
    elif intent == "lead_intent":
        answer, actions, cards = _lead_response()
    elif intent == "viewing_checklist":
        answer, actions, cards = _viewing_checklist_response()
    elif intent == "explain_metric":
        answer, actions, cards = _explain_response(clean_message)
    elif intent == "listing_specific_redirect":
        answer, actions, cards = _listing_redirect_response(parsed)
    else:
        answer = (
            "Mình có thể giúp bạn tìm deal theo ngân sách, tạo bộ lọc, tóm tắt thị trường, "
            "so sánh khu vực, tạo watchlist hoặc giải thích MOS/model định giá."
        )
        actions, cards = [], []

    payload = {
        "ok": True,
        "session_id": token,
        "intent": intent,
        "answer": answer,
        "response": answer,
        "cards": cards,
        "actions": actions,
        "suggested_questions": DEFAULT_SUGGESTED_QUESTIONS,
        "debug": {"entities": parsed.get("entities") or {}} if tier == "admin" else None,
    }
    if payload["debug"] is None:
        payload.pop("debug")

    _safe_log_exchange(
        session_token=token,
        user_id=int(user["id"]) if user and user.get("id") is not None else None,
        tier=tier,
        page_context=page_context,
        user_message=clean_message,
        parsed=parsed,
        answer=answer,
        actions=actions,
    )
    return payload
