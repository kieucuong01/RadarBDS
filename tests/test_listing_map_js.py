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
    assert (
        _run_node("mapApi.precisionCopy('landmark').badge")
        == "Theo khu vực"
    )
    assert (
        _run_node("mapApi.precisionCopy('nearby').badge")
        == "Theo tên đường"
    )
    assert _run_node("mapApi.normalizeAccuracyRadius(150)") == 150
    assert _run_node("mapApi.normalizeAccuracyRadius(-1)") == 0
    assert _run_node("mapApi.normalizeAccuracyRadius(100000)") == 20000


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
        f"mapApi.buildItemsUrl({snapshot},"
        "'landmark:thu-dau-mot:phu-tan:tdc-phu-chanh-b',1,20)"
    ).startswith("/api/map-listing-items?")
    assert _run_node(
        f"mapApi.buildItemsUrl({snapshot},"
        "'nearby:thu-dau-mot:phu-tan:dx-96:near',1,20)"
    ) is None
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


def test_map_prefers_canvas_for_large_marker_sets():
    assert _run_node("mapApi.mapOptions()") == {
        "zoomControl": True,
        "scrollWheelZoom": True,
        "preferCanvas": True,
    }


def test_active_panel_id_selects_exactly_one_responsive_surface():
    assert _run_node("mapApi.activePanelId(false)") == "listingMapPanel"
    assert _run_node("mapApi.activePanelId(true)") == "listingMapMobileSheet"


def test_directory_window_limits_initial_and_incremental_dom_to_100():
    assert _run_node("mapApi.directoryWindow(1837,0)") == {
        "visible": 100,
        "nextVisible": 200,
        "remaining": 1737,
    }
    assert _run_node("mapApi.directoryWindow(1837,100)") == {
        "visible": 100,
        "nextVisible": 200,
        "remaining": 1737,
    }
    assert _run_node("mapApi.directoryWindow(1837,1800)") == {
        "visible": 1800,
        "nextVisible": 1837,
        "remaining": 37,
    }
    assert _run_node("mapApi.directoryWindow(42,0)") == {
        "visible": 42,
        "nextVisible": 42,
        "remaining": 0,
    }


def test_panel_render_model_targets_one_surface_and_slices_locations():
    result = _run_node(
        "(function(){"
        "const locations=Array.from({length:105},(_,i)=>({id:i}));"
        "const model=mapApi.panelRenderModel(true,locations,0);"
        "return {"
        "active:model.activePanelId,"
        "inactive:model.inactivePanelId,"
        "ids:model.groups.map(group=>group.id),"
        "remaining:model.remaining,"
        "nextVisible:model.nextVisible"
        "};"
        "})()"
    )

    assert result == {
        "active": "listingMapMobileSheet",
        "inactive": "listingMapPanel",
        "ids": list(range(100)),
        "remaining": 5,
        "nextVisible": 105,
    }


def test_panel_render_model_omits_exact_locations_from_directory():
    result = _run_node(
        "(function(){"
        "const locations=["
        "{id:'e1',precision:'exact'},"
        "{id:'r1',precision:'road'},"
        "{id:'l1',precision:'landmark'},"
        "{id:'w1',precision:'ward'}"
        "];"
        "const model=mapApi.panelRenderModel(false,locations,0);"
        "return {"
        "ids:model.groups.map(group=>group.id),"
        "remaining:model.remaining,"
        "visible:model.visible"
        "};"
        "})()"
    )

    assert result == {
        "ids": ["r1", "l1", "w1"],
        "remaining": 0,
        "visible": 3,
    }


def test_marker_label_model_uses_compact_price_rows_for_exact_and_single_road():
    for precision, priority in (("exact", 0), ("road", 1)):
        result = _run_node(
            "mapApi.markerLabelModel({"
            f"precision:'{precision}',listing_count:1,"
            "price_ty:1.8,area_m2:100,price_per_m2:18"
            "},13)"
        )

        assert result["visible"] is True
        assert result["kind"] == "price"
        assert result["priority"] == priority
        assert result["line1"] == "1,8 tỷ · 100m²"
        assert result["line2"] == "18tr/m²"

    assert _run_node(
        "mapApi.markerLabelModel({"
        "precision:'exact',listing_count:1,price_ty:1.8,"
        "area_m2:100,price_per_m2:18"
        "},12).visible"
    ) is False


def test_marker_label_model_uses_count_badges_for_grouped_locations():
    cases = (
        ("road", 3, 2),
        ("landmark", 1, 3),
        ("ward", 8, 4),
    )
    for precision, count, priority in cases:
        result = _run_node(
            "mapApi.markerLabelModel({"
            f"precision:'{precision}',listing_count:{count}"
            "},9)"
        )
        assert result["visible"] is True
        assert result["kind"] == "count"
        assert result["priority"] == priority
        assert result["line1"] == f"{count} tin"
        assert result["line2"] == ""


def test_marker_label_model_does_not_replace_invalid_single_price_with_count():
    for precision in ("exact", "road"):
        assert _run_node(
            "mapApi.markerLabelModel({"
            f"precision:'{precision}',listing_count:1,"
            "price_ty:null,area_m2:100,price_per_m2:null"
            "},16).visible"
        ) is False


def test_marker_label_rect_uses_each_model_dimensions():
    result = _run_node(
        "(function(){"
        "const price=mapApi.markerLabelModel({"
        "precision:'exact',listing_count:1,price_ty:1.8,"
        "area_m2:100,price_per_m2:18},13);"
        "const count=mapApi.markerLabelModel({"
        "precision:'ward',listing_count:8},9);"
        "return {price:mapApi.markerLabelRect({x:100,y:100},price),"
        "count:mapApi.markerLabelRect({x:100,y:100},count)};"
        "})()"
    )
    assert result["price"]["right"] - result["price"]["left"] == 92
    assert result["price"]["bottom"] - result["price"]["top"] == 30
    assert result["count"]["right"] - result["count"]["left"] == 44
    assert result["count"]["bottom"] - result["count"]["top"] == 18


def test_closer_initial_zoom_opens_at_fourteen_with_cap():
    assert _run_node("mapApi.closerInitialZoom(8)") == 14
    assert _run_node("mapApi.closerInitialZoom(12)") == 14
    assert _run_node("mapApi.closerInitialZoom(13)") == 14
    assert _run_node("mapApi.closerInitialZoom(14)") == 15
    assert _run_node("mapApi.closerInitialZoom(15)") == 16
    assert _run_node("mapApi.closerInitialZoom(16)") == 16
    assert _run_node("mapApi.closerInitialZoom('broken')") == 14


def test_current_location_zoom_never_zooms_out():
    assert _run_node("mapApi.locationTargetZoom(14)") == 16
    assert _run_node("mapApi.locationTargetZoom(16)") == 16
    assert _run_node("mapApi.locationTargetZoom(18)") == 18
    assert _run_node("mapApi.locationTargetZoom('broken')") == 16


def test_geolocation_errors_use_concise_vietnamese_copy():
    assert _run_node(
        "mapApi.geolocationErrorMessage({code:1})"
    ) == "Bạn chưa cấp quyền vị trí."
    assert _run_node(
        "mapApi.geolocationErrorMessage({code:2})"
    ) == "Không xác định được vị trí."
    assert _run_node(
        "mapApi.geolocationErrorMessage({code:3})"
    ) == "Định vị quá thời gian, hãy thử lại."
    assert _run_node(
        "mapApi.geolocationErrorMessage({code:99})"
    ) == "Không thể định vị lúc này."


def test_stale_or_closed_location_callbacks_are_rejected():
    assert _run_node(
        "mapApi.isCurrentLocationCallback(4,4,true,true)"
    ) is True
    assert _run_node(
        "mapApi.isCurrentLocationCallback(3,4,true,true)"
    ) is False
    assert _run_node(
        "mapApi.isCurrentLocationCallback(4,4,false,true)"
    ) is False
    assert _run_node(
        "mapApi.isCurrentLocationCallback(4,4,true,false)"
    ) is False


def test_marker_label_class_identifies_singleton_road_price():
    result = _run_node(
        "(function(){const group={precision:'road',listing_count:1,"
        "price_ty:1.8,area_m2:100,price_per_m2:18};"
        "const model=mapApi.markerLabelModel(group,14);"
        "return mapApi.markerLabelClassName(group,model);})()"
    )
    assert result == (
        "listing-map-marker-label listing-map-marker-label-price "
        "listing-map-marker-label-precision-road"
    )


def test_exact_marker_label_collision_uses_screen_rect_gap():
    assert _run_node(
        "mapApi.labelRectCollides("
        "{left:10,top:10,right:80,bottom:40},"
        "[{left:75,top:12,right:120,bottom:44}],"
        "6)"
    ) is True
    assert _run_node(
        "mapApi.labelRectCollides("
        "{left:10,top:10,right:80,bottom:40},"
        "[{left:90,top:12,right:130,bottom:44}],"
        "6)"
    ) is False


def test_batch_ranges_split_dom_work_without_gaps_or_overlap():
    assert _run_node("mapApi.batchRanges(0,25)") == []
    assert _run_node("mapApi.batchRanges(100,25)") == [
        [0, 25],
        [25, 50],
        [50, 75],
        [75, 100],
    ]
    assert _run_node("mapApi.batchRanges(105,25)") == [
        [0, 25],
        [25, 50],
        [50, 75],
        [75, 100],
        [100, 105],
    ]


def test_next_marker_batch_advances_by_200_and_finishes_exactly():
    assert _run_node("mapApi.nextBatch(450,0,200)") == {
        "start": 0,
        "end": 200,
        "done": False,
    }
    assert _run_node("mapApi.nextBatch(450,200,200)") == {
        "start": 200,
        "end": 400,
        "done": False,
    }
    assert _run_node("mapApi.nextBatch(450,400,200)") == {
        "start": 400,
        "end": 450,
        "done": True,
    }


def test_marker_render_generation_rejects_closed_or_stale_work():
    assert _run_node("mapApi.canContinueMarkerRender(true,4,4,true)") is True
    assert _run_node("mapApi.canContinueMarkerRender(false,4,4,true)") is False
    assert _run_node("mapApi.canContinueMarkerRender(true,3,4,true)") is False
    assert _run_node("mapApi.canContinueMarkerRender(true,4,4,false)") is False


def test_mobile_sheet_model_exposes_explicit_accessible_states():
    assert _run_node("mapApi.mobileSheetModel(false,'directory')") == {
        "expanded": False,
        "state": "collapsed",
        "ariaExpanded": "false",
        "label": "Xem danh sách vị trí",
    }
    assert _run_node("mapApi.mobileSheetModel(false,'items')") == {
        "expanded": False,
        "state": "collapsed",
        "ariaExpanded": "false",
        "label": "Mở rộng",
    }
    assert _run_node("mapApi.mobileSheetModel(true,'items')") == {
        "expanded": True,
        "state": "expanded",
        "ariaExpanded": "true",
        "label": "Thu gọn",
    }


def test_selected_group_views_require_an_expanded_mobile_sheet():
    assert _run_node("mapApi.sheetExpandedForView('directory',false)") is False
    assert _run_node("mapApi.sheetExpandedForView('directory',true)") is True
    for view in ("items-loading", "items", "items-error"):
        assert _run_node(
            f"mapApi.sheetExpandedForView({json.dumps(view)},false)"
        ) is True


def test_selected_mobile_sheet_actions_remain_available_on_errors():
    for view in ("items-loading", "items"):
        assert _run_node(
            f"mapApi.selectedSheetActionModel({json.dumps(view)})"
        ) == {
            "backLabel": "← Tất cả vị trí",
            "retryLabel": None,
        }
    assert _run_node(
        "mapApi.selectedSheetActionModel('items-error')"
    ) == {"backLabel": "← Tất cả vị trí", "retryLabel": "Thử lại"}


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


def test_listing_map_item_click_opens_existing_modal_without_navigation():
    result = _run_node(
        "(function(){"
        "let assigned=null;"
        "let modalDataset=null;"
        "const fakeRoot={"
        "document:{createElement:function(){return {dataset:{}};}},"
        "location:{assign:function(url){assigned=url;}},"
        "openListingModal:function(proxy){modalDataset=proxy.dataset;}"
        "};"
        "return {"
        "valid:mapApi.openListingFromMap(fakeRoot,{"
        "id:42,title:'Lô góc Mỹ Phước',thumbnail:'thumb.jpg',"
        "price_ty:1.8,area_m2:90,ward:'Mỹ Phước',road_name:'NE8',"
        "prop_type:'land',prop_type_label:'Đất nền',mos_pct:18.5,"
        "source:'facebook',days_ago:0"
        "}),"
        "modalId:modalDataset && modalDataset.id,"
        "modalTitle:modalDataset && modalDataset.title,"
        "modalRoad:modalDataset && modalDataset.road,"
        "assigned:assigned"
        "};"
        "})()"
    )

    assert result == {
        "valid": True,
        "modalId": "42",
        "modalTitle": "Lô góc Mỹ Phước",
        "modalRoad": "NE8",
        "assigned": None,
    }


def test_listing_map_item_click_ignores_missing_ids_without_navigation():
    result = _run_node(
        "(function(){"
        "let assigned=null;"
        "let modalOpened=false;"
        "const fakeRoot={"
        "document:{createElement:function(){return {dataset:{}};}},"
        "location:{assign:function(url){assigned=url;}},"
        "openListingModal:function(){modalOpened=true;}"
        "};"
        "return {"
        "valid:mapApi.openListingFromMap(fakeRoot,{title:'Tin rao'}),"
        "assigned:assigned,"
        "modalOpened:modalOpened"
        "};"
        "})()"
    )

    assert result == {"valid": False, "assigned": None, "modalOpened": False}


def test_listing_map_uses_source_specific_activity_copy():
    assert (
        _run_node("mapApi.cardDateText({days_ago:0,card_date_reason:'price_updated'})")
        == "Cập nhật giá hôm nay"
    )
    assert (
        _run_node("mapApi.cardDateText({days_ago:3,card_date_reason:'first_seen'})")
        == "Theo dõi từ 3 ngày trước"
    )
    assert (
        _run_node("mapApi.cardDateText({days_ago:2,card_date_reason:'posted'})")
        == "2 ngày trước"
    )


def test_listing_map_focus_trap_yields_when_signal_modal_is_open():
    source = MAP_SCRIPT.read_text(encoding="utf-8")

    assert "function isSignalModalOpen()" in source
    assert "if (!state.open || isSignalModalOpen()) return;" in source


def test_listing_map_popstate_keeps_map_open_when_returning_from_signal_modal():
    assert _run_node(
        "mapApi.shouldCloseMapOnPopstate({state:{radarListingMap:true}}, true)"
    ) is False
    assert _run_node(
        "mapApi.shouldCloseMapOnPopstate({state:{signalModal:true}}, true)"
    ) is False
    assert _run_node(
        "mapApi.shouldCloseMapOnPopstate({state:null}, true)"
    ) is True
    assert _run_node(
        "mapApi.shouldCloseMapOnPopstate({state:null}, false)"
    ) is False


def test_client_tracking_allowlist_includes_every_listing_map_event():
    source = MAP_SCRIPT.read_text(encoding="utf-8")
    actions = {
        "listing_map_opened",
        "listing_map_closed",
        "listing_map_base_layer_changed",
        "listing_map_group_selected",
        "listing_map_retry",
    }

    for action in actions:
        assert source.count(f'"{action}"') >= 2
