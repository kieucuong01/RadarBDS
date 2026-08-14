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


def test_admin_logic_is_extracted_from_app_into_service_modules():
    for rel_path in [
        "services/admin_quality.py",
        "services/admin_leads.py",
        "services/admin_users.py",
    ]:
        assert (ROOT / rel_path).exists(), f"missing {rel_path}"

    app_source = _read("app.py")
    for symbol in [
        "def _suppressed_signal_quality_summary",
        "def _resolve_lead_ack_email",
        "def _user_admin_row",
    ]:
        assert symbol not in app_source


def test_index_loads_main_js_feature_files_in_dependency_order():
    html = _read("templates/index.html")
    expected_order = [
        "js/main/core.js",
        "js/main/filter_runtime.js",
        "js/main/filters.js",
        "js/main/signals.js",
        "js/main/boot.js",
    ]
    last_idx = -1
    for asset in expected_order:
        idx = html.find(asset)
        assert idx > last_idx, f"{asset} not loaded after previous feature file"
        last_idx = idx
        assert (ROOT / "static" / asset).exists(), f"missing static/{asset}"

    assert "window.RADAR_ASSETS" in html
    assert "modal: \"{{ url_for('static', filename='js/main/modal.js') }}?v=signal-detail-regression-20260729\"" in html
    assert "market: \"{{ url_for('static', filename='js/main/market.js') }}?v=market-analysis-p0-p2-20260807b\"" in html
    assert "listings: \"{{ url_for('static', filename='js/main/listings.js') }}?v=mobile-scroll-lock-20260802\"" in html
    assert "auth: \"{{ url_for('static', filename='js/auth.js') }}?v=mobile-perf-82-20260611\"" in html
    assert "authCta: \"{{ url_for('static', filename='js/main/auth_cta.js') }}?v=radar-ask-launcher-20260805\"" in html
    assert "radarAsk: \"{{ url_for('static', filename='js/radar_ask.js') }}?v=radar-ask-workspace-v3\"" in html
    assert "window.RADAR_STYLES" in html
    assert '{{ css_auth }}' in html
    body_scripts = html.split("window.RADAR_ASSETS", 1)[-1]
    assert '<script src="{{ url_for(\'static\', filename=\'js/main/modal.js\') }}' not in body_scripts
    assert '<script src="{{ url_for(\'static\', filename=\'js/main/market.js\') }}' not in body_scripts
    assert '<script src="{{ url_for(\'static\', filename=\'js/main/listings.js\') }}' not in body_scripts
    assert '<script src="{{ url_for(\'static\', filename=\'js/auth.js\') }}' not in body_scripts
    assert '<script src="{{ url_for(\'static\', filename=\'js/main/auth_cta.js\') }}' not in body_scripts

    main_js = ROOT / "static/js/main.js"
    assert not main_js.exists() or main_js.stat().st_size < 1200


def test_lazy_auth_and_engagement_proxies_are_available_before_feature_scripts():
    core_js = _read("static/js/main/core.js")

    for expected in [
        "function ensureDashboardStyle(key)",
        "function ensureAuthModule()",
        "function ensureEngagementModule()",
        "function callLazyRadarAuth(method, args)",
        "function callLazyEngagement(method, args)",
        "const lazyRadarAuthMethods",
        "const lazyEngagementMethods",
        "window.RadarAuth = window.RadarAuth || {};",
        "window.tierCTA =",
        "window.openRadarAsk =",
        "window.track =",
    ]:
        assert expected in core_js

    for method in [
        "openAuthModal",
        "toggleUserMenu",
        "openWatchlistModal",
        "nudgeVipUpgrade",
        "submitAuth",
        "connectTelegram",
    ]:
        assert f"'{method}'" in core_js

    for method in [
        "tierCTA",
        "openRadarAsk",
        "submitGuestLead",
        "submitLeadAndOpenZalo",
        "skipLeadAndOpenZalo",
    ]:
        assert f"'{method}'" in core_js


def test_legacy_radar_assistant_runtime_is_permanently_absent():
    for rel_path in [
        "services/radar_assistant.py",
        "services/assistant_" + "intents.py",
        "services/assistant_" + "tools.py",
        "tests/test_radar_assistant.py",
    ]:
        assert not (ROOT / rel_path).exists(), f"legacy file remains: {rel_path}"

    forbidden = [
        "build_assistant_" + "response",
        "assistant_" + "intents",
        "assistant_" + "tools",
        "/api/" + "chat",
        "toggle" + "Chat",
        "chat" + "Window",
        "chat" + "Messages",
        "chat" + "Input",
    ]
    runtime_source = "\n".join(
        _read(path)
        for path in [
            "app.py",
            "routes/market_api.py",
            "templates/index.html",
            "static/js/main/auth_cta.js",
            "static/js/main/core.js",
        ]
    )
    for symbol in forbidden:
        assert symbol not in runtime_source, f"legacy runtime reference remains: {symbol}"


def test_lazy_listings_module_does_not_break_dashboard_boot():
    boot_js = _read("static/js/main/boot.js")
    core_js = _read("static/js/main/core.js")
    filters_js = _read("static/js/main/filters.js")

    assert "typeof setupListingsViewToggle === 'function'" in boot_js
    assert "typeof setupListingsObserver === 'function'" in boot_js
    assert "\n  setupListingsViewToggle();" not in boot_js
    assert "\n  setupListingsObserver();" not in boot_js
    assert "function initializeListingsUi()" in core_js
    assert "initializeListingsUi();" in core_js
    assert ".then(() => { initializeListingsUi(); loadListings(1); })" in filters_js


def test_homepage_mos_control_defaults_to_fifteen_and_locks_non_privileged_tiers():
    html = _read("templates/index.html")
    boot_js = _read("static/js/main/boot.js")

    assert 'id="mosValue">15</span>%' in html
    assert 'id="mosSlider" min="0" max="70" step="5" value="15"' in html
    assert "USER_TIER not in ['vip', 'admin']" in html
    assert "if (mosSlider && !mosSlider.disabled)" in boot_js


def test_homepage_mos_asset_version_changes_with_boot_behavior():
    html = _read("templates/index.html")
    assert "js/main/boot.js') }}?v=scope-filter-storage-20260807" in html


def test_homepage_area_scope_boot_uses_url_then_local_storage_then_chooser():
    html = _read("templates/index.html")
    boot_js = _read("static/js/main/boot.js")
    area_scope_js = _read("static/js/main/area_scope.js")
    filters_js = _read("static/js/main/filters.js")

    assert 'id="areaScopeChooser"' in html
    assert 'class="area-scope-modal"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'class="area-scope-modal-panel"' in html
    assert 'class="area-scope-close"' in html
    assert "closeAreaScopeChooser()" in html
    assert 'id="areaScopeCityChoices"' in html
    assert 'class="area-scope-city-picker"' in html
    assert "selectAreaScopeCity(this.dataset.city)" in html
    assert "('THỦ DẦU MỘT', 'Thủ Dầu Một')" in html
    assert "('BẾN CÁT', 'Bến Cát')" in html
    assert "Xem toàn {{ city_label }}" in html
    assert 'class="area-scope-city-group"' in html
    assert 'hidden' in html
    assert 'class="area-scope-ward-chip"' in html
    assert "toggleAreaScopeWard" in html
    assert "applyAreaScopeWardSelection" in html
    assert 'id="areaScopeOptionalFilters"' in html
    assert 'class="area-scope-filter-panel"' in html
    assert 'data-area-scope-filter="price_range"' in html
    assert 'data-area-scope-filter="area_range"' in html
    assert 'data-area-scope-filter="prop_type"' in html
    assert "toggleAreaScopeOptionalChip(this)" in html
    assert "clearAreaScopeOptionalFilters()" in html
    assert "syncAreaScopeOptionalFilters" in area_scope_js
    assert 'id="areaScopeBar"' in html
    assert "js/main/area_scope.js" in html
    assert html.index("js/main/area_scope.js") < html.index("js/main/boot.js")
    assert "openAreaScopeFilterSheet()" in html
    assert "selectAreaPreset(" not in html

    assert "RadarAreaScope.scopeFromSearchParams" in boot_js
    assert "RadarAreaScope.readStoredScope" in boot_js
    assert "RadarAreaScope.showChooser" in boot_js
    assert "searchParams.getAll('price_range')" in boot_js
    assert "searchParams.getAll('area_range')" in boot_js
    assert "applyRangeParamsFromUrl('price'" in boot_js
    assert "applyRangeParamsFromUrl('area'" in boot_js
    assert "RadarAreaScope.syncStoredFiltersControls" in boot_js
    assert "RadarAreaScope.applyStoredFiltersToParams" in boot_js
    assert "RadarAreaScope.filtersFromSearchParams" in boot_js
    assert "const hasAnyUrlFilter = searchParams.toString().length > 0;" in boot_js
    assert "detectLocation();" not in boot_js
    assert "function hideChooser" in area_scope_js
    assert "area-scope-modal-open" in area_scope_js
    assert "openAreaScopeFilterSheet" in area_scope_js
    assert "closeAreaScopeChooser" in area_scope_js
    assert "root.closeAreaScopeChooser = function closeAreaScopeChooser()" in area_scope_js
    assert "defaultDismissedScope" in area_scope_js
    assert "RADAR_AREA_SCOPE_SKIP_PERSIST_ONCE" in area_scope_js
    assert "RADAR_AREA_SCOPE_SKIP_PERSIST_ONCE" in filters_js


def test_sidebar_keeps_multi_city_ward_selections_while_switching_city_tabs():
    html = _read("templates/index.html")
    filters_js = _read("static/js/main/filters.js")
    area_scope_js = _read("static/js/main/area_scope.js")

    assert "data-city-count" in html
    assert 'id="wardSelectedCount" aria-live="polite"' in html
    assert "RadarAreaScope.setActiveScopeCity" in filters_js
    select_city = filters_js.split("function selectCity(btn)", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "applyFilters()" not in select_city
    assert "applyDashboardScope" not in select_city
    assert "scopeStatusLabel" in area_scope_js
    assert "scopeStatusParts" in area_scope_js
    assert "renderScopeStatusChips" in area_scope_js
    assert 'class="area-scope-chip-list"' in html
    assert "refreshCurrentScopeUi" in area_scope_js
    assert "syncStoredFiltersControls" in area_scope_js
    assert "applyStoredFiltersToParams" in area_scope_js
    assert "selectAreaScopeCity" in area_scope_js
    assert "nextDraftWardScope" in area_scope_js
    assert "applyAreaScopeWardSelection" in area_scope_js


def test_sidebar_city_filter_exposes_supported_crawl_cities_only():
    html = _read("templates/index.html")

    for expected in [
        "('THỦ DẦU MỘT', 'Thủ Dầu Một')",
        "('BẾN CÁT', 'Bến Cát')",
        "('DĨ AN', 'Dĩ An')",
        "('THUẬN AN', 'Thuận An')",
        "('TÂN UYÊN', 'Tân Uyên')",
        'class="city-pill {% if loop.first %}active{% endif %}"',
        'data-city="{{ city_value }}"',
    ]:
        assert expected in html

    assert html.index("('DĨ AN', 'Dĩ An')") < html.index("('THUẬN AN', 'Thuận An')") < html.index("('TÂN UYÊN', 'Tân Uyên')")


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
        "signal-detail-regression-20260729",
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


def test_signal_modal_close_button_respects_mobile_safe_area():
    html = _read("templates/index.html")
    modal_css = _read("static/css/main/modal.css")

    assert 'class="close-modal"' in html
    assert 'style="top:12px; right:12px; z-index:20;"' in html
    assert "css/main/modal.css') ~ '?v=signal-detail-regression-20260729'" in html
    header_rule = re.search(r"#signalModal::before\s*\{(?P<body>[^}]+)\}", modal_css, re.S)
    assert header_rule, "missing mobile signal modal top close zone"
    header_body = header_rule.group("body")
    assert "height: calc(env(safe-area-inset-top, 0px) + 74px)" in header_body
    assert "pointer-events: none" in header_body
    assert "z-index: 50" in header_body

    close_rule = re.search(r"#signalModal\s+\.close-modal\s*\{(?P<body>[^}]+)\}", modal_css, re.S)
    assert close_rule, "missing mobile signal modal close rule"
    body = close_rule.group("body")
    assert "position: fixed !important" in body
    assert "top: calc(env(safe-area-inset-top, 0px) + 10px) !important" in body
    assert "right: calc(env(safe-area-inset-right, 0px) + 12px) !important" in body
    assert "z-index: 60 !important" in body
    assert "width: 52px" in body
    assert "height: 52px" in body
    assert "touch-action: manipulation" in body


def test_signal_modal_tabs_meta_and_comps_are_investor_friendly():
    html = _read("templates/index.html")
    comparable_source = _read("services/listing_comparables.py")
    modal_js = _read("static/js/main/modal.js")
    modal_css = _read("static/css/main/modal.css")

    desc_idx = html.find('data-sm-tab="desc"')
    history_idx = html.find('data-sm-tab="history"')
    comps_idx = html.find('data-sm-tab="comps"')
    memo_idx = html.find('data-sm-tab="memo"')
    assert -1 not in (desc_idx, history_idx, memo_idx)
    assert comps_idx == -1
    assert desc_idx < history_idx < memo_idx
    assert html.find('class="sm-right"') < html.find("data-comparable-carousel")
    assert "comparable_carousel.js" in html
    assert "RadarComparableCarousel.mount" in modal_js
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in modal_css
    assert ">Cố vấn<" in html
    assert ">Ghi chú<" not in html
    assert "sm-source-badge" not in html

    assert "renderModalMetaLine" in modal_js
    assert "Đăng ${timeText}" in modal_js
    assert "Dang ${d.time" not in modal_js
    assert "data.source" not in modal_js
    assert "d.source || '-'" not in modal_js

    for expected in [
        "format_signal_card_record",
        "l.frontage_m",
        "l.depth_m",
        "l.road_name",
        "l.road_type",
        "l.tho_cu_m2",
    ]:
        assert expected in comparable_source


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
    assert "signal-detail-regression-20260729" in html


def test_first_signal_image_is_lcp_priority_but_later_images_stay_lazy():
    signals_js = _read("static/js/main/signals.js")

    assert "priorityImage" in signals_js
    assert 'loading="${loadingAttr}"' in signals_js
    assert 'fetchpriority="${fetchPriorityAttr}"' in signals_js
    assert "loadingAttr = mediaOpts.priorityImage ? 'eager' : 'lazy'" in signals_js
    assert "fetchPriorityAttr = mediaOpts.priorityImage ? 'high' : 'auto'" in signals_js
    assert "priorityImage: Boolean(options.priorityFirstImage && index === 0)" in signals_js
    assert "window.dispatchEvent(new CustomEvent('radar:first-signals-rendered'))" in signals_js


def test_signal_tab_mobile_scroll_container_is_stable():
    html = _read("templates/index.html")
    core_js = _read("static/js/main/core.js")
    signals_js = _read("static/js/main/signals.js")
    filters_css = _read("static/css/main/filters.css")
    cards_css = _read("static/css/main/cards.css")

    for expected in [
        "market-analysis-p0-p2-20260807b",
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
        "scope-filter-storage-20260807",
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
        "signal-detail-regression-20260729",
    ]:
        assert expected in html or expected in signals_js or expected in modal_js

    assert ".meta-chip-label" in cards_css
    assert ".meta-chip-street" in cards_css
    assert ".sm-tags-wrap .sm-tag-chip" in modal_css
    assert re.search(r"\.sc-meta-chips\s*\{[^}]*display: flex;", cards_css, re.S)
    assert re.search(r"\.sc-meta-chips\s*\{[^}]*flex-wrap: wrap;", cards_css, re.S)
    assert re.search(r"\.meta-chip-ward\s*\{[^}]*max-width: min\(100%, 12rem\);", cards_css, re.S)
    assert re.search(r"\.meta-chip-area\s*\{[^}]*max-width: min\(100%, 14rem\);", cards_css, re.S)
    assert re.search(r"\.meta-chip-street\s*\{[^}]*max-width: min\(100%, 18rem\);", cards_css, re.S)
    assert re.search(r"\.meta-chip-property\s*\{[^}]*max-width: min\(100%, 10rem\);", cards_css, re.S)
    assert re.search(r"\.meta-chip-land\s*\{[^}]*max-width: min\(100%, 12rem\);", cards_css, re.S)
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


def test_signal_filter_flow_loads_cards_before_counts_without_dashboard():
    signals_js = _read("static/js/main/signals.js")
    filters_js = _read("static/js/main/filters.js")
    core_js = _read("static/js/main/core.js")
    start = filters_js.index("function applyFilters()")
    end = filters_js.index("\nfunction ", start + 1)
    apply_block = filters_js[start:end]

    assert "RadarFilterRuntime.runSignalFirst" in apply_block
    assert "loadSignals(1, { reset: true })" in apply_block
    assert "currentFilters === filterSnapshot" in apply_block
    assert "deferCountsRefresh(false)" in apply_block
    signal_branch = apply_block.split("if (tab === 'signals')", 1)[1].split("} else", 1)[0]
    assert "refreshDashboardMeta" not in signal_branch
    assert "refreshCounts(false);" not in signal_branch

    assert "params.set('include_total', '0')" in signals_js
    assert "window.RadarFilterRuntime.canonicalize(params)" in signals_js
    assert "params.set('sigv'" not in signals_js
    assert "signalsVersion" not in signals_js
    assert "signalsVersion" not in filters_js
    assert "signalsVersion" not in core_js
    assert "Number.isFinite(Number(data.total))" in signals_js
    assert "deferDashboardMetaRefresh" not in filters_js
    assert "requestIdleCallback" in filters_js
    assert "applyFilters();" in core_js
    assert "navigator.geolocation.getCurrentPosition" not in core_js


def test_homepage_measures_web_vitals_and_first_signal_cards_without_pii():
    html = _read("templates/index.html")
    signals_js = _read("static/js/main/signals.js")
    vitals_js = _read("static/js/main/web_vitals.js")

    assert "js/main/web_vitals.js" in html
    assert html.index("js/main/web_vitals.js") < html.index("js/main/boot.js")
    assert "radar-signals-request-start" in signals_js
    assert "radar-first-signal-cards-rendered" in signals_js
    assert "radar-first-signal-cards" in signals_js
    assert "grid.insertAdjacentHTML" in signals_js
    assert "largest-contentful-paint" in vitals_js
    assert "layout-shift" in vitals_js
    assert "durationThreshold: 40" in vitals_js
    assert "metric_name" in vitals_js
    assert "metric_value" in vitals_js
    assert "metric_rating" in vitals_js
    assert "non_interaction: true" in vitals_js
    for forbidden in ("page_url", "listing_id", "user_id", "cookie", "currentFilters"):
        assert forbidden not in vitals_js


def test_signal_feed_uses_css_skeleton_cards_not_inline_placeholder_blocks():
    html = _read("templates/index.html")
    signals_js = _read("static/js/main/signals.js")
    cards_css = _read("static/css/main/cards.css")

    assert "signal-detail-regression-20260729" in html
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
        "scope-filter-storage-20260807",
    ]:
        assert expected in html or expected in core_js or expected in filters_css or expected in leads_css

    assert "transform: translateY(110%)" in leads_css
    assert ".sidebar.filter-sheet.show" in leads_css
    assert "border-radius: 22px 22px 0 0" in leads_css
    assert "aria-modal=\"true\"" in html


def test_mobile_filter_sheet_headers_do_not_show_scroll_gaps():
    html = _read("templates/index.html")
    filters_css = _read("static/css/main/filters.css")
    leads_css = _read("static/css/main/leads_chat.css")

    for expected in [
        "scope-filter-storage-20260807",
        ".sidebar .filter-sheet-head",
        "position: sticky",
        "margin: -14px -14px 8px",
        ".sidebar .filter-title",
        "margin-inline: -14px",
        "border-radius: 0",
        "background: var(--surface-solid)",
        ".sidebar .signal-filter .filter-title",
    ]:
        assert expected in html or expected in filters_css or expected in leads_css


def test_mobile_filter_sheet_scroll_is_isolated_from_signal_tab():
    html = _read("templates/index.html")
    filters_css = _read("static/css/main/filters.css")
    leads_css = _read("static/css/main/leads_chat.css")

    for expected in [
        'class="command-bar"',
        ".sidebar.filter-sheet.show",
        "-webkit-overflow-scrolling: touch",
        "overscroll-behavior: contain",
        "touch-action: pan-y",
        "body.sidebar-open .content",
        "body.sidebar-open #tab-signals",
        "pointer-events: none",
        "overflow: hidden",
        ".mobile-overlay.show",
        "touch-action: none",
    ]:
        assert expected in html or expected in filters_css or expected in leads_css


def test_mobile_command_bar_actions_share_one_row_without_overlapping_left_controls():
    leads_css = _read("static/css/main/leads_chat.css")
    mobile_css = leads_css.split("@media (max-width: 1024px)", 1)[-1]

    command_bar = re.search(r"\.command-bar\s*\{([^}]*)\}", mobile_css, re.S)
    command_actions = re.search(r"\.command-bar-actions\s*\{([^}]*)\}", mobile_css, re.S)

    assert command_bar
    assert "gap: 10px" in command_bar.group(1)
    assert command_actions
    assert "grid-template-columns: minmax(0, auto) minmax(0, 1fr)" in command_actions.group(1)
    assert "gap: 8px" in command_actions.group(1)
    assert "margin-top: 2px" in command_actions.group(1)


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
    listing_feed_source = _read("services/listing_feed.py")
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
    assert "signal_badge_metadata" in listing_feed_source
    assert '"street_label": badge_meta["street_label"]' in listing_feed_source
    assert '"tho_cu_label": badge_meta["tho_cu_label"]' in listing_feed_source
    assert "function listingCard(x)" in listings_js
    assert "js/main/signals.js" in html
    assert "js/main/listings.js" in html
    assert "window.RADAR_ASSETS" in html

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
        "auth-modal-width-20260806",
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


def test_auth_modal_is_compact_on_desktop_without_affecting_other_modals():
    html = _read("templates/index.html")
    auth_css = _read("static/css/auth.css")

    assert "auth-modal-width-20260806" in html
    assert "#authModal .auth-modal-content" in auth_css
    assert "width: min(420px, calc(100vw - 32px));" in auth_css
    assert "#guestLeadModal .auth-modal-content" in auth_css
    assert "#vipUpgradeModal .auth-modal-content" in auth_css
    assert ".modal-content {\n  background: var(--surface-solid);" not in auth_css


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
    ]:
        assert expected in html or expected in auth_js or expected in auth_css

    assert "alert('💎 Nâng cấp VIP" not in auth_js


def test_guest_lead_zalo_cta_opens_new_tab_without_replacing_current_tab():
    html = _read("templates/index.html")
    auth_cta_js = _read("static/js/main/auth_cta.js")

    for expected in [
        'href="https://zalo.me/0343216024"',
        'target="_blank"',
        'rel="noopener noreferrer"',
        "closeGuestLeadModal()",
    ]:
        assert expected in html or expected in auth_cta_js

    assert "window.location.href = zaloHref" not in auth_cta_js


def test_price_and_area_filters_support_multi_select_range_chips():
    html = _read("templates/index.html")
    filters_js = _read("static/js/main/filters.js")
    filters_css = _read("static/css/main/filters.css")

    for expected in [
        'data-range-name="price_range"',
        'data-range-name="area_range"',
        "js/main/filters.js') }}?v=scope-dismiss-fallback-20260808",
        "js/main/area_scope.js') }}?v=scope-dismiss-fallback-20260808",
        "toggleRangePreset",
        "selectedRangeTokens",
        "applyRangeParamsFromUrl",
    ]:
        assert expected in html or expected in filters_js

    assert ".range-chip.active" in filters_css
    assert ".area-scope-chip-list" in filters_css
    assert ".area-scope-chip-location" in filters_css
    assert ".area-scope-chip-area" in filters_css
    assert ".area-scope-chip-type" in filters_css
    assert "overflow-wrap: anywhere" in filters_css


def test_listing_date_range_filter_is_available_below_source_filter():
    html = _read("templates/index.html")
    filters_css = _read("static/css/main/filters.css")

    assert html.find('id="sourceFilters"') < html.find('id="dateRangeFilters"')
    assert 'name="date_range" value="3m" checked' in html
    for expected in [
        'value="1w"',
        'value="1m"',
        'value="3m"',
        'value="6m"',
        'value="1y"',
        'value="all"',
    ]:
        assert expected in html
    assert ".date-range-grid" in filters_css


def test_index_loads_css_domain_files_in_dependency_order():
    html = _read("templates/index.html")
    expected_order = [
        "css/main/base.css",
        "css/main/layout.css",
        "css/main/filters.css",
        "css/main/cards.css",
    ]
    last_idx = -1
    for asset in expected_order:
        idx = html.find(asset)
        assert idx > last_idx, f"{asset} not loaded after previous CSS file"
        last_idx = idx
        assert (ROOT / "static" / asset).exists(), f"missing static/{asset}"


def test_feature_css_load_strategy_keeps_auth_ready_on_first_paint():
    html = _read("templates/index.html")
    head = html.split("</head>", 1)[0]
    core_js = _read("static/js/main/core.js")

    lazy_assets = {
        "css/main/modal.css": "css_modal",
        "css/main/market.css": "css_market",
    }
    for asset, template_var in lazy_assets.items():
        assert asset in html
        assert f'<link rel="preload" href="{{{{ {template_var} }}}}"' not in head
        assert f'<link rel="stylesheet" href="{{{{ {template_var} }}}}"' not in head

    assert '<link rel="stylesheet" href="{{ css_auth }}">' in head
    assert "window.RADAR_STYLES" in html
    assert "lazyStylePromises" in core_js
    assert "document.createElement('link')" in core_js
    assert "link.rel = 'stylesheet'" in core_js
    assert 'rel="preload" href="{{ css_leads }}" as="style"' in head


def test_lazy_feature_shells_are_hidden_or_positioned_before_lazy_css_loads():
    html = _read("templates/index.html")
    base_css = _read("static/css/main/base.css")

    assert "css/main/base.css') ~ '?v=mobile-scroll-lock-20260802'" in html
    hidden_shell_rule = re.search(
        r"\.modal,\s*\.chat-window,\s*\.user-menu-dropdown,\s*\.mobile-app-title,\s*\.mobile-bottom-nav\s*\{([^}]*)\}",
        base_css,
        re.S,
    )
    assert hidden_shell_rule
    assert "display: none;" in hidden_shell_rule.group(1)
    assert re.search(r"\.user-menu-trigger\s*\{[^}]*display:\s*inline-flex;", base_css, re.S)
    assert re.search(r"\.user-plan-chip\s*\{[^}]*border-radius:\s*999px;", base_css, re.S)
    assert re.search(r"\.modal\.show\s*\{[^}]*display:\s*flex", base_css, re.S)
    assert re.search(r"\.fab-ai\s*\{[^}]*position:\s*fixed;", base_css, re.S)
    assert re.search(r"\.fab-ai\s*\{[^}]*z-index:\s*80;", base_css, re.S)


def test_mobile_form_controls_prevent_ios_focus_zoom_without_disabling_user_zoom():
    html = _read("templates/index.html")
    base_css = _read("static/css/main/base.css")

    viewport = re.search(r'<meta name="viewport" content="([^"]+)"', html)
    assert viewport
    viewport_content = viewport.group(1)
    assert "viewport-fit=cover" in viewport_content
    assert "user-scalable=no" not in viewport_content
    assert "maximum-scale" not in viewport_content

    assert "@media (max-width: 1024px)" in base_css
    mobile_css = base_css.split("@media (max-width: 1024px)", 1)[-1]
    for expected in [
        "min-height: 100dvh",
        "overflow-y: auto",
        "touch-action: manipulation",
        'input:not([type="checkbox"]):not([type="radio"]):not([type="range"])',
        "select",
        "textarea",
        "font-size: 16px !important",
    ]:
        assert expected in mobile_css


def test_mobile_dashboard_uses_page_scroll_without_breaking_infinite_scroll():
    html = _read("templates/index.html")
    base_css = _read("static/css/main/base.css")
    filters_css = _read("static/css/main/filters.css")
    leads_css = _read("static/css/main/leads_chat.css")
    signals_js = _read("static/js/main/signals.js")
    listings_js = _read("static/js/main/listings.js")

    for expected in [
        "mobile-scroll-lock-20260802",
        "body {",
        "overflow-x: clip",
        ".main {",
        "height: auto",
        "overflow: visible",
        "#tab-signals,",
        "#tab-market,",
        "#tab-all.listings-grid-mode,",
        "#tab-insights",
        "scrollbar-gutter: auto",
    ]:
        assert expected in html or expected in base_css or expected in filters_css or expected in leads_css

    mobile_leads = leads_css.split("@media (max-width: 1024px)", 1)[-1]
    header_rule = re.search(r"\.header\s*\{(?P<body>[^}]+)\}", mobile_leads, re.S)
    assert header_rule
    assert "position: fixed" in header_rule.group("body")
    assert "width: 100%" in header_rule.group("body")
    assert "max-width: 100%" in header_rule.group("body")
    assert "padding: calc(var(--mobile-header-height) + 12px)" in mobile_leads

    for source in [signals_js, listings_js]:
        assert "window.matchMedia('(max-width: 1024px)').matches" in source
        assert "? null" in source


def test_dashboard_avoids_mobile_render_blocking_third_party_assets():
    html = _read("templates/index.html")
    base_css = _read("static/css/main/base.css")
    seo_html = _read("templates/seo_landing.html")
    seo_css = _read("static/css/seo.css")
    detail_html = _read("templates/listing_detail.html")
    head = html.split("</head>", 1)[0]

    assert "fonts.googleapis.com/css2?family=Plus+Jakarta+Sans" in html
    assert "fonts.gstatic.com" in html
    assert 'rel="preload" as="style" href="https://fonts.googleapis.com' in html
    assert "<link rel=\"stylesheet\" href=\"https://fonts.googleapis.com" not in head
    assert "@import url('https://fonts.googleapis.com" not in base_css
    assert "font-family: 'Plus Jakarta Sans', 'Segoe UI', Arial, sans-serif;" in base_css
    for content in [seo_html, seo_css]:
        assert "fonts.googleapis.com" not in content
        assert "fonts.gstatic.com" not in content
    assert 'rel="preload" as="style" href="https://fonts.googleapis.com' in detail_html
    assert '<noscript><link rel="stylesheet" href="https://fonts.googleapis.com' in detail_html

    assert "cdn.jsdelivr.net/npm/chart.js" not in head
    assert '<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>' not in html
    assert "images/logo.png" not in html
    assert 'class="logo-img logo-mark logo-mark-image"' in html
    assert "const SIGNAL_PAGE_SIZE = window.matchMedia" in _read("static/js/main/core.js")
    assert "ensureDashboardScript" in _read("static/js/main/core.js")
    assert "await ensureChartJs();" in _read("static/js/main/market.js")
    assert "await ensureChartJs();" in _read("static/js/main/modal.js")
    assert 'rel="preload" href="{{ css_filters }}" as="style"' in html
    assert "onload=\"this.onload=null;this.rel='stylesheet'\"" in html


def test_google_analytics_is_deferred_until_interaction_or_signal_render():
    partial = _read("templates/partials/google_site_tags.html")

    assert '<meta name="google-site-verification"' in partial
    assert '<script async src="https://www.googletagmanager.com/gtag/js' not in partial
    assert "window.dataLayer = window.dataLayer || []" in partial
    assert "window.gtag = window.gtag || function" in partial
    assert "function loadRadarAnalytics()" in partial
    assert "radar:first-signals-rendered" in partial
    assert "setTimeout(loadRadarAnalytics, 8000)" in partial
    assert "pointerdown" in partial
    assert "keydown" in partial


def test_mobile_thumbnails_and_static_cache_are_performance_tuned():
    image_assets = _read("services/image_assets.py")
    nginx_conf = _read("deployment/ubuntu24/nginx-radar-bds.conf")

    assert "THUMB_MAX_SIZE = (520, 338)" in image_assets
    assert "THUMB_QUALITY = 62" in image_assets
    assert "expires 30d;" in nginx_conf
    assert 'Cache-Control "public, max-age=2592000, immutable"' in nginx_conf
    assert "location /data/images/thumbs/" in nginx_conf
    assert "expires 30d;" in nginx_conf


def test_dashboard_accessibility_controls_have_names_and_keyboard_paths():
    html = _read("templates/index.html")
    core_js = _read("static/js/main/core.js")
    modal_js = _read("static/js/main/modal.js")
    signals_js = _read("static/js/main/signals.js")
    signal_card_js = _read("static/js/main/signal_card.js")
    filters_css = _read("static/css/main/filters.css")
    cards_css = _read("static/css/main/cards.css")

    assert '<div class="filter-title" onclick="toggleFilterSection(this)">' not in html
    assert html.count('type="button" class="filter-title"') == 5
    assert 'aria-expanded="true"' in html
    assert "titleEl.setAttribute('aria-expanded'" in core_js

    for expected in [
        'aria-label="Tìm phường xã"',
        'aria-label="Giá tối thiểu tỷ đồng"',
        'aria-label="Giá tối đa tỷ đồng"',
        'aria-label="Diện tích tối thiểu mét vuông"',
        'aria-label="Diện tích tối đa mét vuông"',
        'aria-label="Tìm signal theo tên đường hoặc địa danh"',
        'aria-label="Tìm tin rao theo tên đường hoặc địa danh"',
        'aria-label="Biên an toàn tối thiểu"',
        'aria-label="Đổi giao diện sáng tối"',
        'aria-label="Mở Hỏi Radar BĐS"',
        'aria-label="Đăng nhập để hỏi Radar BĐS"',
    ]:
        assert expected in html

    assert 'role="tab" aria-selected="true"' in html
    assert 'role="tabpanel"' in html
    assert "tab.setAttribute('aria-selected'" in modal_js
    assert "section.setAttribute('aria-hidden'" in modal_js
    assert 'role="button" tabindex="0"' not in signal_card_js
    assert '<article class="scard' in signal_card_js
    assert 'class="sc-title sc-title-link"' in signal_card_js
    assert 'alt="Ảnh tin đăng ${i + 1}"' in modal_js
    assert ".filter-title:focus-visible" in filters_css
    assert ".scard:focus-visible" in cards_css


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


def test_market_tab_is_decision_first_and_accessible():
    html = _read("templates/index.html")
    market_js = _read("static/js/main/market.js")
    market_css = _read("static/css/main/market.css")
    filters_js = _read("static/js/main/filters.js")

    assert html.index('class="chart-card opportunity-card"') < html.index('class="chart-card market-trend-card"')

    for expected in [
        'id="marketScopeSummary"',
        'id="opportunityDecisionTable"',
        'id="opportunityDecisionBody"',
        'id="marketHeatmapRetry"',
        'id="marketIndicatorsRetry"',
        'role="img"',
        'aria-label="Ma trận cơ hội khu vực"',
        'aria-label="Biểu đồ xu hướng giá theo khu vực"',
        'aria-pressed="true"',
        'data-market-sort-col="mos"',
        'onclick="sortOpportunityDecisionTable',
        "Bảng tóm tắt cơ hội khu vực",
    ]:
        assert expected in html

    for expected in [
        "MARKET_TREND_MAX_SERIES",
        "renderMarketScopeSummary",
        "renderOpportunityDecisionTable",
        "sortOpportunityDecisionTable",
        "aria-sort",
        "_marketPayloadRows",
        "renderMarketErrorState",
        "marketIndicatorsRetry",
        "market_opportunity_drilldown",
    ]:
        assert expected in market_js

    assert "button.setAttribute('aria-pressed'" in filters_js
    assert ".market-scope-summary" in market_css
    assert ".market-sort-btn" in market_css
    assert ".opportunity-decision-table" in market_css
    assert ".market-indicator-card.is-tier-locked:not(.area-risk-radar-card)" in market_css
    assert "min-height: 44px" in market_css
