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
