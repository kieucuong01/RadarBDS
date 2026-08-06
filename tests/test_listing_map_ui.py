import re
import shutil
from pathlib import Path

import pytest


def _client():
    import app as app_module

    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def _chrome_executable():
    candidates = [
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    pytest.skip("Chrome/Chromium executable is unavailable")


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
    assert "tọa độ, tuyến đường, khu dân cư hoặc trung tâm phường" in html
    assert 'class="listing-map-precision-legend"' in html
    for precision in ("exact", "road", "landmark", "ward"):
        assert f"listing-map-precision-{precision}" in html
    for hook in (
        "listingMapCanvas",
        "listingMapPanel",
        "listingMapMobileSheet",
    ):
        assert f'id="{hook}"' in html
    assert 'id="listingMapMobileSheet"' in html
    assert 'data-state="collapsed"' in html
    assert "static/js/main/listing_map.js" in html
    assert "static/css/main/listing_map.css" in html
    assert html.count("listing-map-exact-labels-20260807") == 2
    assert "window.RADAR_MAP_VENDOR" in html
    assert not re.search(
        r"<(?:script|link)[^>]+(?:leaflet\.js|leaflet\.css)",
        html,
        re.I,
    )


def test_workspace_omits_official_gis_and_nearby_visuals():
    response = _client().get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "listing-map-official-gis" not in html
    assert "listingMapOfficialGisLink" not in html
    assert "Quy hoạch sử dụng đất &amp; xây dựng" not in html
    assert "listing-map-precision-nearby" not in html
    assert "Gần đúng" not in html


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


def test_listing_map_assets_warm_without_blocking_initial_dashboard_render():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    core = (root / "static/js/main/core.js").read_text(encoding="utf-8")

    assert "function warmListingMapAssets" in core
    assert "window.RadarListingMap.loadLeaflet()" in core
    assert "requestIdleCallback" in core
    assert "pointerenter" in core
    assert "focus" in core
    assert "await warmListingMapAssets()" in core


def test_all_listings_script_warms_after_load_and_before_tab_click():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    core = (root / "static/js/main/core.js").read_text(encoding="utf-8")

    assert "function warmListingsAssets" in core
    assert "function scheduleListingsWarmup" in core
    assert 'querySelectorAll(\'[data-tab-target="all"]\')' in core
    assert "await warmListingsAssets()" in core


def test_dashboard_badges_do_not_render_a_false_zero_before_counts_load():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    html = (root / "templates/index.html").read_text(encoding="utf-8")
    core = (root / "static/js/main/core.js").read_text(encoding="utf-8")
    placeholder = chr(0x2026)

    for badge_id in (
        "badgeSignals",
        "badgeTotal",
        "mobileBadgeSignals",
        "mobileBadgeTotal",
    ):
        assert re.search(
            rf'id="{badge_id}"[^>]*>{re.escape(placeholder)}<', html
        )
        assert not re.search(rf'id="{badge_id}"[^>]*>0<', html)
    assert f"source.textContent || '{placeholder}'" in core


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
        "root.L.circleMarker",
        "precisionCopy(group.precision)",
        "safeCount(summary.unmapped_count)",
        "safeCount(summary.landmark_count)",
        'script.crossOrigin = "anonymous"',
        'link.crossOrigin = "anonymous"',
    ):
        assert contract in script
    assert "item.description" not in script
    assert "@media (max-width: 760px)" in styles
    assert "min-height: 44px" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles
    assert ".listing-map-precision-landmark" in styles
    assert "root.L.circle(" not in script
    assert "safeCount(summary.nearby_count)" not in script
    assert "listing_map_official_gis_opened" not in script
    assert "listingMapOfficialGisLink" not in script
    assert ".listing-map-precision-nearby" not in styles
    assert ".listing-map-official-gis" not in styles


def test_listing_map_exact_marker_labels_are_compact_two_rows():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    styles = (root / "static/css/main/listing_map.css").read_text(
        encoding="utf-8"
    )

    assert ".listing-map-exact-label" in styles
    assert ".listing-map-exact-label-main" in styles
    assert ".listing-map-exact-label-sub" in styles
    assert "font-size: 0.58rem" in styles
    assert "line-height: 1.12" in styles


def test_listing_map_workspace_body_gets_stable_remaining_height():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    styles = (root / "static/css/main/listing_map.css").read_text(
        encoding="utf-8"
    )

    assert "grid-template-rows: auto auto minmax(0, 1fr);" in styles
    assert "grid-template-rows: auto auto auto minmax(0, 1fr);" not in styles


def test_mobile_leaflet_canvas_keeps_full_remaining_viewport_height():
    playwright = pytest.importorskip("playwright.sync_api")
    css = Path("static/css/main/listing_map.css").read_text(encoding="utf-8")
    html = f"""
    <style>{css}</style>
    <style>
      .leaflet-container {{ position: relative; overflow: hidden; }}
    </style>
    <body class="listing-map-open">
      <section class="listing-map-workspace">
        <header class="listing-map-workspace-head"><h2>Maps</h2></header>
        <div class="listing-map-status">Đang tải</div>
        <div class="listing-map-workspace-body">
          <div class="listing-map-canvas leaflet-container"></div>
          <aside class="listing-map-panel"></aside>
        </div>
        <div class="listing-map-mobile-sheet"></div>
      </section>
    </body>
    """

    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(
            executable_path=_chrome_executable(),
            headless=True,
        )
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.set_content(html)
        metrics = page.locator(".listing-map-canvas").evaluate(
            """element => {
              const rect = element.getBoundingClientRect();
              return {
                position: getComputedStyle(element).position,
                height: rect.height,
              };
            }"""
        )
        browser.close()

    assert metrics["position"] == "absolute"
    assert metrics["height"] > 700
