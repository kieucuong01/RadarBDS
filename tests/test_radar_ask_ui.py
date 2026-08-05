from __future__ import annotations

from pathlib import Path

import app as radar_app


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_authenticated_page_renders_private_workspace(monkeypatch):
    import routes.public as public_routes

    monkeypatch.setenv("RADAR_ASK_ENABLED", "1")
    monkeypatch.setenv("RADAR_ASK_ALLOWED_TIERS", "free,vip,admin")
    monkeypatch.setattr(public_routes, "current_user", lambda: {"id": 11, "tier": "free", "display_name": "Nhà đầu tư"})
    monkeypatch.setattr(public_routes, "current_tier", lambda: "free")

    response = radar_app.app.test_client().get("/hoi-radar-bds")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "X-Radar-Public-Cache" not in response.headers
    html = response.get_data(as_text=True)
    assert 'data-radar-ask-app' in html
    assert 'data-tier="free"' in html
    assert 'css/radar_ask.css' in html
    assert 'js/radar_ask.js' in html


def test_template_has_accessible_workspace_and_five_investor_samples():
    html = _read("templates/radar_ask.html")

    for copy in (
        "Hỏi Radar BĐS",
        "Cuộc trò chuyện",
        "Cuộc trò chuyện mới",
        "Nhanh",
        "Phân tích",
        "Chuyên sâu",
        "Nguồn & cách tính",
        "Hỏi về khu vực, lô đất, mặt tiền đường, giá hoặc tín hiệu…",
        "Gửi câu hỏi",
        "Nội dung do AI tổng hợp từ dữ liệu Radar BDS",
    ):
        assert copy in html

    prompts = (
        "Ngân sách 2,5 tỷ ở Thủ Dầu Một nên xem phường nào?",
        "So sánh Phú Mỹ, Định Hòa và Phú Tân cho đầu tư",
        "Tìm lô dưới 20 triệu/m² ở Bến Cát",
        "Hôm nay khu vực nào có nhiều tin giảm giá?",
        "Giải thích bảng giá đất chính thức áp dụng thế nào?",
    )
    assert all(prompt in html for prompt in prompts)
    assert html.count("data-sample-question") == 5

    for marker in (
        'aria-live="polite"',
        'data-history-sheet',
        'data-history-open',
        'data-history-close',
        'data-evidence-sheet',
        'data-evidence-close',
        'data-composer',
        'data-delete-dialog',
        'type="button"',
        'viewport-fit=cover',
    ):
        assert marker in html
    assert "user-scalable=no" not in html
    assert "maximum-scale" not in html
    assert "|safe" not in html


def test_static_workspace_contract_is_safe_and_mobile_first():
    javascript = _read("static/js/radar_ask.js")
    css = _read("static/css/radar_ask.css")

    assert ".innerHTML" not in javascript
    assert "insertAdjacentHTML" not in javascript
    assert "textContent" in javascript
    assert "window.RadarAsk" in javascript
    assert "POLL_DELAYS_MS" in javascript
    assert "120000" in javascript
    assert "noopener noreferrer" in javascript

    assert "@media (max-width: 640px)" in css
    assert "font-size: 16px" in css
    assert "min-height: 44px" in css
    assert "100dvh" in css
    assert "overflow-x: clip" in css
    assert "env(safe-area-inset-bottom" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "grid-template-columns: minmax(250px, 300px) minmax(0, 1fr) minmax(320px, 380px)" in css


def test_review_round_one_accessibility_privacy_and_cache_contracts():
    html = _read("templates/radar_ask.html")
    javascript = _read("static/js/radar_ask.js")
    css = _read("static/css/radar_ask.css")

    assert "onload=" not in html
    assert "onclick=" not in html
    assert "onerror=" not in html
    assert "radar-ask-workspace-v2" in html
    assert "radar-ask-workspace-v1" not in html
    assert 'data-load-more-sessions' in html
    assert 'data-load-more-messages' in html
    assert html.count('role="complementary"') >= 2
    assert 'aria-label="Gửi câu hỏi"' in html
    assert 'data-submit-label' in html

    assert "sessionStorage" in javascript
    assert "consumeHandoff" in javascript
    assert "url.searchParams.set('question'" not in javascript
    assert "url.searchParams.set('ward'" not in javascript
    assert "url.searchParams.set('road'" not in javascript
    assert ".inert" in javascript
    assert "aria-modal" in javascript
    assert "trapSheetFocus" in javascript

    assert ".radar-ask-page .radar-ask-submit" in css
    assert ".radar-ask-submit [data-submit-label]" in css
    assert "pointer-events: none" in css
    assert "visibility: hidden" in css


def test_quota_copy_uses_tier_caps_without_static_remaining_claims():
    html = _read("templates/radar_ask.html")
    javascript = _read("static/js/radar_ask.js")

    assert "Free · 5 câu/ngày" in javascript
    assert "VIP · 20 câu/ngày" in javascript
    assert "Admin · 100 câu/ngày" in javascript
    for fabricated in ("còn 3/5", "còn 4/5", "còn 19/20", "remaining: 3"):
        assert fabricated not in html
        assert fabricated not in javascript


def test_homepage_exposes_authenticated_and_contextual_radar_ask_launchers():
    html = _read("templates/index.html")
    engagement = _read("static/js/main/auth_cta.js")

    assert html.count("data-radar-ask-open") >= 1
    assert "data-radar-ask-context" in html
    assert "{% if USER %}" in html
    assert "RadarAuth.openAuthModal" in html
    assert "window.RadarAsk.open" in engagement
    assert "listing_id" in engagement
    assert "ward" in engagement
    assert "road" in engagement
    assert "question" in engagement
    assert "URLSearchParams" not in engagement
    assert "location.search" not in engagement


def test_legacy_chat_endpoint_returns_not_found():
    response = radar_app.app.test_client().post("/api/" + "chat", json={"message": "test"})

    assert response.status_code == 404
