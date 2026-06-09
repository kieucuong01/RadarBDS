import re
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
    assert "Cố vấn đầu tư" in html
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
        "_historyChartTimeline",
        "const chartTimeline = _historyChartTimeline(decoratedTimeline)",
        "modal-comps-advisor-20260608",
        "toggleSignalHistoryRows",
        "sm-history-summary",
        "sm-history-toggle",
        "is-history-extra",
    ]:
        assert expected in html or expected in modal_js or expected in modal_css

    assert ".sm-history-chart-shell" in modal_css
    assert ".sm-history-summary" in modal_css
    assert "SM_HISTORY_CHART_MAX_POINTS" not in modal_js
    assert "_historyVisibleChartTimeline" not in modal_js
    assert "updateSignalHistoryChart" not in modal_js
    assert "khoảng thời gian" not in modal_js


def test_signal_modal_tabs_meta_and_comps_are_investor_friendly():
    html = _read("templates/index.html")
    app_source = _read("app.py")
    modal_js = _read("static/js/main/modal.js")
    modal_css = _read("static/css/main/modal.css")

    desc_idx = html.find('data-sm-tab="desc"')
    history_idx = html.find('data-sm-tab="history"')
    comps_idx = html.find('data-sm-tab="comps"')
    memo_idx = html.find('data-sm-tab="memo"')
    assert -1 not in (desc_idx, history_idx, comps_idx, memo_idx)
    assert desc_idx < history_idx < comps_idx < memo_idx
    assert ">Cố vấn<" in html
    assert ">Ghi chú<" not in html
    assert "sm-source-badge" not in html

    assert "renderModalMetaLine" in modal_js
    assert "Đăng ${timeText}" in modal_js
    assert "Dang ${d.time" not in modal_js
    assert "data.source" not in modal_js
    assert "d.source || '-'" not in modal_js

    for expected in [
        "renderCompInfoTag",
        "sm-comp-tags",
        "sm-comp-score",
        "sm-comp-price-strip",
        "sm-comp-area",
        "sm-comp-road",
        "sm-comp-property",
        "sm-comp-land",
    ]:
        assert expected in modal_js or expected in modal_css

    for expected in [
        "badge_meta = signal_badge_metadata(c)",
        "'frontage_m': c[\"frontage_m\"]",
        "'depth_m': c[\"depth_m\"]",
        "'road_label': badge_meta[\"road_label\"]",
        "'street_label': badge_meta[\"street_label\"]",
        "'tho_cu_label': badge_meta[\"tho_cu_label\"]",
    ]:
        assert expected in app_source


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
    assert "signal-card-density-20260609" in html


def test_signal_tab_mobile_scroll_container_is_stable():
    html = _read("templates/index.html")
    core_js = _read("static/js/main/core.js")
    signals_js = _read("static/js/main/signals.js")
    filters_css = _read("static/css/main/filters.css")
    cards_css = _read("static/css/main/cards.css")

    for expected in [
        "dashboard-fast-path-20260608",
        "ensureSignalScrollRoot",
        "refreshObserver",
        "signals-scroll-ready",
        "-webkit-overflow-scrolling: touch",
        "touch-action: pan-y",
        "overscroll-behavior-y: contain",
    ]:
        assert expected in html or expected in core_js or expected in signals_js or expected in filters_css

    assert "#tab-signals" in filters_css
    assert "content-visibility: visible" in cards_css


def test_mobile_sidebar_filters_are_compact_for_ward_selection():
    html = _read("templates/index.html")
    boot_js = _read("static/js/main/boot.js")
    filters_css = _read("static/css/main/filters.css")

    for expected in [
        "mobile-filter-compact-20260608",
        "ward-option-name",
        ".sidebar #wardFilters",
        "grid-template-columns: repeat(2, minmax(0, 1fr))",
        ".sidebar #wardFilters .filter-option",
        ".sidebar #wardFilters .ward-option-name",
        "white-space: nowrap",
        "text-overflow: ellipsis",
        "min-height: 30px",
        "font-size: 0.78rem",
        ".sidebar #wardFilters .filter-option input[type=\"checkbox\"]",
        "width: 16px",
        "height: 16px",
    ]:
        assert expected in html or expected in boot_js or expected in filters_css


def test_signal_cards_and_modal_render_compact_property_badges():
    html = _read("templates/index.html")
    signals_js = _read("static/js/main/signals.js")
    modal_js = _read("static/js/main/modal.js")
    cards_css = _read("static/css/main/cards.css")
    modal_css = _read("static/css/main/modal.css")

    for expected in [
        "renderSignalMetaChips",
        "sourceTagHtml",
        "window.USER_TIER === 'admin'",
        "meta-chip-ward",
        "meta-chip-area",
        "['road-label'",
        "['street-label'",
        "['frontage'",
        "['depth'",
        "['tho-cu-label'",
        "['prop-label'",
        "streetLabel",
        "thoCuLabel",
        "propertyTypeLabel",
        "signal-card-density-20260609",
    ]:
        assert expected in html or expected in signals_js or expected in modal_js

    assert ".meta-chip-label" in cards_css
    assert ".meta-chip-street" in cards_css
    assert ".sm-tags-wrap .sm-tag-chip" in modal_css
    assert "grid-template-columns: repeat(12, minmax(0, 1fr))" in cards_css
    assert re.search(r"\.meta-chip-ward\s*\{[^}]*grid-column: span 3;", cards_css, re.S)
    assert re.search(r"\.meta-chip-area\s*\{[^}]*grid-column: span 5;", cards_css, re.S)
    assert re.search(r"\.meta-chip-street\s*\{[^}]*grid-column: span 5;", cards_css, re.S)
    assert re.search(r"\.meta-chip-property\s*\{[^}]*grid-column: span 2;", cards_css, re.S)
    assert re.search(r"\.meta-chip-land\s*\{[^}]*grid-column: span 3;", cards_css, re.S)
    assert "grid-auto-rows: 22px" in cards_css
    assert "flex-wrap: wrap" in modal_css
    assert "font-style: normal" in cards_css
    assert "linear-gradient(135deg, #ef4444 0%, #b91c1c 100%)" in cards_css
    assert "imageCounterHtml" not in signals_js
    assert "sc-image-count" not in signals_js
    assert ".sc-image-count" not in cards_css

    assert "_signalTagArea(data)" in modal_js
    assert "frontageText" in modal_js
    assert "depthText" in modal_js
    assert "return `${frontageText}x${depthText} (${area}m²)`" in modal_js
    assert "frontage: d.frontage" in modal_js
    assert "depth: d.depth" in modal_js
    assert "frontage: data.frontage_m" in modal_js
    assert "depth: data.depth_m" in modal_js


def test_new_signal_cards_use_orange_badge_and_card_highlight():
    signals_js = _read("static/js/main/signals.js")
    cards_css = _read("static/css/main/cards.css")

    assert "isNew ? 'is-new-signal' : ''" in signals_js
    assert re.search(r"\.new-badge\s*\{[^}]*linear-gradient\(135deg, #f97316 0%, #ef4444 100%\)", cards_css, re.S)
    assert re.search(r"\.scard\.is-new-signal\s*\{[^}]*box-shadow:", cards_css, re.S)
    assert ".scard.is-new-signal::before" not in cards_css
    assert "newSignalPulse" not in cards_css
    assert "animation:" not in re.search(r"\.scard\.is-new-signal\s*\{([^}]*)\}", cards_css, re.S).group(1)
    assert "rgba(249, 115, 22" in cards_css


def test_signal_feed_uses_fast_total_free_path_and_defers_dashboard_meta():
    html = _read("templates/index.html")
    signals_js = _read("static/js/main/signals.js")
    filters_js = _read("static/js/main/filters.js")
    core_js = _read("static/js/main/core.js")

    assert "signal-card-density-20260609" in html
    assert "params.set('include_total', '0')" in signals_js
    assert "Number.isFinite(Number(data.total))" in signals_js
    assert "deferDashboardMetaRefresh" in filters_js
    assert "requestIdleCallback" in filters_js
    assert "applyFilters();" in core_js
    assert "navigator.geolocation.getCurrentPosition" not in core_js


def test_signal_feed_uses_css_skeleton_cards_not_inline_placeholder_blocks():
    html = _read("templates/index.html")
    signals_js = _read("static/js/main/signals.js")
    cards_css = _read("static/css/main/cards.css")

    assert "signal-card-density-20260609" in html
    assert "signal-skeleton-card" in signals_js
    assert "signal-skeleton-media" in signals_js
    assert "signal-skeleton-price" in signals_js
    assert ".signal-skeleton-card" in cards_css
    assert ".signal-skeleton-card .skeleton-line" in cards_css
    assert "style=\"min-height:420px" not in signals_js


def test_mobile_filters_are_presented_as_bottom_sheet_with_clear_actions():
    html = _read("templates/index.html")
    core_js = _read("static/js/main/core.js")
    filters_css = _read("static/css/main/filters.css")
    leads_css = _read("static/css/main/leads_chat.css")

    for expected in [
        'class="sidebar filter-sheet"',
        'class="filter-sheet-head"',
        'class="filter-sheet-close"',
        'class="filter-sheet-actions"',
        'class="filter-sheet-apply"',
        "hideSidebarMobile();",
        "filter-sheet-polish-20260608",
    ]:
        assert expected in html or expected in core_js or expected in filters_css or expected in leads_css

    assert "transform: translateY(110%)" in leads_css
    assert ".sidebar.filter-sheet.show" in leads_css
    assert "border-radius: 22px 22px 0 0" in leads_css
    assert "aria-modal=\"true\"" in html


def test_signal_cards_do_not_render_deal_summary_strip():
    signals_js = _read("static/js/main/signals.js")
    cards_css = _read("static/css/main/cards.css")

    assert "function renderSignalDealSummary" not in signals_js
    assert "dealSummaryHtml" not in signals_js
    assert "sc-deal-summary" not in signals_js
    assert ".sc-deal-summary" not in cards_css
    assert "summary-chip-primary" not in cards_css
    assert "summary-chip-muted" not in cards_css


def test_all_listings_grid_reuses_signal_deal_card_renderer():
    html = _read("templates/index.html")
    app_source = _read("app.py")
    signals_js = _read("static/js/main/signals.js")
    listings_js = _read("static/js/main/listings.js")

    for expected in [
        "function renderSignalDealCard",
        "cardContext",
        "contactContext",
        "sourceTagHtml",
        "renderSignalCardMedia",
    ]:
        assert expected in signals_js

    assert "renderSignalDealCard(x, {" in listings_js
    assert "cardContext: 'all'" in listings_js
    assert "signal_badge_metadata" in app_source
    assert '"street_label": badge_meta["street_label"]' in app_source
    assert '"tho_cu_label": badge_meta["tho_cu_label"]' in app_source
    assert "function listingCard(x)" in listings_js
    assert "js/main/signals.js" in html and "js/main/listings.js" in html
    assert html.find("js/main/signals.js") < html.find("js/main/listings.js")

    forbidden_duplicated_markup = [
        "const imageCounterHtml",
        "<span class=\"sc-source-tag\">${escHtml(sourceName)}</span>",
        "<div class=\"price-val-fair\">${fair !== '-'",
    ]
    for snippet in forbidden_duplicated_markup:
        assert snippet not in listings_js


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
