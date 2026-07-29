from __future__ import annotations

import json
import subprocess
from pathlib import Path


MAP_SCRIPT = Path("static/js/main/listing_map.js")


def _run_node(expression: str):
    result = subprocess.run(
        [
            "node",
            "-e",
            (
                f"const mapApi = require({json.dumps(str(MAP_SCRIPT.resolve()))});"
                f"process.stdout.write(JSON.stringify({expression}));"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_mode_base_layer_and_precision_contracts():
    assert _run_node("mapApi.normalizeMode('signals')") == "signals"
    assert _run_node("mapApi.normalizeMode('all')") == "all"
    assert _run_node("mapApi.normalizeMode('market')") is None
    assert _run_node("mapApi.normalizeBaseLayer('satellite')") == "satellite"
    assert _run_node("mapApi.normalizeBaseLayer('broken')") == "street"
    assert _run_node("mapApi.precisionCopy('road').badge") == "Theo tên đường"
    assert (
        _run_node("mapApi.precisionCopy('ward').badge")
        == "Theo trung tâm phường"
    )


def test_summary_and_item_urls_preserve_frozen_filter_snapshot():
    snapshot = "{mode:'all',query:'city=TH%E1%BB%A6+D%E1%BA%A6U+M%E1%BB%98T&ward=Ph%C3%BA+L%E1%BB%A3i&complete=1'}"
    summary = _run_node(f"mapApi.buildSummaryUrl({snapshot})")
    items = _run_node(
        f"mapApi.buildItemsUrl({snapshot},"
        "'ward:thu-dau-mot:phu-loi',2,500)"
    )

    assert summary.startswith("/api/map-listings?")
    assert "mode=all" in summary
    assert "complete=1" in summary
    assert "ward=Ph%C3%BA+L%E1%BB%A3i" in summary
    assert items.startswith("/api/map-listing-items?")
    assert "location_key=ward%3Athu-dau-mot%3Aphu-loi" in items
    assert "page=2" in items
    assert "limit=50" in items
    assert _run_node(
        f"mapApi.buildItemsUrl({snapshot},'bad key',1,20)"
    ) is None


def test_map_base_layers_have_complete_attribution():
    layers = _run_node("mapApi.mapBaseLayers()")

    assert set(layers) == {"street", "satellite"}
    assert "openstreetmap.org" in layers["street"]["url"]
    assert "OpenStreetMap" in layers["street"]["attribution"]
    assert "World_Imagery" in layers["satellite"]["url"]
    assert "Esri" in layers["satellite"]["attribution"]
    assert "Maxar" in layers["satellite"]["attribution"]


def test_tracking_context_is_strictly_allowlisted():
    result = _run_node(
        "mapApi.safeTrackingContext({"
        "mode:'signals',precision:'road',listing_count:3,"
        "mapped_count:8,unmapped_count:2,group_count:4,"
        "layer_ids:['street','planning-land-use','BAD VALUE'],"
        "base_layer_id:'satellite',close_reason:'button',"
        "lat:10.99,lng:106.67,listing_id:42,keyword:'secret'"
        "})"
    )

    assert result == {
        "mode": "signals",
        "precision": "road",
        "listing_count": 3,
        "mapped_count": 8,
        "unmapped_count": 2,
        "group_count": 4,
        "layer_ids": ["street", "planning-land-use"],
        "base_layer_id": "satellite",
        "close_reason": "button",
    }


def test_official_gis_tracking_context_strips_outbound_and_location_data():
    result = _run_node(
        "mapApi.safeTrackingContext({"
        "mode:'all',"
        "official_gis_url:'https://gisxaydung.tphcm.gov.vn/tracuuttqh',"
        "lat:10.99,lng:106.67,location_key:'road:secret',keyword:'secret'"
        "})"
    )

    assert result == {"mode": "all"}


def test_listing_map_item_navigation_targets_internal_detail_page():
    result = _run_node(
        "(function(){"
        "let assigned=null;"
        "const fakeRoot={location:{assign:function(url){assigned=url;}}};"
        "return {"
        "valid:mapApi.navigateToListingDetail(fakeRoot,{id:42}),"
        "assigned:assigned"
        "};"
        "})()"
    )

    assert result == {"valid": True, "assigned": "/listing/42"}


def test_listing_map_item_navigation_ignores_missing_ids():
    result = _run_node(
        "(function(){"
        "let assigned=null;"
        "const fakeRoot={location:{assign:function(url){assigned=url;}}};"
        "return {"
        "valid:mapApi.navigateToListingDetail(fakeRoot,{title:'Tin rao'}),"
        "assigned:assigned"
        "};"
        "})()"
    )

    assert result == {"valid": False, "assigned": None}


def test_client_tracking_allowlist_includes_every_listing_map_event():
    source = MAP_SCRIPT.read_text(encoding="utf-8")
    actions = {
        "listing_map_opened",
        "listing_map_closed",
        "listing_map_base_layer_changed",
        "listing_map_group_selected",
        "listing_map_retry",
        "listing_map_official_gis_opened",
    }

    for action in actions:
        assert source.count(f'"{action}"') >= 2
