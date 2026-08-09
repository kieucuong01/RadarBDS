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
    assert "admin-v52-marketing-funnel" in template
    assert "/admin/api/growth?period=" in script
    assert "include_guland=" in script
    assert "prefers-reduced-motion" in script
    assert "Đăng ký · toàn hệ thống" in script
    assert ".growth-kpis" in styles
    assert "@media (max-width: 600px)" in styles


def test_growth_marketing_ui_is_truthful_accessible_and_responsive():
    template = (ROOT / "templates" / "admin_control_room.html").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "css" / "admin.css").read_text(encoding="utf-8")

    for marker in (
        'id="growthMarketing"',
        'id="growthMarketingChannels"',
        'id="growthMarketingCoverage"',
        'id="growthLandingTableBody"',
        'id="growthCampaignTableBody"',
        'id="growthCtaTableBody"',
        'id="growthMarketingEmpty"',
    ):
        assert marker in template
    assert 'id="growthMarketingCoverage"' in template
    assert 'aria-live="polite"' in template
    assert "Lead gán trực tiếp" in template
    assert "lượt sự kiện, không phải số người duy nhất" in template
    assert "growthMarketingExport" not in template
    assert "function renderGrowthMarketing" in script
    assert "renderGrowthMarketing(data.marketing)" in script
    assert "directly_attributed" in script
    assert "esc(" in script[script.index("function renderGrowthMarketing"):]
    assert "growthFmt(" in script[script.index("function renderGrowthMarketing"):]
    assert ".growth-marketing-grid" in styles
    assert ".growth-marketing-channels" in styles
    assert "grid-template-columns: repeat(5" in styles
    assert "@media (max-width: 1000px)" in styles
    assert "@media (max-width: 600px)" in styles


def test_growth_marketing_workflow_defines_attribution_boundaries():
    workflow = (ROOT / "docs" / "growth_marketing_workflow.md").read_text(
        encoding="utf-8"
    )

    for marker in (
        "legacy_unknown",
        "directly attributed",
        "event counts",
        "unattributed",
        "IP, user-agent, or timestamp proximity",
        "20,000",
        "5,000",
    ):
        assert marker in workflow


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


def test_growth_backend_builds_marketing_inside_existing_connection_scope():
    growth_source = (ROOT / "services" / "admin_growth.py").read_text(
        encoding="utf-8"
    )
    connection_start = growth_source.index("with db_mod.get_conn() as conn:")
    aggregation_call = growth_source.index("build_marketing_source_view(")
    connection_end = growth_source.index("raw_events =", connection_start)

    assert connection_start < aggregation_call < connection_end
    assert "build_marketing_source_view(\n            conn," in growth_source
    assert growth_source.count("with db_mod.get_conn() as conn:") == 1


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


def test_facebook_profile_stats_filters_recent_raw_before_expensive_joins():
    quality_source = (ROOT / "services" / "admin_quality.py").read_text(encoding="utf-8")
    stats_fn = quality_source[quality_source.index("def facebook_profile_stats"):quality_source.index("def normalize_facebook_profile_url")]

    assert "WITH recent_raw AS" in stats_fn
    assert "profile_url" in stats_fn
    assert "profile_predicates" in stats_fn
    assert "r.profile_url IS NOT NULL" in stats_fn
    assert "FACEBOOK_PROFILE_STATS_LIMIT" in stats_fn
    assert "recent_listing AS" in stats_fn
    assert "JOIN recent_listing rl" in stats_fn
    assert "FROM recent_raw r" in stats_fn
    assert "FROM listing_images img" in stats_fn
    assert "WHERE img.listing_id = l.id" not in stats_fn
    assert "FROM valuation_results v" in stats_fn
    assert "WHERE v.listing_id = l.id" not in stats_fn
    assert "LIMIT ?" in stats_fn
    assert "FROM listing_images\n                    GROUP BY listing_id" not in stats_fn
    assert "FROM valuation_results\n                    GROUP BY listing_id" not in stats_fn


def test_facebook_duplicate_analysis_uses_indexable_recent_window():
    quality_source = (ROOT / "services" / "admin_quality.py").read_text(encoding="utf-8")
    duplicate_fn = quality_source[quality_source.index("def facebook_profile_duplicate_analysis"):quality_source.index("def missing_image_summary")]

    assert "cutoff_iso" in duplicate_fn
    assert "l.crawled_at >= ?" in duplicate_fn
    assert "r.crawled_at >= ?" in duplicate_fn
    assert "::timestamp" not in duplicate_fn
    assert "CURRENT_TIMESTAMP - INTERVAL '90 days'" not in duplicate_fn


def test_facebook_crawl_admin_is_task_first_and_loads_focused_module():
    template = (ROOT / "templates" / "admin_control_room.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "admin.css").read_text(encoding="utf-8")

    for view in ("overview", "brokers", "run"):
        assert f'data-crawl-view="{view}"' in template
        assert f'id="crawlView-{view}"' in template
    assert 'id="crawlUnsavedBadge"' in template
    assert 'id="crawlBrokerDrawer"' in template
    assert 'id="crawlRunPreview"' in template
    assert 'id="crawlJobHistory"' in template
    assert "<details" in template
    assert "Tác vụ nâng cao" in template
    assert "js/admin/facebook-crawl.js" in template
    assert "?v=admin-facebook-crawl-v2-broker-delete-ui" in template
    assert "css/admin.css') }}?v=admin-v52-marketing-funnel" in template
    assert "RadarFacebookCrawlAdmin" in script
    assert "RadarFacebookCrawlAdmin?.canLeave()" in script
    assert "/admin/api/facebook-crawl/config" not in (
        ROOT / "static" / "js" / "admin" / "facebook-crawl.js"
    ).read_text(encoding="utf-8")
    assert ".facebook-crawl-shell" in css
    assert ".crawl-broker-drawer" in css
    assert "@media (max-width: 760px)" in css
    assert "min-height: 44px" in css


def test_facebook_crawl_mobile_drawer_stays_in_viewport_with_touch_sized_actions():
    css = (ROOT / "static" / "css" / "admin.css").read_text(encoding="utf-8")
    mobile_css = css[css.index("@media (max-width: 760px)", css.index(".facebook-crawl-shell")):]

    assert ".crawl-broker-drawer { width: 100%; max-width: 440px; }" in mobile_css
    assert ".crawl-drawer-actions button { min-height: 44px; }" in mobile_css


def test_facebook_broker_actions_have_explicit_safe_delete_and_responsive_styles():
    source = (ROOT / "static" / "js" / "admin" / "facebook-crawl.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "admin.css").read_text(encoding="utf-8")

    assert "Tin đã crawl vẫn được giữ nguyên" in source
    assert "crawl-broker-actions" in source
    assert ".crawl-broker-actions" in css
    assert ".danger-btn" in css


def test_data_quality_items_cache_payload_and_ward_metadata():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    items_route = app_source[app_source.index("def admin_api_data_quality_items"):app_source.index("def _admin_review_items_response")]
    review_fn = app_source[app_source.index("def _admin_review_items_response"):app_source.index("def admin_api_legal_verification")]

    assert '_cached_admin_read_payload("data_quality_items"' in items_route
    assert '_cached_admin_read_payload("data_quality_item_wards"' in review_fn
    assert 'scope == "data_quality_summary"' in app_source
    assert '"data_quality_items"' in app_source
    assert '"data_quality_item_wards"' in app_source


def test_data_quality_qc_queues_skip_redundant_pending_count():
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    review_fn = app_source[app_source.index("def _admin_review_items_response"):app_source.index("def admin_api_legal_verification")]

    qc_fast_path = 'if queue in ("source_qc", "needs_valuation", "legal_qc"):'
    assert qc_fast_path in review_fn
    assert review_fn.index(qc_fast_path) < review_fn.index("AND f.id IS NULL")

