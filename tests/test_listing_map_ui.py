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
    for hook in (
        "listingMapCanvas",
        "listingMapPanel",
        "listingMapMobileSheet",
    ):
        assert f'id="{hook}"' in html
    assert "static/js/main/listing_map.js" in html
    assert "static/css/main/listing_map.css" in html
    assert "window.RADAR_MAP_VENDOR" in html
    assert not re.search(
        r"<(?:script|link)[^>]+(?:leaflet\.js|leaflet\.css)",
        html,
        re.I,
    )


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
