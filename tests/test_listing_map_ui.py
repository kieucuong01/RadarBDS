import re


def _client():
    import app as app_module

    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def test_dashboard_renders_lazy_accessible_map_launcher_and_workspace():
    response = _client().get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert (
        '<button id="listingMapLauncher" type="button"'
        in html
    )
    assert 'aria-controls="listingMapWorkspace"' in html
    assert "Xem trên Maps" in html
    assert 'class="listing-map-launcher-icon"' in html
    assert 'aria-hidden="true"' in html
    assert 'id="listingMapWorkspace"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-labelledby="listingMapTitle"' in html
    assert 'aria-describedby="listingMapDescription"' in html
    assert 'id="listingMapClose"' in html
    assert 'aria-label="Đóng bản đồ"' in html
    assert 'id="listingMapStatus"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-busy="false"' in html
    assert (
        "tọa độ, tuyến đường, khu dân cư, vùng gần đúng hoặc "
        "trung tâm phường"
    ) in html
    assert 'class="listing-map-precision-legend"' in html
    for precision in ("exact", "road", "landmark", "nearby", "ward"):
        assert f"listing-map-precision-{precision}" in html
    for hook in (
        "listingMapCanvas",
        "listingMapPanel",
        "listingMapMobileSheet",
    ):
        assert f'id="{hook}"' in html
    assert "static/js/main/listing_map.js" in html
    assert "static/css/main/listing_map.css" in html
    assert html.count("listing-map-location-coverage-20260729") == 2
    assert "window.RADAR_MAP_VENDOR" in html
    assert not re.search(
        r"<(?:script|link)[^>]+(?:leaflet\.js|leaflet\.css)",
        html,
        re.I,
    )


def test_workspace_links_to_official_gis_without_hosted_planning_layers():
    response = _client().get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="listingMapOfficialGisLink"' in html
    assert (
        'href="https://gisxaydung.tphcm.gov.vn/tracuuttqh"'
        in html
    )
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html
    assert "Quy hoạch sử dụng đất &amp; xây dựng" in html
    assert "Mở GIS quy hoạch chính thức" in html
    assert "không thay thế xác nhận pháp lý cho từng thửa đất" in html
    for forbidden_hook in (
        "listingMapPlanningControls",
        "listingMapPlanningLegend",
        "RADAR_LISTING_PLANNING_MANIFEST",
    ):
        assert forbidden_hook not in html


def test_saved_listings_route_omits_map_launcher_and_workspace():
    response = _client().get("/bds-da-luu")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="listingMapLauncher"' not in html
    assert 'id="listingMapWorkspace"' not in html


def test_launcher_contract_supports_only_deal_and_listing_tabs():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    core = (root / "static/js/main/core.js").read_text(encoding="utf-8")
    listings = (root / "static/js/main/listings.js").read_text(
        encoding="utf-8"
    )
    layout = (root / "static/css/main/layout.css").read_text(
        encoding="utf-8"
    )

    assert "function syncListingMapLauncher" in core
    assert "tabId === 'signals' || tabId === 'all'" in core
    assert "function getListingMapFilterSnapshot" in core
    assert "window.openListingMap = lazyOpenListingMap" in core
    assert "syncListingMapLauncher(tabId)" in core
    assert "window.RadarListingsState" in listings
    assert "isCompleteOnly" in listings
    assert ".listing-map-launcher" in layout
    assert "position: fixed" in layout
    assert "left: 50%" in layout
    assert "bottom: 28px" in layout


def test_workspace_js_has_history_focus_abort_and_honest_group_contracts():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    script = (root / "static/js/main/listing_map.js").read_text(
        encoding="utf-8"
    )
    styles = (root / "static/css/main/listing_map.css").read_text(
        encoding="utf-8"
    )

    for contract in (
        "new AbortController()",
        "summarySequence += 1",
        "itemSequence += 1",
        "root.history.pushState",
        'win.addEventListener("popstate"',
        'event.key === "Escape"',
        'event.key !== "Tab"',
        "state.map.remove()",
        "state.previousFocus.focus()",
        "root.L.circle(",
        "root.L.circleMarker",
        "precisionCopy(group.precision)",
        "safeCount(summary.unmapped_count)",
        "safeCount(summary.landmark_count)",
        "safeCount(summary.nearby_count)",
        'script.crossOrigin = "anonymous"',
        'link.crossOrigin = "anonymous"',
    ):
        assert contract in script
    assert "item.description" not in script
    assert "@media (max-width: 760px)" in styles
    assert "max-height: min(47vh, 410px)" in styles
    assert "min-height: 44px" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles
    assert ".listing-map-precision-landmark" in styles
    assert ".listing-map-precision-nearby" in styles


def test_official_gis_tracking_is_mode_only_and_does_not_deep_link():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    script = (root / "static/js/main/listing_map.js").read_text(
        encoding="utf-8"
    )

    assert '"listing_map_official_gis_opened"' in script
    tracking_call = re.search(
        r'emitTrack\("listing_map_official_gis_opened",\s*\{([^}]*)\}\)',
        script,
        re.S,
    )
    assert tracking_call
    assert re.findall(r"([a-z_]+)\s*:", tracking_call.group(1)) == ["mode"]
    assert "listingMapOfficialGisLink" in script
    assert "gisxaydung.tphcm.gov.vn" not in script
