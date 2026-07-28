from __future__ import annotations

import json
import subprocess
from pathlib import Path


MAP_SCRIPT = Path("static/js/binh_duong_map.js")


def _run_node(expression: str):
    result = subprocess.run(
        [
            "node",
            "-e",
            (
                f"const mapPage = require({json.dumps(str(MAP_SCRIPT.resolve()))});"
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


def test_map_hash_parser_accepts_layers_and_valid_area_slugs():
    valid = "{legacy:['thu-dau-mot'],current:['binh-duong']}"

    assert _run_node(
        f"mapPage.parseMapHash('#layer-current/area-binh-duong', {valid})"
    ) == {"layer": "current", "areaSlug": "binh-duong"}
    assert _run_node(
        f"mapPage.parseMapHash('#layer-legacy', {valid})"
    ) == {"layer": "legacy", "areaSlug": None}


def test_map_hash_parser_falls_back_for_invalid_hash_or_unknown_slug():
    valid = "{legacy:['thu-dau-mot'],current:['binh-duong']}"

    for fragment in ("#broken", "#layer-other", "#layer-current/area-nope", "#layer-%"):
        assert _run_node(
            f"mapPage.parseMapHash({json.dumps(fragment)}, {valid})"
        ) == {"layer": "legacy", "areaSlug": None}


def test_map_hash_formatter_normalizes_layer_and_slug():
    assert _run_node(
        "mapPage.formatMapHash('legacy', 'thu-dau-mot')"
    ) == "#layer-legacy/area-thu-dau-mot"
    assert _run_node(
        "mapPage.formatMapHash('current', null)"
    ) == "#layer-current"
    assert _run_node(
        "mapPage.formatMapHash('invalid', 'bad slug')"
    ) == "#layer-legacy"


def test_map_tracking_context_contains_only_safe_identifiers():
    result = _run_node(
        "mapPage.buildTrackingContext("
        "'current',"
        "{properties:{slug:'binh-duong'},geometry:{coordinates:[106.6,11.0]}},"
        "'/?tab=signals'"
        ")"
    )

    assert result == {
        "layer": "current",
        "area_slug": "binh-duong",
        "target": "/?tab=signals",
    }


def test_feature_collection_filter_keeps_only_valid_polygons_for_layer():
    payload = (
        "{type:'FeatureCollection',features:["
        "{type:'Feature',properties:{layer:'legacy',slug:'a'},geometry:{type:'Polygon',coordinates:[]}},"
        "{type:'Feature',properties:{layer:'current',slug:'b'},geometry:{type:'MultiPolygon',coordinates:[]}},"
        "{type:'Feature',properties:{layer:'legacy',slug:'c'},geometry:{type:'Point',coordinates:[]}}"
        "]}"
    )

    result = _run_node(
        f"mapPage.filterFeatureCollection({payload}, 'legacy').features"
        ".map((feature) => feature.properties.slug)"
    )

    assert result == ["a"]


def test_snapshot_slug_match_rejects_stale_same_count_data():
    matching = (
        "{type:'FeatureCollection',features:["
        "{properties:{slug:'a'}},{properties:{slug:'b'}}"
        "]}"
    )
    stale = (
        "{type:'FeatureCollection',features:["
        "{properties:{slug:'a'}},{properties:{slug:'old-b'}}"
        "]}"
    )

    assert _run_node(
        f"mapPage.matchesExpectedSlugs({matching}, ['a','b'])"
    ) is True
    assert _run_node(
        f"mapPage.matchesExpectedSlugs({stale}, ['a','b'])"
    ) is False


def test_map_options_enable_scroll_wheel_zoom():
    assert _run_node("mapPage.mapOptions()") == {
        "scrollWheelZoom": True,
        "zoomControl": True,
    }


def test_fullscreen_toggle_enters_and_exits_the_map_container():
    enter = _run_node(
        "(() => {"
        "const calls=[];"
        "const element={requestFullscreen:()=>calls.push('enter')};"
        "const doc={fullscreenElement:null};"
        "return {result:mapPage.toggleMapFullscreen(element,doc),calls};"
        "})()"
    )
    exit_fullscreen = _run_node(
        "(() => {"
        "const calls=[];"
        "const element={requestFullscreen:()=>calls.push('enter')};"
        "const doc={fullscreenElement:element,exitFullscreen:()=>calls.push('exit')};"
        "return {result:mapPage.toggleMapFullscreen(element,doc),calls};"
        "})()"
    )

    assert enter == {"result": "enter", "calls": ["enter"]}
    assert exit_fullscreen == {"result": "exit", "calls": ["exit"]}
