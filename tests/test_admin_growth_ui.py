from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_growth_admin_ui_contract():
    template = (ROOT / "templates" / "admin_control_room.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "css" / "admin.css").read_text(encoding="utf-8")

    for marker in (
        'id="panel-growth"',
        'data-panel-slug="tang-truong"',
        'id="growthAnchor"',
        'id="growthIncludeGuland"',
        'id="growthSourceChart"',
        'id="growthUniqueChart"',
        'id="growthDropChart"',
        'id="growthUserChart"',
        'id="growthTableBody"',
    ):
        assert marker in template
    assert "growth: 'tang-truong'" in script
    assert template.index('id="panel-infra"') < template.index('id="panel-growth"') < template.index('id="panel-users"')
    assert "chart.js@4.4.4" not in template
    assert "GROWTH_CHART_SRC" in script
    assert "ensureGrowthChartLibrary" in script
    assert "chart.js@4.4.4" in script
    user_select = template[template.index('id="userTierFilter"'):template.index('id="userTable"', template.index('id="userTierFilter"'))]
    assert "chart.js@4.4.4" not in user_select
    assert "admin-v48-admin-client-cache" in template
    assert "/admin/api/growth?period=" in script
    assert "include_guland=" in script
    assert "prefers-reduced-motion" in script
    assert "Đăng ký · toàn hệ thống" in script
    assert ".growth-kpis" in styles
    assert "@media (max-width: 600px)" in styles


def test_admin_review_items_batch_listing_images():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    response_fn = app_source[app_source.index("def _admin_review_items_response"):app_source.index("def admin_api_ai_training_disagreements")]

    assert "image_urls_by_listing" in response_fn
    assert "WHERE listing_id IN" in response_fn
    assert "WHERE listing_id=? ORDER BY" not in response_fn
    assert "latest_feedback AS MATERIALIZED" in response_fn
    assert "latest_review AS MATERIALIZED" in response_fn
    assert "LEFT JOIN latest_feedback f ON f.listing_id = l.id" in response_fn
    assert "LEFT JOIN latest_review r ON r.listing_id = l.id" in response_fn
    assert "SELECT id FROM ai_training_feedback" not in response_fn
    assert "SELECT id FROM ai_deal_review" not in response_fn


def test_admin_read_cache_covers_child_tabs():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "def _cached_admin_read_payload" in app_source
    for scope in (
        "facebook_crawl_config",
        "growth",
        "leads",
        "infra",
        "data_quality_summary",
        "duplicates",
        "blacklist",
        "users",
        "audit",
        "training_disagreements",
        "qc_signals",
    ):
        assert f'"{scope}"' in app_source


def test_admin_auxiliary_reads_are_bounded_and_cached():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    qc_signals_fn = app_source[app_source.index("def admin_api_qc_signals"):app_source.index("def admin_api_data_quality_summary")]
    disagreements_fn = app_source[app_source.index("def admin_api_ai_training_disagreements"):app_source.index("def admin_api_qc_duplicates")]
    audit_fn = app_source[app_source.index("def admin_api_audit"):app_source.index("# Admin: User management")]

    assert "_cached_admin_read_payload(\"qc_signals\"" in qc_signals_fn
    assert "latest_feedback AS" in qc_signals_fn
    assert "LEFT JOIN latest_feedback" in qc_signals_fn
    assert "WHERE af.listing_id = l.id" not in qc_signals_fn
    assert "LIMIT 500" in qc_signals_fn
    assert "_cached_admin_read_payload(\"training_disagreements\"" in disagreements_fn
    assert "latest_feedback AS" in disagreements_fn
    assert "latest_review AS" in disagreements_fn
    assert "WHERE listing_id = l.id ORDER BY created_at DESC LIMIT 1" not in disagreements_fn
    assert "LIMIT 200" in disagreements_fn
    assert "_cached_admin_read_payload(\"audit\"" in audit_fn
    assert "LIMIT 200" in audit_fn


def test_admin_client_get_cache_dedupes_tab_reads_and_skips_polling():
    script = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")

    fetch_fn = script[script.index("async function fetchJSON"):script.index("function ensureToastRoot")]
    assert "ADMIN_CLIENT_CACHE_TTL_MS" in script
    assert "adminClientCache = new Map()" in script
    assert "cloneAdminPayload" in script
    assert "clearAdminClientCache" in script
    assert "clean.pathname.startsWith('/admin/api/')" in fetch_fn
    assert "!isPoll" in fetch_fn
    assert "cached.promise" in fetch_fn
    assert "method !== 'GET'" in fetch_fn
    assert "adminClientCache.delete(cacheKey)" in fetch_fn


def test_growth_backend_limits_event_queries_to_period_window():
    growth_source = (ROOT / "services" / "admin_growth.py").read_text(encoding="utf-8")

    assert "previous_iso = _storage_iso(previous)" in growth_source
    assert "crawled_at >= ?" in growth_source
    assert "SELECT source, COUNT(*) AS n" in growth_source
    assert "SUM(CASE WHEN LOWER(COALESCE(lc.status,''))" in growth_source
    assert "SELECT lc.status" not in growth_source
    assert "drop_events AS" in growth_source
    assert "SELECT created_at AS event_at FROM users" not in growth_source


def test_admin_performance_indexes_cover_growth_and_review_queries():
    schema_source = (ROOT / "db" / "schema.py").read_text(encoding="utf-8")

    for marker in (
        "idx_raw_source_crawled",
        "idx_listings_source_first_seen",
        "idx_ai_training_listing_latest",
        "idx_ai_deal_review_listing_latest",
        "idx_audit_created_user",
    ):
        assert marker in schema_source


def test_facebook_duplicate_analysis_short_circuits_single_profile_city():
    quality_source = (ROOT / "services" / "admin_quality.py").read_text(encoding="utf-8")
    duplicate_fn = quality_source[quality_source.index("def facebook_profile_duplicate_analysis"):quality_source.index("def missing_image_summary")]

    assert "profiles_by_city" in duplicate_fn
    assert "count >= 2" in duplicate_fn
    assert duplicate_fn.index("count >= 2") < duplicate_fn.index("with conn_factory() as conn")

