from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pdfplumber
import pytest
from shapely.geometry import LineString, box

from map_products.geometry import (
    NamedGeometry,
    NormalizedMapLayers,
    StreetGeometry,
)
from map_products.models import MapPoint
from map_products.renderers import render_kml, render_pdf, render_svg
from map_products.scene import (
    MAP_LAYER_IDS,
    build_scene,
)


ROOT = Path(__file__).resolve().parents[1]
SVG_NS = {"svg": "http://www.w3.org/2000/svg"}
KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


@pytest.fixture
def sample_layers() -> NormalizedMapLayers:
    boundary_origins = (
        ("Thủ Dầu Một", 106.62, 10.96),
        ("Phú Lợi", 106.65, 10.96),
        ("Chánh Hiệp", 106.68, 10.96),
        ("Bình Dương", 106.62, 10.99),
        ("Phú An", 106.65, 10.99),
    )
    boundaries = tuple(
        NamedGeometry(
            name,
            box(lon, lat, lon + 0.025, lat + 0.025),
            source_id=f"current-{index}",
        )
        for index, (name, lon, lat) in enumerate(boundary_origins)
    )
    legacy_names = (
        "Chánh Mỹ",
        "Chánh Nghĩa",
        "Định Hòa",
        "Hiệp An",
        "Hiệp Thành",
        "Hòa Phú",
        "Phú Cường",
        "Phú Hòa",
        "Phú Lợi",
        "Phú Mỹ",
        "Phú Tân",
        "Phú Thọ",
        "Tân An",
        "Tương Bình Hiệp",
    )
    legacy_centers = tuple(
        MapPoint(
            name=name,
            lon=106.625 + (index % 5) * 0.014,
            lat=10.965 + (index // 5) * 0.014,
            source=f"Wikidata Q{index + 1}",
            source_url=f"https://www.wikidata.org/wiki/Q{index + 1}",
            confidence="high",
            boundary_claim=False,
        )
        for index, name in enumerate(legacy_names)
    )
    streets = (
        StreetGeometry(
            "Đại lộ Bình Dương",
            LineString(((106.621, 10.975), (106.702, 10.975))),
            "primary",
            "way/100",
        ),
        StreetGeometry(
            "Đường Phú Lợi",
            LineString(((106.655, 10.962), (106.655, 11.012))),
            "secondary",
            "way/101",
        ),
        StreetGeometry(
            "Đường thử nhãn A",
            LineString(((106.687, 11.008), (106.704, 11.008))),
            "secondary",
            "way/102",
        ),
        StreetGeometry(
            "Đường thử nhãn B",
            LineString(((106.687, 11.008), (106.704, 11.008))),
            "secondary",
            "way/103",
        ),
    )
    hydro = (
        NamedGeometry(
            "Sông Sài Gòn",
            LineString(((106.622, 10.958), (106.623, 11.014))),
            "way/200",
        ),
    )
    poi = (
        MapPoint(
            "Chợ Thủ Dầu Một",
            106.641,
            10.971,
            "OpenStreetMap node/300",
            "high",
        ),
    )
    neighborhoods = (
        MapPoint(
            "Khu dân cư Chánh Nghĩa",
            106.647,
            10.982,
            "Radar BDS",
            "high",
        ),
    )
    return NormalizedMapLayers(
        current_boundaries=boundaries,
        legacy_ward_centers=legacy_centers,
        streets=streets,
        hydro=hydro,
        poi=poi,
        neighborhoods=neighborhoods,
        source_manifest={
            "current_boundaries": {
                "license": "Open Database License",
                "license_url": "https://www.openstreetmap.org/copyright",
            },
            "legacy_ward_centers": {
                "license": "CC0",
                "license_url": "https://www.wikidata.org/wiki/Wikidata:Licensing",
            },
        },
    )


@pytest.fixture
def test_fonts() -> dict[str, Path]:
    cache = ROOT / "artifacts/map-products/thu-dau-mot/source-cache"
    fonts = {
        "regular": cache / "font.ttf",
        "semibold": cache / "font_semibold.ttf",
    }
    assert all(path.is_file() for path in fonts.values())
    return fonts


@pytest.fixture
def legacy_scene(sample_layers):
    return build_scene(sample_layers, "legacy")


def _layer(scene, layer_id: str):
    return next(layer for layer in scene.layers if layer.layer_id == layer_id)


def test_scene_projects_wgs84_once_and_enforces_edition_geometry(sample_layers):
    legacy = build_scene(sample_layers, "legacy")
    current = build_scene(sample_layers, "current")

    assert legacy.page_width_pt > legacy.page_height_pt
    assert legacy.bounds_m[0] > 100_000
    assert legacy.bounds_m == current.bounds_m
    assert {layer.layer_id for layer in legacy.layers} == set(MAP_LAYER_IDS)
    assert len(_layer(legacy, "boundaries").features) == 0
    assert len(_layer(legacy, "legacy-reference-centers").features) == 14
    assert len(_layer(current, "boundaries").features) == 5
    assert len(_layer(current, "legacy-reference-centers").features) == 0
    assert "điểm tham chiếu" in legacy.disclaimer.casefold()
    assert "không phải ranh giới" in legacy.disclaimer.casefold()
    assert current.disclaimer == ""
    assert legacy.scale_bar_m > 0
    assert "Điểm tham chiếu phường cũ" in {
        item.label for item in legacy.legend
    }
    assert "Địa giới phường hiện hành" in {
        item.label for item in current.legend
    }


def test_scene_label_policy_keeps_primary_labels_and_blocks_lower_priority_overlap(
    sample_layers,
):
    legacy = build_scene(sample_layers, "legacy")
    primary = [label for label in legacy.labels if label.priority == 1]

    assert len(primary) == 14
    assert all(label.font_role == "semibold" for label in primary)
    assert all(
        not lower.overlaps(higher)
        for lower in legacy.labels
        for higher in legacy.labels
        if higher.priority < lower.priority
    )
    lower_priority = [label for label in legacy.labels if label.priority > 1]
    assert all(
        not first.overlaps(second)
        for index, first in enumerate(lower_priority)
        for second in lower_priority[index + 1 :]
        if first.priority == second.priority
    )


def test_svg_is_vector_layered_and_text_editable(
    tmp_path, legacy_scene, test_fonts
):
    output = render_svg(legacy_scene, tmp_path / "map.svg", test_fonts)
    root = ElementTree.parse(output).getroot()

    assert not root.findall(".//svg:image", SVG_NS)
    assert root.findall(".//svg:text", SVG_NS)
    layer_ids = {
        node.attrib["id"]
        for node in root.findall(".//svg:g", SVG_NS)
        if "id" in node.attrib
    }
    assert set(MAP_LAYER_IDS) <= layer_ids
    assert b"font-family:Poppins" in output.read_bytes()
    assert "14 điểm tham chiếu" in "".join(root.itertext())


def test_pdf_is_landscape_a0_vector_with_embedded_poppins(
    tmp_path, legacy_scene, test_fonts
):
    output = render_pdf(legacy_scene, tmp_path / "map.pdf", test_fonts)

    with pdfplumber.open(output) as pdf:
        assert len(pdf.pages) == 1
        assert pdf.pages[0].images == []
        assert sorted(round(float(value)) for value in pdf.pages[0].mediabox[2:]) == [
            2384,
            3370,
        ]
        assert pdf.pages[0].chars
        extracted = pdf.pages[0].extract_text() or ""
        assert "14" in extracted
        assert "\x00" not in extracted
    raw = output.read_bytes()
    assert b"/FontFile2" in raw
    assert b"/Subtype /Image" not in raw


def test_kml_legacy_contains_14_geographic_points_without_boundary_polygons(
    tmp_path, sample_layers
):
    output = render_kml(sample_layers, "legacy", tmp_path / "map.kml")
    root = ElementTree.parse(output).getroot()

    assert root.findall(".//kml:Placemark", KML_NS)
    assert len(root.findall(".//kml:Point", KML_NS)) == 16
    assert not root.findall(".//kml:Polygon", KML_NS)
    assert not root.findall(".//kml:ScreenOverlay", KML_NS)
    assert b"watermark" not in output.read_bytes().lower()
    legacy_folder = next(
        folder
        for folder in root.findall(".//kml:Folder", KML_NS)
        if folder.findtext("kml:name", namespaces=KML_NS)
        == "legacy-reference-centers"
    )
    legacy_points = legacy_folder.findall(".//kml:Point", KML_NS)
    assert len(legacy_points) == 14
    values = [
        node.text
        for node in legacy_folder.findall(
            ".//kml:ExtendedData/kml:Data[@name='boundary_claim']/kml:value",
            KML_NS,
        )
    ]
    assert values == ["false"] * 14


def test_kml_current_contains_exactly_five_administrative_boundaries(
    tmp_path, sample_layers
):
    output = render_kml(sample_layers, "current", tmp_path / "map.kml")
    root = ElementTree.parse(output).getroot()
    boundary_folder = next(
        folder
        for folder in root.findall(".//kml:Folder", KML_NS)
        if folder.findtext("kml:name", namespaces=KML_NS) == "boundaries"
    )

    assert len(boundary_folder.findall(".//kml:Polygon", KML_NS)) == 5
    assert not any(
        folder.findtext("kml:name", namespaces=KML_NS)
        == "legacy-reference-centers"
        for folder in root.findall(".//kml:Folder", KML_NS)
    )


def test_product_render_stage_writes_six_edition_format_outputs(
    tmp_path, sample_layers, test_fonts
):
    from scripts.build_thu_dau_mot_map_product import render_product_outputs

    outputs = render_product_outputs(
        sample_layers,
        tmp_path,
        test_fonts,
    )

    assert {path.name for path in outputs} == {
        "thu-dau-mot-current.kml",
        "thu-dau-mot-current.pdf",
        "thu-dau-mot-current.svg",
        "thu-dau-mot-legacy.kml",
        "thu-dau-mot-legacy.pdf",
        "thu-dau-mot-legacy.svg",
    }
    assert all(path.is_file() and path.stat().st_size > 0 for path in outputs)
