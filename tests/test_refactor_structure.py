from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_app_routes_are_registered_from_blueprint_modules():
    expected = [
        "routes/__init__.py",
        "routes/public.py",
        "routes/auth_api.py",
        "routes/market_api.py",
        "routes/admin_api.py",
    ]
    for rel_path in expected:
        assert (ROOT / rel_path).exists(), f"missing {rel_path}"

    app_source = _read("app.py")
    assert "register_blueprints(app)" in app_source
    assert "@app.route" not in app_source


def test_index_loads_main_js_feature_files_in_dependency_order():
    html = _read("templates/index.html")
    expected_order = [
        "js/auth.js",
        "js/main/core.js",
        "js/main/filters.js",
        "js/main/signals.js",
        "js/main/modal.js",
        "js/main/market.js",
        "js/main/listings.js",
        "js/main/auth_cta.js",
        "js/main/boot.js",
    ]
    last_idx = -1
    for asset in expected_order:
        idx = html.find(asset)
        assert idx > last_idx, f"{asset} not loaded after previous feature file"
        last_idx = idx
        assert (ROOT / "static" / asset).exists(), f"missing static/{asset}"

    main_js = ROOT / "static/js/main.js"
    assert not main_js.exists() or main_js.stat().st_size < 1200


def test_all_listings_tab_supports_table_and_grid_views():
    html = _read("templates/index.html")
    listings_js = _read("static/js/main/listings.js")
    layout_css = _read("static/css/main/layout.css")

    for expected_id in [
        'id="listingsViewTable"',
        'id="listingsViewGrid"',
        'id="listingsTableView"',
        'id="listingsGrid"',
    ]:
        assert expected_id in html

    for expected_symbol in [
        "listingsView =",
        "function setListingsView",
        "function renderListingCards",
        "listings-grid",
    ]:
        assert expected_symbol in listings_js

    assert ".listings-grid" in layout_css


def test_signal_modal_helpers_used_by_open_path_are_defined():
    modal_js = _read("static/js/main/modal.js")

    for expected_symbol in [
        "function hideLegacyAiAssessment",
        "function setInvestmentMemoVisible",
        "function loadInvestmentMemo",
        "function _openSignalFromData",
    ]:
        assert expected_symbol in modal_js

    assert "hideLegacyAiAssessment();" in modal_js
    assert "setInvestmentMemoVisible(true);" in modal_js


def test_signal_modal_memo_defaults_to_conclusion_and_uses_vietnamese_labels():
    html = _read("templates/index.html")
    modal_js = _read("static/js/main/modal.js")

    assert "function _splitMemoForPreview" in modal_js
    assert "Xem thêm" in modal_js
    assert "Kết luận" in modal_js
    assert "biên an toàn" in modal_js
    assert "Kiểm tra giả định" in modal_js
    assert "lô so sánh" in modal_js
    assert "phương pháp so sánh thị trường" in modal_js
    assert "phương pháp dòng tiền" in modal_js
    assert "giá trị sử dụng tốt nhất" in modal_js
    assert "Ghi chú cố vấn" in html
    assert "Investment Memo" not in html
    assert '>Memo<' not in html
    assert "splitDenseSection" in modal_js
    assert "Thương vụ|Deal|Tóm tắt|Thông tin|Dữ liệu" in modal_js
    assert "!hasFullMemo && data.reasoning" in modal_js


def test_signal_modal_history_uses_compact_timeline_ui():
    html = _read("templates/index.html")
    modal_js = _read("static/js/main/modal.js")
    modal_css = _read("static/css/main/modal.css")

    for expected in [
        'class="sm-history-chart-shell"',
        "SM_HISTORY_VISIBLE_LIMIT = 3",
        "renderSignalHistoryRows",
        "_historyVisibleChartTimeline",
        "updateSignalHistoryChart",
        "history-three-points-20260606",
        "toggleSignalHistoryRows",
        "sm-history-summary",
        "sm-history-toggle",
        "is-history-extra",
    ]:
        assert expected in html or expected in modal_js or expected in modal_css

    assert ".sm-history-chart-shell" in modal_css
    assert ".sm-history-summary" in modal_css


def test_signal_cards_use_professional_empty_image_state():
    html = _read("templates/index.html")
    signals_js = _read("static/js/main/signals.js")
    cards_css = _read("static/css/main/cards.css")

    for expected in [
        "renderSignalCardMedia",
        "sc-img-wrap-empty",
        "sc-empty-media",
        "sc-empty-media-map",
        "is-image-missing",
        "Chưa có ảnh",
    ]:
        assert expected in signals_js or expected in cards_css

    assert ".sc-empty-media" in cards_css
    assert "signal-badge-two-row-20260606" in html


def test_signal_cards_and_modal_render_compact_property_badges():
    html = _read("templates/index.html")
    signals_js = _read("static/js/main/signals.js")
    modal_js = _read("static/js/main/modal.js")
    cards_css = _read("static/css/main/cards.css")
    modal_css = _read("static/css/main/modal.css")

    for expected in [
        "renderSignalMetaChips",
        "data-road-label",
        "data-street-label",
        "data-tho-cu-label",
        "data-prop-label",
        "streetLabel",
        "thoCuLabel",
        "propertyTypeLabel",
        "signal-badge-two-row-20260606",
    ]:
        assert expected in html or expected in signals_js or expected in modal_js

    assert ".meta-chip-label" in cards_css
    assert ".meta-chip-street" in cards_css
    assert ".sm-tags-wrap .sm-tag-chip" in modal_css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in cards_css
    assert "grid-auto-rows: 22px" in cards_css
    assert "flex-wrap: wrap" in modal_css


def test_mobile_account_menu_uses_fixed_dropdown_not_clipped_header_dropdown():
    html = _read("templates/index.html")
    auth_js = _read("static/js/auth.js")
    auth_css = _read("static/css/auth.css")

    for expected in [
        "account-menu-compact-20260606",
        'aria-expanded="false"',
        "setUserMenuOpen",
        "user-menu-open",
        "window.matchMedia('(max-width: 1024px)')",
        "position: fixed",
        "top: calc(var(--mobile-header-height) + 8px)",
        "width: min(300px, calc(100vw - 16px))",
        "min-height: 44px",
    ]:
        assert expected in html or expected in auth_js or expected in auth_css


def test_vip_upgrade_click_uses_modal_with_zalo_cta_instead_of_alert():
    html = _read("templates/index.html")
    auth_js = _read("static/js/auth.js")
    auth_css = _read("static/css/auth.css")

    for expected in [
        'id="vipUpgradeModal"',
        "openVipUpgradeModal",
        "closeVipUpgradeModal",
        "chatVipUpgradeZalo",
        "0343216024",
        "zalo.me/0343216024",
        "vip-upgrade-modal",
        "vip-upgrade-modal-20260606",
    ]:
        assert expected in html or expected in auth_js or expected in auth_css

    assert "alert('💎 Nâng cấp VIP" not in auth_js


def test_price_and_area_filters_support_multi_select_range_chips():
    html = _read("templates/index.html")
    filters_js = _read("static/js/main/filters.js")
    filters_css = _read("static/css/main/filters.css")

    for expected in [
        'data-range-name="price_range"',
        'data-range-name="area_range"',
        "toggleRangePreset",
        "selectedRangeTokens",
    ]:
        assert expected in html or expected in filters_js

    assert ".range-chip.active" in filters_css


def test_index_loads_css_domain_files_in_dependency_order():
    html = _read("templates/index.html")
    expected_order = [
        "css/main/base.css",
        "css/main/layout.css",
        "css/main/filters.css",
        "css/main/cards.css",
        "css/main/modal.css",
        "css/main/market.css",
        "css/main/leads_chat.css",
        "css/auth.css",
    ]
    last_idx = -1
    for asset in expected_order:
        idx = html.find(asset)
        assert idx > last_idx, f"{asset} not loaded after previous CSS file"
        last_idx = idx
        assert (ROOT / "static" / asset).exists(), f"missing static/{asset}"


def test_market_tab_has_opportunity_matrix_visualization():
    html = _read("templates/index.html")
    market_js = _read("static/js/main/market.js")
    market_css = _read("static/css/main/market.css")

    for expected in [
        'id="opportunityMatrixChart"',
        'id="opportunityMatrixInsight"',
        "opportunityMatrixInstance",
        "renderOpportunityMatrix",
        "type: 'bubble'",
        "onClick:",
        "_viewOpportunityWard",
        "MATRIX_BUBBLE_MIN_RADIUS = 12",
        "MATRIX_BUBBLE_MAX_RADIUS = 38",
        "MATRIX_BUBBLE_SCALE = 2.4",
    ]:
        assert expected in html or expected in market_js

    assert ".opportunity-matrix-body" in market_css


def test_market_trend_chart_exposes_sample_reliability():
    market_js = _read("static/js/main/market.js")

    for expected in [
        "sample_count",
        "sampleCounts",
        "pointBackgroundColor",
        "pointBorderColor",
        "từ",
        "tin",
    ]:
        assert expected in market_js


def test_market_tab_has_vip_area_risk_radar():
    html = _read("templates/index.html")
    market_js = _read("static/js/main/market.js")
    market_css = _read("static/css/main/market.css")

    for expected in [
        'id="areaRiskRadar"',
        'id="areaRiskRadarSummary"',
        "renderAreaRiskRadar",
        "area_risk_radar",
        "risk-score-strip",
    ]:
        assert expected in html or expected in market_js or expected in market_css

    assert ".area-risk-radar" in market_css
